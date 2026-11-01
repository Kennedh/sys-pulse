import threading

from PySide6.QtCore import QObject, QSettings, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel,
                              QComboBox, QLineEdit, QPushButton, QSpinBox, QGroupBox, QCheckBox, QRadioButton, QButtonGroup)

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

    def values(self):
        return {"provider": self.provider, "endpoint": self.endpoint, "model": self.model,
                "key": self.key, "answer_tokens": self.answer_tokens, "structured": True, "enabled": self.enabled}

    def save(self, values):
        validate_endpoint(values["endpoint"])
        self.enabled = bool(values.get("enabled", True))
        self.settings.setValue("ai/enabled", self.enabled)
        self.provider, self.endpoint = values["provider"], values["endpoint"]
        self.model, self.key = values["model"].strip(), values.get("key", "")
        self.answer_tokens = int(values.get("answer_tokens", 900))
        remember = bool(values.get("remember_key", False))
        if remember and self.key:
            self.store.write(self.provider, self.key)
        elif self.remember_key:
            self.store.delete(self.provider)
        self.remember_key = remember
        self.settings.setValue("ai/remember_key", remember)
        self.settings.setValue("ai/providers/" + self.provider + "/model", self.model)
        self.settings.setValue("ai/providers/" + self.provider + "/endpoint", self.endpoint)
        for name in ("provider", "endpoint", "model", "answer_tokens"):
            self.settings.setValue("ai/" + name, getattr(self, name))
        self.changed.emit()


