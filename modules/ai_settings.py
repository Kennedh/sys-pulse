import threading
import hashlib

from PySide6.QtCore import QObject, QSettings, Signal, QUrl, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel,
                              QComboBox, QLineEdit, QPushButton, QSpinBox, QGroupBox, QCheckBox, QRadioButton, QButtonGroup, QGridLayout)

from modules.activity import ActivityState
from modules.credentials import CredentialStore
from modules.ai_service import PROVIDERS, list_models, validate_endpoint
from modules.model_manager_view import ModelManagerPanel


class AIConfig(QObject):
    changed = Signal()

    def __init__(self, activity=None, settings=None):
        super().__init__()
        self.activity = activity or ActivityState()
        self.settings = settings or QSettings("SysPulse", "SysPulse")
        provider = self.settings.value("ai/provider", "horde")
        self.provider = provider if provider in PROVIDERS else "ollama"
        preset = PROVIDERS[self.provider]
        self.endpoint = self.settings.value("ai/endpoint", preset["endpoint"])
        self.model = self.settings.value("ai/model", preset["model"])
        self.answer_tokens = int(self.settings.value("ai/answer_tokens", 900))
        self.store = CredentialStore()
        self.remember_key = self.settings.value("ai/remember_key", False, type=bool)
        self.key = self.store.read(self.provider) if self.remember_key else ""
        self.enabled = self.settings.value("ai/enabled", True, type=bool)
        self.cache = {}
        self._keys = {self.provider: self.key}
        self.verified = set()
        self.demo = False
        self._remember_current()

    def _remember_current(self):
        prefix = "ai/providers/" + self.provider
        for key in ("model", "endpoint"):
            if not self.settings.contains(prefix + "/" + key):
                self.settings.setValue(prefix + "/" + key, getattr(self, key))

    def preferences(self, provider):
        preset = PROVIDERS[provider]
        prefix = "ai/providers/" + provider
        remember = self.settings.value(prefix + "/remember", self.remember_key if provider == self.provider else False, type=bool)
        key = self._keys.get(provider)
        if key is None:
            key = self.store.read(provider) if remember and provider not in ("horde", "ollama", "ollama_cloud") else ""
        return {"provider": provider, "endpoint": self.settings.value(prefix + "/endpoint", preset["endpoint"]),
                "model": self.settings.value(prefix + "/model", preset["model"]), "key": key, "remember_key": remember}

    def identity(self):
        digest = hashlib.sha256(self.key.encode()).hexdigest()
        return self.provider, self.endpoint, self.model, digest

    def mark_verified(self):
        self.verified.add(self.identity())

    @property
    def is_verified(self):
        return self.identity() in self.verified

    def values(self):
        return {"provider": self.provider, "endpoint": self.endpoint, "model": self.model,
                "key": self.key, "answer_tokens": self.answer_tokens, "structured": True, "enabled": self.enabled}

    def save(self, values):
        validate_endpoint(values["endpoint"])
        provider = values["provider"]
        if provider not in PROVIDERS:
            raise ValueError("Provedor inválido.")
        key = values.get("key", "")
        remember = bool(values.get("remember_key", False)) and provider not in ("horde", "ollama", "ollama_cloud")
        if remember and key:
            self.store.write(provider, key)
        elif self.settings.value("ai/providers/" + provider + "/remember", False, type=bool):
            self.store.delete(provider)
        self.provider, self.endpoint = provider, values["endpoint"].strip()
        self.model, self.key = values["model"].strip(), key
        self.enabled = bool(values.get("enabled", True))
        self.answer_tokens = max(128, min(2400, int(values.get("answer_tokens", 900))))
        self.remember_key = remember
        self._keys[provider] = key
        self.settings.setValue("ai/enabled", self.enabled)
        self.settings.setValue("ai/remember_key", remember)
        self.settings.setValue("ai/providers/" + provider + "/remember", remember)
        for name in ("model", "endpoint"):
            self.settings.setValue("ai/providers/" + provider + "/" + name, getattr(self, name))
        for name in ("provider", "endpoint", "model", "answer_tokens"):
            self.settings.setValue("ai/" + name, getattr(self, name))
        self.changed.emit()


