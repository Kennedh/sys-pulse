import csv
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path, PureWindowsPath

from modules.advanced_capture import find_tools, write_json
from modules.inspection import driver_rows
from modules.incidents import symptom_evidence


class AdvancedCancelled(Exception):
    pass


def read_text(path, limit=32 * 1024 ** 2):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ValueError("Relatório excede o limite de 32 MiB")
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def parse_dpc_report(text):
    rows, intervals, warnings = {}, [], []
    kind = module = None
    table = interval_table = False
    duration_s = None
    pair = re.compile(r"\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*")

    def get_row(name):
        key = (kind, name.casefold())
        if key not in rows:
            rows[key] = {"kind": kind, "module": name, "total_us": None, "count": None,
                         "mean_us": None, "max_us": None, "max_bucket_low_us": None,
                         "max_bucket_high_us": None, "buckets": [], "cpu_us": []}
        return rows[key]

    for raw in text.splitlines():
        line = raw.replace("\u00a0", " ").strip()
        if re.fullmatch(r"DPC Info", line, re.I):
            kind, table, interval_table, module = "DPC", False, False, None
            continue
        if re.fullmatch(r"(?:Interrupt|ISR) Info", line, re.I):
            kind, table, interval_table, module = "ISR", False, False, None
            continue
        if kind is None:
            continue
        if "CPU Usage Summing By Module For the Whole Trace" in line:
            table, interval_table, module = True, False, None
            continue
        period = re.fullmatch(r"CPU Usage from (\d+) us to (\d+) us:", line)
        if period:
            duration_s = max(duration_s or 0, (int(period[2]) - int(period[1])) / 1e6)
            continue
        if line.startswith("Start (ms)"):
            table, interval_table, module = False, True, None
            continue
        interval = re.fullmatch(r"(\d+)\s*-\s*(\d+)\s*:\s*,(.*)", line)
        if interval_table and interval:
            cells = next(csv.reader([interval[3]], skipinitialspace=True))
            matches = [pair.fullmatch(cell) for cell in cells]
            if matches and all(matches):
                intervals.append({"kind": kind, "start_s": int(interval[1]) / 1000,
                                  "end_s": int(interval[2]) / 1000,
                                  "total_us": sum(float(match[1]) for match in matches)})
            continue
        histogram = re.fullmatch(r'Total\s*=\s*(\d+)\s+for module\s+"?(.+?)"?\s*', line, re.I)
        if histogram:
            table, interval_table = False, False
            module = histogram[2].strip('"')
            get_row(module)["count"] = int(histogram[1])
            continue
        if re.match(r"Total\s*=", line):
            table, module = False, None
            continue
        bucket = re.match(r"Elapsed Time,\s*>\s*(\d+(?:\.\d+)?)\s+usecs?\s+AND\s+<=\s*(\d+(?:\.\d+)?)\s+usecs?,\s*(\d+),", line, re.I)
        if bucket and module:
            low, high, count = float(bucket[1]), float(bucket[2]), int(bucket[3])
            if high > low >= 0:
                get_row(module)["buckets"].append({"low_us": low, "high_us": high, "count": count})
            continue
        if table and "," in line:
            cells = next(csv.reader([line], skipinitialspace=True))
            matches = [pair.fullmatch(cell) for cell in cells[:-1]]
            if len(cells) >= 2 and all(matches) and cells[-1].strip():
                row = get_row(cells[-1].strip())
                if row["total_us"] is not None:
                    warnings.append("Tabela repetida para um módulo; confira o relatório bruto.")
                    continue
                row["cpu_us"] = [float(match[1]) for match in matches]
                row["total_us"] = sum(row["cpu_us"])
    for row in rows.values():
        buckets = row["buckets"]
        if buckets and sum(b["count"] for b in buckets) != row["count"]:
            warnings.append(f"Histograma incompleto: {row['kind']} / {row['module']}.")
        elif buckets:
            populated = [b for b in buckets if b["count"]]
            if populated:
                largest = max(populated, key=lambda b: b["high_us"])
                row["max_bucket_low_us"], row["max_bucket_high_us"] = largest["low_us"], largest["high_us"]
        if row["total_us"] is not None and row["count"]:
            row["mean_us"] = row["total_us"] / row["count"]
    result = sorted(rows.values(), key=lambda r: r["total_us"] if r["total_us"] is not None else -1, reverse=True)
    if not result:
        warnings.append("Sem dados DPC/ISR reconhecidos. A captura pode não conter esses eventos ou usar um formato diferente.")
    if any(re.search(r"unknown|unresolved|desconhecido|^0x", row["module"], re.I) for row in result):
        warnings.append("Há módulos não identificados; não é possível atribuir toda a atividade a um driver.")
    return {"drivers": result, "intervals": intervals, "duration_s": duration_s, "warnings": warnings,
            "method": "Xperf DPC/ISR. Tempo total soma os processadores. Histogramas fornecem faixas, não o máximo exato. "
                      "Duração de execução não mede espera em fila nem latência completa do computador."}


