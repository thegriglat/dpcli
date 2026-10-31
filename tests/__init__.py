"""Lets `python3 -m unittest tests.test_x` run from the repo root: test modules import `helpers` directly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
