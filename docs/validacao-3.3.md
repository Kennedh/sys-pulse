# Validação 3.3

## Conexões e modelos

238 testes passaram no Windows. A suíte cobre os seis novos conectores diretos, os conectores anteriores, consulta do catálogo filtrado do OpenRouter, metadados de capacidade, paginação Messages, respostas efetivas e recusa de respostas interrompidas pelo limite de tokens.

Endereços base, troca de formato, prefixos de proxy, porta inválida, credenciais embutidas na URL e protocolo inseguro são verificados. Também foram testados formato/autenticação persistidos por serviço, limpeza de chave ao trocar servidor, invalidação do catálogo ao mudar chave e seleção manual quando o catálogo está ausente.

Os quatro formatos foram exercitados por HTTP real contra um servidor simulado em loopback. Cada caso consultou modelos e enviou uma solicitação de análise, verificando rota, corpo, cabeçalho de autenticação e resposta efetiva. Isso valida o transporte; não substitui testar todas as opções de cada provedor real.

## Autorização pelo navegador

O OpenRouter usa PKCE S256, verificador por tentativa e callback em porta livre restrita a 127.0.0.1, com caminho aleatório. O fluxo não usa senha ou credencial do autor. O navegador faz a autorização; a credencial recebida pertence à conta escolhida.

A suíte efetuou retornos HTTP reais em loopback, verificando o desafio, a troca de código/verificador, a recusa de caminho incorreto, cancelamento, prazo e recusa pelo provedor. Também verificou o fluxo da interface após a autorização: receber a credencial simulada, buscar modelos, salvar a seleção e não iniciar inferência.

Não foi efetuado login real no OpenRouter nem usada uma conta com saldo para geração. Não havia credenciais reais disponíveis para testar as APIs autenticadas dos provedores. As trocas e respostas externas foram simuladas; esse limite permanece explícito.

## Catálogos públicos

Consultas reais de leitura retornaram 134 modelos no Hugging Face e 452 no catálogo público OpenRouter. Não foram usadas credenciais, saldo ou inferência nessas consultas. O aplicativo autenticado usa /models/user no OpenRouter para respeitar as preferências da conta; essa rota foi verificada por contrato simulado.

Catálogo disponível não garante saldo, cota, permissão final ou compatibilidade com todos os parâmetros de um modelo. O modo manual salva a escolha como ainda não conferida. A análise mantém validação por IDs de evidências; uma resposta fora do contrato é recusada.

A conexão real ao Ollama pela interface detectou três modelos instalados, confirmou llama3.2:3b no formato Ollama e manteve zero modelos carregados em /api/ps. Não foi iniciada inferência nesse teste.

## Compatibilidade e recursos

A conexão consulta metadados. O aplicativo não solicita inferência durante a captura. O corpo nativo Ollama preserva keep_alive=0 após a análise; Responses solicita store=false. O cache distingue provedor, endereço, formato, autenticação, modelo e impressão da credencial, sem persistir a chave no relatório.

As prévias usam preferências temporárias, IDs de modelos e credencial simulados. Não alteram as preferências reais nem abrem login no navegador.

As medições reais anteriores de GPU, CPU/RAM, quadros e consumo estão preservadas na [validação 3.2](validacao-3.2.md). Não foi repetido um benchmark prolongado nesta alteração de conectores.

## Pacotes

O executável Windows passou na abertura de demonstração, integridade do ZIP e auxiliares CPU/RAM de dois segundos. O validador preservou a instalação local existente. A análise do empacotamento confirmou a inclusão de ai_login, ai_connections e ai_providers. Os demais resultados nativos serão conferidos no workflow associado à tag da versão.
