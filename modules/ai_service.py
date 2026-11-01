import json
import socket
from modules.version import VERSION
import urllib.error
import urllib.parse
import urllib.request


from modules.ai_providers import PROVIDERS
from modules.ai_connections import connection, credential_options, catalog_url, compatible_models



class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_endpoint(endpoint):
    from modules.ai_connections import address_parts, endpoint_format
    endpoint, _, local = address_parts(endpoint)
    if endpoint == PROVIDERS["horde"]["endpoint"] or endpoint_format(endpoint) != "auto":
        return endpoint, local
    raise ValueError("Informe o endereço completo da API ou conecte o servidor em Configurações.")


def request_json(url, key="", body=None, timeout=15, limit=1024 * 1024, method=None, extra_headers=None):
    headers = {"Content-Type": "application/json", "User-Agent": f"SysPulse/{VERSION} (+https://github.com/Kennedh/sys-pulse)"}
    headers.update(extra_headers or {})
    if key.strip():
        headers["Authorization"] = "Bearer " + key.strip()
    data = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Resposta excede o limite de leitura.")
        return json.loads(raw)
    except urllib.error.HTTPError as error:
        messages = {400: "Formato ou opções incompatíveis com o modelo. Confira a conexão.",
                    401: "Chave inválida ou ausente.", 402: "O serviço exige saldo ou acesso ao modelo.",
                    403: "O serviço recusou esta solicitação.",
                    404: "Modelo ou endereço não encontrado.", 422: "O serviço não aceita este formato de solicitação.",
                    429: "Cota ou limite de pedidos atingido.", 503: "Nenhum atendimento disponível no serviço agora."}
        raise RuntimeError(f"HTTP {error.code}: " + messages.get(error.code, "O serviço não concluiu a solicitação.")) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout):
        raise RuntimeError("Serviço indisponível ou tempo esgotado. Confira se o servidor está iniciado.") from None
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("O serviço retornou uma resposta JSON inválida.") from None


def list_models(config):
    endpoint, api_format, local = connection(config)
    if api_format == "horde":
        from modules.horde_service import list_models as anonymous_models
        return anonymous_models()
    key, headers = credential_options(config, api_format, local)
    url = catalog_url(endpoint, api_format)
    provider = config.get("provider", "custom")
    if provider == "openrouter":
        url += "/user"
    rows, cursor, seen = [], "", set()
    for _ in range(5 if api_format == "messages" else 1):
        if config.get("_cancelled", lambda: False)():
            raise RuntimeError("Conexão cancelada.")
        page_url = url
        if api_format == "messages":
            page_url += "?limit=100" + ("&after_id=" + urllib.parse.quote(cursor, safe="") if cursor else "")
        data = request_json(page_url, key, timeout=15, limit=4 * 1024 ** 2, extra_headers=headers)
        if not isinstance(data, dict):
            raise ValueError("O serviço não retornou um catálogo de modelos válido.")
        items = data.get("models" if api_format == "ollama" else "data")
        if not isinstance(items, list):
            raise ValueError("A lista de modelos está ausente. Informe o ID manualmente ou confira o formato da API.")
        rows.extend(items[:500])
        if api_format != "messages" or not data.get("has_more"):
            break
        cursor = data.get("last_id")
        if not isinstance(cursor, str) or not 0 < len(cursor) <= 180 or cursor in seen:
            break
        seen.add(cursor)
    return compatible_models(rows, provider)


