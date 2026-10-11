import csv
import json
import queue
import threading
from types import SimpleNamespace

import pytest

from modules.diagnostics import SessionRecorder, event_summary, metrics
from modules.monitor import disk_rates
from modules.sensors import parse_lhm, SensorService


def io(size=0, count=0, duration=0, busy=0):
    return SimpleNamespace(read_bytes=size, write_bytes=0, read_count=count, write_count=0,
                           read_time=duration, write_time=0, busy_time=busy)


def sample(at, cpu=20):
    return {"timestamp": f"2026-10-11T03:00:{int(at):02d}-03:00", "monotonic": at,
            "cpu_percent": cpu, "cpu_max_core": cpu, "ram_percent": 40,
            "ram_available_gb": 8, "interval_ms": 500, "target_interval_ms": 500,
            "disks": [], "gpus": [], "processes": []}


def wait_idle(recorder):
    done = threading.Event()
    thread = threading.Thread(target=lambda: (recorder.commands.join(), done.set()), daemon=True)
    thread.start()
    assert done.wait(3), "Gravador não respondeu"


def test_disk_speed_uses_real_interval_and_latency_operations():
    row = disk_rates({"disk": io()}, {"disk": io(1024 ** 2, 4, 120, 250)}, 0.5)[0]
    assert row["read_mbs"] == 2
    assert row["read_ms"] == 30
    assert row["active_percent"] == 50
    assert row["write_ms"] is None


def test_reset_or_new_device_does_not_invent_reading():
    row = disk_rates({"disk": io(100, 10, 20)}, {"disk": io(10, 1, 2), "new": io()}, 1)
    assert all(item["read_mbs"] is None for item in row)
    assert row[0]["read_ms"] is None
    assert disk_rates({}, {}, 0) == []


def test_unsupported_busy_time_stays_none():
    previous, current = io(), io(100, 1, 2)
    del previous.busy_time
    del current.busy_time
    assert disk_rates({"disk": previous}, {"disk": current}, 1)[0]["active_percent"] is None


def test_no_gpu_and_no_disk_are_missing_not_zero():
    row = metrics(sample(1))
    assert row["gpu_max_percent"] is None
    assert row["disk_max_active_percent"] is None


def test_marker_window_excludes_distant_peaks_and_handles_partial_after():
    event = {"id": 1, "monotonic": 10, "timestamp": "now", "note": "jogo"}
    summary = event_summary(event, [sample(1, 100), sample(6), sample(10.5), sample(16, 100)])
    assert summary["before"]["samples"] == 1
    assert summary["after"]["samples"] == 1
    assert summary["coverage_seconds"] == [-4, 0.5]
    assert summary["evidence"][0].startswith("Sem pico")


def test_single_busy_core_is_not_hidden_by_average_cpu():
    value = sample(10, 5)
    value["cpu_max_core"] = 100
    report = event_summary({"monotonic": 10}, [value])
    assert any("núcleo lógico" in line for line in report["evidence"])


def test_lhm_current_raw_values_and_multiple_gpus():
    tree = {"Children": [
        {"HardwareId": "/amdcpu/0", "Text": "CPU", "Children": [
            {"SensorId": "/amdcpu/0/temperature/0", "Type": "Temperature", "Text": "Core", "RawValue": 65, "Value": "149 °F"}]},
        {"HardwareId": "/gpu-amd/0", "Text": "AMD", "Children": [
            {"SensorId": "/gpu-amd/0/load/0", "Type": "Load", "Text": "GPU Core", "RawValue": 88}]},
        {"HardwareId": "/gpu-intel/0", "Text": "Intel", "Children": [
            {"SensorId": "/gpu-intel/0/load/0", "Type": "Load", "Text": "D3D 3D", "RawValue": 10}]}]}
    result = parse_lhm(tree)
    assert result["cpu_temperature"] == 65
    assert [gpu["percent"] for gpu in result["gpus"]] == [88, 10]
    assert result["gpus"][0]["name"] == "AMD"


