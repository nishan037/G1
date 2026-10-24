# G1 voice conversation with Ollama Cloud

This is a separate voice-only application. It generates replies through the Ollama Cloud API and speaks through your Mac. It does not move the simulation or connect to physical robot hardware. This guide describes the PC copy. For physical robot speaker/microphone integration use the first-connection runbook, G1_FIRST_CONNECTION.md.

## 1. Get an API key

Sign in at https://ollama.com and create a key at https://ollama.com/settings/keys. Your cloud plan/credits determine which models you can use. The default is `gemma4:31b`, currently used in Ollama's cloud API documentation. You can select another supported chat model; the client requests non-thinking output.

## 2. Connect the key in Terminal (Zsh)

```zsh
cd /Users/nishan/G1-Smart-AI
read -s "OLLAMA_API_KEY?Paste your Ollama API key (hidden): "
export OLLAMA_API_KEY
printf '\n'
```

Paste the key at the hidden prompt and press Enter. An environment override is available only in this terminal session and its child processes. Repeat in a new terminal when using an override. Do not paste the key into chat or source files. No `.env` file is required or loaded by this app. Conversation transcripts are not saved. Your requested saved key is in `apps/g1_conversation_test.py`; an environment key overrides it. Keep this file and the consolidation ZIP private.

## 3. Test cloud access

```bash
python3 launch.py conversation-test --check
```

This sends a small test request to verify the key, selected model, and account access; it uses some cloud allowance. Successful authentication alone does not prove a selected model is included in a free plan.

To list published model names:

```bash
python3 launch.py conversation-test --models
```

The published list is not a guarantee that your account can use every model. Select a model available to your account:

```bash
python3 launch.py conversation-test --model gemma4:31b --check
```

## 4. Start talking

```bash
python3 launch.py conversation-test
```

Preflight checks speech packages, Vosk model, microphone, local speech engine, and cloud access. Wait for `VOICE READY`, ask a question, then pause. General Vosk transcription is used instead of a fixed command vocabulary. For example: “Tell me a joke” or “Why is the sky blue?” Replies are generated, not predefined.

To use typed questions with spoken replies:

```bash
python3 launch.py conversation-test --no-voice
```

For typed questions and text replies only:

```bash
python3 launch.py conversation-test --no-voice --mute
```

Options: `--device 1` selects a microphone, `--model NAME` selects a cloud model. `OLLAMA_MODEL` can also set the default model.

## Conversation controls

- `/stop`: interrupt local speech and discard a pending reply. An already-sent cloud request cannot be withdrawn; its result is ignored, but it may still count toward usage. A new question waits until that request has finished/timed out.
- `/reset`: clear local conversation history and discard a pending reply.
- `/quit` or Ctrl+C: exit.
- `/help`: list controls.

Speak `stop` or `reset conversation` while the app is listening. During cloud requests or speech output, microphone transcription pauses to reduce feedback, so type controls to interrupt. Questions arriving while busy are discarded with a message. History is limited to eight turns, stored in memory, and sent with subsequent questions. Closing the app clears it.

## Troubleshooting

- Missing key: repeat the hidden prompt and export in the terminal that launches the app.
- 401: key rejected; verify or regenerate it in your account.
- 403/404: check model access or use a currently available model name.
- 429: wait or check usage/credits in your account.
- Network timeout: check internet access and retry.
- Transcription errors: use `--no-voice` to test the conversation separately, or choose a better microphone with `--device`.

Only transcribed text and recent conversation history are sent to Ollama; this app does not upload microphone recordings. Cloud responses remain conversational text and are never executed as shell code, SDK actions, or movement commands.

Official API reference: https://docs.ollama.com/cloud
