# Validação do SysPulse 3.0

Os resultados abaixo distinguem teste local, validação de pacote e disponibilidade de serviços externos.

## Modelos locais

As execuções em Windows usaram somente entradas sintéticas com IDs de evidência e os mesmos limites da interface. Os relatórios em examples/validacao-modelos não contêm dados de capturas reais.

| Modelo | Caso CPU | Caso disco | Formato/IDs | Modelos carregados ao final |
|---|---:|---:|---|---|
| Llama 3.2 3B | 3,312 s; 287/24 tokens | 3,378 s; 289/24 tokens | Aceitos nos dois casos | Nenhum |
| Qwen 3 0.6B | 14,619 s; 286/25 tokens | 2,768 s; 289/25 tokens | Aceitos nos dois casos | Nenhum |

Sem candidatos, os dois testes retornaram a explicação integrada sem requisição ao modelo e com zero tokens. A configuração usou keep_alive=0.

O Qwen foi baixado por /api/pull em streaming: 522.653.767 bytes, aproximadamente 12,75 s nessa conexão. O Llama informou 2.019.393.189 bytes e reutilizou camadas existentes. Download em disco não mede consumo de RAM/VRAM.

Esses dois casos por modelo confirmam o fluxo e o contrato, sem demonstrar precisão diagnóstica geral. As condições de cache, primeira carga e atividade simultânea não foram controladas para comparar velocidade.

O teste anterior do Llama 3B em [validação 2.3](validacao-2.3.md) registrou 298 tokens de entrada, 24 de saída e aproximadamente 3,12 GB decimais de VRAM durante a chamada, descarregados após ela.

Llama 1B é uma opção de catálogo, sem medição real de qualidade nesta entrega.

## IA remota anônima

Foi usada a API pública do AI Horde com seu identificador anônimo documentado, sem conta e sem chave pessoal. O payload continha somente um caso sintético de CPU.

Uma chamada válida retornou o ID E1 na categoria CPU em 13,521 s, incluindo fila. O modelo disponível nessa chamada foi koboldcpp/gemma-4-31B-it-heretic. O serviço não informou contagens de tokens; elas permanecem N/D.

Uma tentativa anterior foi rejeitada pelo contrato por formato inválido. A integração preservou a explicação local. Uma recusa de transporte inicial foi corrigida identificando o cliente HTTP; ela não foi contabilizada como acerto ou erro de diagnóstico.

A escolha automática pode selecionar outro modelo conforme a disponibilidade. Não há garantia de fila curta, resposta válida ou qualidade constante. Workers voluntários recebem o resumo e podem armazená-lo; a confirmação de envio informa isso. Não foram enviadas capturas reais.

A fila tem prazo de 90 s, com timeouts de rede adicionais. Cancelamento, encerramento ou expiração tentam remover somente a solicitação criada pelo aplicativo.

## Regressões e interfaces

144 testes passaram no Windows após a integração do acesso anônimo. Eles incluem fila e cancelamento, ausência de chave pessoal, download parcial, erros, nomes e endpoints válidos, bloqueio de captura/inferência durante preparação, reutilização do servidor e configuração inicial sem downloads automáticos.

As verificações de coleta, compactação, frametimes, ETL e unidades documentadas na versão anterior continuam na suíte. Os prints foram gerados pela própria interface com dados simulados identificados.

## Coleta longa e consumo

A [validação anterior de 30 minutos](validacao-2.3.md) gravou 3.600 amostras sem perdas, em 3,82 MiB com relatórios, com janela offscreen. O teste curto com janela visível registrou 0,479% de CPU média normalizada pelas 12 CPUs lógicas e RSS máximo de 138,45 MiB.

Essas medições são da base 2.3 anterior às telas de instalação e gerenciamento de modelos. Não são apresentadas como um novo benchmark completo da versão 3.0 nem como garantia de impacto em FPS.

## Instaladores

O build Windows gera Setup.exe, ZIP portátil e SHA-256. O teste de instalação verifica uma pasta personalizada com espaços, abertura do executável, presença do desinstalador e remoção do aplicativo.

A rodada nativa [41321815318](https://github.com/Kennedh/sys-pulse/actions/runs/41321815318), no commit 3ad5c1e, concluiu com sucesso nos quatro sistemas:

| Ambiente | Testes | Pacote verificado |
|---|---|---|
| Windows Server 2022 x64 | 144 passaram | ZIP íntegro, Setup em pasta com espaços, abertura e desinstalação |
| Ubuntu 22.04 x64 | 143 passaram, um exclusivo de Windows não aplicável | Setup.run, abertura e desinstalação em pasta com espaços |
| macOS 15 Apple Silicon | 143 passaram, um exclusivo de Windows não aplicável | Payload do PKG e abertura do aplicativo dentro do DMG |
| macOS 15 Intel | 143 passaram, um exclusivo de Windows não aplicável | Payload do PKG e abertura do aplicativo dentro do DMG |

O teste Windows local também passou na instalação, abertura e remoção em pasta personalizada. Os pacotes de CI usaram Python 3.13.17 e Qt/PySide6 6.12.0; os testes locais de modelos usaram o ambiente Python desta máquina.

A primeira rodada detectou incompatibilidade de PSModulePath ao iniciar Windows PowerShell a partir do runner PowerShell 7 e limpeza inadequada dos widgets Qt no encerramento dos testes Linux. O ambiente do subprocesso e a destruição dos widgets de teste foram corrigidos. A rodada acima confirmou encerramento normal, sem ignorar códigos de erro.

Os builds Linux e macOS ocorreram nesses sistemas. O workflow do GitHub testa a suíte e o pacote em Windows x64, Ubuntu 22.04 x64, macOS 15 Apple Silicon e macOS Intel. A publicação por tag depende da aprovação dos quatro jobs.

A validação do Linux instala o .run em uma pasta temporária personalizada, abre o aplicativo e executa a desinstalação. A do macOS verifica o payload do PKG e abre o aplicativo no DMG montado somente para leitura. Isso não equivale a instalar e usar todos os recursos em toda versão de cada sistema.

Não há certificado comercial de assinatura, notarização Apple nem teste de impacto durante um jogo real nesta entrega.
