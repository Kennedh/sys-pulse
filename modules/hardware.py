import platform
import psutil
import subprocess


def executar_powershell(comando):
    try:
        resultado = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                comando
            ],
            text=True,
            encoding="utf-8",
            errors="ignore"
        )

        return resultado.strip()

    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_hardware_info():
    info = {}

    # Informações do sistema operacional
    info["os"] = platform.system()
    info["os_version"] = platform.release()

    # Informações da CPU
    if info["os"] == "Windows":
        info["cpu"] = executar_powershell(
            "(Get-CimInstance Win32_Processor).Name"
        ) or platform.processor()
    else:
        info["cpu"] = platform.processor()

    freq = psutil.cpu_freq()

    if freq:
        info["cpu_freq_current"] = f"{round(freq.current / 1000, 2)} GHz"
        info["cpu_freq_max"] = f"{round(freq.max / 1000, 2)} GHz"
    else:
        info["cpu_freq_current"] = "N/A"
        info["cpu_freq_max"] = "N/A"

    info["cpu_cores_physical"] = psutil.cpu_count(logical=False)
    info["cpu_cores_logical"] = psutil.cpu_count(logical=True)

    # Memória RAM
    virtual_mem = psutil.virtual_memory()
    info["ram_total"] = f"{round(virtual_mem.total / (1024 ** 3), 2)} GB"

    # Informações específicas do Windows
    if info["os"] == "Windows":
        fabricante = executar_powershell(
            "(Get-CimInstance Win32_BaseBoard).Manufacturer"
        )

        modelo = executar_powershell(
            "(Get-CimInstance Win32_BaseBoard).Product"
        )

        if fabricante or modelo:
            info["motherboard"] = " ".join(
                item for item in [fabricante, modelo] if item
            )
        else:
            info["motherboard"] = "Não identificada"

        info["gpu"] = executar_powershell(
            "(Get-CimInstance Win32_VideoController | "
            "Select-Object -First 1 -ExpandProperty Name)"
        ) or "Não identificada"

    relatorio = (
        "\nINFORMAÇÕES DE HARDWARE\n\n"
        f"Sist. Operacional: {info.get('os')} {info.get('os_version')}\n"
        f"Placa Mãe:         {info.get('motherboard', 'N/A')}\n"
        f"Processador:       {info.get('cpu', 'N/A')}\n"
        f"Núcleos CPU:       {info.get('cpu_cores_physical')} Físicos / "
        f"{info.get('cpu_cores_logical')} Lógicos\n"
        f"Frequência CPU:    {info.get('cpu_freq_current')} "
        f"(Max: {info.get('cpu_freq_max')})\n"
        f"Memória RAM:       {info.get('ram_total')}\n"
        f"Placa de Vídeo:    {info.get('gpu', 'N/A')}\n"
    )

    return relatorio