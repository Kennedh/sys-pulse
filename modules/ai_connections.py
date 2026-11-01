import re
import urllib.parse

from modules.ai_providers import PROVIDERS, API_FORMATS, AUTH_MODES


SUFFIXES = {"/chat/completions": "chat", "/responses": "responses", "/messages": "messages", "/api/chat": "ollama"}


def address_parts(address):
    address = str(address).strip().rstrip("/")
    parsed = urllib.parse.urlsplit(address)
    local = parsed.hostname in ("127.0.0.1", "localhost", "::1")
    try:
        parsed.port
    except ValueError:
        raise ValueError("Porta inválida no endereço do servidor.") from None
    if (len(address) > 2048 or not parsed.hostname or parsed.username or parsed.password or parsed.query
            or parsed.fragment or any(char.isspace() for char in address)):
        raise ValueError("Informe um endereço sem credenciais, parâmetros ou fragmentos.")
    if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
        raise ValueError("Use HTTPS para serviços externos; HTTP é permitido apenas em loopback.")
    return address, parsed, local


def endpoint_format(endpoint):
    path = urllib.parse.urlsplit(endpoint).path.rstrip("/")
    return next((value for suffix, value in SUFFIXES.items() if path.endswith(suffix)), "auto")


def normalize_endpoint(address, api_format="auto"):
    address, parsed, _ = address_parts(address)
    if api_format not in API_FORMATS:
        raise ValueError("Escolha um formato de API disponível.")
    detected = endpoint_format(address)
    if api_format == "auto":
        api_format = detected
        if api_format == "auto":
            api_format = ("ollama" if parsed.port == 11434 or parsed.path.endswith(("/api", "/api/tags")) else
                          "messages" if parsed.hostname == "api.anthropic.com" else
                          "responses" if parsed.hostname == "api.openai.com" else "chat")
    if detected == api_format:
        return address, api_format
    path = parsed.path.rstrip("/")
    if detected != "auto":
        path = path[:-len(next(suffix for suffix, value in SUFFIXES.items() if value == detected))]
    elif path.endswith("/models"):
        path = path[:-len("/models")]
    elif path.endswith("/api/tags"):
        path = path[:-len("/tags")]
    if api_format == "ollama":
        path = path + "/chat" if path.endswith("/api") else path + "/api/chat"
    else:
        path = (path or "/v1") + {"chat": "/chat/completions", "responses": "/responses", "messages": "/messages"}[api_format]
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", "")), api_format


def connection(config):
    provider = config.get("provider", "custom")
    endpoint = config.get("endpoint", "")
    if provider == "horde":
        if endpoint.rstrip("/") != PROVIDERS["horde"]["endpoint"]:
            raise ValueError("A opção anônima usa o endereço oficial do AI Horde.")
        return endpoint.rstrip("/"), "horde", False
    endpoint, api_format = normalize_endpoint(endpoint, config.get("api_format", "auto"))
    _, _, local = address_parts(endpoint)
    if provider in PROVIDERS and provider != "custom":
        expected = PROVIDERS[provider]["endpoint"]
        expected_parts = urllib.parse.urlsplit(expected)
        parts = urllib.parse.urlsplit(endpoint)
        if not local and (parts.scheme, parts.netloc) != (expected_parts.scheme, expected_parts.netloc):
            raise ValueError("O endereço não corresponde ao serviço escolhido. Use Outro serviço para um servidor personalizado.")
    return endpoint, api_format, local


def credential_options(config, api_format, local):
    provider = config.get("provider", "custom")
    preset = PROVIDERS.get(provider, {})
    mode = config.get("auth_mode", preset.get("auth_mode", "auto"))
    if mode not in AUTH_MODES:
        raise ValueError("Forma de autenticação inválida.")
    key = config.get("key", "").strip()
    if preset.get("requires_key", not local) and not key:
        raise ValueError("Conecte sua conta ou informe a chave deste serviço em Configurações.")
    headers = {"anthropic-version": "2023-06-01"} if api_format == "messages" else {}
    if mode == "auto":
        mode = "x-api-key" if api_format == "messages" else "bearer"
    if mode in ("x-api-key", "api-key") and key:
        headers[mode] = key
    return key if mode == "bearer" else "", headers


def catalog_url(endpoint, api_format):
    suffix = next(suffix for suffix, value in SUFFIXES.items() if value == api_format)
    return endpoint[:-len(suffix)] + ("/api/tags" if api_format == "ollama" else "/models")


def compatible_models(rows, provider):
    names = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("id") or row.get("name")
        if not isinstance(name, str) or not 0 < len(name) <= 180 or any(ord(char) < 32 for char in name):
            continue
        if row.get("lifecycle") in ("retired", "deprecated") or row.get("active") is False:
            continue
        capabilities = row.get("capabilities") or {}
        if isinstance(capabilities, dict) and capabilities.get("completion_chat") is False:
            continue
        if row.get("type") in ("embedding", "image", "audio", "rerank") or row.get("object") == "embedding":
            continue
        architecture = row.get("architecture") or {}
        outputs = row.get("output_modalities") or (architecture.get("output_modalities") if isinstance(architecture, dict) else None)
        if isinstance(outputs, list) and outputs and "text" not in outputs:
            continue
        if provider not in ("ollama", "ollama_cloud", "custom", "lmstudio"):
            if any(token in name.lower() for token in ("embedding", "whisper", "tts", "rerank", "moderation", "dall-e", "realtime", "transcri")):
                continue
            if provider == "openai" and (not (name.startswith(("gpt-", "chatgpt-", "ft:gpt-")) or re.match(r"o\d+(?:-|$)", name))
                                        or any(token in name.lower() for token in ("image", "audio", "search", "realtime"))):
                continue
        if provider in ("ollama", "ollama_cloud") and name.endswith(("-cloud", ":cloud")) != (provider == "ollama_cloud"):
            continue
        names.add(name)
    return sorted(names)[:500]
