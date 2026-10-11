import sys
import argparse

from PySide6.QtWidgets import QApplication
from gui import App


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SysPulse — monitoramento e análise de performance")
    parser.add_argument("--demo", action="store_true", help="Abre dados simulados, sem coletar informações do computador")
    options = parser.parse_args()
    application = QApplication(sys.argv)
    window = App(demo=options.demo)
    window.show()
    sys.exit(application.exec())
