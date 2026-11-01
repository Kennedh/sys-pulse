import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_release import main


if __name__ == "__main__":
    sys.argv.append("--skip-freeze")
    main()
