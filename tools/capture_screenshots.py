import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication
from gui import App
from modules.demo import write_demo_session


def pump(app, seconds=.2):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(.01)


def main():
    write_demo_session(ROOT / "examples" / "sessao-demo")
    output = ROOT / "docs" / "images"
    output.mkdir(parents=True, exist_ok=True)
    application = QApplication([])
    window = App(demo=True)
    window.resize(1360, 920)
    window.show()
    try:
        deadline = time.monotonic() + 10
        while window.analysis.result is None and time.monotonic() < deadline:
            pump(application)
        assert window.analysis.result, window.analysis.status.text()
        for filename, page, tab in (("analise.png", 4, 1), ("explicacao.png", 4, 0), ("processos.png", 4, 2),
                                    ("marcacoes.png", 4, 3), ("captura.png", 3, 0), ("triagem.png", 4, 4),
                                    ("sensores.png", 4, 5), ("drivers.png", 5, 0), ("avancado.png", 6, 0), ("ia-opcional.png", 6, 3)):
            window.show_page(page)
            window.analysis.tabs.setCurrentIndex(tab)
            if page == 6:
                window.advanced.tabs.setCurrentIndex(tab)
            if filename == "marcacoes.png":
                window.analysis.event_picker.setCurrentIndex(1)
            pump(application)
            assert window.grab().save(str(output / filename))
            print(output / filename)
    finally:
        window.shutdown()
        window.close()


if __name__ == "__main__":
    main()
