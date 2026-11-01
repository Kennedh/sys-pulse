# Revisão de produto, desempenho e diagnóstico do SysPulse

> Registro anterior à implementação 2.3. Consulte o [guia atual](../README.md) e a [validação 2.3](validacao-2.3.md) para recursos e testes desta entrega.

Data: 01/11/2026. Base revisada: commit 92edd60.

## Parecer

O SysPulse tem uma base organizada e útil para triagem, mas ainda não é um produto pronto para um leigo
instalar, iniciar uma tarefa de meia hora e receber uma explicação consistente do que limitou o desempenho.

A direção recomendada é torná-lo um assistente de investigação de desempenho geral: abrir um programa,
navegar, trabalhar, jogar, reproduzir vídeo ou investigar uma pausa. Frametime é essencial para a parte visual, mas não substitui a investigação de CPU, disco, memória,
drivers e conexão em outros cenários.

O principal ganho virá de capturar o evento relevante com baixo custo e explicá-lo com evidências.
Trocar o modelo de IA não resolve dados que não foram medidos.

Esta revisão inclui leitura de código, pesquisa em fontes oficiais, telas com dados simulados,
medição curta do aplicativo real e perfil da coleta. As funcionalidades sugeridas abaixo são propostas,
não uma nova implementação.

## Como funciona hoje

- A entrada main.py cria a aplicação PySide6 e a janela em gui.py.
- MonitorWorker coleta recursos em segundo plano; a varredura de processos tem uma thread própria.
- SensorService consulta NVML, sensores opcionais, rede e espaço de discos em outra thread.
- A interface consulta o último snapshot em um timer de 250 ms e limita atualização visual a aproximadamente 500 ms.
- SessionRecorder escreve snapshots em JSONL, métricas em CSV e relatórios separados.
- A análise nativa lê a sessão, agrega recursos/processos, compara marcações e produz explicação por regras.
- InspectionService consulta dispositivos, drivers, armazenamento e eventos via PowerShell.
- A captura avançada abre um auxiliar elevado, usa WPR GeneralProfile em arquivo e processa o ETL com Xperf.
- A análise ETL atual executa somente dpcisr e tracestats. Não é uma análise completa de tudo que o ETL contém.
- A IA recebe um resumo selecionado, mediante confirmação, e devolve texto complementar.

Fontes principais: gui.py; modules/monitor.py; modules/sensors.py; modules/diagnostics.py;
modules/analysis.py; modules/advanced_capture.py; modules/advanced_analysis.py; modules/ai_summary.py.

## Facilidade de manter e facilidade para o usuário

**Manutenção: moderada, com uma estrutura aproveitável.** Os módulos são pequenos, as responsabilidades
principais são reconhecíveis e não há dependência de um framework de aplicação complexo.
A revisão anterior deixou 86 testes aprovados. Isso ajuda a evolução, mas não valida todos os fluxos reais
de Windows, jogos, permissões e ferramentas externas.

O maior risco de manutenção está na coordenação: duas capturas, timers, filas, threads, sinais e arquivos
de controle. A janela principal também concentra navegação e apresentação de Hardware, Live Monitor e Rede.
Uma evolução deve manter o estilo atual e introduzir um coordenador simples da sessão, sem reescrita geral.
Extrair os widgets de Hardware/Rede/Monitor pode reduzir o tamanho de gui.py gradualmente.

**Para um leigo: ainda exige preparação técnica.** O fluxo de instalação requer Python, dependências e terminal.
Sensores adicionais exigem outro programa; ETL exige lidar com UAC e instalar o Windows Performance Toolkit;
IA exige identificar endpoint/modelo/chave. Não existe instalador pronto no repositório.

Melhorias propostas:

