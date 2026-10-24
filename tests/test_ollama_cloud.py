import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cloud', ROOT / 'apps/g1_conversation.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class CloudTests(unittest.TestCase):
    def test_environment_key_overrides_saved_configuration(self):
        with patch.dict(os.environ, {'OLLAMA_API_KEY': 'unit-test-override'}):
            self.assertEqual('unit-test-override', m.OllamaCloud().key)

    def test_chat_history_is_bounded_and_text_not_executed(self):
        with patch.dict(os.environ, {'OLLAMA_API_KEY': 'test-private-key'}):
            client = m.OllamaCloud()
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b'{"message":{"content":"Hello!"}}'
        history = [{'role':'user','content':str(i)} for i in range(30)]
        with patch.object(m.urllib.request, 'build_opener', return_value=opener):
            self.assertEqual('Hello!', client.reply('Tell me a joke', history))
        request = opener.open.call_args.args[0]
        body = json.loads(request.data)
        self.assertEqual('https://ollama.com/api/chat', request.full_url)
        self.assertEqual(18, len(body['messages']))
        self.assertFalse(body['stream'])
        self.assertNotIn('test-private-key', json.dumps(body))
        self.assertEqual(30, len(history))

    def test_error_does_not_expose_server_body_or_key(self):
        with patch.dict(os.environ, {'OLLAMA_API_KEY': 'private-test-key'}): client = m.OllamaCloud()
        opener = MagicMock()
        opener.open.side_effect = urllib.error.HTTPError('https://ollama.com',401,'error',{},io.BytesIO(b'private-test-key'))
        with patch.object(m.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(m.CloudError) as exc: client.reply('hello')
        self.assertNotIn('private-test-key', str(exc.exception))
        self.assertIn('key rejected', str(exc.exception))

    def test_redirect_refused(self):
        self.assertIsNone(m.NoRedirect().redirect_request(None,None,302,'',{},'https://example.com'))

    def test_empty_reply_rejected(self):
        with patch.dict(os.environ, {'OLLAMA_API_KEY': 'test'}): client = m.OllamaCloud()
        with patch.object(client,'_request',return_value={'message':{'content':''}}):
            with self.assertRaises(m.CloudError): client.reply('Hello')


if __name__ == '__main__': unittest.main()
