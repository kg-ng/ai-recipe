"""Shared pytest fixtures. Ensures `src/` is importable as the package root
regardless of the directory pytest is invoked from."""
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
