import csv
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
        self.path = None
        self.executable = None
        self.session = None

    def start(self, folder, pid, executable="", seconds=1800):
        if not pid:
            raise ValueError("Selecione o aplicativo para capturar seus frametimes.")
        self.executable = find_presentmon(executable)
        if not self.executable:
            raise ValueError("PresentMon não encontrado. Informe o executável em Mais opções.")
        self.path = Path(folder) / "frametimes.csv"
        self.session = "SysPulseFrames_" + uuid.uuid4().hex
        self.log = (Path(folder) / "presentmon.log").open("wb")
        arguments = [self.executable, "--process_id", str(int(pid)), "--output_file", str(self.path),
                     "--qpc_time_ms", "--v2_metrics", "--no_console_stats",
                     "--no_track_input", "--no_track_gpu", "--no_track_display",
                     "--session_name", self.session, "--timed", str(int(seconds)), "--terminate_after_timed",
                     "--terminate_on_proc_exit"]
        try:
            self.process = subprocess.Popen(arguments, stdout=self.log, stderr=subprocess.STDOUT,
                                            creationflags=0x08000000 if os.name == "nt" else 0)
        except OSError:
            self.log.close()
            raise

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
        if self.log:
            self.log.close()
        if self.path and self.path.suffix == ".csv" and self.path.is_file() and self.path.stat().st_size:
            target = self.path.with_suffix(".csv.gz")
            temporary = target.with_suffix(".gz.tmp")
            with self.path.open("rb") as source, gzip.open(temporary, "wb", compresslevel=1) as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            temporary.replace(target)
            self.path.unlink()
            self.path = target
        return self.process.returncode if self.process else None
