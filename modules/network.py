import psutil
import time
import subprocess
import socket

class NetworkMonitor:
    def __init__(self):
        # Quando a classe é criada, guarda os dados do momento zero
        self.last_io = psutil.net_io_counters()
        self.last_time = time.time()

        # (Marco zero: Acumulo de download na sessão)guarda o dado de quando o app abriu
        self.start_io = self.last_io

    def get_network_speed(self):
        current_io = psutil.net_io_counters()
        current_time = time.time()

        # --- Cálculo da Velocidade Instantânea ---
        time_delta = current_time - self.last_time
        if time_delta == 0:
            time_delta = 1

        download_mbs = (current_io.bytes_recv - self.last_io.bytes_recv) / time_delta / (1024 * 1024)
        upload_mbs = (current_io.bytes_sent - self.last_io.bytes_sent) / time_delta / (1024 * 1024)

        # Atualiza a memória de curto prazo para o próximo segundo
        self.last_io = current_io
        self.last_time = current_time

        # --- Cálculo do Consumo Acumulado (NOVO) ---
        # Subtrai o atual pelo start_io (Marco Zero)
        total_down_mb = (current_io.bytes_recv - self.start_io.bytes_recv) / (1024 * 1024)
        total_up_mb = (current_io.bytes_sent - self.start_io.bytes_sent) / (1024 * 1024)

        # Retornamos tudo no mesmo dicionário
        return {
            'download_mbs': round(download_mbs, 2),
            'upload_mbs': round(upload_mbs, 2),
            'total_down_mb': round(total_down_mb, 2), # Adicionado
            'total_up_mb': round(total_up_mb, 2)      # Adicionado
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

    def get_infrastructure_info(self):
        # Captura o IP Local de forma confiável '-'
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            local_ip = "127.0.0.1"

        # Descobre qual interface de rede está ativa e sua velocidade física
        nome_interface = "Desconectado"
        velocidade_link = "0 Mbps"

        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()

        for interface, stat in stats.items():
            # Se a interface está de pé (isup) e possui endereços configurados
            if stat.isup and interface in addrs:
                # Evita laço de loopback interno
                if interface.lower() == 'lo' or 'loopback' in interface.lower():
                    continue

                # Verifica se essa interface ativa possui um IPv4 configurado
                has_ipv4 = False
                for addr in addrs[interface]:
                    if addr.family == socket.AF_INET:
                        has_ipv4 = True
                        break

                if has_ipv4:
                    nome_interface = interface
                    # O psutil retorna a velocidade em Mbps (ex: 1000 para Gigabit)
                    velocidade_link = f"{stat.speed//8} MBps" if stat.speed > 0 else "Desconhecida"
                    break

        return {
            "local_ip": local_ip,
            "interface_name": nome_interface,
            "link_speed": velocidade_link
        }