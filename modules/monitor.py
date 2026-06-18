import psutil
import time
from datetime import datetime
from PySide6.QtCore import QObject, Signal
import GPUtil
from modules.network import NetworkMonitor

class MonitorWorker(QObject):

    dados_atualizados = Signal(dict)

    def __init__(self, discos_ignorados=None):
        super().__init__()
        self.discos_ignorados = discos_ignorados if discos_ignorados else []
        self.old_disk_io = psutil.disk_io_counters()
        self.num_cores = psutil.cpu_count()

        # Uma chave de segurança para ligar/desligar o monitor pelo menu
        self.is_running = True
        self.net_monitor = NetworkMonitor()  # Inicia a memória da rede

    def run(self):
        #O Motor: O loop que vai rodar no fundo eternamente (ou até mandar parar)

        while self.is_running:

            # Tempo de boot
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.now() - boot_time
            uptime_str = str(uptime).split('.')[0]

            # Coleta de dados em tempo real
            cpu_usage = psutil.cpu_percent(interval=None)
            ram_usage = psutil.virtual_memory().percent

            # GPU para casos de uma GPU só por hora

            gpus = GPUtil.getGPUs()
            gpu_info = {}

            for gpu in gpus:
                gpu_info['percent'] = round(gpu.load * 100)
                gpu_info['memory'] = round(gpu.memoryUsed / 1024,1)
                gpu_info['temperature'] = gpu.temperature

            # Coleta inteligente de todas as partições (Discos/SSDs)
            storage_usage = []

            # all=False ignora partições virtuais/vazias do sistema
            for partition in psutil.disk_partitions(all=False):
                try:
                    # Lê o uso do ponto de montagem (ex: "C:\", "D:\")
                    usage = psutil.disk_usage(partition.mountpoint)

                    # Limpa o nome (tira as barras) para ficar visualmente bonito, ex: "C:"
                    nome_disco = partition.device.replace('\\', '')

                    # Ignora o disco caso esteja na lista
                    if nome_disco in self.discos_ignorados:
                        continue

                    storage_usage.append({
                        "disco": nome_disco,
                        "percent": usage.percent,
                        "total": round(usage.total/1024/1024/1024,1),
                        "used": round(usage.used/1024/1024/1024,1),
                        "free": round(usage.free/1024/1024/1024,1)
                    })
                except Exception:
                    # O try/except é vital no Windows. Se houver um leitor de cartão ou
                    # drive de DVD vazio, o SO bloqueia a leitura. O except ignora e pula pro próximo.
                    continue

            # Cálculo de Atividade do Disco (I/O)
            new_disk_io = psutil.disk_io_counters()
            read_speed = (new_disk_io.read_bytes - self.old_disk_io.read_bytes) / 1024 / 1024
            write_speed = (new_disk_io.write_bytes - self.old_disk_io.write_bytes) / 1024 / 1024
            self.old_disk_io = new_disk_io  # Atualiza a referência para o próximo segundo

            # Coleta de processos individuais
            processos = []
            for proc in psutil.process_iter(['pid', 'name']):
                if proc.info['pid'] in (0, 4):
                    continue
                try:
                    cpu_val = proc.cpu_percent(interval=None) / self.num_cores
                    ram_val = proc.memory_percent()

                    # Sem o 'if' que tinha antes que considera processos com cpu > 0.0
                    # Agora coleta TODOS os processos do Windows (Uns 200 a 300 por ai)
                    processos.append({
                        'name': proc.info['name'],
                        'cpu_percent': round(cpu_val, 1),
                        'ram_percent': round(ram_val, 1)
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Montando dados para a interface

            dados = {
                "uptime": uptime_str,
                "gpu": gpu_info,
                "cpu_percent": cpu_usage,
                "ram_percent": ram_usage,
                "storage_percent": storage_usage,
                "disk_read_mb": round(read_speed, 1),
                "disk_write_mb": round(write_speed, 1),
                "processes": processos,
                "network": self.net_monitor.get_network_speed(),
                "ping": self.net_monitor.get_ping(),
                "net_info": self.net_monitor.get_infrastructure_info()
            }

            # Retorno dos dados coletados
            self.dados_atualizados.emit(dados)
            time.sleep(1)