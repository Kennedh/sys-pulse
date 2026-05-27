from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QFrame, QVBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt

from modules.hardware import get_hardware_info
from modules.monitor import get_live_data

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


        # Colocar os botões e a label dentro frame vertical
        self.frame_botoes.addWidget(self.logo_label)
        self.frame_botoes.addWidget(self.btn_hardware)
        self.frame_botoes.addWidget(self.btn_monitor)

        # Empurra tudo para cima
        self.frame_botoes.addStretch()

        # Frame da direita onde vou colocar os módulos
        self.main_frame = QFrame()
        self.main_frame.setStyleSheet("background-color: #121212;")

        # Agora para colocar os dois frames na tela
        self.main_layout.addWidget(self.sidebar)
        self.main_layout.addWidget(self.main_frame)
