import json

import pytest

from modules.assessment import Assessment, Series
from modules.analysis import analyze_session, resource_values


def reading(at, **extra):
    return {"monotonic": at, "timestamp": str(at), "target_interval_ms": 500,
            "cpu_percent": 95, "cpu_max_core": 95, "ram_percent": 40, **extra}


def add(assessment, sample):
    values, devices = resource_values(sample)
    assessment.add(sample, values, devices)


def test_p95_uses_nearest_rank_and_missing_is_not_zero():
    stat = Series(percentiles=True)
    for value in [None, True, float('nan'), float('inf'), *range(1, 21)]:
        stat.add(value)
    result = stat.result()
    assert result['count'] == 20
    assert result['min'] == 1
    assert result['max'] == 20
    assert result['mean'] == 10.5
    assert result['p95'] == 19


def test_sustained_sequence_breaks_on_gap_missing_and_device_change():
    stat = Series()
    for at in range(7):
        stat.add(95, at, 90, 1, 'cpu0')
    stat.add(95, 10, 90, 1, 'cpu0')
    stat.add(95, 11, 90, 1, 'cpu1')
    stat.add(None, 12, 90, 1, 'cpu1')
    stat.add(95, 13, 90, 1, 'cpu1')
    stat.add(95, 14, 90, 1, 'cpu1')
    result = stat.result()
    assert result['high_seconds'] == 7
    assert result['longest_high_s'] == 6
    assert result['covered_seconds'] == 7


def test_isolated_peak_has_zero_duration_and_sustained_requires_five_seconds():
    assessment = Assessment()
    add(assessment, reading(0))
    assert all('curta' in f['title'] for f in assessment.result()['findings'])
    for at in range(1, 11):
        add(assessment, reading(at / 2))
    cpu = assessment.result()['resources'][0]
    assert cpu['longest_high_s'] == 5
    assert any('persistente' in f['title'] for f in assessment.result()['findings'])


def test_cached_sensors_count_once_and_stale_values_are_excluded():
    assessment = Assessment()
    for at, batch, age, value in ((1, 1, 0, 50), (1.5, 1, 500, 50), (2, 2, 0, 70), (7, 2, 5000, 99)):
        add(assessment, reading(at, sensor_sample_monotonic=batch, sensor_age_ms=age,
                                cpu_temperature=value, gpus=[{'id': 'gpu0', 'name': 'GPU', 'percent': value}]))
    result = assessment.result()
    temperature = next(r for r in result['telemetry'] if r['key'] == 'temperature')
    gpu = next(r for r in result['resources'] if r['key'] == 'gpu')
    assert temperature['count'] == 2
    assert temperature['mean'] == 60
    assert gpu['count'] == 2
    assert gpu['max'] == 70


def test_disk_latency_preserves_device_identity_and_zero_operations():
    assessment = Assessment()
    add(assessment, reading(1, disks=[{'name': 'disk0', 'read_ms': 50}, {'name': 'disk1', 'read_ms': None}]))
    add(assessment, reading(2, disks=[{'name': 'disk0', 'read_ms': None}, {'name': 'disk1', 'read_ms': 2}]))
    rows = {r['key']: r for r in assessment.result()['telemetry']}
    assert rows['disk:disk0:read_ms']['mean'] == 50
    assert rows['disk:disk1:read_ms']['mean'] == 2
    assert rows['disk:disk0:read_ms']['count'] == 1


@pytest.mark.parametrize('inventory', [[], {'sections': []}, {'sections': {'storage': {'rows': [1]}}},
                                     {'sections': {'storage': {'rows': [{'Reliability': 'bad'}]}}},
                                     {'sections': {}, 'bad': float('nan')}])
def test_bad_inventory_does_not_discard_capture(tmp_path, inventory):
    (tmp_path / 'amostras.jsonl').write_text(json.dumps(reading(1)))
    (tmp_path / 'inventario.json').write_text(json.dumps(inventory))
    result = analyze_session(tmp_path)
    assert result['inventory'] is None
    assert result['summary']['samples'] == 1
    assert any('Inventário ilegível' in warning for warning in result['warnings'])


def test_telemetry_limit_is_reported():
    assessment = Assessment()
    for index in range(513):
        assessment.metric(str(index), str(index), "%", 1)
    result = assessment.result()
    assert len(result["telemetry"]) == 512
    assert result["truncated"] is True