class AISettingsPanel(QWidget):
    listed = Signal(object, str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self._busy = False
        self._closed = False
        layout = QVBoxLayout(self)
        title = QLabel("Sua análise, sua IA")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel("A explicação local funciona imediatamente. Escolher um modelo não inicia inferência.\n"
                       "A IA só pode analisar depois da captura; o Ollama descarrega o modelo ao concluir.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.modes = {}
        self.mode_group = QButtonGroup(self)
        for key, caption in (("integrated", "Análise integrada · sem IA e sem configuração"),
                             ("horde", "Online · grátis, sem conta e sem download"),
                             ("ollama", "Local · funciona sem internet após baixar o modelo"),
                             ("advanced", "Já uso outro serviço · configuração avançada")):
            button = QRadioButton(caption)
            self.mode_group.addButton(button)
            self.modes[key] = button
            layout.addWidget(button)
        self.active = QLabel()
        self.active.setObjectName("card")
        self.active.setWordWrap(True)
        layout.addWidget(self.active)
        form = QFormLayout()
        self.form = form
        self.provider = QComboBox()
        for value, preset in PROVIDERS.items():
            self.provider.addItem(preset["name"], value)
        self.provider.setCurrentIndex(self.provider.findData(config.provider))
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItem(config.model)
        self.model.setMinimumWidth(230)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("Sem marcar Lembrar, a chave fica apenas na memória")
        self.key.setText(config.key)
        form.addRow("Onde analisar", self.provider)
        form.addRow("Modelo para analisar", self.model)
        form.addRow("Sua chave", self.key)
        layout.addLayout(form)
        self.remember = QCheckBox("Lembrar minha chave no cofre do Windows")
        self.remember.setChecked(config.remember_key)
        self.remember.setEnabled(config.store.api is not None)
        layout.addWidget(self.remember)
        self.help = QLabel()
        self.help.setWordWrap(True)
        layout.addWidget(self.help)
        controls = QHBoxLayout()
        self.check = QPushButton("Detectar modelos / testar conexão")
        self.check.clicked.connect(self.discover)
        self.save = QPushButton("Usar esta configuração")
        self.save.clicked.connect(self.apply)
        self.guide = QPushButton("Abrir instruções do serviço")
        self.guide.clicked.connect(self.open_guide)
        for widget in (self.check, self.save, self.guide):
            controls.addWidget(widget)
        layout.addLayout(controls)
        advanced = QGroupBox("Opções de conexão")
        self.connection_options = advanced
        advanced.setCheckable(True)
        advanced.setChecked(False)
        advanced_form = QFormLayout(advanced)
        self.endpoint = QLineEdit(config.endpoint)
        self.tokens = QSpinBox()
        self.tokens.setRange(128, 2400)
        self.tokens.setValue(config.answer_tokens)
        advanced_form.addRow("Endereço", self.endpoint)
        advanced_form.addRow("Limite de resposta (tokens)", self.tokens)
        advanced_widgets = (self.endpoint, self.tokens, advanced_form.labelForField(self.endpoint),
                            advanced_form.labelForField(self.tokens))
        for widget in advanced_widgets:
            widget.setVisible(False)
        advanced.toggled.connect(lambda shown: [widget.setVisible(shown) for widget in advanced_widgets])
        layout.addWidget(advanced)
        self.status = QLabel("Nenhum modelo foi carregado. O teste consulta apenas a lista de modelos.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.models = ModelManagerPanel(config)
        self.models.prepare_settings = self.apply
        layout.addWidget(self.models)
        layout.addStretch()
        self.provider.currentIndexChanged.connect(self.use_preset)
        self.listed.connect(self.accept_models)
        config.activity.changed.connect(self.update_state)
        config.changed.connect(self.sync_config)
        self.help.setText(PROVIDERS[config.provider]["help"])
        self.update_key_fields()
        self.models.setVisible(config.provider in ("ollama", "ollama_cloud"))
        for mode, button in self.modes.items():
            button.clicked.connect(lambda checked=False, key=mode: self.choose_mode(key))
        self.sync_mode()
        self.update_state()

    def choose_mode(self, mode):
        if self.config.activity.busy:
            return
        if mode in ("horde", "ollama"):
            self.provider.setCurrentIndex(self.provider.findData(mode))
        self.modes[mode].setChecked(True)
        self.update_mode_controls()
        if mode != "advanced":
            self.apply()

    def sync_mode(self):
        mode = ("integrated" if not self.config.enabled else self.config.provider
                if self.config.provider in ("horde", "ollama") else "advanced")
        self.modes[mode].setChecked(True)
        self.update_mode_controls()

    def update_mode_controls(self):
        mode = next((key for key, button in self.modes.items() if button.isChecked()), "horde")
        advanced = mode == "advanced"
        enabled = mode != "integrated"
        for widget in (self.provider, self.form.labelForField(self.provider)):
            widget.setVisible(advanced)
        for widget in (self.model, self.form.labelForField(self.model)):
            widget.setVisible(enabled and mode != "horde")
        for widget in (self.check, self.save, self.guide, self.help):
            widget.setVisible(enabled)
        self.check.setText("Verificar serviço online" if mode == "horde" else "Listar modelos disponíveis")
        self.connection_options.setVisible(mode in ("ollama", "advanced"))
        self.models.setVisible(enabled and self.provider.currentData() in ("ollama", "ollama_cloud"))
        self.update_key_fields()
        description = ("Análise integrada ativa · sem modelo, conta ou envio de dados." if not self.config.enabled else
                       "Online anônima ativa · usa fila comunitária após sua confirmação." if self.config.provider == "horde" else
                       f"Configuração ativa: {PROVIDERS[self.config.provider]['name']} · {self.config.model or 'escolha o modelo'}.")
        self.active.setText(description + "\nEscolher um modo não carrega o modelo nem inicia análise.")

    def values(self):
        return {"provider": self.provider.currentData(), "endpoint": self.endpoint.text().strip(),
                "model": self.model.currentText().strip(), "key": self.key.text(),
                "answer_tokens": self.tokens.value(), "remember_key": self.remember.isChecked(),
                "enabled": not self.modes["integrated"].isChecked()}

    def use_preset(self):
        preset = PROVIDERS[self.provider.currentData()]
        remembered = "ai/providers/" + self.provider.currentData()
        self.endpoint.setText(self.config.settings.value(remembered + "/endpoint", preset["endpoint"]))
        self.model.clear()
        self.model.addItem(self.config.settings.value(remembered + "/model", preset["model"]))
        self.key.setText(self.config.store.read(self.provider.currentData()) if self.remember.isChecked() else "")
        self.help.setText(preset["help"])
        self.update_key_fields()
        self.models.setVisible(self.provider.currentData() in ("ollama", "ollama_cloud"))
        self.models.set_provider(self.provider.currentData())
        if hasattr(self, "modes"):
            mode = self.provider.currentData() if self.provider.currentData() in ("horde", "ollama") else "advanced"
            self.modes[mode].setChecked(True)
            self.update_mode_controls()

    def sync_config(self):
        self.model.setCurrentText(self.config.model)
        self.sync_mode()

    def shutdown(self):
        self._closed = True
        self.models.shutdown()

    def update_key_fields(self):
        visible = self.provider.currentData() not in ("ollama", "ollama_cloud", "horde")
        self.key.setVisible(visible)
        self.form.labelForField(self.key).setVisible(visible)
        self.remember.setVisible(visible)

    def apply(self):
        if self.config.activity.busy or self._busy:
            self.status.setText("Aguarde a captura, a análise ou a preparação dos modelos terminar.")
            return False
        try:
            self.config.save(self.values())
            message = ("Análise integrada selecionada. Sem modelo ou envio de dados." if not self.config.enabled else
                       "Online anônima selecionada. Nenhuma conta ou chave é necessária." if self.config.provider == "horde" else
                       "Modelo local selecionado. O modelo só trabalha quando a análise for solicitada." if self.config.provider == "ollama" else
                       "Configuração salva. Nenhuma inferência foi iniciada.")
            self.status.setText(message)
        except (ValueError, TypeError, OSError) as error:
            self.status.setText(str(error))
            return False
        return True

    def discover(self):
        if self.config.activity.busy or self._busy:
            return
        values = self.values()
        try:
            validate_endpoint(values["endpoint"])
        except ValueError as error:
            self.status.setText(str(error))
            return
        self._busy = True
        self.status.setText("Consultando modelos disponíveis, sem gerar texto…")
        self.update_state()

        def run():
            try:
                models, error = list_models(values), ""
            except Exception as exception:
                models, error = [], str(exception)
            if not self._closed:
                self.listed.emit(models, error)
        threading.Thread(target=run, name="sys-pulse-models", daemon=True).start()

    def accept_models(self, models, error):
        self._busy = False
        current = self.model.currentText()
        if models:
            self.model.clear()
            self.model.addItems(models)
            choice = current if current in models else next((name for name in models if "llama" in name.lower()), models[0])
            self.model.setCurrentText(choice)
        self.status.setText(error or f"Conexão pronta: {len(models)} modelo(s). Nenhum modelo foi carregado. Salve sua escolha.")
        self.update_state()

    def update_state(self):
        available = not self.config.activity.busy and not self._busy
        for button in self.modes.values():
            button.setEnabled(available)
        self.remember.setEnabled(available and self.config.store.api is not None)
        for widget in (self.provider, self.model, self.key, self.check, self.save, self.endpoint, self.tokens):
            widget.setEnabled(available)

    def open_guide(self):
        url = PROVIDERS[self.provider.currentData()]["url"]
        if url:
            QDesktopServices.openUrl(QUrl(url))
