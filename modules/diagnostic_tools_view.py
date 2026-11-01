import os
import threading
from pathlib import Path

from PySide6.QtCore import QUrl, Signal, QStandardPaths
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QPlainTextEdit, QFileDialog)
from modules.analysis_view import table, fill
from modules.diagnostic_tools import (find_latencymon, query_driver_updates, download_latencymon,
                                     read_latency_report, LATENCYMON_PAGE, MANUFACTURERS)


class DiagnosticToolsPanel(QWidget):
    completed = Signal(str, object, str)

    def __init__(self, activity, demo=False):
        super().__init__()
        self.activity, self.demo = activity, demo
        self.cancelled = threading.Event()
        self.closed = False
        layout = QVBoxLayout(self)
        intro = QLabel("Verifique as ofertas do Windows Update e investigue latências dos drivers. "
                       "Nenhum driver é instalado pela consulta. A versão e a data do inventário não comprovam que o driver está atualizado.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        buttons = QHBoxLayout()
        self.query = QPushButton("Consultar atualizações de drivers")
        self.query.clicked.connect(lambda: self.run("updates"))
        buttons.addWidget(self.query)
        self.update = QPushButton("Instalar pelo Windows Update")
        self.update.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("ms-settings:windowsupdate-optionalupdates")))
        buttons.addWidget(self.update)
        layout.addLayout(buttons)
        self.updates = table(["Oferta do Windows Update", "Modelo", "Fornecedor", "Data", "ID de hardware compatível"])
        self.updates.setMinimumHeight(120)
        layout.addWidget(self.updates, 1)
        self.status = QLabel("Consulta sob demanda · requer Windows e conexão. Pode levar até 2 minutos.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        manufacturers = QHBoxLayout()
        for name, url in MANUFACTURERS.items():
            button = QPushButton("Drivers " + name)
            button.clicked.connect(lambda checked=False, target=url: QDesktopServices.openUrl(QUrl(target)))
            manufacturers.addWidget(button)
        layout.addLayout(manufacturers)
        title = QLabel("LatencyMon · DPC, ISR e hard pagefaults")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        note = QLabel("1 · Instale a ferramenta original. 2 · Abra, inicie a medição e reproduza o sintoma. "
                      "3 · Pare e exporte o relatório em texto; importe abaixo.\n"
                      "O LatencyMon abre em sua própria janela e usa licença própria. "
                      "O relatório mede outro período; ele não comprova sozinho a causa de um engasgo da sessão.")
        note.setWordWrap(True)
        layout.addWidget(note)
        tools = QHBoxLayout()
        self.install = QPushButton("Baixar e abrir instalador oficial")
        self.install.clicked.connect(lambda: self.run("install"))
        self.launch = QPushButton("Detectar / abrir LatencyMon")
        self.launch.clicked.connect(self.open_latency)
        self.import_button = QPushButton("Importar relatório de texto…")
        self.import_button.clicked.connect(self.import_report)
        for button in (self.install, self.launch, self.import_button):
            tools.addWidget(button)
        layout.addLayout(tools)
        official = QPushButton("Site oficial e licença do LatencyMon")
        official.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(LATENCYMON_PAGE)))
        layout.addWidget(official)
        self.latency_status = QLabel("LatencyMon é opcional e não integra o tamanho do pacote.")
        self.latency_status.setWordWrap(True)
        layout.addWidget(self.latency_status)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("O relatório importado aparece aqui, sem envio para a IA.")
        layout.addWidget(self.report, 1)
        self.completed.connect(self.accept)
        self.activity.changed.connect(self.sync)
        self.sync()

    def sync(self):
        windows = os.name == "nt"
        enabled = windows and not self.activity.busy and not self.demo and not self.closed
        for button in (self.query, self.update, self.install, self.launch):
            button.setEnabled(enabled)
        self.import_button.setEnabled(not self.activity.busy and not self.demo and not self.closed)

    def run(self, kind):
        if self.activity.busy or self.demo or self.closed:
            return
        try:
            self.activity.begin_maintenance("diagnostic_tools")
        except RuntimeError as error:
            self.status.setText(str(error))
            return
        self.cancelled.clear()
        label = self.status if kind == "updates" else self.latency_status
        label.setText("Consultando o Windows Update…" if kind == "updates" else "Baixando do site oficial e validando a assinatura da Resplendence…")
        def work():
            try:
                if kind == "updates":
                    value = query_driver_updates(self.cancelled.is_set)
                else:
                    folder = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation)) / "instaladores"
                    value = download_latencymon(folder, self.cancelled.is_set)
                error = ""
            except Exception as exc:
                value, error = None, str(exc)[:400]
            if not self.closed:
                self.completed.emit(kind, value, error)
        threading.Thread(target=work, daemon=True).start()

    def accept(self, kind, value, error):
        self.activity.end_maintenance("diagnostic_tools")
        if self.closed:
            return
        label = self.status if kind == "updates" else self.latency_status
        if error:
            label.setText(error + (" Abra o site oficial para baixar manualmente." if kind == "install" else ""))
            return
        if kind == "updates":
            fill(self.updates, [[row.get(key, "") for key in ("title", "model", "provider", "date", "hardware_id")]
                               for row in value["updates"]])
            label.setText(f"{value['total']} oferta(s) pelo Windows Update. "
                          "Nenhuma oferta não garante a versão mais recente no fabricante."
                          + (" Consulta parcial; tente novamente." if value.get("result_code") == 3 else "")
                          + (" Mostrando as primeiras 100." if value["total"] > 100 else ""))
        else:
            try:
                os.startfile(value)
                label.setText("Instalador original aberto. Conclua a licença e a instalação; depois use Detectar / abrir LatencyMon.")
            except OSError as exc:
                label.setText(f"Não foi possível abrir o instalador: {exc}")

    def open_latency(self):
        if self.demo or self.activity.busy:
            return
        executable = find_latencymon()
        if not executable:
            self.latency_status.setText("LatencyMon não encontrado. Instale pelo botão ou pelo site oficial.")
            return
        try:
            os.startfile(executable)
            self.latency_status.setText("LatencyMon aberto. Inicie e pare a medição na ferramenta, depois exporte o texto.")
        except OSError as error:
            self.latency_status.setText(f"Não foi possível abrir: {error}")

    def import_report(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importar relatório do LatencyMon", "", "Texto (*.txt);;Todos (*)")
        if path:
            try:
                self.report.setPlainText(read_latency_report(path))
                self.latency_status.setText("Relatório importado · período independente da captura. Os valores de execução são do LatencyMon.")
            except (OSError, ValueError) as error:
                self.latency_status.setText(str(error))

    def shutdown(self):
        self.closed = True
        self.cancelled.set()
        self.activity.end_maintenance("diagnostic_tools")
