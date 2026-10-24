# G1 voice control

`g1_voice_control.py` defaults to the existing MuJoCo simulator. It does not send simulated joint angles to hardware.

## Simulation

```bash
cd /Users/nishan/G1-Smart-AI
.venv-g1/bin/python g1_voice_control.py
```

Use `--no-voice` for typed commands or `--list` to list simulation commands.

## Read-only connection check

Connect the computer to the robot network using the network settings for your actual robot. Identify the robot-facing interface (`en5` below is an example, not a detected interface). On macOS, `networksetup -listallhardwareports` helps identify adapters.

```bash
.venv-g1/bin/python g1_voice_control.py --hardware --interface en5
```

This receives `rt/lowstate` on DDS domain 0 and calls `GetActionList()`. It sends no motion requests. The robot must supply both the state stream and the arm action service. A timeout does not establish that your robot lacks the capability: check the interface, network, firmware, and active robot services.

The printed raw action list is matched against the installed SDK's known names and IDs. Unknown layouts, unmatched IDs, and custom teach actions are not enabled automatically. If discovery returns a different format, retain that output for updating the adapter.

## Physical gestures

Once the read-only check works, put the robot in its appropriate standing/control mode using Unitree's normal controls. Keep the area clear and the robot remote available. The program does not change operating modes, disable torque, or stand the robot up.

```bash
.venv-g1/bin/python g1_voice_control.py --hardware --interface en5 --arm
```

Say `help` or type it in this terminal to see the robot's discovered actions. Try one stationary action first, such as `wave hello`. The program sends the onboard wave action and schedules an arm release after three seconds. Some onboard actions may run longer or handle release differently; a successful SDK response is acceptance, not confirmation of physical completion.

- `wave hello` maps to a discovered high wave or face wave.
- Other gestures run only when their name and ID are matched in the returned action list.
- `left wave` and `both wave` have no automatic physical equivalent in this bridge.
- `stop` / `arms down` attempts to stop opted-in locomotion and release the arm. This is not a hardware emergency stop, and it cannot guarantee delivery after network loss.
- `quit` or Ctrl+C attempts to stop any tracked action before exiting.
- Busy commands are discarded with a message; they are not queued for later movement.
- Missing state updates or SDK failures lock out further movement until restart.

## Optional physical walking

Verify the robot's supported locomotion service and operating mode first. The additional flag explicitly enables physical locomotion requests:

```bash
.venv-g1/bin/python g1_voice_control.py --hardware --interface en5 --arm --enable-walking
```

Commands: `walk`, `walk backward`, `turn left`, `turn right`, `stop`.

Movement is limited to one second per utterance. Requests use 0.10 m/s translation or 0.15 rad/s turning, refreshed with a 0.4-second requested onboard duration. The computer stops refreshing and attempts a zero-velocity request on completion or a stale state stream. These are requested limits; actual robot behavior and timeout semantics still need validation on its firmware. No obstacles, navigation, fall detection, or independent emergency-stop mechanism are implemented.

## Microphone

Append `--device 1` (use the correct audio-device index) or `--no-voice`. Voice recognition uses the existing Vosk model and microphone on the computer. There is no requirement to install Vosk on the robot.

## Validation performed

Mock-client tests cover read-only probing, default simulation isolation, discovery filtering, unsupported commands, bounded walking requests, busy-command rejection, timed arm release, stale-state shutdown, and RPC failure handling. Physical connectivity, firmware compatibility, and robot movement have not been tested because no robot is connected.