def suggested_model(provider, models, current=""):
    if current in models:
        return current
    if provider == "horde":
        return "auto" if "auto" in models else models[0] if models else ""
    preferences = {"ollama": ("llama3.2:3b", "qwen3:0.6b", "llama3.2:1b"),
                   "anthropic": ("haiku", "sonnet"), "openai": ("nano", "mini"),
                   "gemini": ("flash-lite", "flash"), "openrouter": (":free", "free")}
    for token in preferences.get(provider, ()):
        match = next((model for model in models if token in model.lower()), None)
        if match:
            return match
    return models[0] if models else ""


class AISettingsPanel(QWidget):
    listed = Signal(int, object, str)

    def __init__(self, config):
        super().__init__()
        self.config, self._closed, self._busy = config, False, False
        self._generation = 0
        self._known_models = []
        self._syncing = False
        layout = QVBoxLayout(self)
        title = QLabel("Escolha quem vai analisar")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel("Conecte uma vez, escolha o modelo e confira a confirmação. A coleta funciona sem IA; nenhum modelo trabalha durante a captura.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        choices = QHBoxLayout()
        self.modes, self.mode_buttons = {}, {}
        self.mode_group = QButtonGroup(self)
        self.card_group = QButtonGroup(self)
        for mode, label in (("integrated", "Integrada\nSem IA"), ("horde", "Online gratuita\nSem conta"),
                            ("ollama", "Local neste PC\nOllama / Llama"), ("advanced", "Conectar minha IA\nClaude, GPT, Gemini…")):
            proxy = QRadioButton(self)
            proxy.hide()
            self.mode_group.addButton(proxy)
            self.modes[mode] = proxy
            button = QPushButton(label)
            button.setObjectName("aiMode")
            button.setCheckable(True)
            button.setMinimumHeight(64)
            button.clicked.connect(lambda checked=False, key=mode: self.choose_mode(key))
            self.card_group.addButton(button)
            self.mode_buttons[mode] = button
            choices.addWidget(button)
        layout.addLayout(choices)
        self.active = QLabel()
        self.active.setObjectName("card")
        self.active.setWordWrap(True)
        layout.addWidget(self.active)
        self.connection = QGroupBox("Conexão e modelo")
        connection_layout = QVBoxLayout(self.connection)
        form = QFormLayout()
        self.form = form
        self.provider = QComboBox(self)
        for key, preset in PROVIDERS.items():
            self.provider.addItem(preset["name"], key)
        self.provider.hide()
        self.service = QComboBox()
        for key in ("anthropic", "openai", "gemini", "openrouter", "lmstudio", "ollama_cloud", "custom"):
            self.service.addItem(PROVIDERS[key]["name"], key)
        form.addRow("Qual serviço você usa?", self.service)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Cole aqui sua chave de API")
        self.key_row = QWidget()
        key_layout = QHBoxLayout(self.key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.addWidget(self.key, 1)
        self.guide = QPushButton("Obter minha chave")
        self.guide.clicked.connect(self.open_guide)
        key_layout.addWidget(self.guide)
        form.addRow("Credencial", self.key_row)
        self.remember = QCheckBox("Guardar no cofre do Windows")
        form.addRow("", self.remember)
        self.model = QComboBox()
        self.model.setMinimumWidth(250)
        form.addRow("Modelo que será usado", self.model)
        connection_layout.addLayout(form)
        self.help = QLabel()
        self.help.setWordWrap(True)
        connection_layout.addWidget(self.help)
        controls = QHBoxLayout()
        self.check = QPushButton("Conectar e buscar modelos")
        self.check.clicked.connect(self.discover)
        self.save = QPushButton("Usar este modelo")
        self.save.clicked.connect(self.apply)
        controls.addWidget(self.check)
        controls.addWidget(self.save)
        connection_layout.addLayout(controls)
        self.status = QLabel()
        self.status.setWordWrap(True)
        connection_layout.addWidget(self.status)
        self.connection_options = QGroupBox("Opções avançadas")
        self.connection_options.setCheckable(True)
        self.connection_options.setChecked(False)
        advanced = QFormLayout(self.connection_options)
        self.endpoint = QLineEdit()
        self.tokens = QSpinBox()
        self.tokens.setRange(128, 2400)
        self.tokens.setValue(config.answer_tokens)
        advanced.addRow("Endereço da API", self.endpoint)
        advanced.addRow("Limite da resposta", self.tokens)
        self.advanced_body = (self.endpoint, self.tokens, advanced.labelForField(self.endpoint), advanced.labelForField(self.tokens))
        for field in self.advanced_body:
            field.hide()
        self.connection_options.toggled.connect(lambda visible: [field.setVisible(visible) for field in self.advanced_body])
        connection_layout.addWidget(self.connection_options)
        layout.addWidget(self.connection)
        self.download_group = QGroupBox("Adicionar um modelo local · download opcional")
        self.download_group.setCheckable(True)
        self.download_group.setChecked(False)
        downloads = QVBoxLayout(self.download_group)
        self.models = ModelManagerPanel(config)
        self.models.prepare_settings = self.prepare_model_setup
        self.models.prepared.connect(lambda name: self.schedule_discovery())
        self.models.hide()
        downloads.addWidget(self.models)
        self.download_group.toggled.connect(self.models.setVisible)
        layout.addWidget(self.download_group)
        layout.addStretch()
        self.auto_timer = QTimer(self)
        self.auto_timer.setSingleShot(True)
        self.auto_timer.setInterval(500)
        self.auto_timer.timeout.connect(self.discover)
        self.provider.currentIndexChanged.connect(self.use_preset)
        self.service.currentIndexChanged.connect(self.select_service)
        self.model.currentIndexChanged.connect(self.select_model)
        self.key.textEdited.connect(self.credential_edited)
        self.key.editingFinished.connect(self.schedule_discovery)
        self.listed.connect(self.accept_models)
        config.activity.changed.connect(self.update_state)
        config.changed.connect(self.sync_config)
        self._set_provider(config.provider)
        self.sync_mode()
        self.update_state()

    def mode(self):
        return next((key for key, button in self.modes.items() if button.isChecked()), "horde")

    def choose_mode(self, mode):
        if self.config.activity.busy:
            return
        self.modes[mode].setChecked(True)
        if mode == "advanced":
            provider = self.service.currentData()
        elif mode == "integrated":
            self.config.save({**self.config.values(), "remember_key": self.config.remember_key, "enabled": False})
            self.sync_mode()
            return
        else:
            provider = mode
        self._set_provider(provider)
        self.modes[mode].setChecked(True)
        if mode == "horde":
            self.apply()
        elif mode == "ollama":
            self.apply()
        self.update_mode_controls()
        self.schedule_discovery()

    def _set_provider(self, provider):
        self._syncing = True
        self.provider.setCurrentIndex(self.provider.findData(provider))
        self._load_provider(provider)
        self._syncing = False

    def _load_provider(self, provider):
        self._generation += 1
        self._busy = False
        self._known_models = []
        preferences = self.config.preferences(provider)
        self.endpoint.setText(preferences["endpoint"])
        self.key.setText(preferences["key"])
        self.remember.setChecked(preferences["remember_key"])
        self.model.blockSignals(True)
        self.model.clear()
        current = preferences["model"]
        if current:
            self.model.addItem("Automático · modelo disponível na fila" if current == "auto" else current, current)
        self.model.setEditable(provider == "custom")
        self.model.blockSignals(False)
        service_index = self.service.findData(provider)
        if service_index >= 0:
            self.service.blockSignals(True)
            self.service.setCurrentIndex(service_index)
            self.service.blockSignals(False)
        self.help.setText(PROVIDERS[provider]["help"])
        if self.models.provider != provider:
            self.models.set_provider(provider)
        self.status.setText("Modelo salvo; disponibilidade ainda não conferida." if current else "Conecte o serviço para carregar os modelos da sua conta.")
        self.update_mode_controls()

    def use_preset(self):
        if self._syncing:
            return
        self._load_provider(self.provider.currentData())
        mode = self.provider.currentData() if self.provider.currentData() in ("horde", "ollama") else "advanced"
        self.modes[mode].setChecked(True)
        self.update_mode_controls()
        self.schedule_discovery()

    def select_service(self):
        if self._syncing:
            return
        self._set_provider(self.service.currentData())
        self.modes["advanced"].setChecked(True)
        self.update_mode_controls()
        self.schedule_discovery()

    def model_id(self):
        if self.model.isEditable() and self.model.currentText() != self.model.itemText(self.model.currentIndex()):
            return self.model.currentText().strip()
        return self.model.currentData() or self.model.currentText().strip()

    def values(self):
        return {"provider": self.provider.currentData(), "endpoint": self.endpoint.text().strip(),
                "model": self.model_id(), "key": self.key.text().strip(), "answer_tokens": self.tokens.value(),
                "remember_key": self.remember.isChecked(), "enabled": self.mode() != "integrated"}

    def sync_mode(self):
        mode = "integrated" if not self.config.enabled else self.config.provider if self.config.provider in ("horde", "ollama") else "advanced"
        self.modes[mode].setChecked(True)
        self.update_mode_controls()

    def sync_config(self):
        if self.config.provider == self.provider.currentData() and self.config.model:
            self.model.blockSignals(True)
            index = next((i for i in range(self.model.count()) if (self.model.itemData(i) or self.model.itemText(i)) == self.config.model), -1)
            if index < 0:
                self.model.addItem(self.config.model, self.config.model)
                index = self.model.count() - 1
            self.model.setCurrentIndex(index)
            self.model.blockSignals(False)
        self.update_active()

    def update_active(self):
        if not self.config.enabled:
            self.active.setText("EM USO · Análise integrada\nSem modelo, conta ou envio de dados.")
        else:
            verified = "disponibilidade conferida" if self.config.is_verified else "disponibilidade ainda não conferida"
            model = "automático na fila" if self.config.model == "auto" else self.config.model or "modelo não escolhido"
            self.active.setText(f"EM USO · {PROVIDERS[self.config.provider]['name']}\n{model} · {verified}")
        self.save.setText("Modelo em uso" if self.model_id() == self.config.model and self.provider.currentData() == self.config.provider and self.config.enabled else "Usar este modelo")

    def update_key_fields(self):
        visible = self.mode() == "advanced" and self.provider.currentData() not in ("ollama_cloud", "lmstudio")
        self.key_row.setVisible(visible)
        self.form.labelForField(self.key_row).setVisible(visible)
        self.key.setVisible(visible)
        self.remember.setVisible(visible)
        self.guide.setText("Obter minha chave" if visible else "Abrir instruções")

    def update_mode_controls(self):
        mode = self.mode()
        self.connection.setVisible(mode != "integrated")
        for key, button in self.mode_buttons.items():
            button.setChecked(key == mode)
        advanced = mode == "advanced"
        self.service.setVisible(advanced)
        self.form.labelForField(self.service).setVisible(advanced)
        show_model = mode not in ("integrated", "horde")
        self.model.setVisible(show_model)
        self.form.labelForField(self.model).setVisible(show_model)
        self.save.setVisible(show_model)
        self.connection_options.setVisible(advanced and self.provider.currentData() in ("custom", "lmstudio"))
        self.download_group.setVisible(mode == "ollama" or advanced and self.provider.currentData() == "ollama_cloud")
        self.update_key_fields()
        self.update_active()
        self.update_state()

    def apply(self):
        if self.config.activity.busy or self._busy:
            return False
        values = self.values()
        if values["enabled"] and not values["model"]:
            self.status.setText("Conecte o serviço e escolha um modelo da lista.")
            return False
        try:
            self.config.save(values)
            self.status.setText("Seleção salva. O modelo só trabalha quando você solicitar a análise.")
            return True
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
            return False

    def prepare_model_setup(self):
        if self.config.activity.busy:
            return False
        values = self.values()
        if not values["model"]:
            values["model"] = PROVIDERS[values["provider"]]["model"]
        try:
            self.config.save(values)
            return True
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
            return False

    def select_model(self):
        if not self._syncing and self.model_id() in self._known_models and not self._busy:
            if self.apply():
                self.config.mark_verified()
                self.config.changed.emit()

    def credential_edited(self):
        self._generation += 1
        self._busy = False
        if len(self.key.text().strip()) >= 12:
            self.schedule_discovery()

    def schedule_discovery(self):
        if not self.config.demo and not self._closed and self.mode() != "integrated":
            self.auto_timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        self.schedule_discovery()

    def discover(self):
        if self.config.activity.busy or self._busy or self._closed or self.mode() == "integrated":
            return
        values = self.values()
        provider = values["provider"]
        if provider in ("anthropic", "openai", "gemini", "openrouter") and not values["key"]:
            self.status.setText("1 · Abra o painel pelo botão Obter minha chave. 2 · Cole a chave aqui; os modelos serão carregados automaticamente.")
            return
        try:
            validate_endpoint(values["endpoint"])
        except ValueError as error:
            self.status.setText(str(error))
            return
        self._generation += 1
        generation = self._generation
        local_runtime = provider in ("ollama", "ollama_cloud")
        if local_runtime:
            try:
                self.config.activity.begin_maintenance("model_discovery")
            except RuntimeError as error:
                self.status.setText(str(error))
                return
        self._busy = True
        self.status.setText("Conectando e buscando modelos… nenhum modelo será carregado.")
        self.update_state()
        def run():
            try:
                if local_runtime:
                    self.models.runtime.start(values["endpoint"], lambda: self._closed)
                models, error = list_models(values), ""
            except Exception as exception:
                models, error = [], str(exception)
            finally:
                if local_runtime:
                    self.config.activity.end_maintenance("model_discovery")
            if not self._closed:
                self.listed.emit(generation, models, error)
        threading.Thread(target=run, name="sys-pulse-model-list", daemon=True).start()

    def accept_models(self, generation, models, error):
        if generation != self._generation or self._closed:
            return
        self._busy = False
        self._known_models = models
        if error:
            self.status.setText(error + " A seleção anterior continua salva.")
            if self.mode() == "ollama":
                self.download_group.setChecked(True)
        elif not models:
            self.status.setText("Nenhum modelo disponível. Instale ou baixe um modelo para continuar.")
            if self.mode() == "ollama":
                self.download_group.setChecked(True)
        else:
            provider = self.provider.currentData()
            current = self.model_id()
            choice = suggested_model(provider, models, current)
            self.model.blockSignals(True)
            self.model.clear()
            for model in models:
                self.model.addItem(model + (" · sugestão econômica" if model == choice and not current else ""), model)
            self.model.setCurrentIndex(models.index(choice))
            self.model.blockSignals(False)
            if self.apply():
                self.config.mark_verified()
                self.config.changed.emit()
                self.status.setText(f"Pronto · {len(models)} modelo(s) disponível(is). Modelo selecionado: {choice}.")
            else:
                self.status.setText("Modelos disponíveis. Use este modelo depois da captura ou da análise atual.")
        self.update_state()

    def update_state(self):
        available = not self.config.activity.busy
        for button in (*self.modes.values(), *self.mode_buttons.values()):
            button.setEnabled(available)
        for widget in (self.provider, self.service, self.key, self.model, self.endpoint, self.tokens):
            widget.setEnabled(available)
        self.check.setEnabled(available and not self._busy)
        self.save.setEnabled(available and not self._busy)
        self.remember.setEnabled(available and self.config.store.api is not None)

    def open_guide(self):
        url = PROVIDERS[self.provider.currentData()]["url"]
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def shutdown(self):
        self._closed = True
        self.auto_timer.stop()
        self.models.shutdown()
