import json
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
                              QComboBox, QFileDialog, QTabWidget, QPlainTextEdit)

from modules.advanced_capture import CaptureController, TERMINAL, find_tools, write_json, read_json
from modules.advanced_analysis import analyze_etl, AdvancedCancelled, readable_report, read_text
from modules.analysis import analyze_session, fmt
from modules.analysis_view import table, fill
from modules.ai_summary import AISummaryPanel
from modules.diagnostics import SessionRecorder


class AdvancedPanel(QWidget):
    recorder_status = Signal(dict)
    capture_state = Signal(dict)
    ready = Signal(int, dict, str)
    failed = Signal(int, str)

    def __init__(self, demo=False, ai_config=None):
        super().__init__()
        self.demo = demo
        self.ai_config = ai_config
        self.session_options = {}
        self.controller = CaptureController()
        self.inventory = None
        self.result = None
        self.native_requested = self.handled = False
        self.native_finished = self.native_stop_requested = False
        self.native_path = None
        self.pending_etl = None
        self.native_error = None
        self._generation = 0
        self._busy = False
        self._closed = False
        self._cancel = threading.Event()
        self._last_marker = 0
        self.recorder = SessionRecorder(self.recorder_status.emit)
        self.recorder_status.connect(self.on_recorder_status)
        layout = QVBoxLayout(self)
        title = QLabel("Diagnóstico avançado")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel("1. Inicie e autorize no Windows.  2. Reproduza o problema e marque o sintoma.  3. Leia a análise.\n"
                       "A análise explica as evidências e os próximos testes. Nenhuma peça é condenada por um pico isolado.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        options = QHBoxLayout()
        self.duration = QComboBox()
        for seconds in (30, 60, 120, 180):
            self.duration.addItem(f"{seconds} segundos", seconds)
        self.duration.setCurrentIndex(1)
        self.start_button = QPushButton("Iniciar captura · administrador")
        self.start_button.clicked.connect(self.start_capture)
        self.stop_button = QPushButton("Encerrar e analisar")
        self.stop_button.clicked.connect(self.stop_capture)
        self.mark_button = QPushButton("Marcar sintoma · Ctrl+Alt+F8")
        self.mark_button.clicked.connect(self.mark)
        for widget in (self.duration, self.start_button, self.stop_button, self.mark_button):
            options.addWidget(widget)
        layout.addLayout(options)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Descreva o sintoma: áudio cortando, congelamento, lentidão…")
        layout.addWidget(self.note)
        files = QHBoxLayout()
        self.open_button = QPushButton("Abrir ETL…")
        self.open_button.clicked.connect(self.choose_etl)
        self.export_button = QPushButton("Exportar explicação…")
        self.export_button.clicked.connect(self.export)
        self.folder_button = QPushButton("Pasta da captura")
        self.folder_button.clicked.connect(self.open_folder)
        self.cancel_button = QPushButton("Cancelar análise")
        self.cancel_button.clicked.connect(self._cancel_analysis)
        self.tools_button = QPushButton("Ferramentas Microsoft")
        self.tools_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://learn.microsoft.com/windows-hardware/test/wpt/")))
        for widget in (self.open_button, self.export_button, self.folder_button, self.cancel_button, self.tools_button):
            files.addWidget(widget)
        layout.addLayout(files)
        self.tools = QLabel()
        self.tools.setWordWrap(True)
        self.tools.setObjectName("muted")
        layout.addWidget(self.tools)
        self.status = QLabel("Pronto. A permissão de administrador é solicitada somente ao iniciar uma captura.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.explanation = QPlainTextEdit("Capture ou abra um ETL para receber uma explicação baseada nos dados.")
        self.explanation.setReadOnly(True)
        self.tabs.addTab(self.explanation, "Entenda o resultado")
        self.drivers = table(["Tipo", "Módulo", "Ocorrências", "Total (ms)", "Média (µs)", "Maior faixa (µs)"])
        self.tabs.addTab(self.drivers, "DPC / ISR")
        self.cpu_table = table(["Processo", "PID", "Execução acumulada (ms)"])
        self.tabs.addTab(self.cpu_table, "CPU")
        self.thread_table = table(["Processo", "PID", "Thread", "Execução acumulada (ms)"])
        self.tabs.addTab(self.thread_table, "Threads")
        self.disk_table = table(["Arquivo", "Operações", "Leitura (MiB)", "Escrita (MiB)"])
        self.tabs.addTab(self.disk_table, "Disco")
        self.fault_table = table(["Processo", "PID", "Hard faults", "Dados (MiB)"])
        self.tabs.addTab(self.fault_table, "Páginas")
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.tabs.addTab(self.raw, "Dados e limites")
        self.ai = AISummaryPanel(ai_config)
        self.tabs.addTab(self.ai, "IA opcional")
        self.ready.connect(self.accept_result)
        self.failed.connect(self.accept_error)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.update_buttons()
        if demo:
            self.status.setText("DADOS SIMULADOS · captura desativada nesta demonstração")

    def update_buttons(self):
        state = self.controller.status().get("state")
        active = self.controller.path is not None and state not in TERMINAL
        finishing = self.native_requested and not self.native_finished
        tools = find_tools()
        other_busy = self.ai_config and (self.ai_config.activity.inference or self.ai_config.activity.maintenance or self.ai_config.activity.capture not in (None, "advanced"))
        self.start_button.setEnabled(not self.demo and not active and not finishing and not self._busy and not other_busy)
        self.duration.setEnabled(not active and not self._busy)
        self.open_button.setEnabled(not active and not finishing and not self._busy and not other_busy)
        self.stop_button.setEnabled(active and state not in ("stopping",))
        self.mark_button.setEnabled(state == "recording")
        self.cancel_button.setVisible(self._busy)
        self.export_button.setEnabled(self.result is not None and not self._busy)
        self.folder_button.setEnabled(self.controller.path is not None)
        self.tools.setText("WPR: " + ("disponível" if tools["wpr"] else "indisponível") +
                           " · Análise ETL (Xperf): " + ("disponível" if tools["xperf"] else "instale o Windows Performance Toolkit") +
                           " · Duração DPC/ISR não é latência completa do computador.")

    def start_capture(self, folder=None, seconds=None, mode="detail"):
        if self.demo:
            return
        if not isinstance(folder, (str, Path)):
            folder = QFileDialog.getExistingDirectory(self, "Pasta para guardar a captura avançada")
        if not folder:
            return
        try:
            if self.ai_config and self.ai_config.activity.capture != "advanced":
                self.ai_config.activity.begin_capture("advanced")
            self.controller.start(folder, seconds or self.duration.currentData(), mode)
            self.native_requested = self.handled = False
            self.native_finished = self.native_stop_requested = False
            self.native_path = self.pending_etl = self.native_error = None
            self.status.setText("Solicitando permissão de administrador ao Windows…")
            self.update_buttons()
        except (OSError, ValueError, RuntimeError) as error:
            if self.ai_config:
                self.ai_config.activity.end_capture("advanced")
            self.status.setText(str(error))
            self.capture_state.emit({"state": "failed", "message": str(error)})

    def stop_capture(self):
        try:
            self.controller.stop()
            self.status.setText("Encerramento solicitado. Aguarde a gravação do ETL.")
        except OSError as error:
            self.status.setText(f"Não foi possível solicitar o encerramento: {error}")

    def mark(self):
        at = time.monotonic()
        if at - self._last_marker < .5:
            return
        try:
            if self.controller.mark(self.note.text()):
                self._last_marker = at
                self.status.setText("Marcação solicitada; o horário recebido pelo WPR pode ter atraso.")
                if self.recorder.active.is_set():
                    self.recorder.command("mark", {"timestamp": datetime.now().astimezone().isoformat(),
                                                  "monotonic": at, "note": self.note.text()[:500]})
        except OSError as error:
            self.status.setText(f"Não foi possível marcar: {error}")

    def submit(self, sample):
        self.recorder.submit(sample)

    def on_recorder_status(self, status):
        if self._closed:
            return
        if status.get("started"):
            self.native_path = Path(status["path"])
            if self.inventory:
                self.recorder.command("inventory", self.inventory)
            try:
                write_json(self.controller.path / "context.json", {"resource_path": str(self.native_path.relative_to(self.controller.path))})
            except (OSError, ValueError) as error:
                self.status.setText(f"Coleta ativa, mas não foi possível salvar o vínculo com os recursos: {error}")
        if status.get("error"):
            self.native_error = status["message"]
        if status.get("completed") or status.get("error"):
            self.native_finished = True
            if self.ai_config and self.controller.status().get("state") in TERMINAL:
                self.ai_config.activity.end_capture("advanced")
        if (status.get("completed") or status.get("error")) and self.pending_etl:
            source, self.pending_etl = self.pending_etl, None
            self.load(source, self.controller.path / "analise", self.native_path)
        self.update_buttons()

    def poll(self):
        if not self.controller.path or self.handled:
            return
        state = self.controller.status()
        self.capture_state.emit(state)
        self.status.setText(state.get("message", ""))
        if state.get("state") == "recording" and not self.native_requested:
            self.native_requested = self.recorder.command("start", {**self.session_options, "folder": str(self.controller.path / "recursos"),
                                                                   "inventory": self.inventory})
        if state.get("state") in TERMINAL | {"stopping"}:
            if self.native_requested and not self.native_finished and not self.native_stop_requested:
                self.native_stop_requested = self.recorder.command("stop")
                if not self.native_stop_requested:
                    self.status.setText("ETL em finalização; aguardando o gravador de recursos.")
                    self.update_buttons()
                    return
        if state.get("state") in TERMINAL:
            self.handled = True
            if self.ai_config and (not self.native_requested or self.native_finished):
                self.ai_config.activity.end_capture("advanced")
            if state["state"] == "completed":
                source = self.controller.path / "captura.etl"
                if self.native_requested and not self.native_finished:
                    self.pending_etl = source
                else:
                    self.load(source, self.controller.path / "analise", self.native_path)
            if state.get("recovery_command"):
                self.raw.setPlainText(state["message"] + "\n\nO encerramento automático falhou. Abra um terminal como administrador e encerre apenas esta sessão:\n" + state["recovery_command"])
        self.update_buttons()

    def choose_etl(self):
        source, _ = QFileDialog.getOpenFileName(self, "Abrir captura ETL", "", "Captura do Windows (*.etl)")
        if not source:
            return
        folder = QFileDialog.getExistingDirectory(self, "Pasta para salvar a análise")
        if folder:
            destination = Path(folder) / datetime.now().strftime("analise-etl-%Y%m%d-%H%M%S-%f")
            self.load(source, destination)

    def load(self, source, destination, native_path=None):
        self._cancel.set()
        self._cancel = cancel = threading.Event()
        self._generation += 1
        generation = self._generation
        self._busy = True
        self.status.setText("Analisando a captura… isso pode levar alguns minutos. A interface continua disponível.")
        self.update_buttons()

        if native_path is None:
            try:
                root = Path(source).resolve().parent
                context = read_json(root / "context.json")
                candidate = (root / context["resource_path"]).resolve()
                if root in candidate.parents and any((candidate / name).is_file() for name in ("amostras.jsonl", "amostras.jsonl.gz")):
                    native_path = candidate
            except (OSError, ValueError, KeyError, TypeError):
                pass

        def run():
            native = None
            native_warning = None
            try:
                if native_path:
                    try:
                        native = analyze_session(native_path, cancel.is_set)
                    except Exception as error:
                        native_warning = f"Análise de recursos indisponível: {error}"
                if cancel.is_set():
                    raise AdvancedCancelled()
                result = analyze_etl(source, destination, cancel.is_set, native, deep=True)
                if native_warning:
                    result["explanation"]["limitations"].append(native_warning)
                    write_json(Path(destination) / "analise-avancada.json", result)
                    (Path(destination) / "analise-avancada.txt").write_text(readable_report(result), encoding="utf-8")
                if self._closed:
                    return
                if not cancel.is_set():
                    self.ready.emit(generation, result, str(destination))
                else:
                    self.failed.emit(generation, "Análise cancelada. O ETL foi preservado.")
            except AdvancedCancelled:
                if not self._closed:
                    self.failed.emit(generation, "Análise cancelada. O ETL foi preservado.")
            except Exception as error:
                if not self._closed:
                    self.failed.emit(generation, str(error))

        threading.Thread(target=run, name="sys-pulse-etl-analysis", daemon=True).start()

    def _cancel_analysis(self):
        self._cancel.set()
        self.status.setText("Cancelando a análise; a captura original será preservada.")

    def accept_result(self, generation, result, destination=""):
        if self._closed or generation != self._generation:
            return
        self.result, self._busy = result, False
        self.explanation.setPlainText(readable_report(result))
        rows = []
        for row in result["drivers"]:
            low, high = row.get("max_bucket_low_us"), row.get("max_bucket_high_us")
            bucket = f"> {low:g} até {high:g}" if high is not None else "N/D"
            rows.append([row["kind"], row["module"], row.get("count") if row.get("count") is not None else "N/D",
                         fmt(row["total_us"] / 1000 if row["total_us"] is not None else None, digits=3), fmt(row.get("mean_us"), digits=3), bucket])
        fill(self.drivers, rows)
        fill(self.cpu_table, [[r["name"], r["pid"], fmt(r["cpu_us"] / 1000)] for r in result.get("cpu", {}).get("processes", [])[:100]])
        fill(self.thread_table, [[r["name"], r["pid"], r["tid"], fmt(r["cpu_us"] / 1000)] for r in result.get("cpu", {}).get("threads", [])[:200]])
        fill(self.disk_table, [[r["file"], r["count"], fmt(r["read_bytes"] / 1024 ** 2), fmt(r["write_bytes"] / 1024 ** 2)]
                              for r in result.get("disk", {}).get("files", [])[:100]])
        fill(self.fault_table, [[r["name"], r["pid"], r["count"], fmt(r["bytes"] / 1024 ** 2)] for r in result.get("faults", {}).get("processes", [])[:100]])
        text = [result["method"], "", *result["explanation"]["limitations"]]
        if destination:
            for name in ("dpc-isr.txt", "trace-stats.txt", "cpu-threads.txt", "disco.txt", "paginas.txt"):
                try:
                    text += ["", name, read_text(Path(destination) / name)[:200000]]
                except (OSError, ValueError):
                    pass
        self.raw.setPlainText("\n".join(text))
        self.ai.set_result({**result, "ai_output": destination} if destination else result)
        self.tabs.setCurrentIndex(0)
        self.status.setText("DADOS SIMULADOS — exemplo de explicação" if result.get("demo") else f"Análise concluída e salva em {destination}.")
        self.update_buttons()

    def accept_error(self, generation, message):
        if not self._closed and generation == self._generation:
            self._busy = False
            self.status.setText(message + (" A explicação anterior permanece na tela." if self.result else ""))
            self.update_buttons()

    def export(self):
        if not self.result:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Salvar explicação", "explicacao-avancada.txt", "Texto (*.txt)")
        if path:
            try:
                Path(path).write_text(readable_report(self.result), encoding="utf-8")
                self.status.setText(f"Explicação salva: {path}")
            except OSError as error:
                self.status.setText(str(error))

    def open_folder(self):
        if self.controller.path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.controller.path)))

    def shutdown(self):
        self._closed = True
        self._cancel.set()
        self.timer.stop()
        try:
            self.controller.close()
        except OSError:
            pass
        self.ai.shutdown()
        self.recorder.shutdown()
