# SysPulse

Uma ferramenta simples em Python para extração rápida de informações de hardware e monitoramento de recursos do sistema. 

O objetivo deste projeto é facilitar o diagnóstico técnico, consolidando dados de hardware e consumo de recursos em tempo real em um único lugar, permitindo identificar gargalos de performance durante o uso (como em jogos ou aplicações pesadas).

---

## 🚧 Em Obras: Refatoração para PySide6 (Qt6)

O projeto está passando por uma reestruturação arquitetural profunda. A migração do `CustomTkinter` para o **PySide6** (Qt6) tem como objetivo resolver gargalos de renderização na interface e preparar o terreno para um monitoramento em tempo real fluido e de alta performance.

### O que já foi implementado na nova versão:
* [x] **Nova Arquitetura Base:** Separação estrita entre o Motor da Aplicação (`main.py` / `QApplication`) e o Design da Interface (`gui.py` / `QMainWindow`).
* [x] **Gerenciamento de Layouts:** Adoção de `QHBoxLayout` e `QVBoxLayout` para uma interface responsiva e organizada.
* [x] **Módulo de Hardware:** Leitura de componentes otimizada via `subprocess` e `wmic`.
* [x] **Threading (Concorrência):** Coleta de dados pesados (`psutil`) isolada em um *Worker Thread* em segundo plano (`QThread`), garantindo que a *Main Thread* da interface rode sem congelamentos.
* [x] **Navegação Assíncrona:** Implementação de `QStackedWidget` para alternância fluida entre módulos (Hardware e Monitor).
* [x] **Monitoramento Visual:** Uso de Sinais e Slots para atualizar `QProgressBar` (CPU/RAM) e rótulos de I/O de disco em tempo real.

### Próximos Passos:
* [ ] **Tabela de Processos:** Renderização otimizada de todos os processos do sistema utilizando o modelo MVC (Model-View) do Qt.
* [ ] **Armazenamento:** Exibição do espaço de uso e partições dos discos locais.

## Tecnologias
- **Linguagem:** Python 3.x
- **Bibliotecas Principais:** `psutil`, `platform`, `PySide6`