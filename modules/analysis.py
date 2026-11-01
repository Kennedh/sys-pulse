import bisect
import csv
import gzip
import io
import json
import math
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from modules.advanced_analysis import explain_capture, readable_report
from modules.assessment import Assessment
from modules.inspection import inspection_text
from modules.incidents import compare_markers
from modules.frametimes import analyze_frames
from modules.session_insights import SessionInsights, insight_text
from modules.version import VERSION


RESOURCE_SPECS = (
    ("cpu", "CPU total", 90, "cpu_percent"),
    ("core", "Núcleo mais ocupado", 95, "cpu_percent"),
    ("ram", "Memória RAM", 90, "rss_mb"),
    ("gpu", "GPU mais ocupada", 95, "gpu_percent"),
    ("vram", "Memória da GPU", 90, None),
    ("disk", "Disco mais ativo", 90, "io_total_mbs"),
    ("dpc", "Tempo de CPU em DPC", 5, None),
)
PROCESS_FIELDS = ("cpu_percent", "rss_mb", "ram_percent", "io_read_mbs", "io_write_mbs",
                  "io_total_mbs", "gpu_percent")
LIMITATIONS = [
    "Utilização elevada é um indício de carga, não comprovação da causa da travada ou de defeito físico.",
    "Percentuais de CPU, RAM, GPU e disco descrevem recursos diferentes; a maior média não é um diagnóstico de gargalo.",
    "Processos são atualizados a cada ~2 s. O processo observado perto de um pico pode não ter causado esse pico.",
    "Rankings usam apenas os processos selecionados e acessíveis. Médias são das leituras observadas, sem preencher ausências com zero.",
    "I/O por processo não identifica um disco físico. No Windows pode incluir operações de dispositivos/rede; caches também interferem.",
    "GPU por processo representa seu engine mais ocupado e pode diferir do uso global da GPU. Não há atribuição de VRAM por processo.",
    "Amostragem não mede FPS/frametime, latência DPC/ISR nem integridade física. Picos curtos podem não ser registrados.",
]


class AnalysisError(ValueError):
    pass


class AnalysisCancelled(Exception):
    pass


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def clean(value):
    return float(value) if number(value) and value >= 0 else None


def text_value(value, limit=300):
    return str(value or "")[:limit]


def display_time(value):
    try:
        return datetime.fromisoformat(value).strftime("%H:%M:%S.%f")[:-3]
    except (ValueError, TypeError):
        return text_value(value, 32) or "N/D"


def fmt(value, suffix="", digits=1):
    return f"{value:.{digits}f}{suffix}" if number(value) else "N/D"


def process_rows(sample):
    if not number(sample.get("process_age_ms")) or not 0 <= sample["process_age_ms"] <= 4000:
        return []
    batch = sample.get("process_sample_monotonic")
    if number(batch) and batch > sample["monotonic"]:
        return []
    result = []
    for p in sample.get("processes", []):
        if not isinstance(p, dict) or not isinstance(p.get("pid"), int):
            continue
        row = {key: clean(p.get(key)) for key in PROCESS_FIELDS}
        row.update(pid=p["pid"], name=text_value(p.get("name"), 120) or "?", created=clean(p.get("created")))
        result.append(row)
    return result


def resource_values(sample):
    values = {"cpu": clean(sample.get("cpu_percent")), "core": clean(sample.get("cpu_max_core")),
              "ram": clean(sample.get("ram_percent")), "gpu": None, "vram": None, "disk": None,
              "dpc": clean(sample.get("dpc_percent"))}
    devices = {"cpu": "Todos os núcleos", "core": "Núcleo lógico", "ram": "RAM do sistema"}
    cores = sample.get("cpu_cores", [])
    valid_cores = [(i, v) for i, v in enumerate(cores) if clean(v) is not None]
    if valid_cores:
        devices["core"] = f"CPU lógica {max(valid_cores, key=lambda item: item[1])[0]}"
    sensor_age = sample.get("sensor_age_ms")
    gpus = [] if number(sensor_age) and not 0 <= sensor_age <= 4000 else sample.get("gpus", [])
    for gpu in gpus:
        load = clean(gpu.get("percent"))
        used, total = clean(gpu.get("memory_used_mb")), clean(gpu.get("memory_total_mb"))
        for key, value in (("gpu", load), ("vram", used / total * 100 if used is not None and total else None)):
            if value is not None and (values[key] is None or value > values[key]):
                values[key], devices[key] = value, text_value(gpu.get("name"))
    for disk in sample.get("disks", []):
        value = clean(disk.get("active_percent"))
        if value is not None and (values["disk"] is None or value > values["disk"]):
            values["disk"], devices["disk"] = value, text_value(disk.get("name"))
    return values, devices


