import psutil
import time

class NetworkMonitor:
    def __init__(self):
        # Quando a classe é criada, guarda os dados do momento zero
        self.last_io = psutil.net_io_counters()
        self.last_time = time.time()

    def get_network_speed(self):
        # Pega os dados exatos de agora
        current_io = psutil.net_io_counters()
        current_time = time.time()

        # Calcula quanto tempo passou (normalmente 1 segundo, mas é bom ser exato)
        time_delta = current_time - self.last_time

        # Prevenção de erro de divisão por zero
        if time_delta == 0:
            time_delta = 1

        # Subtrai o atual pelo antigo para saber quanto trafegou NESTE segundo
        # E divide por (1024 * 1024) para converter de Bytes para Megabytes (MB)
        download_mbs = (current_io.bytes_recv - self.last_io.bytes_recv) / time_delta / (1024 * 1024)
        upload_mbs = (current_io.bytes_sent - self.last_io.bytes_sent) / time_delta / (1024 * 1024)

        # Atualiza a memória para ser usada no próximo ciclo!
        self.last_io = current_io
        self.last_time = current_time

        return {
            'download_mbs': round(download_mbs, 2),
            'upload_mbs': round(upload_mbs, 2)
        }