import json
from collections import deque
import math
import re
import threading
import time
import urllib.request

import psutil

from modules.network import NetworkMonitor


def number(value):
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    match = re.match(r"^\s*(-?\d+(?:[.,]\d+)?)", str(value))
    return float(match[1].replace(",", ".")) if match else None


def parse_lhm(tree):
    sensors, devices = [], {}

    def visit(node, hardware=""):
        identifier = node.get("HardwareId")
        if identifier:
            hardware = identifier
            devices[hardware] = node.get("Text", hardware)
        sensor_id = node.get("SensorId")
        if sensor_id:
            parent = sensor_id.rsplit("/", 2)[0]
            value = number(node.get("RawValue")) if "RawValue" in node else number(node.get("Value"))
            kind = node.get("Type") or sensor_id.split("/")[-2].title()
            if "RawValue" not in node and kind.lower() == "temperature" and "°F" in str(node.get("Value")) and value is not None:
                value = (value - 32) * 5 / 9
            sensors.append({"id": sensor_id, "hardware": hardware or parent,
                            "name": node.get("Text", sensor_id), "type": kind,
                            "value": value, "display": node.get("Value", "")})
        for child in node.get("Children", []):
            visit(child, hardware)

    visit(tree)
    cpu_temperatures, gpus = [], {}
    for sensor in sensors:
        sid, kind, name, value = sensor["id"], sensor["type"].lower(), sensor["name"].lower(), sensor["value"]
        if value is None:
            continue
        if sid.startswith(("/intelcpu/", "/amdcpu/")) and kind == "temperature" and "distance" not in name:
            cpu_temperatures.append(value)
        if not sid.startswith(("/gpu-nvidia/", "/gpu-amd/", "/gpu-intel/")):
            continue
        hardware = sensor["hardware"]
        gpu = gpus.setdefault(hardware, {"id": hardware, "name": devices.get(hardware, hardware), "source": "LibreHardwareMonitor"})
        if kind == "load" and name in ("gpu core", "d3d 3d"):
            gpu["percent"] = max(value, gpu.get("percent", 0))
        elif kind == "temperature" and name in ("gpu core", "gpu temperature"):
            gpu["temperature"] = value
        elif kind == "clock" and name == "gpu core":
            gpu["clock_mhz"] = value
        elif kind in ("smalldata", "data") and name in ("gpu memory used", "gpu memory total", "gpu memory free"):
            key = name.replace("gpu memory ", "memory_") + "_mb"
            gpu[key] = value * (1024 if kind == "data" else 1)
    for gpu in gpus.values():
        if "memory_total_mb" not in gpu and "memory_used_mb" in gpu and "memory_free_mb" in gpu:
            gpu["memory_total_mb"] = gpu["memory_used_mb"] + gpu["memory_free_mb"]
    return {"sensors": sensors, "gpus": list(gpus.values()),
            "cpu_temperature": max(cpu_temperatures, default=None)}


