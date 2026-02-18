import sys
from pathlib import Path

# Add the parent directory to the path so we can import main
sys.path.append(str(Path(__file__).parent.parent))

from main import app
