import json
import math
import struct

import pytest
from PySide6.QtGui import QImage, QColor

from modules.gpu_checks import pattern_bytes, word_difference, canary_bytes, memory_budget, ArtifactCheck, PATTERN_NAMES
from modules.gpu_results import gpu_result_text
from modules.stress import validate_options


@pytest.mark.parametrize("mode,values", [
    (0, [0, 0, 0]), (1, [0xffffffff]*3), (2, [0xaaaaaaaa]*3), (3, [0x55555555]*3),
    (4, [100, 101, 102]), (5, [0xffffffff-100, 0xffffffff-101, 0xffffffff-102]),
    (6, [1]*3), (37, [0x80000000]*3), (38, [0xfffffffe]*3), (69, [0x7fffffff]*3)])
def test_gpu_reference_patterns_cover_addresses_and_bit_positions(mode, values):
    assert pattern_bytes(3, mode, 100) == struct.pack("=III", *values)
    assert len(PATTERN_NAMES) == 70


def test_highest_supported_buffer_address_does_not_overflow():
    assert pattern_bytes(2, 4, 0xfffffffe) == struct.pack("=II", 0xfffffffe, 0xffffffff)


def test_one_changed_bit_reports_logical_address():
    expected = struct.pack("=IIII", 0, 1, 2, 3)
    actual = struct.pack("=IIII", 0, 1, 6, 3)
    assert word_difference(expected, actual, base_bytes=4096) == {
        "words": 1, "bits": 1, "examples": [
        {"byte_offset": 4104, "expected": "00000002", "actual": "00000006"}]}


def test_error_examples_are_bounded_while_counts_remain_complete():
    result = word_difference(bytes(400), bytes([255])*400, limit=3)
    assert result["words"] == 100 and result["bits"] == 3200 and len(result["examples"]) == 3


def test_known_graphic_pattern_preserves_coordinates_and_alpha():
    assert canary_bytes(2, 2, 0) == bytes([0, 0, 0, 255, 1, 0, 1, 255,
                                         0, 1, 1, 255, 1, 1, 0, 255])


def test_scene_comparison_detects_changed_pixel_without_gpu_context():
    checker = ArtifactCheck.__new__(ArtifactCheck)
    checker.stats = {"checks": 0, "scene_pairs": 0, "failed_checks": 0, "mismatched_pixels": 0}
    image = QImage(8, 8, QImage.Format_RGBA8888)
    image.fill(QColor(0, 0, 0, 255))
    assert checker.compare_scene(image, image.copy())["words"] == 0
    changed = image.copy()
    changed.setPixelColor(3, 2, QColor(255, 0, 0, 255))
    assert checker.compare_scene(image, changed)["words"] == 1
    assert checker.stats["failed_checks"] == 1 and checker.stats["mismatched_pixels"] == 1
    assert checker.stats["first_error_monotonic"] > 0


def test_vram_budget_keeps_reserve_and_caps_auto_allocation():
    mib = 1024**2
    target, reserve = memory_budget(0, 8*1024*mib, 32*1024*mib)
    assert reserve >= 512*mib and reserve >= int(8*1024*mib*.15)
    assert target+reserve <= 8*1024*mib and target % (4*mib) == 0
    assert memory_budget(16384, 24*1024*mib, 32*1024*mib)[0] == 16*1024*mib


def test_unknown_vram_budget_uses_conservative_ram_fallback():
    mib = 1024**2
    target, _ = memory_budget(0, None, 2*1024*mib)
    assert 0 < target <= 2*1024*mib*.1 and target <= 512*mib
    assert memory_budget(16, 128*mib, 4*1024*mib)[0] == 0


@pytest.mark.parametrize("resolution", ["3840x2160", "3440x1440", "1920 × 1080"])
def test_gpu_resolution_allows_4k_and_custom_dimensions(resolution):
    result = validate_options({"kind": "gpu", "resolution": resolution})["resolution"]
    assert result == resolution.lower().replace("×", "x").replace(" ", "")


@pytest.mark.parametrize("options", [{"resolution": "99999x99999"}, {"resolution": "7680x4320"},
                                    {"gpu_test": "invalid"}, {"gpu_test": "vram", "gpu_vram_mb": 18}, {"gpu_artifacts": "false"}])
def test_gpu_options_reject_invalid_or_unbounded_requests(options):
    with pytest.raises(ValueError):
        validate_options({"kind": "gpu", **options})


