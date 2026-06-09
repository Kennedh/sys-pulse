import psutil
import time
import subprocess

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

    def get_ping(self):
        try:
            # -n 1: Envia apenas 1 pacote
            # -w 400: Limita a espera em no máximo 400ms (evita travar a thread)
            # Eu vou usar o IP do DNS do Google (8.8.8.8) por ser o mais estavel para testes
            comando = ["ping", "-n", "1", "-w", "400", "8.8.8.8"]

            # Executa o comando de forma oculta e captura o texto de saída
            resultado = subprocess.run(comando, capture_output=True, text=True, timeout=0.5)

            if resultado.returncode == 0:
                saida = resultado.stdout
                # O Windows em português exibe "tempo=XXms", em inglês exibe "time=XXms"
                if "tempo=" in saida:
                    tempo_str = saida.split("tempo=")[1].split("ms")[0].strip()
                    return int(tempo_str)
                elif "time=" in saida:
                    tempo_str = saida.split("time=")[1].split("ms")[0].strip()
                    return int(tempo_str)

            return -1  # Retorna -1 se houver perda de pacote ou timeout
        except Exception:
            return -1