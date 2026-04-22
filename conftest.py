# conftest.py — ensures the project root and lambda source are on sys.path for pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "lambda" / "import_documents"))
