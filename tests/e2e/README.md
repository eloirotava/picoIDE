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
| `test_divisao.py` | Arrastar uma aba para a borda abre um painel ao lado sem recriar a tela do terminal, dois painéis são dois shells que sabem cada um do seu tamanho, dá para chegar a 2x2, a divisão volta igual depois do reload, soltar no meio junta os painéis e fechar o último terminal fecha o painel. |
| `test_subpasta.py` | Sobe um proxy que imita o `route /picoide*` + `strip_prefix` do Caddy — inclusive recusando o que cai fora do prefixo — e confere que assets, API e WebSocket funcionam servidos em `/picoide/`. |
| `test_divisorias.py` | Arrastar redimensiona a árvore e o terminal, o shell aprende o novo tamanho (conferido com `stty size`), os limites impedem sumir com um painel e os tamanhos voltam depois do reload. |
| `test_realce.py` | 20 tipos de arquivo abrem com o modo certo do CodeMirror e de fato coloridos; extensão desconhecida vira texto puro em vez de JavaScript. |
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

Cada teste sobe e derruba a própria instância, todos na mesma porta, então eles
rodam em sequência. Se a porta já estiver ocupada — numa máquina que roda um
picoIDE de verdade, por exemplo — a suíte para na hora e avisa: sem isso ela
testaria o servidor errado e falharia por motivos que não existem no binário.

Variáveis úteis:

- `PW_CHROMIUM` — caminho de um Chromium já instalado, em vez do baixado pelo
  Playwright.
- `PICOIDE_BIN` — caminho do binário a testar (padrão: `target/debug/meu-mini-ide`).
- `PICOIDE_PORTA` — porta da instância de teste (padrão: 8080). É o jeito de
  rodar a suíte numa máquina que já tem um picoIDE no ar.

Lembrete: o `index.html` é embutido no binário via `include_str!`, então editar
o HTML exige `cargo build` antes de testar.
