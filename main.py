import sys
import argparse

if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--etw-helper":
    from modules.advanced_capture import run_capture
    run_capture(sys.argv[2], sys.argv[3])
    raise SystemExit()

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from gui import App


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SysPulse — monitoramento e análise de performance")
    parser.add_argument("--demo", action="store_true", help="Abre dados simulados, sem coletar informações do computador")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    setup = parser.add_mutually_exclusive_group()
    setup.add_argument("--setup-local", action="store_true", help="Abre a preparação de um modelo local")
    setup.add_argument("--setup-online", action="store_true", help="Abre a configuração da conta na nuvem")
    options = parser.parse_args()
    application = QApplication(sys.argv)
    application.setApplicationName("SysPulse")
    application.setOrganizationName("SysPulse")
    window = App(demo=options.demo or options.smoke_test)
    window.show()
    if options.smoke_test:
        QTimer.singleShot(3000, application.quit)
    elif not options.demo:
        from modules.setup_wizard import configure_first_run
        selection = "local" if options.setup_local else "online" if options.setup_online else None
        QTimer.singleShot(0, lambda: configure_first_run(window, selection))
    sys.exit(application.exec())
