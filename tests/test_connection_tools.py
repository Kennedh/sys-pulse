import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox

from modules.ai_service import PROVIDERS, call_model, list_models
from modules.ai_settings import AIConfig, AISettingsPanel
from modules.ai_summary import AISummaryPanel
from modules.diagnostic_tools import read_latency_report, download_latencymon, OfficialRedirect
from modules.frametimes import FrameCapture
from modules.stress_gpu import FrameTiming


def config_at(path):
    config = AIConfig(settings=QSettings(str(path / "ai.ini"), QSettings.IniFormat))
    config.demo = True
    return config


def test_claude_uses_native_messages_and_actual_model():
    config = {**PROVIDERS["anthropic"], "provider": "anthropic", "model": "claude-selected",
              "key": "test-key", "answer_tokens": 400}
    response = {"model": "claude-effective", "content": [{"type": "text", "text": "answer"}],
                "usage": {"input_tokens": 12, "output_tokens": 3}}
    with patch("modules.ai_service.request_json", return_value=response) as request:
        answer = call_model(config, "prompt", {"evidence": []})
    args, kwargs = request.call_args
    assert args[0] == "https://api.anthropic.com/v1/messages"
    assert kwargs["extra_headers"]["x-api-key"] == "test-key"
    assert kwargs["body"]["system"] == "prompt"
    assert kwargs["body"]["messages"][0]["role"] == "user"
    assert kwargs["body"]["max_tokens"] == 400
    assert answer["model"] == "claude-effective" and answer["usage"]["input_tokens"] == 12


def test_claude_models_require_key_and_remove_retired():
    config = {**PROVIDERS["anthropic"], "provider": "anthropic", "key": "test-key"}
    with patch("modules.ai_service.request_json", return_value={"data": [
            {"id": "claude-available"}, {"id": "claude-retired", "lifecycle": "retired"}]}) as request:
        assert list_models(config) == ["claude-available"]
    assert request.call_args.kwargs["extra_headers"]["x-api-key"] == "test-key"
    with patch("modules.ai_service.request_json") as request, pytest.raises(ValueError):
        list_models({**config, "key": ""})
    request.assert_not_called()


def test_cloud_and_local_models_do_not_mix():
    response = {"models": [{"name": "llama3.2:3b"}, {"name": "gpt-oss:120b-cloud"}]}
    with patch("modules.ai_service.request_json", return_value=response):
        assert list_models({**PROVIDERS["ollama"], "provider": "ollama"}) == ["llama3.2:3b"]
        assert list_models({**PROVIDERS["ollama_cloud"], "provider": "ollama_cloud"}) == ["gpt-oss:120b-cloud"]


def test_service_keys_and_models_are_remembered_separately(tmp_path):
    config = config_at(tmp_path)
    for provider, model, key in (("anthropic", "claude-model", "claude-secret"), ("gemini", "gemini-model", "gemini-secret")):
        config.save({**PROVIDERS[provider], "provider": provider, "model": model, "key": key})
    assert config.preferences("anthropic")["key"] == "claude-secret"
    assert config.preferences("anthropic")["model"] == "claude-model"
    assert config.preferences("gemini")["key"] == "gemini-secret"
    config.settings.sync()
    assert "secret" not in (tmp_path / "ai.ini").read_text(encoding="utf-8")


def test_stale_discovery_cannot_replace_new_provider(tmp_path):
    config = config_at(tmp_path)
    panel = AISettingsPanel(config)
    panel.choose_mode("advanced")
    old = panel._generation
    panel.service.setCurrentIndex(panel.service.findData("gemini"))
    panel.accept_models(old, ["claude-old"], "")
    assert panel.provider.currentData() == "gemini"
    assert panel.model.findData("claude-old") == -1


def test_connecting_applies_available_model_without_inference(tmp_path):
    config = config_at(tmp_path)
    panel = AISettingsPanel(config)
    panel.choose_mode("ollama")
    with patch("modules.ai_service.call_model") as inference:
        panel.accept_models(panel._generation, ["llama3.2:1b", "llama3.2:3b"], "")
    inference.assert_not_called()
    assert config.model == "llama3.2:3b" and config.is_verified
    assert "llama3.2:3b" in panel.active.text()
    assert "conferida" in panel.active.text()


