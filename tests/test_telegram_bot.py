import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('telegram_bot', ROOT / 'scripts/telegram_bot.py')
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)


class TelegramFake:
    def __init__(self):
        self.messages = []

    def send(self, chat, text):
        self.messages.append((chat, text))


class BotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.personal = Path(self.tmp.name)
        self.config = bot.Config({'TELEGRAM_BOT_TOKEN': 'fake:token', 'OPENAI_API_KEY': 'fake-key',
                                 'OPENAI_MODEL': 'test-model', 'TELEGRAM_ALLOWED_USER_ID': '42',
                                 'TWEETOS_PERSONAL_DIR': str(self.personal)})
        self.state = bot.State(self.personal / 'test.sqlite3')
        self.addCleanup(self.state.db.close)
        self.telegram = TelegramFake()
        self.calls = []

        def generator(config, history, text):
            self.calls.append((history, text))
            return 'Mon brouillon : ' + text

        self.app = bot.Bot(self.config, self.telegram, self.state, generator)

    def update(self, ident, text='Mon avancée', user=42, kind='private'):
        return {'update_id': ident, 'message': {'from': {'id': user},
                'chat': {'id': user, 'type': kind}, 'text': text}}

    def test_other_users_and_groups_never_generate_or_receive(self):
        self.app.handle(self.update(1, user=99))
        self.app.handle(self.update(2, kind='group'))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.telegram.messages, [])

    def test_duplicate_update_is_not_billed_twice_and_context_is_used(self):
        self.app.handle(self.update(1))
        self.app.handle(self.update(1))
        self.app.handle(self.update(2, 'Plus court'))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[1][0][0]['content'], 'Mon avancée')
        self.assertEqual(self.state.get('offset'), 3)

    def test_checkpoint_survives_restart(self):
        self.app.handle(self.update(7))
        other = bot.State(self.personal / 'test.sqlite3')
        self.addCleanup(other.db.close)
        bot.Bot(self.config, self.telegram, other, self.app.generator).handle(self.update(7))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(other.get('last'), 'Mon brouillon : Mon avancée')

    def test_failed_delivery_draft_is_available_without_regenerating(self):
        with patch.object(self.telegram, 'send', side_effect=bot.ServiceError('network')):
            self.app.handle(self.update(1))
        self.app.handle(self.update(2, '/last'))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.telegram.messages[-1][1], 'Mon brouillon : Mon avancée')

    def test_reset_preserves_offset_but_clears_context(self):
        self.app.handle(self.update(1))
        self.app.handle(self.update(2, '/reset'))
        self.assertEqual(self.state.get('history', []), [])
        self.assertIsNone(self.state.get('last'))
        self.assertEqual(self.state.get('offset'), 3)

    def test_api_failure_and_attachments_do_not_pollute_history(self):
        with patch.object(self.app, 'generator', side_effect=bot.ServiceError('HTTP 429')):
            self.app.handle(self.update(1))
        self.app.handle(self.update(2, ''))
        self.assertEqual(self.state.get('history', []), [])
        self.assertIn('texte', self.telegram.messages[-1][1])

    def test_history_keeps_only_six_exchanges(self):
        for ident in range(1, 10):
            self.app.handle(self.update(ident, str(ident)))
        self.assertEqual(len(self.state.get('history')), 12)
        self.assertEqual(self.state.get('history')[0]['content'], '4')

    def test_responses_request_includes_rules_profile_and_relevant_examples(self):
        (self.personal / 'style.md').write_text('Phrases courtes et concrètes.', encoding='utf-8')
        (self.personal / 'tweets.jsonl').write_text(json.dumps({'id':'1','text':'Développement rapide',
            'kind':'post','created_at':'2024-01-01'})+'\n', encoding='utf-8')
        payload = {'status':'completed','output':[{'type':'message','content':[
            {'type':'output_text','text':'J’ai livré l’app.'}]}]}
        with patch.object(bot, 'post_json', return_value=payload) as call:
            self.assertEqual(bot.generate(self.config, [], 'développement'), "J'ai livré l'app.")
        data = call.call_args.args[1]
        self.assertFalse(data['store'])
        self.assertIn('Phrases courtes et concrètes.', data['instructions'])
        self.assertIn('RÈGLES ÉDITORIALES', data['instructions'])
        self.assertIn('Développement rapide', data['input'][0]['content'])
        self.assertEqual(data['input'][-1]['content'], 'développement')

    def test_incomplete_response_is_not_delivered_as_finished(self):
        with patch.object(bot, 'post_json', return_value={'status':'incomplete','output':[]}):
            with self.assertRaises(bot.ServiceError):
                bot.generate(self.config, [], 'Mon avancée')

    def test_configured_account_and_custom_history_are_used(self):
        self.config.x_account = 'builder_test'
        (self.personal / 'style.md').write_text('Mon style de test.', encoding='utf-8')
        (self.personal / 'corpus-summary.json').write_text(json.dumps({
            'account': 'builder_test', 'source': '/private/archive.zip',
            'limitations': ['Echantillon public uniquement.']}), encoding='utf-8')
        prompt = bot.instructions(self.config.personal_dir, self.config.x_account)
        self.assertIn('@builder_test', prompt)
        self.assertIn('Mon style de test.', prompt)
        self.assertIn('Echantillon public uniquement.', prompt)
        self.assertNotIn('/private/archive.zip', prompt)
        self.assertNotIn('nightdev_saas', prompt)

    def test_wrong_account_corpus_never_reaches_openai(self):
        self.config.x_account = 'builder_test'
        (self.personal / 'corpus-summary.json').write_text(
            json.dumps({'account': 'different_user'}), encoding='utf-8')
        with patch.object(bot, 'post_json') as call:
            with self.assertRaises(bot.ServiceError):
                bot.generate(self.config, [], 'Mon idee')
        call.assert_not_called()

    def test_profile_switch_clears_conversation_but_keeps_offset(self):
        self.state.select_profile('first_user', self.personal)
        self.app.handle(self.update(17))
        self.state.select_profile('first_user', self.personal)
        self.assertTrue(self.state.get('history'))
        self.state.select_profile('second_user', self.personal)
        self.assertEqual(self.state.get('history', []), [])
        self.assertIsNone(self.state.get('last'))
        self.assertEqual(self.state.get('offset'), 18)

    def test_long_emoji_messages_are_split_without_loss(self):
        telegram = bot.Telegram('fake:token')
        text = '🛠' * 5000 + ' J’ai livré l’app.'
        with patch.object(telegram, 'call') as call:
            telegram.send(42, text)
        parts = [c.args[1]['text'] for c in call.call_args_list]
        self.assertEqual(''.join(parts), text.replace('’', "'"))
        self.assertTrue(all(len(p.encode('utf-16-le')) // 2 <= 4096 for p in parts))


if __name__ == '__main__':
    unittest.main()
