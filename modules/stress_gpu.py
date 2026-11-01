import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QSurfaceFormat
from PySide6.QtOpenGL import QOpenGLWindow, QOpenGLShaderProgram, QOpenGLShader, QOpenGLVertexArrayObject

from modules.stress import write_json, parent_alive


VERTEX = """#version 150
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""
FRAGMENT = """#version 150
const float phase = 0.7;
out vec4 color;
void main() {
    vec2 p = gl_FragCoord.xy / vec2(960.0, 540.0) * 3.0 - vec2(2.1, 1.5);
    vec2 z = p;
    float sum = 0.0;
    for (int i = 0; i < 192; ++i) {
        z = vec2(z.x*z.x-z.y*z.y, 2.0*z.x*z.y) + p + 0.0001*sin(phase);
        if (dot(z,z) > 8.0) z = p * 0.3;
        sum += sin(z.x + z.y) * 0.005;
    }
    color = vec4(0.4+0.3*sin(sum+phase),0.3+0.3*cos(sum),0.65,1.0);
}
"""


def run_gpu(folder, config):
    import faulthandler
    faulthandler.enable()
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 2)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setSwapInterval(0)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QGuiApplication([])
    started = time.monotonic()
    result = {"kind": "gpu", "state": "running", "checks": None, "errors": None, "frames": 0,
              "elapsed_s": 0, "started_monotonic": started, "reason": "Duração concluída",
              "options": {key: config[key] for key in ("kind", "duration_s", "intensity")},
              "method": "Carga gráfica GLSL/OpenGL 3.2, 960×540. Sem detector de artefatos ou teste integral de VRAM."}

    class Window(QOpenGLWindow):
        def initializeGL(self):
            try:
                self.functions = self.context().functions()
                renderer = self.functions.glGetString(0x1F01)
                result["renderer"] = renderer.decode("utf-8", "replace") if isinstance(renderer, bytes) else str(renderer)
                if any(name in result["renderer"].lower() for name in ("llvmpipe", "softpipe", "software", "swiftshader", "microsoft basic")):
                    raise RuntimeError("Renderização por software detectada; não corresponde a um teste da GPU.")
                self.shader = QOpenGLShaderProgram(self)
                if not self.shader.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX):
                    raise RuntimeError(self.shader.log())
                if not self.shader.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT) or not self.shader.link():
                    raise RuntimeError(self.shader.log())
                self.vao = QOpenGLVertexArrayObject(self)
                if not self.vao.create():
                    raise RuntimeError("Não foi possível preparar a geometria.")
            except Exception as error:
                result.update(state="failed", reason=str(error))
                QTimer.singleShot(0, app.quit)

        def paintGL(self):
            if not hasattr(self, "vao") or result["state"] == "failed":
                return
            try:
                self.functions.glViewport(0, 0, self.width(), self.height())
                self.shader.bind()
                self.vao.bind()
                self.functions.glDrawArrays(0x0004, 0, 3)
                self.functions.glFinish()
                if self.functions.glGetError():
                    result.update(state="failed", reason="OpenGL informou erro durante a carga.")
                    app.quit()
                self.vao.release()
                self.shader.release()
                result["frames"] += 1
                self.last_frame = time.monotonic()
            except Exception as error:
                result.update(state="failed", reason=f"Renderização interrompida: {error}")
                app.quit()

        def closeEvent(self, event):
            if time.monotonic() - started < config["duration_s"] - .5 and result["state"] != "failed":
                result["reason"] = "Janela do teste fechada"
            app.quit()
            event.accept()

    window = Window()
    window.setTitle("SysPulse · carga GPU · fechar interrompe o teste")
    window.resize(960, 540)
    window.show()
    render = QTimer()
    render.setInterval(max(1, int(40 * (1 - config["intensity"] / 100))))
    render.timeout.connect(window.update)
    render.start()
    monitor = QTimer()

    def poll():
        result["elapsed_s"] = time.monotonic() - started
        window.setTitle(f"SysPulse ? carga GPU ? {result['frames']} quadros ? fechar interrompe")
        if (folder / "stop").exists() or not parent_alive(config):
            result["reason"] = "Parada solicitada ou aplicativo encerrado"
            app.quit()
        elif result["elapsed_s"] >= config["duration_s"]:
            app.quit()
        elif result["frames"] and time.monotonic() - getattr(window, "last_frame", started) > 3:
            result.update(state="stopped", reason="A janela deixou de renderizar. Mantenha o teste visível.")
            app.quit()
        elif result["elapsed_s"] > 10 and not result["frames"]:
            result.update(state="failed", reason="A janela não produziu quadros; confira OpenGL e o driver.")
            app.quit()
        write_json(folder / "progress.json", result)

    monitor.timeout.connect(poll)
    monitor.start(300)
    app.exec()
    monitor.stop()
    render.stop()
    if result["state"] not in ("failed", "stopped"):
        result["state"] = ("stopped" if time.monotonic() - started < config["duration_s"] - .5 else "completed") if result["frames"] else "failed"
        if not result["frames"]:
            result["reason"] = "Sem quadros válidos."
    result["elapsed_s"] = time.monotonic() - started
    result["ended_monotonic"] = time.monotonic()
    write_json(folder / "result.json", result)
    window.close()
    return 0 if result["state"] in ("completed", "stopped") else 1
