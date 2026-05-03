import customtkinter as ctk
from PIL.ImageOps import expand

from modules.hardware import get_hardware_info
from modules.monitor import get_live_data

# Configuração visual global
ctk.set_appearance_mode("dark")  # Modo escuro
ctk.set_default_color_theme("blue") # Cor dos botões e destaques

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Janela Principal
        self.title("SYS-PULSE - Monitor de Recursos")
        self.geometry("900x500")

        # Layout de grade (Grid) em duas colunas
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Frame
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=1)

        # Posicionando o Frame
        self.sidebar.grid(row=0, column=0, sticky="nesw")

        # Texto/Logo do titulo
        self.logo_label = ctk.CTkLabel(self.sidebar, text="SYS-PULSE", font=ctk.CTkFont(size=20, weight="bold"))

        # Posicionamento do titulo
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        # Adicionando um botão Hardware
        self.btn_hardware = ctk.CTkButton(self.sidebar, text="Hardware", command=self.show_hardware)

        # Adicionando o botão do Monitor Live
        self.btn_monitor = ctk.CTkButton(self.sidebar, text="Monitor Live", command=self.show_monitor)

        # Posicionando o botões
        self.btn_hardware.grid(row=1, column=0, padx=20, pady=10)
        self.btn_monitor.grid(row=2, column=0, padx=20, pady=10)

        # Frame da direita onde ficarão os modulos
        self.main_frame = ctk.CTkFrame(self, corner_radius=10)
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")

        # Adicionar um texto no main_frame
        self.conteudo_label = ctk.CTkLabel(self.main_frame, text="Selecione um módulo no menu lateral.", font=ctk.CTkFont(size=16))

        # Posicionando o texto. Em vez de usar o grid vou usar o pack para ficar centralizado
        self.conteudo_label.pack(pady=50)

        # Variável para controlar se o loop do monitor deve rodar ou parar
        self.monitor_active = False

        # Painel do monitor
        self.monitor_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")

        # Titulo do Uptime (Tempo de boot)
        self.lbl_uptime = ctk.CTkLabel(self.monitor_frame, text=" Uptime: --", font=ctk.CTkFont(size=14))
        self.lbl_uptime.pack(pady=(0, 20))

        # --- Bloco da CPU ---
        self.lbl_cpu_text = ctk.CTkLabel(self.monitor_frame, text="CPU Usage: 0%")
        self.lbl_cpu_text.pack()
        # ProgressBar
        self.bar_cpu = ctk.CTkProgressBar(self.monitor_frame, width=300)
        self.bar_cpu.set(0)
        self.bar_cpu.pack(pady=(0, 15))

        # --- Bloco da RAM ---
        self.lbl_ram_text = ctk.CTkLabel(self.monitor_frame, text="RAM Usage: 0%")
        self.lbl_ram_text.pack()
        # ProgresBar
        self.bar_ram = ctk.CTkProgressBar(self.monitor_frame, width=300)
        self.bar_ram.set(0)
        self.bar_ram.pack(pady=(0, 15))

    def show_hardware(self):
        self.monitor_frame.pack_forget()
        self.conteudo_label.pack(pady=50)

        # Desliga o monitor em tempo real para ele não sobrescrever a tela
        self.monitor_active = False

        relatorio_real = get_hardware_info()

        # Atualiza a tela com a descrição do hardware
        self.conteudo_label.configure(text=relatorio_real, justify="left", font=ctk.CTkFont(family="Courier", size=14))

    def show_monitor(self):
        # Liga o interruptor
        self.monitor_active = True

        # Esconde o label do hardware e mostro o frame do monitor
        self.conteudo_label.pack_forget()
        self.monitor_frame.pack(fill="both", expand=True, padx=20, pady=20)

        self.update_monitor()

    def update_monitor(self):
        # Só atualiza a tela se o botão Monitor Live estiver selecionado (flag True)
        if self.monitor_active:
            dados = get_live_data() # Retorna o dicionario de dados do modulo monitor

            # Atualiza os Textos e barras
            self.lbl_uptime.configure(text=f"Tempo desde o boot: {dados['uptime']}")
            self.lbl_cpu_text.configure(text=f"CPU Usage: {dados['cpu_percent']}%")
            self.bar_cpu.set(dados['cpu_percent']/100)
            self.lbl_ram_text.configure(text=f"RAM Usage: {dados['ram_percent']}%")
            self.bar_ram.set(dados['ram_percent']/100)

            # Chama ela mesma de novo após 500 milissegundos (meio segundo)
            self.after(500, self.update_monitor)
