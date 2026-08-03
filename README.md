# picoIDE

IDE mínima que roda direto na placa: editor com realce de sintaxe, árvore de
arquivos e um terminal real, servidos por um único executável. O `index.html` e
as libs de frontend (CodeMirror, xterm.js) vão embutidos no binário, então não
há nada para instalar além do próprio arquivo — e a placa não precisa de
internet para a interface abrir.

Feita para um Banana Pi M1 (Allwinner A20, ARMv7).

## Rodando

Baixe o binário da sua arquitetura na [última release](../../releases/latest):

| Arquivo | Para | `uname -m` |
| --- | --- | --- |
| `picoide-amd64` | PC/servidor x86-64 | `x86_64` |
| `picoide-arm64` | ARM 64-bit (Raspberry Pi 3/4/5 em SO 64-bit) | `aarch64` |
| `picoide-armhf` | ARM 32-bit hard-float (Banana Pi M1) | `armv7l` |

```sh
chmod +x picoide-amd64
./picoide-amd64
```

Depois abra `http://IP-DA-MAQUINA:8080`.

Os binários são estáticos (musl), então não dependem de glibc nem de nada
instalado no destino. Rodar o de uma arquitetura na outra dá um erro
enganoso (`syntax error: unexpected word`): é o shell tentando interpretar o
ELF como script depois que o kernel recusou o `execve`. Confira o `uname -m`.

## Compilando

Para a máquina local:

```sh
cargo run
```

Estático, para distribuir (troque o alvo conforme a máquina de destino:
`x86_64-unknown-linux-musl`, `aarch64-unknown-linux-musl` ou
`armv7-unknown-linux-musleabihf`):

```sh
rustup target add armv7-unknown-linux-musleabihf
RUSTFLAGS="-C linker=rust-lld -C strip=symbols" \
  cargo build --release --target armv7-unknown-linux-musleabihf
```

No Alpine, que já é musl, o alvo nativo serve — mas o `cargo` da distro linka
dinamicamente, então para sair estático use
`RUSTFLAGS="-C target-feature=+crt-static"`.

`rust-lld` dispensa instalar um toolchain de cross-compilação C, porque o
projeto é Rust puro.

> O `index.html` é embutido no binário em tempo de compilação. Editar o HTML
> exige um `cargo build` para a mudança valer.

As libs de frontend ficam versionadas em `static/vendor/` porque o
`include_bytes!` precisa delas na hora de compilar — assim o build não depende
de npm nem de rede. Para trocar de versão, rode `static/vendor/atualizar.sh` e
confira a lista `ASSETS` do `src/main.rs`.

## Testes

```sh
pip install -r tests/e2e/requirements.txt
playwright install chromium
./tests/e2e/run.sh
```

Detalhes em [`tests/e2e/README.md`](tests/e2e/README.md).

## Como funciona

| Rota | O que faz |
| --- | --- |
| `GET /` | A interface, servida da memória (embutida no binário). |
| `GET /vendor/…` | CodeMirror e xterm.js, também embutidos. |
| `GET /api/files?path=` | Lista uma pasta. |
| `GET /api/read?path=` | Devolve o arquivo como texto: 404 se não existir, 415 se for binário. |
| `POST /api/save` | Grava o arquivo (texto do editor). |
| `GET /api/download?path=` | Baixa o arquivo, em fluxo. |
| `POST /api/upload?path=` | Recebe o arquivo no corpo, em fluxo. |
| `GET /api/ws?cwd=&sessao=` | Terminal via websocket. `cwd` é onde um shell novo nasce; `sessao` reata numa sessão existente. |

O terminal é um PTY de verdade (`portable-pty`) ligado ao xterm.js pelo
websocket. O servidor manda Ping a cada 20s para proxies reversos não
derrubarem a conexão por inatividade, e o navegador reconecta sozinho com
espera crescente se a conexão cair.

As sessões de terminal vivem no servidor, não no websocket: **fechar a aba não
mata o que está rodando**. Deixe um `cargo build` em andamento, feche a página,
volte depois — o shell é o mesmo, com o estado e o histórico recente (256 KB) de
volta na tela. O navegador guarda o id da sessão no `localStorage` e reata com
ele; um id desconhecido (servidor reiniciado) simplesmente abre um shell novo.

Duas consequências que valem saber:

- Um shell persistente mantém a pasta **dele**. Mudar a pasta na barra lateral
  não move um terminal que já existe — o `cwd` só vale para shell novo.
- Um `exit` encerra a sessão de vez, e aí sim o próximo acesso ganha um shell
  novo.

O teto é de 16 sessões simultâneas. Ao estourar, as mais antigas **sem ninguém
conectado** são recicladas; uma sessão em uso, ou com build rodando e a aba
fechada, nunca é derrubada por baixo do usuário.

A pasta aberta, as pastas expandidas da árvore e o arquivo em edição ficam no
`localStorage`, então recarregar a página não joga você de volta na raiz.

Para mover arquivos: o 📤 na barra lateral (ou arrastar da sua máquina para
cima dela) envia para a pasta aberta, e o **⬇ Baixar** da barra de cima baixa o
arquivo aberto. Clicar num binário na árvore o abre como arquivo atual — o
editor mostra só `Arquivo binário` e o salvar fica desligado, mas o download
funciona. É assim que se tira da placa o executável que o build acabou de gerar.

Os dois lados passam em fluxo, sem juntar o arquivo inteiro na memória, e o
`POST /api/upload` não tem teto de tamanho: o que limita é o disco.

A árvore se atualiza sozinha a cada 10s, mas só repinta quando a listagem
realmente mudou. Sem essa checagem a barra pisca a cada ciclo e você perde a
seleção de texto e a rolagem.

## Aviso

Não há autenticação: qualquer um que alcance a porta 8080 lê e escreve
arquivos como o usuário que rodou o processo, e tem um shell. Use só em rede
confiável.
