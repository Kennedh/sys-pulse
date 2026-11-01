import csv
import json

import pytest

from modules.analysis import Accumulator, analyze_session, report_text
from modules.advanced_analysis import parse_trace_quality
from modules.assessment import Assessment
from modules.analysis import resource_values


def sample(at, cpu=20, **extra):
    return {"monotonic": at, "timestamp": str(at), "target_interval_ms": 1000,
            "cpu_percent": cpu, "cpu_max_core": cpu, "ram_percent": 30, **extra}


def capture(path, samples, markers):
    (path / "amostras.jsonl").write_text(
        "\n".join(json.dumps(row) for row in samples), encoding="utf-8")
    (path / "sessao.json").write_text(json.dumps({"ended": "done"}), encoding="utf-8")
    with (path / "marcacoes.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["id", "monotonic", "timestamp", "note"])
        writer.writeheader()
        writer.writerows({"id": i + 1, "monotonic": at, "timestamp": str(at), "note": ""}
                         for i, at in enumerate(markers))
    return analyze_session(path)


def test_symptoms_compare_with_rest_of_session_and_preserve_overlap(tmp_path):
    result = capture(tmp_path, [sample(at, 98 if 5 <= at <= 17 else 20) for at in range(31)], [10, 12])
    symptoms = result["symptoms"]
    assert symptoms["near_samples"] == 13
    assert symptoms["outside_samples"] == 18
    cpu = next(row for row in symptoms["candidates"] if row["key"] == "cpu")
    assert cpu["near_count"] == 13
    assert cpu["affected_markers"] == 2
    assert cpu["near_high_percent"] == 100
    assert cpu["outside_high_percent"] == 0
    assert cpu["difference_pp"] == 100
    first = result["explanation"]["evidence"][0]
    assert first["title"].startswith("Perto do sintoma")
    assert "Coincidência temporal não confirma causa" in first["meaning"]
    assert "Perto do sintoma" in report_text(result)
    assert not any(window["partial"] for window in symptoms["windows"])


def test_high_load_elsewhere_is_not_presented_as_marker_evidence(tmp_path):
    result = capture(tmp_path, [sample(at, 98 if at < 5 else 20) for at in range(21)], [12])
    assert not result["symptoms"]["candidates"]
    assert any("CPU total" in item["title"] for item in result["explanation"]["evidence"])
    assert "Sem carga alta" in result["explanation"]["summary"]


def test_constant_load_is_explicitly_weak_at_explaining_pause(tmp_path):
    result = capture(tmp_path, [sample(at, 98) for at in range(21)], [10])
    cpu = result["symptoms"]["candidates"][0]
    assert cpu["difference_pp"] == 0
    assert "explica pouco" in result["explanation"]["evidence"][0]["meaning"]


def test_missing_baseline_is_not_zero(tmp_path):
    result = capture(tmp_path, [sample(at, 98) for at in range(5)], [2])
    cpu = result["symptoms"]["candidates"][0]
    assert cpu["outside_high_percent"] is None
    assert cpu["difference_pp"] is None
    assert result["symptoms"]["windows"][0]["partial"]
    assert any("cobertura parcial" in text for text in result["explanation"]["limitations"])
    assert "falta uma base" in result["explanation"]["evidence"][0]["meaning"]


def test_absent_resource_outside_window_is_not_zero(tmp_path):
    samples = [sample(at, 98 if 5 <= at <= 15 else None) for at in range(21)]
    result = capture(tmp_path, samples, [10])
    cpu = next(row for row in result["symptoms"]["candidates"] if row["key"] == "cpu")
    assert result["symptoms"]["outside_samples"] == 10
    assert cpu["outside_count"] == 0
    assert cpu["outside_high_percent"] is None


def test_gap_is_detected_from_timestamps_even_without_interval_field(tmp_path):
    result = capture(tmp_path, [sample(at, 98, collector_ms=1200) for at in (0, 1, 5, 6)], [3])
    collection = result["summary"]["collection"]
    assert collection["gaps"] == 1
    assert collection["max_gap_ms"] == 4000
    assert collection["expensive_samples"] == 4
    assert result["symptoms"]["windows"][0]["gaps"] == 1
    assert any("lacuna" in text for text in result["warnings"])
    assert any("próprio monitor" in text for text in result["warnings"])
    assert any("coincidência" in text for text in result["explanation"]["limitations"])


def test_no_marker_explanation_requests_useful_capture(tmp_path):
    result = capture(tmp_path, [sample(1, 98)], [])
    assert result["explanation"]["summary"].startswith("Sem marcações")
    assert any("Marque a próxima pausa" in text for text in result["explanation"]["limitations"])


@pytest.mark.parametrize("extra", [{"process_age_ms": -1},
                                  {"process_age_ms": 0, "process_sample_monotonic": 3}])
def test_future_process_reading_is_not_attributed(extra):
    accumulator = Accumulator()
    accumulator.add(sample(1, 98, processes=[{"pid": 1, "name": "future", "cpu_percent": 90}], **extra))
    assert accumulator.finish()["resources"][0]["process"] is None


def test_cached_gpu_observations_count_once_in_resource_comparison():
    accumulator = Accumulator()
    for at in (1, 1.5, 2):
        accumulator.add(sample(at, sensor_sample_monotonic=1, sensor_age_ms=(at - 1) * 1000,
                               gpus=[{"id": "gpu0", "name": "GPU", "percent": 99}]))
    gpu = next(row for row in accumulator.finish()["resources"] if row["key"] == "gpu")
    assert gpu["count"] == 1
    assert gpu["high_count"] == 1


def test_disk_delay_keeps_context_from_same_sample_even_with_low_activity():
    assessment = Assessment()
    for at, latency, queue, active in ((1, 80, 3, 20), (2, 40, 12, 99)):
        row = sample(at, disks=[{"name": "disk0", "read_ms": latency, "queue": queue,
                                "active_percent": active, "read_iops": 10}])
        assessment.add(row, *resource_values(row))
    findings = [row for row in assessment.result()["findings"] if row["resource"] == "disk_latency"]
    assert len(findings) == 1
    assert "disk0" in findings[0]["title"]
    assert "80.0 ms/op" in findings[0]["evidence"]
    assert "fila: 3.0" in findings[0]["evidence"]
    assert "atividade: 20.0%" in findings[0]["evidence"]


def test_real_xperf_quality_format_prefers_total_over_per_trace_counts():
    result = parse_trace_quality(
        "Total # Lost Buffers : 2\nTotal # Lost Events : 7\n"
        "    # Lost Buffers : 2\n    # Lost Events : 7\n")
    assert result == {"lost_events": 7, "lost_buffers": 2, "checked": True}


def test_zero_losses_are_known_and_unrecognized_losses_stay_unknown():
    assert parse_trace_quality("Total # Lost Events : 0")["checked"]
    assert parse_trace_quality("Total # Lost Events : 0")["lost_events"] == 0
    assert parse_trace_quality("Unknown report")["lost_events"] is None
    assert not parse_trace_quality("Unknown report")["checked"]



def test_ai_uses_marker_comparison_without_private_context(tmp_path):
    from modules.ai_summary import ai_payload

    result = capture(tmp_path, [sample(at, 98 if 5 <= at <= 15 else 20) for at in range(21)], [10])
    result["symptoms"]["resources"][0].update(name="private-name", peak_at="private-time")
    result["symptoms"]["windows"][0]["note"] = "private-note"
    for advanced in (False, True):
        payload = ai_payload({"native_summary": result["summary"], "native_symptoms": result["symptoms"]}
                             if advanced else result)
        encoded = json.dumps(payload)
        assert "private-" not in encoded
        cpu = next(row for row in payload["symptom_comparison"] if row["resource"] == "cpu")
        assert cpu["near_high_percent"] == 100
        assert cpu["outside_high_percent"] == 0
        assert payload["causality_confirmed"] is False


def test_process_collection_cost_counts_cached_batch_once():
    assessment = Assessment()
    for at in (1, 1.5, 2):
        row = sample(at, process_sample_monotonic=1, process_collector_ms=400)
        assessment.add(row, *resource_values(row))
    cost = next(row for row in assessment.result()["telemetry"] if row["key"] == "process_collector")
    assert cost["count"] == 1
    assert cost["mean"] == 400
