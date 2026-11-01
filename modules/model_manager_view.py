import os
import shutil
import threading
from pathlib import Path

from PySide6.QtCore import Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                              QComboBox, QProgressBar, QMessageBox)

from modules.model_manager import (LOCAL_MODELS, OllamaRuntime, DownloadCancelled, pull_model,
                                   runtime_url, validate_model, cloud_model)


class ModelManagerPanel(QWidget):
    progressed = Signal(dict)
    finished = Signal(object, str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.runtime = OllamaRuntime()
        self._cancel = threading.Event()
        self._closed = False
        self._working = False
        self._kind = None
        self.prepare_settings = lambda: True
        self.provider = None
        layout = QVBoxLayout(self)
        title = QLabel("Preparar IA sem aumentar o instalador")
        title.setObjectName("title")
        layout.addWidget(title)
        self.info = QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        controls = QHBoxLayout()
        self.install = QPushButton("1 · Baixar Ollama")
        self.install.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(runtime_url())))
        self.detect = QPushButton("2 · Detectar / iniciar Ollama")
        self.detect.clicked.connect(lambda: self.run_job("runtime"))
        self.signin = QPushButton("Entrar na conta Ollama")
        self.signin.clicked.connect(lambda: self.run_job("signin"))
        for button in (self.install, self.detect, self.signin):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.catalog = QComboBox()
        self.catalog.setEditable(True)
        layout.addWidget(self.catalog)
        row = QHBoxLayout()
        self.download = QPushButton("3 · Baixar modelo escolhido")
        self.download.clicked.connect(self.request_download)
        self.cancel = QPushButton("Cancelar")
        self.cancel.clicked.connect(self.cancel_job)
        row.addWidget(self.download, 1)
        row.addWidget(self.cancel)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel("Nenhum download ou modelo iniciado.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progressed.connect(self.on_progress)
        self.finished.connect(self.on_finished)
        config.activity.changed.connect(self.update_state)
        self.set_provider(config.provider)

    def set_provider(self, provider):
        self.provider = provider
        cloud = provider == "ollama_cloud"
        self.catalog.clear()
        if cloud:
            self.catalog.addItem("gpt-oss:120b-cloud")
        else:
            for name, label, size in LOCAL_MODELS:
                self.catalog.addItem(label, name)
        self.info.setText(
            "Use a conta do Ollama, sem colar chave no SysPulse. A inferência ocorre na nuvem; o provedor controla acesso, cotas e cobranças. "
            "O login abre no navegador. Preparar o modelo registra a referência, sem baixar seus pesos."
            if cloud else
            "O Ollama é instalado separadamente. Depois, escolha o modelo para baixar. Download ocupa disco e internet; RAM/VRAM são usadas na análise. "
            "O tamanho indicado é aproximado. O modelo fica no armazenamento do Ollama, separado da pasta do SysPulse.")
        self.signin.setVisible(cloud)
        self.download.setText("3 · Preparar modelo na nuvem" if cloud else "3 · Baixar modelo escolhido")
        self.update_state()

    def chosen_model(self):
        index = self.catalog.currentIndex()
        if index >= 0 and self.catalog.currentText() == self.catalog.itemText(index):
            return self.catalog.itemData(index) or self.catalog.currentText()
        return self.catalog.currentText().strip()

    def request_download(self):
        if self.config.activity.busy:
            return
        if not self.prepare_settings():
            return
        try:
            name = validate_model(self.chosen_model())
            cloud = self.config.provider == "ollama_cloud"
            if cloud != cloud_model(name):
                raise ValueError("Escolha Local para modelos baixados ou Nuvem via Ollama para modelos cloud.")
            if not cloud:
                estimate = next((size for model, _, size in LOCAL_MODELS if model == name), None)
                location = Path(os.environ.get("OLLAMA_MODELS", str(Path.home() / ".ollama/models"))).expanduser()
                existing = location
                while not existing.exists() and existing != existing.parent:
                    existing = existing.parent
                if estimate and shutil.disk_usage(existing).free < estimate * 1.2:
                    raise ValueError("Pouco espaço no volume estimado dos modelos. Confira OLLAMA_MODELS no servidor.")
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
            return
        text = (f"Preparar {name} pelo Ollama?\nOs pesos ficam na nuvem. A análise pode usar a cota ou saldo da sua conta."
                if cloud else
                f"Baixar {name}?\nO download usa internet e disco e segue a licença do modelo. Não inicia inferência.\n"
                "O Ollama gerencia a pasta e preserva camadas parciais para uma nova tentativa.")
        if QMessageBox.question(self, "Preparar modelo", text) == QMessageBox.Yes:
            self.run_job("pull", name)

    def run_job(self, kind, name=None):
        if self._working:
            return
        if not self.prepare_settings():
            return
        try:
            self.config.activity.begin_maintenance("models")
        except RuntimeError as error:
            self.status.setText(str(error))
            return
        self._working, self._kind = True, kind
        self._cancel = cancelled = threading.Event()
        endpoint = self.config.endpoint
        self.progress.setRange(0, 0)
        self.status.setText({"pull": "Preparando download…", "runtime": "Procurando Ollama…",
                             "signin": "Entre na conta pelo navegador aberto pelo Ollama."}[kind])
        self.update_state()

        def run():
            result, error = None, ""
            try:
                if kind == "pull":
                    result = {"model": pull_model(endpoint, name, self.report_progress, cancelled.is_set)}
                elif kind == "runtime":
                    result = self.runtime.start(endpoint, cancelled.is_set)
                else:
                    result = self.runtime.signin(endpoint, cancelled.is_set)
            except DownloadCancelled:
                error = "Operação cancelada. Downloads parciais podem ser retomados pelo Ollama."
            except Exception as exception:
                error = str(exception)
            finally:
                self.config.activity.end_maintenance("models")
            if not self._closed:
                self.finished.emit(result, error)
        threading.Thread(target=run, name="sys-pulse-model-setup", daemon=True).start()

    def report_progress(self, item):
        if not self._closed:
            self.progressed.emit(item)

    def on_progress(self, item):
        total, complete = item.get("total"), item.get("completed", 0)
        if isinstance(total, (int, float)) and total > 0 and isinstance(complete, (int, float)):
            self.progress.setRange(0, 100)
            self.progress.setValue(max(0, min(100, int(complete * 100 / total))))
            self.status.setText(f"Camada do modelo · {complete / 1024 ** 2:.1f} / {total / 1024 ** 2:.1f} MiB")
        else:
            self.status.setText({"success": "Modelo disponível.", "pulling manifest": "Consultando modelo…",
                                 "verifying sha256 digest": "Conferindo integridade…",
                                 "writing manifest": "Finalizando modelo…"}.get(item.get("status"), "Preparando modelo…"))

    def on_finished(self, result, error):
        self._working = False
        self.progress.setRange(0, 100)
        self.progress.setValue(0 if error else 100)
        if error:
            self.status.setText(error)
        elif result and result.get("model"):
            values = self.config.values()
            values["remember_key"] = self.config.remember_key
            values["model"] = result["model"]
            try:
                self.config.save(values)
                self.status.setText(f"{result['model']} disponível e selecionado. Nenhuma inferência foi iniciada.")
            except (ValueError, OSError) as exception:
                self.status.setText("Modelo baixado. Selecione-o em Configurações. " + str(exception))
        else:
            self.status.setText((result or {}).get("message") or "Ollama pronto. Escolha um modelo para preparar.")
        self.update_state()

    def cancel_job(self):
        self._cancel.set()
        self.status.setText("Cancelando… aguardando o encerramento da conexão.")
        self.cancel.setEnabled(False)

    def update_state(self):
        available = not self.config.activity.busy and not self._working
        for widget in (self.install, self.detect, self.signin, self.catalog, self.download):
            widget.setEnabled(available)
        self.cancel.setEnabled(self._working and not self._cancel.is_set())

    def shutdown(self):
        self._closed = True
        self._cancel.set()
        self.runtime.close()
