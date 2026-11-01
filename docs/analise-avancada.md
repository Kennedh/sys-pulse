# SysPulse 2.2 — análise explicada e captura avançada

> Registro anterior à implementação 2.3. Consulte o [guia atual](../README.md) e a [validação 2.3](validacao-2.3.md) para recursos e testes desta entrega.

## O que o usuário recebe

**Entenda o resultado** é a primeira aba da análise. Cada evidência tem uma descrição da medição, seu significado e um próximo teste. O cálculo e a explicação são locais: não precisam de internet, conta, chave ou modelo de linguagem.

A explicação distingue carga alta de defeito. Por exemplo, um núcleo ocupado pode limitar uma tarefa mesmo com CPU total baixa; um disco muito ocupado exige conferir latência e fila; RAM ocupada também pode incluir caches. O nome do processo observado perto do pico é contexto, sem atribuição automática da causa.

No modo avançado, o relatório acrescenta atividade DPC/ISR dos módulos reconhecidos e sinaliza módulos desconhecidos, histograma incompleto e estatísticas indisponíveis. DPC/ISR são rotinas relacionadas ao atendimento de eventos dos dispositivos. Tempo acumulado soma várias execuções; não equivale à duração de uma travada.

Nenhuma dessas medições comprova, sozinha, defeito de uma peça. A conclusão permanece como causa não confirmada até existir investigação específica. A proposta é orientar testes comparáveis e evitar substituições sem evidência, não prometer um diagnóstico físico universal.

## Instalação e fluxo no Windows

Use Python 3.10+ de 64 bits e as dependências do projeto. Para analisar ETL, instale o **Windows Performance Toolkit**, componente disponibilizado pelo Windows ADK, a partir da [documentação Microsoft](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/). O programa procura `xperf.exe` no diretório padrão `Windows Kits/10/Windows Performance Toolkit`, em Program Files ou Program Files (x86). Não baixa executáveis automaticamente.

1. Abra **AVANÇADO**. Escolha 30, 60, 120 ou 180 segundos; o padrão é 60.
2. Clique em **Iniciar captura · administrador**, escolha a pasta e autorize o UAC do Windows.
3. Espere aparecer a indicação de gravação antes de reproduzir o problema. Marque o sintoma pelo botão ou `Ctrl + Alt + F8`.
4. Use **Encerrar e analisar** ou aguarde a duração escolhida. A finalização do ETL leva tempo adicional.
5. Leia a explicação e confira os números em **DPC / ISR**. **Dados e limites** mantém a saída bruta do processador.

A janela principal continua sem elevação. O auxiliar `etw_capture.py` usa o mesmo Python da aplicação e solicita administrador somente ao capturar. Negar o UAC não inicia o WPR. Políticas que bloqueiem a execução são apresentadas como erro; não há tentativa de contorná-las.

A captura usa o perfil WPR `GeneralProfile`, gravação em arquivo e pasta temporária própria. Cada chamada usa a mesma instância exclusiva `SysPulse_<identificador>`, com `-instancename` ao final. O cancelamento de recuperação também aponta apenas essa instância. Veja as [opções oficiais do WPR](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/wpr-command-line-options).

O início exige 2 GiB livres. Durante a coleta, o auxiliar solicita encerramento abaixo de 1 GiB livre ou ao detectar cerca de 1 GiB em ETLs temporários. São limites aproximados, sujeitos ao intervalo de verificação e ao crescimento durante a finalização. **Sair** solicita parada; fechar para a bandeja mantém o programa funcionando. Se o processo principal desaparecer, o auxiliar tenta salvar. Encerrar à força o auxiliar pode deixar uma sessão WPR ativa: a tela mostra o comando de recuperação da instância identificada.

## Recursos e marcações

A captura avançada compartilha as amostras do monitor existente; não inicia outro coletor de recursos. Ela começa sua gravação nativa quando a interface observa o WPR gravando e solicita sua parada quando observa a finalização do ETL. Há atraso de observação de aproximadamente 500 ms, além das filas e do custo dos próprios coletores.

