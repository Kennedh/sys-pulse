import ctypes
import os

from PySide6.QtCore import QAbstractNativeEventFilter


class GlobalHotkey(QAbstractNativeEventFilter):
    identifier = 0x5350

    def __init__(self, application, callback):
        super().__init__()
        self.application = application
        self.callback = callback
        self.registered = False
        self.error = "Atalho global disponível apenas no Windows; use o botão ou o atalho com a janela em foco."
        if os.name == "nt":
            from ctypes import wintypes
            self.user32 = ctypes.WinDLL("user32", use_last_error=True)
            self.user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
            self.user32.RegisterHotKey.restype = wintypes.BOOL
            self.user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
            self.user32.UnregisterHotKey.restype = wintypes.BOOL
            self.registered = bool(self.user32.RegisterHotKey(None, self.identifier, 0x4003, 0x77))
            if self.registered:
                application.installNativeEventFilter(self)
                self.error = ""
            else:
                self.error = f"Atalho global indisponível (Windows {ctypes.get_last_error()}); use o botão ou libere Ctrl+Alt+F8."

    def nativeEventFilter(self, event_type, message):
        if os.name == "nt" and bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam == self.identifier:
                self.callback()
                return True, 0
        return False, 0

    def close(self):
        if self.registered:
            self.user32.UnregisterHotKey(None, self.identifier)
            self.application.removeNativeEventFilter(self)
            self.registered = False
