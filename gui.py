import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QAbstractTableModel, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QStackedWidget, QProgressBar, QTabWidget, QTableView,
    QHeaderView, QSystemTrayIcon, QMenu, QStyle, QPlainTextEdit, QScrollArea)

from modules.hardware import get_hardware_info
from modules.monitor import MonitorWorker
from modules.diagnostics import SessionRecorder
from modules.diagnostic_view import DiagnosticPanel, fmt
from modules.hotkey import GlobalHotkey
from modules.analysis_view import AnalysisPanel


STYLE = """
QWidget { background: #121722; color: #e6eaf3; font-size: 13px; }
QLabel#title { font-size: 21px; font-weight: bold; padding: 6px 0; }
QLabel#card { background: #20293b; border-radius: 7px; padding: 10px; font-size: 14px; }
QLabel#analysisCard { background: #202d43; border: 1px solid #354867; border-radius: 8px; padding: 14px; font-size: 15px; }
QLabel#muted { color: #a4b2c9; }
QLabel#demo { color: #f4c479; padding: 8px 0; font-weight: bold; }
QTableView { alternate-background-color: #182031; background: #131b29; }
QPushButton#navigation { text-align: left; padding: 12px; background: #20293b; }
QPushButton#navigation:checked { background: #425ba8; }
QPushButton { background: #425ba8; padding: 9px 13px; border: none; border-radius: 5px; }
QPushButton:hover { background: #566fc2; }
QPushButton:disabled { background: #242b3a; color: #7b879b; }
QLineEdit, QComboBox, QPlainTextEdit { background: #191f2e; border: 1px solid #34405a; padding: 6px; }
QTabWidget::pane { border: 1px solid #34405a; }
QTabBar::tab { background: #20293b; padding: 8px 16px; }
QTabBar::tab:selected { background: #425ba8; }
QHeaderView::section { background: #20293b; padding: 7px; border: none; }
QTableView { gridline-color: #2c3548; selection-background-color: #425ba8; }
QProgressBar { border: 1px solid #34405a; border-radius: 4px; text-align: center; min-height: 18px; }
QProgressBar::chunk { background: #687ddd; }
"""


