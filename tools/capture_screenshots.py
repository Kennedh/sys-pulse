import os
import sys
import time
import tempfile
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
from modules.ai_settings import AIConfig
from modules.ai_service import PROVIDERS
from PySide6.QtGui import QFont, QFontDatabase
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
    if os.name == "nt":
        font = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts" / "segoeui.ttf"
        font_id = QFontDatabase.addApplicationFont(str(font))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            application.setFont(QFont(families[0]))
    temporary = tempfile.TemporaryDirectory(prefix="syspulse-demo-")
    settings = QSettings(str(Path(temporary.name) / "demo.ini"), QSettings.IniFormat)
    def demo_config(activity):
        config = AIConfig(activity, settings)
        config.demo = True
        config.save({**PROVIDERS["ollama"], "provider": "ollama", "model": "llama3.2:3b", "key": ""})
        return config
    with patch("gui.AIConfig", side_effect=demo_config):
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
                                    ("sensores.png", 4, 5), ("drivers.png", 5, 0), ("avancado.png", 6, 0), ("ia-opcional.png", 6, -1),
                                    ("configuracoes.png", 7, 0), ("live.png", 1, 0), ("hardware.png", 0, 0), ("rede.png", 2, 0), ("estresse.png", 8, 0), ("evolucao.png", 4, 9)):
            window.show_page(page)
            window.analysis.tabs.setCurrentIndex(tab)
            if page == 6:
                window.advanced.tabs.setCurrentIndex(window.advanced.tabs.indexOf(window.advanced.ai) if tab == -1 else tab)
            if filename == "marcacoes.png":
                window.analysis.event_picker.setCurrentIndex(1)
            pump(application)
            assert window.grab().save(str(output / filename))
            print(output / filename)
        panel = window.settings_panel
        window.show_page(7)
        panel.choose_mode("advanced")
        panel.key.setText("credencial-simulada")
        panel.accept_models(panel._generation, ["demonstracao/modelo-compacto:free", "demonstracao/modelo-texto"], "")
        pump(application)
        assert window.grab().save(str(output / "conectar-ia.png"))
        panel.service.setCurrentIndex(panel.service.findData("custom"))
        panel.endpoint.setText("http://localhost:1234/v1")
        panel.api_format.setCurrentIndex(panel.api_format.findData("responses"))
        panel.accept_models(panel._generation, ["modelo-local-demonstracao"], "")
        pump(application)
        assert window.grab().save(str(output / "servidor-ia.png"))
    finally:
        window.shutdown()
        window.close()
        settings.sync()
        temporary.cleanup()


if __name__ == "__main__":
    main()
