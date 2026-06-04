from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QFrame, QVBoxLayout, QLabel, QPushButton,
                               QStackedWidget, QProgressBar, QTabWidget, QTableView, QHeaderView, QSystemTrayIcon,
                               QMenu, QStyle, QApplication)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from modules.hardware import get_hardware_info
from PySide6.QtCore import QThread, QAbstractTableModel
from modules.monitor import MonitorWorker


class ProcessTableModel(QAbstractTableModel):
    def __init__(self, dados):
        super().__init__()
        self.dados = dados
        # Padrão: Coluna 1 (CPU), do maior para o menor (Descending)
        self.coluna_ordenacao = 1
        self.ordem_ordenacao = Qt.DescendingOrder

    def columnCount(self, parent=None):
        return 3

    def rowCount(self, parent=None):
        return len(self.dados['processes'])

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            linha = index.row()
            processo = self.dados['processes'][linha]
            coluna = index.column()

            if coluna == 0:
                return processo['name']
            elif coluna == 1:
                return f"{processo['cpu_percent']}%"
            elif coluna == 2:
                return f"{processo['ram_percent']}%"

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if section == 0:
                return "Nome"
            elif section == 1:
                return "CPU"
            elif section == 2:
                return "RAM"

    def sort(self, column, order):
        # O Qt chama este metodo automaticamente quando clica no título da tabela!
        self.coluna_ordenacao = column
        self.ordem_ordenacao = order
        self.aplicar_ordenacao()

    def aplicar_ordenacao(self):
        # Se a lista estiver vazia, não faz nada
        if not self.dados['processes']:
            return

        # Descobre qual chave do dicionário usar para ordenar
        if self.coluna_ordenacao == 0:
            chave = 'name'
        elif self.coluna_ordenacao == 1:
            chave = 'cpu_percent'
        elif self.coluna_ordenacao == 2:
            chave = 'ram_percent'

        # Verifica se é do maior para o menor
        reverso = (self.ordem_ordenacao == Qt.DescendingOrder)

        # ordena a lista baseada na chave escolhida!
        self.dados['processes'].sort(key=lambda x: x[chave], reverse=reverso)

        # Avisa a interface que os dados mudaram de lugar
        self.layoutChanged.emit()

    def atualizar_dados(self, novos_dados):
        self.dados = novos_dados
        # Agora chama a ordenação em vez do layoutChanged!
        self.aplicar_ordenacao()

