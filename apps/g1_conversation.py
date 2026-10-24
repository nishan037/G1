"""Voice-only conversation with Ollama Cloud. No physical robot commands."""
import argparse
from pathlib import Path
import json
import os
import urllib.error
import urllib.request
import queue
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps'))
from g1_control import LocalSpeaker, make_speaker, connect_audio, pcm_chunks, check_robot_microphone

DEFAULT_MODEL = 'gemma4:31b'
SYSTEM_PROMPT = (
    'You are G1, a friendly robot assistant in a voice-only robot demonstration. '
    'Reply naturally in English using one or two short spoken sentences, at most 80 words. '
    'You can chat, explain things, and tell jokes. Do not claim you can see, sense, '
    'move, or operate a physical robot: this app has no movement or vision interface, even when its speaker is connected. '
    'Use plain spoken text without markdown. Do not invent personal memories.'
)


class CloudError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OllamaCloud:
    def __init__(self, model=None, timeout=25):
        self.key = os.environ.get('OLLAMA_API_KEY', '').strip() or '3000e2ff145f4068a241628f2dfa7279.aCJ7d-FOx8tuIspH-2kYCT4G'
        if not self.key:
            raise CloudError('OLLAMA_API_KEY is not set. See docs/ollama_cloud_conversation.md.')
        self.model = model or os.environ.get('OLLAMA_MODEL', DEFAULT_MODEL)
        self.timeout = timeout

    def _request(self, path, payload=None):
        request = urllib.request.Request(
            'https://ollama.com/api/' + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/json'},
            method='POST' if payload is not None else 'GET',
        )
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=self.timeout) as response:
                return json.loads(response.read(2_000_000))
        except urllib.error.HTTPError as exc:
            messages = {
                401: 'API key rejected. Check the key in your Ollama account.',
                403: 'Access denied. Check your account and model access.',
                404: 'Model unavailable. Use --models and set --model to an available model.',
                429: 'Ollama usage/rate limit reached. Wait or check account credits.',
                400: 'Ollama rejected the request. Check the selected model supports chat and non-thinking replies.',
            }
            raise CloudError(messages.get(exc.code, f'Ollama returned HTTP {exc.code}. Try again later.')) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise CloudError('Cannot reach Ollama Cloud. Check internet access and try again.') from None
        except (ValueError, TypeError):
            raise CloudError('Ollama returned an invalid response.') from None

    def reply(self, text, history=()):
        text = text.strip()
        if not text or len(text) > 4000:
            raise CloudError('Use a question between 1 and 4000 characters.')
        payload = {
            'model': self.model,
            'messages': [{'role': 'system', 'content': SYSTEM_PROMPT}, *list(history)[-16:], {'role': 'user', 'content': text}],
            'stream': False,
            'think': False,
            'options': {'num_predict': 256},
        }
        data = self._request('chat', payload)
        content = data.get('message', {}).get('content', '') if isinstance(data, dict) else ''
        if not isinstance(content, str) or not content.strip():
            raise CloudError('The model returned no spoken reply. Try a different chat model.')
        # Bound local speaking time; never execute model output as code or commands.
        return content.strip()[:1900]

    def check(self):
        self.reply('Reply with only the word ready.')
        return f'Cloud authentication and chat OK: {self.model} (small test request used)'

    def models(self):
        data = self._request('tags')
        return [item['name'] for item in data.get('models', []) if isinstance(item, dict) and 'name' in item]


def control(text):
    value = text.lower().strip().rstrip('.!?')
    if value in ('/quit', 'quit', 'exit', 'goodbye g one'):
        return 'quit'
    if value in ('/stop', 'stop', 'stop speaking'):
        return 'stop'
    if value in ('/reset', 'reset conversation', 'start a new conversation'):
        return 'reset'
    if value in ('/help', 'help'):
        return 'help'
    return None