1. Executável/instalador Windows testado em uma máquina limpa, com atalho de abertura e mensagens úteis de erro.
2. Primeiro uso com verificação de fontes: básico disponível, sensores extras opcionais e captura detalhada opcional.
3. Abrir a visão geral com uma ação principal: Investigar lentidão.
4. Explicar o que pode ser medido antes de iniciar, e distinguir dado ausente de recurso saudável.
5. Deixar explícito que fechar minimiza para a bandeja e que Sair encerra a sessão.
6. Guardar preferências comuns; conexões de IA devem ter uma configuração central compartilhada.

## Hardware, Live Monitor e Rede

| Módulo | O que entrega | O que falta para ficar forte |
|---|---|---|
| Hardware | SO, CPU, placa-mãe/BIOS, núcleos, frequência reportada, RAM total e nomes de GPU | Modelo e configuração da RAM, armazenamento/partições identificáveis, VRAM, driver gráfico, tela/taxa de atualização, plano de energia e disponibilidade dos sensores. Exportação e atualização do resumo. |
| Live Monitor | CPU/RAM, maior núcleo, GPU/VRAM, atividade/latência/fila/IOPS de disco e processos | Histórico curto por recurso na própria tela, carga por núcleo, temperaturas/clocks/potência quando disponíveis, processo alvo, memória comprometida/limite, indicação de throttling quando a fonte informar e eventos de desempenho visual. |
| Rede | Tráfego agregado, total de bytes, interfaces IPv4 ativas e um ping a 8.8.8.8 | Histórico, adaptador selecionado, gateway, latência e variação, taxa de respostas/perdas ICMP identificada como tal, DNS e destino configurável. Hoje a análise não explica conexão a partir desses dados. |

Hardware é um inventário básico; Live Monitor é uma visão geral útil; Rede é um painel básico de tráfego.
Nenhum deles, isoladamente, está completo como diagnóstico de desempenho.

Pontos concretos:

- Hardware é carregado uma vez ao abrir a aba, sem uma ação de atualização/repetição clara.
- A maior parte de Hardware, Live Monitor e Rede é texto em caixas grandes; fica difícil comparar números.
- RAM ocupada não mede, sozinha, falta de memória. Clock reportado pelo SO não é clock efetivo.
- Temperatura sem informação de limite/throttling não comprova limitação térmica.
- Ping externo não é latência específica do aplicativo. Falha de ICMP também pode ser filtragem.
- Ainda não há FPS/frametime. Uma pausa de um quadro pode passar entre duas amostras de 500 ms.

## Visual e fluxo de captura

As telas foram renderizadas em 1366 × 768 com dados simulados. A identidade escura, cores e espaçamento são
coerentes. Captura apresenta seis botões e Avançado sete botões visíveis, sem contar a navegação.
Há ações inativas competindo com a ação principal e bastante vocabulário técnico já na entrada.

A tela Captura exige rolagem nessa altura; Live Monitor e Hardware têm grandes áreas de texto.
O tamanho padrão de 1340 × 900 também pede adaptação a monitores menores e escala de 125%/150%.
A renderização foi offscreen: não substitui avaliação presencial de foco, teclado, contraste,
DPI e movimento da janela.

Proposta de navegação: **Visão geral · Investigar · Sessões · Configurações**.
Detalhes de hardware, rede, processos e drivers podem ser páginas específicas acessíveis na visão geral.
Não é preciso esconder a profundidade técnica; ela deve aparecer quando for útil.

Fluxo proposto:

1. O que está ruim? Computador lento / Programa demora / Imagem engasga / Áudio corta / Conexão ruim.
2. Qual tarefa ou aplicativo? Opcional quando o sintoma é do sistema inteiro.
3. Modo: acompanhamento leve por 30–60 min ou investigação detalhada de um sintoma.
4. Antes de iniciar, mostrar fontes disponíveis, duração e orçamento de armazenamento.

