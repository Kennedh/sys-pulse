
from modules.assessment import Series, valid


METRICS = {
    "cpu": ("CPU total", "%"), "core": ("Núcleo mais ocupado", "%"), "ram": ("RAM ocupada", "%"),
    "gpu": ("GPU", "%"), "vram": ("VRAM", "%"), "disk": ("Disco ativo", "%"),
    "cpu_temperature": ("Temperatura CPU", "°C"), "cpu_freq_mhz": ("Frequência CPU reportada", "MHz"),
    "ram_available_gb": ("RAM disponível", "GiB"), "disk_latency": ("Latência de disco", "ms/op"),
}


class SessionInsights:
    def __init__(self, target_pid=None, stress=None):
        self.target_pid = target_pid
        self.stress = stress or {}
        self.phases = {}
        self.bins = {}
        self.sensor_batch = None
        self.process_batch = None
        self.first = None
        self.last = None
        self.previous = None
        self.gaps = 0

    def add(self, sample, values, processes):
        at = sample["monotonic"]
        self.first = at if self.first is None else self.first
        self.last = at
        target = sample.get("target_interval_ms")
        tolerance = max(1, target / 500) if valid(target) and target > 0 else 1
        if self.previous is not None and at - self.previous > tolerance:
            self.gaps += 1
        self.previous = at
        key = int(at // 60)
        if key not in self.bins:
            if len(self.bins) >= 256:
                return
            self.bins[key] = {"start": at, "end": at, "timestamp": sample.get("timestamp", ""),
                              "samples": 0, "metrics": {}, "target": {}, "target_identity": None}
        window = self.bins[key]
        window["end"], window["samples"] = at, window["samples"] + 1

        phase = None
        start, end = self.stress.get("started_monotonic"), self.stress.get("ended_monotonic")
        if valid(start) and valid(end) and start <= end:
            name = "Antes da carga" if at < start else "Recuperação" if at > end else "Durante a carga"
            phase = self.phases.setdefault(name, {"start": at, "end": at, "samples": 0, "metrics": {}})
            phase["end"], phase["samples"] = at, phase["samples"] + 1

        def add(field, value):
            if valid(value):
                window["metrics"].setdefault(field, Series(percentiles=True)).add(value)
                if phase is not None:
                    phase["metrics"].setdefault(field, Series()).add(value)

        for field in ("cpu", "core", "ram", "disk"):
            add(field, values.get(field))
        latencies = [disk.get(field) for disk in sample.get("disks", []) for field in ("read_ms", "write_ms")
                     if valid(disk.get(field))]
        add("disk_latency", max(latencies) if latencies else None)
        add("ram_available_gb", sample.get("ram_available_gb"))
        batch = sample.get("sensor_sample_monotonic")
        age = sample.get("sensor_age_ms")
        fresh = not valid(age) or 0 <= age <= 4000
        if fresh and (batch is None or batch != self.sensor_batch):
            self.sensor_batch = batch
            for field in ("gpu", "vram"):
                add(field, values.get(field))
            for field in ("cpu_temperature", "cpu_freq_mhz"):
                add(field, sample.get(field))
        process_batch = sample.get("process_sample_monotonic", at)
        if process_batch != self.process_batch:
            self.process_batch = process_batch
            target = next((row for row in processes if row["pid"] == self.target_pid), None)
            if target:
                identity = (target["pid"], target.get("created"))
                if window["target_identity"] in (None, identity):
                    window["target_identity"] = identity
                    window["target_name"] = target.get("name")
                    for field in ("cpu_percent", "rss_mb", "io_total_mbs", "gpu_percent"):
                        if valid(target.get(field)):
                            window["target"].setdefault(field, Series()).add(target[field])

    def result(self, frames=None):
        periods = []
        frame_periods = {}
        if frames and frames.get("series"):
            selected = frames["series"][0]
            if selected["alignment"].startswith("QPC"):
                frame_periods = {row["minute"]: row for row in selected.get("periods", [])}
        for minute, source in sorted(self.bins.items()):
            row = {key: source[key] for key in ("start", "end", "timestamp", "samples")}
            row["metrics"] = {key: stat.result() for key, stat in source["metrics"].items()}
            row["target"] = {key: stat.result() for key, stat in source["target"].items()}
            row["target_identity"] = source["target_identity"]
            row["frames"] = frame_periods.get(minute)
            row["offset_s"] = source["start"] - self.first
            periods.append(row)
        trends = []
        if len(periods) >= 3:
            width = max(1, len(periods) // 3)
            for key, (label, unit) in METRICS.items():
                def average(rows):
                    items = [r["metrics"][key] for r in rows if key in r["metrics"]]
                    count = sum(v["count"] for v in items)
                    return sum(v["mean"] * v["count"] for v in items) / count if count else None
                before, after = average(periods[:width]), average(periods[-width:])
                if before is not None and after is not None:
                    trends.append({"key": key, "name": label, "unit": unit, "early": before,
                                   "late": after, "delta": after - before})
        target_growth = None
        target_rows = [row for row in periods if row["target"].get("rss_mb")]
        if len(target_rows) >= 2 and target_rows[0]["target_identity"] == target_rows[-1]["target_identity"]:
            early, late = target_rows[0]["target"]["rss_mb"]["mean"], target_rows[-1]["target"]["rss_mb"]["mean"]
            target_growth = {"early_mb": early, "late_mb": late, "delta_mb": late - early,
                             "meaning": "Variação do RSS observado; crescimento não comprova vazamento de memória."}
        def severity(row):
            metrics = row["metrics"]
            frame = row.get("frames") or {}
            return (frame.get("over_50_ms", 0),
                    sum((metrics.get(key, {}).get("mean") or 0) >= limit for key, limit in
                        (("cpu", 90), ("core", 95), ("ram", 90), ("gpu", 95), ("disk", 90))),
                    (metrics.get("disk_latency", {}).get("max") or 0)
                    if (metrics.get("disk_latency", {}).get("max") or 0) >= 30 else 0)
        worst = sorted(periods, key=severity, reverse=True)[:5]
        worst = [row for row in worst if any(severity(row))]
        phases = [{"name": name, "duration_s": data["end"] - data["start"], "samples": data["samples"],
                   "metrics": {key: stat.result() for key, stat in data["metrics"].items()}}
                  for name, data in self.phases.items()]
        return {"phases": phases, "periods": periods, "trends": trends, "critical_periods": worst, "target_memory": target_growth,
                "duration_s": (self.last - self.first) if self.first is not None else 0, "gaps": self.gaps,
                "method": "Períodos de até um minuto no relógio monotônico. Comparação dos terços inicial e final, "
                          "ponderada pelas leituras distintas; intervalos sem dados não são preenchidos. "
                          "Uso alto pode ser esperado durante jogos e estresse. Queda de clock reportado não confirma throttling."}


def insight_text(result):
    lines = ["EVOLUÇÃO DA SESSÃO", result.get("method", ""), ""]
    for row in result.get("critical_periods", []):
        fields = []
        for key, (label, unit) in METRICS.items():
            stat = row["metrics"].get(key)
            if stat and key in ("cpu", "core", "ram", "gpu", "disk", "disk_latency"):
                fields.append(f"{label}: média {stat['mean']:.1f} {unit}, pico {stat['max']:.1f} {unit}")
        frames = row.get("frames")
        if frames:
            fields.append(f"Frametime P99 {frames['p99_ms']:.1f} ms; {frames['over_50_ms']} intervalos >50 ms")
        lines.append(f"{row['offset_s'] / 60:.1f} min · " + " | ".join(fields))
    if not result.get("critical_periods"):
        lines.append("Sem período acima dos critérios disponíveis; consulte a evolução e a cobertura dos sensores.")
    lines += ["", "INÍCIO E FIM"]
    for trend in result.get("trends", []):
        lines.append(f"{trend['name']}: {trend['early']:.1f} → {trend['late']:.1f} {trend['unit']} "
                     f"(variação {trend['delta']:+.1f} {trend['unit']}).")
    growth = result.get("target_memory")
    if growth:
        lines.append(f"RSS do aplicativo escolhido: {growth['early_mb']:.1f} → {growth['late_mb']:.1f} MiB. " + growth["meaning"])
    if result.get("phases"):
        lines += ["", "FASES DO TESTE"]
        for phase in result["phases"]:
            fields = [f"{METRICS[key][0]} {stat['mean']:.1f} {METRICS[key][1]}"
                      for key, stat in phase["metrics"].items()
                      if key in ("cpu", "gpu", "ram", "cpu_temperature", "cpu_freq_mhz")]
            lines.append(f"{phase['name']} · {phase['samples']} amostras · " + " | ".join(fields))
    return "\n".join(lines)