def test_partial_vram_coverage_is_not_reported_as_complete():
    text = gpu_result_text({"verification_status": "partial", "vram": {"allocated_bytes": 16*1024**2,
        "unique_checked_bytes": 16*1024**2, "passes": 5, "cycles": 0, "coverage_complete": False}})
    assert "Cobertura parcial" in text and "Cobertura completa" not in text


def test_malformed_gpu_stats_do_not_break_report():
    text = gpu_result_text({"artifacts": [], "vram": {"checks": "bad", "cycles": 10**400,
                                                        "allocated_bytes": math.inf}})
    assert "N/D" in text


def test_gpu_mode_controls_separate_resolution_and_memory_budget():
    from modules.activity import ActivityState
    from modules.stress_view import StressPanel
    panel = StressPanel(ActivityState())
    panel.kind.setCurrentIndex(panel.kind.findData("gpu"))
    panel.gpu_test.setCurrentIndex(panel.gpu_test.findData("vram"))
    assert panel.resolution.isHidden() and not panel.vram_mb.isHidden()
    panel.gpu_test.setCurrentIndex(panel.gpu_test.findData("combined"))
    assert not panel.resolution.isHidden() and not panel.vram_mb.isHidden()
    panel.vram_auto.setChecked(True)
    assert not panel.vram_mb.isEnabled()


def test_analysis_prioritizes_gpu_divergence_and_exposes_coverage(tmp_path):
    from modules.analysis import analyze_session, report_text
    sample = {"monotonic": 100, "timestamp": "synthetic", "target_interval_ms": 500,
              "cpu_percent": 10, "cpu_max_core": 20, "ram_percent": 30, "gpus": [], "disks": [], "processes": []}
    (tmp_path/"amostras.jsonl").write_text(json.dumps(sample)+chr(10), encoding="utf-8")
    (tmp_path/"stress.json").write_text(json.dumps({"kind": "gpu", "state": "failed", "elapsed_s": 3,
        "verification_status": "failed", "errors": 1, "artifacts": {"checks": 2, "failed_checks": 1,
        "scene_pairs": 1, "known_patterns": 1, "mismatched_pixels": 1}}), encoding="utf-8")
    result = analyze_session(tmp_path)
    assert "Divergências detectadas" in result["explanation"]["summary"]
    assert "pixels divergentes" in report_text(result)
    assert "sem detector" not in report_text(result)


def test_gpu_error_becomes_evidence_without_images_or_addresses():
    from modules.ai_summary import ai_payload
    from modules.ai_contract import render_explanation
    payload = ai_payload({"stress": {"kind": "gpu", "state": "failed", "elapsed_s": 1, "vram": {
        "checks": 10, "failed_checks": 1, "examples": [{"byte_offset": 1234}], "path": "private-image.png"}}})
    row = next(row for row in payload["evidence"] if row["type"] == "gpu_verification")
    assert row["category"] == "graphics" and row["candidate"]
    text = render_explanation(json.dumps({"findings": [{"category": "graphics", "evidence_ids": [row["id"]]}]}), payload)
    assert "divergências: 1" in text and "Causa não confirmada" in text
    assert "1234" not in json.dumps(payload) and "private-image" not in json.dumps(payload)


def test_nonzero_worker_exit_does_not_claim_success_after_result_was_written():
    from types import SimpleNamespace
    from unittest.mock import patch
    from modules.activity import ActivityState
    from modules.stress_view import StressPanel
    panel = StressPanel(ActivityState())
    panel.phase, panel.options = "working", {"kind": "gpu", "duration_s": 5}
    panel.controller = SimpleNamespace(
        process=SimpleNamespace(poll=lambda: 1, returncode=1), close=lambda: None,
        status=lambda: {"kind": "gpu", "state": "completed", "verification_status": "passed", "errors": 0})
    with patch.object(panel, "finish_load") as finish:
        panel.poll()
    result = finish.call_args.args[0]
    assert result["state"] == "failed" and result["verification_status"] == "partial"
    assert result["errors"] == 0
    panel.phase = None


def test_hidden_gpu_fields_do_not_block_cpu_or_vram_only():
    assert validate_options({"kind": "cpu", "resolution": "mistyped", "gpu_vram_mb": "bad"})["kind"] == "cpu"
    options = validate_options({"kind": "gpu", "gpu_test": "vram", "resolution": "mistyped", "gpu_vram_mb": 16})
    assert options["resolution"] == "1280x720" and options["gpu_artifacts"] is False