Durante a sessão: **Iniciar**, depois **Marcar problema** e **Encerrar**.
Depois de encerrar: **Ver resultado**.
Pasta, exportação, abrir ETL e ferramentas externas ficam em Mais opções/Detalhes.
Configuração de intervalo, sensores e perfil avançado fica recolhida.

Um coordenador deve impedir combinações confusas de gravação nativa/avançada e tornar claro qual sessão
recebe cada marcação. Hoje os gravadores são independentes e a interface de cada um controla principalmente
o próprio estado.

## Consumo medido

Uma execução real curta, em Windows/Python 3.13.1 e 12 processadores lógicos, produziu:

| Fase | CPU média, normalizada pela máquina | RAM média RSS |
|---|---:|---:|
| Inicialização | 2,69% | 115,9 MiB |
| Live Monitor visível no renderizador | 1,73% | 116,6 MiB |
| Janela oculta | 1,66% | 116,8 MiB |
| Gravação nativa, janela oculta | 1,96% | 116,4 MiB |

O máximo de RAM na fase de gravação foi aproximadamente 117,1 MiB.
O custo médio do laço rápido foi 36,1 ms, com máximo de 141,2 ms.
O intervalo médio das amostras foi 501 ms e o maior 520 ms, para alvo de 500 ms.
A gravação produziu 29 amostras, nenhuma perda e nenhum aviso na análise.
As quatro seções do inventário Windows retornaram status ok nesta execução.

**Limites da medição:** fases sequenciais de 8–15 s, sem jogo, aplicação Qt offscreen e sem WPR ou modelo local.
A CPU medida é do processo Python, sem somar PowerShell, ping ou outros filhos.
A primeira medição usou a fonte padrão do ambiente offscreen; as imagens de avaliação foram depois renderizadas
com Segoe UI carregada explicitamente no renderizador.
CPU e fluidez devem ser repetidas com janela nativa, DPI real e a tarefa em execução.
Não houve teste de vazamento/estabilidade por 30 min nem comparação A/B de impacto em um jogo.
Os timers de auditoria também acrescentam um pequeno custo.

Conclusão: RAM moderada e coleta rápida estável nesse teste. O consumo de CPU ainda merece redução;
não se pode classificá-lo como impacto desprezível.

### Maior custo identificado

Três varreduras de aproximadamente 323 processos levaram 538–570 ms.
O perfil acumulou cerca de 1,53 s de 1,66 s no caminho nativo proc_info do psutil.
O código local do psutil confirma que cpu_times pode recorrer a esse caminho mais lento quando a consulta
normal encontra restrição de permissão. Os contadores GPU por PID levaram aproximadamente 1,7–2,4 ms
no teste separado.

A thread própria evita bloquear as métricas rápidas, mas não remove o trabalho nem a disputa por CPU.

Prioridades de otimização:

- Avaliar coleta Windows em lote para tempos de CPU, evitando repetir consultas caras por PID.
- Cadência adaptativa: processo alvo mais frequente; varredura ampla menos frequente, com lacunas declaradas.
- Quando houver alvo, preservá-lo sempre na sessão, mesmo se não entrar no top 10.
- Reaproveitar snapshots e atualizar apenas o que mudou.
- Reduzir atualização de gráficos invisíveis: o histórico deve continuar sendo mantido, sem solicitar pintura.
- Medir CPU com 50/200/500 processos, diferentes GPUs e máquina mais fraca.
- Analisar custo do início de captura, que hoje solicita atualização do inventário novamente.

## Tamanho dos arquivos e sessões longas

A gravação nativa de 29 amostras produziu 237.751 bytes em JSONL: aproximadamente 8,2 kB por amostra.
A extrapolação por quantidade de amostras daria cerca de **28,1 MiB de JSONL em 30 min a 500 ms**,
mais CSV, inventário e relatórios. Com 250 ms, esse componente aproximadamente dobra.
É uma estimativa de uma sessão curta; mais processos/sensores alteram o tamanho.

Compressão gzip em memória dessa amostra:

