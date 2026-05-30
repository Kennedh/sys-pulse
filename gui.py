from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QFrame, QVBoxLayout, QLabel, QPushButton, QStackedWidget
from PySide6.QtCore import Qt

from modules.hardware import get_hardware_info
from PySide6.QtCore import QThread
from modules.monitor import MonitorWorker

class App(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("SYS-PULSE - Monitoramento Inteligente")
        self.resize(900, 500)

        # Cor de fundo padrãozinho CSS
        self.setStyleSheet("background-color: #121212;")

        # QWidget é onde tudo ficará
        central_widget = QWidget()

        # E preciso setar na Classe o widget
        self.setCentralWidget(central_widget)

        # Layout Horizontal com QHBoxLayout e dentro vai o widget central
        self.main_layout = QHBoxLayout(central_widget)

        # Para não ter mangem e a interface encostar na ponta da janelea
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Criação do frame da esquerda
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(200)
        self.sidebar.setStyleSheet("background-color: #1e1e1e;")

        # Layout vertical pra ficar dentro do sidebar
        self.frame_botoes = QVBoxLayout(self.sidebar)

        # Logo
        self.logo_label = QLabel("SYS-PULSE")
        self.logo_label.setStyleSheet("""
                                      QLabel {
                                          color: white;
                                          font-weight: bold;
                                          font-size: 30px
                                      }
                                      """)
        self.logo_label.setAlignment(Qt.AlignCenter)
        self.logo_label.setFixedHeight(100)

        # Botões
        self.btn_hardware = QPushButton("HARDWARE")
        self.btn_hardware.setStyleSheet("""
                                        QPushButton {
                                            background-color: #425BA8;
                                            color: white;
                                            font-weight: bold;
                                            border-radius: 5px;
                                            padding: 10px;
                                        }
                                        QPushButton:hover {
                                            background-color: #536bc2;
                                        }
                                    """)

        self.btn_hardware.clicked.connect(self.mostrar_hardware)

        self.btn_monitor = QPushButton("LIVE MONITOR")
        self.btn_monitor.setStyleSheet("""
                                        QPushButton {
                                            background-color: #425BA8;
                                            color: white;
                                            font-weight: bold;
                                            border-radius: 5px;
                                            padding: 10px;
                                        }
                                        QPushButton:hover {
                                            background-color: #536bc2;
                                        }
                                    """)


        # Frame da direita onde vou colocar os módulos
        self.main_frame = QFrame()
        self.main_frame.setStyleSheet("background-color: #121212;")

        # Frame para o conteudo dos modulos dentro main_frame
        self.frame_modulos = QVBoxLayout(self.main_frame)

        # Onde ficaram as janelas de cada modulo
        self.telas = QStackedWidget()

        # Label do frame da direita utilizando o sistema de "baralho" no qual vai empilhando as telas

        self.telas = QStackedWidget()

        # ==== COLOCANDO O CONTEUDO NA TELA ====

        # Colocar os botões e a label dentro frame vertical
        self.frame_botoes.addWidget(self.logo_label)
        self.frame_botoes.addWidget(self.btn_hardware)
        self.frame_botoes.addWidget(self.btn_monitor)

        self.frame_botoes.addStretch() # Empurra tudo para cima

        # Coloca a label no frame dos modulos
        self.frame_modulos.addWidget(self.telas)

        # Criando as páginas para os modulos
        self.tela_inicial = QWidget()
        self.tela_hardware = QWidget()
        self.tela_monitor = QWidget()

        # Colocando no baralho
        self.telas.addWidget(self.tela_inicial)  # Carta 0
        self.telas.addWidget(self.tela_hardware)  # Carta 1
        self.telas.addWidget(self.tela_monitor)  # Carta 2

        # Tela Incial
        layout_inicial = QVBoxLayout(self.tela_inicial)
        label_inicial = QLabel("Selecione um módulo no menu lateral.")
        label_inicial.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label_inicial.setStyleSheet("""
                                                      QLabel {
                                                          color: white;
                                                          font-weight: bold;
                                                          font-size: 20px;
                                                      }
                                                      """)
        layout_inicial.addWidget(label_inicial)

        # Tela do Hardware
        layout_hardware = QVBoxLayout(self.tela_hardware)
        self.label_hardware = QLabel()
        self.label_hardware.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.label_hardware.setStyleSheet("""
                                              QLabel {
                                                  color: white;
                                                  font-weight: bold;
                                                  font-size: 16px;
                                                  font-family: Consolas, monospace;
                                              }
                                              """)
        layout_hardware.addWidget(self.label_hardware)

        # Tela do Monitor
        layout_monitor = QVBoxLayout(self.tela_monitor)
        self.label_monitor = QLabel()
        self.label_monitor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_monitor.setStyleSheet("""
                                                      QLabel {
                                                          color: white;
                                                          font-weight: bold;
                                                          font-size: 16px;
                                                          font-family: Consolas, monospace;
                                                      }
                                                      """)
        layout_monitor.addWidget(self.label_monitor)

        self.frame_modulos.addStretch() # Empurra tudo para cima

        # Agora para colocar os dois frames
        self.main_layout.addWidget(self.sidebar)
        self.main_layout.addWidget(self.main_frame)

        # === LIVE MONITOR ===

        # Criação de um Thread especifico para o monitor
        self.thread_monitor = QThread()
        self.worker_monitor = MonitorWorker()

        # Mover o worker de dados do monitor para dentro do thread
        self.worker_monitor.moveToThread(self.thread_monitor)

        # Quando a thread iniciar, ela deve rodar o método run do worker
        self.thread_monitor.started.connect(self.worker_monitor.run)

        # Pegar os dados atualizados e jogar na tela
        self.worker_monitor.dados_atualizados.connect(self.atualizar_tela_monitor)

        # Adição de evento ao botão
        self.btn_monitor.clicked.connect(self.mostrar_monitor)

    def mostrar_hardware(self):
        self.telas.setCurrentIndex(1)
        self.label_hardware.setText(f"{get_hardware_info()}")

    def atualizar_tela_monitor(self, dados):
        self.label_monitor.setText(f"Uso da CPU: {dados['cpu_percent']}%\n"
                                   f"Uso da RAM: {dados['ram_percent']}%")

    def mostrar_monitor(self):
        self.telas.setCurrentIndex(2)
        self.thread_monitor.start()