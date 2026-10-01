import sys
from pathlib import Path

# Let tests import the synthetic book builder next to them.
sys.path.insert(0, str(Path(__file__).parent))
