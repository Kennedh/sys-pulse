import os
import time
import psutil
from datetime import datetime


def clear_console():
    # Limpa o terminal dependendo do SO
    os.system('cls' if os.name == 'nt' else 'clear')


def start_live_monitor(interval=1):
    num_cores = psutil.cpu_count()

    try:
        # Tempo de boot
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time

        # Formatando para tirar os microsegundos
        uptime_str = str(uptime).split('.')[0]

        # Pega a referência inicial do disco antes do loop começar
        old_disk_io = psutil.disk_io_counters()

        print(f"Tempo desde o boot: {uptime_str}")
        while True:
            clear_console()

            # Coleta de dados em tempo real
            cpu_usage = psutil.cpu_percent(interval=None)
            ram_usage = psutil.virtual_memory().percent

            # Criando uma barra de progresso visual simples
            cpu_bar = "█" * int(cpu_usage / 5) + "░" * (20 - int(cpu_usage / 5))
            ram_bar = "█" * int(ram_usage / 5) + "░" * (20 - int(ram_usage / 5))
            storage_usage = psutil.disk_usage('/').percent
            storage_bar = "█" * int(storage_usage / 5) + "░" * (20 - int(storage_usage / 5))

            # Cálculo de Atividade do Disco (I/O)
            new_disk_io = psutil.disk_io_counters()

            # Subtrai o novo do velho e converte bytes para Megabytes (MB)
            read_speed = (new_disk_io.read_bytes - old_disk_io.read_bytes) / 1024 / 1024
            write_speed = (new_disk_io.write_bytes - old_disk_io.write_bytes) / 1024 / 1024

            # Atualiza a referência para o próximo ciclo
            old_disk_io = new_disk_io

            # Coleta de processos individuais
            processos = []
            for proc in psutil.process_iter(['pid', 'name']):
                # Ignora o "System Idle Process" (PID 0) e o "System" (PID 4) que o Windows oculta
                if proc.info['pid'] in (0, 4):
                    continue
                try:
                    cpu_val = proc.cpu_percent(interval=None) / num_cores
                    # Filtra os zerados para focar apenas nos processos ativos (ex: LoL, PyCharm)
                    if cpu_val > 0.0:
                        processos.append({'name': proc.info['name'], 'cpu_percent': round(cpu_val, 1)})
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Ordena pelos que mais usam CPU e pega a quantidade da variavel qt_processes
            qt_processes = 5
            top_procs = sorted(processos, key=lambda x: x['cpu_percent'], reverse=True)[:qt_processes]

            print("=== SYS-PULSE LIVE MONITOR ===")
            print(f"Pressione CTRL+C para sair\n")
            print(f"CPU Usage: [{cpu_bar}] {cpu_usage}%")
            print(f"RAM Usage: [{ram_bar}] {ram_usage}%")
            print(f"Armazenamento: [{storage_bar}] {storage_usage}%")
            print(f"Ativ. Disco:   Leitura: {read_speed:.1f} MB/s | Gravação: {write_speed:.1f} MB/s\n")

            print("\n--- TOP PROCESSOS (CPU) ---")
            for p in top_procs:
                print(f"{p['name'][:15]:<15} | {p['cpu_percent']}%")
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\nMonitoramento encerrado pelo usuário.")
