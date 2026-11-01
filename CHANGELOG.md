# Histórico de versões

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
