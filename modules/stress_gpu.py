import math
import time
from array import array

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QSurfaceFormat
from PySide6.QtOpenGL import (QOpenGLWindow, QOpenGLShaderProgram, QOpenGLShader,
                              QOpenGLVertexArrayObject, QOpenGLFunctions_3_2_Core)

from modules.stress import write_json, parent_alive


VERTEX = """#version 150
uniform float elapsed;
uniform float aspect;
out vec3 normal;
out vec3 position;
out vec3 tint;
const vec2 corners[6] = vec2[6](vec2(-1,-1),vec2(1,-1),vec2(1,1),
                              vec2(-1,-1),vec2(1,1),vec2(-1,1));
void main() {
    int face = gl_VertexID / 6;
    vec2 uv = corners[gl_VertexID % 6] * 0.62;
    vec3 p, n;
    if (face < 2) { p=vec3(0.62,uv); n=vec3(1,0,0); }
    else if (face < 4) { p=vec3(uv.x,0.62,uv.y); n=vec3(0,1,0); }
    else { p=vec3(uv,0.62); n=vec3(0,0,1); }
    if (face % 2 == 1) { p=-p; n=-n; }
    float id = float(gl_InstanceID);
    float a = elapsed * 0.6 + id * 0.17;
    float b = elapsed * 0.4 + id * 0.31;
    mat3 ry=mat3(cos(a),0,sin(a), 0,1,0, -sin(a),0,cos(a));
    mat3 rx=mat3(1,0,0, 0,cos(b),sin(b), 0,-sin(b),cos(b));
    mat3 rotation=ry*rx;
    vec3 center=vec3((float(gl_InstanceID % 12)-5.5)*1.8,
                     (float(gl_InstanceID / 12)-3.0)*1.8,
                     -16.0+1.5*sin(id*0.2+elapsed*0.3));
    position=rotation*p+center;
    normal=rotation*n;
    tint=0.45+0.35*cos(vec3(0,2,4)+id*0.13);
    float near=0.1, far=100.0, f=1.73;
    gl_Position=vec4(position.x*f/aspect,position.y*f,
        -(far+near)/(far-near)*position.z-2.0*far*near/(far-near),-position.z);
}
"""
FRAGMENT = """#version 150
uniform float elapsed;
in vec3 normal;
in vec3 position;
in vec3 tint;
out vec4 color;
void main() {
    vec3 n=normalize(normal);
    vec3 light=normalize(vec3(4,7,-4)-position);
    float diffuse=max(dot(n,light),0.0);
    float spec=pow(max(dot(reflect(-light,n),normalize(-position)),0.0),32.0);
    vec3 p=position;
    float detail=0.0;
    for (int i=0; i<ITERATIONS; ++i) {
        p=sin(p.yzx*1.07+vec3(0.01*float(i),elapsed*0.03,0.3));
        detail+=dot(p,vec3(0.003));
    }
    color=vec4(tint*(0.2+0.8*diffuse)*(0.85+0.15*sin(detail))+vec3(spec*0.6),1);
}
"""


class FrameTiming:
    def __init__(self):
        self.bins = array("I", [0]) * 20001
        self.count = 0
        self.total = self.maximum = 0.0

    def add(self, milliseconds):
        if not math.isfinite(milliseconds) or milliseconds <= 0:
            return
        self.count += 1
        self.total += milliseconds
        self.maximum = max(self.maximum, milliseconds)
        self.bins[min(20000, math.ceil(milliseconds * 10))] += 1

    def summary(self):
        def percentile(fraction):
            target, count = math.ceil(self.count * fraction), 0
            for index, value in enumerate(self.bins):
                count += value
                if count >= target:
                    return index / 10
            return None
        return {"frame_samples": self.count, "fps": 1000 * self.count / self.total if self.total else None,
                "frametime_p95_ms": percentile(.95) if self.count else None,
                "frametime_p99_ms": percentile(.99) if self.count else None,
                "frametime_max_ms": self.maximum if self.count else None,
                "frametime_overflow": self.bins[-1],
                "frametime_method": "Intervalos entre frameSwapped, histograma de 0,1 ms; último balde >= 2000 ms. Inclui espera/pacing; não é tempo exclusivo da GPU."}


def run_gpu(folder, config):
    import faulthandler
    with (folder / "gpu-fault.log").open("wb") as fault_log:
        faulthandler.enable(file=fault_log)
        try:
            return render_gpu(folder, config)
        finally:
            faulthandler.disable()


