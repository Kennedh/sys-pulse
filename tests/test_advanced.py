import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from modules.advanced_analysis import (parse_dpc_report, parse_trace_quality, explain_capture, readable_report,
                                       analyze_etl, run_tool, AdvancedCancelled)
from modules.advanced_capture import CaptureController, run_capture, write_json, wpr_command
from modules.ai_summary import ai_payload, validate_endpoint, explain_with_ai


FIXTURE = Path(__file__).parent / "fixtures/dpc-isr-simulado.txt"


def test_dpc_and_isr_are_separate_and_cpu_times_are_summed():
    result = parse_dpc_report(FIXTURE.read_text())
    rows = {(r["kind"], r["module"]): r for r in result["drivers"]}
    dpc = rows["DPC", "rede-demo.sys"]
    assert dpc["total_us"] == 12000
    assert dpc["count"] == 4
    assert dpc["mean_us"] == 3000
    assert dpc["max_us"] is None
    assert (dpc["max_bucket_low_us"], dpc["max_bucket_high_us"]) == (128, 8192)
    assert rows["ISR", "rede-demo.sys"]["total_us"] == 300
    assert result["intervals"][0]["total_us"] == 6000
    assert result["duration_s"] == 10
    assert any("não identificados" in warning for warning in result["warnings"])


def test_incomplete_histogram_does_not_invent_maximum():
    text = FIXTURE.read_text().replace('Total = 4 for module', 'Total = 40 for module')
    result = parse_dpc_report(text)
    assert result["drivers"][0]["max_bucket_high_us"] is None
    assert any("incompleto" in warning for warning in result["warnings"])


def test_unknown_format_is_not_a_clean_bill_of_health():
    result = parse_dpc_report("No useful DPC output")
    explanation = explain_capture(result)
    assert not result["drivers"]
    assert "insuficientes" in explanation["summary"]
    assert "Causa não confirmada" in explanation["conclusion"]


def test_shared_module_and_loss_are_explained_without_blame():
    result = parse_dpc_report(FIXTURE.read_text().replace('rede-demo.sys', 'ndis.sys'))
    result['quality'] = parse_trace_quality('Events Lost: 3\nLost Events = 2')
    explanation = explain_capture(result)
    assert result['quality']['lost_events'] == 5
    assert any('compartilhada' in e['meaning'] for e in explanation['evidence'])
    assert any('parciais' in text for text in explanation['limitations'])
    assert 'valor exato não está disponível' in explanation['evidence'][0]['observed']
    assert 'Próximo teste:' in readable_report({'explanation': explanation})


def test_xperf_pipeline_saves_explained_report_and_keeps_etl(tmp_path):
    source = tmp_path / 'captura.etl'
    source.write_bytes(b'fixture-etl')
    calls = []

    def tool(arguments, log, cancel):
        calls.append(arguments)
        output = Path(arguments[arguments.index('-o') + 1])
        output.write_text(FIXTURE.read_text() if arguments[-1] == 'dpcisr' else 'Events Lost: 0')

    with patch('modules.advanced_analysis.run_tool', side_effect=tool):
        result = analyze_etl(source, tmp_path / 'report', xperf='xperf.exe')
    assert source.read_bytes() == b'fixture-etl'
    assert result['quality']['lost_events'] == 0
    assert len(calls) == 2
    assert (tmp_path / 'report/analise-avancada.txt').exists()
    assert json.loads((tmp_path / 'report/analise-avancada.json').read_text())['explanation']


def test_cancel_terminates_only_analysis_process(tmp_path):
    process = SimpleNamespace(poll=lambda: None, terminate=lambda: called.append('terminate'), wait=lambda timeout: 0, returncode=0)
    called = []
    with patch('modules.advanced_analysis.subprocess.Popen', return_value=process):
        with pytest.raises(AdvancedCancelled):
            run_tool(['xperf', '-i', 'file.etl'], tmp_path / 'log', lambda: True)
    assert called == ['terminate']