def parse_trace_quality(text):
    def losses(noun):
        label = rf"(?:{noun}\s+Lost|Lost\s+{noun})\s*[:=]\s*(\d+)"
        totals = re.findall(rf"^\s*Total\s*#?\s*{label}", text, re.I | re.M)
        details = re.findall(rf"^\s*#?\s*{label}", text, re.I | re.M)
        values = totals or details
        return sum(map(int, values)) if values else None

    events, buffers = losses("Events"), losses("Buffers")
    return {"lost_events": events, "lost_buffers": buffers, "checked": events is not None}


def driver_name(value):
    return PureWindowsPath(str(value)).name[:160]


def explain_capture(result, native=None):
    evidence, limits, steps = [], list(result.get("warnings", [])), []
    symptoms = native.get("symptoms", {}) if native else {}
    for item in symptom_evidence(symptoms):
        evidence.append({"id": f"E{len(evidence) + 1}", **item})
    drivers = result.get("drivers", [])
    quality = result.get("quality", {})
    if "drivers" in result and quality.get("lost_events"):
        limits.append(f"O rastreamento informa {quality['lost_events']} eventos perdidos; os resultados são parciais.")
    elif "drivers" in result and quality.get("lost_events") is None:
        limits.append("A quantidade de eventos perdidos não foi reconhecida; confira as estatísticas brutas.")
    if quality.get("lost_buffers"):
        limits.append(f"O rastreamento informa {quality['lost_buffers']} buffers perdidos; pode haver intervalos sem eventos.")
    for driver in drivers[:5]:
        module = driver_name(driver["module"])
        total = driver.get("total_us")
        count = driver.get("count")
        high, low = driver.get("max_bucket_high_us"), driver.get("max_bucket_low_us")
        detail = f"{module} teve atividade de {driver['kind']} registrada."
        if total is not None:
            detail += f" Tempo acumulado: {total / 1000:.3f} ms."
        if count is not None:
            detail += f" Ocorrências: {count}."
        if high is not None:
            detail += f" A maior ocorrência está na faixa acima de {low:g} até {high:g} µs; o valor exato não está disponível."
        interpretation = "É um componente para comparar entre capturas. A posição no ranking, sozinha, não indica falha."
        if module.casefold() in {"ndis.sys", "dxgkrnl.sys", "wdf01000.sys", "ntoskrnl.exe", "storport.sys", "acpi.sys"}:
            interpretation += " Este módulo participa de uma camada compartilhada do Windows; outro componente pode estar envolvido."
        evidence.append({"id": f"E{len(evidence) + 1}", "title": ("Sessão inteira · " if symptoms.get("marker_count") else "") + f"{driver['kind']} · {module}",
                         "observed": detail, "meaning": interpretation,
                         "next_test": "Repita a mesma tarefa com e sem o sintoma, mantendo a duração. Compare a atividade e investigue o módulo no WPA."})
    if native:
        meanings = {
            "cpu": "A CPU chegou perto da capacidade total. Se isso coincidir com o sintoma, tarefas podem ter esperado por processamento.",
            "core": "Pelo menos um núcleo ficou muito ocupado. Um programa pode ficar limitado por esse núcleo mesmo com a CPU total baixa.",
            "ram": "Grande parte da RAM estava ocupada. Para saber se faltou memória, também é preciso conferir memória disponível e leituras de páginas; caches usam RAM.",
            "gpu": "A GPU teve bastante trabalho. Isso pode ser esperado em jogos e renderização; confira se o sintoma aparece junto e se há queda de desempenho.",
            "vram": "Grande parte da memória da GPU estava ocupada. A ocupação, sozinha, não mostra se houve espera ou falta de memória.",
            "disk": "O disco passou bastante tempo atendendo operações. Isso não informa sozinho sua velocidade ou saúde; latência e fila ajudam a verificar se houve espera.",
            "dpc": "A CPU dedicou tempo ao trabalho adiado dos drivers. Este percentual não identifica o driver nem mede a duração de cada execução.",
            "disk_latency": "Operações concluídas no disco tiveram tempo médio de atendimento elevado na leitura indicada. Isso pode gerar espera, mas não identifica sozinho a origem nem comprova defeito."
        }
        for finding in native.get("summary", {}).get("assessment", {}).get("findings", []):
            detail = finding["evidence"]
            resource = next((row for row in native.get("summary", {}).get("resources", []) if row["key"] == finding["resource"]), {})
            process = resource.get("process")
            if process:
                detail += f" O processo {process['name']} (PID {process['pid']}) foi observado perto do pico; isso não prova que ele causou a pausa."
            evidence.append({"id": f"E{len(evidence) + 1}", "title": ("Sessão inteira · " if symptoms.get("marker_count") else "") + finding["title"],
                             "observed": detail,
                             "meaning": meanings.get(finding["resource"], "Foi observada carga durante a coleta de recursos.") + " Isso não comprova defeito nem a causa do sintoma.",
                             "next_test": finding["action"]})
        inventory = native.get("inventory") or {}
        for device in [row for row in driver_rows(inventory) if row["status"] == "Atenção"][:5]:
            evidence.append({"id": f"E{len(evidence) + 1}", "title": f"Dispositivo: {device['name']}",
                             "observed": device["detail"],
                             "meaning": "É o estado informado pelo Windows no horário do inventário; não demonstra sozinho defeito físico.",
                             "next_test": "Confira o código nas propriedades do dispositivo e as orientações do fabricante para o modelo exato."})
        for disk in inventory.get("sections", {}).get("storage", {}).get("rows", []):
            if str(disk.get("HealthStatus", "")).casefold() in ("warning", "unhealthy", "1", "2"):
                evidence.append({"id": f"E{len(evidence) + 1}", "title": "Alerta informado pelo armazenamento",
                                 "observed": f"{disk.get('FriendlyName', 'Disco')}: Windows informou {disk['HealthStatus']}.",
                                 "meaning": "O provedor do Windows informou um estado que merece investigação. Isso não determina qual componente físico falhou.",
                                 "next_test": "Confira o backup dos arquivos importantes e valide os detalhes com a ferramenta oficial do fabricante antes de decidir por substituição."})
        limits += native.get("warnings", [])
        if "drivers" in result:
            limits.append("Recursos e ETL têm períodos próprios. Não foi feita atribuição automática de causa nem alinhamento exato das marcações.")
    else:
        limits.append("Sem captura de recursos associada; CPU, RAM, GPU e disco não foram avaliados em conjunto neste relatório.")
    if "drivers" in result:
        limits.append("O ETL pode conter nomes de processos, caminhos e outros dados do sistema. O arquivo completo não é enviado à IA.")
    steps += ["Reproduza a mesma tarefa numa captura curta. Marque quando perceber a falha.",
              "Faça outra captura com a mesma duração e sem o sintoma. Compare repetibilidade, contagens e durações.",
              "Investigue primeiro software, configuração e driver relacionados às evidências. Altere uma variável por vez e registre o resultado.",
              "Considere suspeita de hardware apenas após testes específicos do componente e evidências independentes. Este relatório não recomenda troca de peças."]
    summary = ("Há atividade medida para investigar, mas a causa do sintoma ainda não está confirmada."
               if evidence else "Os dados disponíveis são insuficientes para explicar o sintoma. Isso não significa que o computador esteja sem problemas.")
    if native:
        limits.append("P95 é o valor até o qual ficam pelo menos 95% das leituras válidas. Um pico breve pode ficar acima dele.")
        if symptoms.get("marker_count"):
            limits.append(symptoms["method"])
            partial = sum(window["partial"] for window in symptoms["windows"])
            gaps = sum(bool(window["gaps"]) for window in symptoms["windows"])
            if partial:
                limits.append(f"{partial} janela(s) de marcação com cobertura parcial dos 5 s antes/depois.")
            if gaps:
                limits.append(f"{gaps} janela(s) de marcação contêm lacunas de coleta; a coincidência com o sintoma é incerta.")
            candidates = symptoms.get("candidates", [])
            if candidates:
                summary = (
                    "Carga alta perto das marcações: " + ", ".join(row["name"] for row in candidates) +
                    ". Compare abaixo a frequência dentro e fora das janelas; a causa ainda não está confirmada."
                )
            else:
                summary = ("Sem carga alta nos recursos disponíveis perto das marcações. "
                           "A amostragem pode perder pausas curtas; investigue o período no ETL.")
        else:
            summary = "Sem marcações do sintoma: os resultados descrevem a sessão inteira. " + summary
            limits.append("Marque a próxima pausa para comparar os recursos perto do sintoma com o restante da sessão.")
    return {"summary": summary, "evidence": evidence, "limitations": list(dict.fromkeys(limits)), "next_steps": steps,
            "conclusion": "Causa não confirmada; nenhuma peça condenada por esta análise."}


