"""Convenience entry point: use the current project launcher from archive/."""
from pathlib import Path
import runpy
import sys
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
runpy.run_path(str(root / 'launch.py'), run_name='__main__')
