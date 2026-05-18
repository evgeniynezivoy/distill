from pathlib import Path
import sys

BRAIN_ROOT = Path(__file__).resolve().parent.parent  # ~/brain
BIN_DIR = Path(__file__).resolve().parent             # ~/brain/.bin

sys.path.insert(0, str(BIN_DIR))
