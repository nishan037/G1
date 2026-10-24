"""G1 voice/text control. Simulation by default; --hardware probes without moving.

Use launch.py control, or launch.py hardware --interface NAME [--arm].
All simulation poses are illustrative. Physical mode uses discovered SDK actions.
"""
import argparse
import json
import math
from pathlib import Path
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]

def speech_command(text):
    engine = shutil.which('say')
    if not engine:
        raise RuntimeError('macOS say is unavailable; local speech output requires macOS.')
    text = str(text).strip()
    if not text or len(text) > 2000:
        raise ValueError('Speech text must contain 1–2000 characters.')
    # Text is an argument, never shell code. -- also protects leading hyphens.
    return [engine, '-r', '165', '--', text]


class LocalSpeaker:
    def __init__(self):
        speech_command('ready')
        self.caption = ''
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._process = None
        self._pending = False
        self._generation = 0
        self._cooldown = 0.
        self._closed = False
        threading.Thread(target=self._worker, daemon=True).start()

    def is_speaking(self):
        with self._lock:
            return self._pending or time.monotonic() < self._cooldown

    def speak(self, text):
        command = speech_command(text)
        with self._lock:
            if self._closed or self._pending:
                return False
            self.caption = text
            self._pending = True
            self._queue.put((self._generation, command))
        print(f'G1 says: {text}', flush=True)
        return True

    def _worker(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            generation, command = item
            process = None
            try:
                with self._lock:
                    if self._closed or generation != self._generation:
                        continue
                    process = subprocess.Popen(command)
                    self._process = process
                code = process.wait(timeout=60)
                if code != 0:
                    print(f'Speech output exited with code {code}.', flush=True)
            except Exception as exc:
                if process and process.poll() is None:
                    process.terminate()
                print(f'Speech output unavailable: {exc}', flush=True)
            finally:
                with self._lock:
                    if generation == self._generation:
                        self._process = None
                        self._pending = False
                        self._cooldown = time.monotonic() + .6

    def stop(self):
        with self._lock:
            self._generation += 1
            self._pending = False
            self._cooldown = time.monotonic() + .6
            if self._process and self._process.poll() is None:
                self._process.terminate()
            self._process = None

    def close(self):
        self.stop()
        with self._lock:
            self._closed = True
        self._queue.put(None)


# Every action in the installed G1ArmActionClient.action_map is represented.
ALIASES = {
    'greet': ('greet', 'greet me', 'hello and wave', 'say hello and wave', 'introduce yourself and wave'),
    'wave': ('wave', 'wave hello', 'wave your hand'),
    'face wave': ('face wave', 'wave near your face'),
    'high wave': ('high wave', 'wave high'),
    'left wave': ('left wave', 'wave left', 'wave your left hand'),
    'both wave': ('both wave', 'wave both hands', 'wave with both hands'),
    'shake hand': ('shake hand', 'shake hands', 'handshake', 'give me a handshake'),
    'hands up': ('hands up', 'raise both hands', 'raise your hands'),
    'right hand up': ('right hand up', 'raise your right hand'),
    'clap': ('clap', 'clap your hands', 'applause'),
    'high five': ('high five', 'give me a high five'),
    'hug': ('hug', 'give me a hug', 'open your arms'),
    'heart': ('heart', 'make a heart', 'show a heart'),
    'right heart': ('right heart', 'make a right heart'),
    'reject': ('reject', 'say no', 'no thank you'),
    'x-ray': ('x ray', 'x-ray', 'cross your arms'),
    'two-hand kiss': ('two hand kiss', 'two-hand kiss', 'blow a kiss', 'blow a kiss with both hands'),
    'left kiss': ('left kiss', 'blow a left kiss'),
    'right kiss': ('right kiss', 'blow a right kiss'),
    'release arm': ('release arm', 'release arms', 'arms down', 'rest', 'resting pose', 'reset'),
    'stop': ('stop', 'stop now', 'cancel', 'stop moving'),
    'walk': ('walk', 'start walking', 'walk forward', 'move forward', 'go forward'),
    'walk backward': ('walk backward', 'walk backwards', 'move backward', 'go back'),
    'turn left': ('turn left',),
    'turn right': ('turn right',),
    'help': ('help', 'help me', 'show help', 'list commands', 'what can you do'),
    'speak hello': ('hello', 'say hello', 'speak hello'),
    'introduce yourself': ('introduce yourself', 'who are you', 'what is your name'),
    'say welcome': ('say welcome', 'welcome'),
    'say goodbye': ('say goodbye', 'goodbye'),
    'quit': ('quit', 'exit', 'close simulator'),
}
SPEECH_RESPONSES = {
    'speak hello': 'Hello! I am G one. Nice to meet you.',
    'introduce yourself': 'I am NSJ, your robot assistant. In this simulation I can speak, wave, and demonstrate gestures.',
    'say welcome': 'Welcome! It is great to have you here.',
    'say goodbye': 'Goodbye! See you next time.',
}
WALK_ACTIONS = ('walk', 'walk backward', 'turn left', 'turn right')
UNSUPPORTED = ('sit', 'sit down', 'stand up', 'squat', 'lie down', 'dance', 'jump')
HELP_TEXT = (
    "VOICE / TYPED COMMANDS\n"
    "greet (introduction + wave) | wave hello\n"
    "face wave | high wave\n"
    "left wave | wave both hands | shake hands\n"
    "hands up | right hand up | clap | high five\n"
    "hug | heart | right heart | reject | x ray\n"
    "blow a kiss | left kiss | right kiss\n"
    "walk | walk backward | turn left | turn right\n"
    "say hello | introduce yourself | say welcome | say goodbye\n"
    "stop | arms down | help | quit\n"
    "Walking: 5-second visual animation, no physics controller."
)



def normalize(text):
    return re.sub(r'[^a-z0-9 ]+', ' ', text.lower()).strip()


def interpret_command(text):
    text = ' '.join(normalize(text).split())
    for prefix in ('hey g one', 'hey gee one', 'hey g1', 'g one', 'gee one', 'g1', 'hey robot', 'robot'):
        if text == prefix or text.startswith(prefix + ' '):
            text = text[len(prefix):].strip()
            break
    text = re.sub(r'^please\s+|\s+please$', '', text).strip()
    # Match whole utterances; do not execute "don't wave" or choose one of two actions.
    for action, phrases in ALIASES.items():
        if text in {normalize(p) for p in phrases}:
            return action
    if text in UNSUPPORTED:
        return 'unsupported'
    return None


def print_commands():
    print('\nSIMULATION: illustrative arm motions; fixed fingers; no hardware control.')
    print('Commands: ' + ', '.join(ALIASES))
    print('Say "G one, wave hello" or just "wave hello". Type commands here too.')
    print('Stop/arms down returns to rest. Walking is a 5-second visual animation.\n', flush=True)


def ease(x):
    x = max(0.0, min(1.0, x))
    return x ** 3 * (10 - 15 * x + 6 * x * x)


class Gestures:
    def __init__(self):
        global mujoco, np
        import mujoco
        import mujoco.viewer
        import numpy as np
        self.model = mujoco.MjModel.from_xml_path(str(ROOT / 'unitree_mujoco/unitree_robots/g1/scene_23dof.xml'))
        self.data = mujoco.MjData(self.model)
        mujoco.mj_resetDataKeyframe(self.model, self.data, 0)
        self.joints = {}
        for side in ('right', 'left'):
            for part in ('shoulder_pitch', 'shoulder_roll', 'shoulder_yaw', 'elbow', 'wrist_roll'):
                name = f'{side}_{part}_joint'
                j = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, name)
                if j < 0:
                    raise RuntimeError(f'Missing joint: {name}')
                self.joints[name] = (int(self.model.jnt_qposadr[j]), *self.model.jnt_range[j])
        for side in ('right', 'left'):
            for part in ('hip_pitch', 'knee', 'ankle_pitch'):
                name = f'{side}_{part}_joint'
                j = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, name)
                if j < 0:
                    raise RuntimeError(f'Missing joint: {name}')
                self.joints[name] = (int(self.model.jnt_qposadr[j]), *self.model.jnt_range[j])
        self.rest = self.data.qpos.copy()
        for side in ('right', 'left'):
            self.arm(self.rest, side, [0, -.10, 0, math.pi / 2, 0])
        self.data.qpos[:] = self.rest
        mujoco.mj_forward(self.model, self.data)
        self.action = None
        self.started = 0.0
        self.duration = 0.0
        self.start_pose = self.rest.copy()
        self.last_update = 0.0

    def arm(self, pose, side, angles):
        for part, angle in zip(('shoulder_pitch', 'shoulder_roll', 'shoulder_yaw', 'elbow', 'wrist_roll'), angles):
            if side == 'left' and part in ('shoulder_roll', 'shoulder_yaw', 'wrist_roll'):
                angle = -angle
            address, lower, upper = self.joints[f'{side}_{part}_joint']
            pose[address] = np.clip(angle, lower, upper)

    def target(self, action, t):
        pose = self.rest.copy()
        wave = [-.30, -1.40, -1.50, .10, 0]
        sides = ('left',) if action == 'left wave' else ('right', 'left') if action == 'both wave' else ('right',)
        if action in ('wave', 'face wave', 'high wave', 'left wave', 'both wave', 'right hand up', 'high five', 'hands up'):
            if action == 'hands up':
                sides = ('right', 'left')
            if action == 'face wave':
                wave = [-.55, -1.05, -1.50, -.15, 0]
            if action in ('high wave', 'hands up'):
                wave = [-.30, -1.95, -1.50, .35, 0]
            u = max(0., min(1., t / 3.))
            if 'wave' in action:
                wave[2] += .30 * math.sin(math.pi * u) ** 2 * math.sin(6 * math.pi * u)
            for side in sides:
                self.arm(pose, side, wave)
        elif action == 'shake hand':
            self.arm(pose, 'right', [-.45 + .09 * math.sin(4 * math.pi * t), -.20, 0, .25, 0])
        elif action in ('hug', 'clap', 'heart', 'right heart', 'x-ray', 'reject'):
            angles = {
                'hug': [-.439, -1.280, .380, .146, 0],
                'clap': [-.595, .149, .088, -.152, 0],
                'heart': [-.855, .169, .011, -.370, 0],
                'right heart': [-.855, .28, .011, -.370, 0],
                'x-ray': [-.810, .522, .350, .084, 0],
                'reject': [-.70, -.4, -.5, .0, 0],
            }[action]
            if action == 'clap':
                # Bring fixed hands towards one another; no contact simulation.
                angles[1] -= .45 * (.5 - .5 * math.cos(2 * math.pi * t))
            if action == 'reject':
                angles[2] += .3 * math.sin(4 * math.pi * t)
            for side in (('right',) if action == 'right heart' else ('right', 'left')):
                self.arm(pose, side, angles)
        elif action in ('two-hand kiss', 'left kiss', 'right kiss'):
            sides = ('right', 'left') if action == 'two-hand kiss' else ('left',) if action == 'left kiss' else ('right',)
            reach = ease((t - .5) / 1.3)
            near = np.array([-1.422, .119, -.214, -.070, 0])
            away = np.array([-1.727, -.376, -.506, 1.699, 0])
            for side in sides:
                self.arm(pose, side, near + (away - near) * reach)
        return pose

    def animate_walk(self, t, dt):
        # Kinematic illustration only: legs cycle while the root advances.
        # Persist world position so stopping or waving never teleports home.
        strength = ease(t / .7) * ease((self.duration - t) / .7)
        yaw = 2 * math.atan2(self.rest[6], self.rest[3])
        if self.action in ('turn left', 'turn right'):
            yaw += (.45 if self.action == 'turn left' else -.45) * strength * dt
            self.rest[3:7] = [math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]
        else:
            distance = (.18 if self.action == 'walk' else -.18) * strength * dt
            self.rest[0] += math.cos(yaw) * distance
            self.rest[1] += math.sin(yaw) * distance
        self.data.qpos[:] = self.rest
        direction = -1 if self.action == 'walk backward' else 1
        for side, offset in (('right', 0), ('left', math.pi)):
            phase = 2 * math.pi * 1.2 * t + offset
            swing = math.sin(phase)
            lift = max(0., swing) ** 2
            knee = .38 * lift
            hip = -.24 * direction * swing - .5 * knee
            for part, delta in (('hip_pitch', hip), ('knee', knee),
                                ('ankle_pitch', -hip - knee),
                                ('shoulder_pitch', .12 * direction * swing)):
                address, lo, hi = self.joints[f'{side}_{part}_joint']
                self.data.qpos[address] = np.clip(self.rest[address] + strength * delta, lo, hi)

    def start(self, action, now):
        if action in ('release arm', 'stop'):
            self.action = 'release arm'
            self.duration = 1.2
        else:
            if self.action is not None:
                print('Gesture in progress. Say "stop" first, or wait until it finishes.', flush=True)
                return
            self.action = action
            self.duration = 5.0 if action in WALK_ACTIONS else 6.7
        self.start_pose = self.data.qpos.copy()
        self.started = now
        self.last_update = now
        print(f'Action: {self.action}', flush=True)

    def update(self, now):
        if self.action is None:
            return
        t = max(0., now - self.started)
        dt = max(0., min(now, self.started + self.duration) - self.last_update)
        self.last_update = min(now, self.started + self.duration)
        if self.action in WALK_ACTIONS:
            self.animate_walk(t, dt)
        elif self.action == 'release arm':
            self.data.qpos[:] = self.start_pose + (self.rest - self.start_pose) * ease(t / self.duration)
        elif t < 1.0:
            self.data.qpos[:] = self.start_pose
        elif t < 2.5:
            target = self.target(self.action, 0.)
            self.data.qpos[:] = self.start_pose + (target - self.start_pose) * ease((t - 1.) / 1.5)
        elif t < 5.5:
            # Fade periodic motions in/out to meet transition poses continuously.
            phase = t - 2.5
            base = self.target(self.action, 0.)
            moving = self.target(self.action, phase)
            if self.action.endswith('kiss'):
                self.data.qpos[:] = moving
            else:
                blend = math.sin(math.pi * phase / 3.) ** 2
                self.data.qpos[:] = base + (moving - base) * blend
        else:
            end = self.target(self.action, 3. if self.action.endswith('kiss') else 0.)
            self.data.qpos[:] = end + (self.rest - end) * ease((t - 5.5) / 1.2)
        if t >= self.duration:
            self.data.qpos[:] = self.rest
            print('Finished; resting pose.', flush=True)
            self.action = None
        mujoco.mj_forward(self.model, self.data)


