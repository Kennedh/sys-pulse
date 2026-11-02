import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def self_test(folder):
    from PySide6.QtGui import QGuiApplication, QOpenGLContext, QOffscreenSurface, QSurfaceFormat, QColor
    from PySide6.QtOpenGL import QOpenGLFunctions_3_2_Core, QOpenGLVertexArrayObject
    from modules.gpu_checks import MemoryCheck, ArtifactCheck
    app = QGuiApplication([])
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 2)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()
    context = QOpenGLContext()
    context.setFormat(fmt)
    if not context.create() or not context.makeCurrent(surface):
        raise RuntimeError("Contexto OpenGL indisponível.")
    gl = QOpenGLFunctions_3_2_Core()
    if not gl.initializeOpenGLFunctions():
        raise RuntimeError("OpenGL 3.2 indisponível.")
    renderer = context.functions().glGetString(0x1F01)
    renderer = renderer.decode("utf-8", "replace") if isinstance(renderer, bytes) else str(renderer)
    if any(name in renderer.lower() for name in ("llvmpipe", "software", "swiftshader", "softpipe", "microsoft basic")):
        raise RuntimeError("O autoteste exige GPU real.")
    vao = QOpenGLVertexArrayObject()
    assert vao.create()
    vao.bind()
    for state in (0x0BD0, 0x0BE2, 0x8DB9):
        gl.glDisable(state)
    artifacts = ArtifactCheck(gl)
    memory = None
    started = time.monotonic()
    try:
        assert artifacts.known_pattern()["words"] == 0
        first = artifacts.buffer.toImage(False)
        assert artifacts.compare_scene(first, first.copy())["words"] == 0
        changed = first.copy()
        changed.setPixelColor(0, 0, QColor(255, 1, 2, 255))
        assert artifacts.compare_scene(first, changed)["words"] == 1
        memory = MemoryCheck(context, gl, 16)
        deadline = time.monotonic()+20
        while not memory.stats["cycles"] and time.monotonic() < deadline:
            memory.step()
        assert memory.stats["coverage_complete"] and memory.stats["failed_checks"] == 0
        healthy = dict(memory.stats)
        while memory.stats["phase"] != "Verificando":
            memory.step()
        function = ctypes.WINFUNCTYPE if os.name == "nt" else ctypes.CFUNCTYPE
        write = function(None, ctypes.c_uint, ctypes.c_ssize_t, ctypes.c_ssize_t, ctypes.c_void_p)(
            context.getProcAddress(b"glBufferSubData"))
        gl.glBindBuffer(0x8892, memory.buffers[0])
        wrong = ctypes.c_uint(1)
        write(0x8892, 0, 4, ctypes.byref(wrong))
        assert gl.glGetError() == 0
        memory.step()
        assert memory.stats["mismatched_words"] == 1 and memory.stats["mismatched_bits"] == 1
        report = {"synthetic_faults": True, "renderer": renderer, "elapsed_s": time.monotonic()-started,
                  "healthy_memory": healthy, "injected_memory_errors": memory.stats["mismatched_words"],
                  "injected_image_errors": artifacts.stats["failed_checks"], "gl_error": gl.glGetError()}
        (folder/"autoteste.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True))
    finally:
        if memory:
            memory.close()
        artifacts.buffer = None
        artifacts.program.removeAllShaders()
        vao.release()
        vao.destroy()
        context.doneCurrent()



def fault_test(folder):
    import psutil
    from unittest.mock import patch
    from modules.stress_gpu import run_gpu
    from modules.gpu_checks import ArtifactCheck
    path = folder / ("falha-controlada-"+uuid.uuid4().hex[:8])
    path.mkdir()
    parent = psutil.Process()
    original = ArtifactCheck.compare_scene

    def inject(checker, first, second):
        color = second.pixelColor(0, 0)
        color.setRed(color.red() ^ 1)
        second.setPixelColor(0, 0, color)
        return original(checker, first, second)

    with patch.object(ArtifactCheck, "compare_scene", inject):
        code = run_gpu(path, {"kind": "gpu", "duration_s": 4, "intensity": 25, "gpu_profile": "geometry",
            "gpu_test": "scene", "gpu_artifacts": True, "gpu_vram_mb": 16, "resolution": "1280x720",
            "parent_pid": parent.pid, "parent_created": parent.create_time()})
    result = json.loads((path/"result.json").read_text(encoding="utf-8"))
    result["synthetic_fault"] = True
    (path/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert code == 1 and result["state"] == "failed" and result["artifacts"]["mismatched_pixels"] == 1
    assert result["elapsed_s"] < 2 and len(result["evidence"]) == 2
    assert all((path/name).is_file() for name in result["evidence"])
    print(json.dumps({key: result.get(key) for key in
          ("synthetic_fault", "state", "elapsed_s", "checks", "errors", "verification_status", "evidence")}))

def worker_test(args, folder):
    from modules.stress import StressController, validate_options
    options = validate_options({"kind": "gpu", "duration_s": args.duration, "intensity": 25,
                               "resolution": args.resolution, "gpu_test": args.mode, "gpu_profile": "geometry",
                               "gpu_artifacts": True, "gpu_vram_mb": args.vram_mb})
    if args.executable:
        import psutil
        parent = psutil.Process()
        path = folder / ("executavel-"+uuid.uuid4().hex[:8])
        path.mkdir()
        (path/"request.json").write_text(json.dumps({**options, "parent_pid": parent.pid,
            "parent_created": parent.create_time()}), encoding="utf-8")
        process = subprocess.run([str(Path(args.executable).resolve()), "--stress-worker", str(path.resolve())],
                                 timeout=args.duration+20)
        result = json.loads((path/"result.json").read_text(encoding="utf-8"))
        code = process.returncode
    else:
        controller = StressController()
        try:
            path = controller.start(folder, options)
            code = controller.process.wait(timeout=args.duration+20)
            result = controller.status()
        finally:
            controller.close()
    print(json.dumps({"exit_code": code, "path": str(path),
                      **{key: result.get(key) for key in ("state", "reason", "render_resolution", "checks", "errors",
                                                          "verification_status", "artifacts", "vram")}}, ensure_ascii=True))
    if code or result.get("state") not in ("completed", "stopped") or result.get("errors"):
        raise RuntimeError("A validação GPU não concluiu sem falhas; confira o resultado e o log.")
    if args.mode != "vram":
        assert result["render_resolution"] == list(map(int, options["resolution"].split("x")))
        assert result.get("artifacts", {}).get("known_patterns")
    else:
        assert result.get("vram", {}).get("checks")


def main():
    parser = argparse.ArgumentParser(description="Valida GPU com carga curta; corrupção injetada não indica defeito real.")
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument("--fault-test", action="store_true", help="Injeta um pixel divergente para conferir parada e evidências.")
    checks.add_argument("--self-test", action="store_true", help="Verifica 16 MiB, os 70 padrões e injeta um erro controlado.")
    parser.add_argument("--mode", choices=("scene", "vram", "combined"), default="scene")
    parser.add_argument("--duration", type=int, default=5)
    parser.add_argument("--resolution", default="1280x720")
    parser.add_argument("--vram-mb", type=int, default=16)
    parser.add_argument("--executable")
    parser.add_argument("--output", default=str(ROOT/"diagnosticos/validacao-3.4"))
    args = parser.parse_args()
    if not 1 <= args.duration <= 30 or not 16 <= args.vram_mb <= 64:
        parser.error("Esta validação curta aceita até 30 s e de 16 a 64 MiB.")
    folder = Path(args.output)
    folder.mkdir(parents=True, exist_ok=True)
    if args.self_test:
        self_test(folder)
    elif args.fault_test:
        fault_test(folder)
    else:
        worker_test(args, folder)


if __name__ == "__main__":
    main()