class Stat:
    def __init__(self):
        self.count = self.high_count = 0
        self.total = 0.0
        self.peak = None
        self.at = None

    def add(self, value, at=None, threshold=None):
        value = clean(value)
        if value is None:
            return False
        self.count += 1
        self.total += value
        if threshold is not None and value >= threshold:
            self.high_count += 1
        if self.peak is None or value > self.peak:
            self.peak, self.at = value, at
            return True
        return False

    def result(self):
        return {"count": self.count, "mean": self.total / self.count if self.count else None,
                "peak": self.peak, "peak_at": self.at, "high_count": self.high_count}


class Accumulator:
    def __init__(self, chart=False, process_context=True):
        self.assessment = Assessment() if chart else None
        self.process_context = process_context
        self.stats = {key: Stat() for key, *_ in RESOURCE_SPECS}
        self.peak_details = {}
        self.processes = {}
        self.process_batch = None
        self.count = self.late = self.process_batches = 0
        self.first = self.last = self.first_at = self.last_at = None
        self.points = [] if chart else None
        self.min_available = None
        self.collection_gaps = 0
        self.max_gap_ms = None
        self.target_interval_ms = None
        self.collector = Stat()
        self.expensive_samples = 0
        self.process_error_samples = 0
        self.sensor_batch = None

    def add(self, sample):
        at, stamp = sample["monotonic"], sample["timestamp"]
        self.count += 1
        if self.first is None:
            self.first, self.first_at = at, stamp
        target = clean(sample.get("target_interval_ms"))
        self.target_interval_ms = target
        if self.last is not None:
            gap_ms = (at - self.last) * 1000
            self.max_gap_ms = max(self.max_gap_ms or 0, gap_ms)
            if target and gap_ms > 2 * target:
                self.collection_gaps += 1
        self.last, self.last_at = at, stamp
        if sample.get("process_status"):
            self.process_error_samples += 1
        cost = clean(sample.get("collector_ms"))
        self.collector.add(cost, stamp)
        if cost is not None and target and cost >= target:
            self.expensive_samples += 1
        values, devices = resource_values(sample)
        if self.assessment is not None:
            self.assessment.add(sample, values, devices)
        processes = process_rows(sample) if self.process_context else []
        available = clean(sample.get("ram_available_gb"))
        if available is not None:
            self.min_available = min(available, self.min_available if self.min_available is not None else available)
        sensor_batch = sample.get("sensor_sample_monotonic")
        age = sample.get("sensor_age_ms")
        if not number(sensor_batch) and number(age):
            sensor_batch = round(at - age / 1000, 3)
        for key, _, threshold, process_field in RESOURCE_SPECS:
            if key in ("gpu", "vram") and number(sensor_batch) and sensor_batch == self.sensor_batch:
                continue
            if self.stats[key].add(values[key], stamp, threshold):
                candidates = [p for p in processes if process_field and clean(p.get(process_field)) is not None
                              and p[process_field] > 0]
                leader = max(candidates, key=lambda p: p[process_field]) if candidates else None
                self.peak_details[key] = {"device": devices.get(key), "process": leader,
                                          "process_age_ms": clean(sample.get("process_age_ms"))}
        self.sensor_batch = sensor_batch
        interval, target = clean(sample.get("interval_ms")), clean(sample.get("target_interval_ms"))
        if interval is not None and target and interval > 2 * target:
            self.late += 1
        if self.points is not None:
            self.points.append({"t": at - self.first, **values})
        batch = sample.get("process_sample_monotonic")
        if not number(batch) and number(sample.get("process_age_ms")):
            batch = round(at - sample["process_age_ms"] / 1000, 3)
        if processes and batch != self.process_batch:
            self.process_batch = batch
            self.process_batches += 1
            for p in processes:
                key = (p["pid"], p["name"], p["created"])
                if key not in self.processes:
                    self.processes[key] = {"pid": p["pid"], "name": p["name"], "created": p["created"],
                                           "stats": {field: Stat() for field in PROCESS_FIELDS}}
                for field in PROCESS_FIELDS:
                    self.processes[key]["stats"][field].add(p[field], stamp)

    def finish(self):
        resources = [{"key": key, "name": label, "threshold": threshold,
                      **self.stats[key].result(), **self.peak_details.get(key, {})}
                     for key, label, threshold, _ in RESOURCE_SPECS]
        candidates = [r for r in resources if r["key"] != "core" and r["mean"] is not None]
        dominant = max(candidates, key=lambda r: r["mean"]) if candidates else None
        processes = [{"pid": p["pid"], "name": p["name"], "created": p["created"],
                      "metrics": {key: value.result() for key, value in p["stats"].items()}}
                     for p in self.processes.values()]
        processes.sort(key=lambda p: p["metrics"]["cpu_percent"]["peak"] or 0, reverse=True)
        return {"samples": self.count, "duration_s": self.last - self.first if self.count else 0,
                "start_monotonic": self.first,
                "start": self.first_at, "end": self.last_at, "late_samples": self.late,
                "min_ram_available_gb": self.min_available, "process_batches": self.process_batches,
                "dominant": dominant, "resources": resources, "processes": processes,
                "chart": reduce_chart(self.points or []), "target_interval_ms": self.target_interval_ms,
                "collection": {"gaps": self.collection_gaps, "max_gap_ms": self.max_gap_ms,
                               "collector": self.collector.result(), "expensive_samples": self.expensive_samples,
                               "process_error_samples": self.process_error_samples},
                "assessment": self.assessment.result() if self.assessment is not None else {}}


