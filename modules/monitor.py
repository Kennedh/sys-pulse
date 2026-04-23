import os
import time
import psutil
from datetime import datetime


def clear_console():
    # Limpa o terminal dependendo do SO
    os.system('cls' if os.name == 'nt' else 'clear')


def start_live_monitor(interval=1):
    try:
        # Tempo de boot
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time

        # Formatando para tirar os microsegundos
        uptime_str = str(uptime).split('.')[0]

        print(f"Uptime: {uptime_str}")
        while True:
            clear_console()

            # Coleta de dados em tempo real
            cpu_usage = psutil.cpu_percent(interval=None)
            ram_usage = psutil.virtual_memory().percent

            # Criando uma barra de progresso visual simples
            cpu_bar = "█" * int(cpu_usage / 5) + "░" * (20 - int(cpu_usage / 5))
            ram_bar = "█" * int(ram_usage / 5) + "░" * (20 - int(ram_usage / 5))
            disk = psutil.disk_usage('/')
            disk_usage = disk.percent
            disk_bar = "█" * int(disk_usage / 5) + "░" * (20 - int(disk_usage / 5))

            processos = []
            for proc in psutil.process_iter(['name', 'cpu_percent']):
                try:
                    processos.append(proc.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Ordena pelos que mais usam CPU e pega os 3 primeiros
            top_procs = sorted(processos, key=lambda x: x['cpu_percent'], reverse=True)[:3]

            print("=== SYS-PULSE LIVE MONITOR ===")
            print(f"Pressione CTRL+C para sair\n")
            print(f"CPU Usage: [{cpu_bar}] {cpu_usage}%")
            print(f"RAM Usage: [{ram_bar}] {ram_usage}%")
            print(f"Disk Usage: [{disk_bar}] {disk_usage}%")

            print("\n--- TOP PROCESSOS (CPU) ---")
            for p in top_procs:
                print(f"{p['name'][:15]:<15} | {p['cpu_percent']}%")

                time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\nMonitoramento encerrado pelo usuário.")
