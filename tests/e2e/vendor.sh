#!/usr/bin/env bash
# Baixa do npm as mesmas libs que o index.html busca em CDN, para os testes
# rodarem sem depender de CDN. Idempotente.
set -euo pipefail

cd "$(dirname "$0")"

if [ -f vendor/xterm/lib/xterm.js ]; then
  echo "vendor/ já está populado."
  exit 0
fi

rm -rf vendor .tgz-tmp
mkdir -p vendor .tgz-tmp
cd .tgz-tmp

npm pack --silent codemirror@5.65.13 xterm@5.3.0 xterm-addon-fit@0.8.0

for arquivo in *.tgz; do
  # codemirror-5.65.13.tgz -> codemirror ; xterm-addon-fit-0.8.0.tgz -> xterm-addon-fit
  nome="${arquivo%-*.tgz}"
  mkdir -p "../vendor/$nome"
  tar xzf "$arquivo" -C "../vendor/$nome" --strip-components=1
done

cd ..
rm -rf .tgz-tmp
echo "Libs de teste em $(pwd)/vendor"
