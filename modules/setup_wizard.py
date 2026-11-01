from modules.version import VERSION

from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QRadioButton, QDialogButtonBox


class SetupDialog(QDialog):
    def __init__(self, parent=None, selected="integrated"):
        super().__init__(parent)
        self.setWindowTitle(f"Começar no SysPulse {VERSION}")
        self.setMinimumWidth(540)
        layout = QVBoxLayout(self)
        text = QLabel("Escolha como complementar a análise. A coleta e a explicação integrada funcionam sem IA, conta ou download. "
                      "Essa escolha pode ser alterada em Configurações.")
        text.setWordWrap(True)
        layout.addWidget(text)
        self.choices = {}
        for key, title in (
                ("integrated", "Análise integrada · começar sem downloads"),
                ("local", "IA local · escolher e baixar um modelo separado"),
                ("online", "IA na nuvem · acesso anônimo, sem login ou chave")):
            button = QRadioButton(title)
            self.choices[key] = button
            layout.addWidget(button)
        self.choices[selected].setChecked(True)
        note = QLabel("A IA só trabalha após a captura. Modelos locais usam disco e RAM/VRAM. "
                      "A nuvem anônima usa workers comunitários, com fila e disponibilidade variável. Nenhum download começa sozinho.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Continuar")
        buttons.button(QDialogButtonBox.Cancel).setText("Decidir depois")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selection(self):
        return next(key for key, button in self.choices.items() if button.isChecked())


def configure_first_run(window, selected=None):
    settings = window.ai_config.settings
    if selected is None and settings.value("setup/completed", False, type=bool):
        return
    dialog = SetupDialog(window, selected or "integrated")
    if dialog.exec() != QDialog.Accepted:
        return
    choice = dialog.selection()
    settings.setValue("setup/completed", True)
    if choice == "integrated":
        return
    provider = "horde" if choice == "online" else "ollama"
    panel = window.settings_panel
    panel.provider.setCurrentIndex(panel.provider.findData(provider))
    if choice == "local":
        panel.model.setCurrentText("llama3.2:1b")
    panel.apply()
    window.show_page(7)
