#!/usr/bin/env bash
# Roda a suíte de ponta a ponta. Falha se qualquer teste falhar.
set -uo pipefail

cd "$(dirname "$0")"

if [ ! -f "${PICOIDE_BIN:-../../target/debug/meu-mini-ide}" ]; then
  echo "Compilando primeiro..."
  (cd ../.. && cargo build)
fi

falhou=0
for teste in test_terminal.py test_sessao.py test_arquivos.py test_arvore.py test_persistencia.py test_reconexao.py; do
  echo
  echo "=============== $teste ==============="
  if ! python3 "$teste"; then
    echo ">>> $teste FALHOU"
    falhou=1
  fi
done

echo
if [ "$falhou" != "0" ]; then
  echo "SUÍTE COM FALHAS"
  exit 1
fi
echo "SUÍTE COMPLETA PASSOU"
