#!/bin/sh
set -eu
folder=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
case "$folder" in /|"$HOME"|/usr|/usr/local|/opt|/home|/tmp) exit 64 ;; esac
[ -f "$folder/.syspulse-install" ] && [ -f "$folder/SysPulse" ] || exit 64
if [ "${1:-}" != --yes ]; then
    printf '%s\n' "Remover o SysPulse de $folder? Sessões, preferências e modelos serão mantidos."
    printf '%s' 'Continuar [s/N]? '
    IFS= read -r answer
    case "$answer" in s|S|y|Y) ;; *) exit 0 ;; esac
fi
desktop="$HOME/.local/share/applications/syspulse.desktop"
if [ -f "$desktop" ] && grep -Fq "$folder/SysPulse" "$desktop"; then rm -- "$desktop"; fi
find "$folder" -type f -delete
find "$folder" -type l -delete
find "$folder" -depth -type d -empty -delete
printf '%s\n' 'SysPulse removido. Sessões e modelos foram mantidos.'
