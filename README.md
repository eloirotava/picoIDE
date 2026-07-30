# picoIDE

IDE mínima que roda direto na placa: editor com realce de sintaxe, árvore de
arquivos e um terminal real, servidos por um único executável. O `index.html` e
as libs de frontend (CodeMirror, xterm.js) vão embutidos no binário, então não
há nada para instalar além do próprio arquivo — e a placa não precisa de
internet para a interface abrir.

Feita para um Banana Pi M1 (Allwinner A20, ARMv7).

## Rodando

Baixe o `picoide-armhf` da [última release](../../releases/latest) e execute:

```sh
chmod +x picoide-armhf
./picoide-armhf
```

Depois abra `http://IP-DA-PLACA:8080`.

O binário é estático (musl), então não depende de glibc nem de nada instalado
na placa.

## Compilando

Para a máquina local:

```sh
cargo run
```

Para a placa (ARMv7 hard-float, estático):

```sh
rustup target add armv7-unknown-linux-musleabihf
RUSTFLAGS="-C linker=rust-lld -C strip=symbols" \
  cargo build --release --target armv7-unknown-linux-musleabihf
```

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
| `GET /api/read?path=` | Devolve o arquivo, ou 404 se ele não existir. |
| `POST /api/save` | Grava o arquivo. |
| `GET /api/ws?cwd=` | Terminal via websocket, com o shell nascendo em `cwd`. |

O terminal é um PTY de verdade (`portable-pty`) ligado ao xterm.js pelo
websocket. O servidor manda Ping a cada 20s para proxies reversos não
derrubarem a conexão por inatividade, e o navegador reconecta sozinho com
espera crescente se a conexão cair.

A pasta aberta, as pastas expandidas da árvore e o arquivo em edição ficam no
`localStorage`, então recarregar a página não joga você de volta na raiz.

## Aviso

Não há autenticação: qualquer um que alcance a porta 8080 lê e escreve
arquivos como o usuário que rodou o processo, e tem um shell. Use só em rede
confiável.
