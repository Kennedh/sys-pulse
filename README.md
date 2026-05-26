# SysPulse

Uma ferramenta simples em Python para extração rápida de informações de hardware e monitoramento de recursos do sistema. 

O objetivo deste projeto é facilitar o diagnóstico técnico, consolidando dados de hardware e consumo de recursos em tempo real em um único lugar, permitindo identificar gargalos de performance durante o uso (como em jogos ou aplicações pesadas).

## Interface Gráfica
- Construída com a biblioteca **CustomTkinter** (Modo Escuro / Tema Azul).
- Sistema de **Abas (Tabview)** para organização limpa dos módulos.
- Tabelas roláveis dinâmicas para listas longas (Scrollable Frames).

## Módulos
- [x] **HARDWARE:** Identificação estática de SO, CPU, Memória RAM, Placa-mãe e Placa de vídeo (Módulo Base).
- [x] **MONITOR LIVE (v1.3):** - Monitoramento em tempo real do uso de CPU e Memória RAM.
  - Leitura dinâmica de armazenamento com **Filtro de Discos** (permite ocultar partições específicas/virtuais da interface via checkboxes).
  - Tabela avançada de Processos: Listagem rolável dos **Top 30 processos** ativos, com ordenação dupla focada em caçar gargalos de consumo de CPU (%) e uso de RAM (%).

## Tecnologias
- **Linguagem:** Python 3.x
- **Bibliotecas Principais:** `psutil` (coleta de dados), `platform` (identificação do SO), `customtkinter` (GUI)
