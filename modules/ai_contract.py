import json


CATEGORIES = {
    "cpu": ("Processamento", "Repita a tarefa e compare o processo alvo, a carga por núcleo e as marcações."),
    "memory": ("Memória", "Compare memória disponível, comprometimento e leituras de páginas durante o sintoma."),
    "storage": ("Armazenamento", "Compare latência e fila do mesmo disco no horário do sintoma; I/O por processo não identifica o disco."),
    "graphics": ("Apresentação de quadros", "Repita a cena ou operação gráfica e compare os intervalos, mantendo as demais opções."),
    "drivers": ("Atividade de drivers", "Confira o período no WPA e compare com uma execução sem sintoma; o módulo pode ser compartilhado."),
    "network": ("Conexão", "Compare destinos e a conexão do aplicativo; ausência de ICMP pode ser filtragem."),
}


def render_explanation(text, payload):
    try:
        raw = text.strip()
        fence = chr(96) * 3
        if raw.startswith(fence):
            raw = raw.split("\n", 1)[1].rsplit(fence, 1)[0]
        result = json.loads(raw)
    except (ValueError, IndexError):
        raise ValueError("A IA não respeitou o formato de evidências. A explicação local permanece disponível.") from None
    if not isinstance(result, dict) or not isinstance(result.get("findings"), list) or len(result["findings"]) > 5:
        raise ValueError("Resposta de IA fora do contrato de análise.")
    if result.get("conclusion") not in (None, "hypotheses", "insufficient_data"):
        raise ValueError("A IA tentou apresentar uma conclusão fora do contrato.")
    known = {row["id"]: row for row in payload.get("evidence", [])}
    lines = ["PRIORIZAÇÃO COMPLEMENTAR · IA", ""]
    if payload.get("stress"):
        lines += ["Sessão com carga induzida: utilização alta pode ser esperada. Compare antes, durante e recuperação.", ""]
    selected = set()
    for finding in result["findings"]:
        if not isinstance(finding, dict):
            raise ValueError("Achado de IA inválido.")
        category = finding.get("category")
        ids = finding.get("evidence_ids")
        if category not in CATEGORIES or not isinstance(ids, list) or not 1 <= len(ids) <= 4:
            raise ValueError("A IA não vinculou a hipótese a evidências válidas.")
        for identifier in ids:
            if (not isinstance(identifier, str) or identifier not in known or
                    not known[identifier].get("candidate") or known[identifier].get("category") != category):
                raise ValueError("A IA priorizou uma evidência ausente ou incompatível. Confira a análise local.")
        if category in selected:
            continue
        selected.add(category)
        title, action = CATEGORIES[category]
        lines += [title + " · hipótese para testar"]
        for identifier in ids:
            row = known[identifier]
            label = row.get("resource") or row.get("metric") or row.get("module") or row.get("type")
            label = {"cpu": "CPU total", "core": "Núcleo mais ocupado", "ram": "RAM ocupada",
                     "gpu": "Uso da GPU", "vram": "VRAM ocupada", "disk": "Atividade de disco",
                     "dpc": "CPU em DPC"}.get(label, label)
            unit = row.get("unit", "")
            values = []
            for key in ("mean", "max", "p95", "p99_ms", "max_ms", "long_intervals", "total_us", "max_bucket_low_us", "max_bucket_high_us", "early", "late", "delta", "checks", "failures"):
                value = row.get(key)
                if isinstance(value, (int, float)):
                    caption = {"mean": "média", "max": "pico", "p95": "P95", "p99_ms": "P99", "max_ms": "maior intervalo",
                               "long_intervals": "intervalos longos", "total_us": "tempo acumulado",
                               "max_bucket_low_us": "faixa inferior", "max_bucket_high_us": "faixa superior",
                               "early": "início", "late": "fim", "delta": "variação", "checks": "verificações", "failures": "divergências"}[key]
                    values.append(f"{caption}: {value:g} {unit if key != 'long_intervals' else 'ocorrências'}".strip())
            lines.append(f"{identifier} · {label} · " + " | ".join(values))
        lines += ["Próximo teste: " + action, ""]
    if not selected:
        lines += ["As evidências enviadas não sustentaram uma prioridade adicional.",
                  "Isso não descarta pausas curtas ou recursos sem medição.", ""]
    lines += ["As unidades e os valores acima vêm da análise local; a IA apenas priorizou hipóteses.",
              "Causa não confirmada. Confira cobertura, lacunas e a repetição do sintoma."]
    return "\n".join(lines)
