# SysPulse

> Monitoramento de hardware, processos e rede em tempo real para facilitar diagnósticos e identificar gargalos de desempenho.

O **SysPulse** é uma aplicação desktop desenvolvida em Python para centralizar informações importantes do sistema em uma única interface. O projeto foi criado com foco em diagnóstico técnico, visualização em tempo real e responsividade mesmo durante coletas contínuas de dados.

## 🎯 O problema que resolve

Durante a análise de lentidão ou uso elevado de recursos, normalmente é necessário consultar diferentes ferramentas para entender CPU, memória, GPU, disco, processos e rede.

O SysPulse reúne essas informações em um só lugar para tornar a investigação mais rápida e visual.

## ✨ Principais funcionalidades

### Monitoramento de recursos
- Uso de CPU e memória RAM em tempo real
- Informações da GPU NVIDIA, incluindo carga, VRAM e temperatura
- Visualização do armazenamento por partição
- Monitoramento de leitura e escrita em disco
- Atualização contínua sem bloquear a interface

### Gestão de processos
- Listagem dos processos ativos
- Ordenação por CPU, memória RAM e nome
- Atualizações em tempo real
- Modelo otimizado para lidar com centenas de registros

### Rede
- Velocidade de download e upload
- Consumo de dados acumulado durante a sessão
- Monitoramento de latência
- Identificação do adaptador de rede ativo
- Exibição do IPv4 local e da velocidade do link

### Execução em segundo plano
- Minimização para a bandeja do sistema
- Restauração rápida da interface
- Encerramento pelo menu da bandeja

## 🧠 Destaques técnicos

O projeto foi estruturado para evitar que tarefas de monitoramento prejudiquem a experiência da interface.

Entre as decisões técnicas estão:

- **PySide6 / Qt6** para a interface gráfica
- **QThread** para coleta de dados em segundo plano
- Separação entre interface e lógica de monitoramento
- Padrão **Model-View** no gerenciamento da tabela de processos
- Cache de componentes visuais para reduzir recriações desnecessárias
- Uso de subprocessos para tarefas de rede sem bloquear a aplicação

## 🛠️ Tecnologias

- Python 3
- PySide6
- psutil
- GPUtil
- platform
- socket
- subprocess

## 📦 Instalação

Clone o repositório:

```bash
git clone https://github.com/Kennedh/sys-pulse.git
cd sys-pulse
```

Crie um ambiente virtual, se desejar:

```bash
python -m venv .venv
```

Ative o ambiente e instale as dependências:

```bash
pip install -r requirements.txt
```

## ▶️ Como executar

```bash
python main.py
```

> Algumas informações da GPU dependem de hardware NVIDIA compatível e dos recursos disponíveis no sistema operacional.

## 📁 Estrutura principal

```text
sys-pulse/
├── modules/            # módulos responsáveis pelas coletas e regras
├── gui.py              # interface principal
├── main.py             # ponto de entrada da aplicação
├── requirements.txt    # dependências
└── README.md
```

## 💡 O que este projeto demonstra

Além do objetivo funcional, o SysPulse explora conceitos importantes para aplicações desktop reais:

- concorrência e tarefas em segundo plano;
- atualização de dados em tempo real;
- separação de responsabilidades;
- integração com recursos do sistema operacional;
- tratamento de diferentes fontes de dados;
- preocupação com desempenho da interface.

## 🚀 Possíveis evoluções

- Histórico e gráficos de uso de recursos
- Alertas configuráveis para CPU, RAM, GPU e temperatura
- Exportação de diagnósticos
- Mais informações de hardware
- Empacotamento para distribuição como executável

---

Desenvolvido por [Kennedh](https://github.com/Kennedh).