As duas fontes têm períodos próprios. A análise espera o término de ambas, mas **não alinha automaticamente as linhas do tempo**. Não afirma que um pico de recursos e uma execução de driver aconteceram simultaneamente. A gravação, o inventário e o próprio WPR consomem recursos; considere esse custo na comparação.

Cada marcação tem horário solicitado e confirmação do auxiliar. O ETL recebe um identificador; a anotação fica nos arquivos locais. Uma marcação pode atrasar ou falhar, e sua confirmação é registrada. O atalho indica quando foi recebido, não o início exato de um congelamento.

## Importar e interpretar ETL

**Abrir ETL…** aceita um arquivo não vazio de até 4 GiB e solicita uma pasta para a análise. O processamento utiliza as ações Xperf `dpcisr` e `tracestats`. ETLs de outras ferramentas precisam conter os eventos relevantes e informações para resolver módulos. O parser reconhece os cabeçalhos de texto em inglês cobertos pelos testes; formatos diferentes podem aparecer como dados insuficientes. Os relatórios brutos são preservados para conferência.

| Campo | Significado e limite |
|---|---|
| Tipo | DPC e ISR permanecem separados. |
| Módulo | Nome reconhecido pelo Xperf; pode ser uma camada compartilhada, não o dispositivo responsável pelo sintoma. |
| Ocorrências | Contagem reconhecida na seção do módulo. Ausência fica N/D. |
| Total | Soma dos tempos dos processadores; não é percentual de utilização nem tempo de uma pausa. |
| Média | Total dividido pela contagem quando ambos estão disponíveis. |
| Maior faixa | Faixa mais alta ocupada do histograma, somente quando a soma das contagens confere. **Não é um máximo exato.** |
| Eventos perdidos | Valor reconhecido nas estatísticas; se não for reconhecido, a qualidade fica desconhecida. |

O `max_us` no JSON permanece nulo: o programa não inventa um máximo usando o teto da faixa. A [ação DPC/ISR do Xperf](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/xperf/the-dpc-isr-action) gera resumos, intervalos e histogramas. Isso não equivale à latência interrupt-to-process, espera em fila, FPS ou frametime. Um ranking alto não comprova falha, e módulos como `ndis.sys`, `dxgkrnl.sys` e `Wdf01000.sys` podem envolver outros componentes. Para examinar eventos e pilhas em profundidade, use o WPA.

Cada processo de análise tem timeout de três minutos. Cancelar encerra apenas o processo Xperf iniciado pela análise e preserva o ETL. Os textos lidos são limitados a 32 MiB; exceder o limite é informado como erro. Sem Xperf, a captura pode ser guardada e analisada depois.

## Arquivos

| Arquivo ou pasta | Conteúdo |
|---|---|
| `captura.etl` | Rastreamento original do Windows. |
| `request.json`, `status.json` | Solicitação, estado e identidade da captura. |
| `markers.jsonl` | Marcações e confirmação de envio ao WPR. |
| `recursos/` | Sessão nativa de recursos, processos e inventário disponível. |
| `context.json` | Caminho relativo da sessão associada; reabrir o ETL ao lado deste arquivo recupera o vínculo. |
| `analise/analise-avancada.txt` | Explicação local legível. |
| `analise/analise-avancada.json` | Resultado estruturado, evidências e limites. |
| `analise/dpc-isr.txt`, `trace-stats.txt` | Saída de texto do Xperf. |
| `analise/xperf-*.log`, `wpr-status.txt` | Saídas de diagnóstico das ferramentas. |

ETLs podem conter processos, caminhos e outros dados do sistema. A restrição de conteúdo das capturas nativas não se aplica ao ETL. Confira os arquivos antes de compartilhá-los.

## IA opcional

