# First physical G1 connection

These apps run on your laptop connected to G1. They are not an onboard installer. Your exact robot's firmware, Standard/EDU permissions, and enabled services determine what can work. No physical robot was available for validation.

## Files and modes

| App | Purpose |
| --- | --- |
| `apps/g1_control_test.py` | Preserved PC simulation; physical mode refused |
| `apps/g1_conversation_test.py` | Preserved Ollama conversation through the Mac speaker |
| `apps/g1_control.py` | Physical voice/text actions and robot speech; read-only unless explicitly enabled |
| `apps/g1_conversation.py` | Generated conversation through robot speaker; never sends movement commands |

The control deployment app does not import MuJoCo or NumPy. It uses G1's supported onboard action/locomotion services, never simulated joint angles.

## 1. Connect the laptop and identify its network adapter

Connect using the network method/address settings supplied for your actual G1. Do not overwrite robot network settings or install software on its motion-control computer.

On your Mac:

```bash
cd /Users/nishan/G1-Smart-AI
networksetup -listallhardwareports
```

Choose the device name for the adapter connected to G1. `en5` in the commands below is only an example: replace it everywhere with your actual adapter. The apps use DDS domain 0.

## 2. Read-only action and audio probe

```bash
python3 launch.py control --interface en5 --probe --no-voice
```

This must receive live `rt/lowstate`, match names/IDs from `GetActionList()`, and query speaker volume. It sends no action, speech, volume-change, or LED request. Expect READY before proceeding. If an action query fails, verify the robot model, firmware, supported APIs, mode, and network with Unitree/supplier. An external laptop does not bypass access restrictions.

To test action discovery without requiring audio:

```bash
python3 launch.py control --interface en5 --probe --no-voice --speaker none
```

A successful API response proves connectivity, not physical behavior or safe clearance.

## 3. Test only the robot speaker

```bash
python3 launch.py control --interface en5 --say "Hello. I am ready for the demonstration."
```

This sends text to G1's audio service and exits after an estimated playback period; it never enables movement. It does not change volume. If volume is zero, adjust it using the robot's normal controls. `--speaker-id 1` is the English voice used in Unitree's SDK example; the actual voice/service must work on your firmware.

The installed SDK contains an increment bug in its TTS wrapper, so the app uses the same registered TTS API with increasing request indexes without modifying the vendor repository. TTS acceptance is not proof of audible playback.

## 4. Test one stationary gesture using text

Use the robot's normal controls to establish its appropriate standing/control mode, with clear space and its remote stop available.

```bash
python3 launch.py control --interface en5 --arm --no-voice
```

Type `help`, then one available action such as `wave`. Type `stop` and `quit` as needed. `greet` requests the onboard wave and introduction speech together. Other supported phrases include clap, handshake, hands up, hug, heart, high five, and kisses, **only when matched in the returned action list**. The program refuses simulation-only left/both waves without an exact supported preset.

Arm release is scheduled after three seconds; onboard action duration/release behavior must be verified. An SDK success code means accepted, not completed. Voice/text `stop` attempts to stop opted-in locomotion and release an arm pose; the remote remains necessary. State loss or command failures attempt a stop and lock further movement until restart.

## 5. Enable voice commands with the laptop microphone

```bash
python3 launch.py control --interface en5 --arm
```

The laptop microphone is the default input; the **robot speaker** is the default output. Add `--device INDEX` for another host microphone, `--speaker local` to explicitly use Mac speech, or `--speaker none` to disable audio. Typed commands remain available if recognition fails.

For optional physical walking, separately verify locomotion service/mode first, then add `--enable-walking`. Requests are bounded to one-second bursts with requested 0.4-second onboard expiry. This is not autonomous navigation, collision avoidance, or fall protection.

## 6. Ollama conversation through G1

Cloud-only check (no robot needed):

```bash
python3 launch.py conversation --check
```

Read-only robot-audio/cloud probe:

```bash
python3 launch.py conversation --interface en5 --probe --no-voice
```

Start with typed questions and robot spoken replies:

```bash
python3 launch.py conversation --interface en5 --no-voice
```

Then remove `--no-voice` for laptop-microphone conversation. No arm or locomotion services are opened by this app. The robot can speak even if custom movement access is unavailable, provided its audio service is supported. Your cloud key/model configuration is preserved. Probes/launch preflight use small cloud test requests and therefore some account allowance.

## 7. Optional G1 microphone

Unitree's published audio example receives 16 kHz mono 16-bit PCM from multicast group `239.168.123.161`, UDP port `5555`. This may not be available on every robot/firmware/network. The implementation fails explicitly if packets are absent; it does not silently switch microphones.

Find the laptop's IPv4 on the robot-facing adapter:

```bash
ipconfig getifaddr en5
```

Replace `HOST_IPV4` below with that result, **not the robot IP**:

```bash
python3 launch.py conversation --interface en5 --mic robot --interface-ip HOST_IPV4 --probe
python3 launch.py conversation --interface en5 --mic robot --interface-ip HOST_IPV4
```

For basic commands use the same `--mic robot --interface-ip HOST_IPV4` options with `control --arm`. Check that the microphone packets are from the intended robot/network. The probe receives/discards samples; it does not validate transcription accuracy or firmware format beyond the documented PCM assumption.

If unavailable, return to `--mic host` and use the laptop/USB microphone. Wired versus wireless multicast behavior depends on network configuration.

## Stopping and feedback

Input pauses while speaking to reduce echo. Onboard TTS duration is estimated because no playback-completion event is available in this adapter. Type `stop` (control) or `/stop` (conversation) to interrupt. The audio playback-stop API is best effort; it is **not verified to cancel onboard TTS on every firmware**. It does not affect the remote emergency stop. Cloud requests already sent cannot be withdrawn, although their replies can be discarded locally.

## PC-only commands remain available

```bash
python3 launch.py control-test
python3 launch.py conversation-test
```

## Verification performed

Local/mock tests cover command mapping, simulator limits/return to rest, motion timeout and state-loss handling, read-only probes, unique TTS request IDs, failed audio requests, multicast probe packet handling, and PC/hardware isolation. Hardware motion, audible speech, live microphone multicast, and compatibility with your specific G1 remain unverified.

SDK reference: https://github.com/unitreerobotics/unitree_sdk2/blob/main/example/g1/audio/g1_audio_client_example.cpp
