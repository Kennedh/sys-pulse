# Validação 3.2

## Seleção de IA

A suíte cobre autenticação e corpo nativo da API Anthropic, modelo efetivo retornado, remoção de modelos aposentados, separação local/nuvem, credenciais por provedor, resposta tardia de outro catálogo, troca de modelo, modo integrado e origem persistida da resposta. Também verifica a recusa de resposta salva quando o resumo muda.

Claude foi validado por contratos com respostas simuladas. Não havia credencial de API disponível para testar uma chamada autenticada real. A consulta de catálogo não comprova saldo, cota ou sucesso de uma inferência posterior.

O fluxo real da interface iniciou/detectou o Ollama local, encontrou três modelos instalados e confirmou llama3.2:3b. A consulta /api/ps informou zero modelos carregados. Nenhuma inferência foi iniciada nesse teste.

Os testes anteriores de inferência Llama 3B e Qwen 0.6B permanecem em [validação 3.0](validacao-3.0.md) e [examples/validacao-modelos](../examples/validacao-modelos). Não são um ranking de qualidade.

## Cena GPU

A carga agora usa geometria instanciada: 84 cubos com movimento, perspectiva, teste de profundidade e iluminação. Perfis alteram o trabalho do fragment shader; a resolução é configurável. A submissão CPU é medida separadamente e inclui possíveis esperas na API.

Teste funcional no código-fonte, RTX 3050, perfil equilibrado, 1280×720, orçamento de 25%, três segundos:

- 89 quadros produzidos; 88 intervalos medidos.
- 31,54 FPS pelos intervalos; P95 de 46,0 ms e P99 de 83,2 ms.
- Duração total de 3,34 s; encerramento normal e código zero.

Esses números incluem pausas do orçamento de carga, inicialização e agendamento. Não medem a capacidade máxima da GPU nem são um benchmark comparável entre máquinas. Os percentis usam histograma de 0,1 ms; intervalos a partir de 2.000 ms ficam no último balde, com contagem de estouro e máximo original preservado.

O teste não detecta artefatos, não verifica toda a VRAM e não certifica estabilidade. Não foi executada automaticamente uma carga longa ou total.

## Quadros durante a captura

Um teste Direct3D 11 com pausa artificial de 200 ms produziu 611 linhas válidas, mediana de 16,0131 ms, P99 de 16,9989 ms e maior intervalo de 224,956 ms. A análise classificou um intervalo longo.

Cinco consultas durante a captura receberam dados válidos. A saída de arquivo padrão do PresentMon mantinha dados em buffer; a implementação passou a usar --output_stdout, com descarga por linha, conversão incremental UTF-16/UTF-8 e gravação UTF-8. Esse comportamento foi verificado no [código oficial do PresentMon](https://github.com/GameTechDev/PresentMon/blob/main/PresentMon/CsvOutput.cpp).

O painel lê até 1 MiB por atualização e retém no máximo 4.000 intervalos. Não mistura PID/swapchain. A janela recente usa até dois segundos do relógio QPC quando disponível; ausência de dados novos é indicada.

A cena OpenGL curta não produziu CSV pelo PresentMon nessa máquina. Ela mantém sua própria medição por frameSwapped. Não se declarou suporte universal do PresentMon a qualquer caminho de apresentação.

## Drivers e LatencyMon

A consulta real somente de leitura ao Windows Update concluiu com ResultCode 2 e duas ofertas aplicáveis. Nenhum download/instalação de driver foi solicitado. O caminho de instalação abre a tela do próprio Windows ou a página oficial do fabricante.

O instalador original do LatencyMon foi baixado do domínio Resplendence e teve assinatura Authenticode válida da SOFTREV LABS S.R.L.S. A relação entre marca e empresa está documentada no [site da SoftRev](https://softrev.com/main). O fluxo completo de download e validação passou sem executar o instalador.

A suíte cobre assinatura inválida, editor desconhecido, redirecionamento fora do domínio oficial, limite de arquivo e importação de texto UTF-8, UTF-16 e Windows-1252.

LatencyMon não foi instalado nem executado automaticamente durante a validação. A integração abre a ferramenta original e permite visualizar seu relatório exportado; não incorpora o driver, não automatiza sua medição e não correlaciona períodos independentes. A licença/edição é a do instalador original.

## Consumo da captura

Medição real de 30 segundos, interface visível, 12 processadores lógicos, Python 3.13.1, captura nativa leve, sem IA, jogo, quadros ou stress simultâneo:

| Medição | Resultado |
|---|---:|
| CPU média do processo, normalizada pela máquina | 0,365% |
| Pico CPU do processo | 0,923% |
| RAM RSS média / pico | 143,66 / 144,61 MiB |
| Coleta média / maior | 18,47 / 22,26 ms |
| Intervalo médio / maior | 500,03 / 513,11 ms |
| Amostras / perdas da fila | 61 / 0 |
| Amostras comprimidas | 56.612 bytes |
| Total com inventário e análises | 491.631 bytes |

A análise automática concluiu sem avisos. A medição de CPU/RAM exclui processos filhos. Consulta de drivers, downloads e IA não rodaram durante a medição. Uma execução curta não comprova o custo de todos os modos ou ausência de crescimento em sessões longas. A medição anterior de 30 minutos continua documentada em [validação 2.3](validacao-2.3.md).

O primeiro teste GPU do executável sem console falhou porque faulthandler tentou usar stderr ausente. O log foi redirecionado para gpu-fault.log na pasta do teste. Uma regressão cobre a ausência de console; falhas de inicialização também preservam a mensagem em result.json para a interface.

O executável Windows corrigido concluiu a cena 3D em 3,05 s: 73 quadros, RTX 3050, 1280×720 e orçamento de 25%. O resultado registrou 29,11 FPS, P95 de 51,7 ms e P99 de 212,5 ms, com código de saída zero. Como no teste fonte, os números incluem pacing e inicialização e não representam capacidade máxima.

## Regressões

188 testes passaram no Windows. Os resultados brutos, os instaladores baixados e as capturas locais ficam em diagnosticos/validacao-3.2 e diagnosticos/validacao-grafica, fora do Git.

O pacote Windows final passou na integridade do ZIP, abertura de demonstração e auxiliares CPU/RAM de dois segundos. O validador preservou a instalação local preexistente; instalação e remoção em pasta personalizada ficam para o ambiente limpo do CI. Os demais resultados nativos devem ser conferidos no workflow associado à tag da versão.
