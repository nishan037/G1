"""Physical G1 voice/text deployment app. Default run is a read-only probe."""
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
    'introduce yourself': 'I am NSJ, your robot assistant. I can speak, wave, and demonstrate gestures.',
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


def validate_interface(interface):
    names = {name for _, name in socket.if_nameindex()} - {'lo', 'lo0'}
    if not interface or interface not in names:
        raise RuntimeError(f'Choose the robot-facing --interface from: {sorted(names)}')


def connect_audio(interface):
    """Read-only audio check. Never changes volume or starts playback."""
    validate_interface(interface)
    sys.path.insert(0, str(ROOT / 'unitree_sdk2_python'))
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
    ChannelFactoryInitialize(0, interface)
    client = AudioClient()
    client.SetTimeout(2.)
    client.Init()
    code, volume = client.GetVolume()
    if code != 0:
        raise RuntimeError(f'G1 audio-service query failed: {code}. Verify firmware/service access.')
    print(f'G1 audio service available; volume response: {volume}. Volume unchanged.', flush=True)
    client.SetTimeout(.5)
    return client


class RobotSpeaker:
    """G1 onboard TTS. Busy timing is estimated, not playback completion feedback."""
    def __init__(self, client, speaker_id=1):
        self.client = client
        self.speaker_id = speaker_id
        self.caption = ''
        self.index = 0
        self.busy_until = 0.
        self.active = False

    def is_speaking(self):
        return time.monotonic() < self.busy_until

    def speak(self, text):
        if self.is_speaking():
            print('Robot speaker busy; speech request ignored.', flush=True)
            return False
        text = str(text).strip()
        if not text or len(text) > 2000:
            raise ValueError('Speech text must contain 1–2000 characters.')
        self.index += 1
        # The installed Python SDK has tts_index += tts_index, leaving its index
        # at zero. Use its registered TTS RPC with a monotonically increasing ID.
        from unitree_sdk2py.g1.audio.g1_audio_api import ROBOT_API_ID_AUDIO_TTS
        payload = {'index': self.index, 'text': text, 'speaker_id': self.speaker_id}
        code, _ = self.client._Call(ROBOT_API_ID_AUDIO_TTS, json.dumps(payload))
        if code != 0:
            raise RuntimeError(f'Robot TTS request failed: {code}; no laptop fallback was used.')
        self.caption = text
        self.active = True
        self.busy_until = time.monotonic() + max(3., len(text.split()) * .55 + 2.)
        print('G1 speaker accepted: ' + text, flush=True)
        return True

    def stop(self):
        if not self.active or not self.is_speaking():
            self.active = False
            return
        from unitree_sdk2py.g1.audio.g1_audio_api import ROBOT_API_ID_AUDIO_STOP_PLAY
        try:
            code, _ = self.client._Call(ROBOT_API_ID_AUDIO_STOP_PLAY, json.dumps({'app_name': 'g1_voice'}))
            print(f'Audio stop request returned {code}; onboard TTS cancellation is firmware-dependent.', flush=True)
        except Exception as exc:
            print(f'Audio stop could not be delivered: {exc}', flush=True)
        # Keep the estimated suppression window: a successful playback-stop RPC
        # is not proof that the firmware stopped a TTS utterance.
        self.active = False

    def close(self):
        self.stop()


def make_speaker(args, audio_client=None):
    if args.mute or args.speaker == 'none':
        return None
    if args.speaker == 'local':
        return LocalSpeaker()
    return RobotSpeaker(audio_client or connect_audio(args.interface), args.speaker_id)


def robot_microphone_socket(local_ip, timeout=.2):
    import ipaddress
    ip = ipaddress.IPv4Address(local_ip or '0.0.0.0')
    if ip.is_unspecified or ip.is_loopback:
        raise RuntimeError('--interface-ip must be the laptop/host IPv4 address on the G1-facing network')
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', 5555))
        membership = socket.inet_aton('239.168.123.161') + socket.inet_aton(str(ip))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        sock.settimeout(timeout)
        return sock
    except Exception:
        sock.close()
        raise


def check_robot_microphone(local_ip):
    with robot_microphone_socket(local_ip, 5.) as sock:
        data = sock.recv(65536)
        if not data or len(data) % 2:
            raise RuntimeError('Robot microphone did not provide a valid PCM packet')
    return 'Robot microphone PCM packet received; discarded without saving; speech accuracy unverified'