- Nível 1: 26.958 bytes, redução de 88,7%.
- Nível 6: 16.742 bytes, redução de 93,0%.

Esses percentuais são da amostra, não uma garantia para sessões longas ou ETL.
O gravador atual não usa essa compressão.

Proposta: JSONL comprimido em blocos/segmentos, exportação CSV sob demanda e snapshots de processos/sensores
armazenados uma vez por atualização, em vez de repetidos em cada amostra.
Isso exige compatibilidade de leitura e recuperação após interrupção. Não apagar dados automaticamente
para esconder crescimento do arquivo.

O limite atual da gravação nativa é 256 MiB de JSONL ou duas horas. Meia hora cabe por duração,
mas depende do volume. A importação aceita até 512 MiB/120.000 linhas e há limites adicionais por linha.

### ETL: o problema maior

O ETL já existente tem **725.614.592 bytes, aproximadamente 692 MiB**, para 67,17 s reportados.
Uma extrapolação linear dessa taxa daria **18,1 GiB em 30 min**.
A pasta toda ocupa cerca de 793 MiB, contando relatórios e símbolos.
Não é previsão do tamanho de uma próxima captura.

O fluxo atual limita duração a 180 s e solicita parada com aproximadamente 1 GiB de ETLs temporários
ou menos de 1 GiB livre. O analisador rejeita ETL acima de 4 GiB e cada execução Xperf tem timeout de 3 min.
Portanto, mudar somente a duração na interface não resolve meia hora.

A [documentação Microsoft de logging](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/logging-mode)
distingue arquivo sequencial de buffers circulares em memória. O buffer mantém os eventos recentes:
a janela temporal depende da taxa de eventos, não apenas de uma quantidade fixa de segundos.

Estratégia proposta:

| Modo | Durante toda a tarefa | Detalhe ETW | Limitação |
|---|---|---|---|
| Acompanhamento longo | Telemetria e eventos do aplicativo; frametimes quando o sintoma é visual | Opcional | Não preserva todos os eventos internos do Windows |
| Sintoma imprevisível | Telemetria contínua | WPR circular em memória, orçamento configurado | Eventos antigos são sobrescritos; salvar ao detectar/marcar exige coordenação e tempo |
| Investigação profunda | Mesmo contexto da tarefa | Perfil focado e captura curta em arquivo | Maior custo e volume |
| Histórico ETW completo longo | Contexto contínuo | Perfil leve, validado, com orçamento e eventualmente segmentos | Continua custando CPU/disco; segmentação pode criar lacunas e fragmentar a análise |

Para vários sintomas, salvar uma janela circular ao final só preserva os últimos eventos.
É necessário preservar janelas relevantes quando acontecem, registrar pausas de salvamento/rearme e limitar
o custo disso. Manter o sistema inteiro detalhado por 30 min é uma escolha diferente de manter a visão geral
por 30 min.

A Microsoft também documenta perfis light e a opção de saída comprimida
[WPR -compress](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/wpr-command-line-options).
Isso reduz o arquivo final; não elimina automaticamente o custo nem o volume dos temporários.
Perfis precisam ser validados contra os eventos exigidos pelo analisador.

## Referências de ferramentas e método de investigação

Não existe uma ferramenta universal nem um ranking que prove qual identifica toda causa.

