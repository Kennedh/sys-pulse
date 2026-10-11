import ctypes
import math
import os
import re


def gpu_process_usage(items):
    """Busiest engine per PID, never sum independent engines into >100%."""
    result = {}
    for name, value in items:
        match = re.search(r"(?:^|_)pid_(\d+)_", name or "")
        if match and math.isfinite(value) and value >= 0:
            pid = int(match.group(1))
            result[pid] = max(result.get(pid, 0), min(100.0, value))
    return result


class CounterValue(ctypes.Structure):
    _fields_ = [("status", ctypes.c_uint32), ("value", ctypes.c_double)]


class CounterItem(ctypes.Structure):
    _fields_ = [("name", ctypes.c_wchar_p), ("formatted", CounterValue)]


class WindowsCounters:
    def __init__(self, gpu_only=False):
        self.query = ctypes.c_void_p()
        self.handles = {}
        self.pdh = None
        if os.name != "nt":
            return
        try:
            self.pdh = ctypes.WinDLL("pdh")
            handle = ctypes.c_void_p
            size = ctypes.POINTER(ctypes.c_uint32)
            self.pdh.PdhOpenQueryW.argtypes = [ctypes.c_wchar_p, ctypes.c_size_t, ctypes.POINTER(handle)]
            self.pdh.PdhAddEnglishCounterW.argtypes = [handle, ctypes.c_wchar_p, ctypes.c_size_t, ctypes.POINTER(handle)]
            self.pdh.PdhCollectQueryData.argtypes = [handle]
            self.pdh.PdhGetFormattedCounterValue.argtypes = [handle, ctypes.c_uint32, handle, ctypes.POINTER(CounterValue)]
            self.pdh.PdhGetFormattedCounterArrayW.argtypes = [handle, ctypes.c_uint32, size, size, handle]
            self.pdh.PdhCloseQuery.argtypes = [handle]
            if self.pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.query)):
                self.query = handle()
                return
            if gpu_only:
                self._add("gpu_processes", r"\GPU Engine(*)\Utilization Percentage")
            else:
                self._add("page_reads_s", r"\Memory\Page Reads/sec")
                self._add("idle", r"\PhysicalDisk(*)\% Idle Time")
                self._add("queue", r"\PhysicalDisk(*)\Current Disk Queue Length")
            self.pdh.PdhCollectQueryData(self.query)
        except (OSError, AttributeError):
            self.close()

    def _add(self, key, path):
        handle = ctypes.c_void_p()
        if not self.pdh.PdhAddEnglishCounterW(self.query, path, 0, ctypes.byref(handle)):
            self.handles[key] = handle

    def _array(self, handle):
        size, count = ctypes.c_uint32(), ctypes.c_uint32()
        self.pdh.PdhGetFormattedCounterArrayW(handle, 0x200 | 0x8000, ctypes.byref(size), ctypes.byref(count), None)
        if not size.value or size.value > 4 * 1024 * 1024:
            return []
        buffer = ctypes.create_string_buffer(size.value)
        code = self.pdh.PdhGetFormattedCounterArrayW(handle, 0x200 | 0x8000, ctypes.byref(size), ctypes.byref(count), buffer)
        if code:
            return []
        items = ctypes.cast(buffer, ctypes.POINTER(CounterItem))
        return [(items[i].name, items[i].formatted.value) for i in range(count.value)
                if items[i].formatted.status in (0, 1) and math.isfinite(items[i].formatted.value)]

    def sample(self):
        result = {"disks": {}}
        if not self.query or self.pdh.PdhCollectQueryData(self.query):
            return result
        for key, handle in self.handles.items():
            if key == "gpu_processes":
                result[key] = gpu_process_usage(self._array(handle))
                continue
            if key == "page_reads_s":
                value = CounterValue()
                code = self.pdh.PdhGetFormattedCounterValue(handle, 0x200 | 0x8000, None, ctypes.byref(value))
                if not code and value.status in (0, 1) and math.isfinite(value.value):
                    result[key] = max(0, value.value)
                continue
            for name, value in self._array(handle):
                number = (name or "").split(" ")[0]
                if not number.isdigit():
                    continue
                row = result["disks"].setdefault(number, {})
                if key == "idle":
                    row["active_percent"] = min(100, max(0, 100 - value))
                else:
                    row["queue"] = max(0, value)
        return result

    def close(self):
        if self.pdh and self.query:
            self.pdh.PdhCloseQuery(self.query)
        self.query = ctypes.c_void_p()
