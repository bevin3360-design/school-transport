import sys
from pathlib import Path

# Tests must exercise the deployed app, not the stale copy at the repo root.
PLATFORM_DIR = Path(__file__).resolve().parents[1] / 'sts-platform'
sys.path.insert(0, str(PLATFORM_DIR))