def readable_report(result, title="SYS-PULSE — ANÁLISE AVANÇADA"):
    report = result["explanation"]
    lines = [title, "", report["summary"], "", "O QUE FOI OBSERVADO"]
    if result.get("drivers"):
        lines[4:4] = ["DPC/ISR são rotinas usadas pelos drivers para atender eventos dos dispositivos. µs = microssegundos; 1.000 µs = 1 ms.",
                      "Tempo acumulado soma várias execuções; não representa uma única travada.", ""]
    for item in report["evidence"]:
        lines += [f"{item['id']} · {item['title']}", item["observed"],
                  "O que significa: " + item["meaning"], "Próximo teste: " + item["next_test"], ""]
    lines += ["COMO CONTINUAR", *[f"{i}. {step}" for i, step in enumerate(report["next_steps"], 1)],
              "", "O QUE AINDA NÃO FOI COMPROVADO", *report["limitations"], "", report["conclusion"]]
    return "\n".join(lines)


def run_tool(arguments, log_path, cancel, timeout=180):
    with Path(log_path).open("wb") as log:
        process = subprocess.Popen(list(map(str, arguments)), stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=0x08000000 if os.name == "nt" else 0)
        started = time.monotonic()
        try:
            while process.poll() is None:
                if cancel():
                    raise AdvancedCancelled()
                if time.monotonic() - started > timeout:
                    raise TimeoutError("O processamento excedeu 3 minutos. O ETL original foi preservado.")
                if Path(log_path).stat().st_size > 32 * 1024 ** 2:
                    raise ValueError("Saída do processador excedeu o limite")
                time.sleep(.1)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        if process.returncode:
            raise RuntimeError(f"Xperf retornou {process.returncode}. Consulte {Path(log_path).name}.")


