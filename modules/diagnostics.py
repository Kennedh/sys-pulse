import csv
import gzip
import json
import platform
import queue
import shutil
import threading
import time
from collections import deque
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

from modules.frametimes import FrameCapture
from modules.version import VERSION


CSV_FIELDS = ["timestamp", "cpu_percent", "cpu_max_core", "ram_percent", "ram_available_gb",
              "swap_percent", "cpu_temperature", "cpu_freq_mhz", "gpu_max_percent",
              "gpu_max_temperature", "disk_max_active_percent", "disk_max_read_ms",
              "disk_max_write_ms", "page_reads_s", "dpc_percent", "interrupt_percent",
              "interval_ms", "collector_ms", "sensor_age_ms", "process_age_ms"]


def max_value(values):
    return max((value for value in values if isinstance(value, (int, float))), default=None)


def metrics(sample):
    row = {key: sample.get(key) for key in CSV_FIELDS}
    for suffix, field in (("percent", "percent"), ("temperature", "temperature")):
        row[f"gpu_max_{suffix}"] = max_value(gpu.get(field) for gpu in sample.get("gpus", []))
    for field in ("active_percent", "read_ms", "write_ms"):
        row[f"disk_max_{field}"] = max_value(disk.get(field) for disk in sample.get("disks", []))
    return row


def summarize(samples):
    rows = [metrics(sample) for sample in samples]
    return {"samples": len(rows), "peaks": {key: max_value(row.get(key) for row in rows)
            for key in CSV_FIELDS if key != "timestamp"},
            "min_ram_available_gb": min((row["ram_available_gb"] for row in rows
                                         if row["ram_available_gb"] is not None), default=None)}


def event_summary(event, samples):
    center = event["monotonic"]
    selected = [sample for sample in samples if center - 5 <= sample["monotonic"] <= center + 5]
    before = summarize([sample for sample in selected if sample["monotonic"] < center])
    after = summarize([sample for sample in selected if sample["monotonic"] >= center])
    peaks = summarize(selected)["peaks"]
    evidence = []
    rules = [("cpu_max_core", 95, "Um núcleo lógico chegou a 95% ou mais. Verifique os processos e a carga da tarefa."),
             ("ram_percent", 90, "RAM chegou a 90% ou mais. Compare a memória disponível com as leituras de páginas."),
             ("gpu_max_percent", 95, "GPU chegou a 95% ou mais. Pode ser uso esperado durante o jogo."),
             ("disk_max_active_percent", 90, "Um disco chegou a 90% de atividade. Compare latência e fila por disco."),
             ("disk_max_read_ms", 30, "Latência média de leitura chegou a 30 ms/op ou mais."),
             ("disk_max_write_ms", 30, "Latência média de escrita chegou a 30 ms/op ou mais."),
             ("dpc_percent", 5, "Tempo de CPU em DPC chegou a 5%. Isso não mede latência DPC nem identifica drivers.")]
    for key, threshold, text in rules:
        if peaks.get(key) is not None and peaks[key] >= threshold:
            evidence.append(text)
    if any(sample.get("interval_ms", 0) > sample.get("target_interval_ms", 500) * 2 for sample in selected):
        evidence.append("Houve atraso na coleta; pode ser agendamento do sistema ou custo do monitor. Não é uma medida de frametime.")
    if not evidence:
        evidence.append("Sem pico nos critérios disponíveis. Isso não descarta stutter, driver ou picos menores que o intervalo de coleta.")
    processes = {}
    for sample in selected:
        for process in sample.get("processes", []):
            key = (process["pid"], process["name"], process.get("created"))
            if process.get("cpu_percent") is None:
                continue
            if key not in processes or process["cpu_percent"] > processes[key]["cpu_percent"]:
                processes[key] = process
    return {"event": event, "before": before, "after": after, "evidence": evidence,
            "coverage_seconds": [min((s["monotonic"] - center for s in selected), default=None),
                                 max((s["monotonic"] - center for s in selected), default=None)],
            "top_processes": sorted(processes.values(), key=lambda p: p["cpu_percent"], reverse=True)[:5]}