class ProcessTableModel(QAbstractTableModel):
    columns = [("pid", "PID"), ("name", "Processo"), ("cpu_percent", "CPU %"),
               ("ram_percent", "RAM %"), ("rss_mb", "RAM MiB"),
               ("io_read_mbs", "Ler MiB/s"), ("io_write_mbs", "Gravar MiB/s"), ("gpu_percent", "GPU %")]

    def __init__(self):
        super().__init__()
        self.rows = []
        self.sort_column = 2
        self.sort_order = Qt.DescendingOrder

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent=None):
        return len(self.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        if role == Qt.DisplayRole:
            value = self.rows[index.row()].get(self.columns[index.column()][0])
            return "N/D" if value is None else f"{value:.2f}" if isinstance(value, float) else value

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.columns[section][1]

    def sort(self, column, order):
        self.sort_column, self.sort_order = column, order
        self.update_rows(self.rows)

    def update_rows(self, rows):
        self.beginResetModel()
        key = self.columns[self.sort_column][0]
        available = [row for row in rows if row.get(key) is not None]
        missing = [row for row in rows if row.get(key) is None]
        self.rows = sorted(available, key=lambda row: row[key], reverse=self.sort_order == Qt.DescendingOrder) + missing
        self.endResetModel()


class App(QMainWindow):
    recording_status = Signal(dict)
    hardware_ready = Signal(str)

    def __init__(self, demo=False):
        super().__init__()
        self.demo = demo
        self.setWindowTitle("SYS-PULSE 2.0 — Monitoramento e análise" + (" — DADOS SIMULADOS" if demo else ""))
        self.resize(1340, 900)
        self.setMinimumSize(1080, 740)
        self.setStyleSheet(STYLE)
        self._closed = False
        self._last_sample = self._last_processes = None
        self._last_paint = 0
        self._hardware_loaded = False
        self._last_marker = 0
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        sidebar = QWidget()
        sidebar.setFixedWidth(180)
        navigation = QVBoxLayout(sidebar)
        logo = QLabel("SYS-PULSE")
        logo.setObjectName("title")
        navigation.addWidget(logo)
        navigation.addWidget(QLabel("Performance sob análise\nv2.0.0"))
        self.pages = QStackedWidget()
        layout.addWidget(sidebar)
        layout.addWidget(self.pages, 1)
        self.hardware = QPlainTextEdit("Carregando informações de hardware…")
        self.hardware.setReadOnly(True)
        self.pages.addWidget(self.hardware)
        self.monitor = QTabWidget()
        self.pages.addWidget(self.monitor)
        resources = QWidget()
        resource_layout = QVBoxLayout(resources)
        self.uptime = QLabel()
        resource_layout.addWidget(self.uptime)
        self.resource_labels, self.bars = {}, {}
        for key in ("CPU", "RAM"):
            self.resource_labels[key] = QLabel()
            self.bars[key] = QProgressBar()
            resource_layout.addWidget(self.resource_labels[key])
            resource_layout.addWidget(self.bars[key])
        self.resource_text = QPlainTextEdit()
        self.resource_text.setReadOnly(True)
        resource_layout.addWidget(self.resource_text, 1)
        self.monitor.addTab(resources, "Recursos")
        self.process_table = QTableView()
        self.process_model = ProcessTableModel()
        self.process_table.setModel(self.process_model)
        self.process_table.setSortingEnabled(True)
        self.process_table.sortByColumn(2, Qt.DescendingOrder)
        self.process_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.monitor.addTab(self.process_table, "Processos")
        self.network = QPlainTextEdit()
        self.network.setReadOnly(True)
        self.pages.addWidget(self.network)
        self.diagnostic = DiagnosticPanel()
        diagnostic_scroll = QScrollArea()
        diagnostic_scroll.setWidgetResizable(True)
        diagnostic_scroll.setWidget(self.diagnostic)
        self.pages.addWidget(diagnostic_scroll)
        self.analysis = AnalysisPanel()
        self.pages.addWidget(self.analysis)
        self.nav_buttons = []
        for index, name in enumerate(("HARDWARE", "LIVE MONITOR", "REDE", "CAPTURA", "ANÁLISE")):
            button = QPushButton(name)
            button.setObjectName("navigation")
            button.setCheckable(True)
            self.nav_buttons.append(button)
            button.clicked.connect(lambda checked=False, i=index: self.show_page(i))
            navigation.addWidget(button)
        navigation.addStretch()
        if demo:
            badge = QLabel("DEMONSTRAÇÃO\nDados simulados")
            badge.setObjectName("demo")
            navigation.addWidget(badge)
        quit_button = QPushButton("Sair")
        quit_button.clicked.connect(QApplication.instance().quit)
        navigation.addWidget(quit_button)
        self.recording_status.connect(self.diagnostic.set_status)
        self.recording_status.connect(self.on_recording_status)
        self.hardware_ready.connect(self.hardware.setPlainText)
        self.recorder = SessionRecorder(self.recording_status.emit)
        if demo:
            from modules.demo import DemoMonitor
            self.worker_monitor = DemoMonitor()
            self.diagnostic.start.setEnabled(False)
            self.diagnostic.folder.setText("Demonstração — arquivos não são gravados")
            self.diagnostic.choose.setEnabled(False)
            self.diagnostic.interval.setEnabled(False)
            self.diagnostic.lhm.setEnabled(False)
            self.diagnostic.status.setText("Demonstração · dados simulados · gravação desativada")
            for sample in self.worker_monitor.samples:
                self.diagnostic.chart.add(sample)
            for event in self.worker_monitor.markers:
                self.diagnostic.chart.markers.append(event["monotonic"])
                self.diagnostic.events.appendPlainText(f"#{event['id']} · {event['timestamp']}\n{event['note']}")
        else:
            self.worker_monitor = MonitorWorker(self.recorder.submit)
        self.diagnostic.start_requested.connect(lambda options: self.send_command("start", options))
        self.diagnostic.stop_requested.connect(lambda: self.send_command("stop"))
        self.diagnostic.mark_requested.connect(self.mark_stutter)
        self.diagnostic.analyze_requested.connect(self.analyze_capture)
        self.diagnostic.interval_changed.connect(lambda interval: setattr(self.worker_monitor, "interval", interval))
        self.diagnostic.lhm_changed.connect(lambda enabled: setattr(self.worker_monitor.sensors, "lhm_enabled", enabled))
        self.hotkey = GlobalHotkey(QApplication.instance(), self.mark_stutter)
        self.diagnostic.hotkey_status.setText("Ctrl + Alt + F8: atalho global ativo" if self.hotkey.registered else self.hotkey.error)
        if not self.hotkey.registered:
            self.shortcut = QShortcut(QKeySequence("Ctrl+Alt+F8"), self)
            self.shortcut.activated.connect(self.mark_stutter)
        self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.SP_ComputerIcon), self)
        menu = QMenu(self)
        for name, callback in (("Restaurar", self.restore), ("Marcar travadinha", self.mark_stutter),
                               ("Encerrar gravação", lambda: self.send_command("stop")), ("Sair", QApplication.instance().quit)):
            action = QAction(name, self)
            action.triggered.connect(callback)
            menu.addAction(action)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("SysPulse · Ctrl+Alt+F8 marca uma travadinha durante a gravação")
        self.tray.activated.connect(lambda reason: self.restore() if reason == QSystemTrayIcon.DoubleClick else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self.worker_monitor.start()
        self.show_page(3)
        if demo:
            self.analyze_capture(str(Path(__file__).parent / "examples" / "sessao-demo"))

    def on_recording_status(self, status):
        if status.get("completed") and status.get("count") and not self._closed:
            self.analyze_capture(status["path"], auto_save=True)

    def analyze_capture(self, source, auto_save=False):
        self.show_page(4)
        self.analysis.load(source, auto_save)

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)
        if index == 0 and not self._hardware_loaded:
            self._hardware_loaded = True
            threading.Thread(target=self.load_hardware, name="sys-pulse-hardware", daemon=True).start()
        self._last_paint = 0

    def load_hardware(self):
        try:
            report = ("DEMONSTRAÇÃO — DADOS SIMULADOS\n\nSistema: Windows 11\nCPU: processador de demonstração (6 núcleos / 12 threads)\n"
                      "RAM: 32 GiB\nGPU: GPU de demonstração\n\nExecute sem --demo para consultar seu hardware." if self.demo else get_hardware_info())
        except Exception as error:
            report = f"Não foi possível consultar o hardware: {error}"
        if not self._closed:
            self.hardware_ready.emit(report)

    def send_command(self, kind, payload=None):
        if not self.recorder.command(kind, payload):
            self.diagnostic.set_status({"active": self.recorder.active.is_set(), "path": str(self.recorder.path or ""),
                                        "message": "Gravador ocupado. Tente novamente; o comando não foi registrado.", "error": True})

    def mark_stutter(self):
        now = time.monotonic()
        if not self.recorder.active.is_set() or now - self._last_marker < 0.5:
            return
        self._last_marker = now
        self.send_command("mark", {"timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                                  "monotonic": now, "note": self.diagnostic.note.text()[:500]})

    def refresh(self):
        sample = self.worker_monitor.latest()
        if sample is None:
            self.statusBar().showMessage(self.worker_monitor.last_error or "Inicializando coleta…")
            return
        age = time.monotonic() - sample["monotonic"]
        message = self.worker_monitor.last_error or (f"Coleta sem atualização há {age:.1f} s" if age > 3 else
                  "Coleta ativa · fechar a janela minimiza para a bandeja quando disponível")
        self.statusBar().showMessage(message)
        if sample is not self._last_sample:
            self.diagnostic.chart.add(sample)
            self._last_sample = sample
        if not self.isVisible() or self.isMinimized() or time.monotonic() - self._last_paint < 0.5:
            return
        self._last_paint = time.monotonic()
        page = self.pages.currentIndex()
        if page == 3:
            self.diagnostic.update_sample(sample)
        elif page == 1:
            self.update_resources(sample)
            if sample["processes"] is not self._last_processes:
                self.process_model.update_rows(sample["processes"])
                self._last_processes = sample["processes"]
        elif page == 2:
            self.update_network(sample)

    def update_resources(self, sample):
        self.uptime.setText(f"Tempo desde o boot: {sample['uptime']}")
        for key, field in (("CPU", "cpu_percent"), ("RAM", "ram_percent")):
            self.resource_labels[key].setText(f"{key}: {fmt(sample[field], '%')}")
            self.bars[key].setValue(round(sample[field]))
        lines = [f"Núcleo mais ocupado: {fmt(sample['cpu_max_core'], '%')}",
                 f"RAM disponível: {fmt(sample['ram_available_gb'], ' GiB')}", "", "GPUs"]
        for gpu in sample.get("gpus", []):
            lines.append(f"{gpu['name']}: {fmt(gpu.get('percent'), '%')} | {fmt(gpu.get('temperature'), ' °C')} | "
                         f"VRAM {fmt(gpu.get('memory_used_mb'), '', 0)}/{fmt(gpu.get('memory_total_mb'), ' MiB', 0)}")
        if not sample.get("gpus"):
            lines.append("N/D — NVIDIA usa NVML; AMD/Intel podem fornecer sensores via LibreHardwareMonitor.")
        lines += ["", "ATIVIDADE DOS DISCOS"]
        for disk in sample["disks"]:
            lines.append(f"{disk['name']}: leitura {fmt(disk['read_mbs'], ' MiB/s')} | escrita {fmt(disk['write_mbs'], ' MiB/s')} | "
                         f"atividade {fmt(disk['active_percent'], '%')} | latência R/W {fmt(disk['read_ms'])}/{fmt(disk['write_ms'])} ms/op")
        lines += ["", "ESPAÇO DAS PARTIÇÕES (atualização a cada 30 s)"]
        for disk in sample["storage_percent"]:
            lines.append(f"{disk['disco']}: {fmt(disk['percent'], '%')} ocupado | livre {fmt(disk['free'], ' GiB')} / {fmt(disk['total'], ' GiB')}")
        self.resource_text.setPlainText("\n".join(lines))

    def update_network(self, sample):
        network = sample["network"]
        ping = sample.get("ping")
        ping_text = ("<" if ping.get("less_than") else "") + fmt(ping.get("ms"), " ms") if ping else "N/D — timeout ou ICMP indisponível"
        lines = ["REDE", "", f"Download: {fmt(network.get('download_mbs'), ' MiB/s', 2)}",
                 f"Upload: {fmt(network.get('upload_mbs'), ' MiB/s', 2)}",
                 f"Total recebido: {fmt(network.get('total_down_mb'), ' MiB')}",
                 f"Total enviado: {fmt(network.get('total_up_mb'), ' MiB')}",
                 f"Ping 8.8.8.8 (aprox. 5 s): {ping_text}", "", "INTERFACES ATIVAS"]
        lines += [f"{item['name']} | {item['ip']} | {item['speed_mbps']} Mbps" for item in sample.get("net_info", [])]
        lines += ["", "Tráfego agregado das interfaces. VPNs/adaptadores virtuais podem duplicar contagem.",
                  "Ping não mede FPS nem a latência específica do jogo."]
        self.network.setPlainText("\n".join(lines))

    def restore(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if QSystemTrayIcon.isSystemTrayAvailable() and not self._closed:
            event.ignore()
            self.hide()
        else:
            self.shutdown()
            event.accept()

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self.timer.stop()
        self.hotkey.close()
        self.worker_monitor.stop()
        self.recorder.shutdown()
        self.analysis.shutdown()
        self.tray.hide()
