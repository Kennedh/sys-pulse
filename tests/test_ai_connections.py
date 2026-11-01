import base64
import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from modules.ai_connections import normalize_endpoint, connection, compatible_models
from modules.ai_providers import PROVIDERS
from modules.ai_service import call_model, list_models
from modules.ai_settings import AIConfig, AISettingsPanel
from modules.ai_login import BrowserLogin


def make_config(folder):
    config = AIConfig(settings=QSettings(str(folder / "ai.ini"), QSettings.IniFormat))
    config.demo = True
    return config


@pytest.mark.parametrize("address,wire,expected", [
    ("http://localhost:1234", "auto", "http://localhost:1234/v1/chat/completions"),
    ("http://127.0.0.1:11434", "auto", "http://127.0.0.1:11434/api/chat"),
    ("http://localhost:11434/api/tags", "auto", "http://localhost:11434/api/chat"),
    ("https://server.example/v1/", "chat", "https://server.example/v1/chat/completions"),
    ("https://server.example/proxy/v1/models", "chat", "https://server.example/proxy/v1/chat/completions"),
    ("https://server.example/v1/chat/completions", "responses", "https://server.example/v1/responses"),
    ("https://server.example", "messages", "https://server.example/v1/messages"),
    ("https://server.example/api", "ollama", "https://server.example/api/chat"),
    ("https://api.anthropic.com", "auto", "https://api.anthropic.com/v1/messages"),
    ("https://api.openai.com", "auto", "https://api.openai.com/v1/responses"),
])
def test_base_addresses_and_format_switch_preserve_prefix(address, wire, expected):
    assert normalize_endpoint(address, wire)[0] == expected


@pytest.mark.parametrize("address", ["http://external.example/v1", "https://key@external.example/v1",
                                     "https://external.example/v1?key=secret", "https://external.example:invalid/v1",
                                     "https://external.example/v1#secret"])
def test_connection_rejects_insecure_or_credential_bearing_address(address):
    with pytest.raises(ValueError):
        normalize_endpoint(address)


