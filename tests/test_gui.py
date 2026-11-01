import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from gui import App
from modules.demo import demo_inventory
from modules.advanced_view import AdvancedPanel
from modules.advanced_analysis import analyze_etl


def wait_for(application, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(.01)
    assert predicate()


def test_inventory_arriving_before_recorder_start_is_attached(tmp_path):
    application = QApplication.instance() or QApplication([])
    window = App(demo=True)
    try:
        window._inventory = None
        window.recorder.command('start', {'folder': str(tmp_path)})
        window.on_inventory(demo_inventory())
        wait_for(application, lambda: window.recorder.active.is_set())
        wait_for(application, lambda: (window.recorder.path / 'inventario.json').exists())
        window.inspection.search.setText('USB')
        assert window.inspection.drivers.rowCount() == 1
        window.inspection.filter.setCurrentText('Desativado')
        assert window.inspection.drivers.rowCount() == 0
    finally:
        window.shutdown()
        window.close()


@pytest.mark.parametrize('finish_resources_first', [True, False])
def test_advanced_stops_resources_before_etl_analysis(tmp_path, finish_resources_first):
    application = QApplication.instance() or QApplication([])
    panel = AdvancedPanel()
    panel.timer.stop()
    panel.controller.path = tmp_path
    state = {'state': 'recording', 'message': 'Teste simulado'}
    calls = []

    def tool(arguments, log, cancel):
        calls.append(arguments)
        output = Path(arguments[arguments.index('-o') + 1])
        fixture = Path(__file__).parent / 'fixtures/dpc-isr-simulado.txt'
        output.write_text(fixture.read_text() if arguments[-1] == 'dpcisr' else 'Events Lost: 0')

    def analyze(source, destination, cancel, native):
        assert panel.native_finished
        assert not panel.recorder.active.is_set()
        assert native['summary']['samples'] == 2
        with patch('modules.advanced_analysis.run_tool', side_effect=tool):
            return analyze_etl(source, destination, cancel, native, xperf='xperf.exe')

    try:
        with patch.object(panel.controller, 'status', side_effect=lambda: state), patch('modules.advanced_view.analyze_etl', side_effect=analyze):
            panel.poll()
            wait_for(application, lambda: panel.native_path is not None)
            for at in (1, 2):
                panel.submit({'timestamp': f'2026-10-28T12:00:0{at}-03:00', 'monotonic': at,
                              'cpu_percent': 95, 'cpu_max_core': 99, 'ram_percent': 40,
                              'disks': [], 'gpus': [], 'processes': [], 'target_interval_ms': 1000})
            state['state'] = 'stopping'
            panel.poll()
            assert panel.native_stop_requested
            assert not panel.start_button.isEnabled()
            if finish_resources_first:
                wait_for(application, lambda: panel.native_finished)
                assert not calls
            (tmp_path / 'captura.etl').write_bytes(b'simulated-etl')
            state['state'] = 'completed'
            panel.poll()
            wait_for(application, lambda: panel.result is not None)
            assert len(calls) == 2
            assert 'CPU total' in panel.explanation.toPlainText()
            assert panel.result['native_summary']['duration_s'] == 1
            assert (tmp_path / 'context.json').exists()
            assert (tmp_path / 'analise/analise-avancada.txt').exists()
    finally:
        panel.shutdown()
        panel.close()



def test_marker_comparison_is_visible_in_analysis_panel(tmp_path):
    from modules.analysis import analyze_session
    from modules.analysis_view import AnalysisPanel
    from modules.demo import write_demo_session

    application = QApplication.instance() or QApplication([])
    write_demo_session(tmp_path)
    result = analyze_session(tmp_path)
    panel = AnalysisPanel()
    try:
        panel.accept_result(panel._generation, result)
        application.processEvents()
        assert panel.event_table.columnCount() == 6
        assert panel.event_table.rowCount() == len(result["summary"]["resources"])
        assert panel.event_table.item(0, 4).text() != "N/D"
        assert "Perto do sintoma" in panel.explanation.toPlainText()
        assert "marcações" in panel.insight.text()
    finally:
        panel.shutdown()
        panel.close()
