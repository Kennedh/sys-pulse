import platform
import re
import socket
import subprocess
import time

import psutil


class NetworkMonitor:
    def __init__(self):
        self.last_io = psutil.net_io_counters()
        self.start_io = self.last_io
        self.last_time = time.monotonic()

    def get_network_speed(self):
        current = psutil.net_io_counters()
        now = time.monotonic()
        elapsed = max(now - self.last_time, 0.001)
        previous = self.last_io or current
        initial = self.start_io or current
        self.last_io, self.last_time = current, now
        if current is None:
            return {}
        return {
            "download_mbs": max(0, current.bytes_recv - previous.bytes_recv) / elapsed / 1024 ** 2,
            "upload_mbs": max(0, current.bytes_sent - previous.bytes_sent) / elapsed / 1024 ** 2,
            "total_down_mb": max(0, current.bytes_recv - initial.bytes_recv) / 1024 ** 2,
            "total_up_mb": max(0, current.bytes_sent - initial.bytes_sent) / 1024 ** 2,
        }

    @staticmethod
    def get_ping():
        windows = platform.system() == "Windows"
        command = ["ping", "-n", "1", "-w", "500", "8.8.8.8"] if windows else ["ping", "-n", "-c", "1", "-W", "1", "8.8.8.8"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, errors="replace",
                                    timeout=1.5, creationflags=0x08000000 if windows else 0)
            match = re.search(r"(?:time|tempo)\s*([=<])\s*([\d.,]+)\s*ms", result.stdout, re.I)
            if result.returncode == 0 and match:
                return {"ms": float(match[2].replace(",", ".")), "less_than": match[1] == "<"}
        except (OSError, subprocess.SubprocessError):
            pass
        return None

    @staticmethod
    def get_infrastructure_info():
        addresses = psutil.net_if_addrs()
        rows = []
        for name, stats in psutil.net_if_stats().items():
            if not stats.isup:
                continue
            for address in addresses.get(name, []):
                if address.family == socket.AF_INET and not address.address.startswith("127."):
                    rows.append({"name": name, "ip": address.address, "speed_mbps": stats.speed})
        return rows
