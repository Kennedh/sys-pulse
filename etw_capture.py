import sys

from modules.advanced_capture import run_capture


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Uso interno: etw_capture.py pasta identificacao")
    run_capture(sys.argv[1], sys.argv[2])