def test_wpr_instance_is_last_and_arbitrary_instances_are_rejected():
    instance = 'SysPulse_' + 'a' * 32
    with patch('modules.advanced_capture.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=b'ok', stderr=b'')) as run:
        wpr_command('wpr.exe', instance, '-stop', 'C:/trace with spaces/trace.etl')
    assert run.call_args.args[0][-2:] == ['-instancename', instance]
    assert run.call_args.args[0][2] == 'C:/trace with spaces/trace.etl'
    with pytest.raises(ValueError):
        wpr_command('wpr.exe', 'another-session', '-cancel')


def capture_request(tmp_path):
    identity = 'a' * 32
    (tmp_path / 'commands').mkdir()
    write_json(tmp_path / 'request.json', {'id': identity, 'seconds': 15, 'parent_pid': 100, 'parent_created': 1})
    return identity


def test_capture_saves_own_etl_when_parent_exits(tmp_path):
    identity = capture_request(tmp_path)
    calls = []

    def run(executable, instance, *arguments, **kwargs):
        calls.append((instance, arguments))
        if arguments[0] == '-stop':
            Path(arguments[1]).write_bytes(b'etl-data')
        return 'ok'

    parent = SimpleNamespace(create_time=lambda: 1, is_running=lambda: False)
    with patch('modules.advanced_capture.find_tools', return_value={'wpr': 'wpr.exe'}), patch('modules.advanced_capture.is_admin', return_value=True), patch('modules.advanced_capture.psutil.Process', return_value=parent):
        run_capture(tmp_path, identity, run=run)
    status = json.loads((tmp_path / 'status.json').read_text())
    assert status['state'] == 'completed'
    assert all(instance == 'SysPulse_' + identity for instance, _ in calls)
    assert not any(args[0] == '-cancel' for _, args in calls)


def test_capture_start_failure_cleans_only_own_instance(tmp_path):
    identity = capture_request(tmp_path)
    calls = []

    def run(executable, instance, *arguments, **kwargs):
        calls.append((instance, arguments))
        if arguments[0] == '-start':
            raise RuntimeError('collector conflict')
        return ''

    parent = SimpleNamespace(create_time=lambda: 1)
    with patch('modules.advanced_capture.find_tools', return_value={'wpr': 'wpr.exe'}), patch('modules.advanced_capture.is_admin', return_value=True), patch('modules.advanced_capture.psutil.Process', return_value=parent):
        run_capture(tmp_path, identity, run=run)
    assert json.loads((tmp_path / 'status.json').read_text())['state'] == 'failed'
    assert calls[-1] == ('SysPulse_' + identity, ('-cancel',))


def test_stop_before_uac_completion_never_starts_wpr(tmp_path):
    identity = capture_request(tmp_path)
    (tmp_path / 'stop.request').touch()
    parent = SimpleNamespace(create_time=lambda: 1)
    with patch('modules.advanced_capture.find_tools', return_value={'wpr': 'wpr.exe'}), patch('modules.advanced_capture.is_admin', return_value=True), patch('modules.advanced_capture.psutil.Process', return_value=parent), patch('modules.advanced_capture.wpr_command') as run:
        run_capture(tmp_path, identity, run=run)
    run.assert_not_called()
    assert json.loads((tmp_path / 'status.json').read_text())['state'] == 'cancelled'


def test_uac_refusal_does_not_start_capture(tmp_path):
    controller = CaptureController()
    with patch('modules.advanced_capture.find_tools', return_value={'wpr': 'wpr.exe'}), patch('modules.advanced_capture.shutil.disk_usage', return_value=SimpleNamespace(free=5 * 1024 ** 3)), patch('modules.advanced_capture.request_admin', side_effect=PermissionError('recusada')), patch('modules.advanced_capture.psutil.Process', return_value=SimpleNamespace(create_time=lambda: 1)):
        controller.start(tmp_path)
        controller._thread.join(2)
    assert controller.status()['state'] == 'cancelled'
    assert not (controller.path / 'captura.etl').exists()


def test_ai_payload_excludes_private_details_and_instructions():
    result = {'source': 'C:/Users/Secret/trace.etl', 'note': 'private-note',
              'drivers': [{'module': 'C:/Windows/System32/drivers/ndis.sys', 'kind': 'DPC', 'total_us': 3}],
              'native_summary': {'processes': [{'name': 'private-process'}], 'assessment': {'resources': [{'key': 'cpu', 'max': 99}]}}}
    payload = ai_payload(result)
    text = json.dumps(payload)
    assert all(secret not in text for secret in ('Secret', 'private-note', 'private-process', 'C:/'))
    assert payload['drivers'][0]['module'] == 'ndis.sys'
    assert payload['causality_confirmed'] is False


@pytest.mark.parametrize('endpoint', ['http://external.test/v1/chat/completions', 'https://user:key@host/v1/chat/completions',
                                      'file:///tmp/test', 'https://host/v1/chat/completions?key=secret'])
def test_ai_rejects_unsafe_endpoint(endpoint):
    with pytest.raises(ValueError):
        validate_endpoint(endpoint)


def test_ai_local_endpoint_and_response_contract():
    endpoint = 'http://127.0.0.1:11434/v1/chat/completions'
    assert validate_endpoint(endpoint)[1] is True
    response = SimpleNamespace(read=lambda size: b'{"choices":[{"message":{"content":"Causa nao confirmada"}}]}')
    class Context:
        def __enter__(self):
            return response
        def __exit__(self, *args):
            pass
    opener = SimpleNamespace(open=lambda request, timeout: Context())
    with patch('modules.ai_summary.urllib.request.build_opener', return_value=opener):
        assert 'nao confirmada' in explain_with_ai(endpoint, 'modelo-teste', '', {'drivers': []})