class SessionRecorder:
    def __init__(self, on_status=None, max_bytes=256 * 1024 ** 2):
        self.on_status = on_status or (lambda status: None)
        self.max_bytes = max_bytes
        self.active = threading.Event()
        self.commands = queue.Queue(maxsize=256)
        self.dropped = 0
        self.path = None
        self.files = None
        self.frames = None
        self.thread = threading.Thread(target=self._run, name="sys-pulse-recorder", daemon=True)
        self.thread.start()

    def command(self, kind, payload=None):
        try:
            self.commands.put_nowait((kind, payload))
            return True
        except queue.Full:
            return False

    def submit(self, sample):
        if self.active.is_set() and not self.command("sample", sample):
            self.dropped += 1

    def shutdown(self):
        try:
            self.commands.put(("shutdown", None), timeout=3)
        except queue.Full:
            return False
        self.thread.join(timeout=5)
        return not self.thread.is_alive()

    def _notify(self, message, **extra):
        self.on_status({"active": self.active.is_set(), "message": message,
                        "path": str(self.path) if self.path else None, "dropped": self.dropped, **extra})

    def _start(self, options):
        if self.active.is_set():
            return
        root = Path(options["folder"]).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(root).free < 128 * 1024 ** 2:
            raise OSError("Separe pelo menos 128 MiB livres para a investigação.")
        self.space_checked = time.monotonic()
        self.path = root / datetime.now().strftime("sessao-%Y%m%d-%H%M%S-%f")
        self.path.mkdir()
        self.files = ExitStack()
        compressed = options.get("compressed", False)
        self.raw = self.files.enter_context(
            gzip.open(self.path / "amostras.jsonl.gz", "wt", encoding="utf-8", compresslevel=1)
            if compressed else (self.path / "amostras.jsonl").open("w", encoding="utf-8"))
        self.flat = self.files.enter_context((self.path / "metricas.csv").open("w", encoding="utf-8-sig", newline="")) if options.get("csv", True) else None
        self.duration_s = max(30, min(7200, int(options.get("duration_s", 7200))))
        self.options = options
        self.marks = self.files.enter_context((self.path / "marcacoes.csv").open("w", encoding="utf-8-sig", newline=""))
        self.events = self.files.enter_context((self.path / "eventos.jsonl").open("w", encoding="utf-8"))
        self.report = self.files.enter_context((self.path / "relatorio.txt").open("w", encoding="utf-8"))
        self.csv = csv.DictWriter(self.flat, fieldnames=CSV_FIELDS) if self.flat else None
        if self.csv:
            self.csv.writeheader()
        self.marker_csv = csv.DictWriter(self.marks, fieldnames=["id", "timestamp", "monotonic", "note"])
        self.marker_csv.writeheader()
        metadata = {"schema_version": 3, "app_version": VERSION, "started": datetime.now().astimezone().isoformat(),
                    "system": platform.platform(), "python": platform.python_version(),
                    "interval_ms": options.get("interval_ms", 500), "window_seconds": 5,
                    "max_raw_bytes": self.max_bytes, "max_hours": self.duration_s / 3600,
                    "compressed": compressed, "duration_s": self.duration_s,
                    "symptom": str(options.get("symptom", ""))[:120], "target_pid": options.get("target_pid")}
        self.metadata = metadata
        self._inventory(options.get("inventory"))
        (self.path / "sessao.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        self.report.write("SYS-PULSE — INVESTIGAÇÃO DE TRAVAMENTOS\n\n"
                          "Os indícios abaixo são correlações, não uma conclusão sobre defeitos.\n"
                          "Critérios de triagem: núcleo/GPU >= 95%, RAM/atividade de disco >= 90%,\n"
                          "latência média de disco >= 30 ms/op, CPU em DPC >= 5%.\n"
                          "Temperatura é registrada sem presumir um limite universal.\n"
                          "Cada marcação compara até 5 s antes e depois. Ausência de dados não equivale a zero.\n"
                          "CPU por processo é normalizada pelo total de CPUs lógicas e atualizada a cada 2 s.\n"
                          "Frametimes dependem do PresentMon opcional; não mede latência DPC/ISR ou integridade da fonte/RAM.\n\n")
        self.history = deque(maxlen=160)
        self.pending = []
        self.count = self.event_count = self.raw_bytes = self.dropped = 0
        self.started = self.flushed = time.monotonic()
        self.peaks = {}
        if options.get("frames"):
            self.frames = FrameCapture()
            try:
                self.frames.start(self.path, options.get("target_pid"), options.get("presentmon", ""),
                                  self.duration_s)
            except (ValueError, OSError) as error:
                self.frames = None
                self.metadata["frame_error"] = str(error)
                (self.path / "sessao.json").write_text(json.dumps(self.metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        self.active.set()
        self._notify("Gravação iniciada", count=0, started=True)

    def _inventory(self, snapshot):
        if not snapshot or not self.path:
            return
        target = self.path / "inventario.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(target)

    def _sample(self, sample):
        sample = dict(sample)
        sample.pop("ping_history", None)
        processes = sample.get("processes", [])
        selected = []
        for field in ("cpu_percent", "ram_percent", "io_total_mbs", "gpu_percent"):
            selected += sorted((p for p in processes if p.get(field) is not None),
                               key=lambda p: p[field], reverse=True)[:10]
        target_pid = self.options.get("target_pid")
        selected += [p for p in processes if p.get("pid") == target_pid]
        sample["processes"] = list({(p["pid"], p["name"], p.get("created")): p for p in selected}.values())
        sample["process_selection"] = "top 10 CPU + RAM + I/O + GPU; CPU normalizada; intervalo mínimo de 2 s; varredura em segundo plano"
        line = json.dumps(sample, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
        self.raw.write(line)
        self.raw_bytes += len(line.encode("utf-8"))
        row = metrics(sample)
        if self.csv:
            self.csv.writerow(row)
        for key, value in row.items():
            if key != "timestamp" and value is not None:
                self.peaks[key] = max(value, self.peaks.get(key, value))
        self.count += 1
        self.history.append(sample)
        while self.history and self.history[0]["monotonic"] < sample["monotonic"] - 10:
            self.history.popleft()
        for event in list(self.pending):
            if abs(sample["monotonic"] - event["event"]["monotonic"]) <= 5:
                event["samples"].append(sample)
            if sample["monotonic"] >= event["event"]["monotonic"] + 5:
                self._finish_event(event)
                self.pending.remove(event)
        now = time.monotonic()
        if now - self.flushed >= 2:
            self._flush()
            self.flushed = now
            elapsed = int(now - self.started)
            raw_path = self.path / ("amostras.jsonl.gz" if self.options.get("compressed") else "amostras.jsonl")
            size_mib = raw_path.stat().st_size / 1024 ** 2
            self._notify(f"Gravando · {elapsed // 60:02d}:{elapsed % 60:02d} / {self.duration_s // 60} min · "
                         f"{size_mib:.2f} MiB · {self.count} amostras · {self.event_count} marcações", count=self.count)
        if now - self.space_checked >= 10:
            self.space_checked = now
            if self.frames and self.frames.path and self.frames.path.is_file() and self.frames.path.stat().st_size > 256 * 1024 ** 2:
                try:
                    self.frames.stop()
                except OSError:
                    pass
                self.frames = None
                self.metadata["frame_error"] = "Frametimes interrompidos no limite aproximado de 256 MiB; recursos continuaram sendo gravados."
            if shutil.disk_usage(self.path).free < 64 * 1024 ** 2:
                self._stop("Pouco espaço livre; gravação encerrada para preservar os dados.")
                return
        if self.raw_bytes >= self.max_bytes or now - self.started >= self.duration_s:
            self._stop("Limite de sessão atingido (volume de amostras ou duração escolhida)")

    def _mark(self, event):
        self.event_count += 1
        event = {"id": self.event_count, **event}
        self.marker_csv.writerow(event)
        self.marks.flush()
        self.pending.append({"event": event, "samples": [sample for sample in self.history
                            if abs(sample["monotonic"] - event["monotonic"]) <= 5]})
        self._notify(f"Marcação {self.event_count} registrada às {event['timestamp']}", marker=event)

    def _finish_event(self, pending):
        summary = event_summary(pending["event"], pending["samples"])
        self.events.write(json.dumps(summary, ensure_ascii=False, allow_nan=False) + "\n")
        event = summary["event"]
        self.report.write(f"MARCAÇÃO {event['id']} — {event['timestamp']}\n{event['note']}\n")
        coverage = summary["coverage_seconds"]
        self.report.write(f"Cobertura relativa ao atalho: {coverage} segundos; "
                          f"antes={summary['before']['samples']}, depois={summary['after']['samples']} amostras.\n")
        for evidence in summary["evidence"]:
            self.report.write(f"- {evidence}\n")
        for key in ("cpu_max_core", "ram_percent", "gpu_max_percent", "cpu_temperature",
                    "gpu_max_temperature", "disk_max_read_ms", "disk_max_write_ms", "dpc_percent", "interval_ms"):
            before = summary["before"]["peaks"].get(key)
            after = summary["after"]["peaks"].get(key)
            fmt = lambda value: f"{value:.2f}" if value is not None else "N/D"
            self.report.write(f"  {key}: antes {fmt(before)} | depois {fmt(after)}\n")
        for process in summary["top_processes"]:
            self.report.write(f"  PID {process['pid']} {process['name']}: pico CPU {process['cpu_percent']:.2f}%\n")
        self.report.write("\n")
        self.report.flush()

    def _flush(self):
        for file in (self.raw, self.flat, self.marks, self.events, self.report):
            if file:
                file.flush()

    def _stop(self, reason="Gravação concluída"):
        self.active.clear()
        if self.frames:
            try:
                code = self.frames.stop()
                if code:
                    self.metadata["frame_error"] = f"PresentMon retornou {code}; confira presentmon.log."
                elif not self.frames.path or not self.frames.path.is_file() or not self.frames.path.stat().st_size:
                    self.metadata["frame_error"] = "PresentMon não gerou frametimes; confira o aplicativo selecionado, o suporte e presentmon.log."
            except OSError as error:
                self.metadata["frame_error"] = f"Frametimes preservados sem finalização completa: {error}"
            self.frames = None
        if not self.files:
            return
        for pending in self.pending:
            self._finish_event(pending)
        self.pending.clear()
        self.report.write(f"FIM DA SESSÃO\n{reason}\nAmostras: {self.count}\nMarcações: {self.event_count}\n"
                          f"Amostras perdidas por fila cheia: {self.dropped}\n"
                          "Sessões curtas ou encerradas logo após o atalho terão cobertura parcial.\n"
                          f"Picos da sessão (campos disponíveis):\n{json.dumps(self.peaks, ensure_ascii=False, indent=2)}\n")
        self._flush()
        self.files.close()
        self.files = None
        self.metadata.update(ended=datetime.now().astimezone().isoformat(),
                             count=self.count, dropped=self.dropped, reason=reason)
        (self.path / "sessao.json").write_text(json.dumps(self.metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        self._notify(reason, count=self.count, completed=True)

    def _run(self):
        while True:
            kind, payload = self.commands.get()
            try:
                if kind == "start":
                    self._start(payload)
                elif kind == "inventory" and self.active.is_set():
                    self._inventory(payload)
                elif kind == "stop":
                    self._stop()
                elif kind == "sample" and self.active.is_set():
                    self._sample(payload)
                elif kind == "mark" and self.active.is_set():
                    self._mark(payload)
                elif kind == "shutdown":
                    self._stop()
                    return
            except Exception as error:
                self.active.clear()
                if self.frames:
                    try:
                        self.frames.stop()
                    except OSError:
                        pass
                    self.frames = None
                if self.files:
                    try:
                        self.files.close()
                    except OSError:
                        pass
                    self.files = None
                self._notify(f"Falha na gravação: {type(error).__name__}: {error}. Arquivos podem estar incompletos.", error=True)
                if kind == "shutdown":
                    return
            finally:
                self.commands.task_done()
