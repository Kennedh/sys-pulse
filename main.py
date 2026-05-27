import sys
from PySide6.QtWidgets import QApplication
from gui import App

if __name__ == "__main__":
    # Instancia o motor do QT6 (Gerencia a interface e janelas)
    app = QApplication(sys.argv)

    # Chama a interface importada do gui
    janela = App()

    # Mostra a janela na tela (Meio obvio pela sintaxe mas vale o comentário)
    janela.show()

    # Inicia o loop do motor e garante a limpeza da memoria de maneira correta
    sys.exit(app.exec())
