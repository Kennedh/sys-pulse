import io
import json
import threading
from unittest.mock import patch

import pytest
from PySide6.QtCore import QSettings

from modules.activity import ActivityState
from modules.ai_service import PROVIDERS, call_model
from modules.ai_settings import AIConfig, AISettingsPanel
from modules.model_manager import pull_model, validate_model, DownloadCancelled, OllamaRuntime, ollama_base
from modules.setup_wizard import SetupDialog


def stream(lines):
    return io.BytesIO(b"".join(json.dumps(item).encode() + b"\n" for item in lines))


def test_download_stream_reports_layers_and_never_requests_inference():
    progress = []
    response = stream([{"status": "pulling manifest"}, {"status": "pulling layer", "total": 100, "completed": 80},
                       {"status": "success"}])
    with patch("modules.model_manager.urllib.request.build_opener") as factory:
        factory.return_value.open.return_value = response
        assert pull_model(PROVIDERS["ollama"]["endpoint"], "llama3.2:1b", progress.append, lambda: False) == "llama3.2:1b"
    request = factory.return_value.open.call_args.args[0]
    assert request.full_url.endswith("/api/pull")
    assert json.loads(request.data) == {"model": "llama3.2:1b", "stream": True}
    assert progress[1]["completed"] == 80


def test_download_cancel_closes_the_stream():
    response = stream([{"status": "pulling layer", "total": 100, "completed": 1}, {"status": "success"}])
    cancelled = threading.Event()
    with patch("modules.model_manager.urllib.request.build_opener") as factory:
        factory.return_value.open.return_value = response
        with pytest.raises(DownloadCancelled):
            pull_model(PROVIDERS["ollama"]["endpoint"], "llama3.2:1b",
                       lambda item: cancelled.set(), cancelled.is_set)
    assert response.closed


@pytest.mark.parametrize("lines", [
    [{"error": "disk full"}],
    [{"status": "pulling manifest"}],
])
def test_incomplete_download_is_never_reported_as_installed(lines):
    with patch("modules.model_manager.urllib.request.build_opener") as factory:
        factory.return_value.open.return_value = stream(lines)
        with pytest.raises(RuntimeError):
            pull_model(PROVIDERS["ollama"]["endpoint"], "llama3.2:1b", lambda item: None, lambda: False)


@pytest.mark.parametrize("endpoint", ["https://example.com/api/chat", "http://127.0.0.1:1234/v1/chat/completions"])
def test_model_download_requires_native_loopback_api(endpoint):
    with patch("modules.model_manager.urllib.request.build_opener") as request:
        with pytest.raises(ValueError):
            pull_model(endpoint, "llama3.2:1b", lambda item: None, lambda: False)
    request.assert_not_called()


@pytest.mark.parametrize("name", ["../model", "--help", "model;command", "https://example.com/file", "bad name"])
def test_model_name_does_not_accept_paths_urls_or_shell_options(name):
    with pytest.raises(ValueError):
        validate_model(name)


def test_model_setup_blocks_both_capture_and_inference():
    state = ActivityState()
    state.begin_maintenance("models")
    with pytest.raises(RuntimeError):
        state.begin_capture("native")
    with pytest.raises(RuntimeError):
        state.begin_inference()
    state.end_maintenance("another-owner")
    assert state.maintenance == "models"
    state.end_maintenance("models")
    state.begin_capture("native")
    with pytest.raises(RuntimeError):
        state.begin_maintenance("models")


def test_existing_ollama_server_is_borrowed_and_never_terminated():
    runtime = OllamaRuntime()
    with patch("modules.model_manager.request_json", return_value={"version": "test"}), patch("modules.model_manager.subprocess.Popen") as start:
        assert runtime.start(PROVIDERS["ollama"]["endpoint"], lambda: False) == {"version": "test"}
        runtime.close()
    start.assert_not_called()


def test_local_provider_rejects_cloud_model_before_network_request():
    with patch("modules.ai_service.request_json") as request:
        with pytest.raises(ValueError, match="nuvem"):
            call_model({**PROVIDERS["ollama"], "provider": "ollama", "model": "gpt-oss:120b-cloud"}, "", {})
    request.assert_not_called()


def test_cloud_account_uses_native_api_without_user_api_key():
    config = {**PROVIDERS["ollama_cloud"], "provider": "ollama_cloud"}
    response = {"message": {"content": '{"findings":[]}'}, "prompt_eval_count": 12, "eval_count": 3}
    with patch("modules.ai_service.request_json", return_value=response) as request:
        answer = call_model(config, "", {})
    assert request.call_args.args[0] == PROVIDERS["ollama"]["endpoint"]
    assert request.call_args.kwargs["body"]["model"].endswith("-cloud")
    assert not request.call_args.kwargs.get("key")
    assert answer["usage"]["input_tokens"] == 12


