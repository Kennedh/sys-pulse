import threading
import time
from datetime import datetime

import psutil

from modules.network import NetworkMonitor
from modules.sensors import SensorService
from modules.windows_counters import WindowsCounters


def process_io_rates(previous, current, seconds):
    rates = {"io_read_mbs": None, "io_write_mbs": None, "io_total_mbs": None}
    if previous is None or current is None or seconds <= 0:
        return rates
    for field, key in (("read_bytes", "io_read_mbs"), ("write_bytes", "io_write_mbs")):
        before, after = getattr(previous, field, -1), getattr(current, field, -1)
        if before >= 0 and after >= before:
            rates[key] = (after - before) / seconds / 1024 ** 2
    if rates["io_read_mbs"] is not None and rates["io_write_mbs"] is not None:
        rates["io_total_mbs"] = rates["io_read_mbs"] + rates["io_write_mbs"]
    return rates


def disk_rates(previous, current, seconds):
    result = []
    if seconds <= 0:
        return result
    for name, value in current.items():
        old = previous.get(name)
        row = {"name": name, "read_mbs": None, "write_mbs": None,
               "read_ms": None, "write_ms": None, "active_percent": None, "read_iops": None, "write_iops": None}
        if old is not None:
            def delta(field):
                before, after = getattr(old, field, None), getattr(value, field, None)
                return after - before if before is not None and after is not None and after >= before else None

            for operation in ("read", "write"):
                size, count, duration = (delta(f"{operation}_{field}") for field in ("bytes", "count", "time"))
                row[f"{operation}_mbs"] = size / seconds / 1024 ** 2 if size is not None else None
                row[f"{operation}_ms"] = duration / count if duration is not None and count else None
                row[f"{operation}_iops"] = count / seconds if count is not None else None
            busy = delta("busy_time")
            row["active_percent"] = min(100.0, busy / (seconds * 10)) if busy is not None else None
        result.append(row)
    return result


