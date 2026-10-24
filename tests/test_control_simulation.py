import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('control_simulation', ROOT / 'apps/g1_control_test.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ControlSimulationTests(unittest.TestCase):
    def test_import_does_not_load_simulator_or_sdk(self):
        script = "import importlib.util,sys; s=importlib.util.spec_from_file_location('control',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); assert 'mujoco' not in sys.modules; assert not any(n.startswith('unitree_sdk2py') for n in sys.modules)"
        subprocess.run([str(ROOT / '.venv-g1/bin/python'), '-c', script, str(ROOT / 'apps/g1_control_test.py')], check=True)

    def test_every_alias_uses_the_same_parser_and_rejects_negation(self):
        for action, phrases in m.ALIASES.items():
            for phrase in phrases:
                self.assertEqual(action, m.interpret_command('G1, ' + phrase + '!'))
        self.assertIsNone(m.interpret_command("don't wave"))
        self.assertIsNone(m.interpret_command('wave then clap'))
        self.assertEqual('unsupported', m.interpret_command('jump'))

    def test_all_motion_paths_stay_in_limits_and_return_to_rest(self):
        import numpy as np
        g = m.Gestures()
        actions = [a for a in m.ALIASES if a not in ('greet', 'help', 'quit', 'stop', 'release arm', *m.SPEECH_RESPONSES)]
        with contextlib.redirect_stdout(io.StringIO()):
            for action in actions:
                g.start(action, 0)
                frames = []
                for t in np.linspace(0, 6.7, 671):
                    g.update(t)
                    frames.append(g.data.qpos.copy())
                    for address, lower, upper in g.joints.values():
                        self.assertGreaterEqual(g.data.qpos[address], lower - 1e-9, action)
                        self.assertLessEqual(g.data.qpos[address], upper + 1e-9, action)
                self.assertTrue(np.allclose(g.data.qpos, g.rest), action)
                self.assertLess(np.max(np.abs(np.diff(frames, axis=0))), .06, action)

    def test_greeting_starts_speech_and_arm_together_and_rejects_repeats(self):
        g = Mock(action=None)
        speaker = Mock()
        speaker.is_speaking.return_value = False
        speaker.speak.return_value = True
        self.assertTrue(m.begin_greeting(g, speaker, 100, 'Custom introduction'))
        speaker.speak.assert_called_once_with('Custom introduction')
        g.start.assert_called_once_with('wave', 99)
        g.update.assert_called_once_with(100)
        g.action = 'wave'
        self.assertFalse(m.begin_greeting(g, speaker, 101))
        self.assertEqual(1, speaker.speak.call_count)

    def test_stop_preserves_position_after_walking(self):
        import numpy as np
        g = m.Gestures()
        with contextlib.redirect_stdout(io.StringIO()):
            g.start('walk', 0)
            for t in np.linspace(0, 2, 201): g.update(t)
            location = g.data.qpos[:7].copy()
            before = g.data.qpos.copy()
            g.start('stop', 2)
            g.update(2)
            self.assertTrue(np.allclose(before, g.data.qpos))
            g.update(3.2)
        self.assertTrue(np.allclose(g.data.qpos[:7], location))
        self.assertTrue(np.allclose(g.data.qpos, g.rest))


if __name__ == '__main__':
    unittest.main()
