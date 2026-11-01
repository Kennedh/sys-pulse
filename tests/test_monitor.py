from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from modules.monitor import MonitorWorker, disk_rates
from modules.diagnostics import event_summary


class FakeProcess:
    pid = 10
    info = {'name': 'app.exe'}
    created = 1

    def oneshot(self):
        return nullcontext()

    def create_time(self):
        return self.created

    def cpu_percent(self):
        return 80

    def memory_percent(self):
        return 1

    def memory_info(self):
        return SimpleNamespace(rss=1024 ** 2)

    def io_counters(self):
        return SimpleNamespace(read_bytes=10, write_bytes=10)


def test_new_process_and_reused_pid_require_cpu_baseline():
    worker = MonitorWorker()
    worker._cpu_count = 4
    process = FakeProcess()
    with patch('modules.monitor.psutil.process_iter', return_value=[process]):
        assert worker._processes()[0]['cpu_percent'] is None
        assert worker._processes()[0]['cpu_percent'] == 20
        process.created = 2
        assert worker._processes()[0]['cpu_percent'] is None


def test_event_report_accepts_process_during_warmup():
    result = event_summary({'monotonic': 1}, [{'monotonic': 1, 'processes': [
        {'pid': 10, 'name': 'new', 'created': 1, 'cpu_percent': None}]}])
    assert result['top_processes'] == []


def test_iops_uses_real_elapsed_time_and_does_not_invent_latency():
    old = SimpleNamespace(read_bytes=0, write_bytes=0, read_count=0, write_count=0, read_time=0, write_time=0)
    new = SimpleNamespace(read_bytes=1024, write_bytes=0, read_count=10, write_count=0, read_time=25, write_time=0)
    row = disk_rates({'disk0': old}, {'disk0': new}, .5)[0]
    assert row['read_iops'] == 20
    assert row['read_ms'] == 2.5
    assert row['write_iops'] == 0
    assert row['write_ms'] is None



def test_slow_process_scan_does_not_block_resource_sampling():
    import threading

    scanning = threading.Event()
    release = threading.Event()
    sampled = threading.Event()
    worker = MonitorWorker(on_sample=lambda sample: sampled.set())
    worker.interval = .05
    worker.sensors = SimpleNamespace(start=lambda: None, stop=lambda: None, snapshot=lambda: {})

    def slow_processes(*args):
        scanning.set()
        assert release.wait(5)
        return []

    counter = SimpleNamespace(sample=lambda: {}, close=lambda: None)
    try:
        with (patch.object(worker, "_processes", side_effect=slow_processes),
              patch("modules.monitor.WindowsCounters", return_value=counter)):
            worker.start()
            assert scanning.wait(2)
            assert sampled.wait(2), "Varredura de processos bloqueou métricas rápidas"
            assert not release.is_set()
            latest = worker.latest()
            assert latest["process_age_ms"] is None
            assert latest["process_sample_monotonic"] is None
    finally:
        release.set()
        worker.stop()
    assert not worker._process_thread.is_alive()
    assert not worker._thread.is_alive()