def reduce_chart(points, limit=1000):
    if len(points) <= limit:
        return points
    width = math.ceil(len(points) / limit)
    result = []
    for start in range(0, len(points), width):
        bucket = points[start:start + width]
        row = {"t": bucket[-1]["t"]}
        for key, *_ in RESOURCE_SPECS:
            row[key] = max((r[key] for r in bucket if r.get(key) is not None), default=None)
        result.append(row)
    return result


@contextmanager
def session_files(source):
    path = Path(source)
    names = ("amostras.jsonl", "amostras.jsonl.gz")
    if path.suffix.lower() == ".etl":
        raise AnalysisError("Abra o ETL no diagnóstico detalhado.")
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            matches = [n for n in archive.namelist() if n.replace("\\\\", "/").split("/")[-1] in names]
            if len(matches) != 1:
                raise AnalysisError("O ZIP precisa conter exatamente uma sessão com amostras.jsonl ou amostras.jsonl.gz.")
            selected = matches[0]
            root = selected.rsplit("/", 1)[0] + "/" if "/" in selected else ""

            def opener(name):
                target = selected if name == "amostras.jsonl" else root + name
                if name == "frametimes.csv" and target not in archive.namelist():
                    target += ".gz"
                try:
                    info = archive.getinfo(target)
                except KeyError:
                    raise FileNotFoundError(name) from None
                if info.file_size > (512 * 1024 ** 2 if name in ("amostras.jsonl", "frametimes.csv") else 4 * 1024 ** 2):
                    raise AnalysisError(f"{name} excede o limite de leitura segura.")
                file = archive.open(target)
                return gzip.GzipFile(fileobj=file) if target.endswith((".jsonl.gz", ".csv.gz")) else file
            yield opener
    else:
        root = path if path.is_dir() else path.parent
        if not path.is_dir() and path.name not in (*names, "sessao.json"):
            raise AnalysisError("Selecione uma sessão, ZIP, amostras.jsonl ou amostras.jsonl.gz.")

        def opener(name):
            target = root / name
            if not target.exists() and name in ("amostras.jsonl", "frametimes.csv"):
                target = root / (name + ".gz")
            if target.stat().st_size > (512 * 1024 ** 2 if name in ("amostras.jsonl", "frametimes.csv") else 4 * 1024 ** 2):
                raise AnalysisError(f"{name} excede o limite de leitura segura.")
            return gzip.open(target, "rb") if target.name.endswith((".jsonl.gz", ".csv.gz")) else target.open("rb")
        yield opener


