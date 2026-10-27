import pathlib
import sys

# the module runs as `python src/main.py`: its files import each other from src/, and so do the tests
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
