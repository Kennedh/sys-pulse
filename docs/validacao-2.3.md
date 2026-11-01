# Validação do SysPulse 2.3

Validação realizada no Windows desta máquina em 01/11/2026, com Python 3.13.1, 12 CPUs lógicas e ambiente local do projeto. Os resultados descrevem essas execuções, sem garantir o mesmo custo em todo hardware ou tarefa.

## Captura nativa por 30 minutos

Execução real de coleta, gravação comprimida, encerramento e análise automática. A janela ficou em modo offscreen. O Ollama não tinha modelos carregados no início e a sessão não solicitou inferência.

| Medida | Resultado |
|---|---:|
| Duração configurada | 1.800 s |
| Amostras gravadas | 3.600 |
| Amostras perdidas na fila | 0 |
| CPU média do processo / capacidade total | 0,164% |
| CPU máxima / capacidade total | 0,782% |
| RSS médio / máximo | 119,70 / 123,08 MiB |
| Coleta média / máxima | 19,13 / 70,41 ms |
| Intervalo médio / máximo | 499,90 / 536,83 ms |
| amostras.jsonl.gz | 3.208.864 bytes, 3,06 MiB |
| Todos os arquivos, incluindo relatórios | 4.004.183 bytes, 3,82 MiB |
| Análise automática | Concluída, sem avisos |

Resultado local: diagnosticos/teste-implementacao/20261101-105237/benchmark.json.

A CPU foi normalizada pelas 12 CPUs lógicas e mede somente o processo Python observado, sem filhos. O relatório original usa a frase resumida “Sem jogo, WPR ou inferência de IA”: ela descreve o modo dessa sessão. Ferramentas de desenvolvimento e testes curtos de gráficos/WPR rodaram em outros processos durante parte do período. Não foi um ensaio de máquina ociosa controlada nem um comparativo de FPS com e sem SysPulse. A sessão longa começou antes dos últimos ajustes da interface; os ajustes finais receberam validação separada.

## Janela nativa visível

Execução curta de 30 segundos, com a interface nativa renderizada e a mesma gravação leve.

| Medida | Resultado |
|---|---:|
| Amostras / perdidas | 61 / 0 |
| CPU média / máxima normalizada | 0,479% / 1,313% |
| RSS médio / máximo | 137,01 / 138,45 MiB |
| Coleta média / máxima | 19,27 / 22,64 ms |
| Intervalo médio / máximo | 500,44 / 514,06 ms |
| Amostras comprimidas | 60.062 bytes |
| Análise / inferência | Concluída / não iniciada |

Resultado local: diagnosticos/teste-visivel/20261101-112611/benchmark.json. Esse teste complementa a execução longa; não transforma os 30 minutos em uma medição de renderização contínua da janela.

A consulta de processos agrupada também foi comparada à leitura anterior: aproximadamente 328 processos em 9,8 ms, contra cerca de 550 ms no caminho anterior observado. A criação e o tempo de CPU do próprio processo foram conferidos contra psutil. A API nativa tem fallback porque seu formato depende do Windows.

## Captura circular real

O auxiliar solicitou UAC, iniciou uma instância própria do WPR com perfil validado e encerrou após uma marcação de teste mais cinco segundos. Nenhuma outra instância foi encerrada.

- Duração: 9,52 s.
- ETL: 14.158.692 bytes, aproximadamente 13,50 MiB.
- Xperf: 21 entradas de tipo/módulo DPC/ISR, 253 processos, 1.413 threads, 104 arquivos com I/O e nove processos com hard faults.
- Estatísticas informaram zero eventos e zero buffers perdidos.

Os contadores são cobertura de leitura, não indicação de defeito. A análise final avisa que a memória circular pode ter sobrescrito eventos antigos. A memória do perfil é aproximadamente 128 MiB para buffers do kernel; tamanho de ETL não cresce como uma gravação contínua ilimitada.

Uma captura ETL anterior também foi processada para conferir os parsers contra saídas reais do Xperf. As capturas e seus nomes de processos/caminhos continuam locais e ignorados pelo Git.

## Quadros reais

A ferramenta tools/validate_graphics.py criou uma janela D3D11 própria, com apresentação aproximadamente a cada 16 ms e uma pausa sintética de 200 ms.