def keyboard_worker(commands, done):
    while not done.is_set():
        try:
            line = input()
        except EOFError:
            commands.put('quit')
            return
        action = interpret_command(line)
        if action:
            commands.put(action)
        else:
            print('Unknown command. Type help for the command list.', flush=True)


def voice_worker(commands, done, device, speaker=None):
    try:
        import sounddevice as sd
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
        model_path = ROOT / 'models/speech/vosk-model-small-en-us-0.15'
        if not model_path.is_dir():
            raise RuntimeError(f'Speech model missing: {model_path}')
        speech_model = Model(str(model_path))
        # Constrained vocabulary helps the small offline recognizer distinguish gestures.
        phrases = {normalize(p) for variants in ALIASES.values() for p in variants}
        phrases.update(UNSUPPORTED)
        grammar = set(phrases)
        for prefix in ('g one', 'gee one', 'hey g one', 'hey robot'):
            grammar.update(prefix + ' ' + p for p in phrases)
        grammar.add('[unk]')
        info = sd.query_devices(device, 'input')
        rate = int(info['default_samplerate'])
        recognizer = KaldiRecognizer(speech_model, rate, json.dumps(sorted(grammar)))
        audio = queue.Queue(maxsize=32)

        def callback(indata, frames, timing, status):
            if status:
                print(f'Microphone: {status}', flush=True)
            if speaker and speaker.is_speaking():
                return
            try:
                audio.put_nowait(bytes(indata))
            except queue.Full:
                pass

        with sd.RawInputStream(device=device, samplerate=rate, blocksize=max(800, rate // 5),
                               dtype='int16', channels=1, callback=callback):
            print(f'VOICE READY — microphone: {info["name"]}. Say "G one, wave hello!"', flush=True)
            while not done.is_set():
                if speaker and speaker.is_speaking():
                    recognizer.Reset()
                    while not audio.empty():
                        try:
                            audio.get_nowait()
                        except queue.Empty:
                            break
                    done.wait(.05)
                    continue
                try:
                    chunk = audio.get(timeout=.2)
                except queue.Empty:
                    continue
                # Finalized utterances prevent partial phrases executing twice.
                if recognizer.AcceptWaveform(chunk):
                    text = json.loads(recognizer.Result()).get('text', '').strip()
                    if text:
                        action = interpret_command(text)
                        print(f'Heard: {text}' + (f' -> {action}' if action else ' (unrecognized)'), flush=True)
                        if action:
                            commands.put(action)
    except Exception as exc:
        print(f'Voice unavailable: {exc}\nAllow microphone access in macOS settings and restart, '
              'or use --devices / --device. Typed commands remain available.', flush=True)


def normalized(name):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', str(name).lower()).split())


def discover_actions(payload, known):
    """Accept common discovery layouts; only accept matching known name/ID pairs.

    Custom teach actions are intentionally not enabled. Unknown payloads fail closed.
    """
    result = {}
    names = {normalized(k): k for k in known}

    def add(name, ident):
        key = names.get(normalized(name))
        if isinstance(ident, str) and ident.isdigit():
            ident = int(ident)
        if key and type(ident) is int and known[key] == ident:
            result[key] = ident

    def visit(value):
        if isinstance(value, str):
            try:
                visit(json.loads(value))
            except (ValueError, TypeError):
                pass
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            add(value.get('name', value.get('action_name', '')),
                value.get('id', value.get('action_id')))
            for key, child in value.items():
                add(key, child)
                if isinstance(child, (dict, list)) or key in ('data', 'actions', 'action_list'):
                    visit(child)
    visit(payload)
    return result


class TimedCommands:
    def __init__(self):
        self.q = queue.Queue(maxsize=16)

    def put(self, action):
        try:
            self.q.put_nowait((time.monotonic(), action))
        except queue.Full:
            print('Command buffer full; command ignored.', flush=True)


class Hardware:
    def __init__(self, arm, loco, actions, last_state, enable_walking=False):
        self.arm_client = arm
        self.loco = loco
        self.actions = actions
        self.last_state = last_state
        self.enable_walking = enable_walking
        self.fault = False
        self.moving_until = 0.
        self.arm_until = 0.
        self.next_send = 0.
        self.velocity = (0., 0., 0.)
        self.state_timeout = 1.0

    def healthy(self, now):
        return now - self.last_state() <= self.state_timeout

    def checked(self, label, fn):
        try:
            code = fn()
            if code != 0:
                raise RuntimeError(f'return code {code}')
            return True
        except Exception as exc:
            print(f'{label} failed: {exc}', flush=True)
            self.fault = True
            return False

    def stop(self):
        # Best effort only: network failure can prevent receipt. Never disable torque.
        was_moving = self.moving_until > 0
        had_arm = self.arm_until > 0
        self.moving_until = self.arm_until = 0.
        if was_moving:
            self.checked('Stop walking', lambda: self.loco.SetVelocity(0., 0., 0., .4))
        if had_arm and 'release arm' in self.actions:
            self.checked('Release arm', lambda: self.arm_client.ExecuteAction(self.actions['release arm']))

    def tick(self, now):
        if not self.healthy(now) and not self.fault:
            print('Robot state is stale. Stopping; restart to reconnect.', flush=True)
            self.fault = True
            self.stop()
        if self.fault:
            return
        if self.moving_until:
            if now >= self.moving_until:
                self.stop()
            elif now >= self.next_send:
                # Each request expires onboard; do not request continuous movement.
                if not self.checked('Walking', lambda: self.loco.SetVelocity(*self.velocity, .4)):
                    self.stop()
                self.next_send = now + .15
        if self.arm_until and now >= self.arm_until:
            self.stop()

    def command(self, action, now):
        if action in ('stop', 'release arm'):
            # Explicit stop also sends a stop request when no local action is tracked.
            self.moving_until = max(self.moving_until, now) if self.enable_walking else 0.
            self.arm_until = max(self.arm_until, now)
            self.stop()
            return
        if self.fault or not self.healthy(now):
            print('Connection not healthy; motion refused.', flush=True)
            return
        if self.moving_until or self.arm_until:
            print('Busy: wait or say stop. This command was not queued.', flush=True)
            return
        if action in ('walk', 'walk backward', 'turn left', 'turn right'):
            if not self.enable_walking:
                print('Walking disabled. Restart with --enable-walking after verifying locomotion.', flush=True)
                return
            self.velocity = {
                'walk': (.10, 0., 0.), 'walk backward': (-.10, 0., 0.),
                'turn left': (0., 0., .15), 'turn right': (0., 0., -.15),
            }[action]
            self.moving_until = now + 1.0
            self.next_send = now
            self.tick(now)
            return
        # Generic wave selects an onboard wave. Never upload simulated joint angles.
        target = ('high wave' if 'high wave' in self.actions else 'face wave') if action == 'wave' else action
        if target not in self.actions:
            print(f'Action unavailable on this robot: {action}', flush=True)
            return
        self.arm_until = now + 3.0
        if not self.checked(target, lambda: self.arm_client.ExecuteAction(self.actions[target])):
            self.stop()
        else:
            print(f'Robot accepted {target}; arm release scheduled in 3 seconds.', flush=True)


def connect(interface, enable_walking):
    available = {name for _, name in socket.if_nameindex()}
    if interface not in available or interface in ('lo', 'lo0'):
        raise RuntimeError(f'Choose a robot-facing interface from: {sorted(available - {"lo", "lo0"})}')
    sys.path.insert(0, str(ROOT / 'unitree_sdk2_python'))
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
    from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient, action_map
    from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
    ChannelFactoryInitialize(0, interface)
    last = [0.]
    received = threading.Event()

    def on_state(msg):
        if len(msg.motor_state) >= 23:
            last[0] = time.monotonic()
            received.set()

    subscriber = ChannelSubscriber('rt/lowstate', LowState_)
    subscriber.Init(on_state, 10)
    try:
        if not received.wait(5):
            raise RuntimeError('No G1 rt/lowstate received in 5 seconds. Check robot/network/interface.')
        arm = G1ArmActionClient()
        arm.SetTimeout(3.)
        arm.Init()
        code, payload = arm.GetActionList()
        if code != 0:
            raise RuntimeError(f'Arm action discovery failed: {code}. Firmware/service support must be checked.')
        print('Robot action-list response:\n' + json.dumps(payload, indent=2), flush=True)
        actions = discover_actions(payload, action_map)
        print('Matched supported presets: ' + ', '.join(sorted(actions)), flush=True)
        loco = None
        if enable_walking:
            loco = LocoClient()
            loco.SetTimeout(.3)
            loco.Init()
            code, fsm = loco.GetFsmId()
            if code != 0:
                raise RuntimeError(f'Locomotion state query failed: {code}')
            print(f'Locomotion FSM: {fsm}. This program does not change the robot operating mode.', flush=True)
        arm.SetTimeout(.3)
        return Hardware(arm, loco, actions, lambda: last[0], enable_walking), subscriber
    except Exception:
        subscriber.Close()
        raise


def hardware_help(controller):
    print('HARDWARE commands: ' + ', '.join(sorted(controller.actions)), flush=True)
    print('Also: wave hello, stop, arms down, help, quit. '
          + ('Walking: walk / walk backward / turn left / turn right (1-second bursts).'
             if controller.enable_walking else 'Walking is disabled.'), flush=True)
    print('Left/both wave simulations have no automatic physical mapping. '
          'Voice stop is not an emergency stop; keep the robot remote available.', flush=True)


def run_hardware(args):
    controller, subscriber = connect(args.interface, args.enable_walking)
    if not args.arm or args.list:
        subscriber.Close()
        print('Read-only probe complete. No motion commands sent. Use --arm to enable gestures.')
        return
    if 'release arm' not in controller.actions:
        subscriber.Close()
        raise RuntimeError('Release-arm action was not discovered; refusing to enable gestures.')
    if not controller.healthy(time.monotonic()):
        subscriber.Close()
        raise RuntimeError('State stream became stale during discovery; no motion enabled.')
    speaker = None if args.mute else LocalSpeaker()
    done = threading.Event()
    commands = TimedCommands()

    hardware_help(controller)
    print('HARDWARE CONTROL ENABLED. Start with one stationary gesture in clear space.', flush=True)
    threading.Thread(target=keyboard_worker, args=(commands, done), daemon=True).start()
    if not args.no_voice:
        device = int(args.device) if args.device and args.device.isdigit() else args.device
        threading.Thread(target=voice_worker, args=(commands, done, device, speaker), daemon=True).start()
    try:
        while not done.is_set():
            now = time.monotonic()
            controller.tick(now)
            if controller.fault:
                break
            try:
                timestamp, action = commands.q.get(timeout=.05)
            except queue.Empty:
                continue
            if action == 'quit':
                break
            if action == 'help':
                hardware_help(controller)
            elif now - timestamp <= 1.0 or action in ('stop', 'release arm'):
                if action in ('stop', 'release arm') and speaker:
                    speaker.stop()
                if action in SPEECH_RESPONSES:
                    if speaker:
                        speaker.speak(SPEECH_RESPONSES[action])
                    else:
                        print('Speech output muted.', flush=True)
                elif action == 'greet':
                    if controller.healthy(time.monotonic()) and not controller.fault and not controller.arm_until and not controller.moving_until:
                        controller.command('wave', time.monotonic())
                        if controller.arm_until and not controller.fault and speaker:
                            speaker.speak(args.text or greeting_text())
                    else:
                        print('Robot busy or connection not healthy; greeting refused.', flush=True)
                else:
                    controller.command(action, time.monotonic())
            else:
                print('Stale command ignored.', flush=True)
    finally:
        done.set()
        controller.stop()
        if speaker:
            speaker.close()
        subscriber.Close()



def greeting_text():
    return 'Hello! ' + SPEECH_RESPONSES['introduce yourself']


def begin_greeting(gestures, speaker, now, text=None):
    if gestures.action is not None or (speaker and speaker.is_speaking()):
        print('Busy; wait or type stop.', flush=True)
        return False
    if speaker and not speaker.speak(text or greeting_text()):
        return False
    gestures.start('wave', now - 1.0)
    gestures.update(now)
    return True


def run_simulation(args):
    gestures = Gestures()
    speaker = None if args.mute else LocalSpeaker()
    commands = queue.SimpleQueue()
    done = threading.Event()
    device = int(args.device) if args.device and args.device.isdigit() else args.device
    threading.Thread(target=keyboard_worker, args=(commands, done), daemon=True).start()
    if not args.no_voice:
        threading.Thread(target=voice_worker, args=(commands, done, device, speaker), daemon=True).start()
    print_commands()
    demo_actions = iter(a for a in ALIASES if a not in ('help', 'quit', 'stop', 'release arm', *SPEECH_RESPONSES))
    next_demo = time.monotonic() + 2
    try:
        with mujoco.viewer.launch_passive(gestures.model, gestures.data) as viewer:
            viewer.cam.lookat[:] = [0, 0, .9]
            viewer.cam.distance = 2.5
            viewer.cam.azimuth = 15
            viewer.cam.elevation = -10
            help_visible = True
            while viewer.is_running() and not done.is_set():
                now = time.monotonic()
                gestures.update(now)
                if args.demo and gestures.action is None and not (speaker and speaker.is_speaking()) and now >= next_demo:
                    action = next(demo_actions, None)
                    if action: commands.put(action)
                    else: args.demo = False
                    next_demo = now + 7.7
                while not commands.empty():
                    action = commands.get()
                    if action == 'quit':
                        done.set()
                    elif action == 'help':
                        print_commands()
                        help_visible = True
                    elif action == 'greet':
                        help_visible = False
                        begin_greeting(gestures, speaker, now, args.text)
                    elif action in SPEECH_RESPONSES:
                        help_visible = False
                        if speaker: speaker.speak(SPEECH_RESPONSES[action])
                        else: print('Speech output muted.', flush=True)
                    elif action == 'unsupported':
                        print('Body action not implemented. Say help for supported commands.', flush=True)
                    else:
                        help_visible = False
                        if action in ('stop', 'release arm'):
                            args.demo = False
                            if speaker: speaker.stop()
                        gestures.start(action, now)
                viewer.cam.lookat[:2] = gestures.data.qpos[:2]
                status = 'Action: ' + (gestures.action or 'Resting — say help')
                if speaker and speaker.caption: status += '\nG1 says: ' + speaker.caption
                viewer.set_texts((mujoco.mjtFontScale.mjFONTSCALE_100,
                                  mujoco.mjtGridPos.mjGRID_TOPLEFT,
                                  HELP_TEXT if help_visible else status, ''))
                viewer.sync()
                time.sleep(.02)
    finally:
        done.set()
        if speaker: speaker.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hardware', action='store_true', help='physical robot mode; read-only unless --arm')
    parser.add_argument('--interface', help='robot-facing network interface')
    parser.add_argument('--arm', action='store_true', help='enable physical gesture requests')
    parser.add_argument('--enable-walking', action='store_true', help='allow one-second physical walking requests')
    parser.add_argument('--no-voice', action='store_true', help='typed commands only')
    parser.add_argument('--mute', action='store_true', help='disable local speech output')
    parser.add_argument('--device', help='microphone name or index')
    parser.add_argument('--text', help='custom text for the greet command')
    parser.add_argument('--list', action='store_true', help='list commands; hardware mode queries the robot')
    parser.add_argument('--devices', action='store_true', help='list audio devices and exit')
    parser.add_argument('--demo', action='store_true', help='cycle simulation actions')
    args = parser.parse_args()
    if args.hardware or args.arm or args.enable_walking or args.interface:
        parser.error('This is the PC/simulation copy. Use g1_control.py for physical G1 control.')
    if args.devices:
        import sounddevice as sd
        print(sd.query_devices())
        return 0
    if not args.hardware:
        if args.interface or args.arm or args.enable_walking:
            parser.error('--interface, --arm, and --enable-walking require --hardware')
        if args.list:
            print_commands()
            return 0
    else:
        if not args.interface: parser.error('--hardware requires --interface')
        if args.enable_walking and not args.arm: parser.error('--enable-walking requires --arm')
        if args.demo: parser.error('--demo is simulation-only')
    try:
        if args.hardware: run_hardware(args)
        else: run_simulation(args)
    except KeyboardInterrupt:
        print('Stopped.')
    except Exception as exc:
        print(f'G1 control unavailable: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
