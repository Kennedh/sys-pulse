import threading

from PySide6.QtCore import QObject, Signal


class ActivityState(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self.capture = None
        self.inference = False
        self.maintenance = None

    def begin_capture(self, owner):
        with self._lock:
            if self.capture or self.inference or self.maintenance:
                raise RuntimeError("Aguarde a captura, a análise ou a preparação dos modelos terminar.")
            self.capture = owner
        self.changed.emit()

    def end_capture(self, owner):
        with self._lock:
            if self.capture != owner:
                return
            self.capture = None
        self.changed.emit()

    def begin_inference(self):
        with self._lock:
            if self.capture or self.inference or self.maintenance:
                raise RuntimeError("A IA fica disponível depois da captura e da preparação dos modelos.")
            self.inference = True
        self.changed.emit()

    def end_inference(self):
        with self._lock:
            self.inference = False
        self.changed.emit()

    @property
    def busy(self):
        return bool(self.capture or self.inference or self.maintenance)

    def begin_maintenance(self, owner):
        with self._lock:
            if self.capture or self.inference or self.maintenance:
                raise RuntimeError("Aguarde a captura, a análise ou a preparação dos modelos terminar.")
            self.maintenance = owner
        self.changed.emit()

    def end_maintenance(self, owner):
        with self._lock:
            if self.maintenance != owner:
                return
            self.maintenance = None
        self.changed.emit()
