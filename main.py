from modules.hardware import get_hardware_info
from modules.monitor import start_live_monitor


def main():
    print("1 - Relatório Completo de Hardware")
    print("2 - Monitoramento em Tempo Real (Live)")

    opcao = input("\nEscolha uma opção: ")

    if opcao == '1':
        info = get_hardware_info()
    elif opcao == '2':
        start_live_monitor()
    else:
        print("Opção inválida.")


if __name__ == "__main__":
    main()