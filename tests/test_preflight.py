import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PreflightTests(unittest.TestCase):
    def test_failure_blocks_launch(self):
        launcher = load('checked_launcher', 'launch.py')
        checks = types.SimpleNamespace(run_checks=lambda *args: False)
        with patch.dict(sys.modules, {'preflight': checks}), patch.object(sys, 'argv', ['launch.py', 'hardware', '--interface', 'test', '--arm']), patch.object(launcher.subprocess, 'call') as call:
            self.assertEqual(1, launcher.main())
            call.assert_not_called()

    def test_success_allows_launch(self):
        launcher = load('checked_launcher', 'launch.py')
        checks = types.SimpleNamespace(run_checks=lambda *args: True)
        with patch.dict(sys.modules, {'preflight': checks}), patch.object(sys, 'argv', ['launch.py', 'control']), patch.object(launcher.subprocess, 'call', return_value=0) as call:
            self.assertEqual(0, launcher.main())
            call.assert_called_once()

    def test_worker_failure_cannot_report_ready(self):
        checks = load('readiness_checks', 'preflight.py')
        result = types.SimpleNamespace(stdout='G1_PREFLIGHT_RESULT=[{"status":"FAIL","check":"network","detail":"offline"}]', stderr='', returncode=1)
        with patch.object(checks.subprocess, 'run', return_value=result):
            self.assertFalse(checks.run_checks('hardware', ['--interface', 'test']))

    def test_malformed_worker_output_fails(self):
        checks = load('readiness_checks', 'preflight.py')
        result = types.SimpleNamespace(stdout='', stderr='worker crashed', returncode=1)
        with patch.object(checks.subprocess, 'run', return_value=result):
            self.assertFalse(checks.run_checks('control'))


if __name__ == '__main__':
    unittest.main()
