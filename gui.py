import customtkinter as ctk

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

        # Painel do monitor
        self.monitor_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")

        # Variável para controlar se o loop do monitor deve rodar ou parar
        self.monitor_active = False

        # Lista dinâmica de discos que o usuário quer esconder
        self.discos_ignorados = []

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

        # Título da seção
        self.lbl_storage_title = ctk.CTkLabel(self.monitor_frame, text="--- Armazenamento ---",
                                              font=ctk.CTkFont(weight="bold"))
        self.lbl_storage_title.pack(pady=(10, 5))

        # FRAME PARA OS CHECKBOXES DO FILTRO
        self.filter_frame = ctk.CTkFrame(self.monitor_frame, fg_color="transparent")
        self.filter_frame.pack(pady=(0, 10))

        self.disk_widgets = {}

        # Puxa os dados SEM FILTRO inicial para descobrir TODOS os discos conectados
        dados_iniciais = get_live_data([])

        for disco_info in dados_iniciais["storage_percent"]:
            nome_disco = disco_info["disco"]

            # Cria a variável que sabe se o checkbox está marcado ou não
            var_checkbox = ctk.StringVar(value="on")  # "on" = mostrar, "off" = esconder

            # Cria o Checkbox
            chk = ctk.CTkCheckBox(
                self.filter_frame,
                text=nome_disco,
                variable=var_checkbox,
                onvalue="on",
                offvalue="off",
                command=lambda d=nome_disco, v=var_checkbox: self.toggle_disk(d, v)
            )
            chk.pack(side="left", padx=0)

            # Cria um Frame agrupador só para este disco
            disk_frame = ctk.CTkFrame(self.monitor_frame, fg_color="transparent")
            disk_frame.pack()

            # Cria a Label dentro deste disk_frame
            lbl = ctk.CTkLabel(disk_frame, text=f"Disco {nome_disco} Usage: 0%")
            lbl.pack()

            # Cria a Barra dentro deste disk_frame
            bar = ctk.CTkProgressBar(disk_frame, width=300)
            bar.set(0)
            bar.pack(pady=(0, 15))

            # Guarda no dicionário com a referência ao frame
            self.disk_widgets[nome_disco] = {
                "frame": disk_frame,
                "label": lbl,
                "bar": bar
            }

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
        # Só atualiza a tela se o botão Monitor Live estiver selecionado
        if self.monitor_active:
            dados = get_live_data(self.discos_ignorados)

            # Atualiza os Textos (CPU e RAM)
            self.lbl_uptime.configure(text=f"Tempo desde o boot: {dados['uptime']}")
            self.lbl_cpu_text.configure(text=f"CPU Usage: {dados['cpu_percent']}%")
            self.lbl_ram_text.configure(text=f"RAM Usage: {dados['ram_percent']}%")

            # Atualiza as Barras (CPU e RAM)
            self.bar_cpu.set(dados['cpu_percent'] / 100)
            self.bar_ram.set(dados['ram_percent'] / 100)

            # --- ATUALIZA OS DISCOS DINAMICAMENTE ---
            for disco_info in dados["storage_percent"]:
                nome = disco_info["disco"]
                percentual = disco_info["percent"]

                # Verifica se o disco existe no nosso dicionário de telas
                if nome in self.disk_widgets:
                    # Atualiza o texto do disco correspondente
                    self.disk_widgets[nome]["label"].configure(text=f"Disco {nome} Usage: {percentual}%")
                    # Atualiza a barra do disco correspondente
                    self.disk_widgets[nome]["bar"].set(percentual / 100)

            # Chama ela mesma de novo após 500 milissegundos
            self.after(500, self.update_monitor)

    def toggle_disk(self, disco, var_checkbox):
        if var_checkbox.get() == "off":
            # O usuário desmarcou a caixinha! Vamos ignorar esse disco.
            if disco not in self.discos_ignorados:
                self.discos_ignorados.append(disco)  # Adiciona na blacklist

            # Esconde o Frame inteiro da tela (Some a label e a barra)
            self.disk_widgets[disco]["frame"].pack_forget()
        else:
            # O usuário marcou de novo! Vamos voltar a monitorar.
            if disco in self.discos_ignorados:
                self.discos_ignorados.remove(disco)  # Tira da blacklist

            # Mostra o Frame na tela de novo
            self.disk_widgets[disco]["frame"].pack()
