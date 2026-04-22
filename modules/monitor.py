import os
import time
import psutil


def clear_console():
    # Limpa o terminal dependendo do SO
    os.system('cls' if os.name == 'nt' else 'clear')


def start_live_monitor(interval=1):
    try:
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

            print("=== SYS-PULSE LIVE MONITOR ===")
            print(f"Pressione CTRL+C para sair\n")
            print(f"CPU Usage: [{cpu_bar}] {cpu_usage}%")
            print(f"RAM Usage: [{ram_bar}] {ram_usage}%")
            print(f"Disk Usage: [{disk_bar}] {disk_usage}%")

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n\nMonitoramento encerrado pelo usuário.")
