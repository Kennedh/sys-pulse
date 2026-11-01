# SysPulse 2.1 — análise técnica e mudanças

> Histórico técnico da versão 2.1. As adições de ETL, elevação e explicação da versão 2.2 estão em [análise avançada](analise-avancada.md). Os limites da tabela abaixo descrevem a 2.1.

Referências consultadas em 28/10/2026. A comparação usa capacidades descritas pelos fabricantes e documentação das APIs, sem ranking comercial, benchmark entre produtos ou alegação de equivalência.

## Referências e aplicação no projeto

| Referência | Capacidade documentada | Aplicação no SysPulse 2.1 | Limite desta entrega |
|---|---|---|---|
| [HWiNFO](https://www.hwinfo.com/about-software/) | Inventário, monitoramento e relatórios | Inventário pontual com origem, horário, disponibilidade e exportação; estatísticas por dispositivo | Sem o alcance de sensores de baixo nível, alertas configuráveis ou interfaces de integração do HWiNFO |
| [HWMonitor](https://www.cpuid.com/softwares/hwmonitor.html) | Temperatura, tensão, potência, clocks e ventilação | Mínimo/média/máximo das leituras NVML, psutil e LibreHardwareMonitor disponíveis; IOPS e latência por disco | Depende das fontes existentes; não adiciona driver próprio de acesso ao hardware |
| [LatencyMon](https://resplendence.com/latencymon) | Tempos de execução DPC/ISR e hard pagefaults | Separação explícita entre utilização de CPU em DPC e latência por driver; orientação de investigação | Não mede execução DPC/ISR por arquivo `.sys`, latência interrupt-to-process ou frametime |
| [WPA: análise de CPU](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/cpu-analysis) | Correlação temporal de eventos e DPC/ISR | Horários, contexto e próximos passos sem concluir causalidade apenas pela coincidência | Sem decodificação/importação de ETL |

## O que foi preservado

- Aplicativo desktop Python/PySide6, com a navegação e o tema existentes.
- Módulos pequenos separados entre coleta, cálculo e apresentação, seguindo a divisão já utilizada.
- Dicionários para amostras e funções diretas, sem adicionar um framework ou uma camada de serviços genérica.
- Threads para operações de coleta e sinais do Qt para atualizar a interface.
- Sessões em JSONL/CSV, análise independente da interface e relatórios TXT/JSON.
- Nomes e contratos existentes; os novos campos são aditivos no formato de captura 2. O relatório estruturado passa a `analysis_version: 2`.
- Comentários restritos às regras pouco óbvias. Não foram inseridos comentários narrando o trabalho ou falando sobre o autor do código.

## Mudanças implementadas

### Drivers e dispositivos

`inspection.py` cruza [Win32_PnPEntity](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-pnpentity) e [Win32_PnPSignedDriver](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/whqlprov/win32-pnpsigneddriver) pelo DeviceID, ignorando diferença entre maiúsculas e minúsculas. Dispositivos sem correspondência na lista de drivers continuam visíveis, inclusive código 28.

O código PnP e a assinatura informada pelo WMI são evidências distintas. Código zero não prova que um driver é adequado, atual ou incapaz de causar travamentos. Código 22 e ausência/desconexão têm filtros próprios. A data do driver não é usada para classificá-lo como desatualizado.

`inspect_windows.ps1` concentra consultas somente de leitura. O processo usa `-NoProfile`, `-NonInteractive`, saída UTF-8 e timeout de 45 s. Não usa `shell=True`, elevação automática, bypass da política de execução ou downloads de drivers. Falhas por seção preservam os demais resultados; um timeout do processo torna a consulta inteira indisponível.

### Saúde e eventos

[Get-StorageReliabilityCounter](https://learn.microsoft.com/en-us/powershell/module/storage/get-storagereliabilitycounter) fornece os contadores que o dispositivo e o provedor suportam. Valores ausentes ficam N/D. Temperatura, desgaste e erros não corrigidos são exibidos com o contexto do disco; não são tratados como teste de integridade.

[Get-WinEvent / consulta de eventos](https://learn.microsoft.com/en-us/windows/win32/wes/consuming-events) filtra o log System por provedores relevantes, níveis 1/2/3 e últimas 24 h. São guardados até 100 eventos mais recentes desse recorte, com mensagens limitadas a 2.000 caracteres. A consulta usa XPath para não depender do registro local de todos os provedores listados. Ausência de correspondências é diferente de falha de acesso.

### Estatísticas e interpretação

`assessment.py` acrescenta P95, duração observada de carga alta e sequência máxima. Dado ausente, lacuna e mudança do dispositivo dominante quebram a sequência. A duração não inclui o intervalo anterior à primeira leitura nem extrapola a última. CPU, RAM e DPC usam os tempos de amostragem; GPU/VRAM usam o horário da leitura de sensores, quando disponível.

A indicação de persistência exige cinco segundos observados. É uma escolha de triagem documentada, sem pretensão de ser um limite técnico universal. As sugestões apontam o próximo dado a conferir; não condenam hardware ou driver.

As estatísticas por dispositivo incluem temperatura, frequência, uso de GPU, potência, VRAM, atividade/latência/taxa/fila/IOPS de disco, RAM disponível, leituras de páginas e custo da coleta. Sensores adicionais de tensão, corrente e ventilação aparecem quando fornecidos pelo LibreHardwareMonitor.

P95 usa leituras válidas, ordenadas, com posição `ceil(0,95 × n)`. Mínimo/média/máximo não incluem dados vencidos de sensores. Há um limite de 512 séries de telemetria, com aviso no relatório se excedido. Na visão geral legada, as médias continuam sendo médias de snapshots; portanto, podem diferir da triagem com cache deduplicado.

### Precisão e ciclo de gravação

- Conforme a [documentação do psutil](https://psutil.readthedocs.io/stable/), a primeira leitura não bloqueante de CPU de processo não tem base comparativa. Agora fica N/D, inclusive após reutilização de PID.
- IOPS usa a diferença do número de operações dividida pelo intervalo real. Sem operação, a latência permanece N/D; contador reiniciado não produz taxa negativa.
- Resumos básicos de marcação usam PID, nome e criação, preservando identidades distintas.
- Inventário é anexado ao iniciar ou ao concluir uma consulta durante a gravação. A notificação de início também trata a conclusão antecipada da consulta, evitando perder o inventário na corrida entre threads.
- Capturas antigas sem inventário continuam abrindo, com aviso. Inventário inválido não elimina as amostras válidas.

## Verificação realizada

50 testes automatizados passaram. A captura real de verificação produziu 11 amostras, uma marcação e 133 séries de telemetria neste ambiente Linux, sem erro informado pelo coletor. Esses números descrevem o ambiente de teste; a disponibilidade no computador de destino será diferente.

- Testes de P95, lacunas, carga persistente, pico isolado, troca de dispositivo e sensores em cache.
- Testes de driver antigo, assinatura ausente, dispositivo desconectado, falha, timeout e suporte de plataforma.
- Testes de gravação/importação/exportação com inventário e sessão antiga sem inventário.
- Teste Qt de filtro de drivers e conclusão do inventário durante a inicialização do gravador.
- Testes anteriores de gravação, janelas, ZIP, contadores e processos preservados.
- Fluxo de coleta real em Linux, marcação, encerramento, análise automática e geração dos relatórios.
- Renderização e revisão visual das telas com dados simulados.

As consultas Windows foram verificadas por contrato e testes com respostas simuladas. A execução nativa de PowerShell/CIM/Storage/Event Log e PDH não foi validada neste ambiente Linux. Isso é uma limitação da validação, não evidência de funcionamento em todo computador Windows.

## Roteiro para validar no Windows

1. Execute `python -m pytest -q` no ambiente virtual e depois `python main.py`.
2. Aguarde a consulta de Drivers e saúde. Compare placa de vídeo e adaptador de rede com **Gerenciador de Dispositivos → Propriedades → Driver**. Confira nome, fornecedor, versão, data e código PnP.
3. Confira um dispositivo já desativado/desconectado, se existir. Não é necessário desativar nenhum dispositivo para testar.
4. Compare discos com `Get-PhysicalDisk` e os contadores com `Get-PhysicalDisk | Get-StorageReliabilityCounter`. Uma consulta negada/sem suporte deve aparecer como indisponível.
5. Compare um evento retornado com o Visualizador de Eventos, pelo provedor, ID e horário. Observe o recorte de 24 h e o limite de 100 ocorrências.
6. Grave uma tarefa habitual por 30–60 s, marque um sintoma, aguarde pelo menos 5 s e encerre. Confirme a abertura automática da análise.
7. Confira `inventario.json`, `amostras.jsonl`, `analise.json` e `analise.txt`. Abra novamente a pasta e um ZIP contendo essa única sessão.
8. Confira os sensores com a mesma fonte usada para coletar: NVML/LHM e contadores Windows. Cadências diferentes podem produzir picos distintos em outros aplicativos.
9. Se o objetivo for identificar latência por driver, obtenha uma captura específica no WPR/WPA ou LatencyMon. A lista de drivers do SysPulse não substitui essa medição.

## Cobertura ainda não implementada

Atribuição DPC/ISR por driver, análise ETL, FPS/frametime, SMART/NVMe completo, sensores próprios de baixo nível, rede por processo, catálogo confiável de versões de drivers e alertas configuráveis continuam fora desta versão. Essas capacidades exigem fontes e validação próprias; não foram simuladas como se já existissem.
