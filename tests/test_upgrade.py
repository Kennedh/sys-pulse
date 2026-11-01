import ctypes
import gzip
import io
import json
import os
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from modules.activity import ActivityState
from modules.ai_contract import render_explanation
from modules.ai_service import call_model, list_models, PROVIDERS
from modules.ai_settings import AIConfig
from modules.ai_summary import AISummaryPanel, ai_payload
from modules.analysis import analyze_session
from modules.diagnostics import SessionRecorder
from modules.frametimes import analyze_frames, FrameCapture
from modules.monitor import MonitorWorker
from modules.network import ping_statistics, validate_host
from modules.windows_processes import ProcessTimes, decode_process_times, WindowsProcessTimes
from modules.wpr_profile import write_profile


def row(at, **extra):
    return {"timestamp": str(at), "monotonic": at, "cpu_percent": 20,
            "cpu_max_core": 30, "ram_percent": 40, "target_interval_ms": 500,
            "process_age_ms": 0, "processes": [], "disks": [], "gpus": [], **extra}


def idle(recorder):
    complete = threading.Event()
    threading.Thread(target=lambda: (recorder.commands.join(), complete.set()), daemon=True).start()
    assert complete.wait(5)


def test_compressed_session_roundtrip_zip_and_no_optional_csv(tmp_path):
    recorder = SessionRecorder()
    try:
        recorder.command("start", {"folder": str(tmp_path), "compressed": True, "csv": False, "duration_s": 1800})
        idle(recorder)
        recorder.submit(row(1))
        recorder.submit(row(1.5, cpu_percent=98))
        recorder.command("stop")
        idle(recorder)
        root = recorder.path
        assert (root / "amostras.jsonl.gz").is_file()
        assert not (root / "metricas.csv").exists()
        result = analyze_session(root)
        assert result["summary"]["samples"] == 2
        assert result["metadata"]["compressed"]
        archive = tmp_path / "capture.zip"
        with zipfile.ZipFile(archive, "w") as file:
            for target in root.iterdir():
                file.write(target, "capture/" + target.name)
        assert analyze_session(archive)["summary"]["resources"] == result["summary"]["resources"]
    finally:
        recorder.shutdown()


def test_truncated_gzip_preserves_complete_lines_and_warns(tmp_path):
    data = b""
    for at in (1, 2):
        data += gzip.compress((json.dumps(row(at)) + "\n").encode())
    (tmp_path / "amostras.jsonl.gz").write_bytes(data + gzip.compress(b"unfinished")[:15])
    result = analyze_session(tmp_path)
    assert result["summary"]["samples"] == 2
    assert any("incompleta" in warning for warning in result["warnings"])


def test_target_process_is_preserved_outside_top_ten(tmp_path):
    recorder = SessionRecorder()
    try:
        recorder.command("start", {"folder": str(tmp_path), "target_pid": 100})
        idle(recorder)
        processes = [{"pid": i, "name": "p", "cpu_percent": 99-i, "ram_percent": 99-i,
                      "io_total_mbs": 99-i, "gpu_percent": 99-i} for i in range(1, 25)]
        processes.append({"pid": 100, "name": "target", "cpu_percent": 0})
        recorder.submit(row(1, processes=processes))
        recorder.command("stop")
        idle(recorder)
        saved = json.loads((recorder.path / "amostras.jsonl").read_text(encoding="utf-8"))
        assert any(p["pid"] == 100 for p in saved["processes"])
    finally:
        recorder.shutdown()


def test_duration_limit_ends_long_session_without_waiting(tmp_path):
    recorder = SessionRecorder()
    try:
        recorder.command("start", {"folder": str(tmp_path), "duration_s": 1800})
        idle(recorder)
        recorder.started -= 1801
        recorder.submit(row(1))
        idle(recorder)
        assert not recorder.active.is_set()
        metadata = json.loads((recorder.path / "sessao.json").read_text(encoding="utf-8"))
        assert metadata["ended"]
    finally:
        recorder.shutdown()


def test_bulk_process_structure_decodes_and_rejects_broken_offsets():
    size = ctypes.sizeof(ProcessTimes)
    buffer = ctypes.create_string_buffer(size * 2)
    first = ProcessTimes.from_buffer(buffer)
    first.next, first.pid = size, 11
    first.created, first.user, first.kernel = 116444736010000000, 20000000, 10000000
    first.working_set, first.read_bytes, first.write_bytes = 8192, 100, 200
    second = ProcessTimes.from_buffer(buffer, size)
    second.pid, second.created = 12, 116444736020000000
    result = decode_process_times(buffer, len(buffer))
    assert result[11][:5] == (1, 3, 8192, 100, 200)
    first.next = 1
    assert decode_process_times(buffer, len(buffer)) is None


