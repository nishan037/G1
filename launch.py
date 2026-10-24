"""G1 PC-test and physical deployment launchers; preflight runs before apps."""
import argparse
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parent
APPS = {
    'control-test': 'apps/g1_control_test.py',
    'conversation-test': 'apps/g1_conversation_test.py',
    'control': 'apps/g1_control.py',
    'hardware': 'apps/g1_control.py',
    'conversation': 'apps/g1_conversation.py',
    'vision': 'apps/vision/object_detection.py',
}

def main():
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument('app', choices=(*APPS, 'test', 'check'))
    if len(sys.argv) == 1 or sys.argv[1] in ('-h', '--help'):
        parser.print_help(); return 0
    args, extra = parser.parse_known_args()
    if args.app == 'check':
        from preflight import main as check_main
        sys.argv = [str(ROOT / 'preflight.py'), *extra]
        return check_main()
    if args.app != 'test' and not any(flag in extra for flag in ('--help', '-h', '--list', '--devices', '--models', '--check')):
        from preflight import run_checks
        if not run_checks(args.app, extra): return 1
    if args.app == 'test':
        command = [str(ROOT / '.venv-g1/bin/python'), '-m', 'unittest', 'discover', '-s', str(ROOT / 'tests'), '-p', 'test_*.py', *extra]
    else:
        runtime = '.venv/bin/python' if args.app == 'vision' else '.venv-g1/bin/python'
        if args.app == 'control-test' and '--hardware' not in extra and not any(flag in extra for flag in ('--help','-h','--list','--devices')):
            runtime = '.venv-g1/bin/mjpython'
        command = [str(ROOT / runtime), str(ROOT / APPS[args.app]), *extra]
    try: return subprocess.call(command, cwd=ROOT)
    except KeyboardInterrupt: return 130

if __name__ == '__main__': raise SystemExit(main())
