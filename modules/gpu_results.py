import math


def gpu_result_text(result):
    def mapping(value):
        return value if isinstance(value, dict) else {}
    def value(number, divisor=1, digits=1):
        try:
            if isinstance(number, (int, float)) and not isinstance(number, bool) and math.isfinite(number):
                return f"{number/divisor:.{digits}f}"
        except OverflowError:
            pass
        return "N/D"
    states = {"passed": "Concluída sem divergências nos critérios testados", "failed": "Divergências detectadas",
              "partial": "Cobertura parcial", "disabled": "Verificações desativadas",
              "unavailable": "Sem verificação concluída"}
    lines = ["Verificação GPU: " + states.get(result.get("verification_status"), "Confira os contadores e a cobertura")]
    resolution = result.get("render_resolution")
    if isinstance(resolution, list) and len(resolution) == 2:
        lines.append(f"Renderização fixa: {resolution[0]}×{resolution[1]}; a janela é uma prévia.")
    art = mapping(result.get("artifacts"))
    memory = mapping(result.get("vram"))
    if art:
        lines += [f"Imagens: {value(art.get('scene_pairs'), digits=0)} pares e {value(art.get('known_patterns'), digits=0)} padrões conhecidos · "
                  f"verificações com divergência: {value(art.get('failed_checks'), digits=0)} · "
                  f"pixels divergentes: {value(art.get('mismatched_pixels'), digits=0)}",
                  str(art.get("method") or "")]
    if memory:
        mb = 1024**2
        lines += [f"Memória GPU · {memory.get('phase', 'N/D')} · padrão: {memory.get('pattern', 'N/D')}",
                  f"Alvo: {value(memory.get('target_bytes'), mb)} MiB · alocado: {value(memory.get('allocated_bytes'), mb)} MiB · "
                  f"endereços únicos lidos: {value(memory.get('unique_checked_bytes'), mb)} MiB",
                  f"Passagens: {value(memory.get('passes'), digits=0)} · ciclos de 70 padrões: {value(memory.get('cycles'), digits=0)} · "
                  f"leituras acumuladas: {value(memory.get('checked_bytes'), mb)} MiB",
                  f"Palavras divergentes: {value(memory.get('mismatched_words'), digits=0)} · bits divergentes: {value(memory.get('mismatched_bits'), digits=0)}",
                  "Cobertura completa do orçamento e de um ciclo." if memory.get("coverage_complete") is True else
                  "Cobertura parcial: confira bytes lidos e ciclos concluídos.",
                  str(memory.get("method") or "")]
    if art or memory:
        lines.append(f"Tempo acumulado das verificações: {value(result.get('verification_ms'))} ms; isso interfere no FPS.")
    else:
        lines.append("Verificações de imagem/memória não registradas; renderizar sem erro não verifica integridade.")
    if result.get("evidence"):
        lines.append("Evidências na subpasta do auxiliar: " + str(result.get("evidence_folder") or "carga"))
    return "\n".join(lines)