@pytest.mark.skipif(os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8, reason="Fonte Windows 64 bits")
def test_bulk_process_cpu_matches_current_process():
    import psutil
    native = WindowsProcessTimes().sample()
    assert native and os.getpid() in native
    process = psutil.Process()
    assert native[os.getpid()][0] == pytest.approx(process.create_time(), abs=.001)
    assert native[os.getpid()][1] <= sum(process.cpu_times()[:2]) + .1
    assert native[os.getpid()][2] > 0


def test_frames_keep_swapchains_separate_and_calculate_quantiles():
    csv = "ProcessID,SwapChainAddress,CPUStartQPCTime,MsBetweenPresents,MsGPUBusy\n"
    csv += "\n".join(f"10,abc,{100000+i*16},16,8" for i in range(99))
    csv += "\n10,abc,101600,200,10\n10,other,100000,5,1\n"
    result = analyze_frames(io.StringIO(csv), target_pid=10)
    first = result["series"][0]
    assert first["count"] == 100
    assert first["p99_ms"] == 16
    assert first["max_ms"] == 200
    assert first["long_intervals"] == 1
    assert first["events"][0]["monotonic"] == 101.6
    assert len(result["series"]) == 2


def test_frame_context_uses_qpc_and_does_not_blame_process(tmp_path):
    (tmp_path / "amostras.jsonl").write_text("\n".join(json.dumps(row(at, cpu_percent=98)) for at in (100, 100.5, 101)), encoding="utf-8")
    (tmp_path / "frametimes.csv").write_text("ProcessID,SwapChainAddress,CPUStartQPCTime,MsBetweenPresents\n10,abc,100500,200\n", encoding="utf-8")
    result = analyze_session(tmp_path)
    event = result["frametimes"]["series"][0]["events"][0]
    assert event["resource_context"]["samples"] == 3
    assert any("Intervalos de quadros" in item["title"] for item in result["explanation"]["evidence"])
    assert "Causa não confirmada" in result["explanation"]["conclusion"]


def test_frame_capture_requires_target_and_uses_own_session(tmp_path):
    capture = FrameCapture()
    with pytest.raises(ValueError, match="Selecione"):
        capture.start(tmp_path, None)
    process = SimpleNamespace(poll=lambda: 0, returncode=0)
    with patch("modules.frametimes.find_presentmon", return_value="PresentMon.exe"), patch("modules.frametimes.subprocess.Popen", return_value=process) as launch:
        capture.start(tmp_path, 10)
        arguments = launch.call_args.args[0]
        assert "--qpc_time_ms" in arguments
        assert "--restart_as_admin" not in arguments
        assert capture.session.startswith("SysPulseFrames_")
        capture.stop()


@pytest.mark.parametrize("host", ["8.8.8.8", "localhost", "example.com", "::1"])
def test_network_destination_accepts_only_address(host):
    assert validate_host(host) == host


@pytest.mark.parametrize("host", ["-t", "a b", "https://example.com", "$(whoami)", "x;whoami"])
def test_network_destination_rejects_shell_or_flags(host):
    with pytest.raises(ValueError):
        validate_host(host)


def test_network_missing_reply_is_not_zero_rtt():
    result = ping_statistics([{"ms": 10}, {"ms": None}, {"ms": 30}])
    assert result["replies"] == 2 and result["timeouts"] == 1
    assert result["mean_ms"] == 20
    assert result["variation_ms"] == 20


def test_profile_has_bounded_memory_and_both_modes(tmp_path):
    import xml.etree.ElementTree as ET
    path = write_profile(tmp_path / "test.wprp", 128)
    root = ET.parse(path).getroot()
    assert root.find(".//Buffers").get("Value") == "128"
    assert {row.get("LoggingMode") for row in root.findall(".//Profile")} == {"Memory", "File"}


def test_capture_and_inference_are_mutually_exclusive():
    state = ActivityState()
    state.begin_capture("native")
    with pytest.raises(RuntimeError):
        state.begin_inference()
    with pytest.raises(RuntimeError):
        state.begin_capture("advanced")
    state.end_capture("other")
    assert state.capture == "native"
    state.end_capture("native")
    state.begin_inference()
    with pytest.raises(RuntimeError):
        state.begin_capture("native")
    state.end_inference()
    state.begin_capture("advanced")


