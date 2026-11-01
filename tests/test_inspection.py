import json
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from modules.inspection import driver_rows, inspect_system, inspection_text
from modules.diagnostics import SessionRecorder
from modules.analysis import analyze_session, report_text
from modules.demo import demo_inventory, write_demo_session


def test_drivers_match_case_insensitive_ids_and_keep_missing_devices():
    snapshot = demo_inventory()
    snapshot['sections']['drivers']['rows'][0]['DeviceID'] = 'demo_gpu'
    rows = {r['id'].upper(): r for r in driver_rows(snapshot)}
    assert len(rows) == 3
    assert rows['DEMO_GPU']['status'] == 'Sem erro PnP'
    assert rows['DEMO_WIFI']['status'] == 'Desativado'
    assert rows['DEMO_USB']['status'] == 'Atenção'
    assert rows['DEMO_USB']['signed'] is None
    assert rows['DEMO_USB']['version'] is None


def test_old_driver_is_not_classified_as_outdated():
    snapshot = demo_inventory()
    snapshot['sections']['drivers']['rows'][0]['DriverDate'] = '2006-06-21'
    assert next(r for r in driver_rows(snapshot) if r['id'] == 'DEMO_GPU')['status'] == 'Sem erro PnP'


def test_unsigned_is_attention_but_disconnected_is_not_fault():
    snapshot = demo_inventory()
    snapshot['sections']['drivers']['rows'][0]['IsSigned'] = False
    assert next(r for r in driver_rows(snapshot) if r['id'] == 'DEMO_GPU')['status'] == 'Atenção'
    snapshot['sections']['devices']['rows'][0]['Present'] = False
    assert next(r for r in driver_rows(snapshot) if r['id'] == 'DEMO_GPU')['status'] == 'Ausente'


def test_query_failure_does_not_look_healthy():
    with patch('modules.inspection.platform.system', return_value='Windows'), patch('modules.inspection.subprocess.run', side_effect=subprocess.TimeoutExpired('powershell', 45)):
        snapshot = inspect_system()
    assert all(s['status'] == 'erro' and s['error'] for s in snapshot['sections'].values())
    assert not driver_rows(snapshot)
    assert 'indisponível' in inspection_text(snapshot)


def test_platform_without_windows_stays_explicit():
    with patch('modules.inspection.platform.system', return_value='Linux'), patch('modules.inspection.subprocess.run') as run:
        snapshot = inspect_system()
    run.assert_not_called()
    assert all(s['status'] == 'não suportado neste sistema' for s in snapshot['sections'].values())


def test_partial_query_and_single_result_are_preserved():
    response = {'drivers': {'status': 'ok', 'rows': {'DeviceID': 'a', 'DriverVersion': '1'}},
                'devices': {'status': 'erro', 'error': 'Access denied', 'rows': []}}
    with patch('modules.inspection.platform.system', return_value='Windows'), patch('modules.inspection.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(response))) as run:
        snapshot = inspect_system()
    assert driver_rows(snapshot)[0]['version'] == '1'
    assert driver_rows(snapshot)[0]['code'] is None
    assert snapshot['sections']['storage']['status'] == 'erro'
    assert run.call_args.kwargs['timeout'] == 45
    assert 'shell' not in run.call_args.kwargs


def test_inventory_roundtrip_in_recording_and_analysis(tmp_path):
    recorder = SessionRecorder()
    try:
        recorder.command('start', {'folder': str(tmp_path), 'inventory': demo_inventory()})
        recorder.commands.join()
        recorder.submit({'monotonic': 1, 'timestamp': '2026-01-15T14:30:00-03:00', 'cpu_percent': 4})
        recorder.command('inventory', demo_inventory())
        recorder.command('stop')
        recorder.commands.join()
        result = analyze_session(recorder.path)
        assert result['inventory']['demo'] is True
        assert 'USB de demonstração' in report_text(result)
    finally:
        recorder.shutdown()


def test_older_session_without_inventory_remains_readable(tmp_path):
    write_demo_session(tmp_path)
    (tmp_path / 'inventario.json').unlink()
    result = analyze_session(tmp_path)
    assert result['inventory'] is None
    assert result['summary']['samples'] == 181
    assert any('Sem inventário' in w for w in result['warnings'])
