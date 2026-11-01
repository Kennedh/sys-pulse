import json
import socket
import urllib.error
import urllib.parse
import urllib.request


PROVIDERS = {
    "horde": {"name": "Nuvem · anônima, sem login ou chave", "endpoint": "https://aihorde.net/api/v2",
              "model": "auto",
              "help": "AI Horde: serviço comunitário gratuito, com fila e disponibilidade variável. Workers recebem o resumo; não envie dados privados. Não exige conta ou chave sua.",
              "url": "https://aihorde.net"},
    "ollama": {"name": "Local · Ollama", "endpoint": "http://127.0.0.1:11434/api/chat", "model": "llama3.2:3b",
               "help": "Selecione um modelo instalado. Llama sugerido: llama3.2:3b. A listagem não carrega o modelo.",
               "url": "https://ollama.com/download"},
    "ollama_cloud": {"name": "Nuvem · conta Ollama, sem colar chave", "endpoint": "http://127.0.0.1:11434/api/chat",
                     "model": "gpt-oss:120b-cloud",
                     "help": "Entre na sua conta pelo Ollama. A nuvem usa a cota ou saldo da conta; não exige chave no SysPulse.",
                     "url": "https://docs.ollama.com/cloud"},
    "gemini": {"name": "Nuvem · Gemini", "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "model": "",
               "help": "Use sua chave do Google AI Studio. A faixa gratuita tem limites e depende do modelo e da conta.",
               "url": "https://aistudio.google.com/apikey"},
    "lmstudio": {"name": "Local · LM Studio", "endpoint": "http://127.0.0.1:1234/v1/chat/completions", "model": "",
                 "help": "Inicie o servidor em Developer no LM Studio. O carregamento externo de modelos depende desse programa.",
                 "url": "https://lmstudio.ai/"},
    "openrouter": {"name": "Nuvem · OpenRouter", "endpoint": "https://openrouter.ai/api/v1/chat/completions", "model": "openrouter/free",
                   "help": "Use sua chave. Modelos gratuitos têm cotas e disponibilidade própria.",
                   "url": "https://openrouter.ai/keys"},
    "openai": {"name": "Nuvem · OpenAI", "endpoint": "https://api.openai.com/v1/chat/completions", "model": "",
                "help": "Use sua chave de API e um modelo da sua conta. O uso pode ser cobrado.",
                "url": "https://platform.openai.com/api-keys"},
    "custom": {"name": "Outro serviço compatível", "endpoint": "https://", "model": "",
               "help": "Informe o endpoint completo de Chat Completions do serviço.",
               "url": ""},
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_endpoint(endpoint):
    endpoint = endpoint.strip()
    parsed = urllib.parse.urlsplit(endpoint)
    local = parsed.hostname in ("127.0.0.1", "localhost", "::1")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Informe uma URL sem credenciais, parâmetros ou fragmentos.")
    if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
        raise ValueError("Use HTTPS para serviços externos; HTTP é permitido apenas em loopback.")
    if endpoint.rstrip("/") == "https://aihorde.net/api/v2":
        return endpoint.rstrip("/"), False
    if not (parsed.path.rstrip("/").endswith("/chat/completions") or local and parsed.path == "/api/chat"):
        raise ValueError("Use um endpoint /chat/completions ou a API local /api/chat do Ollama.")
    return endpoint, local


def request_json(url, key="", body=None, timeout=15, limit=1024 * 1024, method=None, extra_headers=None):
    headers = {"Content-Type": "application/json", "User-Agent": "SysPulse/3.0 (+https://github.com/Kennedh/sys-pulse)"}
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
        messages = {401: "Chave inválida ou ausente.", 403: "O serviço recusou esta solicitação.",
                    404: "Modelo ou endereço não encontrado.", 429: "Cota ou limite de pedidos atingido."}
        raise RuntimeError(f"HTTP {error.code}: " + messages.get(error.code, "O serviço não concluiu a solicitação.")) from None
    except (urllib.error.URLError, TimeoutError, socket.timeout):
        raise RuntimeError("Serviço indisponível ou tempo esgotado. Confira se o servidor está iniciado.") from None
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("O serviço retornou uma resposta JSON inválida.") from None


def list_models(config):
    if config.get("provider") == "horde":
        from modules.horde_service import list_models as anonymous_models
        return anonymous_models()
    endpoint, local = validate_endpoint(config["endpoint"])
    if local and urllib.parse.urlsplit(endpoint).path == "/api/chat":
        data = request_json(endpoint[:-len("/chat")] + "/tags", timeout=10)
        names = [row.get("name") for row in data.get("models", []) if isinstance(row, dict)]
    else:
        data = request_json(endpoint[:-len("/chat/completions")] + "/models", config.get("key", ""), limit=4 * 1024 ** 2)
        names = [row.get("id") for row in data.get("data", []) if isinstance(row, dict)]
    return sorted({name for name in names if isinstance(name, str) and 0 < len(name) <= 180})[:500]


def call_model(config, prompt, payload):
    endpoint, local = validate_endpoint(config["endpoint"])
    model = config.get("model", "").strip()
    if not model:
        raise ValueError("Escolha um modelo instalado ou disponível na sua conta.")
    if config.get("provider") == "ollama_cloud" and (not local or urllib.parse.urlsplit(endpoint).path != "/api/chat"):
        raise ValueError("A conta Ollama usa a API local. Escolha Outro serviço para um endpoint diferente.")
    if not local and config.get("provider") != "horde" and not config.get("key", "").strip():
        raise ValueError("Informe a chave deste serviço em Configurações.")
    if config.get("provider") == "ollama" and model.endswith(("-cloud", ":cloud")):
        raise ValueError("Esse modelo usa a nuvem. Escolha Nuvem via Ollama em Configurações.")
    if config.get("provider") == "ollama_cloud" and not model.endswith(("-cloud", ":cloud")):
        raise ValueError("Escolha um modelo cloud para a conta Ollama.")
    if config.get("structured"):
        candidates = [row for row in payload.get("evidence", []) if row.get("candidate")]
        if not candidates:
            return {"text": '{"findings":[],"conclusion":"insufficient_data"}',
                    "usage": {"input_tokens": 0, "output_tokens": 0}, "model": "análise local"}
        payload = {"evidence": candidates, "resource_collection": payload.get("resource_collection"),
                   "lost_events": payload.get("lost_events"), "timelines_aligned": payload.get("timelines_aligned"),
                   "symptom_comparison": payload.get("symptom_comparison")}
    if config.get("provider") == "horde":
        if endpoint != PROVIDERS["horde"]["endpoint"]:
            raise ValueError("A opção anônima usa o endpoint oficial do AI Horde.")
        from modules.horde_service import call_anonymous
        return call_anonymous(config, prompt, payload)
    messages = [{"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))}]
    limit = max(128, min(2400, int(config.get("answer_tokens", 900))))
    if local and urllib.parse.urlsplit(endpoint).path == "/api/chat":
        body = {"model": model, "messages": messages, "stream": False,
                "keep_alive": 0, "options": {"num_predict": limit, "num_ctx": 8192}}
        if model.startswith("qwen3"):
            body["think"] = False
        if config.get("structured"):
            body["format"] = "json"
        try:
            result = request_json(endpoint, body=body, timeout=240, limit=256 * 1024)
        except RuntimeError as error:
            if config.get("provider") == "ollama_cloud" and "HTTP 401" in str(error):
                raise RuntimeError("Entre na sua conta pelo Ollama e confira o acesso ao modelo cloud.") from None
            raise
        answer = result.get("message", {}).get("content")
        usage = {"input_tokens": result.get("prompt_eval_count"), "output_tokens": result.get("eval_count")}
    else:
        token_field = "max_completion_tokens" if config.get("provider") == "openai" else "max_tokens"
        body = {"model": model, "messages": messages, "stream": False, token_field: limit}
        if config.get("structured") and config.get("provider") != "custom":
            body["response_format"] = {"type": "json_object"}
        result = request_json(endpoint, config.get("key", ""), body, timeout=120, limit=256 * 1024)
        try:
            answer = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ValueError("Resposta incompatível com Chat Completions.") from None
        source = result.get("usage") or {}
        usage = {"input_tokens": source.get("prompt_tokens"), "output_tokens": source.get("completion_tokens")}
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("O modelo não retornou uma explicação em texto.")
    return {"text": answer[:24000], "usage": usage, "model": model}
