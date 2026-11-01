def compare_markers(events, near, outside):
    method = (
        "Compara leituras até 5 s antes/depois das marcações com as demais leituras da mesma sessão. "
        "Janelas sobrepostas contam uma vez nos percentuais agregados. Fora das marcações não significa sem sintoma. "
        "A comparação é descritiva, sem teste de significância ou atribuição de causa."
    )
    windows = []
    for event in events:
        summary = event["analysis"]
        low, high = event["coverage"]
        tolerance = (summary.get("target_interval_ms") or 500) / 1000
        windows.append({
            "id": event["marker"]["id"], "samples": summary["samples"],
            "partial": low is None or high is None or low > -5 + tolerance or high < 5 - tolerance,
            "gaps": summary.get("collection", {}).get("gaps", 0),
        })
    baseline = {row["key"]: row for row in outside["resources"]}
    candidates = []
    for row in near["resources"]:
        if not row["count"]:
            continue
        other = baseline[row["key"]]
        marker_percent = 100 * row["high_count"] / row["count"]
        baseline_percent = 100 * other["high_count"] / other["count"] if other["count"] else None
        affected, observed = 0, 0
        for event in events:
            resource = next(r for r in event["analysis"]["resources"] if r["key"] == row["key"])
            affected += bool(resource["high_count"])
            observed += bool(resource["count"])
        candidates.append({
            "key": row["key"], "name": row["name"], "threshold": row["threshold"],
            "affected_markers": affected, "observed_markers": observed,
            "near_count": row["count"], "near_high_count": row["high_count"],
            "near_high_percent": marker_percent, "outside_count": other["count"],
            "outside_high_count": other["high_count"], "outside_high_percent": baseline_percent,
            "difference_pp": marker_percent - baseline_percent if baseline_percent is not None else None,
            "peak": row["peak"], "peak_at": row["peak_at"],
        })
    candidates.sort(key=lambda row: (row["difference_pp"] is not None,
                                     row["difference_pp"] if row["difference_pp"] is not None else 0,
                                     row["affected_markers"]), reverse=True)
    return {"marker_count": len(events), "near_samples": near["samples"],
            "outside_samples": outside["samples"], "windows": windows,
            "resources": candidates, "candidates": [row for row in candidates if row["near_high_count"]], "method": method}


def symptom_evidence(symptoms):
    evidence = []
    actions = {
        "cpu": "Confira os processos de CPU na marcação e repita a tarefa fechando um programa de cada vez.",
        "core": "Confira no WPA quais threads ocuparam esse núcleo; o líder de CPU total pode ser outro processo.",
        "ram": "Compare RAM disponível e leituras de páginas no mesmo período antes de concluir falta de memória.",
        "gpu": "Repita a mesma cena com uma opção gráfica alterada e compare a repetição do sintoma.",
        "vram": "Repita a tarefa com menos uso de memória gráfica e compare o sintoma, mantendo as demais opções.",
        "disk": "Confira latência e fila do mesmo disco; o ranking de I/O não vincula um processo ao disco físico.",
        "dpc": "Confira no WPA DPC/ISR por módulo no período do sintoma; o percentual não identifica um driver.",
    }
    for row in symptoms.get("candidates", []):
        observed = (
            f"Carga ≥{row['threshold']}% em {row['affected_markers']}/{row['observed_markers']} marcação(ões) com dados. "
            f"Perto das marcações: {row['near_high_count']}/{row['near_count']} leituras "
            f"({row['near_high_percent']:.1f}%). "
        )
        outside = row["outside_high_percent"]
        if outside is None:
            observed += "Sem leituras deste recurso fora das janelas para comparação."
            meaning = "Há carga perto do sintoma, mas falta uma base de comparação na sessão."
        else:
            observed += (
                f"Fora das janelas: {row['outside_high_count']}/{row['outside_count']} "
                f"({outside:.1f}%). Diferença: {row['difference_pp']:+.1f} pontos percentuais."
            )
            meaning = (
                "A carga alta foi mais frequente perto das marcações; é uma pista para testar."
                if row["difference_pp"] > 0 else
                "A carga alta também aparece fora das janelas com frequência igual ou maior; explica pouco o horário da pausa."
            )
        evidence.append({"title": f"Perto do sintoma · {row['name']}", "observed": observed,
                         "meaning": meaning + " Coincidência temporal não confirma causa; marcações próximas podem descrever a mesma pausa.",
                         "next_test": actions[row["key"]]})
    return evidence