| Ferramenta | Para que serve no diagnóstico | O que aproveitar no SysPulse |
|---|---|---|
| [WPR/WPA](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/introduction-to-wpr) | Rastrear e investigar CPU, threads e recursos em um período | Perfis por sintoma e análise temporal |
| [GPUView](https://learn.microsoft.com/en-us/windows-hardware/drivers/display/using-gpuview) | Investigar eventos e atividade CPU/GPU de ETL | Detalhamento da fila e esperas gráficas quando necessário |
| [PresentMon](https://github.com/GameTechDev/PresentMon/blob/main/README-ConsoleApplication.md) | Capturar dados de apresentação por aplicativo e exportar CSV; pode analisar ETL compatível | Fonte de frametime por processo e relógio comum, sem armazenar um ETL geral inteiro |
| [CapFrameX](https://www.capframex.com/features) | Análise de frametimes, sensores e comparação de execuções | Linha do tempo, comparação A/B e métricas com definição explícita |
| [HWiNFO](https://www.hwinfo.com/about-software/) | Inventário e acompanhamento amplo de sensores | Fontes, mínimos/máximos, histórico e exportação |
| [LatencyMon](https://www.resplendence.com/latencymon.htm) | Investigar tarefas sensíveis a tempo, DPC/ISR e hard faults | Métricas específicas de latência; não tratar percentual DPC como equivalente |
| [Process Monitor](https://learn.microsoft.com/en-us/sysinternals/downloads/procmon) | Investigar operações de arquivos/registro e processos com filtros | Aprofundar uma hipótese específica, sem coletar tudo continuamente |
| [OCCT](https://ocbase.com/occt/pro) | Testes controlados de estabilidade de componentes | Etapa de validação de uma suspeita, separada da sessão normal |
| [MemTest86](https://www.memtest86.com/troubleshooting.htm) | Investigar erros no subsistema de memória | Teste específico quando houver evidência; erro não identifica automaticamente um pente |

Um exemplo concreto de uso especializado é o
[roteiro NVIDIA para baixo FPS/stutter com GPUView](https://nvidia.custhelp.com/app/answers/detail/a_id/3507/kw/windows%2010).
A lição é preservar a janela do problema e sua atividade gráfica, não concluir por um ranking global de drivers.

Método a incorporar:

1. Definir o sintoma e a tarefa, sem começar presumindo componente defeituoso.
2. Registrar uma linha de base e marcar o evento percebido.
3. Encontrar o evento relevante: demora de operação, quadro atrasado, espera de thread, I/O lento ou falha observada.
4. Conferir o que estava ocorrendo no mesmo intervalo, com relógios alinhados e qualidade declarada.
5. Formular hipótese e indicar a evidência a favor, contra e ausente.
6. Alterar uma variável e comparar tarefas semelhantes.
7. Usar teste de componente apenas quando a hipótese justificar.

## Para melhorar a análise de verdade

A análise ETL atual precisa ir além de DPC/ISR agregados:

- CPU: threads do aplicativo, execução, tempo pronto e espera, quando os eventos permitirem.
- Memória: comprometimento/limite, memória disponível, hard faults e tempo de atendimento por processo.
- Disco: operações, duração e fila, identificando arquivo/processo quando disponível e apropriado.
- Gráficos: quadros apresentados, intervalos anormais, apresentação e trabalho CPU/GPU conforme a fonte.
- Sensores: temperatura, clock efetivo e flags de limitação de potência/térmica quando a fonte expuser.
- Eventos: WHEA, resets de driver e armazenamento filtrados pela sessão, não apenas pelo dia.
- Rede: analisada quando o sintoma pedir, com medição de conexão separada de problema de renderização.

Um relógio monotônico/QPC comum deve relacionar marcações, telemetria e eventos externos.
Hoje esse alinhamento exato não existe. Importar frametimes não autoriza atribuir automaticamente cada pico
a um driver ou a um processo.

Cada achado deveria mostrar: **o que aconteceu, quando, impacto medido, evidências, qualidade,
hipótese, o que ainda falta e próximo teste**. Percentuais de confiança inventados devem ser evitados.
Uma conclusão forte exige validação adicional; causa indeterminada deve continuar sendo um resultado válido.

Para quadros, usar frametime mediano/P95/P99 e contagem/duração dos eventos, com orçamento e limiar definidos.
Um alvo de 60 FPS tem orçamento de aproximadamente 16,7 ms por quadro; 144 FPS, 6,9 ms.
VSync/limitador, múltiplas swapchains, minimização e troca de aplicativo devem ser tratados para não criar
falsos sintomas. A API disponível no jogo também precisa de validação real.

Uma captura de 30 min a 144 FPS pode produzir cerca de 259 mil quadros.
Esse fluxo não deve ser simplesmente colocado no atual JSONL de recursos, que limita a importação a 120 mil linhas.

## IA: acesso, qualidade e poucos tokens

### Padrão e serviços

GPT sem autenticação não é um padrão viável da API pública.
A [OpenAI documenta credenciais e proteção das chaves](https://developers.openai.com/api/reference/overview).
Para dispensar conta própria do usuário em uma integração de nuvem, seria necessário um backend do SysPulse
que autentica no provedor, custeia o uso e controla cota/abuso. A chave compartilhada não deve ser distribuída
dentro do executável.

O padrão imediato continua sendo a explicação local por regras.
IA externa ou local entra depois da medição, preservando a análise quando não houver conexão.

| Opção | Vantagem para o projeto | Condição |
|---|---|---|
| [Gemini](https://ai.google.dev/gemini-api/docs/openai) | Candidato de nuvem para avaliar qualidade/custo; há endpoint compatível | Chave e acesso ao modelo; não foi testado no SysPulse |
| [Faixa gratuita do Gemini](https://ai.google.dev/gemini-api/docs/pricing) | Pode servir para experimentação em modelos elegíveis | Limites, disponibilidade e política de dados; não equivale a gratuidade irrestrita |
| [Ollama local](https://docs.ollama.com/api/authentication) | API local sem autenticação para modelos locais | Instalação e modelo; usa CPU/RAM/GPU; nuvem do Ollama tem outras condições |
| [LM Studio](https://lmstudio.ai/docs/developer/core/server) | Interface para servir modelos locais e APIs compatíveis | Instalar/configurar servidor e modelo; medir custo no PC |
| [OpenRouter](https://openrouter.ai/collections/free-models) | Acesso a opções de modelos gratuitos e pagos | Chave, limites e condições do modelo/provedor |
| [OpenAI](https://developers.openai.com/api/docs/models) | Alternativa de nuvem com opções de custo/capacidade | Credenciais e cobrança/condições aplicáveis |

Não há modelo “melhor para tudo” demonstrado para este projeto.
A proposta é avaliar um Gemini de custo baixo, um modelo local e uma opção OpenAI com os mesmos casos.
O vencedor padrão deve ser decidido por fidelidade às evidências, clareza em português, custo, latência
e comportamento quando faltam dados, não por popularidade ou tamanho.

### Problemas do resumo atual

Na sessão curta, o JSON atual teve 2.263 bytes formatado ou 1.620 bytes compacto.
Bytes não equivalem a tokens; a contagem depende do modelo e precisa ser obtida por tokenizer/usage.

O envio já seleciona agregados e evita dados pessoais importantes, o que é uma boa base.
Porém, não envia a telemetria detalhada de latência por disco, contexto de sensores nem todos os achados
que a própria análise local produziu. Também não oferece contagem de tokens/custo na interface.
O código usa um formato Chat Completions específico, sem detecção de capacidades do provedor.

O alvo é **analisar todos os dados necessários localmente e enviar somente evidências relevantes**.
Comprimir o arquivo ou renomear campos arbitrariamente não resolve tokenização nem falta de contexto.

Proposta de contrato compacto:

- Perfil da tarefa e capacidades realmente disponíveis.
- Qualidade: perdas, lacunas, alinhamento e fontes ausentes.
- Principais incidentes com tempos relativos, tipo e impacto.
- Evidências identificadas por E1/E2 etc., unidades e comparação com a linha de base.
- Achados locais e evidências que contradizem cada hipótese.
- Contexto mínimo de hardware necessário para interpretar a medição, com seleção explícita de dados.
- Lista curta de próximos testes possíveis, sem execução automática.

O modelo deve responder com hipótese, IDs das evidências usadas, dado ausente e próximo teste.
A aplicação valida o formato e rejeita referência a evidência inexistente.
A IA não deve afirmar integridade física, inventar medições nem substituir evidência por texto convincente.

Para custo: uma chamada ao final, limite de entrada/saída, resposta curta por padrão, cache por hash da análise
e instruções estáveis. Consultas adicionais enviam somente o contexto necessário.
A [documentação OpenAI de otimização](https://developers.openai.com/api/docs/guides/cost-optimization)
recomenda reduzir pedidos/tokens e avaliar modelos menores.
Compatibilidade, nomes de parâmetros e uso reportado devem ser tratados por adaptador de serviço.
Não foi feito envio externo nesta revisão.

### Configuração simples da própria IA

Uma única tela em Configurações:

1. Serviço: Local / Gemini / OpenAI / OpenRouter / Personalizado.
2. Para nuvem, colar a chave; para local, detectar servidor.
3. Mostrar modelos disponíveis quando houver API para listagem, com escolha manual como alternativa.
4. Testar conexão com uma solicitação mínima e informar quando isso pode consumir cota.
5. Mostrar resumo legível do que será enviado, estimativa de tamanho e destino.
6. Salvar preferências; chave persistida somente por opção e no cofre do sistema operacional.

Endpoint e parâmetros avançados ficam recolhidos.
A configuração deve ser compartilhada pelas análises nativa e avançada.
Compatível com OpenAI não significa que todos os parâmetros/modelos funcionarão sem adaptação.
Inferência local fica suspensa ou adiada durante a captura, salvo escolha explícita com impacto informado.

## Ordem de evolução e critérios de aceite

| Etapa | Entrega | Como validar |
|---|---|---|
| 1 | Captura única e acompanhamento longo leve, orçamento de tamanho e exportação organizada | Sessão real de 30–60 min, recuperação após interrupção, perdas/espaço exibidos, sem dois modos conflitantes |
| 2 | Motor de incidentes e fontes por sintoma; frametime para tarefas gráficas, esperas/IO para demais tarefas | Confrontar mesmos eventos com WPA/PresentMon e casos de controle sem sintoma |
| 3 | Coleta de processos mais barata, armazenamento compacto e interface com ações por estado | Perfis CPU/RAM em máquinas/cargas distintas, comparação A/B com monitor desligado |
| 4 | Configuração guiada de IA e contrato de evidências, com avaliações de modelos | Sem dados inventados, referências válidas, resposta clara, custo/uso visíveis e falha sem bloquear análise |
| 5 | Empacotamento Windows, primeiro uso e acessibilidade | Instalação limpa por leigo, 1366×768/1080p, 100/125/150% DPI e navegação por teclado |

Antes de chamar o produto de leve ou a análise de confiável, manter testes reais de referência:
capturas com e sem sintoma; mesmo aplicativo/configuração; métricas documentadas; erro permitido para valores
confrontados com as ferramentas; impacto no desempenho medido; sessões longas e interrupções.

## Artefatos desta revisão

Em diagnosticos/revisao-20261101, ignorado pelo Git:

- perfil.json: consumo do processo e cadência observada.
- processos-profile.txt e detalhes.json: perfil das consultas e tamanho do resumo de IA.
- tamanhos.json: extrapolações e experimento de compressão.
- hardware.png, live.png, rede.png, captura.png e avancado.png: telas simuladas.
- medicao/: sessão nativa real curta, com inventário local.

Os dados locais dessa pasta não foram publicados. O relatório não contém nomes de processos reais, IPs
ou o inventário completo. Nenhum teste de estresse de hardware, nova captura WPR ou chamada real de IA
foi executado. A suíte anterior não foi repetida: os fontes da aplicação não foram alterados nesta auditoria.
