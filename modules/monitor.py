import psutil
from datetime import datetime

# Essa variável fica de fora da função para não ser zerada toda vez que a interface pedir dados
old_disk_io = psutil.disk_io_counters()

def get_live_data():
    global old_disk_io # Avisa a função para usar a variável lá de cima
    num_cores = psutil.cpu_count()

    # Tempo de boot
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime = datetime.now() - boot_time
    uptime_str = str(uptime).split('.')[0]

    # Coleta de dados em tempo real
    cpu_usage = psutil.cpu_percent(interval=None)
    ram_usage = psutil.virtual_memory().percent
    # Coleta inteligente de todas as partições (Discos/SSDs)

    storage_usage = []
    # all=False ignora partições virtuais/vazias do sistema
    for partition in psutil.disk_partitions(all=False):
        try:
            # Lê o uso do ponto de montagem (ex: "C:\", "D:\")
            usage = psutil.disk_usage(partition.mountpoint)

            # Limpa o nome (tira as barras) para ficar visualmente bonito, ex: "C:"
            nome_disco = partition.device.replace('\\', '')

            storage_usage.append({
                "disco": nome_disco,
                "percent": usage.percent
            })
        except Exception:
            # O try/except é vital no Windows. Se houver um leitor de cartão ou
            # drive de DVD vazio, o SO bloqueia a leitura. O except ignora e pula pro próximo.
            continue

    # Cálculo de Atividade do Disco (I/O)
    new_disk_io = psutil.disk_io_counters()
    read_speed = (new_disk_io.read_bytes - old_disk_io.read_bytes) / 1024 / 1024
    write_speed = (new_disk_io.write_bytes - old_disk_io.write_bytes) / 1024 / 1024
    old_disk_io = new_disk_io # Atualiza a referência para o próximo segundo

    # Coleta de processos individuais
    processos = []
    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['pid'] in (0, 4):
            continue
        try:
            cpu_val = proc.cpu_percent(interval=None) / num_cores
            if cpu_val > 0.0:
                processos.append({'name': proc.info['name'], 'cpu_percent': round(cpu_val, 1)})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Ordenação
    qt_processes = 10
    top_procs = sorted(processos, key=lambda x: x['cpu_percent'], reverse=True)[:qt_processes]

    # Montando dados para a interface

    dados = {
        "uptime": uptime_str,
        "cpu_percent": cpu_usage,
        "ram_percent": ram_usage,
        "storage_percent": storage_usage,
        "disk_read_mb": round(read_speed, 1),
        "disk_write_mb": round(write_speed, 1),
        "top_processes": top_procs
    }

    return dados