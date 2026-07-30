#!/usr/bin/env bash
# Repopula static/vendor a partir do npm, nas versões fixadas abaixo.
#
# Estes arquivos são versionados no repositório de propósito: o include_bytes!
# do src/main.rs precisa deles no momento da compilação, e assim o build não
# depende de ter npm nem rede. Rode isto só para trocar de versão — e depois
# confira que a lista de ASSETS do src/main.rs continua batendo com o que caiu
# aqui.
set -euo pipefail

CODEMIRROR=5.65.13
XTERM=5.3.0
XTERM_FIT=0.8.0

cd "$(dirname "$0")"
DESTINO="$PWD"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

(
  cd "$tmp"
  npm pack --silent "codemirror@$CODEMIRROR" "xterm@$XTERM" "xterm-addon-fit@$XTERM_FIT"
  for arquivo in *.tgz; do
    # codemirror-5.65.13.tgz -> codemirror ; xterm-addon-fit-0.8.0.tgz -> xterm-addon-fit
    nome="${arquivo%-*.tgz}"
    mkdir -p "$nome"
    tar xzf "$arquivo" -C "$nome" --strip-components=1
  done
)

copiar() {
  mkdir -p "$DESTINO/$(dirname "$1")"
  cp "$tmp/$1" "$DESTINO/$1"
}

copiar codemirror/LICENSE
copiar codemirror/lib/codemirror.js
copiar codemirror/lib/codemirror.css
copiar codemirror/theme/dracula.css
# O modo rust usa defineSimpleMode, que vem neste addon.
copiar codemirror/addon/mode/simple.js
for modo in javascript rust xml css htmlmixed toml; do
  copiar "codemirror/mode/$modo/$modo.js"
done

copiar xterm/LICENSE
copiar xterm/lib/xterm.js
copiar xterm/css/xterm.css

copiar xterm-addon-fit/LICENSE
copiar xterm-addon-fit/lib/xterm-addon-fit.js

echo "static/vendor atualizado: codemirror $CODEMIRROR, xterm $XTERM, xterm-addon-fit $XTERM_FIT"
