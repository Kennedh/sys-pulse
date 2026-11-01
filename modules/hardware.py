import json
import platform
import subprocess

import psutil


def executar_powershell(comando):
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; " + comando],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=18,
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
            "$ram = Get-CimInstance Win32_PhysicalMemory; "
            "$drives = Get-CimInstance Win32_DiskDrive; "
            "$power = powercfg /getactivescheme; "
            "@{cpu=($cpu.Name -join ', '); motherboard=($board.Manufacturer + ' ' + $board.Product); "
            "gpu=($gpu.Name -join ', '); bios=($bios.SMBIOSBIOSVersion -join ', '); "
            "ram=@($ram | Select-Object BankLabel,Capacity,ConfiguredClockSpeed,PartNumber); "
            "drivers=($gpu.DriverVersion -join ', '); refresh=($gpu.CurrentRefreshRate -join ', '); "
            "disks=@($drives | Select-Object Model,Size,InterfaceType); power=($power -join ' ')} | ConvertTo-Json -Depth 4 -Compress")
        if raw:
            try:
                info = json.loads(raw)
            except (ValueError, TypeError):
                pass
    memory = psutil.virtual_memory()
    try:
        freq = psutil.cpu_freq()
    except (OSError, NotImplementedError):
        freq = None
    extra = []
    for module in info.get("ram", []):
        extra.append(f"{module.get('BankLabel', 'Módulo RAM')}: {(module.get('Capacity') or 0) / 1024 ** 3:.0f} GiB · "
                     f"{module.get('ConfiguredClockSpeed') or 'N/D'} MT/s · {str(module.get('PartNumber') or '').strip()}")
    for drive in info.get("disks", []):
        extra.append(f"{drive.get('Model') or 'Disco'}: {(drive.get('Size') or 0) / 1024 ** 3:.1f} GiB · {drive.get('InterfaceType') or 'N/D'}")
    extra += [f"Driver gráfico: {info.get('drivers') or 'N/D'}",
              f"Atualização informada pelo vídeo: {info.get('refresh') or 'N/D'} Hz",
              f"Plano de energia: {info.get('power') or 'N/D'}",
              "Configuração de canais e clock efetivo dependem de fonte adicional."]
    return ("INFORMAÇÕES DE HARDWARE\n\n"
            f"Sistema: {platform.system()} {platform.release()}\n"
            f"Placa-mãe: {info.get('motherboard', 'N/D')}\n"
            f"BIOS: {info.get('bios', 'N/D')}\n"
            f"Processador: {info.get('cpu') or platform.processor() or 'N/D'}\n"
            f"Núcleos físicos: {psutil.cpu_count(logical=False)} | Lógicos: {psutil.cpu_count()}\n"
            f"Frequência reportada pelo SO: {round(freq.current) if freq else 'N/D'} MHz\n"
            f"RAM total: {memory.total / 1024 ** 3:.1f} GiB\n"
            f"GPU(s): {info.get('gpu', 'Consulte os sensores no diagnóstico')}\n\n"
            + "\n".join(extra) + "\n\n" +
            "A disponibilidade das leituras depende do hardware, driver e permissões.\n"
            "Temperaturas e GPU AMD/Intel: integração opcional com LibreHardwareMonitor.\n")
