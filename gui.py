import customtkinter as ctk
from modules.hardware import get_hardware_info

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

        # Adicionando um botão
        self.btn_hardware = ctk.CTkButton(self.sidebar, text="Hardware", command=self.show_hardware)

        # Posicionando o botão
        self.btn_hardware.grid(row=1, column=0, padx=20, pady=10)

        # Frame da direita onde ficarão os modulos
        self.main_frame = ctk.CTkFrame(self, corner_radius=10)
        self.main_frame.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")

        # Adicionar um texto no main_frame
        self.conteudo_label = ctk.CTkLabel(self.main_frame, text="Selecione um módulo no menu lateral.", font=ctk.CTkFont(size=16))

        # Posicionando o texto. Em vez de usar o grid vou usar o pack para ficar centralizado
        self.conteudo_label.pack(pady=50)

    def show_hardware(self):
        relatorio_real = get_hardware_info()

        # Atualiza a tela com a descrição do hardware
        self.conteudo_label.configure(text=relatorio_real, justify="left", font=ctk.CTkFont(family="Courier", size=14))

# Loop Principal
if __name__ == "__main__":
    app = App()
    app.mainloop()