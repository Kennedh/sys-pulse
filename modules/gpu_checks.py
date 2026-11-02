import ctypes
import os
import struct
import time
from array import array

import psutil
from PySide6.QtGui import QImage
from PySide6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram, QOpenGLFramebufferObject

BLOCK_BYTES = 4 * 1024 ** 2
PATTERN_NAMES = ["Zeros", "Uns", "0xAA", "0x55", "Endereços", "Endereços invertidos"]
PATTERN_NAMES += [f"Bit {bit} ligado" for bit in range(32)]
PATTERN_NAMES += [f"Bit {bit} desligado" for bit in range(32)]

FULLSCREEN_VERTEX = """#version 150
void main() {
    vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);
    gl_Position=vec4(p*2.0-1.0,0,1);
}
"""
CANARY_FRAGMENT = """#version 150
uniform uint seed;
out vec4 color;
void main() {
    uvec2 p=uvec2(gl_FragCoord.xy);
    color=vec4(float((p.x+seed)&255u),float((p.y^seed)&255u),
               float((p.x^p.y^seed)&255u),255.0)/255.0;
}
"""
MEMORY_VERTEX = """#version 150
uniform int mode;
uniform uint base;
out uint value;
void main() {
    uint address=base+uint(gl_VertexID);
    if(mode==0) value=0u;
    else if(mode==1) value=0xffffffffu;
    else if(mode==2) value=0xaaaaaaaau;
    else if(mode==3) value=0x55555555u;
    else if(mode==4) value=address;
    else if(mode==5) value=~address;
    else if(mode<38) value=1u<<uint(mode-6);
    else value=~(1u<<uint(mode-38));
    gl_Position=vec4(0,0,0,1);
}
"""


def pattern_bytes(words, mode, base=0):
    if not 0 <= words <= BLOCK_BYTES // 4 or not 0 <= mode < len(PATTERN_NAMES):
        raise ValueError("Padrão ou tamanho de bloco inválido.")
    if mode in (4, 5):
        start = base if mode == 4 else 0xffffffff-base
        values = range(start, start+words) if mode == 4 else range(start, start-words, -1)
        return array("I", values).tobytes()
    value = (0, 0xffffffff, 0xaaaaaaaa, 0x55555555)[mode] if mode < 4 else (
        1 << (mode-6) if mode < 38 else 0xffffffff ^ (1 << (mode-38)))
    return struct.pack("=I", value)*words


def word_difference(expected, actual, base_bytes=0, limit=16):
    if len(expected) != len(actual) or len(actual) % 4:
        raise ValueError("Leitura gráfica com tamanho inesperado.")
    if expected == actual:
        return {"words": 0, "bits": 0, "examples": []}
    count = bits = 0
    examples = []
    for index, (left, right) in enumerate(zip(memoryview(expected).cast("I"), memoryview(actual).cast("I"))):
        if left != right:
            count += 1
            bits += (left ^ right).bit_count()
            if len(examples) < limit:
                examples.append({"byte_offset": base_bytes+index*4, "expected": f"{left:08x}", "actual": f"{right:08x}"})
    return {"words": count, "bits": bits, "examples": examples}


def image_bytes(image):
    if image.isNull():
        raise RuntimeError("Não foi possível ler a imagem da GPU.")
    converted = image.convertToFormat(QImage.Format_RGBA8888)
    return converted, bytes(converted.constBits())


def canary_bytes(width, height, seed):
    data = bytearray(width*height*4)
    for y in range(height):
        for x in range(width):
            offset = (y*width+x)*4
            data[offset:offset+4] = bytes(((x+seed)&255, (y^seed)&255, (x^y^seed)&255, 255))
    return bytes(data)


class NativeGL:
    def __init__(self, context):
        function = ctypes.WINFUNCTYPE if os.name == "nt" else ctypes.CFUNCTYPE
        declarations = {
            "glGenBuffers": (None, ctypes.c_int, ctypes.POINTER(ctypes.c_uint)),
            "glDeleteBuffers": (None, ctypes.c_int, ctypes.POINTER(ctypes.c_uint)),
            "glBufferData": (None, ctypes.c_uint, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint),
            "glGetBufferSubData": (None, ctypes.c_uint, ctypes.c_ssize_t, ctypes.c_ssize_t, ctypes.c_void_p),
            "glGetIntegerv": (None, ctypes.c_uint, ctypes.POINTER(ctypes.c_int)),
            "glTransformFeedbackVaryings": (None, ctypes.c_uint, ctypes.c_int, ctypes.POINTER(ctypes.c_char_p), ctypes.c_uint),
        }
        for name, signature in declarations.items():
            address = context.getProcAddress(name.encode("ascii"))
            if not address:
                raise RuntimeError("Função gráfica indisponível: " + name)
            setattr(self, name, function(*signature)(address))