def test_model_manager_failure_releases_block_and_does_not_save_model(tmp_path):
    config = AIConfig(settings=QSettings(str(tmp_path / "ai.ini"), QSettings.IniFormat))
    panel = AISettingsPanel(config)
    original = config.model
    try:
        with patch("modules.model_manager_view.pull_model", side_effect=RuntimeError("download failed")):
            panel.models.run_job("pull", "llama3.2:1b")
            from PySide6.QtWidgets import QApplication
            import time
            deadline = time.monotonic() + 3
            while panel.models._working and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(.01)
        assert not config.activity.busy
        assert config.model == original
        assert "download failed" in panel.models.status.text()
    finally:
        panel.shutdown()
        panel.close()


def test_cloud_settings_hide_key_and_offer_account_login(tmp_path):
    config = AIConfig(settings=QSettings(str(tmp_path / "ai.ini"), QSettings.IniFormat))
    panel = AISettingsPanel(config)
    try:
        panel.provider.setCurrentIndex(panel.provider.findData("ollama_cloud"))
        assert panel.key.isHidden()
        assert not panel.models.signin.isHidden()
        assert panel.apply()
        assert config.provider == "ollama_cloud"
        assert config.key == ""
    finally:
        panel.shutdown()
        panel.close()


def test_first_run_never_starts_download_or_inference():
    with patch("modules.model_manager.pull_model") as download, patch("modules.ai_service.call_model") as inference:
        panel = SetupDialog()
        try:
            assert panel.selection() == "integrated"
            panel.choices["local"].setChecked(True)
            assert panel.selection() == "local"
        finally:
            panel.close()
    download.assert_not_called()
    inference.assert_not_called()


def test_anonymous_service_has_no_key_or_login_fields(tmp_path):
    config = AIConfig(settings=QSettings(str(tmp_path / "anonymous.ini"), QSettings.IniFormat))
    panel = AISettingsPanel(config)
    try:
        panel.provider.setCurrentIndex(panel.provider.findData("horde"))
        assert panel.key.isHidden()
        assert panel.remember.isHidden()
        assert panel.models.isHidden()
        assert panel.apply()
        assert config.provider == "horde"
        assert config.model == "auto"
        assert not config.key
    finally:
        panel.shutdown()
        panel.close()


def test_anonymous_call_uses_only_public_identifier_and_bounded_output():
    from modules.horde_service import call_anonymous
    identifier = "d96c6475-f8b2-4a13-8ed5-f7e85df7f5c4"
    answer = '{"findings":[],"conclusion":"insufficient_data"}'
    with patch("modules.horde_service.choose_model", return_value="public/model"), patch("modules.horde_service.request_json") as request:
        request.side_effect = [{"id": identifier}, {"done": True, "generations": [{"text": answer, "model": "public/model"}]}]
        result = call_anonymous({"model": "auto", "key": "never-forward-this"}, "JSON only", {"evidence": []})
    assert result["anonymous"] is True
    first = request.call_args_list[0]
    assert first.kwargs["extra_headers"]["apikey"] == "0000000000"
    assert "key" not in first.kwargs
    assert first.kwargs["body"]["params"]["max_length"] == 256
    assert "never-forward-this" not in json.dumps(first.kwargs)


def test_anonymous_cancel_deletes_only_its_own_job():
    from modules.horde_service import call_anonymous
    identifier = "d96c6475-f8b2-4a13-8ed5-f7e85df7f5c4"
    cancelled = threading.Event()
    with patch("modules.horde_service.choose_model", return_value="public/model"), patch("modules.horde_service.request_json") as request, patch("modules.horde_service.time.sleep", side_effect=lambda seconds: cancelled.set()):
        request.side_effect = [{"id": identifier}, {"done": False, "queue_position": 1}, {}]
        with pytest.raises(RuntimeError, match="cancelada"):
            call_anonymous({"model": "auto", "_cancelled": cancelled.is_set}, "", {"evidence": []})
    assert request.call_args.kwargs["method"] == "DELETE"
    assert request.call_args.args[0].endswith("/" + identifier)


def test_anonymous_timeout_removes_pending_request():
    from modules.horde_service import call_anonymous
    identifier = "d96c6475-f8b2-4a13-8ed5-f7e85df7f5c4"
    with patch("modules.horde_service.choose_model", return_value="public/model"), patch("modules.horde_service.request_json") as request, patch("modules.horde_service.time.monotonic", side_effect=[0, 91]):
        request.side_effect = [{"id": identifier}, {}]
        with pytest.raises(RuntimeError, match="90 s"):
            call_anonymous({"model": "auto"}, "", {"evidence": []})
    assert request.call_args.kwargs["method"] == "DELETE"


def test_anonymous_job_id_cannot_change_request_destination():
    from modules.horde_service import call_anonymous
    with patch("modules.horde_service.choose_model", return_value="public/model"), patch("modules.horde_service.request_json", return_value={"id": "../other-account"}) as request:
        with pytest.raises(ValueError):
            call_anonymous({"model": "auto"}, "", {"evidence": []})
    assert request.call_count == 1


def test_no_anonymous_request_without_candidate_evidence():
    config = {**PROVIDERS["horde"], "provider": "horde", "structured": True}
    with patch("modules.horde_service.call_anonymous") as request:
        result = call_model(config, "", {"evidence": []})
    request.assert_not_called()
    assert result["usage"] == {"input_tokens": 0, "output_tokens": 0}
