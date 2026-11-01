import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description="Mede CPU, RAM, cadência e arquivos de uma captura nativa.")
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--offscreen", action="store_true")
    parser.add_argument("--output", default=str(ROOT / "diagnosticos" / "benchmark"))
    args = parser.parse_args()
    if not 30 <= args.duration <= 7200:
        parser.error("Duração entre 30 e 7200 segundos.")
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import psutil
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon
    from gui import App

    destination = Path(args.output) / time.strftime("%Y%m%d-%H%M%S")
    destination.mkdir(parents=True, exist_ok=True)
    application = QApplication([])
    if args.offscreen and os.name == "nt":
        font = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts/segoeui.ttf"
        font_id = QFontDatabase.addApplicationFont(str(font))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            application.setFont(QFont(families[0]))
    hotkey = SimpleNamespace(registered=False, error="Atalho desativado neste teste", close=lambda: None)
    process = psutil.Process()
    rows, collection, intervals = [], [], []
    started = previous = time.monotonic()
    previous_cpu = sum(process.cpu_times()[:2])
    seen = None
    recording_at = None
    finishing_at = None
    recording_path = None

    def stats(values):
        return {"mean": statistics.mean(values), "max": max(values), "min": min(values)} if values else {}

    with patch("gui.GlobalHotkey", return_value=hotkey), patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False):
        window = App()
        if not args.offscreen:
            window.show()
        window.show_page(1)

        def poll():
            nonlocal previous, previous_cpu, seen, recording_at, finishing_at, recording_path
            now = time.monotonic()
            cpu = sum(process.cpu_times()[:2])
            value = (cpu - previous_cpu) / max(.001, now - previous) * 100
            rows.append({"elapsed_s": now - started, "recording": recording_at is not None and finishing_at is None,
                         "cpu_machine_percent": value / (psutil.cpu_count() or 1),
                         "rss_mib": process.memory_info().rss / 1024 ** 2})
            previous, previous_cpu = now, cpu
            sample = window.worker_monitor.latest()
            if sample and sample["monotonic"] != seen:
                seen = sample["monotonic"]
                collection.append(sample["collector_ms"])
                intervals.append(sample["interval_ms"])
            if recording_at is None:
                if now - started < 8 or window._inventory is None and now - started < 50:
                    return
                window.send_command("start", {"folder": str(destination), "compressed": True, "csv": False,
                                               "duration_s": args.duration, "mode": "light", "interval_ms": 500,
                                               "symptom": "system"})
                recording_at = now
                print("Captura iniciada:", args.duration, "s", flush=True)
            elif finishing_at is None:
                recording_path = window.recorder.path
                if now - recording_at >= args.duration:
                    window.send_command("stop")
                    finishing_at = now
            elif window.analysis.result is not None or now - finishing_at > 60:
                timer.stop()
                selected = [row for row in rows if row["recording"]]
                metadata = {}
                if recording_path and (recording_path / "sessao.json").exists():
                    metadata = json.loads((recording_path / "sessao.json").read_text(encoding="utf-8"))
                result = {"duration_requested_s": args.duration, "offscreen": args.offscreen,
                          "logical_cpus": psutil.cpu_count(), "python": sys.version.split()[0],
                          "cpu_machine_percent": stats([row["cpu_machine_percent"] for row in selected]),
                          "rss_mib": stats([row["rss_mib"] for row in selected]),
                          "rss_first_last_mib": [selected[0]["rss_mib"], selected[-1]["rss_mib"]] if selected else [],
                          "collector_ms": stats(collection), "interval_ms": stats(intervals),
                          "count": metadata.get("count"), "dropped": metadata.get("dropped"),
                          "analysis_completed": window.analysis.result is not None,
                          "warnings": (window.analysis.result or {}).get("warnings", []),
                          "files_bytes": {p.name: p.stat().st_size for p in recording_path.iterdir() if p.is_file()} if recording_path else {},
                          "scope": "CPU do processo Python, exclui filhos. Captura nativa sem jogo ou IA; não mede outros processos da máquina.",
                          "inference_started": window.activity.inference}
                (destination / "benchmark.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                (destination / "observacoes.json").write_text(json.dumps(rows), encoding="utf-8")
                window.shutdown()
                window.close()
                print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)
                application.quit()

        timer = QTimer()
        timer.setInterval(1000)
        timer.timeout.connect(poll)
        timer.start()
        application.exec()


if __name__ == "__main__":
    main()
