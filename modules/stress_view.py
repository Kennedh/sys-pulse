import os
import time
from datetime import datetime
from pathlib import Path

import psutil
from PySide6.QtCore import Signal, QTimer, QStandardPaths
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
                              QComboBox, QSpinBox, QLineEdit, QFileDialog, QMessageBox, QPlainTextEdit, QCheckBox)

from modules.diagnostics import SessionRecorder
from modules.stress import StressController, validate_options, write_json
from modules.gpu_results import gpu_result_text


class StressPanel(QWidget):
    recorded = Signal(dict)
    sampled = Signal(dict)
    ready = Signal(str)

    def __init__(self, activity, demo=False):
        super().__init__()
        self.activity, self.demo = activity, demo
        self.inventory = None
        self.controller = StressController()
        self.recorder = SessionRecorder(self.recorded.emit)
        self.phase = None
        self.path = None
        self.last_sample = None
        self.last_sample_at = None
        self.reason = ""
        self.options = None
        self.thermal_coverage = {"cpu": 0, "gpu": 0}
        self._closed = False
        self.gpu_status = {}
        layout = QVBoxLayout(self)
        title = QLabel("Teste a resposta do sistema sob carga")
        title.setObjectName("title")
        layout.addWidget(title)
        intro = QLabel("Escolha um componente. A gravação inclui 5 s antes, toda a carga e 5 s de recuperação. "
                       "A análise compara os períodos; a IA permanece desligada durante o teste. "
                       "A carga aumenta consumo e temperatura. Concluir não certifica integridade física.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = self.form = QFormLayout()
        self.kind = QComboBox()
        for label, value in (("CPU · cálculo com resultado conhecido", "cpu"),
                             ("GPU · renderização 3D", "gpu"), ("RAM · escrita e leitura verificadas", "memory")):
            self.kind.addItem(label, value)
        self.gpu_test = QComboBox()
        for label, value in (("Cena 3D", "scene"), ("VRAM · escrita e leitura", "vram"), ("Cena 3D + VRAM", "combined")):
            self.gpu_test.addItem(label, value)
        self.resolution = QComboBox()
        self.resolution.setEditable(True)
        self.resolution.setInsertPolicy(QComboBox.NoInsert)
        for size, caption in (("1280x720", "HD"), ("1920x1080", "Full HD"), ("2560x1440", "QHD"), ("3840x2160", "4K")):
            self.resolution.addItem(size + " · " + caption, size)
        self.resolution.lineEdit().setPlaceholderText("Ex.: 3440x1440")
        self.artifacts = QCheckBox("Verificar imagens e padrão gráfico conhecido")
        self.artifacts.setChecked(True)
        self.vram_mb = QSpinBox()
        self.vram_mb.setRange(16, 16384)
        self.vram_mb.setSingleStep(64)
        self.vram_mb.setValue(512)
        self.vram_mb.setSuffix(" MiB")
        self.vram_auto = QCheckBox("Usar a disponível com reserva · até 16 GiB")
        self.gpu_profile = QComboBox()
        for label, value in (("Geometria · shader leve", "geometry"), ("Equilibrado · cena e iluminação", "balanced"),
                             ("Shader intenso · mais cálculo por pixel", "shader")):
            self.gpu_profile.addItem(label, value)
        self.gpu_profile.setCurrentIndex(1)
        self.duration = QComboBox()
        for minutes in (5, 15, 30, 60):
            self.duration.addItem(f"{minutes} minutos", minutes * 60)
        self.intensity = QComboBox()
        for value in (25, 50, 75, 100):
            self.intensity.addItem(f"{value}% · orçamento de carga", value)
        self.intensity.setCurrentIndex(1)
        self.workers = QSpinBox()
        self.workers.setRange(1, min(64, os.cpu_count() or 1))
        self.workers.setValue(min(64, os.cpu_count() or 1))
        self.memory = QSpinBox()
        self.memory.setRange(16, 4096)
        self.memory.setValue(256)
        self.memory.setSuffix(" MiB")
        self.cpu_limit, self.gpu_limit = QSpinBox(), QSpinBox()
        for field, value in ((self.cpu_limit, 90), (self.gpu_limit, 85)):
            field.setRange(50, 110)
            field.setValue(value)
            field.setSuffix(" °C")
        for caption, field in (("Componente", self.kind), ("Duração da carga", self.duration),
                               ("Intensidade solicitada", self.intensity), ("Teste GPU", self.gpu_test),
                               ("Resolução de renderização", self.resolution), ("Perfil GPU", self.gpu_profile),
                               ("Verificação gráfica", self.artifacts), ("Memória da GPU a testar", self.vram_mb),
                               ("Orçamento VRAM", self.vram_auto), ("Processos CPU", self.workers),
                               ("RAM a verificar (até 25% da disponível)", self.memory),
                               ("Parar na temperatura CPU", self.cpu_limit), ("Parar na temperatura GPU", self.gpu_limit)):
            form.addRow(caption, field)
        layout.addLayout(form)
        note = QLabel("Os percentuais controlam o trabalho solicitado, não garantem uso medido exato. "
                      "GPU requer OpenGL 3.2; a janela é uma prévia da resolução fixa escolhida. "
                      "A verificação cobre as imagens e os buffers acessíveis pelo driver; não toda a VRAM física. "
                      "Limites térmicos são precauções configuráveis e dependem de sensores atualizados.")
        note.setWordWrap(True)
        layout.addWidget(note)
        folders = QHBoxLayout()
        documents = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home())
        self.folder = QLineEdit("Demonstração — arquivos não são gravados" if demo else str(Path(documents) / "SysPulse/diagnosticos"))
        self.choose = QPushButton("Escolher pasta")
        self.choose.clicked.connect(self.choose_folder)
        folders.addWidget(self.folder, 1)
        folders.addWidget(self.choose)
        layout.addLayout(folders)
        buttons = QHBoxLayout()
        self.start = QPushButton("Iniciar teste e gravação")
        self.start.setObjectName("primary")
        self.stop = QPushButton("Parar teste")
        self.start.clicked.connect(self.request_start)
        self.stop.clicked.connect(self.request_stop)
        buttons.addWidget(self.start)
        self.mark_button = QPushButton("Marcar sintoma")
        self.mark_button.clicked.connect(lambda: self.mark())
        buttons.addWidget(self.mark_button)
        buttons.addWidget(self.stop)
        layout.addLayout(buttons)
        self.status = QLabel("Aguardando o inventário inicial." if not demo else "Demonstração · carga desativada.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.live = QPlainTextEdit("Temperaturas e cobertura serão mostradas ao receber as leituras.")
        self.live.setReadOnly(True)
        layout.addWidget(self.live, 1)
        self.recorded.connect(self.on_recorded)
        self.sampled.connect(self.on_sample)
        self.activity.changed.connect(self.update_state)
        self.kind.currentIndexChanged.connect(self.update_state)
        self.gpu_test.currentIndexChanged.connect(self.update_state)
        self.vram_auto.toggled.connect(self.update_state)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.update_state()

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Guardar o teste", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def update_state(self):
        available = not self.activity.busy and not self.phase and not self.demo
        self.start.setEnabled(available and self.inventory is not None)
        self.mark_button.setEnabled(bool(self.phase))
        self.stop.setEnabled(bool(self.phase and self.phase != "finishing"))
        for field in (self.kind, self.duration, self.intensity, self.folder, self.choose, self.cpu_limit, self.gpu_limit):
            field.setEnabled(available)
        self.workers.setEnabled(available and self.kind.currentData() == "cpu")
        self.memory.setEnabled(available and self.kind.currentData() == "memory")
        gpu = self.kind.currentData() == "gpu"
        scene = gpu and self.gpu_test.currentData() != "vram"
        memory = gpu and self.gpu_test.currentData() in ("vram", "combined")
        fields = ((self.workers, self.kind.currentData() == "cpu"), (self.memory, self.kind.currentData() == "memory"),
                  (self.gpu_test, gpu), (self.resolution, scene), (self.gpu_profile, scene), (self.artifacts, scene),
                  (self.vram_mb, memory), (self.vram_auto, memory))
        for field, visible in fields:
            field.setVisible(visible)
            label = self.form.labelForField(field)
            if label:
                label.setVisible(visible)
            field.setEnabled(available and visible)
        self.vram_mb.setEnabled(available and memory and not self.vram_auto.isChecked())

    def request_start(self):
        if self.demo or self.activity.busy or self.inventory is None:
            return
        try:
            options = validate_options({"kind": self.kind.currentData(), "duration_s": self.duration.currentData(),
                "workers": self.workers.value(), "memory_mb": self.memory.value(), "intensity": self.intensity.currentData(),
                "resolution": (self.resolution.currentData() if self.resolution.currentText() == self.resolution.itemText(self.resolution.currentIndex())
                               else self.resolution.currentText()), "gpu_profile": self.gpu_profile.currentData(),
                "gpu_test": self.gpu_test.currentData(), "gpu_artifacts": self.artifacts.isChecked(),
                "gpu_vram_mb": 0 if self.vram_auto.isChecked() else self.vram_mb.value()})
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
            return
        if QMessageBox.question(self, "Iniciar carga controlada",
                "Iniciar o teste e gravar os recursos?\nA carga aumenta consumo e temperatura. "
                "A parada térmica depende de sensores disponíveis; sem leitura ela não pode ser verificada. "
                "Use Parar teste a qualquer momento.") != QMessageBox.Yes:
            return
        try:
            self.activity.begin_capture("stress")
            self.options, self.reason, self.phase = options, "", "starting"
            self.gpu_status = {}
            self.controller = StressController()
            self.thermal_coverage = {"cpu": 0, "gpu": 0}
            self.path = None
            if not self.recorder.command("start", {"folder": self.folder.text(), "compressed": True,
                    "csv": False, "duration_s": options["duration_s"] + 30, "inventory": self.inventory,
                    "symptom": "Teste de estresse: " + options["kind"]}):
                raise RuntimeError("Não foi possível iniciar a gravação.")
            self.status.setText("Preparando gravação e linha de base…")
        except (ValueError, RuntimeError, OSError) as error:
            self.phase = None
            self.activity.end_capture("stress")
            self.status.setText(str(error))
        self.update_state()

    def on_recorded(self, status):
        if self._closed:
            return
        if status.get("started"):
            self.path = Path(status["path"])
            self.phase, self.next_phase = "baseline", time.monotonic() + 5
            if self.reason:
                self.finish_load({"state": "stopped", "kind": self.options["kind"], "elapsed_s": 0, "errors": None})
        if status.get("completed") or status.get("error"):
            if self.phase != "finishing":
                self.controller.close()
            self.phase = None
            self.activity.end_capture("stress")
            self.status.setText(status["message"])
            if status.get("completed") and status.get("count"):
                self.ready.emit(str(self.path))
        self.update_state()

    def submit(self, sample):
        if not self._closed:
            self.recorder.submit(sample)
            if self.phase:
                self.sampled.emit(sample)

    def on_sample(self, sample):
        self.last_sample, self.last_sample_at = sample, time.monotonic()
        age = sample.get("sensor_age_ms")
        fresh = isinstance(age, (int, float)) and 0 <= age <= 4000
        cpu = sample.get("cpu_temperature") if fresh else None
        temperatures = [gpu["temperature"] for gpu in sample.get("gpus", []) if isinstance(gpu.get("temperature"), (int, float))] if fresh else []
        gpu = max(temperatures) if temperatures else None
        self.live.setPlainText(f"CPU: {sample.get('cpu_percent')}% · RAM: {sample.get('ram_percent')}%\n"
                               f"Temperatura CPU: {cpu if cpu is not None else 'N/D'} °C\n"
                               f"Temperatura GPU: {gpu if gpu is not None else 'N/D'} °C\n"
                               "Sem sensor atualizado não há verificação da parada térmica correspondente."
                               + ("\n\n" + gpu_result_text(self.gpu_status) if self.gpu_status else ""))
        if cpu is not None:
            self.thermal_coverage["cpu"] += 1
        if gpu is not None:
            self.thermal_coverage["gpu"] += 1
        if self.phase in ("baseline", "working"):
            if cpu is not None and cpu >= self.cpu_limit.value() or gpu is not None and gpu >= self.gpu_limit.value():
                self.request_stop("Limite térmico configurado atingido")
            memory = psutil.virtual_memory()
            if memory.available < max(256 * 1024 ** 2, memory.total * .05):
                self.request_stop("Pouca RAM disponível")

    def request_stop(self, reason="Parada solicitada"):
        if isinstance(reason, bool):
            reason = "Parada solicitada"
        if not self.phase or self.phase in ("recovery", "finishing"):
            return
        self.reason = reason
        self.controller.stop()
        if self.phase == "baseline":
            self.finish_load({"state": "stopped", "kind": self.options["kind"], "elapsed_s": 0, "errors": None})
        self.status.setText(reason + " · encerrando carga e preservando a recuperação.")

    def mark(self, note="Sintoma percebido durante o teste"):
        if not self.recorder.active.is_set():
            return
        self.recorder.command("mark", {"timestamp": datetime.now().astimezone().isoformat(),
                                       "monotonic": time.monotonic(), "note": note})

    def finish_load(self, result):
        self.controller.close()
        if self.reason:
            result.update(state="failed" if result.get("state") == "failed" else "stopped", reason=self.reason)
        result["stop_limits"] = {"cpu_c": self.cpu_limit.value(), "gpu_c": self.gpu_limit.value()}
        result["thermal_readings"] = dict(self.thermal_coverage)
        if self.controller.path:
            result["evidence_folder"] = self.controller.path.name
        if result.get("kind") == "gpu":
            self.gpu_status = result
        write_json(self.path / "stress.json", result)
        self.phase, self.next_phase = "recovery", time.monotonic() + 5
        self.status.setText("Carga encerrada · registrando 5 s de recuperação…")
        self.update_state()

    def poll(self):
        if self._closed or not self.phase:
            return
        try:
            if self.phase == "baseline" and time.monotonic() >= self.next_phase:
                if self.last_sample_at is None or time.monotonic() - self.last_sample_at > 5:
                    raise RuntimeError("Sem leituras atualizadas para acompanhar o teste.")
                self.controller.start(self.path, self.options)
                self.phase = "working"
            elif self.phase == "working":
                status = self.controller.status()
                if self.options["kind"] == "gpu":
                    self.gpu_status = status
                text = f"Carga {self.options['kind']} · {status.get('elapsed_s', 0):.0f} / {self.options['duration_s']} s"
                if isinstance(status.get("fps"), (int, float)):
                    text += f" · {status['fps']:.1f} FPS · P95 {status.get('frametime_p95_ms', 0):.1f} ms · P99 {status.get('frametime_p99_ms', 0):.1f} ms"
                self.status.setText(text + " · Parar teste encerra a carga.")
                if self.last_sample_at is not None and time.monotonic() - self.last_sample_at > 5:
                    self.request_stop("Monitor sem leituras atualizadas")
                if self.controller.process.poll() is not None:
                    if self.controller.process.returncode and status.get("state") not in ("running", "failed", None):
                        status = {**status, "state": "failed",
                                  "verification_status": "failed" if status.get("errors") else "partial",
                                  "reason": f"Auxiliar encerrou com código {self.controller.process.returncode}; resultado final incompleto."}
                    if not status or status.get("state") == "running":
                        status = {"kind": self.options["kind"], "state": "failed", "errors": None, "elapsed_s": 0,
                                  "reason": f"Processo encerrou sem resultado válido; código {self.controller.process.returncode}."}
                    self.finish_load(status)
            elif self.phase == "recovery" and time.monotonic() >= self.next_phase:
                self.phase = "finishing"
                self.recorder.command("stop")
        except (OSError, ValueError, RuntimeError) as error:
            self.finish_load({"kind": self.options["kind"], "state": "failed", "elapsed_s": 0, "errors": None, "reason": str(error)})

    def shutdown(self):
        self._closed = True
        self.timer.stop()
        self.controller.close()
        try:
            if self.path and self.options and self.phase in ("baseline", "working"):
                result = self.controller.status()
                if result.get("state") not in ("completed", "stopped", "failed"):
                    result = {"kind": self.options["kind"], "state": "stopped", "elapsed_s": result.get("elapsed_s", 0),
                              "errors": None, "reason": "Aplicativo encerrado antes da finalização da carga."}
                result["stop_limits"] = {"cpu_c": self.cpu_limit.value(), "gpu_c": self.gpu_limit.value()}
                result["thermal_readings"] = dict(self.thermal_coverage)
                write_json(self.path / "stress.json", result)
        finally:
            self.recorder.shutdown()
            self.activity.end_capture("stress")
