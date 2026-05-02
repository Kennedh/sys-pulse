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
    storage_usage = psutil.disk_usage('/').percent

    # Barras visuais
    cpu_bar = "█" * int(cpu_usage / 5) + "░" * (20 - int(cpu_usage / 5))
    ram_bar = "█" * int(ram_usage / 5) + "░" * (20 - int(ram_usage / 5))
    storage_bar = "█" * int(storage_usage / 5) + "░" * (20 - int(storage_usage / 5))

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

    # Montando a "foto" (String formatada) em vez de dar print
    relatorio = (
        f"Tempo desde o boot: {uptime_str}\n\n"
        f"CPU Usage: [{cpu_bar}] {cpu_usage}%\n"
        f"RAM Usage: [{ram_bar}] {ram_usage}%\n"
        f"Armazenamento: [{storage_bar}] {storage_usage}%\n"
        f"Ativ. Disco:   Leitura: {read_speed:.1f} MB/s | Gravação: {write_speed:.1f} MB/s\n\n"
        f"--- TOP PROCESSOS (CPU) ---\n"
    )

    for p in top_procs:
        # Adicionando cada processo ao relatório
        relatorio += f"{p['name'][:15]:<15} | {p['cpu_percent']}%\n"

    return relatorio