class SensorService:
    def __init__(self, discos_ignorados=None):
        self.discos_ignorados = discos_ignorados or []
        self.lhm_enabled = False
        self.ping_target = '8.8.8.8'
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._data = {}
        self._thread = None
        self.nvml = None
        self.handles = []
        self.nvml_status = "NVIDIA: inicializando"

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, name="sys-pulse-sensors", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def snapshot(self):
        with self._lock:
            data = dict(self._data)
        sampled_at = data.pop("sensor_at", None)
        data["sensor_sample_monotonic"] = sampled_at
        age = time.monotonic() - (sampled_at or 0)
        data["sensor_age_ms"] = age * 1000 if data else None
        if age > 4:
            data.update(gpus=[], sensors=[], cpu_temperature=None, cpu_freq_mhz=None,
                        sensor_status="Sensores indisponíveis ou sem atualização há mais de 4 s")
        data.setdefault("storage_percent", [])
        ping_at = data.get("ping_at")
        data["ping_age_ms"] = (time.monotonic() - ping_at) * 1000 if ping_at else None
        if data["ping_age_ms"] is None or data["ping_age_ms"] > 15000:
            data["ping"] = None
        return data

    def _init_nvml(self):
        try:
            import pynvml
            pynvml.nvmlInit()
            self.nvml = pynvml
            self.handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(pynvml.nvmlDeviceGetCount())]
            self.nvml_status = "NVIDIA: NVML ativo" if self.handles else "NVIDIA: nenhuma GPU disponível"
        except Exception as error:
            self.nvml_status = f"NVIDIA indisponível ({type(error).__name__})"

    def _nvidia(self):
        rows = []
        if not self.nvml:
            return rows
        nv = self.nvml
        for index, handle in enumerate(self.handles):
            def query(function, *args):
                try:
                    return function(handle, *args)
                except nv.NVMLError:
                    return None
            name = query(nv.nvmlDeviceGetName)
            if isinstance(name, bytes):
                name = name.decode(errors="replace")
            memory = query(nv.nvmlDeviceGetMemoryInfo)
            if memory and (memory.total <= 0 or memory.used > memory.total):
                memory = None
            usage = query(nv.nvmlDeviceGetUtilizationRates)
            power = query(nv.nvmlDeviceGetPowerUsage)
            rows.append({"id": f"nvidia:{index}", "name": name or f"NVIDIA {index}", "source": "NVML",
                         "percent": usage.gpu if usage else None,
                         "memory_used_mb": memory.used / 1024 ** 2 if memory else None,
                         "memory_total_mb": memory.total / 1024 ** 2 if memory else None,
                         "temperature": query(nv.nvmlDeviceGetTemperature, nv.NVML_TEMPERATURE_GPU),
                         "clock_mhz": query(nv.nvmlDeviceGetClockInfo, nv.NVML_CLOCK_GRAPHICS),
                         "power_w": power / 1000 if power is not None else None})
        return rows

    def _storage(self):
        rows = []
        for partition in psutil.disk_partitions(all=False):
            if partition.device.rstrip("\\/") in self.discos_ignorados:
                continue
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                rows.append({"disco": partition.device, "percent": usage.percent,
                             "total": usage.total / 1024 ** 3, "free": usage.free / 1024 ** 3})
            except (OSError, psutil.Error, NotImplementedError):
                continue
        return rows

    def run(self):
        self._init_nvml()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        last_network = last_ping = 0
        net_info, storage, ping, ping_at = [], [], None, None
        history = deque(maxlen=120)
        previous_target = self.ping_target
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                data = {"gpus": self._nvidia(), "sensors": [], "cpu_temperature": None,
                        "cpu_freq_mhz": None, "sensor_status": self.nvml_status}
                try:
                    freq = psutil.cpu_freq()
                    data["cpu_freq_mhz"] = freq.current if freq and freq.current > 0 else None
                    temperatures = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
                    values = [entry.current for group, entries in temperatures.items()
                              if group.lower() in ("coretemp", "k10temp", "cpu_thermal", "zenpower")
                              for entry in entries if entry.current is not None]
                    data["cpu_temperature"] = max(values, default=None)
                except (OSError, psutil.Error, NotImplementedError):
                    pass
                if self.lhm_enabled:
                    try:
                        with opener.open("http://127.0.0.1:8085/data.json", timeout=0.6) as response:
                            content = response.read(2 * 1024 * 1024 + 1)
                        if len(content) > 2 * 1024 * 1024:
                            raise ValueError("resposta muito grande")
                        lhm = parse_lhm(json.loads(content))
                        data["sensors"] = lhm["sensors"]
                        data["cpu_temperature"] = lhm["cpu_temperature"] or data["cpu_temperature"]
                        data["gpus"] += [gpu for gpu in lhm["gpus"] if not (data["gpus"] and gpu["id"].startswith("/gpu-nvidia/"))]
                        data["sensor_status"] += f" | Libre: {len(lhm['sensors'])} sensores"
                    except Exception as error:
                        data["sensor_status"] += f" | Libre indisponível ({type(error).__name__})"
                else:
                    data["sensor_status"] += " | Libre desativado"
                data["sensor_at"] = time.monotonic()
                if started - last_network >= 30:
                    try:
                        net_info = NetworkMonitor.get_infrastructure_info()
                        storage = self._storage()
                    except (OSError, psutil.Error, NotImplementedError):
                        net_info = []
                    last_network = started
                if started - last_ping >= 5:
                    target = self.ping_target
                    if target != previous_target:
                        history.clear()
                        previous_target = target
                    ping = NetworkMonitor.get_ping(target)
                    ping_at = time.monotonic()
                    history.append({"at": ping_at, "ms": ping.get("ms") if ping else None})
                    last_ping = started
                data.update(net_info=net_info, storage_percent=storage, ping=ping, ping_at=ping_at,
                            ping_target=previous_target, ping_history=list(history))
                with self._lock:
                    self._data = data
                self._stop.wait(max(0.05, 1 - (time.monotonic() - started)))
        finally:
            if self.nvml:
                self.nvml.nvmlShutdown()