def test_model_discovery_never_sends_inference():
    with patch("modules.ai_service.request_json", return_value={"models": [{"name": "llama3.2:3b"}]}) as request:
        assert list_models(PROVIDERS["ollama"]) == ["llama3.2:3b"]
    assert request.call_args.args[0].endswith("/api/tags")
    assert "body" not in request.call_args.kwargs


def test_preference_never_saves_key(tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    config = AIConfig(settings=settings)
    config.save({"provider": "ollama", "endpoint": PROVIDERS["ollama"]["endpoint"],
                 "model": "llama3.2:3b", "key": "private-secret", "answer_tokens": 400})
    settings.sync()
    assert "private-secret" not in (tmp_path / "settings.ini").read_text(encoding="utf-8")
    assert AIConfig(settings=settings).model == "llama3.2:3b"


def candidate():
    return {"evidence": [{"id": "E1", "category": "cpu", "candidate": True,
                           "resource": "cpu", "unit": "%", "max": 98, "p95": 95}]}


def test_structured_ai_preserves_native_units_and_rejects_unknown_evidence():
    text = render_explanation('{"findings":[{"category":"cpu","evidence_ids":["E1"]}]}', candidate())
    assert "98 %" in text and "95 %" in text
    assert "Causa não confirmada" in text
    with pytest.raises(ValueError):
        render_explanation('{"findings":[{"category":"storage","evidence_ids":["E1"]}]}', candidate())
    with pytest.raises(ValueError):
        render_explanation('{"findings":[{"category":"cpu","evidence_ids":["E99"]}]}', candidate())


def test_no_candidates_avoids_any_model_request():
    with patch("modules.ai_service.request_json") as request:
        result = call_model({"endpoint": PROVIDERS["ollama"]["endpoint"], "model": "llama3.2:3b", "structured": True}, "", {"evidence": []})
    assert not request.called
    assert result["usage"]["output_tokens"] == 0


def test_ollama_unloads_after_analysis_and_uses_structured_response():
    response = {"message": {"content": '{"findings":[]}'}, "prompt_eval_count": 100, "eval_count": 20}
    with patch("modules.ai_service.request_json", return_value=response) as request:
        result = call_model({"endpoint": PROVIDERS["ollama"]["endpoint"], "model": "llama3.2:3b", "structured": True}, "", candidate())
    body = request.call_args.kwargs["body"]
    assert body["keep_alive"] == 0 and body["format"] == "json"
    assert result["usage"]["input_tokens"] == 100


def test_ai_panel_blocks_capture_until_inference_finishes(tmp_path):
    application = QApplication.instance() or QApplication([])
    state = ActivityState()
    config = AIConfig(state, QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    config.model = "llama3.2:3b"
    panel = AISummaryPanel(config)
    panel.payload = candidate()
    started, release = threading.Event(), threading.Event()

    def inference(*args):
        started.set()
        assert release.wait(5)
        return {"text": '{"findings":[{"category":"cpu","evidence_ids":["E1"]}]}', "usage": {}}

    try:
        with patch("modules.ai_summary.QMessageBox.question", return_value=QMessageBox.Yes), patch("modules.ai_summary.call_model", side_effect=inference):
            panel.request()
            assert started.wait(2)
            with pytest.raises(RuntimeError):
                state.begin_capture("native")
            release.set()
            deadline = time.monotonic() + 3
            while (state.inference or panel._busy) and time.monotonic() < deadline:
                application.processEvents()
                time.sleep(.01)
            assert not state.inference
            assert "98 %" in panel.answer.toPlainText()
    finally:
        release.set()
        panel.shutdown()
        panel.close()



def test_etl_detail_parsers_use_explicit_headers_and_units():
    from modules.etl_details import parse_cpu_report, parse_disk_report, parse_fault_report
    cpu = parse_cpu_report("Time (us), Process Name ( PID)\n900, Idle (0)\n200, app.exe (10)\n"
                           "Time (us), Process Name ( PID), ThreadID\n120, app.exe (10), 20\n")
    assert cpu["processes"] == [{"cpu_us": 200, "name": "app.exe", "pid": 10}]
    assert cpu["threads"][0]["tid"] == 20
    assert parse_cpu_report("200, app.exe (10)")["processes"] == []
    disk = parse_disk_report("Count,Size,SrvT,R-Count,R-Size,R-SrvT,W-Count,W-Size,W-SrvT,IOTime,Filename\n"
                             '2,8192,100,1,4096,50,1,4096,50,200,"C:/file,part.dat"\n')
    assert disk["files"][0]["bytes"] == 8192
    assert disk["files"][0]["file"] == "C:/file,part.dat"
    faults = parse_fault_report('NumFaults,TotalBytes,Process Name ( PID),FileName\n'
                               '2,4096,app.exe (10),a\n3,8192,app.exe (10),b\n')
    assert faults["processes"][0]["count"] == 5
    assert faults["processes"][0]["bytes"] == 12288


def test_compressed_frames_import_and_csv_export(tmp_path):
    from modules.analysis import export_metrics
    import csv
    (tmp_path / "amostras.jsonl.gz").write_bytes(gzip.compress(
        ("\n".join(json.dumps(row(at)) for at in (100, 100.5, 101)) + "\n").encode()))
    (tmp_path / "frametimes.csv.gz").write_bytes(gzip.compress(
        b"ProcessID,SwapChainAddress,CPUStartQPCTime,MsBetweenPresents\n10,abc,100500,200\n"))
    result = analyze_session(tmp_path)
    assert result["frametimes"]["series"][0]["count"] == 1
    export_metrics(tmp_path, tmp_path / "export.csv")
    with (tmp_path / "export.csv").open(encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 3
    assert rows[0]["cpu_percent"] == "20"


def test_windows_vault_is_optional_and_never_plaintext_in_preferences(tmp_path):
    settings = QSettings(str(tmp_path / "vault.ini"), QSettings.IniFormat)
    config = AIConfig(settings=settings)
    with patch.object(config.store, "write") as save:
        config.save({"provider": "gemini", "endpoint": PROVIDERS["gemini"]["endpoint"],
                     "model": "available-model", "key": "secret-for-vault", "remember_key": True})
    save.assert_called_once_with("gemini", "secret-for-vault")
    settings.sync()
    assert "secret-for-vault" not in (tmp_path / "vault.ini").read_text(encoding="utf-8")


def test_graphics_capture_requires_target_in_interface():
    from modules.diagnostic_view import DiagnosticPanel
    panel = DiagnosticPanel()
    try:
        panel.frames.setChecked(True)
        panel.request_start()
        assert "Selecione o aplicativo" in panel.status.text()
        assert panel.start.isEnabled()
    finally:
        panel.close()


def test_frame_finalization_failure_preserves_resource_session(tmp_path):
    recorder = SessionRecorder()
    try:
        recorder.command("start", {"folder": str(tmp_path)})
        idle(recorder)
        recorder.submit(row(1))
        idle(recorder)
        recorder.frames = SimpleNamespace(stop=lambda: (_ for _ in ()).throw(OSError("locked")))
        recorder.command("stop")
        idle(recorder)
        result = analyze_session(recorder.path)
        assert result["metadata"]["ended"]
        assert result["summary"]["samples"] == 1
        assert any("Frametimes preservados" in warning for warning in result["warnings"])
    finally:
        recorder.shutdown()



def test_failed_etl_keeps_ai_blocked_until_resources_finish():
    from gui import App
    window = App(demo=True)
    try:
        window._capture_mode = "circular"
        window.activity.begin_capture("advanced")
        window.advanced.native_requested = True
        window.advanced.native_finished = False
        window.on_advanced_state({"state": "failed", "message": "Teste"})
        with pytest.raises(RuntimeError):
            window.activity.begin_inference()
        with patch.object(window.advanced.controller, "status", return_value={"state": "failed"}):
            window.advanced.on_recorder_status({"completed": True, "active": False, "message": "Finalizado"})
        assert window.activity.capture is None
        window.activity.begin_inference()
        window.activity.end_inference()
    finally:
        window.shutdown()
        window.close()


def test_presentmon_without_output_is_reported_without_losing_resources(tmp_path):
    recorder = SessionRecorder()
    try:
        recorder.command("start", {"folder": str(tmp_path)})
        idle(recorder)
        recorder.submit(row(1))
        idle(recorder)
        recorder.frames = SimpleNamespace(stop=lambda: 0, path=tmp_path / "missing.csv")
        recorder.command("stop")
        idle(recorder)
        result = analyze_session(recorder.path)
        assert result["summary"]["samples"] == 1
        assert any("não gerou frametimes" in warning for warning in result["warnings"])
    finally:
        recorder.shutdown()