A integração está preparada para a API de Chat Completions. O padrão é `http://127.0.0.1:11434/v1/chat/completions`, compatível com o [servidor local do Ollama](https://docs.ollama.com/api/openai-compatibility).

Para uso local, instale o Ollama, disponibilize um modelo que caiba nos recursos do computador e informe o nome exato exibido pelo serviço. A chave normalmente pode ficar vazia no servidor local. A escolha e o download do modelo ficam com o usuário; nenhum modelo foi instalado nesta entrega. Um modelo executado localmente usa os recursos do computador e pode funcionar sem cobrança por consulta, conforme sua licença. Faça a consulta depois da captura para não contaminar a medição.

Para um provedor externo, informe endpoint HTTPS terminado em `/chat/completions`, modelo e chave quando exigida. Planos, limites, gratuidade e compatibilidade dependem do provedor. Não há serviço gratuito externo garantido ou conta contratada. Um servidor local também pode encaminhar consultas a modelos de nuvem; confira qual modelo foi escolhido.

A interface mostra o JSON completo que será enviado e pede confirmação do destino. Ele contém até dez módulos com métricas, estatísticas agregadas de recursos, duração e perdas reconhecidas. Exclui nomes de processos, caminhos, IPs, anotações, inventário e conteúdo do ETL. A chave não é salva nos relatórios nem nas configurações; permanece em memória durante a sessão. Redirecionamentos HTTP não são seguidos.

A resposta aparece como texto complementar, podendo conter erros. Não é executada como comando, não muda drivers e não altera a conclusão da análise local. O envio é manual, nunca consequência automática da captura. Falhas de conexão não impedem a leitura da análise local.

## Validação desta entrega

Foram executados **69 testes automatizados**, incluindo análise de métricas, importação, histograma incompleto, formatos desconhecidos, recusa de UAC simulada, cancelamento por instância e privacidade do resumo. Dois testes de interface exercitam gravação real dos recursos com entrada simulada e ambas as ordens de conclusão entre gravador e ETL; o Xperf é simulado nesses testes.

As telas foram renderizadas com Qt e dados simulados. O parser foi testado com uma fixture sintética identificada como tal. **Não foi processado um ETL real, executado UAC/WPR/Xperf no Windows ou consultado um modelo real de IA neste ambiente Linux.** Os testes verificam os contratos implementados, não substituem a validação abaixo.

Uma coleta real de recursos em Linux produziu 11 amostras e uma marcação, sem erro informado pelo coletor. O fluxo de parada, análise local e exportação TXT/JSON foi concluído. Isso verifica o caminho nativo de recursos neste ambiente; não valida a captura avançada do Windows.

## Roteiro no computador Windows

1. Execute os testes e abra o programa sem administrador. Confira a detecção de WPR/Xperf.
2. Inicie e recuse uma solicitação UAC. Deve aparecer o cancelamento, sem ETL iniciado. Depois aceite uma nova captura curta.
3. Marque o sintoma, encerre e confira ETL, recursos, relatório e confirmação das marcações. Repita deixando a duração terminar automaticamente.
4. Compare contagens e tempos com o mesmo ETL no Xperf/WPA. Confira que o teto do histograma nunca aparece como máximo exato.
5. Reabra o ETL junto de `context.json` e verifique a recuperação dos recursos. Importe também uma captura sem os eventos necessários: deve haver limitação explícita.
6. Cancele a análise e confirme que o ETL original continua disponível. Use **Sair** durante outra captura curta e confira posteriormente se o auxiliar a salvou.
7. Se houver outra sessão de diagnóstico autorizada em andamento, confira que o SysPulse não a cancela. Conflitos devem ser informados; nunca use cancelamento global para resolver o teste.
8. Confira a saída com UAC/política negados, Xperf ausente e falta de espaço. Não desative proteções para concluir a validação.
9. Teste a IA com um serviço escolhido, confira a prévia e a resposta contra os números locais. Com serviço indisponível, a explicação local deve continuar acessível.
10. Compare duas capturas da mesma tarefa e duração, uma com sintoma e outra sem. Registre mudanças de software/configuração uma por vez antes de considerar testes físicos do componente.
