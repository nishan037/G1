import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('deployment',ROOT / 'apps/g1_control.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class DeploymentAudioTests(unittest.TestCase):
    def test_tts_unique_indexes_and_no_volume_or_motion_writes(self):
        client=Mock();client._Call.return_value=(0,None)
        speaker=m.RobotSpeaker(client,1)
        self.assertTrue(speaker.speak('Hello'))
        self.assertFalse(speaker.speak('Busy'))
        speaker.busy_until=0
        self.assertTrue(speaker.speak('Welcome'))
        calls=client._Call.call_args_list
        self.assertEqual([1,2],[json.loads(c.args[1])['index'] for c in calls])
        self.assertTrue(all(c.args[0]==1001 for c in calls))
        self.assertEqual(1,json.loads(calls[0].args[1])['speaker_id'])
        client.SetVolume.assert_not_called()

    def test_failed_robot_tts_is_reported_without_local_fallback(self):
        client=Mock();client._Call.return_value=(123,None)
        with self.assertRaises(RuntimeError):m.RobotSpeaker(client).speak('Hello')

    def test_read_only_probe_queries_audio_without_tts(self):
        client=Mock();controller=Mock();sub=Mock()
        args=types.SimpleNamespace(interface='test',enable_walking=False,speaker='robot',mute=False,arm=False,list=False)
        with patch.object(m,'connect',return_value=(controller,sub)),patch.object(m,'connect_audio',return_value=client) as audio:
            m.run_hardware(args)
        audio.assert_called_once_with('test')
        client._Call.assert_not_called();controller.command.assert_not_called();controller.stop.assert_not_called()
        sub.Close.assert_called_once()

    def test_robot_microphone_probe_discards_pcm(self):
        sock=Mock();sock.__enter__=Mock(return_value=sock);sock.__exit__=Mock(return_value=False)
        sock.recv.return_value=b'\0\0'*80
        with patch.object(m,'robot_microphone_socket',return_value=sock):
            self.assertIn('discarded',m.check_robot_microphone('192.168.123.100'))
        sock.recv.return_value=b'\0'
        with patch.object(m,'robot_microphone_socket',return_value=sock):
            with self.assertRaises(RuntimeError):m.check_robot_microphone('192.168.123.100')

    def test_probe_and_arm_are_mutually_exclusive(self):
        with patch.object(sys,'argv',['g1_control.py','--interface','test','--probe','--arm']):
            with self.assertRaises(SystemExit) as exc:m.main()
        self.assertEqual(2,exc.exception.code)

    def test_pc_control_refuses_hardware(self):
        spec=importlib.util.spec_from_file_location('pc_control',ROOT / 'apps/g1_control_test.py')
        pc=importlib.util.module_from_spec(spec);spec.loader.exec_module(pc)
        with patch.object(sys,'argv',['g1_control_test.py','--hardware','--interface','test','--arm']),patch.object(pc,'connect') as connect:
            with self.assertRaises(SystemExit):pc.main()
            connect.assert_not_called()

if __name__=='__main__':unittest.main()
