import platform
import psutil
import subprocess

def get_hardware_info():
    info = {}

    # Infos do Sistema Operacional
    info["os"] = platform.system()
    info["os_version"] = platform.release()

    # Infos da CPU
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

    # Memória RAM (Convertendo para GB)
    virtual_mem = psutil.virtual_memory()
    info["ram_total"] = f"{round(virtual_mem.total / (1024**3), 2)} GB"

    # Infos específicas de Windows (Placa Mãe e GPU)

    if info["os"] == "Windows":
        try:
            # Placa-mãe
            raw_mb = subprocess.check_output("wmic baseboard get product,Manufacturer", shell=True).decode()
            info['motherboard'] = raw_mb.split('\n')[1].strip()

            # Placa de Vídeo (GPU)
            raw_gpu = subprocess.check_output("wmic path win32_VideoController get name", shell=True).decode()
            info['gpu'] = raw_gpu.split('\n')[1].strip()
        except Exception:
            info['motherboard'] = "Não identificada"
            info['gpu'] = "Não identificada"

    return info
