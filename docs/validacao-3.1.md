# Validação 3.1

## Sessões longas

Uma sessão sintética de 30 minutos verificou a evolução, a mudança de carga após dez minutos e as tendências de temperatura/frequência. Foram testadas também deduplicação de sensores, identidade do processo e distribuição temporal dos quadros.

A captura real anterior de aproximadamente 1.799,5 s foi reanalisada com o novo código. O resultado produziu 31 faixas de até um minuto e nove tendências. Os limites seguem o relógio monotônico: primeiro e último períodos podem ser parciais. Isso não é uma nova medição de consumo durante 30 minutos.

## Cargas reais curtas nesta máquina

| Carga | Configuração | Resultado |
|---|---|---|
| CPU | 2 s, um processo, orçamento de 25% | 216 verificações conhecidas, zero divergências; duração total 2,31 s. |
| RAM | 2 s, 16 MiB, orçamento de 25% | 149 blocos de 1 MiB verificados, zero divergências; duração total 2,18 s. |
| GPU | 3 s, OpenGL 3.2, 960×540, orçamento de 25% | 74 quadros, encerramento normal; sem verificação de artefatos. |

Esses testes validam funcionamento, não estabilidade prolongada nem capacidade máxima. Não foi iniciado automaticamente um teste longo em carga total.

A primeira implementação GPU identificou o adaptador, mas falhou na chamada de uniform do binding Qt. O caminho foi simplificado e a renderização foi repetida com sucesso. Falhas não foram contadas como resultado válido.

## Fluxo integrado

A interface iniciou uma sessão CPU curta com linha de base e recuperação. O gravador salvou 28 amostras e o auxiliar completou 319 verificações em cerca de 3,20 s, com zero divergências.

A análise separou 11 amostras antes, sete durante e dez após a carga. Nenhum marcador sintético foi criado. A análise abriu automaticamente após finalizar a gravação. A contagem pode variar conforme agendamento e cadência.

## Proteções e limites

O controle valida duração, processos, intensidade e memória antes de iniciar. A memória solicitada não pode exceder 25% da disponível, com máximo de 4 GiB. Parada manual, perda de monitoramento, pouca RAM e temperaturas configuradas são tratadas pela interface. A parada térmica depende de dados frescos; N/D não é interpretado como frio.

Um servidor/modelo de IA não é iniciado pelo teste. A exclusão de atividades impede outras capturas e inferência enquanto a sessão está ativa. O auxiliar monitora a existência do processo pai e tem prazo próprio. A aplicação encerra somente seus auxiliares.

CPU usa uma operação criptográfica com resultado conhecido. RAM verifica memória virtual alocada, não toda a memória física. GPU verifica a execução/renderização e erros OpenGL disponíveis, sem detector de artefatos ou teste completo de VRAM. Um teste concluído não declara hardware saudável.

## Regressões e pacote

162 testes passaram no Windows, incluindo períodos de carga, sensores em cache, fases, cancelamento antes de iniciar, mudança de provedor/modelo e referências/unidades da IA.

O validador de pacotes agora também executa auxiliares CPU e RAM por dois segundos, com um processo e 16 MiB, no executável congelado. A GPU requer contexto gráfico real e foi validada nesta máquina pelo caminho descrito acima; runners sem GPU não servem como prova desse teste.

A instalação local preexistente é preservada pelo validador. Instalação/desinstalação em pasta personalizada é conferida pelos ambientes limpos de CI.

Resultados locais completos ficam em diagnosticos/validacao-estresse, fora do Git.

## Executável final e ambientes nativos

O auxiliar GPU também foi executado no pacote Windows 3.1: três segundos, orçamento de 25%, 78 quadros, código de saída zero e encerramento por duração. Não houve teste prolongado nem detecção de artefatos.

A rodada [41336734423](https://github.com/Kennedh/sys-pulse/actions/runs/41336734423) validou a tag 3.1.0:

| Ambiente | Testes | Verificação do pacote |
|---|---|---|
| Windows x64 | 162 passaram | Abertura, auxiliares CPU/RAM, instalação e remoção em pasta personalizada |
| Ubuntu 22.04 x64 | 161 passaram, um exclusivo de Windows não aplicável | Abertura, auxiliares CPU/RAM, instalação e remoção |
| macOS 15 Intel | 161 passaram, um exclusivo de Windows não aplicável | PKG, DMG, abertura e auxiliares CPU/RAM |
| macOS 15 Apple Silicon | 161 passaram, um exclusivo de Windows não aplicável | PKG, DMG, abertura e auxiliares CPU/RAM |

Esses testes de pacote usaram cargas CPU/RAM de dois segundos, um processo e 16 MiB. A validação gráfica real foi feita nesta máquina Windows; os runners não demonstram desempenho GPU em outras placas.
