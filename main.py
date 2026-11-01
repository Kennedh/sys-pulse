import sys
import argparse

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    if len(sys.argv) == 3 and sys.argv[1] == "--stress-worker":
        from modules.stress import run_worker
        raise SystemExit(run_worker(sys.argv[2]))

if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--etw-helper":
    from modules.advanced_capture import run_capture
    run_capture(sys.argv[2], sys.argv[3])
    raise SystemExit()

if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from gui import App

    parser = argparse.ArgumentParser(description="SysPulse — monitoramento e análise de performance")
    parser.add_argument("--demo", action="store_true", help="Abre dados simulados, sem coletar informações do computador")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--setup-tools", action="store_true", help="Abre a preparação opcional do LatencyMon")
    setup = parser.add_mutually_exclusive_group()
    setup.add_argument("--setup-local", action="store_true", help="Abre a preparação de um modelo local")
    setup.add_argument("--setup-online", action="store_true", help="Abre a configuração online anônima")
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
        def configure():
            configure_first_run(window, selection)
            if options.setup_tools:
                window.show_page(5)
                window.inspection.tabs.setCurrentWidget(window.driver_tools)
        QTimer.singleShot(0, configure)
    sys.exit(application.exec())
