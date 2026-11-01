# Histórico de versões

## 3.2.0 — 01/11/2026

- Seleção de IA por origem, catálogo automático e confirmação explícita do modelo em uso.
- Claude pela API nativa Anthropic, credenciais por provedor e modelos locais separados dos modelos de nuvem.
- Respostas com provedor/modelo efetivo, data, cache e persistência junto à sessão.
- Downloads locais recolhidos e conexão ao Ollama sem carregar pesos.
- FPS produzidos e frametime P95/P99 recentes durante capturas compatíveis.
- GPU com geometria 3D instanciada, profundidade, movimento e iluminação; perfis e resoluções configuráveis.
- FPS e percentis da cena GPU nos resultados, separados do tempo de submissão CPU.
- Consulta de drivers pelo Windows Update e acesso aos instaladores oficiais dos fabricantes.
- Instalação opcional, detecção, abertura e importação de texto do LatencyMon; assinatura do fabricante verificada.
- Testes de regressão, documentação e prévias atualizados.

## 3.1.0 — 01/11/2026

- Seleção de análise por modos claros: integrada, online anônima, local e serviço avançado.
- Configuração ativa explícita e modelo salvo por provedor.
- Evolução por minuto, tendências de início/fim e períodos de maior pressão em sessões longas.
- Frametime por período, RSS do aplicativo e comparação das fases de estresse.
- Removida a recomendação genérica de encurtar capturas; marcações permanecem opcionais.
- Cargas CPU com resultado conhecido, RAM com escrita/leitura verificada e GPU 3D via OpenGL.
- Gravação automática antes, durante e depois da carga; parada, limites térmicos e cobertura informados.
- Auxiliares isolados, compatibilidade de multiprocessing no executável e validação de CPU/RAM empacotados.
- Testes, documentação e prints atualizados.

## 3.0.0 — 01/11/2026

- Instaladores nativos e pacotes portáteis para Windows, Linux e macOS, com builds por arquitetura.
- Windows com escolha de pasta, atalhos, análise inicial e desinstalação; modelos fora do instalador.
- Configuração inicial e download opcional de modelos pelo aplicativo, com progresso e cancelamento.
- Ollama detectado/reutilizado ou iniciado sem carregar modelo; servidores externos preservados.
- IA anônima via AI Horde sem login ou chave pessoal, com fila limitada, cancelamento e validação das respostas.
- APIs e conta Ollama mantidas como alternativas avançadas.
- Download, preparação e inferência impedem novas capturas; escolha do modelo não inicia análise.
- Testes reais documentados de Llama 3B, Qwen 0.6B e geração anônima com dados sintéticos.
- Fluxo GitHub Actions para validar pacotes nos sistemas nativos e publicar os arquivos em Releases.
- README e guia de instalação com armazenamento de modelos, consumo, testes e limites por sistema.

## 2.3.0 — 01/11/2026

- Navegação e cartões renovados; captura principal com Iniciar, Marcar e Encerrar, opções técnicas recolhidas.
- Hardware e rede com informações adicionais, destino de ping configurável e dados indisponíveis explícitos.
- Sessões de até duas horas, gzip rápido, exportação CSV sob demanda e limites de espaço.
- Leitura agrupada de processos do Windows, com fallback e preservação do processo escolhido.
- Captura circular WPR em memória para aguardar o sintoma; detalhes ETL de execução, arquivos e hard faults.
- PresentMon opcional por processo, frametimes comprimidos, percentis e contexto de recursos por QPC.
- Configuração compartilhada de Ollama/Llama, LM Studio, Gemini, OpenRouter, OpenAI e API compatível.
- Inferência bloqueada durante capturas; Ollama solicitado a descarregar após a análise.
- Resumo limitado, cache em memória, tokens informados e resposta validada por IDs de evidências.
- Chave opcional no Gerenciador de Credenciais do Windows, sem texto simples nas preferências.
- Pacote portátil Windows, inicializador, ícone e ferramentas de benchmark e validação gráfica.
- Validação real nesta máquina: sessão de 30 minutos, janela visível, WPR/UAC/Xperf, PresentMon e Llama.
- Prints, guia de uso, regressões e documentação de medidas e limites atualizados.