def analyze_session(source, cancel=None):
    warnings, markers, metadata = [], [], {}
    inventory = None
    frames = None
    all_data = Accumulator(chart=True)
    near_markers, outside_markers = Accumulator(process_context=False), Accumulator(process_context=False)
    with session_files(source) as open_file:
        try:
            with open_file("sessao.json") as file:
                metadata = json.load(file)
            if not isinstance(metadata, dict):
                metadata = {}
                warnings.append("Metadados inválidos; análise baseada nas amostras.")
        except FileNotFoundError:
            warnings.append("Sessão sem metadados; término e perdas de gravação desconhecidos.")
        except (ValueError, UnicodeError):
            warnings.append("Metadados ilegíveis; análise baseada nas amostras.")
        metadata = {key: value for key, value in metadata.items()
                    if key in ("schema_version", "app_version", "demo", "started", "ended", "system", "python",
                               "interval_ms", "count", "dropped", "reason", "max_hours", "max_raw_bytes", "window_seconds",
                               "compressed", "duration_s", "symptom", "target_pid", "frame_error")
                    and (isinstance(value, (str, bool)) or number(value) or value is None)}
        stress = None
        try:
            with open_file("stress.json") as file:
                candidate = json.load(file)
            if (isinstance(candidate, dict) and candidate.get("kind") in ("cpu", "gpu", "memory")
                    and candidate.get("state") in ("completed", "stopped", "failed")
                    and number(candidate.get("elapsed_s"))):
                stress = candidate
            else:
                warnings.append("Resultado de estresse inválido; análise de recursos preservada.")
        except (FileNotFoundError, ValueError, UnicodeError):
            pass
        evolution = SessionInsights(metadata.get("target_pid"), stress)
        try:
            with open_file("inventario.json") as file:
                inventory = json.load(file)
            json.dumps(inventory, allow_nan=False)
            if not isinstance(inventory, dict) or not isinstance(inventory.get("sections"), dict):
                raise ValueError()
            for section in inventory["sections"].values():
                if not isinstance(section, dict) or not isinstance(section.get("rows", []), list):
                    raise ValueError()
                if any(not isinstance(row, dict) for row in section.get("rows", [])):
                    raise ValueError()
            for disk in inventory["sections"].get("storage", {}).get("rows", []):
                if disk.get("Reliability") is not None and not isinstance(disk["Reliability"], dict):
                    raise ValueError()
        except FileNotFoundError:
            warnings.append("Sem inventário de drivers e saúde nesta sessão.")
        except (ValueError, UnicodeError):
            inventory = None
            warnings.append("Inventário ilegível; análise de recursos preservada.")
        try:
            with open_file("marcacoes.csv") as file:
                for row in csv.DictReader(io.TextIOWrapper(file, encoding="utf-8-sig")):
                    try:
                        at = float(row["monotonic"])
                        if not number(at):
                            raise ValueError()
                        markers.append({"id": text_value(row.get("id"), 20), "monotonic": at,
                                        "timestamp": text_value(row.get("timestamp")), "note": text_value(row.get("note"), 500)})
                    except (ValueError, KeyError, TypeError):
                        warnings.append("Uma marcação inválida foi ignorada.")
                    if len(markers) > 2000:
                        raise AnalysisError("A sessão excede o limite de 2.000 marcações.")
        except FileNotFoundError:
            pass
        try:
            with open_file("frametimes.csv") as file:
                frames = analyze_frames(io.TextIOWrapper(file, encoding="utf-8-sig"), cancel or (lambda: False),
                                        metadata.get("target_pid"))
            if not frames["series"]:
                warnings.append("Nenhum frametime válido nesta sessão. Confira o suporte e a permissão do PresentMon.")
        except FileNotFoundError:
            pass
        except (ValueError, csv.Error, UnicodeError) as error:
            warnings.append(f"Frametimes indisponíveis: {error}")
        except InterruptedError:
            raise AnalysisCancelled() from None
        markers.sort(key=lambda r: r["monotonic"])
        centers = [r["monotonic"] for r in markers]
        windows = [Accumulator() for _ in markers]
        before = [Accumulator() for _ in markers]
        after = [Accumulator() for _ in markers]
        frame_windows = []
        if frames and frames["series"]:
            selected = frames["series"][0]
            if selected["alignment"].startswith("QPC"):
                frame_windows = [(event, Accumulator()) for event in selected["events"]
                                 if number(event.get("monotonic"))]
        invalid = 0
        try:
            with open_file("amostras.jsonl") as file:
                line_number = total_bytes = 0
                while True:
                    if cancel and cancel():
                        raise AnalysisCancelled()
                    try:
                        line = file.readline(1024 * 1024 + 1)
                    except (EOFError, gzip.BadGzipFile) as error:
                        warnings.append(f"Gravação comprimida incompleta; linhas válidas preservadas ({type(error).__name__}).")
                        break
                    if not line:
                        break
                    line_number += 1
                    total_bytes += len(line)
                    if total_bytes > 512 * 1024 ** 2:
                        raise AnalysisError("Sessão descomprimida excede 512 MiB.")
                    if len(line) > 1024 * 1024 or line_number > 120000:
                        raise AnalysisError("Sessão excede os limites de análise (120.000 linhas; 1 MiB por linha).")
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                        if not isinstance(row, dict) or not number(row.get("monotonic")):
                            raise ValueError()
                        if all_data.last is not None and row["monotonic"] <= all_data.last:
                            raise ValueError()
                        for key in ("gpus", "disks", "processes", "sensors"):
                            if not isinstance(row.get(key, []), list) or any(not isinstance(p, dict) for p in row.get(key, [])):
                                raise ValueError()
                        if not isinstance(row.get("cpu_cores", []), list):
                            raise ValueError()
                        row["timestamp"] = text_value(row.get("timestamp"))
                    except (ValueError, TypeError, UnicodeError):
                        invalid += 1
                        continue
                    all_data.add(row)
                    evolution.add(row, resource_values(row)[0], process_rows(row))
                    for frame, window in frame_windows:
                        if abs(row["monotonic"] - frame["monotonic"]) <= 1:
                            window.add(row)
                    left = bisect.bisect_left(centers, row["monotonic"] - 5)
                    right = bisect.bisect_right(centers, row["monotonic"] + 5)
                    (near_markers if left < right else outside_markers).add(row)
                    for i in range(left, right):
                        windows[i].add(row)
                        (before[i] if row["monotonic"] < centers[i] else after[i]).add(row)
        except FileNotFoundError as error:
            raise AnalysisError("Não foi encontrado amostras.jsonl na sessão selecionada.") from error

    if metadata.get("frame_error"):
        warnings.append(metadata["frame_error"])
    if invalid:
        warnings.append(f"{invalid} linha(s) inválida(s), repetida(s) ou fora de ordem foram ignoradas; análise parcial.")
    if not all_data.count:
        raise AnalysisError("Esta sessão não contém amostras válidas para analisar.")
    if not metadata.get("ended"):
        warnings.append("Sem registro de encerramento: sessão antiga, ainda em gravação ou incompleta.")
    dropped = metadata.get("dropped")
    if number(dropped) and dropped > 0:
        warnings.append(f"O gravador informou {dropped} amostras perdidas.")
    if all_data.late:
        warnings.append(f"{all_data.late} amostra(s) chegaram com intervalo maior que 2× o alvo. Isso não mede frametime.")
    result = all_data.finish()
    collection = result["collection"]
    if collection["gaps"]:
        warnings.append(f"{collection['gaps']} lacuna(s) entre amostras válidas; maior intervalo {collection['max_gap_ms']:.0f} ms. "
                        "Pausas dentro dessas lacunas não podem ser reconstruídas.")
    if collection["expensive_samples"]:
        warnings.append(f"Em {collection['expensive_samples']} amostra(s), a coleta consumiu pelo menos o intervalo alvo. "
                        "O próprio monitor pode interferir na medição; compare uma captura com intervalo maior.")
    if collection["process_error_samples"]:
        warnings.append(f"Coleta de processos informou erro em {collection['process_error_samples']} amostra(s); "
                        "rankings e contexto de processos podem estar incompletos.")
    if result["assessment"].get("truncated"):
        warnings.append("Limite de 512 séries de telemetria atingido; estatísticas por dispositivo parciais.")
    events = []
    for marker, window, pre, post in zip(markers, windows, before, after):
        coverage = [window.first - marker["monotonic"], window.last - marker["monotonic"]] if window.count else [None, None]
        events.append({"marker": marker, "coverage": coverage, "analysis": window.finish(),
                       "before": pre.finish()["resources"], "after": post.finish()["resources"]})
    for frame, window in frame_windows:
        context = window.finish()
        frame["resource_context"] = {"samples": context["samples"], "resources": context["resources"],
                                     "collection": context["collection"]}
    symptoms = compare_markers(events, near_markers.finish(), outside_markers.finish())
    analysis = {"analysis_version": 4, "symptoms": symptoms, "inventory": inventory, "source": str(source), "metadata": metadata,
                "summary": result, "events": events, "warnings": warnings, "frametimes": frames,
                "limitations": LIMITATIONS, "invalid_lines": invalid, "evolution": evolution.result(frames)}
    if stress:
        analysis["stress"] = stress
    analysis["explanation"] = explain_capture({}, analysis)
    return analysis


