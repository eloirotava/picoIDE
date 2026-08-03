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

A porta padrão é 8080; para trocar, `--porta N` (ou `-p N`, ou só o número):

```sh
./picoide-amd64 --porta 9090
```

Porta inválida ou argumento desconhecido é erro duro, com saída 2 — escutar
numa porta diferente da pedida faria você procurar o problema no lugar errado.

Os binários são estáticos (musl), então não dependem de glibc nem de nada
instalado no destino. Rodar o de uma arquitetura na outra dá um erro
enganoso (`syntax error: unexpected word`): é o shell tentando interpretar o
ELF como script depois que o kernel recusou o `execve`. Confira o `uname -m`.

## Compilando

Para a máquina local:

```sh
cargo run
```

### Estático, para a própria máquina

Não precisa de flag de linker nenhuma — o linker do sistema dá conta. Mas o
`--target` é obrigatório, mesmo sendo a arquitetura em que você já está:

```sh
RUSTFLAGS="-C target-feature=+crt-static" \
  cargo build --release --target "$(rustc -vV | sed -n 's/^host: //p')"
# binário em target/<triple>/release/meu-mini-ide
```

Sem o `--target`, o `RUSTFLAGS` também vale para os *proc-macros*, que são
compilados para a máquina do build e precisam ser bibliotecas dinâmicas — o
`+crt-static` torna isso impossível:

```
error: cannot produce proc-macro for `async-trait` as the target
       `x86_64-unknown-linux-musl` does not support these crate types
```

Com o `--target` explícito o cargo aplica as flags só ao alvo, e os proc-macros
compilam normalmente.

No Alpine é este o caminho: a distro já é musl, e o `+crt-static` é necessário
porque o `cargo` de lá linka dinamicamente por padrão. Se faltar linker,
`apk add build-base`. O `$(rustc -vV ...)` evita errar o nome do alvo: o Rust
da distro se chama `x86_64-alpine-linux-musl`, e o do rustup,
`x86_64-unknown-linux-musl`.

### Estático, cross-compilando para outra arquitetura

```sh
rustup target add armv7-unknown-linux-musleabihf
RUSTFLAGS="-C linker=rust-lld -C strip=symbols" \
  cargo build --release --target armv7-unknown-linux-musleabihf
```

Alvos: `x86_64-unknown-linux-musl`, `aarch64-unknown-linux-musl`,
`armv7-unknown-linux-musleabihf`.

O `-C linker=rust-lld` **só serve aqui**, e existe para dispensar um toolchain
de cross-compilação C, já que o projeto é Rust puro. Sem ele o `cargo` chama o
`cc` do sistema, que aciona o linker do host e não entende objeto de outra
arquitetura:

```
/usr/bin/ld: crt1.o: Relocations in generic ELF (EM: 183)
/usr/bin/ld: crt1.o: error adding symbols: file in wrong format
```

> **Não use essa flag em build nativo.** O `rust-lld` não fica no `PATH`: ele
> vem dentro do toolchain do rustup. Com o Rust da distro (`apk add rust`) ele
> não existe, e o build morre com `error: linker \`rust-lld\` not found`. Para
> cross-compilar do Alpine, instale o rustup em vez do pacote da distro.

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

## Atrás de um proxy reverso

Funciona tanto na raiz de um host quanto numa subpasta. Todos os endereços da
interface são montados a partir da pasta em que a página foi servida, então o
servidor não precisa saber o prefixo — quem o remove é o proxy.

```caddy
la.rotava.com {
    basic_auth {
        eloi $2a$14$...
    }

    # A barra final é obrigatória: sem ela o navegador resolve os endereços
    # relativos a partir da raiz do site e nada é encontrado.
    redir /picoide /picoide/

    route /picoide/* {
        uri strip_prefix /picoide
        reverse_proxy 10.0.3.174:8080
    }
}
```

Dois tropeços comuns:

- **O prefixo do `strip_prefix` tem de ser o mesmo do `route`.** Se não bater,
  o picoIDE recebe `/picoide/...`, rota que ele não tem, e responde 404 — o que
  parece "o proxy não está chegando no servidor".
- **Basic auth atrapalha o WebSocket:** nem todo navegador manda o header
  `Authorization` no handshake. Se a página abrir mas o terminal ficar em
  "Conexão perdida", é por aí. Autenticação por cookie se dá melhor com WS.

## Como funciona

| Rota | O que faz |
| --- | --- |
| `GET /` | A interface, servida da memória (embutida no binário). |
| `GET /icone.svg` | O ícone da aba, também embutido. |
| `GET /vendor/…` | CodeMirror e xterm.js, também embutidos. |
| `GET /api/files?path=` | Lista uma pasta. |
| `GET /api/read?path=` | Devolve o arquivo como texto: 404 se não existir, 415 se for binário. |
| `POST /api/save` | Grava o arquivo (texto do editor). |
| `GET /api/download?path=` | Baixa o arquivo, em fluxo. |
| `POST /api/upload?path=` | Recebe o arquivo no corpo, em fluxo. |
| `GET /api/ws?cwd=&sessao=` | Terminal via websocket. `cwd` é onde um shell novo nasce; `sessao` reata numa sessão existente. |
| `POST /api/terminal/encerrar?sessao=` | Encerra a sessão de vez (fechar a aba do terminal). |

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

Dá para abrir **vários arquivos e vários terminais**, cada um na sua aba. Cada
arquivo tem o seu próprio `Doc` do CodeMirror, então cursor, seleção e histórico
de desfazer não se misturam ao alternar; e o autosave grava no arquivo que foi
editado mesmo que você já tenha trocado de aba. Cada terminal é uma sessão
independente no servidor.

Fechar a aba de um terminal (o `×`) **encerra aquele shell**, diferente de
fechar a página, que o deixa rodando. As duas listas de abas ficam no
`localStorage`, junto com a pasta aberta e as pastas expandidas da árvore, então
recarregar a página não joga você de volta na raiz nem fecha nada.

Para mover arquivos: o 📤 na barra lateral (ou arrastar da sua máquina para
cima dela) envia para a pasta aberta, e o **⬇ Baixar** da barra de cima baixa o
arquivo aberto. Clicar num binário na árvore o abre como arquivo atual — o
editor mostra só `Arquivo binário` e o salvar fica desligado, mas o download
funciona. É assim que se tira da placa o executável que o build acabou de gerar.

Os dois lados passam em fluxo, sem juntar o arquivo inteiro na memória, e o
`POST /api/upload` não tem teto de tamanho: o que limita é o disco.

No terminal, **selecionar já copia** (como no ttyd), e colar é `Ctrl+V`. O
`Ctrl+C` fica intocado: no terminal ele interrompe o processo, e sobrecarregar
essa tecla deixaria ambígua a mais importante das duas funções.

Acessar a placa por `http://IP` não é contexto seguro, e ali a Clipboard API do
navegador nem existe — por isso o copiar tem um caminho alternativo, que é
justamente o que roda no uso real.

A árvore se atualiza sozinha a cada 10s, mas só repinta quando a listagem
realmente mudou. Sem essa checagem a barra pisca a cada ciclo e você perde a
seleção de texto e a rolagem.

## Aviso

Não há autenticação: qualquer um que alcance a porta 8080 lê e escreve
arquivos como o usuário que rodou o processo, e tem um shell. Use só em rede
confiável.