## Em desenvolvimento — revisão de travamentos

- Explicação prioriza janelas de sintomas, comparando carga alta com o restante da sessão.
- Janelas sobrepostas deduplicadas na comparação agregada; cobertura parcial e lacunas explícitas.
- Varredura de processos em thread própria, com custo e idade preservados, sem bloquear métricas rápidas.
- Custo da coleta, lacunas reais entre amostras e falhas na leitura de processos informados no relatório.
- Triagem de latência por disco com fila, atividade e IOPS da mesma observação.
- GPU/VRAM em cache contam uma vez também no resumo de recursos; leituras futuras de processos rejeitadas.
- Leitura dos totais de eventos/buffers perdidos do Xperf sem duplicar totais e rastreamentos individuais.
- IA opcional recebe comparações numéricas por recurso, sem horários, marcações individuais ou processos.
- Teste de exportação corrigido para UTF-8 no Windows e regressões para coleta, cálculos e interface.

## 2.2.0

- Explicação local das evidências, significado, limites e próximos testes em capturas nativas e avançadas.
- Captura WPR GeneralProfile por processo auxiliar, com solicitação UAC e instância própria.
- Duração selecionável, encerramento antecipado, marcações e tentativa de salvar ao sair.
- Recursos gravados junto ao ETL; finalização coordenada antes da análise, sem alegação de sincronismo exato.
- Importação de ETL via Xperf; DPC/ISR por módulo, contagens, total, média e faixa superior do histograma.
- Eventos perdidos, módulos desconhecidos e saída não reconhecida explicitamente sinalizados.
- Relatórios avançados TXT/JSON e preservação da captura original ao cancelar análise.
- Integração opcional com Chat Completions, padrão Ollama local, prévia e confirmação do envio.
- Resumo para IA sem nomes de processos, caminhos, IPs, observações ou ETL completo; chave somente em memória.
- Testes de cálculos, cancelamento, recusa de UAC, comandos por instância, privacidade e ciclo de gravação/análise.
- Documentação de uso e roteiro Windows; execução nativa WPR/UAC/Xperf ainda não validada nesta entrega.

## 2.1.0

- Tela Drivers e saúde com busca, filtros, códigos PnP e exportação JSON.
- Consulta Windows em segundo plano, com timeout e erros explícitos por seção.
- Saúde de armazenamento e contadores de confiabilidade conforme suporte.
- Eventos selecionados do log System nas últimas 24 h, limitados a 100 registros.
- Inventário vinculado à gravação e integrado à análise de pasta/ZIP.
- P95 e duração observada de carga alta, com interrupção por lacuna, ausência e troca de dispositivo.
- Estatísticas de sensores e discos por dispositivo; exclusão de cache e dados vencidos.
- IOPS de leitura/escrita e fila no monitor.
- CPU de processo novo ou PID reutilizado indisponível durante a primeira leitura.
- Preservação de identidade por criação do processo também no resumo básico de marcações.
- Correção da corrida entre conclusão do inventário e início da gravação.
- Comentários curtos, apenas para regras que precisam de contexto.
- Testes e documentação técnica com referências e roteiro de validação Windows.

## 2.0.0

- Aba de análise com resumo, histórico, rankings e marcações.
- Análise automática ao encerrar a captura e exportação TXT/JSON.
- Importação por pasta, JSONL ou ZIP; compatibilidade com formato 1.
- Rankings de CPU, RAM, I/O e GPU por processo, conforme disponibilidade.
- Novas leituras de I/O por processo e GPU por PID no Windows.
- Deduplicação de cache e identificação por PID + criação nas novas capturas.
- Metadados de encerramento e perdas no formato 2.
- Versão da BIOS no inventário Windows.
- Modo de demonstração, sessão simulada e quatro prints reproduzíveis.
- Testes de análise, importação, limites e qualidade dos dados.

## 1.x

- Monitoramento, sensores opcionais, gravador e marcações antes/depois.
