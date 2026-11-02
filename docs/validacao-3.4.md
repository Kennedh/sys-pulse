# Validação 3.4 — verificação GPU

Data: 01/11/2026. Windows, Python 3.13.1, PySide6 e NVIDIA RTX 3050. Os resultados descrevem esta máquina e os parâmetros usados; não certificam estabilidade de outros sistemas.

## Suíte e interface

- 270 testes passaram no Windows.
- Validação de opções, padrões, endereços lógicos, contagem de palavras/bits/pixels, orçamento com reserva, cobertura parcial e limites de resolução.
- Relatório e resumo de IA conferidos para priorizar divergências sem enviar imagens, caminhos ou endereços dos exemplos.
- Saída anormal do auxiliar prevalece sobre um resultado previamente marcado como concluído.
- Interface demonstrativa recriada com cena + VRAM em 4K e cobertura parcial, identificada como dados simulados.
- Os testes unitários de imagem usam QImage. Os testes OpenGL reais abaixo foram executados separadamente em hardware; a suíte dos runners não comprova funcionamento físico de GPU.

## GPU real no código-fonte

| Validação | Resultado |
|---|---|
| Cena 1280×720, geometria, 25%, 3 s | 86 quadros, três pares de imagens e três padrões conhecidos; nenhuma divergência |
| Cena + 16 MiB, 5 s, antes do ajuste do lote de verificações | 137 quadros, dez verificações de imagem e 64 de memória; 16 passagens e nenhum ciclo completo; cobertura parcial |
| Autoteste de 16 MiB | 70 passagens, um ciclo, 280 leituras de blocos e 1120 MiB de leituras acumuladas em aproximadamente 2,09 s; nenhuma divergência antes da injeção |
| Cena 3840×2160, 3 s | Resolução efetiva 4K, três pares e três padrões conhecidos; nenhuma divergência |
| VRAM 16 MiB, 8 s | 431 leituras, 107 passagens, um ciclo, 1724 MiB de leituras acumuladas; 16 MiB de endereços únicos e cobertura completa do orçamento testado |

O automático e os orçamentos elevados não foram usados para carregar toda a memória desta máquina. Os testes acima são curtos. O teste exclusivo de VRAM mantém uma prévia leve e não apresenta seus FPS como benchmark de memória.

## Executável Windows

Build local concluído com PyInstaller e Inno Setup. A validação do pacote conferiu ZIP, abertura do aplicativo e auxiliares CPU/RAM; a instalação já existente nesta máquina foi preservada. As cargas abaixo foram executadas por dist/SysPulse/SysPulse.exe, sem importar o código-fonte do verificador:

| Modo | Resultado |
|---|---|
| Cena + VRAM, 1280×720, 16 MiB, 5 s | 141 verificações: dez de imagem e 131 leituras de memória; 32 passagens e nenhum ciclo; nenhuma divergência, cobertura parcial |
| VRAM, 16 MiB, 8 s | 439 leituras, 109 passagens, um ciclo, 1756 MiB acumulados; 16 MiB únicos, nenhuma divergência e cobertura completa do orçamento |
| Cena 3840×2160, 3 s | Resolução efetiva 4K, três pares e três padrões conhecidos; nenhuma divergência |

## Falhas sintéticas

O autoteste altera um bit no buffer OpenGL depois da escrita. A comparação detectou exatamente uma palavra e um bit divergentes. Uma imagem alterada em um pixel também produziu exatamente um pixel divergente. A execução registra synthetic_faults=true; isso não representa defeito real do hardware.

O teste do auxiliar completo altera um pixel da segunda renderização. A última repetição interrompeu a carga em aproximadamente 0,62 s, gravou estado failed e um erro de verificação e preservou artefato-referencia.png e artefato-observado.png. O registro identifica synthetic_fault=true.

A primeira execução desse cenário revelou encerramento imediato do Qt dentro da renderização, com falha nativa antes de gravar o resultado. O encerramento passou a ser agendado para depois da chamada de renderização. As repetições preservaram JSON e imagens e retornaram a falha esperada sem travamento nativo.

## Reproduzir

Na raiz do projeto, com o ambiente preparado:

~~~powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe tools/validate_gpu.py --self-test
.venv\Scripts\python.exe tools/validate_gpu.py --fault-test
.venv\Scripts\python.exe tools/validate_gpu.py --mode scene --resolution 3840x2160 --duration 3
.venv\Scripts\python.exe tools/validate_gpu.py --mode vram --duration 8
.venv\Scripts\python.exe tools/validate_gpu.py --executable dist/SysPulse/SysPulse.exe --mode combined --duration 5
~~~

A ferramenta limita a validação curta a 30 s e 16–64 MiB. Resultados reais ficam em diagnosticos/validacao-3.4, fora do Git. A interface permite sessões maiores e um orçamento diferente.

## Interpretação e limites

A escrita ocorre na GPU por transform feedback; toda a leitura de cada bloco de 4 MiB é comparada na CPU. Cada padrão percorre todos os buffers antes de mudar de fase. Os 70 padrões incluem zeros, uns, AA/55, endereços/inversos e 32 bits móveis ligados/desligados.

Cobertura completa exige todo o orçamento efetivo lido e um ciclo dos 70 padrões concluído. Bytes acumulados incluem repetições e não representam capacidade física adicional. O orçamento solicitado pode ser reduzido para manter a reserva; o relatório informa alvo e alocação.

OpenGL não garante residência física exclusiva em VRAM. Memória compartilhada, paginação, regiões reservadas e o adaptador escolhido pelo driver limitam a conclusão. Não há promessa de teste integral da VRAM física.

A comparação 3D detecta divergências entre duas imagens do mesmo instante; um erro persistente idêntico nas duas pode passar. Um padrão inteiro de 128×128 fornece comparação adicional com referência calculada na CPU. Isso não cobre todo o espaço de falhas de shaders, rasterização ou apresentação.

A carga solicita parada na primeira divergência detectada. Exemplos e PNGs são limitados; não há gravação contínua de vídeo. Leitura de imagens e buffers usa CPU, tráfego e sincronização e interfere no frametime. Os contadores informam esse custo. Divergência localiza evidência no caminho gráfico; isoladamente não identifica GPU, RAM, driver ou outra peça como causa.

As validações de empacotamento e os quatro ambientes nativos são registradas após concluir os respectivos builds.

## Referências da implementação

- [Qt: QOpenGLFramebufferObject](https://doc.qt.io/qt-6.8/qopenglframebufferobject.html).
- [Khronos: glGetBufferSubData](https://wikis.khronos.org/opengl/GLAPI/glGetBufferSubData).
- [Khronos: transform feedback](https://wikis.khronos.org/opengl/Transform_Feedback).