def test_integrated_can_be_chosen_from_invalid_custom_form(tmp_path):
    config = config_at(tmp_path)
    panel = AISettingsPanel(config)
    panel.choose_mode("advanced")
    panel.service.setCurrentIndex(panel.service.findData("custom"))
    panel.endpoint.setText("invalid")
    panel.choose_mode("integrated")
    assert not config.enabled


def test_response_provenance_is_saved_and_survives_selection_change(tmp_path):
    config = config_at(tmp_path)
    panel = AISummaryPanel(config)
    panel.set_result({"source": str(tmp_path)})
    panel.accept(panel._generation, {"text": "evidence checked", "provider": "anthropic",
                 "provider_name": "Claude", "requested_model": "alias", "model": "claude-effective",
                 "analyzed_at": "2026-11-01T12:00:00", "usage": {"input_tokens": 0, "output_tokens": 0}})
    config.save({**PROVIDERS["ollama"], "provider": "ollama", "key": "secret-must-not-be-saved"})
    assert "claude-effective" in panel.used.text() and "Ollama" in panel.choice.text()
    data = (tmp_path / "ia.json").read_text(encoding="utf-8")
    assert "secret" not in data and "endpoint" not in data
    panel.set_result({"source": str(tmp_path)})
    assert "claude-effective" in panel.used.text() and "salva" in panel.used.text()
    assert panel.answer.toPlainText() == "evidence checked"


def test_saved_answer_is_not_reused_for_different_capture(tmp_path):
    config = config_at(tmp_path)
    panel = AISummaryPanel(config)
    panel.set_result({"source": str(tmp_path)})
    panel.accept(panel._generation, {"text": "previous", "model": "model"})
    panel.set_result({"source": str(tmp_path), "summary": {"duration_s": 42}})
    assert not panel.answer.toPlainText()
    (tmp_path / "ia.json").write_text("[]", encoding="utf-8")
    panel.set_result({"source": str(tmp_path)})


def test_frame_reader_preserves_partial_rows_and_separates_swapchains(tmp_path):
    path = tmp_path / "frametimes.csv"
    path.write_text("ProcessID,SwapChainAddress,CPUStartQPCTime,FrameTime\n10,a,100000,16\n10,b,100010,100\n10,a,100016,", encoding="utf-8")
    capture = FrameCapture()
    capture.path, capture.pid = path, 10
    assert capture.live_snapshot()["frames"] == 1
    with path.open("a", encoding="utf-8") as file:
        file.write("16\n10,a,100032,16\n99,a,100048,900\n")
    result = capture.live_snapshot()
    assert result["frames"] == 3 and result["swapchain"] == "a"
    assert result["fps"] == 62.5 and result["p99_ms"] == 16
    with patch("modules.frametimes.time.monotonic", return_value=capture.live_updated+5):
        assert capture.live_snapshot()["state"] == "stale"


def test_frame_reader_caps_memory_and_read_volume(tmp_path):
    path = tmp_path / "frametimes.csv"
    path.write_text("ProcessID,FrameTime\n" + "10,16\n"*200000, encoding="utf-8")
    capture = FrameCapture()
    capture.path, capture.pid = path, 10
    result = capture.live_snapshot()
    assert result["backlog"] and capture.live_offset <= 1024*1024
    assert len(capture.live_rows) <= 4000


def test_gpu_percentiles_include_long_stalls_without_unbounded_memory():
    stats = FrameTiming()
    for value in [16]*98+[50,2500]:
        stats.add(value)
    result = stats.summary()
    assert result["frametime_p95_ms"] == 16
    assert result["frametime_p99_ms"] == 50
    assert result["frametime_max_ms"] == 2500
    assert result["frametime_overflow"] == 1
    assert result["fps"] == pytest.approx(100000/(16*98+50+2500))


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "cp1252"])
def test_latencymon_report_handles_windows_encodings(tmp_path, encoding):
    path = tmp_path / "latency.txt"
    path.write_bytes("LatencyMon · relatório de latência".encode(encoding))
    assert "relatório" in read_latency_report(path)


