import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SpeechTests(unittest.TestCase):
    def test_text_is_literal_argument(self):
        module = load('speech', 'apps/g1_control_test.py')
        text = 'Hello; $(echo example)'
        with patch.object(module.shutil, 'which', return_value='/usr/bin/say'):
            self.assertEqual(['/usr/bin/say', '-r', '165', '--', text], module.speech_command(text))
            with self.assertRaises(ValueError):
                module.speech_command('')

    def test_missing_engine_reports_failure(self):
        module = load('speech', 'apps/g1_control_test.py')
        with patch.object(module.shutil, 'which', return_value=None):
            with self.assertRaises(RuntimeError):
                module.speech_command('Hello')

    def test_speech_and_gesture_phrases_are_distinct(self):
        module = load('simulator', 'apps/g1_control_test.py')
        self.assertEqual('speak hello', module.interpret_command('G1, say hello!'))
        self.assertEqual('wave', module.interpret_command('G1, wave hello!'))
        for action in module.SPEECH_RESPONSES:
            self.assertEqual(action, module.interpret_command(action))


if __name__ == '__main__':
    unittest.main()
