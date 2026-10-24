import importlib.util, unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('bridge',Path(__file__).resolve().parents[1] / 'apps/g1_control.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
class Client:
 def __init__(self):self.calls=[];self.code=0
 def ExecuteAction(self,i):self.calls.append(('arm',i));return self.code
 def SetVelocity(self,*v):self.calls.append(('velocity',*v));return self.code
class Tests(unittest.TestCase):
 def setup_controller(self,walk=False):
  self.arm=Client();self.loco=Client();self.stamp=10
  self.c=b.Hardware(self.arm,self.loco,{'high wave':26,'release arm':99},lambda:self.stamp,walk)
 def test_discovery(self):
  known={'high wave':26,'release arm':99}
  for data in ([[{'id':26,'name':'high_wave'},{'id':99,'name':'release_arm'}],[]], {'high wave':26,'release arm':99}, {'data':'[{"name":"high wave","id":26}]'}):
   self.assertIn('high wave',b.discover_actions(data,known))
  self.assertEqual({},b.discover_actions([{'id':99,'name':'high wave'},{'id':123,'name':'custom'}],known))
 def test_disabled_and_unsupported(self):
  self.setup_controller();self.c.command('walk',10);self.c.command('both wave',10)
  self.assertEqual([],self.arm.calls+self.loco.calls)
 def test_gesture_release_and_busy(self):
  self.setup_controller();self.c.command('wave',10);self.c.command('wave',10)
  self.assertEqual([('arm',26)],self.arm.calls)
  self.stamp=13;self.c.tick(13)
  self.assertEqual(('arm',99),self.arm.calls[-1]);self.assertFalse(self.c.arm_until)
 def test_walk_bounded_and_stop(self):
  self.setup_controller(True);self.c.command('walk',10)
  self.assertEqual(('velocity',.1,0.,0.,.4),self.loco.calls[-1])
  self.stamp=11.01;self.c.tick(11.01)
  self.assertEqual(('velocity',0.,0.,0.,.4),self.loco.calls[-1]);self.assertFalse(self.c.moving_until)
 def test_stale_and_rpc_failure(self):
  self.setup_controller(True);self.c.command('walk',10);self.c.tick(11.1)
  self.assertTrue(self.c.fault);self.assertEqual(0.,self.loco.calls[-1][1])
  before=len(self.arm.calls);self.c.command('wave',11.1);self.assertEqual(before,len(self.arm.calls))
  self.setup_controller();self.arm.code=7;self.c.command('wave',10);self.assertTrue(self.c.fault)
 def test_probe_no_writes(self):
  self.setup_controller()
  class Sub:
   def Close(self):pass
  class Args:interface='test';enable_walking=False;arm=False;list=False;speaker='none';mute=True
  with patch.object(b,'connect',return_value=(self.c,Sub())):b.run_hardware(Args())
  self.assertEqual([],self.arm.calls+self.loco.calls)
 def test_deployment_module_has_no_simulator(self):
  self.assertFalse(hasattr(b,'Gestures'))
if __name__=='__main__':unittest.main()
