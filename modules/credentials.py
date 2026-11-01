import ctypes
import os

from modules.ai_providers import PROVIDERS


class Credential(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint32), ("kind", ctypes.c_uint32), ("target", ctypes.c_wchar_p),
                ("comment", ctypes.c_wchar_p), ("written", ctypes.c_uint32 * 2),
                ("size", ctypes.c_uint32), ("blob", ctypes.c_void_p), ("persist", ctypes.c_uint32),
                ("attributes_count", ctypes.c_uint32), ("attributes", ctypes.c_void_p),
                ("alias", ctypes.c_wchar_p), ("user", ctypes.c_wchar_p)]


class CredentialStore:
    def __init__(self):
        self.api = None
        if os.name == "nt":
            self.api = ctypes.WinDLL("advapi32", use_last_error=True)
            self.api.CredReadW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                           ctypes.POINTER(ctypes.c_void_p)]
            self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), ctypes.c_uint32]
            self.api.CredDeleteW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
            self.api.CredFree.argtypes = [ctypes.c_void_p]

    def target(self, provider):
        if provider not in PROVIDERS:
            raise ValueError("Serviço inválido.")
        return "SysPulse/AI/" + provider

    def read(self, provider):
        if self.api is None:
            return ""
        pointer = ctypes.c_void_p()
        if not self.api.CredReadW(self.target(provider), 1, 0, ctypes.byref(pointer)):
            return ""
        try:
            value = ctypes.cast(pointer, ctypes.POINTER(Credential)).contents
            return ctypes.string_at(value.blob, value.size).decode("utf-8") if 0 < value.size <= 2048 else ""
        finally:
            self.api.CredFree(pointer)

    def write(self, provider, secret):
        if self.api is None:
            raise ValueError("Cofre disponível apenas no Windows.")
        raw = secret.encode("utf-8")
        if not 0 < len(raw) <= 2048:
            raise ValueError("A chave precisa ter entre 1 e 2048 bytes.")
        buffer = ctypes.create_string_buffer(raw)
        value = Credential()
        value.kind, value.target, value.persist = 1, self.target(provider), 2
        value.user, value.size = "SysPulse", len(raw)
        value.blob = ctypes.cast(buffer, ctypes.c_void_p)
        if not self.api.CredWriteW(ctypes.byref(value), 0):
            raise OSError("Não foi possível salvar a chave no cofre do Windows.")

    def delete(self, provider):
        if self.api:
            self.api.CredDeleteW(self.target(provider), 1, 0)