def call_model(config, prompt, payload):
    endpoint, api_format, local = connection(config)
    provider = config.get("provider", "custom")
    model = config.get("model", "").strip()
    if not model:
        raise ValueError("Escolha um modelo instalado ou disponível na sua conta.")
    if provider == "ollama_cloud" and (not local or api_format != "ollama"):
        raise ValueError("A conta Ollama usa a API local. Escolha Outro serviço para um endpoint diferente.")
    if provider == "ollama" and model.endswith(("-cloud", ":cloud")):
        raise ValueError("Esse modelo usa a nuvem. Escolha Nuvem via Ollama em Configurações.")
    if provider == "ollama_cloud" and not model.endswith(("-cloud", ":cloud")):
        raise ValueError("Escolha um modelo cloud para a conta Ollama.")
    if config.get("structured"):
        candidates = [row for row in payload.get("evidence", []) if row.get("candidate")]
        if not candidates:
            return {"text": '{"findings":[],"conclusion":"insufficient_data"}',
                    "usage": {"input_tokens": 0, "output_tokens": 0}, "model": "análise local"}
        payload = {"evidence": candidates, "resource_collection": payload.get("resource_collection"),
                   "lost_events": payload.get("lost_events"), "timelines_aligned": payload.get("timelines_aligned"),
                   "symptom_comparison": payload.get("symptom_comparison"), "stress": payload.get("stress")}
    if api_format == "horde":
        from modules.horde_service import call_anonymous
        return call_anonymous(config, prompt, payload)
    key, headers = credential_options(config, api_format, local)
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    limit = max(128, min(2400, int(config.get("answer_tokens", 900))))
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": text}]
    if api_format == "messages":
        body = {"model": model, "system": prompt, "messages": [{"role": "user", "content": text}], "max_tokens": limit}
    elif api_format == "responses":
        body = {"model": model, "instructions": prompt, "input": text, "max_output_tokens": limit, "store": False}
        if config.get("structured") and provider == "openai":
            body["text"] = {"format": {"type": "json_object"}}
    elif api_format == "ollama":
        body = {"model": model, "messages": messages, "stream": False,
                "keep_alive": 0, "options": {"num_predict": limit, "num_ctx": 8192}}
        if model.startswith("qwen3"):
            body["think"] = False
        if config.get("structured"):
            body["format"] = "json"
    else:
        token_field = "max_completion_tokens" if provider == "openai" else "max_tokens"
        body = {"model": model, "messages": messages, "stream": False, token_field: limit}
        if config.get("structured") and provider in ("openai", "gemini", "deepseek", "mistral"):
            body["response_format"] = {"type": "json_object"}
    try:
        result = request_json(endpoint, key=key, body=body, timeout=240 if api_format == "ollama" else 120,
                              limit=256 * 1024, extra_headers=headers)
    except RuntimeError as error:
        if provider == "ollama_cloud" and "HTTP 401" in str(error):
            raise RuntimeError("Entre na sua conta pelo Ollama e confira o acesso ao modelo cloud.") from None
        raise
    if not isinstance(result, dict):
        raise ValueError("O serviço não retornou uma resposta de análise válida.")
    source = result.get("usage") or {}
    if not isinstance(source, dict):
        source = {}
    if api_format == "messages":
        blocks = result.get("content") or []
        answer = "".join(row["text"] for row in blocks if isinstance(row, dict) and row.get("type") == "text" and isinstance(row.get("text"), str))
        usage = {field: source.get(field) for field in ("input_tokens", "output_tokens")}
        if result.get("stop_reason") == "max_tokens":
            raise ValueError("O modelo atingiu o limite antes de concluir. Ajuste o limite da resposta ou escolha outro modelo.")
    elif api_format == "responses":
        if result.get("status") in ("incomplete", "failed", "cancelled"):
            raise ValueError("O modelo não concluiu a resposta. Confira o limite de tokens e a disponibilidade do serviço.")
        answer = "".join(block["text"] for row in result.get("output", []) if isinstance(row, dict) and row.get("type") == "message"
                         for block in row.get("content", []) if isinstance(block, dict) and block.get("type") == "output_text" and isinstance(block.get("text"), str))
        usage = {field: source.get(field) for field in ("input_tokens", "output_tokens")}
    elif api_format == "ollama":
        answer = (result.get("message") or {}).get("content")
        usage = {"input_tokens": result.get("prompt_eval_count"), "output_tokens": result.get("eval_count")}
    else:
        try:
            choice = result["choices"][0]
            answer = choice["message"]["content"]
            if choice.get("finish_reason") == "length":
                raise ValueError("O modelo atingiu o limite antes de concluir. Ajuste o limite da resposta ou escolha outro modelo.")
        except (KeyError, IndexError, TypeError):
            raise ValueError("Resposta incompatível com Chat Completions.") from None
        usage = {"input_tokens": source.get("prompt_tokens"), "output_tokens": source.get("completion_tokens")}
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("O modelo não retornou uma explicação em texto.")
    actual_model = result.get("model")
    return {"text": answer[:24000], "usage": usage, "model": actual_model[:180] if isinstance(actual_model, str) and actual_model else model,
            "provider": provider, "api_format": api_format}
