from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QPointF, QStandardPaths
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QCheckBox, QLineEdit, QFileDialog, QPlainTextEdit, QTabWidget)

from modules.diagnostics import metrics


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

    def __init__(self):
        super().__init__()
        self.session_path = None
        layout = QVBoxLayout(self)
        title = QLabel("Captura de performance")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel("Inicie a gravação, use o PC e marque a travadinha com Ctrl + Alt + F8.\n"
                       "Aguarde pelo menos 5 segundos após a última marcação antes de encerrar.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        options = QHBoxLayout()
        self.interval = QComboBox()
        for label, value in (("250 ms", 0.25), ("500 ms", 0.5), ("1 segundo", 1.0)):
            self.interval.addItem(label, value)
        self.interval.setCurrentIndex(1)
        self.interval.currentIndexChanged.connect(lambda: self.interval_changed.emit(self.interval.currentData()))
        options.addWidget(QLabel("Coleta:"))
        options.addWidget(self.interval)
        self.lhm = QCheckBox("Ler LibreHardwareMonitor (local:8085)")
        self.lhm.setToolTip("Opcional: abra o LibreHardwareMonitor e ative Options > Remote Web Server > Run na porta 8085.")
        self.lhm.toggled.connect(self.lhm_changed.emit)
        options.addWidget(self.lhm)
        options.addStretch()
        layout.addLayout(options)
        destination = QHBoxLayout()
        base = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home())
        self.folder = QLineEdit(str(Path(base) / "SysPulse" / "diagnosticos"))
        self.folder.setReadOnly(True)
        self.choose = QPushButton("Pasta…")
        self.choose.clicked.connect(self.choose_folder)
        destination.addWidget(self.folder)
        destination.addWidget(self.choose)
        layout.addLayout(destination)
        controls = QHBoxLayout()
        self.start = QPushButton("Iniciar gravação")
        self.mark = QPushButton("Marcar travadinha")
        self.stop = QPushButton("Encerrar gravação")
        self.open = QPushButton("Pasta da sessão")
        self.analyze = QPushButton("Analisar sessão")
        self.analyze.clicked.connect(lambda: self.analyze_requested.emit(self.session_path) if self.session_path else None)
        self.analyze.setEnabled(False)
        self.start.clicked.connect(self.request_start)
        self.mark.clicked.connect(self.mark_requested.emit)
        self.stop.clicked.connect(self.request_stop)
        self.open.clicked.connect(self.open_session)
        self.mark.setEnabled(False)
        self.stop.setEnabled(False)
        self.open.setEnabled(False)
        for button in (self.start, self.mark, self.stop, self.analyze, self.open):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Observação opcional para a próxima marcação (ex.: YouTube, jogo, áudio cortou)")
        layout.addWidget(self.note)
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

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Pasta para os diagnósticos", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def request_start(self):
        self.start.setEnabled(False)
        self.start_requested.emit({"folder": self.folder.text(), "interval_ms": self.interval.currentData() * 1000})

    def request_stop(self):
        self.stop.setEnabled(False)
        self.stop_requested.emit()

    def open_session(self):
        if self.session_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.session_path))

    def set_status(self, status):
        active = status["active"]
        self.start.setEnabled(not active)
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
