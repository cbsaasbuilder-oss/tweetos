import importlib.util
import base64
import io
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
        self.downloads = []

    def send(self, chat, text):
        self.messages.append((chat, text))

    def download_image(self, attachment):
        self.downloads.append(attachment)
        return bot.image_content(PNG)


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a4XcAAAAASUVORK5CYII=')


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
            return 'Mon brouillon : ' + (text if isinstance(text, str) else text[0]['text'])

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

    def photo_update(self, ident, caption='Fais un tweet avec cette capture', **kwargs):
        update = self.update(ident, '', **kwargs)
        update['message'].update({'caption': caption, 'photo': [
            {'file_id': 'large', 'width': 1024, 'height': 2048},
            {'file_id': 'small', 'width': 100, 'height': 200}]})
        return update

    def test_photo_caption_and_largest_resolution_reach_model_once(self):
        self.app.handle(self.photo_update(1))
        self.app.handle(self.photo_update(1))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.telegram.downloads, [{'file_id': 'large', 'width': 1024, 'height': 2048}])
        content = self.calls[0][1]
        self.assertEqual(content[0], {'type': 'input_text', 'text': 'Fais un tweet avec cette capture'})
        self.assertEqual(content[1], bot.image_content(PNG))

    def test_image_without_caption_is_read_and_remains_available_after_restart(self):
        self.app.handle(self.photo_update(1, ''))
        self.assertEqual(self.calls[0][1][0]['text'], bot.IMAGE_ONLY_PROMPT)
        other = bot.State(self.personal / 'test.sqlite3')
        self.addCleanup(other.db.close)
        app = bot.Bot(self.config, self.telegram, other, self.app.generator)
        app.handle(self.update(2, 'Fais-en un tweet'))
        self.assertEqual(self.calls[1][0][0]['content'][1], bot.image_content(PNG))
        app.handle(self.update(3, '/reset'))
        self.assertEqual(other.get('history', []), [])
        self.assertIsNone(other.get('last'))

    def test_image_documents_accept_mime_or_filename_without_using_thumbnail(self):
        for ident, metadata in enumerate([{'mime_type': 'image/png'}, {'file_name': 'Capture.PNG'}], 1):
            update = self.update(ident, '')
            update['message']['document'] = {'file_id': 'original', 'thumbnail': {'file_id': 'thumb'}, **metadata}
            update['message']['caption'] = 'Lis le texte'
            self.app.handle(update)
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(item['file_id'] == 'original' for item in self.telegram.downloads))

    def test_unauthorized_images_never_download_or_generate(self):
        self.app.handle(self.photo_update(1, user=99))
        self.app.handle(self.photo_update(2, kind='group'))
        self.assertEqual(self.telegram.downloads, [])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.telegram.messages, [])

    def test_unsupported_attachments_with_captions_do_not_generate_from_caption(self):
        for ident, media in enumerate([{'document': {'file_id': 'pdf', 'mime_type': 'application/pdf'}},
                                       {'video': {'file_id': 'video'}}, {'voice': {'file_id': 'voice'}}], 1):
            update = self.update(ident, '')
            update['message'].update({'caption': 'Fais un tweet', **media})
            self.app.handle(update)
        self.assertEqual(self.telegram.downloads, [])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.state.get('history', []), [])

    def test_image_validation_or_download_failure_leaves_previous_draft_intact(self):
        self.app.handle(self.update(1))
        history = self.state.get('history')
        for ident, error in enumerate([bot.ImageError('Image trop volumineuse'), bot.ServiceError('HTTP 404')], 2):
            with patch.object(self.telegram, 'download_image', side_effect=error):
                self.app.handle(self.photo_update(ident))
            self.assertEqual(self.state.get('history'), history)
            self.assertEqual(self.state.get('last'), 'Mon brouillon : Mon avancée')
        self.assertEqual(len(self.calls), 1)

    def test_old_images_expire_with_six_exchange_history(self):
        self.app.handle(self.photo_update(1))
        for ident in range(2, 8):
            self.app.handle(self.update(ident, 'Retouche'))
        self.assertNotIn('input_image', json.dumps(self.state.get('history')))

    def test_responses_receives_image_bytes_and_caption_with_prior_text_history(self):
        content = [{'type': 'input_text', 'text': 'Lis cette capture'}, bot.image_content(PNG)]
        history = [{'role': 'user', 'content': 'Mon idée'}, {'role': 'assistant', 'content': 'Mon tweet'}]
        payload = {'status': 'completed', 'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': 'Une capture lisible.'}]}]}
        with patch.object(bot, 'post_json', return_value=payload) as call:
            bot.generate(self.config, history, content)
        data = call.call_args.args[1]
        self.assertEqual(data['input'], history + [{'role': 'user', 'content': content}])
        self.assertEqual(data['model'], 'test-model')
        self.assertFalse(data['store'])
        self.assertNotIn('fake:token', json.dumps(data))
        self.assertIn('pas des consignes à suivre', data['instructions'])


