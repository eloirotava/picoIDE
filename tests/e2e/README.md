# Testes de ponta a ponta

Cobrem as duas coisas que dificilmente se testa "no olho": a sessão sobreviver
a um F5 e o terminal não cair sozinho.

| Arquivo | O que garante |
| --- | --- |
| `test_terminal.py` | O shell nasce na pasta pedida, `TERM` está definido, o servidor manda Ping de keepalive (conexão viva após 50s ociosa) e fecha limpo no `exit`. |
| `test_persistencia.py` | Depois de um reload voltam a pasta, a árvore expandida, o arquivo aberto, o conteúdo no editor e a pasta do terminal. |
| `test_reconexao.py` | Derruba o servidor de verdade e confere que o terminal reconecta sozinho; e que um `exit` não vira laço de reconexão. |

## Rodando

```bash
pip install -r requirements.txt
playwright install chromium
./run.sh
```

O `run.sh` compila o binário se precisar, baixa as libs de frontend e roda os
três testes em sequência.

## Detalhes que importam

O `index.html` busca CodeMirror e xterm.js em CDN. Os testes servem essas
mesmas versões a partir de `vendor/` (populado pelo `vendor.sh` a partir do
npm), para o resultado não depender de CDN.

O servidor escuta em `127.0.0.1:8080` fixo, então os testes rodam em sequência,
cada um subindo e derrubando a própria instância.

Variáveis úteis:

- `PW_CHROMIUM` — caminho de um Chromium já instalado, em vez do baixado pelo
  Playwright.
- `PICOIDE_BIN` — caminho do binário a testar (padrão: `target/debug/meu-mini-ide`).

Lembrete: o `index.html` é embutido no binário via `include_str!`, então editar
o HTML exige `cargo build` antes de testar.
