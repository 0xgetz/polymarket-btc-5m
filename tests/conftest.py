import sys
from pathlib import Path

# Make scripts/ importable for all test modules.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
