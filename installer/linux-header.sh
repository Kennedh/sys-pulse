#!/bin/sh
set -eu
prefix=""
launch=yes
desktop=yes
analysis=""
automatic=no
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix) [ "$#" -ge 2 ] || exit 64; prefix=$2; shift 2 ;;
        --no-launch) launch=no; shift ;;
        --no-desktop) desktop=no; shift ;;
        --local-ai) analysis=--setup-local; shift ;;
        --online-ai) analysis=--setup-online; shift ;;
        --yes) automatic=yes; shift ;;
        --help)
            printf '%s\n' 'SysPulse @VERSION@ · instalador Linux' 'Opções: --prefix PASTA --no-launch --no-desktop --local-ai --online-ai --yes'
            exit 0 ;;
        *) printf '%s\n' "Opção desconhecida: $1"; exit 64 ;;
    esac
done
if [ -z "$prefix" ]; then
    if command -v zenity >/dev/null 2>&1 && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
        parent=$(zenity --file-selection --directory --title="Escolha onde criar a pasta SysPulse" --filename="$HOME/") || exit 0
        prefix="$parent/SysPulse"
        choice=$(zenity --list --radiolist --title="Preparar análise" --column="Usar" --column="Opção" TRUE Integrada FALSE Local FALSE Nuvem) || exit 0
        case "$choice" in Local) analysis=--setup-local ;; Nuvem) analysis=--setup-online ;; esac
    elif [ -t 0 ]; then
        printf '%s' "Pasta de instalação [$HOME/.local/opt/SysPulse]: "
        IFS= read -r prefix
        prefix=${prefix:-"$HOME/.local/opt/SysPulse"}
    else
        printf '%s\n' 'Abra em um terminal ou informe --prefix PASTA --yes.'
        exit 64
    fi
fi
if printf '%s' "$prefix" | LC_ALL=C grep -q '[[:cntrl:]]'; then exit 64; fi
if [ -L "$prefix" ]; then printf '%s\\n' 'Escolha uma pasta sem link simbólico.'; exit 64; fi
prefix=$(realpath -m -- "$prefix")
case "$prefix" in /*) ;; *) printf '%s\n' 'Informe uma pasta absoluta.'; exit 64 ;; esac
case "$prefix" in /|"$HOME"|/usr|/usr/local|/opt|/home|/tmp|/etc|/var|/bin|/sbin) printf '%s\n' 'Escolha uma subpasta exclusiva para o SysPulse.'; exit 64 ;; esac
if [ -L "$prefix" ]; then printf '%s\n' 'Escolha uma pasta sem link simbólico.'; exit 64; fi
if [ -d "$prefix" ] && [ -n "$(ls -A "$prefix")" ] && [ ! -f "$prefix/.syspulse-install" ]; then
    printf '%s\n' 'A pasta já contém arquivos de outro programa. Escolha uma pasta vazia.'
    exit 64
fi
if [ "$automatic" = no ] && [ -t 0 ]; then
    printf '%s\n' "Instalar em $prefix? A IA é opcional e seus modelos não estão neste arquivo."
    printf '%s' 'Continuar [s/N]? '
    IFS= read -r answer
    case "$answer" in s|S|y|Y) ;; *) exit 0 ;; esac
fi
staging=$(mktemp -d "${TMPDIR:-/tmp}/syspulse.XXXXXX")
trap 'rm -rf -- "$staging"' EXIT HUP INT TERM
offset=$(awk '/^__SYSPULSE_ARCHIVE__$/ {print NR + 1; exit}' "$0")
tail -n +"$offset" "$0" > "$staging/payload.tar.gz"
printf '%s  %s\n' '@SHA256@' "$staging/payload.tar.gz" | sha256sum -c -
tar -xzf "$staging/payload.tar.gz" -C "$staging"
mkdir -p -- "$prefix"
cp -R "$staging/SysPulse/." "$prefix/"
printf '%s\n' '@VERSION@' > "$prefix/.syspulse-install"
chmod +x "$prefix/SysPulse" "$prefix/uninstall.sh"
if [ "$desktop" = yes ]; then
    mkdir -p "$HOME/.local/share/applications"
    escaped=$(printf '%s' "$prefix" | sed 's/\\/\\\\/g;s/"/\\"/g;s/%/%%/g')
    printf '%s\n' '[Desktop Entry]' 'Type=Application' 'Name=SysPulse' "Exec=\"$escaped/SysPulse\"" "Icon=$prefix/_internal/assets/syspulse.svg" 'Terminal=false' 'Categories=System;Monitor;' > "$HOME/.local/share/applications/syspulse.desktop"
fi
printf '%s\n' "SysPulse instalado em $prefix." 'Modelos e sessões ficam separados da instalação.'
if [ "$launch" = yes ]; then
    if [ -n "$analysis" ]; then "$prefix/SysPulse" "$analysis" >/dev/null 2>&1 &
    else "$prefix/SysPulse" >/dev/null 2>&1 & fi
fi
exit 0
__SYSPULSE_ARCHIVE__
