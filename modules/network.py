import platform
import ipaddress
import statistics
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
    def get_ping(host='8.8.8.8'):
        host = validate_host(host)
        windows = platform.system() == "Windows"
        command = ["ping", "-n", "1", "-w", "500", host] if windows else ["ping", "-n", "-c", "1", "-W", "1000" if platform.system() == "Darwin" else "1", host]
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
                    rows.append({"name": name, "ip": address.address, "speed_mbps": stats.speed,
                                 "netmask": address.netmask, "mtu": stats.mtu})
        return rows


def validate_host(value):
    value = str(value).strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        if (len(value) <= 253 and value and not value.startswith("-") and
                all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", part)
                    for part in value.rstrip(".").split("."))):
            return value
    raise ValueError("Informe somente um IP ou nome de servidor, sem endereço web ou opções.")


def ping_statistics(history):
    values = [row["ms"] for row in history if row.get("ms") is not None]
    differences = [abs(b - a) for a, b in zip(values, values[1:])]
    return {"attempts": len(history), "replies": len(values), "timeouts": len(history) - len(values),
            "mean_ms": statistics.mean(values) if values else None,
            "max_ms": max(values) if values else None,
            "variation_ms": statistics.mean(differences) if differences else None}
