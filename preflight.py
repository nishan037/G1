"""Read-only readiness checks. No robot motion, TTS, volume, or LED writes."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
ROOT = Path(__file__).resolve().parent
TARGETS = ('control-test','conversation-test','control','hardware','conversation','vision')
RESULT_PREFIX = 'G1_PREFLIGHT_RESULT='


def load_app(name):
    spec = importlib.util.spec_from_file_location('preflight_' + name, ROOT / 'apps' / (name + '.py'))
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def worker(args):
    rows = []
    def check(label, fn):
        try:
            detail = fn();rows.append({'status':'PASS','check':label,'detail':str(detail or 'OK')});return True
        except Exception as exc:
            rows.append({'status':'FAIL','check':label,'detail':str(exc)});return False
    def skip(label, why): rows.append({'status':'SKIP','check':label,'detail':why})
    def require(path):
        if not path.exists(): raise RuntimeError(f'Missing {path}')
        return path
    target = 'control' if args.target == 'hardware' else args.target
    pc = target.endswith('-test')
    physical_control = target == 'control'
    physical_chat = target == 'conversation'
    graphics = target == 'control-test'
    readonly_control = physical_control and (not args.arm or args.probe or args.say)
    speech = not args.no_voice and target != 'vision' and not readonly_control and not args.probe
    speaker = ('local' if pc else 'robot') if args.speaker is None else args.speaker
    muted = args.mute or speaker == 'none'
    check('Python environment', lambda:f'{sys.executable} (Python {sys.version.split()[0]})')
    script = {'control-test':'g1_control_test','conversation-test':'g1_conversation_test','control':'g1_control','conversation':'g1_conversation'}.get(target)
    if script: check('Application file', lambda:require(ROOT / 'apps' / (script + '.py')))
    modules = ['mujoco','numpy'] if graphics else ['cv2','ultralytics'] if target == 'vision' else []
    if physical_control or (physical_chat and speaker == 'robot' and not muted):
        sys.path.insert(0,str(ROOT / 'unitree_sdk2_python'))
        modules += ['cyclonedds','unitree_sdk2py.core.channel']
    if speech: modules += ['vosk'] + (['sounddevice'] if args.mic == 'host' else [])
    packages_ok = check('Required packages', lambda:[__import__(name,fromlist=['*']).__name__ for name in modules])
    if not muted and speaker == 'local':
        def local_audio():
            import shutil
            if not shutil.which('say'): raise RuntimeError('macOS say not available; select robot speaker or --mute')
            return 'macOS say available; output volume/audibility not measured'
        check('Local speech output', local_audio)
    if graphics and packages_ok:
        def render():
            import mujoco
            path = require(ROOT / 'unitree_mujoco/unitree_robots/g1/scene_23dof.xml')
            m=mujoco.MjModel.from_xml_path(str(path));d=mujoco.MjData(m)
            mujoco.mj_resetDataKeyframe(m,d,0);mujoco.mj_forward(m,d)
            with mujoco.Renderer(m,height=64,width=64) as renderer:
                renderer.update_scene(d);renderer.render()
            require(ROOT / '.venv-g1/bin/mjpython')
            return 'G1 model loaded and test frame rendered'
        check('G1 simulation graphics',render)
    else: skip('Simulation graphics','Not required or packages unavailable')
    if speech and packages_ok:
        def model():
            from vosk import Model,SetLogLevel
            SetLogLevel(-1);Model(str(require(ROOT / 'models/speech/vosk-model-small-en-us-0.15')))
            return 'Offline recognition model loaded'
        check('Speech model',model)
    microphone_needed = (speech or args.probe) and not args.no_voice and target != 'vision'
    if microphone_needed and packages_ok:
        if args.mic == 'robot':
            check('Robot microphone stream',lambda:load_app('g1_control').check_robot_microphone(args.interface_ip))
        else:
            def host_mic():
                import sounddevice as sd
                device=int(args.device) if args.device and args.device.isdigit() else args.device
                info=sd.query_devices(device,'input');rate=int(info['default_samplerate'])
                with sd.RawInputStream(device=device,samplerate=rate,channels=1,dtype='int16') as stream:
                    data,_=stream.read(rate//10)
                    if not len(data): raise RuntimeError('No microphone samples')
                return info['name'] + '; samples discarded'
            check('Host microphone',host_mic)
    else: skip('Microphone','Disabled or not needed for read-only action discovery')
    if physical_control and not args.say:
        def actions():
            module=load_app('g1_control');controller,sub=module.connect(args.interface,args.enable_walking)
            try:
                if not controller.healthy(time.monotonic()): raise RuntimeError('State stream stale during discovery')
                if not controller.actions: raise RuntimeError('No supported presets matched the robot action list')
                if args.arm and 'release arm' not in controller.actions: raise RuntimeError('Release-arm action required')
                return f'Live G1 state and {len(controller.actions)} matched presets; no motion sent'
            finally: sub.Close()
        check('PC-to-G1 state/action services',actions)
    if (physical_control or physical_chat) and speaker == 'robot' and not muted:
        def robot_audio():
            load_app('g1_control').connect_audio(args.interface)
            return 'Audio GetVolume succeeded; no speech/volume change sent'
        check('G1 speaker service',robot_audio)
    if target in ('conversation','conversation-test'):
        check('Ollama cloud key/model/access',lambda:load_app(script).OllamaCloud(args.model).check())
    if target == 'vision' and packages_ok:
        def vision():
            from ultralytics import YOLO
            import cv2
            YOLO(str(require(ROOT / 'models/vision/yolo11n.pt')))
            cap=cv2.VideoCapture(0)
            try:
                ok,frame=cap.read()
                if not ok or frame is None: raise RuntimeError('Camera unavailable')
            finally: cap.release()
            return 'Weights loaded and camera frame received/discarded'
        check('Vision model/camera',vision)
    return rows


def add_options(parser):
    parser.add_argument('--interface');parser.add_argument('--interface-ip')
    parser.add_argument('--device');parser.add_argument('--model')
    parser.add_argument('--speaker',choices=('robot','local','none'))
    parser.add_argument('--speaker-id',type=int,default=1)
    parser.add_argument('--mic',choices=('host','robot'),default='host')
    parser.add_argument('--say')
    for name in ('no-voice','mute','arm','enable-walking','probe','hardware','list'):
        parser.add_argument('--'+name,action='store_true')


def run_checks(target,extra=()):
    parser=argparse.ArgumentParser(add_help=False);add_options(parser);flags,_=parser.parse_known_args(extra)
    effective='control' if target=='hardware' else target
    # PC test hardware compatibility uses production preflight, not graphics.
    if effective=='control-test' and flags.hardware: effective='control'
    runtime=ROOT / ('.venv/bin/python' if effective=='vision' else '.venv-g1/bin/python')
    rows=[];print(f'\nG1 PRE-FLIGHT — {effective}',flush=True)
    if not runtime.is_file():rows=[{'status':'FAIL','check':'Python runtime','detail':str(runtime)}]
    else:
        cmd=[str(runtime),str(ROOT / 'preflight.py'),'--worker','--target',effective]
        for name in ('interface','interface_ip','device','model','speaker','speaker_id','mic'):
            value=getattr(flags,name)
            if value is not None:cmd+=['--'+name.replace('_','-'),str(value)]
        if flags.say is not None: cmd+=['--say','preflight-only']
        for name in ('no_voice','mute','arm','enable_walking','probe'):
            if getattr(flags,name):cmd+=['--'+name.replace('_','-')]
        try:
            result=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True,timeout=45)
            line=next((s for s in reversed(result.stdout.splitlines()) if s.startswith(RESULT_PREFIX)),None)
            if not line:raise RuntimeError((result.stderr or result.stdout or f'Worker exited {result.returncode}')[-1600:])
            rows=json.loads(line[len(RESULT_PREFIX):])
        except Exception as exc: rows=[{'status':'FAIL','check':'Preflight execution','detail':str(exc)}]
    for row in rows:print(f'[{row["status"]}] {row["check"]}: {row["detail"]}',flush=True)
    ready=bool(rows) and not any(row['status']=='FAIL' for row in rows)
    print('READY — required checks passed.' if ready else 'NOT READY — fix failed checks before launch.',flush=True)
    print('Readiness does not validate physical motion, clearance, microphone accuracy, or audible robot TTS.\n',flush=True)
    return ready


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',choices=TARGETS,default='control-test')
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS);add_options(parser)
    args=parser.parse_args()
    if args.worker:
        rows=worker(args);print(RESULT_PREFIX+json.dumps(rows),flush=True)
        return int(any(row['status']=='FAIL' for row in rows))
    return int(not run_checks(args.target,sys.argv[1:]))

if __name__=='__main__':raise SystemExit(main())
