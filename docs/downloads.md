# Downloads e instalação

Os instaladores e pacotes portáteis ficam em [GitHub Releases → Assets](https://github.com/Kennedh/sys-pulse/releases/latest). O código-fonte ZIP/TAR gerado automaticamente pelo GitHub não substitui o instalador.

## Windows

Baixe SysPulse-3.4.0-Windows-x64-Setup.exe e abra. Escolha a pasta, o grupo de atalhos e, se quiser, um atalho na área de trabalho. A instalação é por usuário e a pasta precisa permitir escrita. O aplicativo não exige Python instalado.

Na etapa Análise inicial, escolha análise integrada, preparação de IA local ou IA anônima. Ao abrir o SysPulse, a configuração inicial confirma a escolha. Downloads precisam de confirmação na interface. A tarefa opcional LatencyMon abre a tela de ferramentas após a instalação; o download, a assinatura e a licença são tratados separadamente pelo instalador original.

Para usar sem instalação, extraia o ZIP portátil inteiro e mantenha _internal junto a SysPulse.exe. Para desinstalar a versão instalada, use Aplicativos instalados do Windows ou o atalho de desinstalação.

O instalador não tem certificado comercial. Confira a origem e o SHA-256; o Windows pode informar editor desconhecido. A captura avançada solicita UAC separadamente.

## Linux

Use uma distribuição desktop compatível com a base Ubuntu 22.04/glibc 2.35, arquitetura x64. O Qt depende de bibliotecas gráficas do sistema. Em derivados de Ubuntu, as dependências usadas na validação são libegl1, libopengl0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1 e libxcb-render-util0.

Permita executar o arquivo Setup.run e abra em um terminal:

```sh
chmod +x SysPulse-3.4.0-Linux-x64-Setup.run
./SysPulse-3.4.0-Linux-x64-Setup.run
```

Com Zenity instalado, o instalador oferece seleção gráfica de pasta e análise. Sem ele, o terminal solicita a pasta. Também é possível informar:

```sh
./SysPulse-3.4.0-Linux-x64-Setup.run --prefix "$HOME/Aplicativos/SysPulse" --yes
```

A pasta deve ser exclusiva do SysPulse. O instalador verifica o payload com SHA-256 e cria uma entrada no menu de aplicativos. Para preparar IA na primeira abertura, use --local-ai ou --online-ai. Para remover, execute uninstall.sh na pasta instalada; sessões e modelos externos são preservados.

O TAR.GZ é a alternativa portátil. Bibliotecas do sistema não são incluídas automaticamente.

## macOS

Escolha arm64 para Apple Silicon ou x64 para Intel. O PKG instala em /Applications usando o instalador nativo. Para escolher uma pasta diferente, use o DMG e arraste SysPulse.app para a pasta desejada.

A primeira abertura oferece análise integrada, modelo local ou IA anônima. Os pacotes ainda não são notarizados pela Apple. Confira a origem e o checksum; a liberação, quando necessária, é feita nos controles normais de Privacidade e Segurança do sistema.

O pacote declara macOS 13 como mínimo, mas a validação nativa de build ocorre em macOS 15. O Ollama atual requer macOS 14 ou superior. Sensores Apple e dados detalhados de drivers não são medidos pelas fontes Windows/NVML.

Para remover o aplicativo, retire SysPulse.app da pasta de instalação. Preferências, capturas e modelos ficam fora do bundle e são mantidos.

## Conectar um serviço que já usa

Em Configurações → Conectar minha IA, escolha o serviço e siga a autenticação mostrada. OpenRouter oferece autorização pelo navegador; conta Ollama usa o login do próprio runtime. Os demais conectores por API têm link para o painel de chaves e busca automática de modelos.

Uma credencial fica em memória por padrão. Guardar no cofre do Windows é opcional. Em Linux/macOS, a credencial precisa ser informada novamente ao abrir o aplicativo. Preferências de serviço, endereço, formato e modelo são preservadas; a chave não é escrita nas preferências comuns.

Outro serviço compatível aceita endereço base e os formatos Chat Completions, Responses, Messages ou Ollama. Um catálogo ausente permite informar o ID manualmente. Conectar e consultar modelos não solicita inferência.

## Modelos e espaço

O instalador distribui o SysPulse e as bibliotecas necessárias. Não inclui pesos de IA nem instala modelos em segundo plano.

Ollama é opcional e tem tamanho e requisitos próprios. Seu instalador/runtime pode ocupar vários GB além dos modelos. O botão Baixar Ollama abre a distribuição oficial do sistema; a instalação é concluída por ela.

Modelos ficam no armazenamento do Ollama. No Windows por usuário, o padrão usual é a pasta .ollama/models do usuário; no macOS, a pasta .ollama; no Linux como serviço, o diretório depende da conta do serviço. OLLAMA_MODELS permite escolher outro local no servidor. Consulte a [documentação oficial](https://docs.ollama.com/faq#where-are-models-stored).

Mudar a pasta de instalação do SysPulse não move o armazenamento do Ollama. Desinstalar o SysPulse não desinstala esse programa nem apaga modelos. O download de Qwen 0.6B é aproximadamente 523 MB, Llama 1B 1,3 GB e Llama 3B 2 GB; memória durante inferência é adicional.

A IA anônima não baixa pesos, não exige Ollama e não pede login ou chave. Ela depende da conexão e da capacidade comunitária disponível.

## Integridade e atualização

Cada release contém SHA256SUMS.txt. No PowerShell, confira um arquivo com Get-FileHash -Algorithm SHA256 e compare o resultado. No Linux use sha256sum; no macOS, shasum -a 256.

Feche o SysPulse antes de atualizar. Instale a nova versão na mesma pasta ou substitua o pacote portátil inteiro. Capturas antigas continuam compatíveis. Não existe atualização silenciosa de código ou modelos.

Os builds de Windows, Linux, macOS Intel e Apple Silicon são executados separadamente pelo workflow do repositório. A publicação exige que testes e verificações dos pacotes nativos passem. Falha em um sistema impede a publicação automática conjunta.