def ranked_processes(summary, field="cpu_percent", statistic="peak"):
    rows = [p for p in summary["processes"] if p["metrics"][field][statistic] is not None]
    return sorted(rows, key=lambda p: p["metrics"][field][statistic], reverse=True)


def report_text(result):
    summary = result["summary"]
    lines = [f"SYS-PULSE {VERSION} — ANÁLISE DE PERFORMANCE", "", f"Sessão: {result['source']}",
             f"Período: {summary['start']} a {summary['end']}",
             f"Duração: {summary['duration_s']:.1f} s | Amostras: {summary['samples']}", ""]
    if result.get("explanation"):
        lines += [readable_report(result, "ENTENDA A CAPTURA"), "", "DETALHAMENTO TÉCNICO"]
    lines += [insight_text(result.get("evolution", {})), ""]
    stress = result.get("stress") or {}
    if stress:
        lines += ["TESTE DE ESTRESSE", f"Componente: {stress.get('kind')} | estado: {stress.get('state')}",
                  str(stress.get("method") or ""), str(stress.get("reason") or "")]
        if stress.get("kind") == "gpu":
            lines += [f"Adaptador: {stress.get('renderer', 'N/D')} | resolução real: {stress.get('render_resolution', 'N/D')}",
                      f"FPS: {fmt(stress.get('fps'))} | frametime P95 {fmt(stress.get('frametime_p95_ms'), ' ms')} | "
                      f"P99 {fmt(stress.get('frametime_p99_ms'), ' ms')} | maior {fmt(stress.get('frametime_max_ms'), ' ms')}",
                      f"Submissão CPU média: {fmt(stress.get('cpu_submit_mean_ms'), ' ms')} (inclui espera da API; não é tempo de GPU)",
                      str(stress.get("frametime_method") or "")]
        else:
            lines += [f"Verificações: {stress.get('checks', 'N/D')} | divergências: {stress.get('errors', 'N/D')}"]
        lines.append("")
    dominant = summary["dominant"]
    if dominant:
        lines.append(f"Maior utilização média (%): {dominant['name']} — {dominant['mean']:.1f}%")
    lines += ["Médias aritméticas das amostras disponíveis; recursos não equivalem entre si.", "", "RECURSOS"]
    for row in summary["resources"]:
        lines.append(f"{row['name']}: média {fmt(row['mean'], '%')} | pico {fmt(row['peak'], '%')} às {display_time(row['peak_at'])} | "
                     f"leituras >= {row['threshold']}%: {row['high_count']}/{row['count']}")
        p = row.get("process")
        if p:
            lines.append(f"  Processo observado perto do pico: {p['name']} (PID {p['pid']}); idade da leitura {fmt(row.get('process_age_ms'), ' ms')}.")
    for field, title in (("cpu_percent", "CPU (%)"), ("rss_mb", "RAM (MiB)"),
                         ("io_total_mbs", "I/O (MiB/s)"), ("gpu_percent", "GPU / engine (%)")):
        lines += ["", f"PROCESSOS — {title}"]
        rows = ranked_processes(summary, field)[:15]
        if not rows:
            lines.append("N/D — esta captura não contém leituras disponíveis.")
        for p in rows:
            stat = p["metrics"][field]
            lines.append(f"{p['name']} | PID {p['pid']} | média observada {fmt(stat['mean'])} | pico {fmt(stat['peak'])} | "
                         f"às {display_time(stat['peak_at'])} | {stat['count']} leituras distintas")
    assessment = summary.get("assessment", {})
    lines += ["", "TRIAGEM DE RECURSOS", assessment.get("method", "")]
    for finding in assessment.get("findings", []):
        lines += [finding["title"], finding["evidence"], finding["action"]]
    if not assessment.get("findings"):
        lines.append("Sem alerta nos critérios disponíveis; isso não descarta problemas não capturados.")
    network = assessment.get("network", {})
    if network.get("attempts"):
        lines += ["", "CONEXÃO · TENTATIVAS ICMP",
                  f"{network['replies']}/{network['attempts']} respostas · {network['timeouts']} sem resposta.",
                  f"RTT médio {fmt(network.get('mean_ms'), ' ms')} · maior {fmt(network.get('max_ms'), ' ms')} · "
                  f"variação média entre respostas {fmt(network.get('variation_ms'), ' ms')}.",
                  "Timeout pode ser filtragem ICMP; este teste não mede a conexão específica de um aplicativo."]
    lines += ["", "ESTATÍSTICAS POR DISPOSITIVO"]
    for row in assessment.get("telemetry", []):
        lines.append(f"{row['name']}: mín {fmt(row['min'])} | média {fmt(row['mean'])} | máx {fmt(row['max'])} {row['unit']} | {row['count']} leituras")
    lines += ["", inspection_text(result.get("inventory")), "", "MARCAÇÕES"]
    for event in result["events"]:
        marker = event["marker"]
        lines.append(f"#{marker['id']} {marker['timestamp']} — {marker['note']} | cobertura {event['coverage']} s")
        for pre, post in zip(event["before"], event["after"]):
            lines.append(f"  {pre['name']}: pico antes {fmt(pre['peak'], '%')} / depois {fmt(post['peak'], '%')}")
    lines += ["", "QUALIDADE DA CAPTURA", *(result["warnings"] or ["Sem avisos de leitura."]), "", "LIMITES DA ANÁLISE", *result["limitations"]]
    return "\n".join(lines) + "\n"


def save_report(result, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    # Substituição atômica por arquivo.
    for name, contents in (("analise.json", json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)),
                           ("analise.txt", report_text(result))):
        target = destination / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(contents, encoding="utf-8")
        temporary.replace(target)



def export_metrics(source, destination, cancel=None):
    from modules.diagnostics import CSV_FIELDS, metrics

    destination = Path(destination)
    temporary = destination.with_name(destination.name + ".tmp")
    with session_files(source) as open_file, open_file("amostras.jsonl") as file:
        with temporary.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
            writer.writeheader()
            total = count = 0
            while True:
                if cancel and cancel():
                    raise AnalysisCancelled()
                line = file.readline(1024 * 1024 + 1)
                if not line:
                    break
                total += len(line)
                count += 1
                if len(line) > 1024 * 1024 or total > 512 * 1024 ** 2 or count > 120000:
                    raise AnalysisError("Sessão excede os limites de exportação.")
                try:
                    sample = json.loads(line)
                    if isinstance(sample, dict) and number(sample.get("monotonic")):
                        writer.writerow(metrics(sample))
                except (ValueError, TypeError, AttributeError):
                    continue
    temporary.replace(destination)
    return destination
