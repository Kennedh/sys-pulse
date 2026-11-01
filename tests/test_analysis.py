import json
import zipfile
from types import SimpleNamespace

import pytest

from modules.analysis import (Accumulator, AnalysisError, analyze_session, ranked_processes,
                              save_report, AnalysisCancelled, reduce_chart)
from modules.demo import write_demo_session
from modules.monitor import process_io_rates
from modules.windows_counters import gpu_process_usage


def sample(at, cpu=20, processes=None, age=0):
    return {"timestamp": f"2026-01-15T14:30:{int(at):02d}-03:00", "monotonic": at,
            "cpu_percent": cpu, "cpu_max_core": 99, "ram_percent": 40,
            "gpus": [], "disks": [], "processes": processes or [], "process_age_ms": age,
            "interval_ms": 500, "target_interval_ms": 500}


def process(pid, cpu, rss=100, created=1):
    return {"pid": pid, "name": f"process-{pid}", "cpu_percent": cpu, "rss_mb": rss, "created": created}


def session(tmp_path, samples):
    (tmp_path / "amostras.jsonl").write_text("\n".join(json.dumps(s) for s in samples), encoding="utf-8")
    return tmp_path


def test_cached_process_readings_not_counted_repeatedly():
    data = Accumulator()
    for at, age, cpu in ((1, 0, 60), (1.5, 500, 60), (2, 1000, 60), (3, 0, 20)):
        data.add(sample(at, processes=[process(1, cpu)], age=age))
    stat = data.finish()["processes"][0]["metrics"]["cpu_percent"]
    assert stat["mean"] == 40
    assert stat["count"] == 2


def test_peak_attribution_uses_contemporaneous_resource_not_session_cpu_leader():
    data = Accumulator()
    data.add(sample(1, 90, [process(1, 80, 100), process(2, 1, 2000)]))
    data.add(sample(3, 95, [process(1, 1, 100), process(2, 60, 2000)]))
    resources = {r["key"]: r for r in data.finish()["resources"]}
    assert resources["cpu"]["process"]["pid"] == 2
    assert resources["ram"]["process"]["pid"] == 2
    assert resources["gpu"]["mean"] is None
    assert resources["vram"]["mean"] is None


def test_stale_processes_never_attributed():
    data = Accumulator()
    data.add(sample(1, 90, [process(1, 80)], age=5000))
    result = data.finish()
    assert not result["processes"]
    assert result["resources"][0]["process"] is None


def test_pid_reuse_and_absence_not_zero_filled():
    data = Accumulator()
    data.add(sample(1, processes=[process(1, 80, created=1)]))
    data.add(sample(3))
    data.add(sample(5, processes=[process(1, 20, created=2)]))
    result = data.finish()
    assert len(result["processes"]) == 2
    assert [p["metrics"]["cpu_percent"]["mean"] for p in result["processes"]] == [80, 20]


def test_mean_dominant_excludes_busy_core_and_preserves_missing(tmp_path):
    result = analyze_session(session(tmp_path, [sample(1, 20), sample(2, 80)]))
    assert result["summary"]["dominant"]["key"] == "cpu"
    assert result["summary"]["dominant"]["mean"] == 50
    assert result["summary"]["resources"][3]["count"] == 0


def test_zip_import_matches_folder_and_markers(tmp_path):
    folder = tmp_path / "demo"
    write_demo_session(folder)
    direct = analyze_session(folder)
    archive_path = tmp_path / "session.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for file in folder.iterdir():
            archive.write(file, f"nested/session/{file.name}")
    zipped = analyze_session(archive_path)
    assert direct["summary"] == zipped["summary"]
    assert len(zipped["events"]) == 3
    assert zipped["events"][0]["coverage"] == [-5, 5]
    assert zipped["summary"]["process_batches"] == 46
    assert ranked_processes(zipped["summary"], "io_total_mbs")[0]["name"] == "backup-demo.exe"
    assert not (tmp_path / "nested").exists()


def test_partial_and_out_of_order_lines_are_reported(tmp_path):
    path = session(tmp_path, [sample(2), sample(1), sample(3)])
    with (path / "amostras.jsonl").open("a") as file:
        file.write('\n{"incomplete":')
    result = analyze_session(path)
    assert result["summary"]["samples"] == 2
    assert result["invalid_lines"] == 2
    assert any("parcial" in text for text in result["warnings"])


def test_empty_and_etl_fail_with_actionable_error(tmp_path):
    with pytest.raises(AnalysisError, match="ETL"):
        analyze_session(tmp_path / "capture.etl")
    with pytest.raises(AnalysisError, match="amostras válidas"):
        analyze_session(session(tmp_path, []))


def test_ambiguous_zip_is_rejected(tmp_path):
    path = tmp_path / "two.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("one/amostras.jsonl", "")
        archive.writestr("two/amostras.jsonl", "")
    with pytest.raises(AnalysisError, match="exatamente uma"):
        analyze_session(path)


def test_cancel_and_export_round_trip(tmp_path):
    path = session(tmp_path, [sample(1, processes=[process(1, 30)])])
    with pytest.raises(AnalysisCancelled):
        analyze_session(path, lambda: True)
    result = analyze_session(path)
    save_report(result, tmp_path / "report")
    loaded = json.loads((tmp_path / "report/analise.json").read_text(encoding="utf-8"))
    assert loaded["summary"] == result["summary"]
    assert "process-1" in (tmp_path / "report/analise.txt").read_text(encoding="utf-8")


def test_process_io_rate_warmup_reset_unsupported_and_interval():
    old = SimpleNamespace(read_bytes=0, write_bytes=1024 ** 2)
    new = SimpleNamespace(read_bytes=4 * 1024 ** 2, write_bytes=3 * 1024 ** 2)
    assert process_io_rates(old, new, 2)["io_total_mbs"] == 3
    assert process_io_rates(None, new, 2)["io_total_mbs"] is None
    assert process_io_rates(new, old, 2)["io_total_mbs"] is None
    assert process_io_rates(old, new, 0)["io_total_mbs"] is None


def test_gpu_process_busiest_engine_not_sum():
    values = gpu_process_usage([("pid_10_luid_0x0_eng_0_engtype_3D", 75),
                                ("pid_10_luid_0x0_eng_1_engtype_Copy", 50),
                                ("pid_11_luid_0x0_eng_0_engtype_3D", 0),
                                ("pid_12_luid_0x0_eng_0", float("nan"))])
    assert values == {10: 75, 11: 0}


def test_chart_downsample_keeps_peak():
    points = [{"t": i, "cpu": 99 if i == 5 else 2, "core": 2, "ram": None,
               "gpu": None, "vram": None, "disk": 0} for i in range(100)]
    reduced = reduce_chart(points, 10)
    assert len(reduced) == 10
    assert max(p["cpu"] for p in reduced) == 99
    assert all(p["ram"] is None for p in reduced)
