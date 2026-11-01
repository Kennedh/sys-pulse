from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
                              QPlainTextEdit, QLineEdit, QTabWidget, QGroupBox)

from modules.analysis_view import table, fill
from modules.diagnostic_view import HistoryChart, fmt
from modules.diagnostics import metrics
from modules.network import ping_statistics, validate_host


def cards(layout, labels, columns=3):
    grid, result = QGridLayout(), {}
    grid.setSpacing(12)
    for index, (key, label) in enumerate(labels):
        card = QLabel(label + "\nAguardando leitura")
        card.setObjectName("analysisCard")
        card.setWordWrap(True)
        card.setMinimumHeight(85)
        grid.addWidget(card, index // columns, index % columns)
        result[key] = card
    layout.addLayout(grid)
    return result


class LivePanel(QWidget):
    investigate = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        heading = QHBoxLayout()
        title = QLabel("Como o computador está agora?")
        title.setObjectName("title")
        heading.addWidget(title, 1)
        action = QPushButton("Investigar lentidão")
        action.setObjectName("primary")
        action.clicked.connect(self.investigate.emit)
        heading.addWidget(action)
        layout.addLayout(heading)
        self.status = QLabel("Medições disponíveis, sem presumir defeitos.")
        self.status.setObjectName("muted")
        layout.addWidget(self.status)
        self.cards = cards(layout, (("cpu", "CPU"), ("ram", "Memória"), ("gpu", "Gráficos"),
                                    ("disk", "Armazenamento"), ("temperature", "Temperaturas"), ("collection", "Coleta")))
        self.chart = HistoryChart()
        self.chart.setMinimumHeight(150)
        layout.addWidget(self.chart)
        self.disks = table(["Disco", "Atividade", "Leitura / escrita", "Latência R/W", "Fila"])
        self.disks.setMaximumHeight(165)
        layout.addWidget(self.disks)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(130)
        layout.addWidget(self.details)
        self._sample = None

    def add_history(self, sample):
        if sample is not self._sample:
            self.chart.add(sample)
            self._sample = sample

    def update_sample(self, sample):
        row = metrics(sample)
        self.cards["cpu"].setText(f"CPU · {fmt(sample.get('cpu_percent'), '%')}\nMaior núcleo: {fmt(sample.get('cpu_max_core'), '%')}")
        self.cards["ram"].setText(f"RAM · {fmt(sample.get('ram_percent'), '%')}\nDisponível: {fmt(sample.get('ram_available_gb'), ' GiB')}")
        self.cards["gpu"].setText(f"GPU · {fmt(row.get('gpu_max_percent'), '%')}\n" +
                                  (", ".join(g.get("name", "GPU") for g in sample.get("gpus", [])) or "Fonte de GPU indisponível"))
        self.cards["disk"].setText(f"Disco · {fmt(row.get('disk_max_active_percent'), '%')}\nMaior atividade observada")
        self.cards["temperature"].setText(f"CPU {fmt(sample.get('cpu_temperature'), ' °C')}\nGPU {fmt(row.get('gpu_max_temperature'), ' °C')}")
        self.cards["collection"].setText(f"Intervalo · {fmt(sample.get('interval_ms'), ' ms', 0)}\nColeta: {fmt(sample.get('collector_ms'), ' ms')}")
        self.status.setText(f"Desde o boot: {sample.get('uptime', 'N/D')} · N/D indica falta de leitura.")
        fill(self.disks, [[d.get("name"), fmt(d.get("active_percent"), "%"),
                           fmt(d.get("read_mbs")) + " / " + fmt(d.get("write_mbs")) + " MiB/s",
                           fmt(d.get("read_ms")) + " / " + fmt(d.get("write_ms")) + " ms/op",
                           fmt(d.get("queue"))] for d in sample.get("disks", [])])
        lines = ["Núcleos: " + " · ".join(f"{i}: {v:.0f}%" for i, v in enumerate(sample.get("cpu_cores", []))),
                 f"Memória comprometida: {fmt(sample.get('commit_gb'))} / {fmt(sample.get('commit_limit_gb'))} GiB",
                 f"Varredura de processos: {fmt(sample.get('process_collector_ms'), ' ms')} · idade {fmt(sample.get('process_age_ms'), ' ms')}",
                 sample.get("sensor_status", "Sensores inicializando")]
        for gpu in sample.get("gpus", []):
            lines.append(f"{gpu.get('name')}: VRAM {fmt(gpu.get('memory_used_mb'))}/{fmt(gpu.get('memory_total_mb'))} MiB · "
                         f"{fmt(gpu.get('clock_mhz'), ' MHz')} · {fmt(gpu.get('power_w'), ' W')}")
        for disk in sample.get("storage_percent", []):
            lines.append(f"{disk.get('disco')}: {fmt(disk.get('free'), ' GiB')} livres de {fmt(disk.get('total'), ' GiB')}")
        self.details.setPlainText("\n".join(lines))


class HardwarePanel(QWidget):
    refresh_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel("Seu computador")
        title.setObjectName("title")
        heading.addWidget(title, 1)
        self.refresh_button = QPushButton("Atualizar hardware")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        heading.addWidget(self.refresh_button)
        layout.addLayout(heading)
        self.cards = cards(layout, (("Processador", "Processador"), ("RAM total", "Memória"),
                                    ("GPU(s)", "Gráficos"), ("Placa-mãe", "Plataforma")), 2)
        self.details = QPlainTextEdit("Carregando informações de hardware…")
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)

    def setPlainText(self, text):
        self.details.setPlainText(text)
        lines = {key.strip(): value.strip() for line in text.splitlines() if ":" in line
                 for key, value in [line.split(":", 1)]}
        for key, widget in self.cards.items():
            widget.setText(key + "\n" + lines.get(key, "Consulte os detalhes"))
        self.refresh_button.setEnabled(True)

    def toPlainText(self):
        return self.details.toPlainText()