def test_lhm_older_locale_and_unknown_readings():
    tree = {"Children": [
        {"SensorId": "/intelcpu/0/temperature/0", "Text": "Core", "Value": "122,0 °F"},
        {"SensorId": "/gpu-amd/0/load/0", "Text": "GPU Core", "Value": "37,5 %"},
        {"SensorId": "/gpu-amd/0/temperature/0", "Text": "GPU Core", "Value": "N/A"}]}
    result = parse_lhm(tree)
    assert result["cpu_temperature"] == 50
    assert result["gpus"][0]["percent"] == 37.5
    assert "temperature" not in result["gpus"][0]


def test_stale_sensors_are_cleared():
    service = SensorService()
    service._data = {"sensor_at": 0, "gpus": [{"percent": 90}], "cpu_temperature": 80}
    snapshot = service.snapshot()
    assert snapshot["gpus"] == []
    assert snapshot["cpu_temperature"] is None


def test_recording_flushes_on_shutdown_and_finishes_partial_event(tmp_path):
    recorder = SessionRecorder()
    try:
        assert recorder.command("start", {"folder": str(tmp_path)})
        wait_idle(recorder)
        recorder.submit(sample(6))
        recorder.command("mark", {"timestamp": "2026-10-11T03:00:10-03:00", "monotonic": 10, "note": "YouTube"})
        recorder.submit(sample(11, 99))
        assert recorder.shutdown()
        raw = [json.loads(line) for line in (recorder.path / "amostras.jsonl").read_text().splitlines()]
        assert len(raw) == 2
        event = json.loads((recorder.path / "eventos.jsonl").read_text())
        assert event["before"]["samples"] == event["after"]["samples"] == 1
        assert "YouTube" in (recorder.path / "relatorio.txt").read_text()
        with (recorder.path / "metricas.csv").open(encoding="utf-8-sig") as file:
            rows = list(csv.DictReader(file))
        assert len(rows) == 2 and rows[0]["gpu_max_percent"] == ""
    finally:
        if recorder.thread.is_alive():
            recorder.shutdown()


def test_event_finishes_at_plus_five_and_restart_is_isolated(tmp_path):
    recorder = SessionRecorder()
    try:
        recorder.command("start", {"folder": str(tmp_path)})
        wait_idle(recorder)
        first = recorder.path
        recorder.submit(sample(5))
        recorder.command("mark", {"monotonic": 10, "timestamp": "now", "note": "x"})
        recorder.submit(sample(15))
        recorder.submit(sample(16))
        recorder.command("stop")
        wait_idle(recorder)
        events = (first / "eventos.jsonl").read_text().splitlines()
        assert len(events) == 1
        assert json.loads(events[0])["coverage_seconds"] == [-5, 5]
        recorder.command("start", {"folder": str(tmp_path)})
        wait_idle(recorder)
        assert recorder.path != first
        recorder.command("stop")
        wait_idle(recorder)
        assert (recorder.path / "eventos.jsonl").read_text() == ""
    finally:
        recorder.shutdown()


def test_disk_failure_is_reported_and_worker_survives(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    statuses = []
    recorder = SessionRecorder(statuses.append)
    try:
        recorder.command("start", {"folder": str(blocker)})
        wait_idle(recorder)
        assert statuses[-1]["error"]
        assert not recorder.active.is_set()
        recorder.command("start", {"folder": str(tmp_path)})
        wait_idle(recorder)
        assert recorder.active.is_set()
    finally:
        recorder.shutdown()


def test_size_limit_stops_recording(tmp_path):
    recorder = SessionRecorder(max_bytes=1)
    try:
        recorder.command("start", {"folder": str(tmp_path)})
        wait_idle(recorder)
        recorder.submit(sample(1))
        wait_idle(recorder)
        assert not recorder.active.is_set()
        assert "Limite" in (recorder.path / "relatorio.txt").read_text()
    finally:
        recorder.shutdown()


def test_full_queue_never_blocks_collector():
    recorder = object.__new__(SessionRecorder)
    recorder.active = threading.Event()
    recorder.active.set()
    recorder.commands = queue.Queue(maxsize=1)
    recorder.commands.put(("sample", {}))
    recorder.dropped = 0
    recorder.submit(sample(1))
    assert recorder.dropped == 1
    assert not recorder.command("mark", {})
