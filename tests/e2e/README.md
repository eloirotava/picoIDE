# Testes de ponta a ponta

Cobrem as duas coisas que dificilmente se testa "no olho": a sessão sobreviver
a um F5 e o terminal não cair sozinho.

| Arquivo | O que garante |
| --- | --- |
| `test_terminal.py` | O shell nasce na pasta pedida, `TERM` está definido, o servidor manda Ping de keepalive (conexão viva após 50s ociosa) e fecha limpo no `exit`. |
| `test_sessao.py` | Um processo iniciado no terminal continua rodando depois de fechar a aba, reatar devolve o mesmo shell com histórico e estado, id desconhecido abre shell novo e sessão encerrada não é reatada. |
| `test_arquivos.py` | Upload e download preservam o arquivo byte a byte (3 MB aleatórios), nome com acento sobrevive ao cabeçalho HTTP, os erros dão o código certo, e abrir um binário permite baixá-lo sem que o autosave o corrompa. |
| `test_arvore.py` | O refresh automático não repinta a árvore quando nada mudou (é o que fazia a barra piscar), mas continua mostrando arquivo novo — na raiz e dentro de subpasta aberta. |
| `test_abas.py` | Dois arquivos abertos não compartilham texto, o autosave grava no que foi editado mesmo depois de trocar de aba, dois terminais são sessões distintas, fechar um não derruba o outro, as duas listas de abas voltam depois do reload, e selecionar no terminal já copia sem que o Ctrl+C deixe de interromper. |
| `test_subpasta.py` | Sobe um proxy que imita o `route /picoide*` + `strip_prefix` do Caddy — inclusive recusando o que cai fora do prefixo — e confere que assets, API e WebSocket funcionam servidos em `/picoide/`. |
| `test_persistencia.py` | Depois de um reload voltam a pasta, a árvore expandida, o arquivo aberto e o conteúdo no editor — e o terminal é o mesmo shell de antes, com variável e histórico intactos. |
| `test_reconexao.py` | Derruba o servidor de verdade e confere que o terminal reconecta sozinho; e que um `exit` não vira laço de reconexão. |

## Rodando

```bash
pip install -r requirements.txt
playwright install chromium
./run.sh
```

O `run.sh` compila o binário se precisar e roda os três testes em sequência.

## Detalhes que importam

Os testes de navegador bloqueiam todo request que não vá para o próprio
servidor (`exigir_offline`, em `helpers.py`) e falham se algum acontecer. Como
CodeMirror e xterm.js vêm embutidos no binário (`static/vendor`), a interface
tem de carregar inteira sem rede — é assim que um `<script src="https://cdn…">`
reintroduzido vira teste vermelho aqui, em vez de uma falha que só aparece na
placa do usuário.

O servidor escuta em `127.0.0.1:8080` fixo, então os testes rodam em sequência,
cada um subindo e derrubando a própria instância.

Variáveis úteis:

- `PW_CHROMIUM` — caminho de um Chromium já instalado, em vez do baixado pelo
  Playwright.
- `PICOIDE_BIN` — caminho do binário a testar (padrão: `target/debug/meu-mini-ide`).

Lembrete: o `index.html` é embutido no binário via `include_str!`, então editar
o HTML exige `cargo build` antes de testar.