O PresentMon em modo mínimo registrou 530 quadros válidos, mediana de 15,7829 ms, P99 de 30,9887 ms e três intervalos classificados como longos. O máximo de 1.174,6643 ms inclui condições de inicialização; não foi atribuído à pausa sintética de 200 ms.

O modo detalhado de GPU/display não produziu dados úteis neste ambiente. A integração usa o modo mínimo que funcionou, com métricas indisponíveis explicitamente N/D. Esse teste não mede impacto em FPS num jogo nem latência efetivamente exibida.

A leitura de frametimes comprimidos, separação por swapchain, limites e associação QPC/monotônico aos recursos foram verificadas também por testes automatizados.

PresentMon 2.6.0 obtido da distribuição oficial, assinatura Authenticode válida. SHA-256 do executável local:
b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af

## Llama local e contrato de análise

O modelo llama3.2:3b foi instalado no Ollama e executado somente depois das capturas. Na investigação do formato de resposta, texto livre trocou unidades e inventou interpretações; por isso a integração final aceita apenas a priorização de IDs de evidências reconhecidas.

No teste final com um candidato sintético de CPU, a resposta válida levou aproximadamente 3,66 s e informou 298 tokens de entrada e 24 de saída. O software apresentou os valores originais de CPU, incluindo o máximo de 98%, sem aceitar números escritos pelo modelo.

Durante a análise, o Ollama informou cerca de 3,12 GB decimais de VRAM para o modelo. Após a chamada, a listagem de modelos carregados ficou vazia, conforme keep_alive=0. Sem candidatos, a integração final retorna a explicação local sem solicitar inferência.

Esse resultado confirma conexão, formato e descarregamento nesse caso. Não comprova precisão universal do Llama ou de outros modelos. A validação por IDs e unidades, o limite de entrada/saída e o bloqueio durante gravações continuam necessários.

O download do modelo ocupa aproximadamente 2 GB em disco e permanece no armazenamento do Ollama, separado do projeto e do pacote portátil.

Nenhuma chamada remota foi realizada porque não havia chave configurada. Gemini, OpenRouter, OpenAI e serviços compatíveis têm presets e transporte testados com respostas controladas; uma validação real depende da chave e do modelo disponíveis na conta.

## Interface, regressões e distribuição

Os prints foram gerados pela aplicação real com a sessão simulada e revisados visualmente. A navegação principal reúne Visão geral, Investigar, Sessões e Configurações; hardware, rede e drivers permanecem acessíveis.

A suíte final passou com **120 testes** e cobre gravação/compressão, importação, exportação CSV, processos, cadência, marcações, frametimes, parsers ETL, ciclo de captura, erros, credenciais e contrato da IA. O ciclo de vida usa uma QApplication compartilhada nos testes para evitar destruição repetida do Qt no Windows.

O pacote portátil inclui a aplicação, dependências, dados simulados, auxiliar PowerShell, ícone e PresentMon com licença quando presente no build. Não inclui capturas reais, credenciais ou modelos.

O build final encerrou com código zero. O executável abriu em demonstração e encerrou automaticamente com código zero em 4,40 s. A verificação de integridade do ZIP passou, com 222 entradas e nenhum arquivo obrigatório ausente. O pacote final ocupa 48.003.277 bytes, aproximadamente 45,78 MiB.

O primeiro teste do pacote encontrou um arquivo da demonstração referenciado na pasta de testes. O arquivo passou para examples/sessao-demo, com referências corrigidas e nova execução completa do build e do teste de abertura.

A consulta real de hardware retornou placa-mãe, BIOS, velocidade dos módulos de RAM, driver gráfico, atualização informada e plano de energia, sem campos N/D no relatório dessa execução. Isso não garante disponibilidade em outro hardware.

Os arquivos gerados ficam em dist e os logs de validação em diagnosticos; ambos são ignorados pelo Git. O smoke test valida abertura e encerramento do pacote em demonstração. As medições longas, WPR, gráficos e IA foram feitas pelo ambiente Python do projeto nesta máquina.

## Próxima validação de campo

Para medir interferência em uma tarefa real, execute a mesma cena com e sem captura, preservando resolução, limite de FPS, plano de energia e programas em segundo plano. Repita cada condição. Compare frametimes e consumo, além dos percentis.

Para investigar uma pausa concreta, selecione o processo correto, marque o sintoma e confira a cobertura. Se a hipótese depender de uma espera de thread, pilha ou componente de driver, aprofunde no WPA. Uma correlação de recursos não encerra essa investigação.
