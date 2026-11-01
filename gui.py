import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QAbstractTableModel, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QStackedWidget, QProgressBar, QTabWidget, QTableView,
    QHeaderView, QSystemTrayIcon, QMenu, QStyle, QPlainTextEdit, QScrollArea)

from modules.hardware import get_hardware_info
from modules.monitor import MonitorWorker
from modules.diagnostics import SessionRecorder
from modules.diagnostic_view import DiagnosticPanel, fmt
from modules.hotkey import GlobalHotkey
from modules.analysis_view import AnalysisPanel
from modules.inspection import InspectionService
from modules.inspection_view import InspectionPanel
from modules.advanced_view import AdvancedPanel
from modules.activity import ActivityState
from modules.stress_view import StressPanel
from modules.version import VERSION
from modules.ai_settings import AIConfig, AISettingsPanel
from modules.overview_view import LivePanel, HardwarePanel, NetworkPanel


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
QPushButton#primary { background: #627ee6; font-weight: bold; padding: 12px 18px; }
QPushButton#primary:hover { background: #7892f5; }
QPushButton#primary:disabled { background: #242b3a; color: #7b879b; }
QPushButton#secondary { background: #20293b; color: #c1cce4; }
QPushButton#aiMode { background: #20293b; border: 2px solid #34405a; color: #becbe1; }
QPushButton#aiMode:hover { background: #2d3953; border-color: #6b83d7; }
QPushButton#aiMode:checked { background: #344b90; border-color: #9cb0ff; color: #ffffff; font-weight: bold; }
QPushButton#aiMode:disabled { color: #7b879b; }
QGroupBox::indicator { width: 16px; height: 16px; border: 1px solid #63749a; border-radius: 3px; background: #1d2638; }
QGroupBox::indicator:checked { background: #7f98fa; border-color: #b4c4ff; }
QGroupBox { border: 1px solid #34405a; border-radius: 7px; margin-top: 14px; padding: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #151d2c; width: 12px; }
QScrollBar::handle:vertical { background: #354867; border-radius: 5px; min-height: 30px; }
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
    inventory_ready = Signal(dict)

    def __init__(self, demo=False):
        super().__init__()
        self.demo = demo
        self.setWindowTitle(f"SYS-PULSE {VERSION} — Monitoramento e análise" + (" — DADOS SIMULADOS" if demo else ""))
        self.resize(1280, 820)
        self.setMinimumSize(980, 680)
        self.activity = ActivityState()
        self.ai_config = AIConfig(self.activity)
        self.ai_config.demo = demo
        self._capture_mode = "light"
        self.setStyleSheet(STYLE)
        self.setWindowIcon(QIcon(str(Path(__file__).parent / "assets" / "syspulse.svg")))
        self._closed = False
        self._last_sample = self._last_processes = None
        self._last_paint = 0
        self._hardware_loaded = False
        self._inventory = None
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
        navigation.addWidget(QLabel(f"Performance sob análise\nv{VERSION}"))
        self.pages = QStackedWidget()
        layout.addWidget(sidebar)
        layout.addWidget(self.pages, 1)
        self.hardware = HardwarePanel()
        self.hardware.refresh_requested.connect(self.reload_hardware)
        self.pages.addWidget(self.hardware)
        self.monitor = QTabWidget()
        self.pages.addWidget(self.monitor)
        self.dashboard = LivePanel()
        self.dashboard.investigate.connect(lambda: self.show_page(3))
        self.monitor.addTab(self.dashboard, "Visão geral")
        self.process_table = QTableView()
        self.process_model = ProcessTableModel()
        self.process_table.setModel(self.process_model)
        self.process_table.setSortingEnabled(True)
        self.process_table.sortByColumn(2, Qt.DescendingOrder)
        self.process_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.monitor.addTab(self.process_table, "Processos")
        self.network = NetworkPanel()
        self.pages.addWidget(self.network)
        self.diagnostic = DiagnosticPanel()
        diagnostic_scroll = QScrollArea()
        diagnostic_scroll.setWidgetResizable(True)
        diagnostic_scroll.setWidget(self.diagnostic)
        self.pages.addWidget(diagnostic_scroll)
        self.analysis = AnalysisPanel(self.ai_config)
        self.pages.addWidget(self.analysis)
        from modules.diagnostic_tools_view import DiagnosticToolsPanel
        self.inspection = InspectionPanel()
        self.driver_tools = DiagnosticToolsPanel(self.activity, demo=demo)
        self.inspection.tabs.addTab(self.driver_tools, "Atualizações e LatencyMon")
        self.pages.addWidget(self.inspection)
        self.inspection_service = InspectionService(self.inventory_ready.emit)
        self.inventory_ready.connect(self.on_inventory)
        self.inspection.refresh_requested.connect(self.refresh_inventory)
        self.advanced = AdvancedPanel(demo=demo, ai_config=self.ai_config)
        self.pages.addWidget(self.advanced)
        self.settings_panel = AISettingsPanel(self.ai_config)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(self.settings_panel)
        self.pages.addWidget(settings_scroll)
        self.stress = StressPanel(self.activity, demo=demo)
        stress_scroll = QScrollArea()
        stress_scroll.setWidgetResizable(True)
        stress_scroll.setWidget(self.stress)
        self.pages.addWidget(stress_scroll)
        self.stress.ready.connect(self.analyze_capture)
        self.analysis.ai.configure_requested.connect(lambda: self.show_page(7))
        self.advanced.ai.configure_requested.connect(lambda: self.show_page(7))
        self.diagnostic.configure_ai.connect(lambda: self.show_page(7))
        self.diagnostic.advanced_requested.connect(lambda: self.show_page(6))
        self.advanced.capture_state.connect(self.on_advanced_state)
        self.advanced.recorder_status.connect(self.diagnostic.update_frame_stats)
        self.advanced.ready.connect(lambda generation, result, destination: self.show_page(6)
                                    if generation == self.advanced._generation else None)
        self.activity.changed.connect(self.on_activity)
        self.ai_config.changed.connect(lambda: self.diagnostic.ai_button.setText(
            ("Análise integrada · sem IA" if not self.ai_config.enabled else
             "Online anônima · sem conta · usar após a captura" if self.ai_config.provider == "horde" else
             f"IA · {self.ai_config.model or 'escolher modelo'} · usar após a captura")))
        self.nav_buttons = []
        for index, name in ((1, "VISÃO GERAL"), (3, "INVESTIGAR"), (4, "SESSÕES"),
                            (8, "TESTES DE ESTRESSE"), (7, "CONFIGURAÇÕES"), (0, "HARDWARE"), (2, "REDE"), (5, "DRIVERS E SAÚDE")):
            button = QPushButton(name)
            button.setObjectName("navigation")
            button.setCheckable(True)
            button.setProperty("page", index)
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
                self.dashboard.add_history(sample)
            for event in self.worker_monitor.markers:
                self.diagnostic.chart.markers.append(event["monotonic"])
                self.diagnostic.events.appendPlainText(f"#{event['id']} · {event['timestamp']}\n{event['note']}")
        else:
            self.worker_monitor = MonitorWorker(self.submit_sample)
        self.diagnostic.start_requested.connect(lambda options: self.send_command("start", options))
        self.diagnostic.stop_requested.connect(lambda: self.send_command("stop"))
        self.diagnostic.mark_requested.connect(self.mark_stutter)
        self.diagnostic.analyze_requested.connect(self.open_result)
        self.diagnostic.interval_changed.connect(lambda interval: setattr(self.worker_monitor, "interval", interval))
        self.diagnostic.lhm_changed.connect(lambda enabled: setattr(self.worker_monitor.sensors, "lhm_enabled", enabled))
        self.network.target_changed.connect(self.change_ping_target)
        self.hotkey = GlobalHotkey(QApplication.instance(), self.mark_stutter, enabled=not demo)
        self.diagnostic.hotkey_status.setText("Ctrl + Alt + F8: atalho global ativo" if self.hotkey.registered else self.hotkey.error)
        if not self.hotkey.registered:
            self.shortcut = QShortcut(QKeySequence("Ctrl+Alt+F8"), self)
            self.shortcut.activated.connect(self.mark_stutter)
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
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
        if demo:
            from modules.demo import demo_inventory, demo_advanced
            self.advanced.accept_result(0, demo_advanced())
            self.on_inventory(demo_inventory())
            self.inspection.refresh_button.setEnabled(False)
        else:
            self.refresh_inventory()
        self.show_page(1)
        if demo:
            self.analyze_capture(str(Path(__file__).parent / "examples" / "sessao-demo"))

    def submit_sample(self, sample):
        self.recorder.submit(sample)
        self.advanced.submit(sample)
        self.stress.submit(sample)

    def refresh_inventory(self):
        if self.inspection_service.refresh():
            self.inspection.refresh_button.setEnabled(False)
            self.inspection.status.setText("Consultando o Windows… até 45 s; monitoramento continua ativo.")

    def on_inventory(self, snapshot):
        if self._closed:
            return
        self._inventory = snapshot
        self.advanced.inventory = snapshot
        self.stress.inventory = snapshot
        self.stress.update_state()
        if self.advanced.recorder.active.is_set():
            self.advanced.recorder.command("inventory", snapshot)
        self.inspection.set_snapshot(snapshot)
        self.on_activity()
        if self.recorder.active.is_set():
            if not self.recorder.command("inventory", snapshot):
                self.inspection.status.setText("Inventário disponível na tela; fila cheia impediu anexar à captura.")

    def on_recording_status(self, status):
        if status.get("completed") or status.get("error"):
            self.activity.end_capture("native")
        if status.get("started") and self._inventory:
            self.on_inventory(self._inventory)
        if status.get("completed") and status.get("count") and not self._closed:
            self.analyze_capture(status["path"], auto_save=True)

    def analyze_capture(self, source, auto_save=False):
        self.show_page(4)
        self.analysis.load(source, auto_save)

    def show_page(self, index):
        self.pages.setCurrentIndex(index)
        for button in self.nav_buttons:
            button.setChecked(button.property("page") == index)
        if index == 0 and not self._hardware_loaded and not self.activity.capture:
            self._hardware_loaded = True
            threading.Thread(target=self.load_hardware, name="sys-pulse-hardware", daemon=True).start()
        self._last_paint = 0
        if index == 3:
            self._last_processes = None

    def load_hardware(self):
        try:
            report = ("DEMONSTRAÇÃO — DADOS SIMULADOS\n\nSistema: Windows 11\nCPU: processador de demonstração (6 núcleos / 12 threads)\n"
                      "RAM: 32 GiB\nGPU: GPU de demonstração\n\nExecute sem --demo para consultar seu hardware." if self.demo else get_hardware_info())
        except Exception as error:
            report = f"Não foi possível consultar o hardware: {error}"
        if not self._closed:
            self.hardware_ready.emit(report)

    def send_command(self, kind, payload=None):
        if kind == "start":
            if self.demo:
                return
            if self._inventory is None:
                self.diagnostic.set_status({"active": False, "message": "Preparando o inventário inicial. Aguarde a conclusão antes de capturar."})
                self.on_activity()
                return
            payload = {**(payload or {}), "inventory": self._inventory}
            self._capture_mode = payload.get("mode", "light")
            try:
                if self._capture_mode in ("circular", "detail"):
                    self.activity.begin_capture("advanced")
                    self.advanced.session_options = payload
                    self.advanced.start_capture(payload["folder"],
                                                payload.get("duration_s", 1800) if self._capture_mode == "circular" else 180,
                                                self._capture_mode)
                    return
                self.activity.begin_capture("native")
                self.worker_monitor.target_pid = payload.get("target_pid")
            except (RuntimeError, ValueError, OSError) as error:
                self.diagnostic.set_status({"active": False, "message": str(error)})
                return
        if kind == "stop" and self.activity.capture == "advanced":
            self.advanced.stop_capture()
            return
        if not self.recorder.command(kind, payload):
            if kind == "start":
                self.activity.end_capture("native")
            self.diagnostic.set_status({"active": self.recorder.active.is_set(), "path": str(self.recorder.path or ""),
                                        "message": "Gravador ocupado. Tente novamente; o comando não foi registrado.", "error": True})

    def on_activity(self):
        busy = self.activity.busy
        self.diagnostic.start.setEnabled(not busy and not self.demo and self._inventory is not None)
        self.hardware.refresh_button.setEnabled(not busy)
        self.network.apply.setEnabled(not busy)
        self.network.target.setEnabled(not busy)
        self.inspection.refresh_button.setEnabled(not busy and not self.demo)
        self.advanced.update_buttons()

    def on_advanced_state(self, state):
        if self._capture_mode not in ("circular", "detail"):
            return
        active = state.get("state") not in ("completed", "failed", "cancelled")
        self.diagnostic.set_status({"active": active, "message": state.get("message", ""),
                                    "path": str(self.advanced.controller.path or "")})
        self.on_activity()

    def open_result(self, path):
        if self._capture_mode in ("circular", "detail"):
            self.show_page(6)
        else:
            self.analyze_capture(path)

    def reload_hardware(self):
        if not self.activity.capture:
            self.hardware.refresh_button.setEnabled(False)
            threading.Thread(target=self.load_hardware, name="sys-pulse-hardware", daemon=True).start()

    def change_ping_target(self, target):
        if not self.demo and not self.activity.capture:
            self.worker_monitor.sensors.ping_target = target


    def mark_stutter(self):
        if self.stress.phase:
            self.stress.mark(self.diagnostic.note.text() or "Sintoma percebido durante o teste")
            return
        self.advanced.note.setText(self.diagnostic.note.text())
        self.advanced.mark()
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
            self.dashboard.add_history(sample)
            self._last_sample = sample
        if not self.isVisible() or self.isMinimized() or time.monotonic() - self._last_paint < 0.5:
            return
        self._last_paint = time.monotonic()
        page = self.pages.currentIndex()
        if page == 3:
            self.diagnostic.update_sample(sample)
            if sample["processes"] is not self._last_processes and not self.activity.capture:
                self.diagnostic.update_processes(sample["processes"])
                self._last_processes = sample["processes"]
        elif page == 1:
            self.update_resources(sample)
            if sample["processes"] is not self._last_processes:
                self.process_model.update_rows(sample["processes"])
                self._last_processes = sample["processes"]
        elif page == 2:
            self.update_network(sample)

    def update_resources(self, sample):
        self.dashboard.update_sample(sample)

    def update_network(self, sample):
        self.network.update_sample(sample)

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
        self.stress.shutdown()
        self.settings_panel.shutdown()
        self.timer.stop()
        self.hotkey.close()
        self.worker_monitor.stop()
        self.recorder.shutdown()
        self.analysis.shutdown()
        self.advanced.shutdown()
        self.inspection_service.stop()
        self.driver_tools.shutdown()
        self.tray.hide()