def pcm_chunks(done, device=None, mic='host', interface_ip=None, active=lambda: True):
    """Yield (sample_rate, PCM), or PCM=None to reset recognition during output."""
    if mic == 'robot':
        with robot_microphone_socket(interface_ip) as sock:
            last_packet = time.monotonic()
            print('Listening to documented G1 multicast microphone stream (16 kHz mono PCM).', flush=True)
            while not done.is_set():
                try:
                    data = sock.recv(65536)
                except socket.timeout:
                    if time.monotonic() - last_packet > 5:
                        raise RuntimeError('No robot microphone packets for 5 seconds. Use --mic host or verify multicast service/network.')
                    continue
                last_packet = time.monotonic()
                if data and len(data) % 2 == 0:
                    yield 16000, data if active() else None
        return
    import sounddevice as sd
    info = sd.query_devices(device, 'input')
    rate = int(info['default_samplerate'])
    audio = queue.Queue(maxsize=20)
    def callback(indata, frames, timing, status):
        if active():
            try: audio.put_nowait(bytes(indata))
            except queue.Full: pass
    with sd.RawInputStream(device=device, samplerate=rate, channels=1, dtype='int16',
                           blocksize=rate // 5, callback=callback):
        print(f'VOICE READY — host microphone: {info["name"]}', flush=True)
        while not done.is_set():
            if not active():
                while not audio.empty():
                    try: audio.get_nowait()
                    except queue.Empty: break
                yield rate, None
                done.wait(.05)
                continue
            try: yield rate, audio.get(timeout=.2)
            except queue.Empty: continue


def voice_worker(commands, done, device, speaker=None, mic='host', interface_ip=None):
    try:
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
        model = Model(str(ROOT / 'models/speech/vosk-model-small-en-us-0.15'))
        phrases = {normalize(p) for variants in ALIASES.values() for p in variants}
        phrases.update(UNSUPPORTED)
        grammar = set(phrases)
        for prefix in ('g one', 'gee one', 'hey g one', 'hey robot'):
            grammar.update(prefix + ' ' + p for p in phrases)
        grammar.add('[unk]')
        recognizer = None
        active = lambda: not (speaker and speaker.is_speaking())
        for rate, chunk in pcm_chunks(done, device, mic, interface_ip, active):
            if recognizer is None:
                recognizer = KaldiRecognizer(model, rate, json.dumps(sorted(grammar)))
            if chunk is None or not active():
                recognizer.Reset()
                continue
            if recognizer.AcceptWaveform(chunk):
                text = json.loads(recognizer.Result()).get('text', '').strip()
                if text:
                    action = interpret_command(text)
                    print(f'Heard: {text} -> {action or "unrecognized"}', flush=True)
                    if action: commands.put(action)
    except Exception as exc:
        print(f'Voice input unavailable: {exc}. Typed commands remain available.', flush=True)


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
    print('Also: greet, wave hello, say hello, introduce yourself, say welcome, say goodbye, stop, arms down, help, quit. '
          + ('Walking: walk / walk backward / turn left / turn right (1-second bursts).'
             if controller.enable_walking else 'Walking is disabled.'), flush=True)
    print('Only discovered onboard presets are available; simulation-only gestures are refused. '
          'Voice stop is not an emergency stop; keep the robot remote available.', flush=True)


def run_hardware(args):
    controller, subscriber = connect(args.interface, args.enable_walking)
    audio_client = None
    try:
        if args.speaker == 'robot' and not args.mute:
            audio_client = connect_audio(args.interface)
    except Exception:
        subscriber.Close()
        raise
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
    try:
        speaker = make_speaker(args, audio_client)
    except Exception:
        subscriber.Close()
        raise
    done = threading.Event()
    commands = TimedCommands()

    hardware_help(controller)
    print('HARDWARE CONTROL ENABLED. Start with one stationary gesture in clear space.', flush=True)
    threading.Thread(target=keyboard_worker, args=(commands, done), daemon=True).start()
    if not args.no_voice:
        device = int(args.device) if args.device and args.device.isdigit() else args.device
        threading.Thread(target=voice_worker, args=(commands, done, device, speaker, args.mic, args.interface_ip), daemon=True).start()
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
    # Preserve the user's customized identity without claiming a simulation.
    return 'Hello! ' + SPEECH_RESPONSES['introduce yourself'].replace('I can', 'I can')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interface', required=True, help='robot-facing network adapter, e.g. en5')
    parser.add_argument('--arm', action='store_true', help='enable physical preset action requests')
    parser.add_argument('--enable-walking', action='store_true', help='allow bounded physical walking requests')
    parser.add_argument('--speaker', choices=('robot', 'local', 'none'), default='robot')
    parser.add_argument('--speaker-id', type=int, default=1, help='onboard TTS language/voice ID; SDK example uses 1 for English')
    parser.add_argument('--mic', choices=('host', 'robot'), default='host')
    parser.add_argument('--interface-ip', help='host IPv4 on the robot-facing network; required for robot microphone')
    parser.add_argument('--device', help='host microphone name or index')
    parser.add_argument('--no-voice', action='store_true')
    parser.add_argument('--mute', action='store_true')
    parser.add_argument('--text', help='custom greeting text')
    parser.add_argument('--say', help='speak this text on selected speaker, then exit; sends no movement')
    parser.add_argument('--probe', action='store_true', help='read-only state/action/audio check (the default)')
    parser.add_argument('--list', action='store_true', help='read-only action discovery')
    args = parser.parse_args()
    if args.enable_walking and not args.arm: parser.error('--enable-walking requires --arm')
    if args.probe and (args.arm or args.say): parser.error('--probe cannot be combined with --arm or --say')
    if args.say and (args.arm or args.mute or args.speaker == 'none'): parser.error('--say requires a speaker and cannot be combined with --arm/--mute')
    if args.mic == 'robot' and not args.no_voice and not args.interface_ip and args.arm:
        parser.error('--mic robot requires --interface-ip (the host IP, not the robot IP)')
    try:
        if args.say:
            speaker = make_speaker(args)
            try:
                speaker.speak(args.say)
                while speaker.is_speaking(): time.sleep(.1)
            finally: speaker.close()
        else:
            run_hardware(args)
    except KeyboardInterrupt:
        print('Stopped.')
    except Exception as exc:
        print(f'G1 deployment unavailable: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
