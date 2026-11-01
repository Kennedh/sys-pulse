import json
import time
import uuid

from modules.ai_service import request_json

ENDPOINT = "https://aihorde.net/api/v2"
HEADERS = {"apikey": "0000000000", "Client-Agent": "SysPulse:3.0.0:https://github.com/Kennedh/sys-pulse"}


def available_models():
    data = request_json(ENDPOINT + "/status/models?type=text", timeout=15, limit=2 * 1024 ** 2)
    if not isinstance(data, list):
        raise ValueError("O catálogo anônimo não retornou modelos válidos.")
    return [row for row in data if isinstance(row, dict) and isinstance(row.get("name"), str)
            and len(row["name"]) <= 180 and isinstance(row.get("count"), (int, float)) and row["count"] > 0]


def list_models():
    models = available_models()
    return ["auto"] + sorted({row["name"] for row in models})[:200]


def choose_model(name):
    models = available_models()
    if name != "auto":
        if not any(row["name"] == name for row in models):
            raise ValueError("Esse modelo não tem worker disponível. Atualize a lista ou escolha auto.")
        return name
    if not models:
        raise RuntimeError("Sem modelos anônimos disponíveis agora. A análise integrada continua disponível.")
    def score(row):
        suitable = any(token in row["name"].lower() for token in ("qwen", "instruct", "-it", "gemma"))
        speed = max(1, float(row.get("performance") or 1))
        queue = max(0, float(row.get("queued") or 0))
        return (not suitable, queue / speed, -speed)
    return min(models, key=score)["name"]


def call_anonymous(config, prompt, payload):
    cancelled = config.get("_cancelled", lambda: False)
    if cancelled():
        raise RuntimeError("Análise cancelada.")
    model = choose_model(config["model"])
    candidates = payload.get("evidence", [])[:8]
    compact = {"evidence": candidates, "lost_events": payload.get("lost_events"),
               "timelines_aligned": payload.get("timelines_aligned")}
    text = prompt + "\nEvidências:\n" + json.dumps(compact, ensure_ascii=False, separators=(",", ":")) + "\nResponda somente com o JSON solicitado:\n"
    if len(text) > 6000:
        raise ValueError("O resumo excede o limite da opção anônima. Use a explicação integrada ou um modelo local.")
    body = {"prompt": text, "models": [model], "trusted_workers": True, "validated_backends": True,
            "slow_workers": True, "allow_downgrade": True, "context_fit": "reject",
            "params": {"max_context_length": 2048, "max_length": 256, "temperature": .1, "n": 1}}
    job = request_json(ENDPOINT + "/generate/text/async", body=body, timeout=15, extra_headers=HEADERS)
    try:
        identifier = str(uuid.UUID(job["id"]))
    except (KeyError, ValueError, TypeError):
        raise ValueError("O serviço anônimo não confirmou uma solicitação válida.") from None
    destination = ENDPOINT + "/generate/text/status/" + identifier
    complete = False
    deadline = time.monotonic() + 90
    try:
        while time.monotonic() < deadline:
            if cancelled():
                raise RuntimeError("Análise cancelada.")
            result = request_json(destination, timeout=10, extra_headers=HEADERS)
            if cancelled():
                raise RuntimeError("Análise cancelada.")
            progress = config.get("_progress")
            if progress:
                queue = result.get("queue_position", "N/D")
                progress(f"Fila anônima · posição {queue} · espera limitada a 90 s. Cancelar mantém a explicação integrada.")
            if result.get("faulted") or result.get("is_possible") is False:
                raise RuntimeError("O serviço anônimo está sem capacidade para essa solicitação. A análise integrada permanece disponível.")
            if result.get("done"):
                generations = result.get("generations") or []
                answer = generations[0].get("text") if generations else None
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("O serviço anônimo concluiu sem uma resposta utilizável.")
                complete = True
                return {"text": answer[:24000], "usage": {"input_tokens": None, "output_tokens": None},
                        "model": generations[0].get("model") or model, "anonymous": True}
            time.sleep(1)
        raise RuntimeError("A fila anônima excedeu 90 s. Tente depois ou use a análise integrada/local.")
    finally:
        if not complete:
            try:
                request_json(destination, method="DELETE", timeout=10, extra_headers=HEADERS)
            except (RuntimeError, ValueError):
                pass
