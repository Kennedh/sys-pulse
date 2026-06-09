# SysPulse

Uma ferramenta avançada em Python para extração rápida de informações de hardware e monitoramento de recursos do sistema. 

O objetivo deste projeto é facilitar o diagnóstico técnico, consolidando dados de hardware e consumo de recursos em tempo real em um único lugar, permitindo identificar gargalos de performance durante o uso (como em jogos ou aplicações pesadas).

---

## 🚀 Funcionalidades Principais

A interface foi construída utilizando **PySide6 (Qt6)**, focando em alta performance, concorrência e renderização fluida:

* **Arquitetura Desacoplada:** Separação estrita entre a interface gráfica (`gui.py`) e a lógica de coleta de dados (`monitor.py`).
* **Coleta de Dados Assíncrona:** Uso de `QThread` (Worker Threads) para realizar a leitura de sensores em segundo plano, garantindo que a interface principal nunca congele.
* **Monitoramento Visual Completo (Aba Recursos):**
  * Uso de CPU e RAM atualizados em tempo real via barras de progresso.
  * Leitura de carga, memória VRAM e temperatura da GPU (NVIDIA).
  * Exibição dinâmica do armazenamento de múltiplas partições (Total, Livre, Utilizado) com sistema de cache de componentes para evitar vazamentos de memória.
  * Monitoramento de I/O de disco (Velocidade de Leitura/Escrita).
* **Gestão de Processos (Aba Processos):**
  * Tabela em tempo real com todos os processos ativos do Windows.
  * Renderização otimizada utilizando o padrão **MVC (Model-View)** nativo do Qt (`ProcessTableModel` e `QTableView`), capaz de lidar com centenas de linhas sem perda de performance.
  * Ordenação dinâmica de processos (por uso de CPU, RAM ou Nome) com preservação de estado entre atualizações.
* **Monitoramento de Rede (Módulo Network):**
  * Cálculo dinâmico da taxa de transferência de rede, exibindo velocidades de Download e Upload em Megabytes por segundo (MB/s).
  * Monitor de latência (Ping) integrado rodando de forma assíncrona via subprocesso nativo para evitar travamentos, com tratamento para perdas de pacotes ou falhas de conexão.
* **Execução em Segundo Plano (Bandeja do Sistema):**
  * Interceptação do evento de fechamento da janela principal (`closeEvent`). Ao clicar em fechar, a aplicação é minimizada para a área de notificação do Windows (`QSystemTrayIcon`).
  * Menu de contexto integrado na bandeja do sistema que permite restaurar a interface gráfica ou encerrar definitivamente a execução da ferramenta.

## 🛠️ Tecnologias
- **Linguagem:** Python 3.x
- **Interface Gráfica:** `PySide6` (Qt6)
- **Bibliotecas de Sensores e Sistema:** `psutil`, `GPUtil`, `platform`, `subprocess`