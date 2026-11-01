import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QLineEdit, QPlainTextEdit, QMessageBox, QAbstractItemView, QToolTip)

from modules.ai_summary import AISummaryPanel
from modules.advanced_analysis import readable_report
from modules.analysis import (analyze_session, save_report, report_text, ranked_processes,
                              display_time, fmt, AnalysisCancelled)


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectRows)
    widget.setAlternatingRowColors(True)
    widget.verticalHeader().hide()
    widget.verticalHeader().setDefaultSectionSize(35)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    widget.horizontalHeader().setStretchLastSection(True)
    return widget


def fill(widget, rows):
    widget.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            widget.setItem(i, j, item)


class SessionChart(QWidget):
    series = [("cpu", "CPU", "#8d9eff"), ("core", "Maior núcleo", "#c7a1ff"),
              ("ram", "RAM", "#5bdbb0"), ("gpu", "GPU", "#f4c479"),
              ("disk", "Disco", "#7dcfff")]

    def __init__(self):
        super().__init__()
        self.points, self.markers = [], []
        self.duration = 1
        self.setMinimumHeight(170)
        self.setMouseTracking(True)
        self.setToolTip("Histórico completo da sessão. Em sessões longas, preserva o pico de cada intervalo visual.")

    def set_result(self, result):
        self.points = result["summary"]["chart"]
        self.duration = max(result["summary"]["duration_s"], .001)
        first = result["summary"].get("start_monotonic")
        self.markers = [e["marker"]["monotonic"] - first for e in result["events"]] if first is not None else []
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#151d2c"))
        left, top, width, height = 40, 36, self.width() - 58, self.height() - 63
        for value in (0, 50, 100):
            y = top + height * (1 - value / 100)
            p.setPen(QColor("#2a3549"))
            p.drawLine(QPointF(left, y), QPointF(left + width, y))
            p.setPen(QColor("#91a0bb"))
            p.drawText(7, int(y + 4), str(value))
        for index, (key, label, color) in enumerate(self.series):
            p.setPen(QColor(color))
            p.drawText(left + index * max(90, width // 6), 22, label)
            path, connected = QPainterPath(), False
            for row in self.points:
                value = row.get(key)
                if value is None:
                    connected = False
                    continue
                point = QPointF(left + width * row["t"] / self.duration,
                                top + height * (1 - min(100, max(0, value)) / 100))
                if connected:
                    path.lineTo(point)
                else:
                    path.moveTo(point)
                connected = True
            p.setPen(QPen(QColor(color), 1.8))
            p.drawPath(path)
        p.setPen(QPen(QColor("#f68ea3"), 1, Qt.DashLine))
        for seconds in self.markers:
            if 0 <= seconds <= self.duration:
                x = left + width * seconds / self.duration
                p.drawLine(QPointF(x, top), QPointF(x, top + height))
        p.setPen(QColor("#91a0bb"))
        p.drawText(left, self.height() - 7, "0 s")
        p.drawText(max(left, self.width() - 110), self.height() - 7, f"{self.duration:.1f} s")
        if not self.points:
            p.drawText(self.rect(), Qt.AlignCenter, "Grave ou abra uma sessão para visualizar o histórico")

    def mouseMoveEvent(self, event):
        if self.points:
            seconds = max(0, min(1, (event.position().x() - 40) / max(1, self.width() - 58))) * self.duration
            row = min(self.points, key=lambda r: abs(r["t"] - seconds))
            text = f"{row['t']:.2f} s\n" + "\n".join(f"{label}: {fmt(row.get(key), '%')}" for key, label, _ in self.series)
            QToolTip.showText(event.globalPosition().toPoint(), text, self)


class AnalysisPanel(QWidget):
    ready = Signal(int, object, str)
    failed = Signal(int, str)
    cancelled = Signal(int)

    def __init__(self):
        super().__init__()
        self.result = None
        self._generation = 0
        self._jobs = []
        self._cancel = threading.Event()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Análise de performance")
        title.setObjectName("title")
        title_box.addWidget(title)
        subtitle = QLabel("Recursos, processos e picos da sua captura em um só lugar.")
        subtitle.setObjectName("muted")
        title_box.addWidget(subtitle)
        heading.addLayout(title_box, 1)
        self.import_button = QPushButton("Abrir captura…")
        self.import_button.clicked.connect(self.choose_file)
        self.folder_button = QPushButton("Abrir pasta…")
        self.folder_button.clicked.connect(self.choose_folder)
        self.export_button = QPushButton("Exportar análise…")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export)
        for button in (self.import_button, self.folder_button, self.export_button):
            heading.addWidget(button)
        layout.addLayout(heading)
        status_row = QHBoxLayout()
        self.status = QLabel("Encerre uma gravação para analisá-la automaticamente ou abra uma sessão anterior.")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        status_row.addWidget(self.status, 1)
        self.cancel_button = QPushButton("Cancelar leitura")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.hide()
        status_row.addWidget(self.cancel_button)
        layout.addLayout(status_row)
        self.cards = []
        cards = QHBoxLayout()
        for name in ("Maior utilização média", "Maior pico observado", "Líder de CPU", "Captura"):
            card = QLabel(f"{name}\n—")
            card.setObjectName("analysisCard")
            card.setWordWrap(True)
            card.setMinimumHeight(82)
            cards.addWidget(card, 1)
            self.cards.append(card)
        layout.addLayout(cards)
        self.chart = SessionChart()
        layout.addWidget(self.chart)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.explanation = QPlainTextEdit()
        self.explanation.setReadOnly(True)
        self.tabs.addTab(self.explanation, "Entenda o resultado")
        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        self.resource_table = table(["Recurso", "Média", "Pico", "Horário do pico", "Carga alta¹", "Processo observado no pico²"])
        overview_layout.addWidget(self.resource_table)
        self.insight = QLabel("¹ Leituras acima do critério / leituras válidas. ² Observação contemporânea, sem atribuição de causa.")
        self.insight.setWordWrap(True)
        self.insight.setObjectName("muted")
        overview_layout.addWidget(self.insight)
        self.tabs.addTab(overview, "Visão geral")
        processes = QWidget()
        process_layout = QVBoxLayout(processes)
        filters = QHBoxLayout()
        self.metric = QComboBox()
        for name, field in (("CPU (%)", "cpu_percent"), ("RAM (MiB)", "rss_mb"),
                            ("Leitura + escrita (MiB/s)", "io_total_mbs"), ("GPU / engine (%)", "gpu_percent")):
            self.metric.addItem(name, field)
        self.statistic = QComboBox()
        self.statistic.addItem("Ordenar por pico", "peak")
        self.statistic.addItem("Ordenar por média observada", "mean")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrar por nome ou PID…")
        for widget in (self.metric, self.statistic, self.search):
            filters.addWidget(widget)
        self.metric.currentIndexChanged.connect(self.show_processes)
        self.statistic.currentIndexChanged.connect(self.show_processes)
        self.search.textChanged.connect(self.show_processes)
        process_layout.addLayout(filters)
        self.process_table = table(["#", "Processo", "PID", "Média observada", "Pico", "Horário do pico", "Leituras"])
        self.process_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.process_table.horizontalHeader().setStretchLastSection(False)
        process_layout.addWidget(self.process_table)
        self.process_note = QLabel()
        self.process_note.setWordWrap(True)
        self.process_note.setObjectName("muted")
        process_layout.addWidget(self.process_note)
        self.tabs.addTab(processes, "Processos")
        events = QWidget()
        event_layout = QVBoxLayout(events)
        self.event_picker = QComboBox()
        self.event_picker.currentIndexChanged.connect(self.show_event)
        event_layout.addWidget(self.event_picker)
        self.event_note = QLabel("Sem marcações. O resumo da sessão inteira continua disponível.")
        self.event_note.setWordWrap(True)
        event_layout.addWidget(self.event_note)
        self.event_table = table(["Recurso", "Pico antes (−5 s)", "Pico depois (+5 s)", "Carga alta na janela", "Carga alta fora das marcações", "Processo observado na janela"])
        event_layout.addWidget(self.event_table)
        self.tabs.addTab(events, "Marcações")
        triage = QWidget()
        triage_layout = QVBoxLayout(triage)
        self.triage_text = QPlainTextEdit()
        self.triage_text.setReadOnly(True)
        triage_layout.addWidget(self.triage_text, 1)
        self.pressure_table = table(["Recurso", "P95", "Tempo alto observado", "Maior sequência", "Cobertura observada"])
        triage_layout.addWidget(self.pressure_table, 1)
        self.tabs.addTab(triage, "Triagem")
        self.sensor_table = table(["Dispositivo / métrica", "Unidade", "Mínimo", "Média", "Máximo", "Leituras"])
        self.tabs.addTab(self.sensor_table, "Sensores e discos")
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.tabs.addTab(self.report, "Relatório e limites")
        self.ai = AISummaryPanel()
        self.tabs.addTab(self.ai, "IA opcional")
        footer = QLabel("Médias das leituras disponíveis • CPU por processo normalizada pelo total de CPUs lógicas • N/D = dado indisponível")
        footer.setWordWrap(True)
        footer.setObjectName("muted")
        layout.addWidget(footer)
        self.ready.connect(self.accept_result)
        self.failed.connect(self.accept_error)
        self.cancelled.connect(self.accept_cancelled)

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Abrir captura SysPulse", "",
            "Captura SysPulse (*.zip *.jsonl *.json);;Todos os arquivos (*)")
        if path:
            self.load(path)

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Pasta que contém amostras.jsonl")
        if path:
            self.load(path)

    def set_busy(self, value):
        self.import_button.setEnabled(not value)
        self.folder_button.setEnabled(not value)
        self.export_button.setEnabled(not value and self.result is not None)
        self.cancel_button.setVisible(value)

    def load(self, source, auto_save=False):
        self._cancel.set()
        self._cancel = cancel = threading.Event()
        self._generation += 1
        generation = self._generation
        self.set_busy(True)
        self.status.setText(f"Analisando {Path(source).name}… A interface continua disponível.")

        def run():
            try:
                result = analyze_session(source, cancel.is_set)
                if cancel.is_set():
                    raise AnalysisCancelled()
                save_warning = ""
                if auto_save:
                    try:
                        save_report(result, source)
                    except OSError as error:
                        save_warning = f"Análise disponível na tela; não foi possível salvar o relatório: {error}"
                if cancel.is_set():
                    raise AnalysisCancelled()
                self.ready.emit(generation, result, save_warning)
            except AnalysisCancelled:
                self.cancelled.emit(generation)
            except Exception as error:
                if not cancel.is_set():
                    self.failed.emit(generation, str(error))

        thread = threading.Thread(target=run, name="sys-pulse-analysis", daemon=True)
        self._jobs = [job for job in self._jobs if job.is_alive()]
        self._jobs.append(thread)
        thread.start()

    def cancel(self):
        self._cancel.set()
        self.status.setText("Cancelando leitura…")

    def accept_cancelled(self, generation):
        if generation == self._generation:
            self.set_busy(False)
            self.status.setText("Leitura cancelada. A análise anterior foi preservada." if self.result else "Leitura cancelada.")

    def accept_error(self, generation, message):
        if generation == self._generation:
            self.set_busy(False)
            self.status.setText(f"Não foi possível analisar: {message}")

    def accept_result(self, generation, result, save_warning=""):
        if generation != self._generation:
            return
        self.result = result
        self.set_busy(False)
        summary = result["summary"]
        name = Path(result["source"]).name
        demo = "DADOS SIMULADOS · " if result["metadata"].get("demo") else ""
        quality = f" · {len(result['warnings'])} aviso(s) no relatório" if result["warnings"] else ""
        self.status.setText(save_warning or f"{demo}{name} · {display_time(summary['start'])} a {display_time(summary['end'])}{quality}")
        dominant = summary["dominant"]
        self.cards[0].setText("Maior utilização média\n" + (f"{dominant['name']} · {fmt(dominant['mean'], '%')}" if dominant else "N/D"))
        peaks = [r for r in summary["resources"] if r["peak"] is not None]
        peak = max(peaks, key=lambda r: r["peak"]) if peaks else None
        self.cards[1].setText("Maior pico observado\n" + (f"{peak['name']} · {fmt(peak['peak'], '%')}" if peak else "N/D"))
        ranked = ranked_processes(summary)
        leader = ranked[0] if ranked and ranked[0]["metrics"]["cpu_percent"]["peak"] > 0 else None
        self.cards[2].setText("Líder de CPU por pico\n" + (f"{leader['name']} · {fmt(leader['metrics']['cpu_percent']['peak'], '%')}" if leader else "N/D"))
        self.cards[3].setText(f"{summary['duration_s']:.1f} s de captura\n{summary['samples']} amostras · {len(result['events'])} marcações")
        self.chart.set_result(result)
        rows = []
        for r in summary["resources"]:
            p = r.get("process")
            process = f"{p['name']} · PID {p['pid']}" if p else "N/D"
            if r["key"] == "disk" and p:
                process += " (I/O)"
            rows.append([r["name"], fmt(r["mean"], "%"), fmt(r["peak"], "%"), display_time(r["peak_at"]),
                         f"{r['high_count']}/{r['count']} ≥{r['threshold']}%", process])
        fill(self.resource_table, rows)
        for i, r in enumerate(summary["resources"]):
            tooltip = f"Dispositivo no pico: {r.get('device') or 'N/D'}\nIdade dos processos: {fmt(r.get('process_age_ms'), ' ms')}"
            if r["key"] == "core":
                tooltip += "\nO processo de maior CPU total não é necessariamente o que ocupou este núcleo."
            if r["key"] == "disk":
                tooltip += "\nO I/O do processo não está vinculado a este disco físico."
            self.resource_table.item(i, 5).setToolTip(tooltip)
        pressure = [r["name"] for r in summary["resources"] if r["high_count"]]
        evidence = ("Carga alta registrada: " + ", ".join(pressure) + ". Investigue os horários e marcações." if pressure else
                    "Sem leituras acima dos critérios disponíveis. Isso não descarta pausas curtas ou problemas de apresentação dos quadros.")
        evidence = result.get("explanation", {}).get("summary", evidence)
        self.insight.setText(evidence + "\n¹ Leituras acima do critério / leituras válidas. ² Processo observado perto do pico; não comprova causa.")
        self.show_processes()
        self.event_picker.blockSignals(True)
        self.event_picker.clear()
        for event in result["events"]:
            m = event["marker"]
            self.event_picker.addItem(f"#{m['id']} · {display_time(m['timestamp'])} · {m['note']}")
        self.event_picker.blockSignals(False)
        self.show_event()
        assessment = summary.get("assessment", {})
        findings = assessment.get("findings", [])
        lines = []
        for finding in findings:
            lines += [finding["title"], finding["evidence"], finding["action"], ""]
        if not findings:
            lines.append("Sem alerta nos critérios disponíveis. Isso não descarta problemas não capturados.")
        lines += [assessment.get("method", "")]
        self.triage_text.setPlainText("\n".join(lines))
        fill(self.pressure_table, [[r["name"], fmt(r["p95"], "%"),
                                   fmt(r["high_seconds"], " s") if r["count"] else "N/D",
                                   fmt(r["longest_high_s"], " s") if r["count"] else "N/D",
                                   fmt(r["covered_seconds"], " s") if r["count"] else "N/D"]
                                  for r in assessment.get("resources", [])])
        fill(self.sensor_table, [[r["name"], r["unit"], fmt(r["min"]), fmt(r["mean"]), fmt(r["max"]), r["count"]]
                                for r in assessment.get("telemetry", [])])
        self.report.setPlainText(report_text(result))
        self.explanation.setPlainText(readable_report(result, "ENTENDA O RESULTADO"))
        self.ai.set_result(result)

    def show_processes(self, *_):
        if not self.result:
            return
        field, statistic = self.metric.currentData(), self.statistic.currentData()
        query = self.search.text().casefold().strip()
        rows = ranked_processes(self.result["summary"], field, statistic)
        rows = [p for p in rows if query in p["name"].casefold() or query in str(p["pid"])]
        values = []
        for index, p in enumerate(rows, 1):
            stat = p["metrics"][field]
            values.append([index, p["name"], p["pid"], fmt(stat["mean"], digits=2), fmt(stat["peak"], digits=2),
                           display_time(stat["peak_at"]), stat["count"]])
        fill(self.process_table, values)
        note = "Médias das leituras distintas em que o processo foi registrado. Ausências não contam como zero."
        if field.startswith("io_"):
            note += " I/O não identifica o disco físico e pode incluir dispositivos/rede no Windows."
        if field == "gpu_percent":
            note += " Engine mais ocupado por PID; não somar engines nem comparar diretamente à GPU global."
        if not rows:
            note = "Nenhuma leitura disponível para este recurso/filtro. Sessões antigas não têm I/O ou GPU por processo."
        self.process_note.setText(note)

    def show_event(self, *_):
        if not self.result or self.event_picker.currentIndex() < 0:
            fill(self.event_table, [])
            self.event_note.setText("Sem marcações. O resumo da sessão inteira continua disponível.")
            return
        event = self.result["events"][self.event_picker.currentIndex()]
        coverage = event["coverage"]
        self.event_note.setText(f"Janela em torno do atalho · cobertura {fmt(coverage[0], ' s')} a +{fmt(coverage[1], ' s')} · "
                               f"{event['analysis']['samples']} amostras. O atalho registra sua percepção, não o início exato da pausa.")
        windows = self.result.get("symptoms", {}).get("windows", [])
        index = self.event_picker.currentIndex()
        if index < len(windows):
            window = windows[index]
            if window["partial"]:
                self.event_note.setText(self.event_note.text() + " Cobertura parcial.")
            if window["gaps"]:
                self.event_note.setText(self.event_note.text() + f" {window['gaps']} lacuna(s) de coleta nesta janela.")
        baseline = {r["key"]: r for r in self.result.get("symptoms", {}).get("resources", [])}
        rows = []
        for pre, post, r in zip(event["before"], event["after"], event["analysis"]["resources"]):
            p = r.get("process")
            outside = baseline.get(r["key"], {}).get("outside_high_percent")
            high = f"{r['high_count']}/{r['count']} ≥{r['threshold']}%" if r["count"] else "N/D"
            rows.append([r["name"], fmt(pre["peak"], "%"), fmt(post["peak"], "%"), high, fmt(outside, "%"),
                         f"{p['name']} · PID {p['pid']}" if p else "N/D"])
        fill(self.event_table, rows)

    def export(self):
        if not self.result:
            return
        folder = QFileDialog.getExistingDirectory(self, "Pasta para exportar o relatório")
        if folder:
            destination = Path(folder) / datetime.now().strftime("analise-%Y%m%d-%H%M%S-%f")
            try:
                save_report(self.result, destination)
                self.status.setText(f"Relatórios TXT e JSON exportados em {destination}")
            except OSError as error:
                QMessageBox.warning(self, "Falha ao exportar", str(error))

    def shutdown(self):
        self.ai.shutdown()
        self._generation += 1
        self._cancel.set()
        for thread in self._jobs:
            thread.join(timeout=2)
