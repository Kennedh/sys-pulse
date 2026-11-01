import math

from modules.network import ping_statistics


RULES = {
    'cpu': ("CPU total", 90, "Confira o ranking de CPU e repita a tarefa para comparar a carga."),
    'core': ("Núcleo mais ocupado", 95, "Confira a carga por núcleo; CPU total baixa pode esconder trabalho concentrado."),
    'ram': ("Memória RAM", 90, "Compare memória disponível, processos e leituras de páginas; RAM ocupada inclui caches."),
    'gpu': ("GPU", 95, "Compare uso, temperatura e tarefa em execução. Uso alto em jogos pode ser esperado."),
    'vram': ("Memória da GPU", 90, "Compare alocação de VRAM com a tarefa; ocupação não comprova falta de memória."),
    'disk': ("Atividade de disco", 90, "Compare latência, fila e taxas do mesmo disco; o I/O do processo não identifica o disco físico."),
    'dpc': ("Tempo de CPU em DPC", 5, "Para atribuição a drivers, capture DPC/ISR com WPR/WPA ou LatencyMon."),
}


def valid(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


class Series:
    def __init__(self, percentiles=False):
        self.count = 0
        self.total = 0
        self.minimum = self.maximum = None
        self.values = [] if percentiles else None
        self.previous = None
        self.run = self.longest = self.high_seconds = self.covered_seconds = 0

    def add(self, value, at=None, threshold=None, max_gap=1, device=None):
        if not valid(value):
            self.previous = None
            self.run = 0
            return
        self.count += 1
        self.total += value
        self.minimum = value if self.minimum is None else min(value, self.minimum)
        self.maximum = value if self.maximum is None else max(value, self.maximum)
        if self.values is not None:
            self.values.append(value)
        high = threshold is not None and value >= threshold
        if self.previous is not None and valid(at):
            last_at, was_high, last_device = self.previous
            elapsed = at - last_at
            if 0 < elapsed <= max_gap and last_device == device:
                self.covered_seconds += elapsed
                if high and was_high:
                    self.run += elapsed
                    self.high_seconds += elapsed
                    self.longest = max(self.longest, self.run)
                else:
                    self.run = 0
            else:
                self.run = 0
        else:
            self.run = 0
        self.previous = (at, high, device) if valid(at) else None

    def result(self):
        ordered = sorted(self.values) if self.values else []
        return {"count": self.count, "min": self.minimum,
                "mean": self.total / self.count if self.count else None, "max": self.maximum,
                "p95": ordered[math.ceil(.95 * len(ordered)) - 1] if ordered else None,
                "high_seconds": self.high_seconds, "longest_high_s": self.longest,
                "covered_seconds": self.covered_seconds}


class Assessment:
    def __init__(self):
        self.resources = {key: Series(percentiles=True) for key in RULES}
        self.telemetry = {}
        self.sensor_batch = None
        self.truncated = False
        self.disk_delays = {}
        self.process_batch = None
        self.ping_batch = None
        self.pings = []

    def metric(self, key, name, unit, value):
        if not valid(value):
            return
        if key not in self.telemetry:
            if len(self.telemetry) >= 512:
                self.truncated = True
                return
            self.telemetry[key] = {"name": name, "unit": unit, "stat": Series()}
        self.telemetry[key]["stat"].add(value)

    def add(self, sample, values, devices):
        target = sample.get("target_interval_ms")
        gap = target / 500 if valid(target) and target > 0 else 1
        age = sample.get("sensor_age_ms")
        fresh = not valid(age) or 0 <= age <= 4000
        batch = sample.get("sensor_sample_monotonic")
        if not valid(batch) and valid(age):
            batch = round(sample["monotonic"] - age / 1000, 3)
        new_sensor = fresh and (batch is None or batch != self.sensor_batch)
        for key, (_, threshold, _) in RULES.items():
            value = sample.get("dpc_percent") if key == "dpc" else values.get(key)
            if key in ("gpu", "vram"):
                if not fresh:
                    self.resources[key].add(None)
                    continue
                if not new_sensor:
                    continue
                at = batch if valid(batch) else sample["monotonic"]
                max_gap = 2.5
            else:
                at, max_gap = sample["monotonic"], gap
            self.resources[key].add(value, at, threshold, max_gap, devices.get(key))
        ping_at = sample.get("ping_at")
        if valid(ping_at) and ping_at != self.ping_batch:
            ping = sample.get("ping") or {}
            self.pings.append({"ms": ping.get("ms") if valid(ping.get("ms")) else None})
            self.ping_batch = ping_at
        self.metric("commit", "Memória comprometida", "GiB", sample.get("commit_gb"))
        self.metric("commit_limit", "Limite de comprometimento", "GiB", sample.get("commit_limit_gb"))
        self.metric("ram_available", "RAM disponível", "GiB", sample.get("ram_available_gb"))
        self.metric("page_reads", "Leituras de páginas", "/s", sample.get("page_reads_s"))
        self.metric("dpc", "Tempo de CPU em DPC", "%", sample.get("dpc_percent"))
        self.metric("interrupt", "Tempo de CPU em interrupções", "%", sample.get("interrupt_percent"))
        self.metric("collector", "Custo da coleta", "ms", sample.get("collector_ms"))
        process_batch = sample.get("process_sample_monotonic")
        if valid(process_batch) and process_batch != self.process_batch:
            self.metric("process_collector", "Custo da varredura de processos", "ms", sample.get("process_collector_ms"))
            self.process_batch = process_batch
        for disk in sample.get("disks", []):
            name = str(disk.get("name") or "Disco")
            for operation in ("read", "write"):
                latency = disk.get(f"{operation}_ms")
                key = (name, operation)
                previous = self.disk_delays.get(key)
                if valid(latency) and latency >= 30 and (previous is None or latency > previous["latency"]):
                    if key in self.disk_delays or len(self.disk_delays) < 512:
                        self.disk_delays[key] = {"latency": latency, "timestamp": str(sample.get("timestamp", "")),
                                                "active": disk.get("active_percent"), "queue": disk.get("queue"),
                                                "iops": disk.get(f"{operation}_iops")}
                    else:
                        self.truncated = True
            for field, label, unit in (("active_percent", "Atividade", "%"), ("read_ms", "Latência de leitura", "ms/op"),
                                       ("write_ms", "Latência de escrita", "ms/op"), ("queue", "Fila", "requisições"),
                                       ("read_mbs", "Leitura", "MiB/s"), ("write_mbs", "Escrita", "MiB/s"),
                                       ("read_iops", "Operações de leitura", "/s"), ("write_iops", "Operações de escrita", "/s")):
                self.metric(f"disk:{name}:{field}", f"{name} · {label}", unit, disk.get(field))
        if new_sensor:
            self.sensor_batch = batch
            self.metric("temperature", "Temperatura CPU", "°C", sample.get("cpu_temperature"))
            self.metric("frequency", "Frequência CPU reportada", "MHz", sample.get("cpu_freq_mhz"))
            for gpu in sample.get("gpus", []):
                name, identity = str(gpu.get("name") or "GPU"), str(gpu.get("id") or gpu.get("name"))
                for field, label, unit in (("percent", "Uso", "%"), ("temperature", "Temperatura", "°C"),
                                           ("clock_mhz", "Clock", "MHz"), ("power_w", "Potência", "W"),
                                           ("memory_used_mb", "VRAM utilizada", "MiB")):
                    self.metric(f"gpu:{identity}:{field}", f"{name} · {label}", unit, gpu.get(field))
            units = {"temperature": "°C", "load": "%", "clock": "MHz", "power": "W", "fan": "RPM",
                     "voltage": "V", "current": "A", "data": "GiB", "smalldata": "MiB"}
            for sensor in sample.get("sensors", []):
                kind = str(sensor.get("type", "")).lower()
                if kind in units:
                    self.metric(f"sensor:{sensor.get('id')}", f"{sensor.get('hardware')} · {sensor.get('name')}",
                                units[kind], sensor.get("value"))

    def result(self):
        resources, findings = [], []
        for key, (name, threshold, action) in RULES.items():
            stat = self.resources[key].result()
            resources.append({"key": key, "name": name, "threshold": threshold, **stat})
            if stat["max"] is not None and stat["max"] >= threshold:
                sustained = stat["longest_high_s"] >= 5
                findings.append({"resource": key, "title": f"{name}: " + ("carga alta persistente observada" if sustained else "pico ou sequência curta"),
                                 "evidence": f"Pico {stat['max']:.1f}% · P95 {stat['p95']:.1f}% · maior sequência {stat['longest_high_s']:.1f} s.",
                                 "action": action})
        for (name, operation), observation in self.disk_delays.items():
            label = "leitura" if operation == "read" else "escrita"
            detail = f"{name}: maior latência média de {label} {observation['latency']:.1f} ms/op às {observation['timestamp']}."
            for key, title, unit in (("active", "atividade", "%"), ("queue", "fila", " requisições"),
                                     ("iops", "operações", "/s")):
                if valid(observation[key]) and observation[key] >= 0:
                    detail += f" Na mesma amostra, {title}: {observation[key]:.1f}{unit}."
            findings.append({"resource": "disk_latency", "title": f"{name}: latência de {label} elevada",
                             "evidence": detail,
                             "action": "Compare este horário com a marcação e repita a tarefa. Confira o mesmo disco no WPA; "
                                       "30 ms/op é um critério de triagem, não limite de defeito. "
                                       "A gravação do ETL também pode disputar esse disco."})
        return {"resources": resources, "findings": findings, "truncated": self.truncated, "network": ping_statistics(self.pings),
                "telemetry": [{"key": key, "name": row["name"], "unit": row["unit"], **row["stat"].result()}
                              for key, row in self.telemetry.items()],
                "method": "P95 por posição mais próxima (ceil), sem interpolação. Tempo alto soma intervalos entre duas leituras altas "
                          "consecutivas do mesmo dispositivo; lacunas, troca de dispositivo e N/D interrompem a sequência. "
                          "Sensores em cache contam uma vez. Persistência de 5 s é critério de triagem, não limite de defeito. "
                          "Máximos de núcleo/disco/GPU podem alternar de dispositivo; P95 do agregado não representa um dispositivo fixo."}
