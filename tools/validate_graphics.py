import ctypes
import gzip
import json
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if os.name != "nt":
        raise SystemExit("Este teste usa Direct3D 11 no Windows.")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QWidget
    from modules.frametimes import FrameCapture, analyze_frames

    class Rational(ctypes.Structure):
        _fields_ = [("numerator", ctypes.c_uint32), ("denominator", ctypes.c_uint32)]

    class Mode(ctypes.Structure):
        _fields_ = [("width", ctypes.c_uint32), ("height", ctypes.c_uint32), ("refresh", Rational),
                    ("format", ctypes.c_uint32), ("scanline", ctypes.c_uint32), ("scaling", ctypes.c_uint32)]

    class Samples(ctypes.Structure):
        _fields_ = [("count", ctypes.c_uint32), ("quality", ctypes.c_uint32)]

    class SwapDescription(ctypes.Structure):
        _fields_ = [("mode", Mode), ("samples", Samples), ("usage", ctypes.c_uint32),
                    ("count", ctypes.c_uint32), ("window", ctypes.c_void_p), ("windowed", ctypes.c_int32),
                    ("effect", ctypes.c_uint32), ("flags", ctypes.c_uint32)]

    def method(pointer, index, result, *arguments):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *arguments)(table[index])

    destination = ROOT / "diagnosticos" / "validacao-grafica"
    destination.mkdir(parents=True, exist_ok=True)
    application = QApplication([])
    window = QWidget()
    window.setWindowTitle("SysPulse · teste gráfico sintético")
    window.resize(240, 160)
    window.show()
    application.processEvents()
    description = SwapDescription()
    description.mode.width, description.mode.height, description.mode.format = 240, 160, 28
    description.mode.refresh.numerator, description.mode.refresh.denominator = 60, 1
    description.samples.count = 1
    description.usage, description.count, description.windowed = 0x20, 1, 1
    description.window = int(window.winId())
    swap, device, context = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    feature = ctypes.c_uint32()
    create = ctypes.WinDLL("d3d11").D3D11CreateDeviceAndSwapChain
    create.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                       ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(SwapDescription),
                       ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
                       ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p)]
    create.restype = ctypes.c_long
    status = create(None, 1, None, 0, None, 0, 7, ctypes.byref(description), ctypes.byref(swap),
                    ctypes.byref(device), ctypes.byref(feature), ctypes.byref(context))
    if status < 0:
        raise OSError(f"Direct3D não iniciou: {status & 0xffffffff:#x}")
    present = method(swap, 8, ctypes.c_long, ctypes.c_uint32, ctypes.c_uint32)
    texture, target = ctypes.c_void_p(), ctypes.c_void_p()
    identifier = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID("6f15aaf2-d208-4e89-9ab4-489535d34f9c").bytes_le)
    get_buffer = method(swap, 9, ctypes.c_long, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    if get_buffer(swap, 0, ctypes.byref(identifier), ctypes.byref(texture)) < 0:
        raise OSError("Backbuffer indisponível")
    make_target = method(device, 9, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    if make_target(device, texture, None, ctypes.byref(target)) < 0:
        raise OSError("Render target indisponível")
    clear = method(context, 50, None, ctypes.c_void_p, ctypes.POINTER(ctypes.c_float))
    color = (ctypes.c_float * 4)(.12, .2, .4, 1)
    capture = FrameCapture()
    capture.start(destination, os.getpid(), seconds=10)
    started = time.monotonic()

    def render():
        elapsed = time.monotonic() - started
        if 2 <= elapsed < 2.2:
            return
        color[1] = .2 + .1 * (elapsed % 1)
        clear(context, target, color)
        present(swap, 0, 0)

    live = []
    live_timer = QTimer()
    live_timer.setInterval(2000)
    live_timer.timeout.connect(lambda: live.append(capture.live_snapshot()))
    live_timer.start()

    def finish():
        timer.stop()
        live_timer.stop()
        code = capture.stop()
        frame_file = capture.path or destination / "frametimes.csv"
        if frame_file.exists():
            with (gzip.open(frame_file, "rt", encoding="utf-8-sig") if frame_file.suffix == ".gz" else frame_file.open(encoding="utf-8-sig")) as file:
                result = analyze_frames(file, target_pid=os.getpid())
        else:
            result = {"series": [], "rows": 0, "invalid_rows": 0, "error": "CSV não gerado"}
        print("Plataforma Qt:", application.platformName(), flush=True)
        result["live_snapshots"] = live
        result["synthetic"] = True
        result["injected_pause_ms"] = 200
        result["exit_code"] = code
        (destination / "resultado.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"series": [{k: r[k] for k in ("count", "median_ms", "p99_ms", "max_ms", "long_intervals", "metric", "alignment")}
                                     for r in result["series"]], "rows": result["rows"], "invalid_rows": result["invalid_rows"],
                          "exit_code": code, "live_ok": sum(row.get("state") == "ok" for row in live)}, ensure_ascii=True, indent=2))
        for pointer in (target, texture, context, device, swap):
            method(pointer, 2, ctypes.c_uint32)(pointer)
        window.close()
        application.quit()

    timer = QTimer()
    timer.setInterval(16)
    timer.timeout.connect(render)
    timer.start()
    QTimer.singleShot(11500, finish)
    application.exec()


if __name__ == "__main__":
    main()
