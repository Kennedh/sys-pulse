import json
import platform
import subprocess

import psutil


def executar_powershell(comando):
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; " + comando],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8,
            creationflags=0x08000000 if platform.system() == "Windows" else 0)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def get_hardware_info():
    info = {}
    if platform.system() == "Windows":
        raw = executar_powershell("$cpu = Get-CimInstance Win32_Processor; "
            "$board = Get-CimInstance Win32_BaseBoard; "
            "$gpu = Get-CimInstance Win32_VideoController; "
            "$bios = Get-CimInstance Win32_BIOS; "
            "@{cpu=($cpu.Name -join ', '); motherboard=($board.Manufacturer + ' ' + $board.Product); "
            "gpu=($gpu.Name -join ', '); bios=($bios.SMBIOSBIOSVersion -join ', ')} | ConvertTo-Json -Compress")
        if raw:
            try:
                info = json.loads(raw)
            except (ValueError, TypeError):
                pass
    memory = psutil.virtual_memory()
    freq = psutil.cpu_freq()
    return ("INFORMAÇÕES DE HARDWARE\n\n"
            f"Sistema: {platform.system()} {platform.release()}\n"
            f"Placa-mãe: {info.get('motherboard', 'N/D')}\n"
            f"BIOS: {info.get('bios', 'N/D')}\n"
            f"Processador: {info.get('cpu') or platform.processor() or 'N/D'}\n"
            f"Núcleos físicos: {psutil.cpu_count(logical=False)} | Lógicos: {psutil.cpu_count()}\n"
            f"Frequência reportada pelo SO: {round(freq.current) if freq else 'N/D'} MHz\n"
            f"RAM total: {memory.total / 1024 ** 3:.1f} GiB\n"
            f"GPU(s): {info.get('gpu', 'Consulte os sensores no diagnóstico')}\n\n"
            "A disponibilidade das leituras depende do hardware, driver e permissões.\n"
            "Temperaturas e GPU AMD/Intel: integração opcional com LibreHardwareMonitor.\n")
