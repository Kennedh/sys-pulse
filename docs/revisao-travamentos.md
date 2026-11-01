# Revisão da investigação de travamentos

Data: 31/10/2026.

## Resultado da revisão

A base 2.2 já possuía coleta, marcações, inventário, WPR, Xperf e explicação local.
O principal problema era a distância entre a pergunta “o que aconteceu quando travou?” e o relatório,
que explicava principalmente os maiores consumos da sessão inteira.

Foram preservados os módulos, as threads, os dicionários e a interface Qt existentes, incluindo as alterações
locais anteriores. O Markdown externo foi usado como histórico: suas sugestões de instalar Ollama
não foram tratadas como nova solicitação. Nenhum serviço de IA foi instalado ou chamado.

## Problemas encontrados e alterações

| Problema | Alteração |
|---|---|
| Varredura de processos no mesmo laço das métricas rápidas | Thread própria para processos e contadores GPU por PID; publica snapshot completo com idade e custo. |
| Explicação baseada nos maiores consumos globais | Comparação de carga perto das marcações com o restante da sessão; evidências por sintoma aparecem primeiro. |
| Janelas próximas podem repetir a mesma leitura | Cada amostra entra uma vez na comparação agregada da união das janelas. |
| Carga alta o tempo todo pode parecer causa da pausa | O texto informa quando a carga fora das janelas tem frequência igual ou maior. |
| Falta de base ou cobertura pode parecer consumo zero | Base ausente fica N/D; janelas parciais e lacunas são informadas. |
| Latência de disco ficava apenas na tabela técnica | Triagem por disco/operação, com atividade, fila e IOPS da mesma amostra. |
| Cache podia alterar o peso de GPU/VRAM | A mesma atualização conta uma vez também no resumo de recursos. |
| Processo com idade negativa ou leitura futura podia virar contexto | Esses snapshots são rejeitados na análise. |
| ETL informa perdas totais e novamente por rastreamento | Parser prefere o total; só soma linhas individuais na ausência dele. Buffers perdidos também são informados. |
| Teste de exportação dependia da codificação padrão do Windows | Leitura explícita em UTF-8. |
| IA opcional não recebia comparação por sintoma | Métricas agregadas sem nomes de processos, horários, notas ou caminhos. |

A análise nativa versão 4 acrescenta a estrutura symptoms; a análise avançada a guarda em native_symptoms.
Capturas anteriores continuam sendo lidas a partir dos arquivos brutos.
O critério de 30 ms/op para latência média de disco é uma heurística de triagem, sem comprovação de defeito.

## Evidências da captura existente

Foi reanalisada sem alterações a pasta avancado-20261028-233700-863b3893.
São dados preservados, não uma nova reprodução do sintoma:

- 75 amostras nativas, cobrindo aproximadamente 44,7 s, e nenhuma marcação.
- 10 intervalos entre amostras válidas excederam duas vezes o alvo; o maior foi aproximadamente 1.904 ms.
- Custo registrado da coleta: média de aproximadamente 171 ms e máximo de 1.403 ms.
- Em 10 amostras, o custo foi pelo menos o intervalo alvo.
- O texto DPC/ISR existente cobre aproximadamente 67,2 s e reconhece 28 entradas de módulo/tipo.
- As estatísticas textuais informam zero eventos e zero buffers perdidos.
- O novo critério de latência de disco não gerou alerta nessa sessão.

A diferença entre os períodos nativo/ETL e a ausência de marcações impedem relacionar determinado consumo
à pausa percebida. Atividade gráfica, de disco ou de processo é contexto; a captura não comprova uma causa.

A coleta serializada era um risco concreto para a medição: uma varredura lenta segurava o próximo snapshot.
A separação das threads corrige esse bloqueio. O trabalho da varredura continua consumindo recursos.

## Validação executada

Windows, Python 3.13.1, psutil 7.2.2 e PySide6 6.11.1.
Foi criado .venv com acesso aos pacotes existentes e pytest instalado somente nesse ambiente virtual.

- Suíte inicial: 68 testes aprovados e uma falha de codificação no teste de exportação.
- Suíte final: **86 testes aprovados**, incluindo interface Qt offscreen.
- Regressões verificam sobreposição, comparação com o restante da sessão, carga constante, base ausente,
  cobertura parcial, lacunas, leitura futura, cache de GPU, contexto de latência do mesmo disco,
  privacidade do resumo e perdas do Xperf.
- Teste sincronizado bloqueia artificialmente a varredura de processos e confirma que os recursos continuam
  entregando amostras.
- Coleta real curta após a separação: 16 amostras, custo médio do laço de aproximadamente 30 ms,
  máximo de 124 ms e maior intervalo de 546 ms para alvo de 500 ms.
- Houve processos disponíveis em 11 amostras, sem erro informado; ambas as threads encerraram.
  A varredura de processos chegou a aproximadamente 487 ms.

A coleta curta não repetiu a tarefa antiga. Esses valores verificam funcionamento e cadência neste teste,
sem quantificar ganho sob carga equivalente ou provar resolução do travamento.

Os textos Xperf existentes foram reprocessados pelo parser. Não houve nova captura WPR, elevação UAC
ou comparação independente com WPA. Os testes WPR/UAC/Xperf existentes usam simulações.
IA real não foi consultada.

## Próxima medição

1. Abra o programa atualizado, espere o inventário terminar e use inicialmente o intervalo de 500 ms.
2. Reproduza a tarefa que apresenta o sintoma em uma captura curta.
3. Marque as pausas com Ctrl + Alt + F8 e aguarde pelo menos 5 s depois da última marcação.
4. Leia **Entenda o resultado** e **Marcações**, conferindo carga dentro/fora das janelas, cobertura e lacunas.
5. Repita tarefa e duração com uma única variável alterada a partir da evidência.
6. Se a amostragem não explicar a pausa, investigue no WPA o período correspondente do ETL.

Fora das marcações não significa sem travamento. As frequências são percentuais de leituras válidas,
sem ponderação por tempo ou teste de significância. Diferença positiva não é probabilidade de causa.

## Limites restantes

- Não há FPS/frametime ou medição do início exato do congelamento.
- A janela nativa de ±5 s não alinha automaticamente os eventos ETL.
- O resumo DPC/ISR ainda não reconstrói automaticamente a cadeia de espera de uma thread com CPU,
  disco, escalonamento e apresentação de quadros.
- O topo por tempo DPC/ISR acumulado não identifica sozinho o evento que bloqueou a tarefa.
- Faixas de histograma não são máximos exatos nem latência completa do computador.
- Inventário e eventos do Windows precisam ser conferidos pelo horário.
- Nenhum componente foi confirmado como defeituoso nesta revisão.

A orientação Microsoft de [análise de CPU no WPA](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/cpu-analysis)
distingue atividade DPC/ISR relacionada e não relacionada ao problema.
A [ação DPC/ISR do Xperf](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/xperf/the-dpc-isr-action)
fornece resumos, intervalos e histogramas; esses agregados não substituem a investigação do período do sintoma.
