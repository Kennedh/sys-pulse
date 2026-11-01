import io
import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import QSettings

from modules.ai_settings import AIConfig, AISettingsPanel
from modules.analysis import analyze_session, report_text
from modules.stress import validate_options, cpu_lane
from modules.session_insights import SessionInsights
from modules.frametimes import analyze_frames


def sample(at, **extra):
    return {"monotonic": at, "timestamp": str(at), "target_interval_ms": 500, "cpu_percent": 80,
            "cpu_max_core": 90, "ram_percent": 50, "sensor_sample_monotonic": at,
            "sensor_age_ms": 0, "process_age_ms": 0, "processes": [], "disks": [], "gpus": [], **extra}


def test_long_session_reports_when_load_changes_without_symptom_markers(tmp_path):
    rows = [sample(120 + second, cpu_percent=95 if second >= 600 else 30,
                   cpu_temperature=65 if second < 600 else 85, cpu_freq_mhz=4000 if second < 600 else 3500)
            for second in range(1800)]
    (tmp_path / "amostras.jsonl").write_text("\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")
    (tmp_path / "sessao.json").write_text(json.dumps({"ended": "test", "duration_s": 1800}), encoding="utf-8")
    result = analyze_session(tmp_path)
    evolution = result["evolution"]
    assert len(evolution["periods"]) == 30
    cpu = next(row for row in evolution["trends"] if row["key"] == "cpu")
    assert cpu["early"] == 30 and cpu["late"] == 95
    assert evolution["critical_periods"][0]["offset_s"] >= 600
    assert "captura curta" not in report_text(result)
    assert "3500" in report_text(result)


def test_target_rss_growth_requires_same_process_identity():
    insights = SessionInsights(target_pid=10)
    for at, identity, memory in ((120, 1, 100), (180, 2, 300)):
        insights.add(sample(at, process_sample_monotonic=at), {"cpu": 30},
                     [{"pid": 10, "created": identity, "name": "app", "rss_mb": memory}])
    assert insights.result()["target_memory"] is None


def test_sensor_cache_does_not_bias_period_average():
    insights = SessionInsights()
    insights.add(sample(120, sensor_sample_monotonic=120, cpu_temperature=60), {"gpu": 10}, [])
    insights.add(sample(120.5, sensor_sample_monotonic=120, cpu_temperature=60), {"gpu": 10}, [])
    insights.add(sample(121, sensor_sample_monotonic=121, cpu_temperature=80), {"gpu": 90}, [])
    metrics = insights.result()["periods"][0]["metrics"]
    assert metrics["cpu_temperature"]["mean"] == 70
    assert metrics["gpu"]["count"] == 2


def test_stress_phases_use_actual_load_times_and_do_not_create_symptoms(tmp_path):
    (tmp_path / "stress.json").write_text(json.dumps({"kind": "cpu", "state": "completed", "elapsed_s": 2,
            "started_monotonic": 122, "ended_monotonic": 124, "errors": 0}), encoding="utf-8")
    (tmp_path / "amostras.jsonl").write_text("\n".join(json.dumps(sample(at)) for at in range(120, 127)) + "\n", encoding="utf-8")
    result = analyze_session(tmp_path)
    phases = {row["name"]: row["samples"] for row in result["evolution"]["phases"]}
    assert phases == {"Antes da carga": 2, "Durante a carga": 3, "Recuperação": 2}
    assert not result["events"]
    assert result["stress"]["state"] == "completed"


def test_frametimes_are_kept_in_their_own_period():
    frames = analyze_frames(io.StringIO("ProcessID,SwapChainAddress,CPUStartQPCTime,FrameTime\n"
                                       "10,a,120000,16\n10,a,180000,100\n"))
    periods = frames["series"][0]["periods"]
    assert periods[0]["minute"] == 2 and periods[0]["p99_ms"] == 16
    assert periods[1]["minute"] == 3 and periods[1]["over_50_ms"] == 1


@pytest.mark.parametrize("options", [{"kind": "disk"}, {"kind": "cpu", "duration_s": 90000},
                                     {"kind": "cpu", "workers": 1000}, {"kind": "gpu", "intensity": 0}])
def test_invalid_stress_budget_is_rejected(options):
    with pytest.raises(ValueError):
        validate_options(options)


