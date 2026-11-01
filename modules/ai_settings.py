import threading
import hashlib

from PySide6.QtCore import QObject, QSettings, Signal, QUrl, QTimer, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel,
                              QComboBox, QLineEdit, QPushButton, QSpinBox, QGroupBox, QCheckBox, QRadioButton, QButtonGroup, QCompleter)

from modules.activity import ActivityState
from modules.credentials import CredentialStore
from modules.ai_service import PROVIDERS, list_models
from modules.ai_providers import API_FORMATS, AUTH_MODES
from modules.ai_connections import connection, endpoint_format
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
        self.api_format = self.settings.value("ai/api_format", endpoint_format(self.endpoint))
        self.auth_mode = self.settings.value("ai/auth_mode", preset["auth_mode"])
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
        for key in ("model", "endpoint", "api_format", "auth_mode"):
            if not self.settings.contains(prefix + "/" + key):
                self.settings.setValue(prefix + "/" + key, getattr(self, key))

    def preferences(self, provider):
        preset = PROVIDERS[provider]
        prefix = "ai/providers/" + provider
        remember = self.settings.value(prefix + "/remember", self.remember_key if provider == self.provider else False, type=bool)
        key = self._keys.get(provider)
        if key is None:
            key = self.store.read(provider) if remember and provider not in ("horde", "ollama", "ollama_cloud") else ""
        endpoint = self.settings.value(prefix + "/endpoint", preset["endpoint"])
        return {"provider": provider, "endpoint": endpoint,
                "api_format": self.settings.value(prefix + "/api_format", endpoint_format(endpoint)),
                "auth_mode": self.settings.value(prefix + "/auth_mode", preset["auth_mode"]),
                "model": self.settings.value(prefix + "/model", preset["model"]), "key": key, "remember_key": remember}

    def identity(self):
        digest = hashlib.sha256(self.key.encode()).hexdigest()
        return self.provider, self.endpoint, self.api_format, self.auth_mode, self.model, digest

    def mark_verified(self):
        self.verified.add(self.identity())

    @property
    def is_verified(self):
        return self.identity() in self.verified

    def values(self):
        return {"provider": self.provider, "endpoint": self.endpoint, "model": self.model,
                "key": self.key, "api_format": self.api_format, "auth_mode": self.auth_mode,
                "answer_tokens": self.answer_tokens, "structured": True, "enabled": self.enabled}

    def save(self, values):
        endpoint, api_format, _ = connection(values)
        provider = values["provider"]
        auth_mode = values.get("auth_mode", PROVIDERS.get(provider, {}).get("auth_mode", "auto"))
        if auth_mode not in AUTH_MODES:
            raise ValueError("Forma de autenticação inválida.")
        if provider not in PROVIDERS:
            raise ValueError("Provedor inválido.")
        key = values.get("key", "").strip() if auth_mode != "none" else ""
        remember = bool(values.get("remember_key", False)) and auth_mode != "none" and provider not in ("horde", "ollama", "ollama_cloud")
        if remember and key:
            self.store.write(provider, key)
        elif self.settings.value("ai/providers/" + provider + "/remember", False, type=bool):
            self.store.delete(provider)
        self.provider, self.endpoint = provider, endpoint
        self.api_format, self.auth_mode = api_format if api_format != "horde" else "auto", auth_mode
        self.model, self.key = values["model"].strip(), key
        self.enabled = bool(values.get("enabled", True))
        self.answer_tokens = max(128, min(2400, int(values.get("answer_tokens", 900))))
        self.remember_key = remember
        self._keys[provider] = key
        self.settings.setValue("ai/enabled", self.enabled)
        self.settings.setValue("ai/remember_key", remember)
        self.settings.setValue("ai/providers/" + provider + "/remember", remember)
        for name in ("model", "endpoint", "api_format", "auth_mode"):
            self.settings.setValue("ai/providers/" + provider + "/" + name, getattr(self, name))
        for name in ("provider", "endpoint", "model", "answer_tokens", "api_format", "auth_mode"):
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
    authenticated = Signal(int, str, str)

    def __init__(self, config):
        super().__init__()
        self.config, self._closed, self._busy = config, False, False
        self._generation = 0
        self._known_models = []
        self._syncing = False
        self._auth_busy = False
        self._login_cancel = threading.Event()
        self._credential_origin = None
        layout = QVBoxLayout(self)
        title = QLabel("Escolha quem vai analisar")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel("Escolha o serviço, conecte sua conta ou servidor e confira o modelo em uso. A coleta funciona sem IA; nenhum modelo trabalha durante a captura.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        choices = QHBoxLayout()
        self.modes, self.mode_buttons = {}, {}
        self.mode_group = QButtonGroup(self)
        self.card_group = QButtonGroup(self)
        for mode, label in (("integrated", "Integrada\nSem IA"), ("horde", "Online gratuita\nSem conta"),
                            ("ollama", "Local neste PC\nOllama / Llama"), ("advanced", "Conectar minha IA\nServiços e servidores")):
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
        first = ("openrouter", "openai", "gemini", "anthropic")
        last = ("ollama_cloud", "lmstudio", "custom")
        services = [*first, *(key for key in PROVIDERS if key not in (*first, *last, "horde", "ollama")), *last]
        for key in services:
            self.service.addItem(PROVIDERS[key]["name"], key)
        self.service.setEditable(True)
        self.service.setInsertPolicy(QComboBox.NoInsert)
        self.service.completer().setFilterMode(Qt.MatchContains)
        self.service.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.service.lineEdit().setPlaceholderText("Busque o serviço que você já usa…")
        form.addRow("1 · Serviço ou servidor", self.service)
        self.endpoint = QLineEdit()
        self.endpoint.setPlaceholderText("http://localhost:1234 ou https://servidor/v1")
        form.addRow("Endereço do servidor", self.endpoint)
        self.api_format = QComboBox()
        for key, label in API_FORMATS.items():
            self.api_format.addItem(label, key)
        form.addRow("Formato da API", self.api_format)
        self.auth_mode = QComboBox()
        for key, label in AUTH_MODES.items():
            self.auth_mode.addItem(label, key)
        form.addRow("Autenticação", self.auth_mode)
        self.login_row = QWidget()
        login_layout = QHBoxLayout(self.login_row)
        login_layout.setContentsMargins(0, 0, 0, 0)
        self.signin = QPushButton("Entrar pelo navegador")
        self.cancel_login = QPushButton("Cancelar conexão")
        self.cancel_login.hide()
        self.signin.clicked.connect(self.login)
        self.cancel_login.clicked.connect(self.cancel_connection)
        login_layout.addWidget(self.signin, 1)
        login_layout.addWidget(self.cancel_login)
        form.addRow("2 · Conectar conta", self.login_row)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Cole sua chave ou token de API")
        self.key.setClearButtonEnabled(True)
        self.key_row = QWidget()
        key_layout = QHBoxLayout(self.key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.addWidget(self.key, 1)
        self.guide = QPushButton("Obter minha chave")
        self.guide.clicked.connect(self.open_guide)
        key_layout.addWidget(self.guide)
        form.addRow("2 · Chave ou token", self.key_row)
        self.remember = QCheckBox("Guardar no cofre do Windows")
        form.addRow("", self.remember)
        self.model = QComboBox()
        self.model.setMinimumWidth(250)
        self.model.setEditable(True)
        self.model.setInsertPolicy(QComboBox.NoInsert)
        self.model.completer().setFilterMode(Qt.MatchContains)
        self.model.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.model.lineEdit().setPlaceholderText("Busque na lista ou informe o ID do modelo")
        form.addRow("3 · Modelo para analisar", self.model)
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
        self.tokens = QSpinBox()
        self.tokens.setRange(128, 2400)
        self.tokens.setValue(config.answer_tokens)
        advanced.addRow("Limite da resposta", self.tokens)
        self.advanced_body = (self.tokens, advanced.labelForField(self.tokens))
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
        self.service.lineEdit().editingFinished.connect(self.finish_service_search)
        self.endpoint.editingFinished.connect(self.address_edited)
        self.api_format.currentIndexChanged.connect(self.connection_edited)
        self.auth_mode.currentIndexChanged.connect(self.connection_edited)
        self.model.currentIndexChanged.connect(self.select_model)
        self.model.lineEdit().editingFinished.connect(self.finish_model_search)
        self.key.textEdited.connect(self.credential_edited)
        self.key.editingFinished.connect(self.schedule_discovery)
        self.listed.connect(self.accept_models)
        self.authenticated.connect(self.accept_login)
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
        self._credential_origin = self.origin(preferences["endpoint"])
        for field, value in ((self.api_format, preferences["api_format"]), (self.auth_mode, preferences["auth_mode"])):
            field.blockSignals(True)
            field.setCurrentIndex(max(0, field.findData(value)))
            field.blockSignals(False)
        self.key.setText(preferences["key"])
        self.remember.setChecked(preferences["remember_key"])
        self.model.blockSignals(True)
        self.model.clear()
        current = preferences["model"]
        if current:
            self.model.addItem("Automático · modelo disponível na fila" if current == "auto" else current, current)
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
        if self._syncing or self.service.currentData() not in PROVIDERS:
            return
        self._set_provider(self.service.currentData())
        self.modes["advanced"].setChecked(True)
        self.update_mode_controls()
        self.schedule_discovery()

    @staticmethod
    def origin(endpoint):
        from urllib.parse import urlsplit
        parsed = urlsplit(endpoint)
        return parsed.scheme, parsed.netloc.casefold()

    def finish_service_search(self):
        if self._syncing:
            return
        text = self.service.currentText().strip().casefold()
        matches = [index for index in range(self.service.count()) if text and
                   (text in self.service.itemText(index).casefold() or text == str(self.service.itemData(index)).casefold())]
        if len(matches) == 1:
            self.service.setCurrentIndex(matches[0])
        elif self.service.currentIndex() >= 0:
            self.service.setEditText(self.service.itemText(self.service.currentIndex()))
            if not matches:
                self.status.setText("Serviço não listado? Escolha Outro serviço compatível e informe o endereço do servidor.")

    def finish_model_search(self):
        if self._syncing or self.config.activity.busy:
            return
        name = self.model_id()
        if name in self._known_models:
            if self.apply():
                self.config.mark_verified()
                self.config.changed.emit()
        elif name:
            self.status.setText("ID informado manualmente. Use este modelo para salvar; o acesso será confirmado na análise.")

    def address_edited(self):
        if self._syncing or self.provider.currentData() != "custom":
            return
        origin = self.origin(self.endpoint.text().strip())
        if self._credential_origin and origin != self._credential_origin:
            self.key.clear()
            self.remember.setChecked(False)
        self._credential_origin = origin
        self.connection_edited()

    def connection_edited(self):
        if self._syncing:
            return
        self._generation += 1
        self._busy = False
        self._known_models = []
        self.update_key_fields()
        self.schedule_discovery()

    def login(self):
        if self.config.activity.busy or self._auth_busy or self.config.demo:
            return
        if self.provider.currentData() == "ollama_cloud":
            self.download_group.setChecked(True)
            self.models.run_job("signin")
            return
        if self.provider.currentData() != "openrouter":
            return
        from modules.ai_login import BrowserLogin
        try:
            login = BrowserLogin()
            self.config.activity.begin_maintenance("ai_login")
        except (OSError, RuntimeError) as error:
            if "login" in locals():
                login.close()
            self.status.setText(str(error))
            return
        self.auto_timer.stop()
        self._generation += 1
        generation = self._generation
        self._login_cancel = threading.Event()
        self._auth_busy = True
        self.status.setText(f"Autorize a conexão local {login.host} no navegador e volte ao SysPulse. O uso segue o saldo e as cotas da sua conta.")
        self.update_state()
        if not QDesktopServices.openUrl(QUrl(login.url)):
            login.close()
            self._auth_busy = False
            self.config.activity.end_maintenance("ai_login")
            self.status.setText("Não foi possível abrir o navegador. Use uma chave ou configure o navegador padrão.")
            self.update_state()
            return
        def run():
            try:
                key, error = login.wait(lambda: self._closed or self._login_cancel.is_set()), ""
            except Exception as exc:
                key, error = "", str(exc)
            finally:
                self.config.activity.end_maintenance("ai_login")
            if not self._closed:
                self.authenticated.emit(generation, key, error)
        threading.Thread(target=run, name="sys-pulse-ai-login", daemon=True).start()

    def cancel_connection(self):
        self._login_cancel.set()
        self.status.setText("Cancelando conexão…")
        self.update_state()

    def accept_login(self, generation, key, error):
        self._auth_busy = False
        if self._closed or generation != self._generation:
            self.update_state()
            return
        if error or self._login_cancel.is_set():
            self.status.setText(error or "Conexão cancelada.")
        else:
            self.key.setText(key)
            self.status.setText("Conta autorizada. Buscando os modelos disponíveis…")
            self.discover()
        self.update_state()

    def model_id(self):
        if self.model.isEditable() and self.model.currentText() != self.model.itemText(self.model.currentIndex()):
            return self.model.currentText().strip()
        return self.model.currentData() or self.model.currentText().strip()

    def values(self):
        return {"provider": self.provider.currentData(), "endpoint": self.endpoint.text().strip(),
                "model": self.model_id(), "key": self.key.text().strip(), "answer_tokens": self.tokens.value(),
                "remember_key": self.remember.isChecked(), "enabled": self.mode() != "integrated",
                "api_format": self.api_format.currentData(), "auth_mode": self.auth_mode.currentData()}

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
            verified = "catálogo conferido · inferência só após a captura" if self.config.is_verified else "conexão ainda não conferida"
            model = "automático na fila" if self.config.model == "auto" else self.config.model or "modelo não escolhido"
            self.active.setText(f"EM USO · {PROVIDERS[self.config.provider]['name']}\n{model} · {verified}")
        try:
            draft = self.values()
            endpoint, wire, _ = connection(draft)
            same = (self.config.enabled and draft["provider"] == self.config.provider and draft["model"] == self.config.model
                    and endpoint == self.config.endpoint and wire == self.config.api_format
                    and draft["auth_mode"] == self.config.auth_mode and draft["key"] == self.config.key)
        except ValueError:
            same = False
        self.save.setText("Modelo em uso" if same else "Usar este modelo")

    def update_key_fields(self):
        provider = self.provider.currentData()
        visible = self.mode() == "advanced" and provider != "ollama_cloud" and self.auth_mode.currentData() != "none"
        self.key_row.setVisible(visible)
        self.form.labelForField(self.key_row).setText("Ou use chave/token" if provider == "openrouter" else "2 · Chave ou token")
        self.form.labelForField(self.key_row).setVisible(visible)
        self.key.setVisible(visible)
        self.remember.setVisible(visible)
        self.guide.setVisible(bool(PROVIDERS[provider]["url"]))
        self.guide.setText("Abrir instruções" if provider == "lmstudio" else "Obter chave ou token")
        self.key.setPlaceholderText("Opcional · somente se o servidor exigir" if provider in ("lmstudio", "custom") else "Cole sua chave ou token de API")
        login = self.mode() == "advanced" and provider in ("openrouter", "ollama_cloud")
        self.login_row.setVisible(login)
        self.form.labelForField(self.login_row).setVisible(login)
        self.signin.setText("Entrar na conta Ollama" if provider == "ollama_cloud" else "Conectar OpenRouter pelo navegador")

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
        self.form.labelForField(self.model).setText("3 · Modelo para analisar" if advanced else "Modelo para analisar")
        self.form.labelForField(self.model).setVisible(show_model)
        self.save.setVisible(show_model)
        custom = advanced and self.provider.currentData() == "custom"
        for field in (self.endpoint, self.api_format, self.auth_mode):
            field.setVisible(custom)
            self.form.labelForField(field).setVisible(custom)
        self.connection_options.setVisible(mode not in ("integrated", "horde"))
        self.download_group.setVisible(mode == "ollama" or advanced and self.provider.currentData() == "ollama_cloud")
        self.update_key_fields()
        self.update_active()
        self.update_state()

    def apply(self):
        if self.config.activity.busy or self._busy:
            return False
        values = self.values()
        if PROVIDERS[values["provider"]]["requires_key"] and values["enabled"] and not values["key"]:
            self.status.setText("Conecte sua conta pelo navegador ou informe sua chave antes de selecionar o modelo.")
            return False
        if values["enabled"] and not values["model"]:
            self.status.setText("Conecte o serviço e escolha um modelo da lista.")
            return False
        try:
            self.config.save(values)
            self.endpoint.setText(self.config.endpoint)
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
        self._known_models = []
        self.update_active()
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
        provider = self.provider.currentData()
        if provider == "custom" and self.origin(self.endpoint.text().strip()) != self._credential_origin:
            self.key.clear()
            self.remember.setChecked(False)
            self._credential_origin = self.origin(self.endpoint.text().strip())
        values = self.values()
        if PROVIDERS[provider]["requires_key"] and not values["key"]:
            self.status.setText("Conecte pelo navegador ou cole sua chave; a lista de modelos será carregada automaticamente."
                                if provider == "openrouter" else
                                "Abra Obter chave ou token, cole sua credencial e aguarde a busca automática dos modelos.")
            return
        try:
            endpoint, api_format, _ = connection(values)
            values.update(endpoint=endpoint, api_format=api_format)
            self.endpoint.setText(endpoint)
        except ValueError as error:
            self.status.setText(str(error))
            return
        self._generation += 1
        generation = self._generation
        values["_cancelled"] = lambda: self._closed or generation != self._generation
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
            self.status.setText(error + " A seleção anterior continua salva. Se o serviço não listar modelos, informe o ID e use este modelo.")
            if self.mode() == "ollama":
                self.download_group.setChecked(True)
        elif not models:
            if self.mode() == "ollama":
                self.status.setText("Nenhum modelo local instalado. Abra Adicionar um modelo local para baixar.")
                self.download_group.setChecked(True)
            else:
                self.status.setText("Nenhum modelo listado nesta conexão. Confira o acesso no serviço ou informe o ID manualmente.")
        else:
            provider = self.provider.currentData()
            current = self.model_id()
            choice = suggested_model(provider, models, current)
            self.model.blockSignals(True)
            self.model.clear()
            for model in models:
                self.model.addItem(model, model)
            self.model.setCurrentIndex(models.index(choice))
            self.model.blockSignals(False)
            if self.apply():
                self.config.mark_verified()
                self.config.changed.emit()
                self.status.setText(f"Pronto · {len(models)} modelo(s) disponível(is). Modelo selecionado: {choice}.")
            elif self.config.activity.busy:
                self.status.setText("Modelos disponíveis. Use este modelo depois da captura ou da análise atual.")
        self.update_state()

    def update_state(self):
        available = not self.config.activity.busy and not self._auth_busy
        for button in (*self.modes.values(), *self.mode_buttons.values()):
            button.setEnabled(available)
        for widget in (self.provider, self.service, self.key, self.model, self.endpoint, self.tokens, self.api_format, self.auth_mode):
            widget.setEnabled(available)
        self.signin.setEnabled(available and not self._busy)
        self.cancel_login.setVisible(self._auth_busy)
        self.cancel_login.setEnabled(self._auth_busy and not self._login_cancel.is_set())
        self.check.setEnabled(available and not self._busy)
        self.save.setEnabled(available and not self._busy)
        self.remember.setEnabled(available and self.config.store.api is not None)

    def open_guide(self):
        url = PROVIDERS[self.provider.currentData()]["url"]
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def shutdown(self):
        self._closed = True
        self._login_cancel.set()
        self.auto_timer.stop()
        self.models.shutdown()
