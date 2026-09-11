import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('archive_tweets',
    Path(__file__).resolve().parents[1] / 'scripts/archive_tweets.py')
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


class ArchiveAccountTests(unittest.TestCase):
    def test_account_is_verified_before_replacing_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'tweets.zip'
            with zipfile.ZipFile(source, 'w') as out:
                out.writestr('data/account.js', 'window.YTD.account.part0 = ' +
                    json.dumps([{'account': {'username': 'builder_test'}}]))
                out.writestr('data/tweets.js', 'window.YTD.tweets.part0 = ' +
                    json.dumps([{'tweet': {'id_str': '123', 'full_text': 'Un vrai tweet'}}]))
            target = root / 'history'
            target.mkdir()
            corpus = target / 'tweets.jsonl'
            corpus.write_text('previous history', encoding='utf-8')
            args = argparse.Namespace(archive=str(source), output=str(target), account='wrong_user')
            with self.assertRaises(ValueError):
                archive.import_archive(args)
            self.assertEqual(corpus.read_text(), 'previous history')
            args.account = '@BUILDER_TEST'
            with patch('builtins.print'):
                archive.import_archive(args)
            summary = json.loads((target / 'corpus-summary.json').read_text())
            self.assertTrue(summary['account_verified'])
            self.assertEqual(summary['account'], 'BUILDER_TEST')
            self.assertEqual(json.loads(corpus.read_text())['text'], 'Un vrai tweet')