@pytest.mark.parametrize("provider", ["deepseek", "groq", "mistral", "xai", "together", "huggingface"])
def test_direct_provider_lists_models_and_sends_compatible_request(provider):
    config = {**PROVIDERS[provider], "provider": provider, "key": "test-token", "model": "chat-model"}
    with patch("modules.ai_service.request_json", return_value={"data": [
            {"id": "chat-model"}, {"id": "embedding-model", "type": "embedding"}]}) as request:
        assert list_models(config) == ["chat-model"]
    assert request.call_args.args[0].endswith("/models")
    assert request.call_args.args[1] == "test-token"
    response = {"model": "effective-model", "choices": [{"message": {"content": '{"findings":[]}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4}}
    with patch("modules.ai_service.request_json", return_value=response) as request:
        result = call_model(config, "prompt", {})
    assert result["model"] == "effective-model"
    assert request.call_args.kwargs["key"] == "test-token"
    assert request.call_args.kwargs["body"]["messages"][0]["content"] == "prompt"


def test_openrouter_uses_account_filtered_catalog():
    config = {**PROVIDERS["openrouter"], "provider": "openrouter", "key": "test-token"}
    with patch("modules.ai_service.request_json", return_value={"data": [{"id": "provider/model:free"}]}) as request:
        assert list_models(config) == ["provider/model:free"]
    assert request.call_args.args[0] == "https://openrouter.ai/api/v1/models/user"


def test_declared_capabilities_remove_non_chat_models():
    rows = [{"id": "chat", "capabilities": {"completion_chat": True}},
            {"id": "vision-chat", "output_modalities": ["text"]},
            {"id": "fim", "capabilities": {"completion_chat": False}},
            {"id": "picture", "architecture": {"output_modalities": ["image"]}},
            {"id": "inactive", "active": False}]
    assert compatible_models(rows, "mistral") == ["chat", "vision-chat"]


def test_openai_responses_and_legacy_chat_remain_available():
    response = {"status": "completed", "model": "effective", "output": [
        {"type": "reasoning", "content": [{"type": "output_text", "text": "ignore"}]},
        {"type": "message", "content": [{"type": "output_text", "text": '{"findings":[]}'}]}],
        "usage": {"input_tokens": 20, "output_tokens": 5}}
    config = {**PROVIDERS["openai"], "provider": "openai", "key": "test-token", "model": "available"}
    with patch("modules.ai_service.request_json", return_value=response) as request:
        result = call_model(config, "prompt", {})
    body = request.call_args.kwargs["body"]
    assert request.call_args.args[0].endswith("/responses")
    assert body["store"] is False and body["instructions"] == "prompt"
    assert body["max_output_tokens"] == 900
    assert result["text"] == '{"findings":[]}' and result["usage"]["input_tokens"] == 20
    legacy = {**config, "endpoint": "https://api.openai.com/v1/chat/completions"}
    with patch("modules.ai_service.request_json", return_value={"choices": [{"message": {"content": "answer"}}]}) as request:
        call_model(legacy, "prompt", {})
    assert "max_completion_tokens" in request.call_args.kwargs["body"]


@pytest.mark.parametrize("wire,response", [
    ("chat", {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}),
    ("responses", {"status": "incomplete", "output": []}),
    ("messages", {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "partial"}]})
])
def test_incomplete_answers_are_not_accepted_as_complete(wire, response):
    config = {"provider": "custom", "endpoint": "https://server.example/v1", "api_format": wire, "model": "model"}
    with patch("modules.ai_service.request_json", return_value=response) as request:
        with pytest.raises(ValueError):
            call_model(config, "prompt", {})
    assert request.call_count == 1


@pytest.mark.parametrize("mode,header", [("bearer", "Authorization"), ("api-key", "api-key"), ("x-api-key", "x-api-key"), ("none", None)])
def test_custom_authentication_is_used_for_discovery_and_analysis(mode, header):
    config = {"provider": "custom", "endpoint": "https://server.example/v1", "model": "model",
              "api_format": "chat", "auth_mode": mode, "key": "test-token"}
    with patch("modules.ai_service.request_json", return_value={"data": [{"id": "model"}]}) as request:
        list_models(config)
    key, extra = request.call_args.args[1], request.call_args.kwargs["extra_headers"]
    assert key == ("test-token" if mode == "bearer" else "")
    assert extra.get(header) == ("test-token" if mode in ("api-key", "x-api-key") else None)
    with patch("modules.ai_service.request_json", return_value={"choices": [{"message": {"content": "text"}}]}) as request:
        call_model(config, "prompt", {})
    assert request.call_args.kwargs["key"] == key
    assert request.call_args.kwargs["extra_headers"] == extra


def test_custom_messages_protocol_is_not_tied_to_anthropic_host():
    config = {"provider": "custom", "endpoint": "https://server.example/v1", "api_format": "messages",
              "key": "test-token", "model": "model"}
    response = {"content": [{"type": "text", "text": "answer"}], "model": "effective", "usage": {"input_tokens": 2}}
    with patch("modules.ai_service.request_json", return_value=response) as request:
        assert call_model(config, "system", {})["model"] == "effective"
    assert request.call_args.kwargs["extra_headers"]["x-api-key"] == "test-token"
    assert request.call_args.kwargs["body"]["system"] == "system"


def test_messages_catalog_follows_bounded_pagination():
    config = {**PROVIDERS["anthropic"], "provider": "anthropic", "key": "test-token"}
    pages = [{"data": [{"id": "model-a"}], "has_more": True, "last_id": "cursor/a"},
             {"data": [{"id": "model-b"}], "has_more": False}]
    with patch("modules.ai_service.request_json", side_effect=pages) as request:
        assert list_models(config) == ["model-a", "model-b"]
    assert "after_id=cursor%2Fa" in request.call_args.args[0]


def test_known_provider_cannot_forward_key_to_another_remote_host():
    config = {**PROVIDERS["groq"], "provider": "groq", "endpoint": "https://other.example/v1/chat/completions",
              "key": "test-token"}
    with patch("modules.ai_service.request_json") as request, pytest.raises(ValueError):
        list_models(config)
    request.assert_not_called()


def test_custom_address_change_clears_previous_server_credential(tmp_path):
    config = make_config(tmp_path)
    config.save({"provider": "custom", "endpoint": "https://first.example/v1", "model": "model", "key": "first-token"})
    panel = AISettingsPanel(config)
    panel.endpoint.setText("https://second.example/v1")
    panel.address_edited()
    assert panel.key.text() == "" and not panel.remember.isChecked()


def test_connection_format_and_auth_are_remembered_per_service(tmp_path):
    config = make_config(tmp_path)
    config.save({"provider": "custom", "endpoint": "https://server.example/v1", "model": "model",
                 "api_format": "messages", "auth_mode": "bearer", "key": "test-token"})
    config.save({**PROVIDERS["groq"], "provider": "groq", "model": "groq-model", "key": "groq-token"})
    saved = config.preferences("custom")
    assert saved["api_format"] == "messages" and saved["auth_mode"] == "bearer"
    assert saved["endpoint"] == "https://server.example/v1/messages"
    config.settings.sync()
    text = (tmp_path / "ai.ini").read_text(encoding="utf-8")
    assert "test-token" not in text and "groq-token" not in text


def test_manual_model_survives_missing_catalog_without_false_verification(tmp_path):
    config = make_config(tmp_path)
    panel = AISettingsPanel(config)
    panel.choose_mode("advanced")
    panel.service.setCurrentIndex(panel.service.findData("custom"))
    panel.endpoint.setText("http://localhost:1234/v1")
    panel.accept_models(panel._generation, [], "HTTP 404: catálogo ausente")
    panel.model.setEditText("my-model")
    assert panel.apply()
    assert config.model == "my-model" and not config.is_verified
    assert config.endpoint == "http://localhost:1234/v1/chat/completions"


def test_provider_search_selects_matching_service(tmp_path):
    panel = AISettingsPanel(make_config(tmp_path))
    panel.choose_mode("advanced")
    panel.service.setEditText("Groq")
    panel.finish_service_search()
    assert panel.provider.currentData() == "groq"
    assert panel.login_row.isHidden()
    panel.service.setEditText("OpenRouter")
    panel.finish_service_search()
    assert panel.provider.currentData() == "openrouter"
    assert not panel.login_row.isHidden()


def callback_request(login, query, path=None):
    url = "http://127.0.0.1:" + str(login.server.server_port) + (path or login.callback_path) + "?" + query
    request = urllib.request.Request(url, headers={"Host": login.host})
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=3)


def test_browser_pkce_callback_exchanges_only_code_and_verifier():
    login = BrowserLogin()
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(login.url).query)
    expected = base64.urlsafe_b64encode(hashlib.sha256(login.verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    assert query["code_challenge"] == [expected] and query["code_challenge_method"] == ["S256"]
    assert login.verifier not in login.url
    assert login.server.server_address[0] == "127.0.0.1"
    cancelled = threading.Event()
    with patch("modules.ai_login.request_json", return_value={"key": "test-authorized-token"}) as exchange, ThreadPoolExecutor(1) as pool:
        future = pool.submit(login.wait, cancelled.is_set)
        try:
            with pytest.raises(urllib.error.HTTPError) as error:
                callback_request(login, "code=wrong", path="/wrong-path")
            assert error.value.code == 404 and login.code is None
            with callback_request(login, "code=authorized-code") as response:
                assert b"test-authorized-token" not in response.read()
            assert future.result(timeout=3) == "test-authorized-token"
        finally:
            cancelled.set()
            login.close()
    body = exchange.call_args.kwargs["body"]
    assert body["code"] == "authorized-code" and body["code_challenge_method"] == "S256"
    assert login.closed and login.code is None and not login.verifier


def test_browser_login_cancellation_and_timeout_do_not_exchange():
    with patch("modules.ai_login.request_json") as exchange:
        login = BrowserLogin()
        with pytest.raises(RuntimeError, match="cancelada"):
            login.wait(lambda: True)
        assert login.closed
        login = BrowserLogin()
        with pytest.raises(RuntimeError, match="tempo"):
            login.wait(timeout=0)
        assert login.closed
    exchange.assert_not_called()


def test_browser_authorization_denial_keeps_no_credential():
    login = BrowserLogin()
    cancelled = threading.Event()
    with patch("modules.ai_login.request_json") as exchange, ThreadPoolExecutor(1) as pool:
        future = pool.submit(login.wait, cancelled.is_set)
        try:
            with callback_request(login, "error=access_denied"):
                pass
            with pytest.raises(RuntimeError, match="recusada"):
                future.result(timeout=3)
        finally:
            cancelled.set()
            login.close()
    exchange.assert_not_called()


def test_browser_login_is_not_started_during_capture(tmp_path):
    config = make_config(tmp_path)
    config.demo = False
    panel = AISettingsPanel(config)
    config.activity.begin_capture("native")
    with patch("modules.ai_login.BrowserLogin") as login:
        panel.login()
    login.assert_not_called()


def test_late_login_result_cannot_replace_another_service(tmp_path):
    config = make_config(tmp_path)
    panel = AISettingsPanel(config)
    panel.choose_mode("advanced")
    generation = panel._generation
    panel.service.setCurrentIndex(panel.service.findData("groq"))
    panel.accept_login(generation, "old-authorized-token", "")
    assert not panel.key.text()
    assert config.provider != "openrouter"


def test_changing_key_invalidates_previous_catalog_and_active_button(tmp_path):
    config = make_config(tmp_path)
    config.save({**PROVIDERS["groq"], "provider": "groq", "model": "model", "key": "first-token"})
    panel = AISettingsPanel(config)
    panel.accept_models(panel._generation, ["model"], "")
    assert config.is_verified
    panel.key.setText("second-token")
    panel.credential_edited()
    assert not panel._known_models
    assert panel.save.text() == "Usar este modelo"


def test_custom_connection_changes_do_not_claim_model_is_already_in_use(tmp_path):
    config = make_config(tmp_path)
    config.save({"provider": "custom", "endpoint": "https://first.example/v1", "model": "model", "key": "token"})
    panel = AISettingsPanel(config)
    panel.endpoint.setText("https://second.example/v1")
    panel.update_active()
    assert panel.save.text() == "Usar este modelo"


def test_browser_authorization_populates_models_without_starting_inference(tmp_path):
    config = make_config(tmp_path)
    config.demo = False
    panel = AISettingsPanel(config)
    panel.choose_mode("advanced")
    panel.auto_timer.stop()
    with patch("modules.ai_login.BrowserLogin") as factory, \
         patch("modules.ai_settings.QDesktopServices.openUrl", return_value=True), \
         patch("modules.ai_settings.list_models", return_value=["openrouter/free"]) as catalog, \
         patch("modules.ai_service.call_model") as inference:
        login = factory.return_value
        login.host = "localhost:12345"
        login.url = "https://openrouter.ai/auth"
        login.wait.return_value = "authorized-user-token"
        panel.login()
        deadline = time.monotonic()+3
        while (panel._auth_busy or panel._busy or config.activity.busy) and time.monotonic()<deadline:
            QApplication.processEvents()
            time.sleep(.01)
        QApplication.processEvents()
    assert config.provider == "openrouter" and config.is_verified
    assert config.key == "authorized-user-token"
    assert catalog.call_args.args[0]["key"] == "authorized-user-token"
    inference.assert_not_called()
    config.settings.sync()
    assert "authorized-user-token" not in (tmp_path / "ai.ini").read_text(encoding="utf-8")


@pytest.mark.parametrize("wire", ["chat", "responses", "messages", "ollama"])
def test_custom_protocol_works_over_http_without_provider_sdk(wire):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    seen = []
    class Service(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def respond(self, value):
            raw = json.dumps(value).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def do_GET(self):
            seen.append(("GET", self.path))
            self.respond({"models": [{"name": "test-model"}]} if self.path.endswith("/api/tags")
                         else {"data": [{"id": "test-model"}]})
        def do_POST(self):
            seen.append(("POST", self.path))
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert body["model"] == "test-model"
            assert (self.headers.get("x-api-key") if wire == "messages" else self.headers.get("Authorization")) == (
                "test-token" if wire == "messages" else "Bearer test-token")
            if wire == "responses":
                value = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "answer"}]}]}
            elif wire == "messages":
                value = {"content": [{"type": "text", "text": "answer"}]}
            elif wire == "ollama":
                value = {"message": {"content": "answer"}}
            else:
                value = {"choices": [{"message": {"content": "answer"}}]}
            self.respond({**value, "model": "effective-model"})
    server = ThreadingHTTPServer(("127.0.0.1", 0), Service)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
    thread.start()
    config = {"provider": "custom", "endpoint": "http://127.0.0.1:"+str(server.server_port),
              "api_format": wire, "key": "test-token", "model": "test-model"}
    try:
        assert list_models(config) == ["test-model"]
        assert [row[0] for row in seen] == ["GET"]
        result = call_model(config, "prompt", {})
        assert result["model"] == "effective-model" and result["text"] == "answer"
        assert [row[0] for row in seen] == ["GET", "POST"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