def test_unrelated_and_oversized_latency_report_are_rejected(tmp_path):
    path = tmp_path / "bad.txt"
    path.write_text("unrelated")
    with pytest.raises(ValueError):
        read_latency_report(path)
    path.write_bytes(b"x"*(2*1024*1024+1))
    with pytest.raises(ValueError):
        read_latency_report(path)


@pytest.mark.parametrize("publisher,status,success", [
    ("CN=SOFTREV LABS S.R.L.S., O=SOFTREV LABS S.R.L.S., C=IT", "Valid", True),
    ("CN=Unknown, O=Unknown", "Valid", False),
    ("CN=SOFTREV LABS S.R.L.S., O=SOFTREV LABS S.R.L.S.", "HashMismatch", False)])
def test_latency_installer_requires_valid_known_publisher(tmp_path, publisher, status, success):
    response = io.BytesIO(b"MZ"+b"x"*65536)
    with patch("modules.diagnostic_tools.platform.system", return_value="Windows"), \
         patch("urllib.request.OpenerDirector.open", return_value=response), \
         patch("modules.diagnostic_tools.run_powershell", return_value={"publisher": publisher, "status": status}):
        if success:
            assert Path(download_latencymon(tmp_path)).is_file()
        else:
            with pytest.raises(ValueError):
                download_latencymon(tmp_path)
    assert not (tmp_path / "LatencyMon-Setup.part").exists()


def test_latency_redirect_cannot_leave_official_site():
    handler = OfficialRedirect()
    with pytest.raises(ValueError):
        handler.redirect_request(None, None, 302, "", {}, "https://other.example/file.exe")


def test_tools_scan_is_blocked_during_capture():
    from modules.activity import ActivityState
    from modules.diagnostic_tools_view import DiagnosticToolsPanel
    activity = ActivityState()
    panel = DiagnosticToolsPanel(activity)
    activity.begin_capture("native")
    with patch("modules.diagnostic_tools_view.query_driver_updates") as query:
        panel.run("updates")
    query.assert_not_called()
    assert not panel.query.isEnabled()


@pytest.mark.parametrize("encoding", ["utf-16", "utf-8-sig"])
def test_presentmon_stream_is_normalized_before_live_read(tmp_path, encoding):
    from types import SimpleNamespace
    stream = io.BytesIO("ProcessID,FrameTime\r\n10,16\r\n".encode(encoding))
    capture = FrameCapture()
    capture.process = SimpleNamespace(stdout=stream)
    capture.path, capture.pid = tmp_path / "frametimes.csv", 10
    with capture.path.open("wb") as capture.output:
        capture._copy_output()
    assert capture.stream_error is None
    assert capture.path.read_text(encoding="utf-8").startswith("ProcessID")
    assert capture.live_snapshot()["fps"] == 62.5


def test_stress_context_is_kept_without_process_identity():
    from modules.ai_summary import ai_payload
    from modules.ai_contract import render_explanation
    payload = ai_payload({"stress": {"kind": "gpu", "state": "completed", "elapsed_s": 30,
                                     "renderer": "private-device", "path": "private-path"}})
    assert payload["stress"] == {"kind": "gpu", "state": "completed", "elapsed_s": 30}
    assert "private" not in json.dumps(payload)
    assert "carga induzida" in render_explanation('{"findings":[]}', payload)


def test_gpu_fault_log_works_without_console(tmp_path):
    import faulthandler
    import sys
    from modules.stress_gpu import run_gpu
    enabled = faulthandler.is_enabled()
    try:
        with patch.object(sys, "stderr", None), patch("modules.stress_gpu.render_gpu", return_value=0):
            assert run_gpu(tmp_path, {}) == 0
        assert (tmp_path / "gpu-fault.log").is_file()
    finally:
        if enabled:
            faulthandler.enable()


def test_gpu_start_failure_preserves_reason_for_interface(tmp_path):
    from modules.stress import run_worker
    (tmp_path / "request.json").write_text(json.dumps({"kind": "gpu", "duration_s": 1}))
    with patch("modules.stress_gpu.run_gpu", side_effect=RuntimeError("context unavailable")):
        assert run_worker(tmp_path) == 1
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["state"] == "failed" and result["errors"] is None
    assert "context unavailable" in result["reason"]