class App(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("SYS-PULSE - Monitoramento Inteligente")
        self.resize(1000, 500)

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

        # Abas
        self.abas_monitor = QTabWidget()

        self.abas_monitor.setStyleSheet("""
                    QTabWidget::pane { border: none; }
                    QTabBar::tab { background: #1e1e1e; color: #888; padding: 10px 30px; font-weight: bold; font-size: 14px;}
                    QTabBar::tab:hover { background: #333; color: white; }
                    QTabBar::tab:selected { background: #425BA8; color: white; }
                """)

        # Cada aba é adicionado como Widget
        self.aba_recursos = QWidget()
        self.aba_processos = QWidget()

        self.abas_monitor.addTab(self.aba_recursos, "Recursos")
        self.abas_monitor.addTab(self.aba_processos, "Processos")

        layout_base_monitor = QVBoxLayout(self.tela_monitor)
        layout_base_monitor.addWidget(self.abas_monitor)

        # Tela de recursos
        layout_recursos = QVBoxLayout(self.aba_recursos)

        # Tempo de boot
        self.label_uptime = QLabel()
        self.label_uptime.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_uptime.setStyleSheet("""
                                        QLabel {
                                            color: white;
                                            font-weight: bold;
                                            font-size: 18px;
                                            font: monospace;
                                        }
                                        """)
        self.label_uptime.setFixedHeight(50)
        layout_recursos.addWidget(self.label_uptime)

        # CPU Label e Progress Bar
        self.label_cpu = QLabel()
        self.label_cpu.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_cpu.setStyleSheet("""
                                     QLabel {
                                         color: white;
                                         font-weight: bold;
                                         font-size: 16px;
                                         font-family: Consolas, monospace;
                                     }
                                     """)
        layout_recursos.addWidget(self.label_cpu)

        self.barra_cpu = QProgressBar()
        self.barra_cpu.setRange(0, 100)  # Define que a barra trabalha com porcentagem (0 a 100)
        self.barra_cpu.setValue(0)
        layout_recursos.addWidget(self.barra_cpu)

        # RAM Label e Progress Bar
        self.label_ram = QLabel()
        self.label_ram.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_ram.setStyleSheet("""
                                     QLabel {
                                         color: white;
                                         font-weight: bold;
                                         font-size: 16px;
                                         font-family: Consolas, monospace;
                                     }
                                     """)
        layout_recursos.addWidget(self.label_ram)

        self.barra_ram = QProgressBar()
        self.barra_ram.setRange(0, 100)  # Define que a barra trabalha com porcentagem (0 a 100)
        self.barra_ram.setValue(0)
        layout_recursos.addWidget(self.barra_ram)

        # GPU Label e progress bar
        self.label_gpu = QLabel()
        self.label_gpu.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_gpu.setStyleSheet("""
                                             QLabel {
                                                 color: white;
                                                 font-weight: bold;
                                                 font-size: 16px;
                                                 font-family: Consolas, monospace;
                                             }
                                             """)
        layout_recursos.addWidget(self.label_gpu)

        self.barra_gpu = QProgressBar()
        self.barra_gpu.setRange(0, 100)  # Define que a barra trabalha com porcentagem (0 a 100)
        self.barra_gpu.setValue(0)
        layout_recursos.addWidget(self.barra_gpu)

        #Discos
        self.label_discos = QLabel()
        self.label_discos.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_discos.setStyleSheet("""
                                        QLabel {
                                            color: white;
                                            font-weight: bold;
                                            font-size: 16px;
                                            font-family: Consolas, monospace;
                                        }
                                        """)
        self.label_discos.setText("DISCOS")
        self.label_discos.setFixedHeight(20)
        layout_recursos.addWidget(self.label_discos)

        # Velocidade de Leitura e Escrita dos Discos
        self.label_disk_speed = QLabel()
        self.label_disk_speed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_disk_speed.setStyleSheet("""
                                            QLabel {
                                                color: white;
                                                font-weight: bold;
                                                font-size: 16px;
                                                font-family: Consolas, monospace;
                                            }
                                            """)
        self.label_disk_speed.setFixedHeight(50)
        layout_recursos.addWidget(self.label_disk_speed)

        # Armazenamento utilizado em cada disco
        self.barras_discos = {}

        self.layout_discos = QVBoxLayout()
        self.layout_discos.setSpacing(15)

        layout_recursos.addLayout(self.layout_discos)

        # Empurra tudo para cima
        layout_recursos.addStretch()
        self.frame_modulos.addStretch()

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

        # PROCESSOS
        layout_processos = QVBoxLayout(self.aba_processos)

        self.view_processos = QTableView()
        self.view_processos.setStyleSheet("""
                    QTableView { background-color: #121212; color: white; gridline-color: #333; border: none; font-size: 13px;}
                    QHeaderView::section { background-color: #1e1e1e; color: white; padding: 5px; border: 1px solid #333; font-weight: bold; font-size: 13px;}
                    QTableView::item:selected { background-color: #425BA8; }
                """)
        layout_processos.addWidget(self.view_processos)

        # Cria a view vazia para depois popular os dados
        dados_vazios = {'processes': []}
        self.modelo_processos = ProcessTableModel(dados_vazios)

        # Conecta ao modelo de dados
        self.view_processos.setModel(self.modelo_processos)

        # Ordenação da view
        self.view_processos.setSortingEnabled(True)

        # Ajustar tamanho da coluna na View
        header = self.view_processos.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        # Icone da bandeja
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))

        # Menu do TrayIcon
        tray_menu = QMenu()

        # Opções clicaveis
        action_restaurar = QAction("Restaurar", self)
        action_sair = QAction("Sair", self)

        # Reabre a janela
        action_restaurar.triggered.connect(self.show)

        # Para fechar é necessário chamar o motor da aplicação que está na Main (QApplication)
        action_sair.triggered.connect(QApplication.instance().quit)

        # 4. Adicionamos as ações dentro do menu
        tray_menu.addAction(action_restaurar)
        tray_menu.addAction(action_sair)

        # 5. Finalmente, colamos o menu no nosso ícone da bandeja!
        self.tray_icon.setContextMenu(tray_menu)

    def mostrar_hardware(self):
        self.telas.setCurrentIndex(1)
        self.label_hardware.setText(f"{get_hardware_info()}")

    def atualizar_tela_monitor(self, dados):
        self.label_uptime.setText(f"Tempo desde o Boot: {dados['uptime']}")
        self.label_cpu.setText(f"Uso de CPU: {dados['cpu_percent']}%")
        self.barra_cpu.setValue(int(dados['cpu_percent']))
        self.label_ram.setText(f"Uso de RAM: {dados['ram_percent']}%")
        self.barra_ram.setValue(int(dados['ram_percent']))
        self.label_gpu.setText(f"GPU\n\nMemória Utilizada: {dados['gpu']['memory']} GB Temperatura: {dados['gpu']['temperature']} º\n\n"
                               f"Uso: {dados['gpu']['percent']}%")
        self.barra_gpu.setValue(int(dados['gpu']['percent']))
        self.label_disk_speed.setText(f"Leitura: {dados['disk_read_mb']} MB/s Escrita: {dados['disk_write_mb']} MB/s")

        # Discos
        for info in dados['storage_percent']:
            nome_disco = info['disco']
            uso_percent = int(info['percent'])
            total = info['total']
            utilizado = info['used']
            livre = info['free']

            # Verifica se o disco já está no dicionario criado no __init__
            # Se sim atualiza os valores da label e progress bar
            if nome_disco in self.barras_discos:
                label_disco, barra_disco = self.barras_discos[nome_disco]
                label_disco.setText(f"{nome_disco} Total: {total} GB Livre: {livre} GB Utilizado: {utilizado} GB ({uso_percent}%)")
                barra_disco.setValue(uso_percent)

            # Se não é criado e configurado cada label e progress bar
            else:
                label_disco = QLabel()
                label_disco.setAlignment(Qt.AlignmentFlag.AlignCenter)
                label_disco.setStyleSheet("""
                                              QLabel {
                                                  color: white;
                                                  font-size: 14px;
                                                  font-family: DejaVu Sans Mono, monospace;
                                              }
                                              """)
                label_disco.setText(f"{nome_disco} Total: {total} GB Livre: {livre} GB Utilizado: {utilizado} GB ({uso_percent}%)")

                barra_disco = QProgressBar()
                barra_disco.setRange(0, 100)
                barra_disco.setValue(uso_percent)

                self.layout_discos.addWidget(label_disco)
                self.layout_discos.addWidget(barra_disco)

                self.barras_discos[nome_disco] = (label_disco, barra_disco)

        # Atualizar dados da view
        self.modelo_processos.atualizar_dados(dados)


    def mostrar_monitor(self):
        self.telas.setCurrentIndex(2)
        self.thread_monitor.start()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.show()