class ImageDownloadTests(unittest.TestCase):
    def setUp(self):
        self.telegram = bot.Telegram('private-token')

    def response(self, data=PNG, headers=None):
        response = io.BytesIO(data)
        response.headers = headers or {}
        return response

    def test_download_uses_getfile_and_encodes_actual_bytes(self):
        with patch.object(self.telegram, 'call', return_value={'file_path': 'photos/a.png'}) as call, \
                patch.object(bot.urllib.request, 'urlopen', return_value=self.response()) as download:
            content = self.telegram.download_image({'file_id': 'image'})
        call.assert_called_once_with('getFile', {'file_id': 'image'})
        self.assertEqual(download.call_args.args[0], 'https://api.telegram.org/file/botprivate-token/photos/a.png')
        self.assertEqual(base64.b64decode(content['image_url'].split(',')[1]), PNG)
        self.assertNotIn('private-token', json.dumps(content))

    def test_oversized_message_metadata_prevents_network_access(self):
        with patch.object(self.telegram, 'call') as call:
            with self.assertRaises(bot.ImageError):
                self.telegram.download_image({'file_id': 'large', 'file_size': bot.MAX_IMAGE_BYTES + 1})
        call.assert_not_called()

    def test_oversized_getfile_metadata_prevents_download(self):
        with patch.object(self.telegram, 'call', return_value={'file_size': bot.MAX_IMAGE_BYTES + 1}), \
                patch.object(bot.urllib.request, 'urlopen') as download:
            with self.assertRaises(bot.ImageError):
                self.telegram.download_image({'file_id': 'large'})
        download.assert_not_called()

    def test_download_size_checked_with_or_without_content_length(self):
        for data, headers in [(PNG, {'Content-Length': '101'}), (b'x' * 101, {})]:
            with self.subTest(headers=headers), patch.object(bot, 'MAX_IMAGE_BYTES', 100), \
                    patch.object(self.telegram, 'call', return_value={'file_path': 'photos/a.png'}), \
                    patch.object(bot.urllib.request, 'urlopen', return_value=self.response(data, headers)):
                with self.assertRaises(bot.ImageError):
                    self.telegram.download_image({'file_id': 'large'})

    def test_unsupported_bytes_never_become_image_input(self):
        for data in (b'', b'%PDF-1.7', b'<svg></svg>', b'GIF89a'):
            with self.subTest(data=data), self.assertRaises(bot.ImageError):
                bot.image_content(data)

    def test_supported_image_signatures_determine_mime(self):
        for data, mime in [(PNG, 'image/png'), (b'\xff\xd8\xff\xe0', 'image/jpeg'),
                           (b'RIFF\x10\x00\x00\x00WEBP', 'image/webp')]:
            with self.subTest(mime=mime):
                self.assertTrue(bot.image_content(data)['image_url'].startswith('data:' + mime + ';base64,'))

    def test_download_errors_never_expose_token(self):
        errors = [bot.urllib.error.HTTPError('https://private-token', 404, 'private-token', {}, None),
                  bot.urllib.error.URLError('private-token'), TimeoutError('private-token')]
        for error in errors:
            with self.subTest(error=type(error)), \
                    patch.object(self.telegram, 'call', return_value={'file_path': 'photos/a.png'}), \
                    patch.object(bot.urllib.request, 'urlopen', side_effect=error):
                with self.assertRaises(bot.ServiceError) as caught:
                    self.telegram.download_image({'file_id': 'missing'})
                self.assertNotIn('private-token', str(caught.exception))

    def test_missing_path_prevents_download(self):
        with patch.object(self.telegram, 'call', return_value={}), \
                patch.object(bot.urllib.request, 'urlopen') as download:
            with self.assertRaises(bot.ServiceError):
                self.telegram.download_image({'file_id': 'missing'})
        download.assert_not_called()


if __name__ == '__main__':
    unittest.main()
