import csv
import codecs
import threading
import gzip
import ctypes
import heapq
import math
import os
import shutil
import subprocess
import time
import uuid
from array import array
from collections import deque
from pathlib import Path


def find_presentmon(path=""):
    if path and Path(path).is_file():
        return str(Path(path).resolve())
    bundled = Path(__file__).resolve().parents[1] / "tools" / "bin" / "PresentMon.exe"
    return str(bundled) if bundled.is_file() else shutil.which("PresentMon.exe")


def numeric(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def analyze_frames(file, cancel=lambda: False, target_pid=None):
    groups, invalid, total = {}, 0, 0

    def lines():
        size = 0
        for line in file:
            size += len(line.encode("utf-8"))
            if size > 512 * 1024 ** 2:
                raise ValueError("Frametimes descomprimidos excedem 512 MiB.")
            if len(line) > 65536:
                raise ValueError("Linha de frametimes excede 64 KiB.")
            yield line

    for row in csv.DictReader(lines()):
        if cancel():
            raise InterruptedError("Leitura de frametimes cancelada.")
        total += 1
        if total > 2_000_000:
            raise ValueError("Frametimes excedem 2 milhões de linhas.")
        try:
            pid = int(row.get("ProcessID") or row.get("ProcessId") or 0)
        except ValueError:
            invalid += 1
            continue
        if target_pid and pid != target_pid:
            continue
        key = (pid, str(row.get("SwapChainAddress") or "default")[:80])
        if key not in groups:
            if len(groups) >= 64:
                invalid += 1
                continue
            groups[key] = {"values": array("d"), "top": [], "previous": None,
                           "metric": None, "alignment": "unavailable", "periods": {}}
        group = groups[key]
        at = numeric(row.get("CPUStartQPCTime"))
        if at is not None:
            at /= 1000
            group["alignment"] = "QPC em segundos; origem comum à coleta Windows"
        else:
            at = numeric(row.get("TimeInSeconds"))
            if at is not None:
                group["alignment"] = "Tempo relativo do PresentMon; sem alinhamento exato automático"
        value = None
        for field in ("MsBetweenPresents", "CPUFrameTime", "FrameTime"):
            value = numeric(row.get(field))
            if value is not None:
                group["metric"] = field
                break
        if value is None and at is not None and group["previous"] is not None and at > group["previous"]:
            value = (at - group["previous"]) * 1000
            group["metric"] = "Diferença entre CPUStartQPCTime"
        group["previous"] = at
        if value is None or value <= 0:
            invalid += 1
            continue
        group["values"].append(value)
        if at is not None:
            minute = int(at // 60)
            if minute in group["periods"] or len(group["periods"]) < 256:
                group["periods"].setdefault(minute, array("d")).append(value)
        item = (value, total, at, numeric(row.get("MsGPUBusy") or row.get("GPUBusy")),
                numeric(row.get("MsCPUBusy") or row.get("CPUBusy")))
        heapq.heappush(group["top"], item)
        if len(group["top"]) > 20:
            heapq.heappop(group["top"])
    series = []
    for (pid, chain), group in groups.items():
        ordered = sorted(group["values"])
        if not ordered:
            continue
        count = len(ordered)
        median = ordered[(count - 1) // 2]
        threshold = max(50, median * 3)
        periods = []
        for minute, values in sorted(group["periods"].items()):
            ordered_period = sorted(values)
            periods.append({"minute": minute, "count": len(values),
                            "p99_ms": ordered_period[math.ceil(.99 * len(values)) - 1],
                            "mean_ms": sum(values) / len(values), "max_ms": ordered_period[-1],
                            "over_50_ms": sum(value > 50 for value in values)})
        series.append({"periods": periods, "pid": pid, "swapchain": chain, "count": count, "metric": group["metric"],
                       "alignment": group["alignment"], "median_ms": median,
                       "p95_ms": ordered[math.ceil(.95 * count) - 1], "p99_ms": ordered[math.ceil(.99 * count) - 1],
                       "max_ms": ordered[-1], "mean_ms": sum(ordered) / count,
                       "over_50_ms": sum(value > 50 for value in ordered),
                       "over_100_ms": sum(value > 100 for value in ordered),
                       "long_threshold_ms": threshold, "long_intervals": sum(value >= threshold for value in ordered),
                       "events": [{"duration_ms": item[0], "monotonic": item[2], "gpu_busy_ms": item[3], "cpu_busy_ms": item[4]}
                                  for item in sorted(group["top"], reverse=True)]})
    series.sort(key=lambda row: row["count"], reverse=True)
    return {"series": series, "invalid_rows": invalid, "rows": total,
            "method": "Intervalos por PID e swapchain, sem misturar cadeias. P95/P99 por posição mais próxima. "
                      "Intervalo longo: pelo menos 50 ms e 3 vezes a mediana da cadeia; é triagem, não causa. "
                      "Minimização, limitador e tarefa podem explicar intervalos longos. A coluna usada é informada; o modo mínimo não mede tempo exibido, GPU por quadro ou latência de entrada."}


class FrameCapture:
    def __init__(self):
        self.process = None
        self.log = None
        self.output = None
        self.reader = None
        self.stream_error = None
        self.path = None
        self.executable = None
        self.session = None
        self.live_offset = 0
        self.live_partial = b''
        self.live_header = None
        self.live_rows = deque(maxlen=4000)
        self.live_updated = None
        self.pid = None

    def start(self, folder, pid, executable="", seconds=1800):
        if not pid:
            raise ValueError("Selecione o aplicativo para capturar seus frametimes.")
        self.executable = find_presentmon(executable)
        if not self.executable:
            raise ValueError("PresentMon não encontrado. Informe o executável em Mais opções.")
        self.pid = int(pid)
        self.path = Path(folder) / "frametimes.csv"
        self.session = "SysPulseFrames_" + uuid.uuid4().hex
        self.log = (Path(folder) / "presentmon.log").open("wb")
        self.output = self.path.open("wb", buffering=0)
        arguments = [self.executable, "--process_id", str(int(pid)), "--output_stdout",
                     "--qpc_time_ms", "--v2_metrics", "--no_console_stats",
                     "--no_track_input", "--no_track_gpu", "--no_track_display",
                     "--session_name", self.session, "--timed", str(int(seconds)), "--terminate_after_timed",
                     "--terminate_on_proc_exit"]
        try:
            self.process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=self.log,
                                            creationflags=0x08000000 if os.name == "nt" else 0)
            self.reader = threading.Thread(target=self._copy_output, name="sys-pulse-frames", daemon=True)
            self.reader.start()
        except OSError:
            self.output.close()
            self.log.close()
            raise

    def _copy_output(self):
        try:
            with self.process.stdout as source:
                first = source.read(2)
                if not first:
                    return
                encoding = "utf-16" if first in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
                decoder = codecs.getincrementaldecoder(encoding)()
                self.output.write(decoder.decode(first).encode("utf-8"))
                while True:
                    block = source.read1(65536)
                    if not block:
                        break
                    self.output.write(decoder.decode(block).encode("utf-8"))
                self.output.write(decoder.decode(b"", final=True).encode("utf-8"))
        except (OSError, UnicodeError) as error:
            self.stream_error = str(error)

    def live_snapshot(self):
        now = time.monotonic()
        if self.stream_error:
            return {"state": "invalid"}
        if not self.path or not self.path.is_file() or self.path.suffix != ".csv":
            return {"state": "waiting"}
        try:
            with self.path.open("rb") as source:
                source.seek(self.live_offset)
                block = source.read(1024 * 1024)
                self.live_offset = source.tell()
            lines = (self.live_partial + block).split(b"\n")
            self.live_partial = lines.pop()
            if len(self.live_partial) > 65536:
                self.live_partial = b""
                return {"state": "invalid"}
            for line in lines:
                if len(line) > 65536:
                    continue
                try:
                    cells = next(csv.reader([line.decode("utf-8-sig", "replace").rstrip("\r")]), [])
                except csv.Error:
                    continue
                if self.live_header is None:
                    self.live_header = cells
                    continue
                row = dict(zip(self.live_header, cells))
                try:
                    pid = int(row.get("ProcessID") or row.get("ProcessId") or 0)
                except ValueError:
                    continue
                if self.pid and pid != self.pid:
                    continue
                value = next((numeric(row.get(field)) for field in
                              ("MsBetweenPresents", "CPUFrameTime", "FrameTime") if numeric(row.get(field))), None)
                if value:
                    at = numeric(row.get("CPUStartQPCTime"))
                    self.live_rows.append((now, at / 1000 if at is not None else None,
                                           str(row.get("SwapChainAddress") or "default")[:80], value))
                    self.live_updated = now
        except OSError:
            return {"state": "waiting"}
        if self.live_updated is None:
            return {"state": "waiting"}
        if now - self.live_updated > 4:
            return {"state": "stale"}
        recent = [row for row in self.live_rows if now - row[0] <= 3]
        if not recent:
            return {"state": "waiting"}
        latest = max((row[1] for row in recent if row[1] is not None), default=None)
        if latest is not None:
            recent = [row for row in recent if row[1] is not None and latest - row[1] <= 2]
        groups = {}
        for _, _, chain, value in recent:
            groups.setdefault(chain, []).append(value)
        chain, values = max(groups.items(), key=lambda item: len(item[1]))
        values.sort()
        return {"state": "ok", "fps": 1000 * len(values) / sum(values),
                "p95_ms": values[math.ceil(.95 * len(values)) - 1],
                "p99_ms": values[math.ceil(.99 * len(values)) - 1],
                "frames": len(values), "swapchain": chain, "pid": self.pid,
                "backlog": len(block) == 1024 * 1024}

    def stop(self):
        if self.process and self.process.poll() is None:
            try:
                subprocess.run([self.executable, "--session_name", self.session, "--terminate_existing_session"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                               creationflags=0x08000000 if os.name == "nt" else 0)
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.process.terminate()
                self.process.wait(timeout=5)
        if self.reader:
            self.reader.join(timeout=5)
            if self.reader.is_alive():
                raise OSError("A saída de quadros não concluiu; confira presentmon.log.")
        if self.log:
            self.log.close()
        if self.output:
            self.output.close()
        if self.path and self.path.suffix == ".csv" and self.path.is_file() and self.path.stat().st_size:
            target = self.path.with_suffix(".csv.gz")
            temporary = target.with_suffix(".gz.tmp")
            with self.path.open("rb") as source, gzip.open(temporary, "wb", compresslevel=1) as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            temporary.replace(target)
            self.path.unlink()
            self.path = target
        if self.stream_error:
            raise OSError("Saída de quadros incompleta: " + self.stream_error)
        return self.process.returncode if self.process else None