class NetworkPanel(QWidget):
    target_changed = Signal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("Sua conexão, além da velocidade")
        title.setObjectName("title")
        layout.addWidget(title)
        self.cards = cards(layout, (("traffic", "Tráfego"), ("latency", "Latência"),
                                    ("replies", "Respostas ICMP")))
        row = QHBoxLayout()
        self.target = QLineEdit("8.8.8.8")
        self.target.setPlaceholderText("IP ou servidor para testar")
        self.apply = QPushButton("Usar este destino")
        self.apply.clicked.connect(self.set_target)
        row.addWidget(QLabel("Destino de teste"))
        row.addWidget(self.target, 1)
        row.addWidget(self.apply)
        layout.addLayout(row)
        self.status = QLabel("Ping não mede FPS nem a latência específica de um aplicativo.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.interfaces = table(["Interface", "IP", "Máscara", "Link informado", "MTU"])
        self.interfaces.setMaximumHeight(200)
        layout.addWidget(self.interfaces)
        self.history = table(["Última tentativa", "Tempo de resposta"])
        layout.addWidget(self.history, 1)
        note = QLabel("Ausência de resposta pode ser filtragem ICMP. VPNs e adaptadores virtuais podem duplicar tráfego agregado.")
        note.setWordWrap(True)
        layout.addWidget(note)

    def set_target(self):
        try:
            host = validate_host(self.target.text())
            self.target_changed.emit(host)
            self.status.setText("Novo destino aplicado. O histórico será reiniciado na próxima tentativa.")
        except ValueError as error:
            self.status.setText(str(error))

    def update_sample(self, sample):
        net, history = sample.get("network", {}), sample.get("ping_history", [])
        stats = ping_statistics(history)
        self.cards["traffic"].setText(f"Download {fmt(net.get('download_mbs'), ' MiB/s')}\nUpload {fmt(net.get('upload_mbs'), ' MiB/s')}")
        self.cards["latency"].setText(f"Média {fmt(stats['mean_ms'], ' ms')} · maior {fmt(stats['max_ms'], ' ms')}\n"
                                      f"Variação média {fmt(stats['variation_ms'], ' ms')}")
        self.cards["replies"].setText(f"{stats['replies']} / {stats['attempts']} respostas\n{stats['timeouts']} sem resposta · janela recente")
        fill(self.interfaces, [[r.get("name"), r.get("ip"), r.get("netmask", "N/D"),
                                fmt(r.get("speed_mbps"), " Mbps"), r.get("mtu", "N/D")] for r in sample.get("net_info", [])])
        at = sample.get("monotonic", 0)
        fill(self.history, [[f"há {max(0, at - r['at']):.0f} s", fmt(r.get("ms"), " ms") if r.get("ms") is not None else "Sem resposta ICMP"]
                            for r in reversed(history[-30:])])