def test_memory_budget_reserves_most_available_ram():
    from types import SimpleNamespace
    with patch("modules.stress.psutil.virtual_memory", return_value=SimpleNamespace(available=1024**3)):
        with pytest.raises(ValueError):
            validate_options({"kind": "memory", "memory_mb": 512})


def test_simple_ai_modes_save_without_loading_a_model(tmp_path):
    config = AIConfig(settings=QSettings(str(tmp_path / "ai.ini"), QSettings.IniFormat))
    panel = AISettingsPanel(config)
    try:
        with patch("modules.ai_settings.list_models") as request:
            panel.choose_mode("integrated")
            assert not config.enabled
            panel.choose_mode("horde")
            assert config.enabled and config.provider == "horde"
            assert panel.provider.isHidden() and panel.model.isHidden()
            panel.choose_mode("ollama")
            assert config.provider == "ollama" and not panel.models.isHidden()
        request.assert_not_called()
    finally:
        panel.shutdown()


def test_stress_excludes_advanced_capture_and_ai(tmp_path):
    from gui import App
    window = App(demo=True)
    try:
        window.activity.begin_capture("stress")
        assert not window.advanced.start_button.isEnabled()
        with pytest.raises(RuntimeError):
            window.activity.begin_inference()
        assert not window.settings_panel.modes["horde"].isEnabled()
    finally:
        window.shutdown()


def test_low_disk_latency_does_not_create_critical_period():
    insights = SessionInsights()
    insights.add(sample(120, disks=[{"read_ms": .3}]), {"cpu": 20}, [])
    assert not insights.result()["critical_periods"]


def test_switching_ai_mode_remembers_installed_model(tmp_path):
    config = AIConfig(settings=QSettings(str(tmp_path / "ai.ini"), QSettings.IniFormat))
    panel = AISettingsPanel(config)
    try:
        panel.choose_mode("ollama")
        panel.model.setCurrentText("qwen3:0.6b")
        panel.apply()
        panel.choose_mode("horde")
        panel.choose_mode("ollama")
        assert config.model == "qwen3:0.6b"
    finally:
        panel.shutdown()


def test_stop_before_recorder_started_does_not_start_workload(tmp_path):
    from modules.activity import ActivityState
    from modules.stress_view import StressPanel
    panel = StressPanel(ActivityState())
    try:
        panel.phase = "starting"
        panel.options = {"kind": "cpu"}
        with patch.object(panel.controller, "start") as start:
            panel.request_stop()
            panel.on_recorded({"started": True, "path": str(tmp_path)})
        start.assert_not_called()
        report = json.loads((tmp_path / "stress.json").read_text(encoding="utf-8"))
        assert report["state"] == "stopped"
    finally:
        panel.shutdown()


def test_memory_trend_sent_to_ai_preserves_units_and_hides_process_identity():
    from modules.ai_summary import ai_payload
    from modules.ai_contract import render_explanation
    payload = ai_payload({"evolution": {"duration_s": 1800,
                         "target_memory": {"early_mb": 100, "late_mb": 600, "delta_mb": 500}}})
    item = next(row for row in payload["evidence"] if row["type"] == "trend")
    text = render_explanation(json.dumps({"findings":[{"category":"memory","evidence_ids":[item["id"]]}]}), payload)
    assert "100 MiB" in text and "600 MiB" in text and "500 MiB" in text
    assert "não comprova vazamento" in text


def test_malformed_stress_result_preserves_resource_analysis(tmp_path):
    (tmp_path / "stress.json").write_text(json.dumps({"kind":"cpu","state":"completed","elapsed_s":"bad"}))
    (tmp_path / "amostras.jsonl").write_text(json.dumps(sample(1)) + "\n")
    result = analyze_session(tmp_path)
    assert result["summary"]["samples"] == 1
    assert "stress" not in result
    assert any("estresse inválido" in warning for warning in result["warnings"])


def test_shutdown_preserves_interrupted_stress_context(tmp_path):
    from modules.activity import ActivityState
    from modules.stress_view import StressPanel
    panel = StressPanel(ActivityState())
    panel.path, panel.phase, panel.options = tmp_path, "baseline", {"kind": "cpu"}
    panel.shutdown()
    result = json.loads((tmp_path / "stress.json").read_text(encoding="utf-8"))
    assert result["state"] == "stopped"
    assert result["errors"] is None
    assert "encerrado" in result["reason"]