def microphone_worker(inputs, done, listening, speaker, device, mic='host', interface_ip=None):
    try:
        from vosk import Model, KaldiRecognizer, SetLogLevel
        SetLogLevel(-1)
        model = Model(str(ROOT / 'models/speech/vosk-model-small-en-us-0.15'))
        recognizer = None
        active = lambda: listening.is_set() and not (speaker and speaker.is_speaking())
        for rate, chunk in pcm_chunks(done, device, mic, interface_ip, active):
            if recognizer is None: recognizer = KaldiRecognizer(model, rate)
            if chunk is None or not active():
                recognizer.Reset()
                continue
            if recognizer.AcceptWaveform(chunk):
                text = json.loads(recognizer.Result()).get('text', '').strip()
                if text:
                    listening.clear()
                    inputs.put((time.monotonic(), text))
    except Exception as exc:
        print(f'Microphone unavailable: {exc}. Typed questions remain available.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interface', help='robot-facing network adapter')
    parser.add_argument('--speaker', choices=('robot', 'local', 'none'), default='robot')
    parser.add_argument('--speaker-id', type=int, default=1)
    parser.add_argument('--mic', choices=('host', 'robot'), default='host')
    parser.add_argument('--interface-ip', help='host IPv4 for robot microphone multicast')
    parser.add_argument('--probe', action='store_true', help='read-only audio/cloud/input checks, then exit')
    parser.add_argument('--model', help='cloud model name; defaults to OLLAMA_MODEL or gemma4:31b')
    parser.add_argument('--no-voice', action='store_true', help='typed input only')
    parser.add_argument('--mute', action='store_true', help='text replies only')
    parser.add_argument('--device', help='microphone name or index')
    parser.add_argument('--models', action='store_true', help='list cloud model names, then exit')
    parser.add_argument('--check', action='store_true', help='test cloud credentials/model, then exit')
    args = parser.parse_args()
    if not args.models and not args.check and args.speaker == 'robot' and not args.mute and not args.interface:
        parser.error('--interface is required for robot speaker output')
    if args.mic == 'robot' and not args.no_voice and not args.interface_ip:
        parser.error('--mic robot requires --interface-ip')
    try:
        client = OllamaCloud(args.model)
        if args.models:
            print('\n'.join(client.models()))
            return 0
        if args.check:
            print(client.check())
            return 0
    except CloudError as exc:
        print(f'Cloud setup: {exc}', file=sys.stderr)
        return 1
    try:
        if args.probe:
            if args.speaker == 'robot' and not args.mute: connect_audio(args.interface)
            print(client.check())
            if args.mic == 'robot' and not args.no_voice: print(check_robot_microphone(args.interface_ip))
            print('Read-only conversation probe complete. No speech or movement sent.')
            return 0
        speaker = make_speaker(args)
    except Exception as exc:
        print(f'G1 audio/input setup unavailable: {exc}', file=sys.stderr)
        return 1
    inputs = queue.Queue()
    replies = queue.Queue()
    done = threading.Event()
    listening = threading.Event()
    listening.set()
    history = []
    generation = 0
    pending = None
    request_thread = None

    def keyboard():
        while not done.is_set():
            try: text = input()
            except EOFError:
                inputs.put((time.monotonic(), '/quit'))
                return
            if text.strip(): inputs.put((time.monotonic(), text))

    def ask(token, text, previous):
        try: replies.put((token, text, client.reply(text, previous), None))
        except CloudError as exc: replies.put((token, text, None, str(exc)))
        except Exception: replies.put((token, text, None, 'Unexpected cloud request failure; try again.'))

    print(f'G1 CLOUD CONVERSATION — {client.model}\nQuestions go to Ollama Cloud; replies use the selected speaker ({args.speaker}).\n'
          'Type /stop to interrupt, /reset to clear memory, /quit to exit. No robot movement.\n'
          'Microphone pauses during requests/replies; typed controls always work.', flush=True)
    threading.Thread(target=keyboard, daemon=True).start()
    if not args.no_voice:
        device = int(args.device) if args.device and args.device.isdigit() else args.device
        threading.Thread(target=microphone_worker, args=(inputs, done, listening, speaker, device, args.mic, args.interface_ip), daemon=True).start()
    try:
        while not done.is_set():
            while not replies.empty():
                token, question, answer, error = replies.get()
                if token != pending:
                    continue
                pending = None
                if error:
                    print(f'Cloud: {error}', flush=True)
                else:
                    history.extend([{'role': 'user', 'content': question}, {'role': 'assistant', 'content': answer}])
                    history[:] = history[-16:]
                    if speaker:
                        try: speaker.speak(answer)
                        except Exception as exc: print(f'Robot speech failed: {exc}. Reply text: {answer}', flush=True)
                    else:
                        print('G1: ' + answer, flush=True)
                print('Ready for your next question after speech finishes.', flush=True)
            try:
                timestamp, text = inputs.get(timeout=.05)
            except queue.Empty:
                if pending is None and not (speaker and speaker.is_speaking()):
                    listening.set()
                continue
            command = control(text)
            if command == 'quit':
                break
            if command in ('stop', 'reset'):
                generation += 1
                pending = None
                if speaker: speaker.stop()
                if command == 'reset': history.clear()
                print('Stopped. Pending response discarded.' if command == 'stop' else 'Conversation memory cleared.', flush=True)
                continue
            if command == 'help':
                print('Ask any question. /stop, /reset, /quit. Use --no-voice for typed input.', flush=True)
                continue
            if time.monotonic() - timestamp > 10:
                print('Old input discarded; please ask again.', flush=True)
                continue
            if (request_thread and request_thread.is_alive()) or pending is not None or (speaker and speaker.is_speaking()):
                print('Still thinking/speaking. Wait, or type /stop. This question was not queued.', flush=True)
                continue
            listening.clear()
            generation += 1
            pending = generation
            print(f'You: {text}\nG1 is thinking...', flush=True)
            request_thread = threading.Thread(target=ask, args=(pending, text, list(history)), daemon=True)
            request_thread.start()
    except KeyboardInterrupt:
        pass
    finally:
        done.set()
        if speaker: speaker.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