def render_gpu(folder, config):
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 2)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSwapInterval(0)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QGuiApplication([])
    started = time.monotonic()
    timing = FrameTiming()
    resolution = config.get("resolution", "1280x720")
    profile = config.get("gpu_profile", "balanced")
    iterations = {"geometry": 16, "balanced": 128, "shader": 384}[profile]
    result = {"kind": "gpu", "state": "running", "checks": None, "errors": None, "frames": 0,
              "elapsed_s": 0, "started_monotonic": started, "reason": "Duração concluída",
              "options": {key: config.get(key) for key in ("kind", "duration_s", "intensity", "resolution", "gpu_profile")},
              "method": "OpenGL 3.2: 84 cubos instanciados, perspectiva, profundidade e iluminação. "
                        "Perfis variam o shader. Sem detector de artefatos ou teste integral de VRAM."}

    class Window(QOpenGLWindow):
        def initializeGL(self):
            try:
                self.functions = QOpenGLFunctions_3_2_Core()
                if not self.functions.initializeOpenGLFunctions():
                    raise RuntimeError("OpenGL 3.2 indisponível.")
                renderer = self.context().functions().glGetString(0x1F01)
                result["renderer"] = renderer.decode("utf-8", "replace") if isinstance(renderer, bytes) else str(renderer)
                if any(name in result["renderer"].lower() for name in ("llvmpipe", "softpipe", "software", "swiftshader", "microsoft basic")):
                    raise RuntimeError("Renderização por software detectada; não corresponde a um teste da GPU.")
                self.shader = QOpenGLShaderProgram(self)
                if not self.shader.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX):
                    raise RuntimeError(self.shader.log())
                if not self.shader.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT.replace("ITERATIONS", str(iterations))) or not self.shader.link():
                    raise RuntimeError(self.shader.log())
                self.time_uniform = self.shader.uniformLocation("elapsed")
                self.aspect_uniform = self.shader.uniformLocation("aspect")
                self.vao = QOpenGLVertexArrayObject(self)
                if not self.vao.create():
                    raise RuntimeError("Não foi possível preparar a geometria.")
                self.functions.glEnable(0x0B71)
                self.functions.glClearColor(0.035, 0.05, 0.09, 1.0)
                self.submit_total = 0.0
            except Exception as error:
                result.update(state="failed", reason=str(error))
                QTimer.singleShot(0, app.quit)

        def paintGL(self):
            if not hasattr(self, "vao") or result["state"] == "failed":
                return
            try:
                before = time.perf_counter()
                scale = self.devicePixelRatio()
                width, height = int(self.width()*scale), int(self.height()*scale)
                self.functions.glViewport(0, 0, width, height)
                result["render_resolution"] = [width, height]
                self.functions.glClear(0x00004000 | 0x00000100)
                self.shader.bind()
                self.vao.bind()
                self.functions.glUniform1f(self.time_uniform, time.monotonic()-started)
                self.functions.glUniform1f(self.aspect_uniform, width/max(1, height))
                self.functions.glDrawArraysInstanced(0x0004, 0, 36, 84)
                if self.functions.glGetError():
                    raise RuntimeError("OpenGL informou erro durante a carga.")
                self.vao.release()
                self.shader.release()
                self.submit_total += (time.perf_counter()-before)*1000
                result["frames"] += 1
                result["cpu_submit_mean_ms"] = self.submit_total/result["frames"]
            except Exception as error:
                result.update(state="failed", reason=f"Renderização interrompida: {error}")
                app.quit()

        def swapped(self):
            now = time.monotonic()
            if hasattr(self, "last_frame"):
                timing.add((now-self.last_frame)*1000)
            self.last_frame = now

        def closeEvent(self, event):
            if time.monotonic()-started < config["duration_s"]-.5 and result["state"] != "failed":
                result["reason"] = "Janela do teste fechada"
            app.quit()
            event.accept()

    window = Window()
    window.frameSwapped.connect(window.swapped)
    window.setTitle("SysPulse · cena 3D · fechar interrompe")
    width, height = map(int, resolution.split("x"))
    window.resize(width, height)
    window.show()
    render = QTimer()
    render.setInterval(max(1, int(40*(1-config["intensity"]/100))))
    render.timeout.connect(window.update)
    render.start()
    monitor = QTimer()

    def poll():
        result["elapsed_s"] = time.monotonic()-started
        result.update(timing.summary())
        fps = result.get("fps")
        window.setTitle(f"SysPulse · cena 3D · {fps:.1f} FPS · fechar interrompe" if fps else "SysPulse · preparando cena 3D")
        if (folder/"stop").exists() or not parent_alive(config):
            result["reason"] = "Parada solicitada ou aplicativo encerrado"
            app.quit()
        elif result["elapsed_s"] >= config["duration_s"]:
            app.quit()
        elif result["frames"] and time.monotonic()-getattr(window, "last_frame", started) > 3:
            result.update(state="stopped", reason="A janela deixou de renderizar. Mantenha o teste visível.")
            app.quit()
        elif result["elapsed_s"] > 10 and not result["frames"]:
            result.update(state="failed", reason="A janela não produziu quadros; confira OpenGL e o driver.")
            app.quit()
        write_json(folder/"progress.json", result)

    monitor.timeout.connect(poll)
    monitor.start(300)
    app.exec()
    monitor.stop()
    render.stop()
    if result["state"] not in ("failed", "stopped"):
        result["state"] = ("stopped" if time.monotonic()-started < config["duration_s"]-.5 else "completed") if result["frames"] else "failed"
        if not result["frames"]:
            result["reason"] = "Sem quadros válidos."
    result.update(timing.summary())
    result["elapsed_s"] = time.monotonic()-started
    result["ended_monotonic"] = time.monotonic()
    write_json(folder/"result.json", result)
    window.close()
    return 0 if result["state"] in ("completed", "stopped") else 1