def available_memory(context, functions, native):
    if context.hasExtension(b"GL_NVX_gpu_memory_info"):
        value = ctypes.c_int()
        native.glGetIntegerv(0x9049, ctypes.byref(value))
        if not functions.glGetError() and value.value > 0:
            return value.value*1024, "GL_NVX_gpu_memory_info"
    if context.hasExtension(b"GL_ATI_meminfo"):
        values = (ctypes.c_int*4)()
        native.glGetIntegerv(0x87FB, values)
        if not functions.glGetError() and values[0] > 0:
            return values[0]*1024, "GL_ATI_meminfo"
    return None, "Driver não informou memória gráfica livre"


def memory_budget(requested_mb, free_bytes, available_ram):
    reserve = max(512*1024**2, int((free_bytes or 0)*.15))
    limit = max(0, free_bytes-reserve) if free_bytes is not None else min(512*1024**2, int(available_ram*.1))
    requested = requested_mb*1024**2 if requested_mb else limit
    effective = min(requested, limit, 16*1024**3)
    return effective//BLOCK_BYTES*BLOCK_BYTES, reserve


class MemoryCheck:
    def __init__(self, context, functions, requested_mb):
        self.context, self.gl = context, functions
        self.native = NativeGL(context)
        free, source = available_memory(context, functions, self.native)
        self.target, self.reserve = memory_budget(requested_mb, free, psutil.virtual_memory().available)
        self.stats = {"requested_mb": requested_mb, "target_bytes": self.target, "allocated_bytes": 0,
                      "unique_checked_bytes": 0, "checked_bytes": 0, "checks": 0, "failed_checks": 0,
                      "mismatched_words": 0, "mismatched_bits": 0, "passes": 0, "cycles": 0,
                      "pattern_count": len(PATTERN_NAMES), "pattern": PATTERN_NAMES[0], "phase": "Alocando",
                      "free_source": source, "initial_free_bytes": free, "reserve_bytes": self.reserve,
                      "bytes_covered": False, "coverage_complete": False, "examples": [],
                      "method": "Buffers OpenGL escritos pela GPU via transform feedback e lidos integralmente para comparação na CPU. "
                                "70 padrões: constantes, endereços, inversos e bits móveis. Endereços são lógicos; o driver pode paginar ou usar RAM compartilhada. Não verifica VRAM física integral."}
        if self.target < BLOCK_BYTES:
            raise RuntimeError("Memória gráfica disponível insuficiente após reservar espaço para o sistema.")
        self.buffers = []
        self.host = (ctypes.c_ubyte*BLOCK_BYTES)()
        self.cursor = self.mode = 0
        self.program = QOpenGLShaderProgram()
        if not self.program.addShaderFromSourceCode(QOpenGLShader.Vertex, MEMORY_VERTEX):
            raise RuntimeError(self.program.log())
        names = (ctypes.c_char_p*1)(b"value")
        self.native.glTransformFeedbackVaryings(self.program.programId(), 1, names, 0x8C8C)
        if not self.program.link():
            raise RuntimeError(self.program.log())
        self.mode_location = self.program.uniformLocation("mode")
        self.base_location = self.program.uniformLocation("base")

    def step(self):
        if psutil.virtual_memory().available < 256*1024**2:
            raise RuntimeError("Pouca RAM livre; verificação gráfica interrompida com cobertura parcial.")
        if self.stats["phase"] == "Alocando":
            free, _ = available_memory(self.context, self.gl, self.native)
            if (len(self.buffers)*BLOCK_BYTES >= self.target or
                    free is not None and free < self.reserve+BLOCK_BYTES):
                if not self.buffers:
                    raise RuntimeError("O driver não disponibilizou memória suficiente para verificar.")
                self.stats["phase"] = "Escrevendo"
                return
            handle = ctypes.c_uint()
            self.native.glGenBuffers(1, ctypes.byref(handle))
            self.gl.glBindBuffer(0x8892, handle.value)
            self.native.glBufferData(0x8892, BLOCK_BYTES, None, 0x88E6)
            if self.gl.glGetError():
                self.native.glDeleteBuffers(1, ctypes.byref(handle))
                raise RuntimeError("O driver recusou a alocação gráfica. A cobertura ficou incompleta.")
            self.buffers.append(handle.value)
            self.stats["allocated_bytes"] = len(self.buffers)*BLOCK_BYTES
            return
        handle = self.buffers[self.cursor]
        base = self.cursor*(BLOCK_BYTES//4)
        if self.stats["phase"] == "Escrevendo":
            self.program.bind()
            self.gl.glUniform1i(self.mode_location, self.mode)
            self.gl.glUniform1ui(self.base_location, base)
            self.gl.glBindBufferBase(0x8C8E, 0, handle)
            self.gl.glEnable(0x8C89)
            self.gl.glBeginTransformFeedback(0x0000)
            self.gl.glDrawArrays(0x0000, 0, BLOCK_BYTES//4)
            self.gl.glEndTransformFeedback()
            self.gl.glDisable(0x8C89)
            self.gl.glBindBufferBase(0x8C8E, 0, 0)
            self.program.release()
        else:
            self.gl.glBindBuffer(0x8892, handle)
            self.native.glGetBufferSubData(0x8892, 0, BLOCK_BYTES, self.host)
            if self.gl.glGetError():
                raise RuntimeError("O driver não concluiu a leitura gráfica; resultado incompleto.")
            expected = pattern_bytes(BLOCK_BYTES//4, self.mode, base)
            difference = word_difference(expected, bytes(self.host), base*4)
            self.stats["checks"] += 1
            self.stats["checked_bytes"] += BLOCK_BYTES
            if self.mode == 0 and self.stats["passes"] == 0:
                self.stats["unique_checked_bytes"] += BLOCK_BYTES
            if difference["words"]:
                self.stats.setdefault("first_error_monotonic", time.monotonic())
                self.stats["failed_checks"] += 1
                self.stats["mismatched_words"] += difference["words"]
                self.stats["mismatched_bits"] += difference["bits"]
                self.stats["examples"] = difference["examples"]
        if self.gl.glGetError():
            raise RuntimeError("Erro OpenGL durante a verificação; resultado incompleto.")
        self.cursor += 1
        if self.cursor == len(self.buffers):
            self.cursor = 0
            if self.stats["phase"] == "Escrevendo":
                self.stats["phase"] = "Verificando"
            else:
                self.stats["passes"] += 1
                self.stats["cycles"] = self.stats["passes"]//len(PATTERN_NAMES)
                self.stats["bytes_covered"] = self.stats["unique_checked_bytes"] == self.target
                self.stats["coverage_complete"] = self.stats["bytes_covered"] and self.stats["cycles"] > 0
                self.mode = (self.mode+1)%len(PATTERN_NAMES)
                self.stats["pattern"] = PATTERN_NAMES[self.mode]
                self.stats["phase"] = "Escrevendo"

    def close(self):
        if self.buffers:
            handles = (ctypes.c_uint*len(self.buffers))(*self.buffers)
            self.native.glDeleteBuffers(len(self.buffers), handles)
            self.buffers.clear()
        self.program.removeAllShaders()


class ArtifactCheck:
    def __init__(self, functions):
        self.gl = functions
        self.buffer = QOpenGLFramebufferObject(128, 128)
        if not self.buffer.isValid():
            raise RuntimeError("Não foi possível preparar o padrão de verificação gráfica.")
        self.program = QOpenGLShaderProgram()
        if (not self.program.addShaderFromSourceCode(QOpenGLShader.Vertex, FULLSCREEN_VERTEX) or
                not self.program.addShaderFromSourceCode(QOpenGLShader.Fragment, CANARY_FRAGMENT) or not self.program.link()):
            raise RuntimeError(self.program.log())
        self.seed_location = self.program.uniformLocation("seed")
        self.stats = {"checks": 0, "scene_pairs": 0, "known_patterns": 0, "failed_checks": 0,
                      "mismatched_pixels": 0, "examples": [],
                      "method": "Compara duas renderizações 3D com o mesmo tempo e um padrão inteiro conhecido de 128×128. "
                                "Divergências são evidência no caminho gráfico; não identificam a peça. Artefatos iguais nas duas imagens e falhas fora dos padrões podem passar."}

    def known_pattern(self):
        seed = (self.stats["known_patterns"]*37)&255
        self.buffer.bind()
        self.gl.glViewport(0, 0, 128, 128)
        self.gl.glDisable(0x0B71)
        self.program.bind()
        self.gl.glUniform1ui(self.seed_location, seed)
        self.gl.glDrawArrays(0x0004, 0, 3)
        self.program.release()
        observed = self.buffer.toImage(False)
        _, actual = image_bytes(observed)
        if self.gl.glGetError():
            raise RuntimeError("Não foi possível concluir a leitura do padrão gráfico.")
        expected = canary_bytes(128, 128, seed)
        difference = word_difference(expected, actual)
        self.stats["checks"] += 1
        self.stats["known_patterns"] += 1
        self._record(difference)
        if difference["words"]:
            self.stats["pattern_seed"] = seed
            self.failed_image = observed
            self.failed_expected = QImage(expected, 128, 128, 128*4, QImage.Format_RGBA8888).copy()
        return difference

    def compare_scene(self, first, second):
        _, expected = image_bytes(first)
        _, actual = image_bytes(second)
        difference = word_difference(expected, actual)
        self.stats["checks"] += 1
        self.stats["scene_pairs"] += 1
        self._record(difference)
        return difference

    def _record(self, difference):
        if difference["words"]:
            self.stats.setdefault("first_error_monotonic", time.monotonic())
            self.stats["failed_checks"] += 1
            self.stats["mismatched_pixels"] += difference["words"]
            self.stats["examples"] = difference["examples"]
