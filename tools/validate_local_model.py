import argparse
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules.ai_service import PROVIDERS, call_model, request_json
from modules.ai_summary import SYSTEM_PROMPT
from modules.ai_contract import render_explanation
from modules.model_manager import pull_model, validate_model, cloud_model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="llama3.2:3b")
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--output", default="diagnosticos/validacao-3.0/modelo-local.json")
    options = parser.parse_args()
    model = validate_model(options.model)
    if cloud_model(model):
        raise SystemExit("Esta validação executa somente modelos locais.")
    config = {**PROVIDERS["ollama"], "provider": "ollama", "model": model, "structured": True}
    statuses = set()
    started = time.monotonic()
    if options.download:
        def progress(item):
            status = item.get("status")
            if status not in statuses:
                print(status, flush=True)
                statuses.add(status)
        pull_model(config["endpoint"], model, progress, lambda: False)
    download_s = time.monotonic() - started if options.download else None
    cases = [
        ("cpu", {"evidence": [{"id": "E1", "type": "resource", "resource": "cpu", "category": "cpu",
                              "candidate": True, "unit": "%", "mean": 80, "max": 98, "p95": 96}]}),
        ("storage", {"evidence": [{"id": "E1", "type": "disk", "metric": "read_latency", "category": "storage",
                                  "candidate": True, "unit": "ms/op", "mean": 40, "max": 120, "p95": 90}]}),
        ("no_candidates", {"evidence": []}),
    ]
    results = []
    for name, payload in cases:
        at = time.monotonic()
        try:
            answer = call_model(config, SYSTEM_PROMPT, payload)
            text = render_explanation(answer["text"], payload)
            results.append({"case": name, "accepted": True, "elapsed_s": round(time.monotonic() - at, 3),
                            "usage": answer["usage"], "raw": answer["text"], "validated_text": text})
        except Exception as error:
            results.append({"case": name, "accepted": False, "elapsed_s": round(time.monotonic() - at, 3),
                            "error": str(error)})
        print(json.dumps({key: value for key, value in results[-1].items() if key not in ("raw", "validated_text")}), flush=True)
    base = config["endpoint"][:-len("/chat")]
    loaded = request_json(base + "/ps").get("models", [])
    metadata = request_json(base + "/tags").get("models", [])
    size = next((item.get("size") for item in metadata if item.get("name") == model), None)
    report = {"model": model, "synthetic_inputs": True, "system": platform.system(), "download_s": download_s,
              "model_disk_bytes": size, "download_statuses": sorted(statuses),
              "cases": results, "loaded_models_after": [item.get("name") for item in loaded]}
    destination = Path(options.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