class MonitorWorker:
    def __init__(self, on_sample=None, discos_ignorados=None):
        self.on_sample = on_sample
        self.discos_ignorados = discos_ignorados or []
        self.interval = 0.5
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest = None
        self._thread = None
        self.sensors = SensorService(self.discos_ignorados)
        self.last_error = None
        self._process_io = {}
        self._process_seen = set()
        self._cpu_count = psutil.cpu_count() or 1
        self._process_lock = threading.Lock()
        self._process_thread = None
        self._process_snapshot = ([], None, None)
        self._process_error = None

    def start(self):
        if any(thread and thread.is_alive() for thread in (self._thread, self._process_thread)):
            return
        self._process_io = {}
        self._process_seen = set()
        self._stop.clear()
        self.sensors.start()
        self._thread = threading.Thread(target=self.run, name="sys-pulse-collector", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._process_thread:
            self._process_thread.join(timeout=5)
        self.sensors.stop()

    def latest(self):
        with self._lock:
            return self._latest

    def _processes(self, gpu_processes=None):
        rows = []
        now = time.monotonic()
        previous_io, self._process_io = self._process_io, {}
        previous_seen, self._process_seen = self._process_seen, set()
        for process in psutil.process_iter(["pid", "name"]):
            if process.pid == 0:
                continue
            try:
                with process.oneshot():
                    created = process.create_time()
                    key = (process.pid, created)
                    cpu = process.cpu_percent()
                    self._process_seen.add(key)
                    row = {"pid": process.pid, "name": process.info["name"] or "?",
                                 "created": created,
                                 "cpu_percent": round(cpu / self._cpu_count, 2) if key in previous_seen else None,
                                 "ram_percent": round(process.memory_percent(), 2),
                                 "rss_mb": round(process.memory_info().rss / 1024 ** 2, 1),
                                 "gpu_percent": (gpu_processes or {}).get(process.pid)}
                    try:
                        current = process.io_counters()
                    except (psutil.Error, OSError, AttributeError, NotImplementedError):
                        current = None
                    previous, at = previous_io.get(key, (None, now))
                    row.update(process_io_rates(previous, current, now - at))
                    if current is not None:
                        self._process_io[key] = (current, now)
                    rows.append(row)
            except (psutil.Error, OSError):
                continue
        return sorted(rows, key=lambda row: row["cpu_percent"] if row["cpu_percent"] is not None else -1, reverse=True)

    def _run_processes(self):
        counters = WindowsCounters(gpu_only=True)
        try:
            self._processes()
            while not self._stop.wait(2):
                started = time.monotonic()
                try:
                    rows = self._processes(counters.sample().get("gpu_processes"))
                    cost = (time.monotonic() - started) * 1000
                    with self._process_lock:
                        self._process_snapshot = (rows, started, cost)
                        self._process_error = None
                except (OSError, psutil.Error) as error:
                    with self._process_lock:
                        self._process_error = f"Processos temporariamente indisponíveis: {error}"
        except Exception as error:
            with self._process_lock:
                self._process_error = f"Coleta de processos interrompida: {type(error).__name__}: {error}"
        finally:
            counters.close()

    def run(self):
        counters = WindowsCounters()
        try:
            network = NetworkMonitor()
            previous_disks = psutil.disk_io_counters(perdisk=True) or {}
            psutil.cpu_percent(percpu=True)
            psutil.cpu_percent()
            psutil.cpu_times_percent()
            with self._process_lock:
                self._process_snapshot = ([], None, None)
                self._process_error = None
            self._process_thread = threading.Thread(target=self._run_processes, name="sys-pulse-processes", daemon=True)
            self._process_thread.start()
            previous_at = time.monotonic()
            boot_time = psutil.boot_time()
            deadline = previous_at + self.interval
            while not self._stop.wait(max(0, deadline - time.monotonic())):
                started = time.monotonic()
                with self._process_lock:
                    processes, process_at, process_cost = self._process_snapshot
                    process_error = self._process_error
                try:
                    elapsed = started - previous_at
                    cpu = psutil.cpu_percent()
                    cores = psutil.cpu_percent(percpu=True)
                    cpu_times = psutil.cpu_times_percent()
                    memory = psutil.virtual_memory()
                    swap = psutil.swap_memory()
                    current_disks = psutil.disk_io_counters(perdisk=True) or {}
                    disks = disk_rates(previous_disks, current_disks, elapsed)
                    previous_disks, previous_at = current_disks, started
                    win = counters.sample()
                    for disk in disks:
                        native = win.get("disks", {}).get(disk["name"].removeprefix("PhysicalDrive"))
                        if native:
                            disk.update(native)
                    sample = {
                        "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                        "monotonic": started, "interval_ms": elapsed * 1000,
                        "target_interval_ms": self.interval * 1000,
                        "uptime": str(datetime.now() - datetime.fromtimestamp(boot_time)).split(".")[0],
                        "cpu_percent": cpu, "cpu_cores": cores,
                        "cpu_max_core": max(cores, default=None),
                        "dpc_percent": getattr(cpu_times, "dpc", None),
                        "interrupt_percent": getattr(cpu_times, "interrupt", None),
                        "ram_percent": memory.percent, "ram_available_gb": memory.available / 1024 ** 3,
                        "ram_total_gb": memory.total / 1024 ** 3, "swap_percent": swap.percent,
                        "page_reads_s": win.get("page_reads_s"),
                        "disks": disks,
                        "processes": processes, "process_age_ms": (started - process_at) * 1000 if process_at is not None else None,
                        "process_sample_monotonic": process_at, "process_collector_ms": process_cost,
                        "process_status": process_error,
                        "network": network.get_network_speed(), **self.sensors.snapshot(),
                    }
                    sample["collector_ms"] = (time.monotonic() - started) * 1000
                    with self._lock:
                        self._latest = sample
                    if self.on_sample:
                        self.on_sample(sample)
                    self.last_error = None
                except (OSError, psutil.Error) as error:
                    self.last_error = f"Coleta temporariamente indisponível: {error}"
                deadline += self.interval
                if deadline <= time.monotonic():
                    deadline = time.monotonic() + self.interval
        except Exception as error:
            self.last_error = f"Coleta interrompida: {type(error).__name__}: {error}"
        finally:
            self._stop.set()
            counters.close()
