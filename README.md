# SysPulse

Uma ferramenta simples em Python para extração rápida de informações de hardware e monitoramento de recursos do sistema. 

O objetivo deste projeto é facilitar o diagnóstico técnico, consolidando dados de hardware e consumo de recursos em tempo real em um único lugar, permitindo identificar gargalos de performance durante o uso (como em jogos ou aplicações pesadas).

---

## 🚧 Em Obras: Refatoração para PySide6 (Qt6)

O projeto está passando por uma reestruturação arquitetural profunda. A migração do `CustomTkinter` para o **PySide6** (Qt6) tem como objetivo resolver gargalos de renderização na interface e preparar o terreno para um monitoramento em tempo real fluido e de alta performance.

### O que já foi implementado na nova versão:
* [x] **Nova Arquitetura Base:** Separação estrita entre o Motor da Aplicação (`main.py` / `QApplication`) e o Design da Interface (`gui.py` / `QMainWindow`).
* [x] **Gerenciamento de Layouts:** Adoção de `QHBoxLayout` e `QVBoxLayout` para uma interface responsiva e organizada.
* [x] **Design e QSS:** Estilização usando o CSS nativo do Qt, garantindo alinhamento perfeito de relatórios com fontes *monospace*.
* [x] **Módulo de Hardware:** Leitura de componentes otimizada via `subprocess` e `wmic`, conectada reativamente à interface via *Signals and Slots*.

### Próximos Passos:
* [ ] **Módulo Monitor Live:** Recriação da tabela dinâmica de processos na nova engine.
* [ ] **Threading (Concorrência):** Isolar a coleta de dados pesados do `psutil` em um *Worker Thread* em segundo plano, garantindo que a *Main Thread* da interface rode a 60 FPS sem congelamentos.

## Tecnologias
- **Linguagem:** Python 3.x
- **Bibliotecas Principais:** `psutil`, `platform`, `PySide6`