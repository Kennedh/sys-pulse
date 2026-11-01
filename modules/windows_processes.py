import ctypes
import os


class UnicodeString(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint16), ("maximum", ctypes.c_uint16), ("buffer", ctypes.c_void_p)]


class ProcessTimes(ctypes.Structure):
    _fields_ = [("next", ctypes.c_uint32), ("threads", ctypes.c_uint32),
                ("reserved", ctypes.c_byte * 24), ("created", ctypes.c_int64),
                ("user", ctypes.c_int64), ("kernel", ctypes.c_int64),
                ("name", UnicodeString), ("priority", ctypes.c_int32), ("pid", ctypes.c_void_p),
                ("parent", ctypes.c_void_p), ("handles", ctypes.c_uint32), ("session", ctypes.c_uint32),
                ("key", ctypes.c_void_p), ("peak_virtual", ctypes.c_size_t), ("virtual", ctypes.c_size_t),
                ("faults", ctypes.c_uint32), ("peak_working_set", ctypes.c_size_t),
                ("working_set", ctypes.c_size_t), ("peak_paged", ctypes.c_size_t), ("paged", ctypes.c_size_t),
                ("peak_nonpaged", ctypes.c_size_t), ("nonpaged", ctypes.c_size_t),
                ("pagefile", ctypes.c_size_t), ("peak_pagefile", ctypes.c_size_t), ("private", ctypes.c_size_t),
                ("read_count", ctypes.c_int64), ("write_count", ctypes.c_int64), ("other_count", ctypes.c_int64),
                ("read_bytes", ctypes.c_int64), ("write_bytes", ctypes.c_int64), ("other_bytes", ctypes.c_int64)]


def decode_process_times(buffer, used):
    result, offset = {}, 0
    size = ctypes.sizeof(ProcessTimes)
    while offset + size <= used:
        row = ProcessTimes.from_buffer(buffer, offset)
        pid = row.pid or 0
        if pid > 0 and row.created > 0 and row.user >= 0 and row.kernel >= 0:
            result[pid] = (row.created / 10_000_000 - 11_644_473_600,
                           (row.user + row.kernel) / 10_000_000, row.working_set,
                           row.read_bytes, row.write_bytes, row.faults, row.threads)
        step = row.next
        if not step:
            return result
        if step < size or offset + step > used:
            return None
        offset += step
    return None


class WindowsProcessTimes:
    def __init__(self):
        self.query = None
        self.size = 1024 * 1024
        if os.name == "nt" and ctypes.sizeof(ctypes.c_void_p) == 8:
            try:
                self.query = ctypes.WinDLL("ntdll").NtQuerySystemInformation
                self.query.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                                       ctypes.POINTER(ctypes.c_uint32)]
                self.query.restype = ctypes.c_long
            except (OSError, AttributeError):
                pass

    def sample(self):
        if self.query is None:
            return None
        for _ in range(5):
            buffer = ctypes.create_string_buffer(self.size)
            needed = ctypes.c_uint32()
            status = self.query(5, buffer, self.size, ctypes.byref(needed)) & 0xffffffff
            if status == 0:
                return decode_process_times(buffer, min(needed.value or self.size, self.size))
            if status != 0xc0000004 or needed.value > 64 * 1024 ** 2:
                return None
            self.size = max(self.size * 2, needed.value + 65536)
        return None