def analyze_etl(source, destination, cancel=lambda: False, native=None, xperf=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source.suffix.lower() != ".etl" or not source.is_file():
        raise ValueError("Selecione um arquivo ETL existente.")
    if not 0 < source.stat().st_size <= 4 * 1024 ** 3:
        raise ValueError("O ETL precisa ter entre 1 byte e 4 GiB.")
    executable = xperf or find_tools()["xperf"]
    if not executable:
        raise RuntimeError("Instale o Windows Performance Toolkit para analisar ETL. A captura pode ser guardada e aberta depois.")
    destination.mkdir(parents=True, exist_ok=True)
    report_path, stats_path = destination / "dpc-isr.txt", destination / "trace-stats.txt"
    run_tool([executable, "-i", source, "-o", report_path, "-a", "dpcisr"], destination / "xperf-dpc.log", cancel)
    result = parse_dpc_report(read_text(report_path))
    if cancel():
        raise AdvancedCancelled()
    try:
        run_tool([executable, "-i", source, "-o", stats_path, "-a", "tracestats"], destination / "xperf-stats.log", cancel)
        result["quality"] = parse_trace_quality(read_text(stats_path))
    except (OSError, ValueError, RuntimeError) as error:
        result["quality"] = {"lost_events": None, "checked": False}
        result["warnings"].append(f"Estatísticas do ETL indisponíveis: {error}")
    result.update(schema_version=1, source=str(source), analyzed_at=datetime.now().astimezone().isoformat(),
                  engine="Microsoft Xperf", native_summary=native.get("summary") if native else None,
                  native_symptoms=native.get("symptoms") if native else None)
    result["explanation"] = explain_capture(result, native)
    if cancel():
        raise AdvancedCancelled()
    write_json(destination / "analise-avancada.json", result)
    (destination / "analise-avancada.txt").write_text(readable_report(result), encoding="utf-8")
    return result
