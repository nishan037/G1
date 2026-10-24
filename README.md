# G1 Smart AI

Working PC apps are preserved with `_test.py` names; physical G1 apps use the original names.

| Command | Application | Mode |
| --- | --- | --- |
| `python3 launch.py control-test` | `apps/g1_control_test.py` | PC simulation, voice/text gestures, Mac speech |
| `python3 launch.py conversation-test` | `apps/g1_conversation_test.py` | Ollama voice/text conversation, Mac speech |
| `python3 launch.py control --interface en5 --probe --no-voice` | `apps/g1_control.py` | Read-only physical state/action/audio probe |
| `python3 launch.py control --interface en5 --arm` | `apps/g1_control.py` | Physical voice/text actions, robot speech |
| `python3 launch.py conversation --interface en5` | `apps/g1_conversation.py` | Ollama conversation through G1 speaker; no movement |

`en5` is an example; choose the actual laptop adapter connected to G1. **Read [the first-connection runbook](docs/G1_FIRST_CONNECTION.md) before testing physical commands.** Robot services and permissions must be verified; the existence of SDK code does not establish support on G1 Standard.

## Basic commands

`wave`, `clap`, `shake hands`, `hands up`, `high five`, `hug`, `heart`, `walk`, `walk backward`, `turn left`, `turn right`, `stop`, `help`, `quit`. Physical actions must be discovered from the robot. Physical walking additionally requires `--enable-walking` and is bounded to short requests.

`greet` / `hello and wave` performs the introduction and wave together. `say hello`, `introduce yourself`, `say welcome`, and `say goodbye` speak only. The customized NSJ introduction is retained. Simulation-only trajectories are never sent to physical motors.

## Input and output

PC apps use Mac microphone/speakers. Physical apps default to laptop microphone and robot speaker, with `--mic host|robot` and `--speaker robot|local|none` selections. Robot microphone input requires `--interface-ip HOST_IPV4` and a verified multicast stream. `--no-voice` enables typed input only; `--mute` disables output. No robot volume changes happen automatically.

## Readiness and tests

```bash
python3 launch.py check --target control-test
python3 launch.py check --target control --interface en5 --no-voice
python3 launch.py check --target conversation --interface en5 --no-voice
python3 launch.py test
```

Launchers run preflight automatically; failed required checks block launch. Readiness checks never send motion or speech. Cloud checks send small test requests. Physical movement and audio remain untested on your robot; Mac/simulator and mock tests cannot certify them.

## Files

- Four app files under `apps/`, plus independent camera detection under `apps/vision/`.
- `launch.py` and `preflight.py`: entry points/readiness checks.
- `models/`: speech-recognition and detection models (git-ignored; provided locally).
- `tests/`, `docs/`, `logs/`: checks, guides, and logs.
- Existing `.venv`, `.venv-g1`, `unitree_sdk2_python`, `unitree_mujoco`, and `cyclonedds` paths are preserved. These environments are Mac-specific; Linux/Raspberry Pi deployments require rebuilding them.

Ollama key instructions: [cloud conversation guide](docs/ollama_cloud_conversation.md). Environment variable `OLLAMA_API_KEY` overrides saved configuration. Test and physical conversation apps preserve the working configuration, but prompts accurately distinguish their capabilities. Neither app converts LLM replies into movement commands.
