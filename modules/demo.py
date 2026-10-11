"""Explicit synthetic data for documentation; never used in real captures."""
import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


def demo_samples():
    start = datetime(2026, 1, 15, 14, 30, tzinfo=timezone(timedelta(hours=-3)))
    result = []
    for index in range(181):
        seconds = index / 2
        burst = 32 <= seconds <= 38
        cpu = 85 + 10 * math.sin(seconds) if burst else 22 + 7 * math.sin(seconds / 5)
        gpu = 95 + 3 * math.sin(seconds) if 60 <= seconds <= 70 else 45 + 12 * math.sin(seconds / 8)
        disk = 94 if 48 <= seconds <= 51 else 5 + 3 * math.sin(seconds / 4)
        batch = index // 4 * 2
        heavy = 32 <= batch <= 38
        process_data = [
            (4100, "jogo-demo.exe", 68 if heavy else 17, 2300, 2.0, 0.1, gpu * .9),
            (5200, "navegador-demo.exe", 8.2, 1280, 0.3, 0.2, 4.0),
            (6300, "backup-demo.exe", 3.0, 450, 90 if 48 <= batch <= 52 else 0.2, 40 if 48 <= batch <= 52 else 0.1, 0.0),
            (7400, "editor-demo.exe", 1.5, 2100, .05, .2, 0.0),
            (8500, "syspulse-demo.exe", .6, 140, .02, .06, 0.0),
        ]
        processes = [{"pid": pid, "name": name, "created": 1000 + pid, "cpu_percent": load,
                      "rss_mb": ram, "ram_percent": ram / 32768 * 100, "io_read_mbs": read,
                      "io_write_mbs": write, "io_total_mbs": read + write, "gpu_percent": engine}
                     for pid, name, load, ram, read, write, engine in process_data]
        sample = {"timestamp": (start + timedelta(seconds=seconds)).isoformat(timespec="milliseconds"),
                  "monotonic": 10000 + seconds, "interval_ms": 500, "target_interval_ms": 500,
                  "cpu_percent": cpu, "cpu_max_core": 99 if burst else min(100, cpu * 1.8),
                  "cpu_cores": [99 if burst else cpu * 1.8] + [cpu] * 11,
                  "ram_percent": 52 + 2 * math.sin(seconds / 20), "ram_available_gb": 15.0,
                  "ram_total_gb": 32, "swap_percent": 3.0, "cpu_freq_mhz": 4100,
                  "cpu_temperature": 64, "uptime": "2:35:10", "collector_ms": 7.2,
                  "sensor_age_ms": 0, "process_age_ms": (seconds - batch) * 1000,
                  "process_sample_monotonic": 10000 + batch, "processes": processes,
                  "gpus": [{"name": "GPU de demonstração", "source": "Simulado", "percent": gpu,
                            "temperature": 61, "memory_used_mb": 3200, "memory_total_mb": 8192,
                            "clock_mhz": 1750, "power_w": 100}],
                  "disks": [{"name": "SSD de demonstração", "active_percent": disk,
                             "read_mbs": 95 if disk > 90 else 2.4, "write_mbs": 42 if disk > 90 else .8,
                             "read_ms": 14 if disk > 90 else .4, "write_ms": 8 if disk > 90 else .6, "queue": 1}],
                  "storage_percent": [{"disco": "C:", "percent": 42, "free": 290, "total": 500}],
                  "network": {"download_mbs": 1.2, "upload_mbs": .1, "total_down_mb": 750, "total_up_mb": 35},
                  "ping": {"ms": 18}, "net_info": [], "sensor_status": "DADOS SIMULADOS — prévia de documentação",
                  "page_reads_s": 0, "dpc_percent": .2, "interrupt_percent": .1, "sensors": []}
        result.append(sample)
    return result


def demo_markers(samples):
    return [{"id": i, "timestamp": samples[index]["timestamp"], "monotonic": samples[index]["monotonic"], "note": note}
            for i, (index, note) in enumerate(((70, "Pausa percebida — exemplo de CPU"),
                                               (100, "Leitura/escrita — exemplo de I/O"),
                                               (130, "Cena exigente — exemplo de GPU")), 1)]


def write_demo_session(destination):
    path = Path(destination)
    path.mkdir(parents=True, exist_ok=True)
    samples = demo_samples()
    with (path / "amostras.jsonl").open("w", encoding="utf-8") as file:
        for sample in samples:
            file.write(json.dumps(sample, ensure_ascii=False) + "\n")
    with (path / "marcacoes.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, ["id", "timestamp", "monotonic", "note"])
        writer.writeheader()
        writer.writerows(demo_markers(samples))
    (path / "sessao.json").write_text(json.dumps({"schema_version": 2, "app_version": "2.0.0", "demo": True,
        "started": samples[0]["timestamp"], "ended": samples[-1]["timestamp"], "interval_ms": 500,
        "count": len(samples), "dropped": 0}, ensure_ascii=False, indent=2), encoding="utf-8")


class DemoMonitor:
    def __init__(self):
        self.samples = demo_samples()
        self.markers = demo_markers(self.samples)
        self.sensors = SimpleNamespace(lhm_enabled=False)
        self.last_error = "Modo demonstração • dados simulados • nenhuma coleta real"
        self.interval = .5

    def latest(self):
        return self.samples[-1]

    def start(self):
        pass

    def stop(self):
        pass
