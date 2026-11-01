import os
from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QPointF, QStandardPaths
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QLineEdit, QFileDialog, QPlainTextEdit, QTabWidget, QGroupBox)

from modules.diagnostics import metrics
from modules.frametimes import find_presentmon


def fmt(value, suffix="", digits=1):
    return f"{value:.{digits}f}{suffix}" if isinstance(value, (int, float)) else "N/D"


class HistoryChart(QWidget):
    series = [("cpu_max_core", "Núcleo mais ocupado", "#8d9eff"),
              ("ram_percent", "RAM", "#5bdbb0"), ("gpu_max_percent", "GPU mais ocupada", "#f4c479")]

    def __init__(self):
        super().__init__()
        self.points = deque(maxlen=500)
        self.markers = deque(maxlen=120)
        self.setMinimumHeight(165)

    def add(self, sample):
        self.points.append((sample["monotonic"], metrics(sample)))
        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#151b28"))
        left, top, width, height = 38, 32, self.width() - 52, self.height() - 56
        for value in (0, 50, 100):
            y = top + height * (1 - value / 100)
            painter.setPen(QColor("#30384a"))
            painter.drawLine(QPointF(left, y), QPointF(left + width, y))
            painter.setPen(QColor("#a8b4ca"))
            painter.drawText(4, int(y + 4), str(value))
        for index, (_, label, color) in enumerate(self.series):
            painter.setPen(QColor(color))
            painter.drawText(left + index * max(175, width // 3), 20, label)
        if not self.points:
            return
        end = self.points[-1][0]
        for key, _, color in self.series:
            path = QPainterPath()
            connected, previous = False, None
            for timestamp, row in self.points:
                if timestamp < end - 60:
                    continue
                value = row.get(key)
                if value is None:
                    connected = False
                    continue
                point = QPointF(left + width * (timestamp - end + 60) / 60,
                                top + height * (1 - min(100, max(0, value)) / 100))
                if connected and previous is not None and timestamp - previous <= 2:
                    path.lineTo(point)
                else:
                    path.moveTo(point)
                connected, previous = True, timestamp
            painter.setPen(QPen(QColor(color), 1.8))
            painter.drawPath(path)
        painter.setPen(QPen(QColor("#ff8b9d"), 1, Qt.DashLine))
        for timestamp in self.markers:
            if end - 60 <= timestamp <= end:
                x = left + width * (timestamp - end + 60) / 60
                painter.drawLine(QPointF(x, top), QPointF(x, top + height))
        painter.setPen(QColor("#a8b4ca"))
        painter.drawText(left, self.height() - 6, "−60 s")
        painter.drawText(self.width() - 55, self.height() - 6, "agora")


class DiagnosticPanel(QWidget):
    start_requested = Signal(dict)
    stop_requested = Signal()
    mark_requested = Signal()
    interval_changed = Signal(float)
    lhm_changed = Signal(bool)
    analyze_requested = Signal(str)
    configure_ai = Signal()
    advanced_requested = Signal()

    def __init__(self):
        super().__init__()
        self.session_path = None
        layout = QVBoxLayout(self)
        title = QLabel("Investigue o que está lento")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel("Escolha a tarefa, inicie e use o computador. Marque quando perceber o problema.\n"
                       "A análise reúne as evidências ao encerrar; a IA só trabalha depois da captura.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        setup = QGridLayout()
        self.symptom = QComboBox()
        for label, value in (("Computador lento", "system"), ("Programa demora", "application"),
                             ("Imagem engasga / FPS cai", "graphics"), ("Áudio corta", "audio"),
                             ("Conexão ruim", "network")):
            self.symptom.addItem(label, value)
        self.mode = QComboBox()
        self.mode.addItem("Leve · acompanhe a sessão inteira", "light")
        if os.name == "nt":
            self.mode.addItem("Detalhada · aguarde o próximo sintoma", "circular")
            self.mode.addItem("Detalhada · reprodução curta (até 3 min)", "detail")
        self.duration = QComboBox()
        for minutes in (15, 30, 60, 120):
            self.duration.addItem(f"{minutes} minutos", minutes * 60)
        self.duration.setCurrentIndex(1)
        self.target = QComboBox()
        self.target.addItem("Sistema inteiro", None)
        setup.addWidget(QLabel("O que está acontecendo?"), 0, 0)
        setup.addWidget(QLabel("Como acompanhar?"), 0, 1)
        setup.addWidget(self.symptom, 1, 0)
        setup.addWidget(self.mode, 1, 1)
        setup.addWidget(QLabel("Aplicativo"), 2, 0)
        setup.addWidget(QLabel("Duração máxima"), 2, 1)
        setup.addWidget(self.target, 3, 0)
        setup.addWidget(self.duration, 3, 1)
        layout.addLayout(setup)
        self.budget = QLabel()
        self.budget.setWordWrap(True)
        self.budget.setObjectName("muted")
        layout.addWidget(self.budget)
        self.mode.currentIndexChanged.connect(self.update_budget)
        self.duration.currentIndexChanged.connect(self.update_budget)
        self.ai_button = QPushButton("IA opcional · escolher antes, analisar depois")
        self.ai_button.setObjectName("secondary")
        self.ai_button.clicked.connect(self.configure_ai.emit)
        layout.addWidget(self.ai_button)
        controls = QHBoxLayout()
        self.start = QPushButton("Iniciar investigação")
        self.start.setObjectName("primary")
        self.mark = QPushButton("Marcar problema · Ctrl+Alt+F8")
        self.stop = QPushButton("Encerrar e analisar")
        self.start.clicked.connect(self.request_start)
        self.mark.clicked.connect(self.mark_requested.emit)
        self.stop.clicked.connect(self.request_stop)
        self.mark.setEnabled(False)
        self.stop.setEnabled(False)
        self.mark.hide()
        self.stop.hide()
        for button in (self.start, self.mark, self.stop):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Observação opcional para a próxima marcação")
        layout.addWidget(self.note)
        self.options = QGroupBox("Mais opções")
        self.options.setCheckable(True)
        self.options.setChecked(False)
        advanced = QVBoxLayout(self.options)
        self.options_body = QWidget()
        body = QVBoxLayout(self.options_body)
        options = QHBoxLayout()
        self.interval = QComboBox()
        for label, value in (("250 ms · mais detalhes", .25), ("500 ms · equilibrado", .5), ("1 s · menor custo", 1.0)):
            self.interval.addItem(label, value)
        self.interval.setCurrentIndex(1)
        self.interval.currentIndexChanged.connect(lambda: self.interval_changed.emit(self.interval.currentData()))
        self.lhm = QCheckBox("Sensores extras via LibreHardwareMonitor")
        self.lhm.setToolTip("Ative o servidor local do LibreHardwareMonitor na porta 8085.")
        self.lhm.toggled.connect(self.lhm_changed.emit)
        self.frames = QCheckBox("Capturar frametimes do aplicativo com PresentMon")
        self.frames.setEnabled(os.name == "nt")
        self.symptom.currentIndexChanged.connect(lambda: self.frames.setChecked(os.name == "nt" and self.symptom.currentData() == "graphics"))
        options.addWidget(self.interval)
        options.addWidget(self.lhm)
        body.addLayout(options)
        body.addWidget(self.frames)
        self.presentmon = QLineEdit()
        self.presentmon.setPlaceholderText("Caminho opcional para PresentMon.exe")
        body.addWidget(self.presentmon)
        base = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home())
        self.folder = QLineEdit(str(Path(base) / "SysPulse" / "diagnosticos"))
        self.folder.setReadOnly(True)
        destination = QHBoxLayout()
        self.choose = QPushButton("Destino…")
        self.choose.clicked.connect(self.choose_folder)
        destination.addWidget(self.folder, 1)
        destination.addWidget(self.choose)
        body.addLayout(destination)
        files = QHBoxLayout()
        self.open = QPushButton("Pasta da sessão")
        self.open.clicked.connect(self.open_session)
        self.open.setEnabled(False)
        self.analyze = QPushButton("Ver resultado")
        self.analyze.clicked.connect(lambda: self.analyze_requested.emit(self.session_path) if self.session_path else None)
        self.analyze.setEnabled(False)
        detailed = QPushButton("Abrir ETL e detalhes técnicos")
        detailed.clicked.connect(self.advanced_requested.emit)
        for button in (self.analyze, self.open, detailed):
            files.addWidget(button)
        body.addLayout(files)
        advanced.addWidget(self.options_body)
        self.options_body.hide()
        self.options.toggled.connect(self.options_body.setVisible)
        layout.addWidget(self.options)
        self.update_budget()
        self.status = QLabel("Monitorando • gravação desligada")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.hotkey_status = QLabel()
        self.hotkey_status.setWordWrap(True)
        layout.addWidget(self.hotkey_status)
        cards = QGridLayout()
        self.cards = {}
        for index, key in enumerate(("cpu", "ram", "gpu", "disk", "temperature", "collector")):
            label = QLabel("Aguardando dados…")
            label.setObjectName("card")
            label.setWordWrap(True)
            self.cards[key] = label
            cards.addWidget(label, index // 3, index % 3)
        layout.addLayout(cards)
        self.chart = HistoryChart()
        layout.addWidget(self.chart)
        self.details = QTabWidget()
        self.readings = QPlainTextEdit()
        self.events = QPlainTextEdit()
        for box in (self.readings, self.events):
            box.setReadOnly(True)
            box.setMaximumBlockCount(300)
        self.details.addTab(self.readings, "Leituras / disponibilidade")
        self.details.addTab(self.events, "Marcações")
        layout.addWidget(self.details, 1)


    def update_budget(self):
        circular = self.mode.currentData() == "circular"
        detail = self.mode.currentData() == "detail"
        text = ("Detalhes recentes em memória · orçamento de 128 MiB. A marcação salva após 5 s e encerra. "
                "O início da sessão pode já ter sido sobrescrito." if circular else
                "WPR em arquivo · até 3 min e limite aproximado de 1 GiB. Requer administrador." if detail else
                "Sessão compacta, até 2 h e 256 MiB antes da compressão. O tamanho depende das fontes.")
        self.budget.setText(text)
        self.duration.setEnabled(not detail)

    def update_processes(self, rows):
        if self.target.view().isVisible() or self.target.hasFocus():
            return
        selected = self.target.currentData()
        self.target.blockSignals(True)
        self.target.clear()
        self.target.addItem("Sistema inteiro", None)
        for row in sorted(rows, key=lambda item: (item.get("name", "").lower(), item["pid"])):
            self.target.addItem(f"{row.get('name', '?')} · PID {row['pid']}", row["pid"])
        index = self.target.findData(selected)
        self.target.setCurrentIndex(max(0, index))
        self.target.blockSignals(False)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Pasta para os diagnósticos", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def request_start(self):
        if self.frames.isChecked() and self.target.currentData() is None:
            self.status.setText("Selecione o aplicativo para medir seus quadros. Sistema inteiro continua disponível sem frametimes.")
            return
        if self.frames.isChecked() and not find_presentmon(self.presentmon.text().strip()):
            self.status.setText("Informe o executável do PresentMon em Mais opções para medir os quadros.")
            return
        self.start.setEnabled(False)
        self.start_requested.emit({"folder": self.folder.text(), "interval_ms": self.interval.currentData() * 1000,
                                   "compressed": True, "csv": False, "mode": self.mode.currentData(),
                                   "duration_s": self.duration.currentData(), "symptom": self.symptom.currentData(),
                                   "target_pid": self.target.currentData(), "frames": self.frames.isChecked(),
                                   "presentmon": self.presentmon.text().strip()})

    def request_stop(self):
        self.stop.setEnabled(False)
        self.stop_requested.emit()

    def open_session(self):
        if self.session_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.session_path))

    def set_status(self, status):
        active = status["active"]
        self.start.setEnabled(not active)
        self.start.setVisible(not active)
        self.mark.setVisible(active)
        self.stop.setVisible(active)
        for widget in (self.mode, self.duration, self.target, self.symptom, self.ai_button):
            widget.setEnabled(not active)
        self.mark.setEnabled(active)
        self.stop.setEnabled(active)
        self.interval.setEnabled(not active)
        self.choose.setEnabled(not active)
        self.session_path = status.get("path")
        self.open.setEnabled(bool(self.session_path))
        self.analyze.setEnabled(bool(self.session_path) and not active)
        if active and status.get("count") == 0 and "marker" not in status:
            self.events.clear()
            self.chart.markers.clear()
        self.status.setText(status["message"] + (f" • perdidas: {status['dropped']}" if status.get("dropped") else ""))
        if "marker" in status:
            event = status["marker"]
            self.chart.markers.append(event["monotonic"])
            self.events.appendPlainText(f"#{event['id']} · {event['timestamp']}\n{event['note']}")
        if status.get("error"):
            self.events.appendPlainText(status["message"])

    def update_sample(self, sample):
        row = metrics(sample)
        self.cards["cpu"].setText(f"CPU {fmt(sample['cpu_percent'], '%')}\nMaior núcleo: {fmt(sample['cpu_max_core'], '%')}")
        self.cards["ram"].setText(f"RAM {fmt(sample['ram_percent'], '%')}\nDisponível: {fmt(sample['ram_available_gb'], ' GiB')}")
        self.cards["gpu"].setText(f"GPU {fmt(row['gpu_max_percent'], '%')}\nMaior carga entre as GPUs")
        self.cards["disk"].setText(f"Disco ativo {fmt(row['disk_max_active_percent'], '%')}\nLeitura: {fmt(row['disk_max_read_ms'], ' ms/op')}")
        self.cards["temperature"].setText(f"CPU {fmt(sample.get('cpu_temperature'), ' °C')}\nGPU {fmt(row['gpu_max_temperature'], ' °C')}")
        self.cards["collector"].setText(f"Intervalo real {fmt(sample['interval_ms'], ' ms', 0)}\nCusto da coleta: {fmt(sample['collector_ms'], ' ms')}")
        lines = [sample.get("sensor_status", "Sensores inicializando"),
                 f"Idade dos sensores: {fmt(sample.get('sensor_age_ms'), ' ms', 0)} | Processos: {fmt(sample['process_age_ms'], ' ms', 0)}",
                 f"Frequência CPU reportada pelo SO: {fmt(sample.get('cpu_freq_mhz'), ' MHz', 0)} (não é clock efetivo por núcleo)",
                 f"RAM livre: {fmt(sample['ram_available_gb'], ' GiB')} | Uso do swap/pagefile: {fmt(sample['swap_percent'], '%')}",
                 f"Leituras de páginas: {fmt(sample.get('page_reads_s'), '/s')} | CPU em DPC: {fmt(sample.get('dpc_percent'), '%')} | Interrupções: {fmt(sample.get('interrupt_percent'), '%')}",
                 "Núcleos lógicos: " + "  ".join(f"{i}: {value:.0f}%" for i, value in enumerate(sample['cpu_cores'])), ""]
        for disk in sample.get("disks", []):
            lines.append(f"{disk['name']}: ler {fmt(disk['read_mbs'], ' MiB/s')} / gravar {fmt(disk['write_mbs'], ' MiB/s')} | "
                         f"latência {fmt(disk['read_ms'])}/{fmt(disk['write_ms'])} ms/op | "
                         f"ativo {fmt(disk['active_percent'], '%')} | fila {fmt(disk.get('queue'))}")
        for gpu in sample.get("gpus", []):
            lines.append(f"{gpu['name']} [{gpu['source']}]: {fmt(gpu.get('percent'), '%')} | "
                         f"VRAM {fmt(gpu.get('memory_used_mb'), '', 0)}/{fmt(gpu.get('memory_total_mb'), ' MiB', 0)} | "
                         f"{fmt(gpu.get('temperature'), ' °C')} | {fmt(gpu.get('clock_mhz'), ' MHz', 0)} | {fmt(gpu.get('power_w'), ' W')}")
        for sensor in sample.get("sensors", []):
            lines.append(f"{sensor['id']} · {sensor['name']}: {sensor['display'] or fmt(sensor['value'])}")
        lines += ["", "N/D = indisponível ou sem operações na janela. Espaço ocupado não é atividade de disco.",
                  "GPU AMD/Intel e sensores extras dependem do LibreHardwareMonitor e do suporte do hardware.",
                  "Amostragem não mede FPS/frametime nem descarta travamentos mais curtos que o intervalo."]
        scrollbar = self.readings.verticalScrollBar()
        position = scrollbar.value()
        self.readings.setPlainText("\n".join(lines))
        scrollbar.setValue(position)
