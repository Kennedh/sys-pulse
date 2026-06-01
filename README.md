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
* [x] **Armazenamento Dinâmico:** Exibição em tempo real do espaço de uso (Total, Livre, Utilizado) de múltiplas partições, utilizando um sistema de cache de dicionários para reciclar instâncias de `QLabel` e `QProgressBar`, prevenindo vazamentos de memória (memory leaks).

### Próximos Passos:
* [ ] **Monitoramento de GPU:** Integração de leitura de carga e memória da placa de vídeo ao painel de monitoramento.
* [ ] **Tabela de Processos:** Renderização otimizada de todos os processos do sistema utilizando o modelo MVC (Model-View) nativo do Qt.

## Tecnologias
- **Linguagem:** Python 3.x
- **Bibliotecas Principais:** `psutil`, `platform`, `PySide6`