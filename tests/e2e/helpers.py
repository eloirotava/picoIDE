"""Utilidades compartilhadas pelos testes de ponta a ponta."""

import contextlib
import os
import pathlib
import socket
import subprocess
import time

RAIZ = pathlib.Path(__file__).resolve().parents[2]
VENDOR = pathlib.Path(__file__).resolve().parent / "vendor"
BINARIO = os.environ.get("PICOIDE_BIN", str(RAIZ / "target" / "debug" / "meu-mini-ide"))
URL = os.environ.get("PICOIDE_URL", "http://127.0.0.1:8080")
PORTA = 8080

# O index.html busca as libs em CDN. Nos testes servimos as mesmas versões a
# partir de tests/e2e/vendor (populado pelo vendor.sh), para o resultado não
# depender da rede nem de um CDN fora do ar.
ASSETS = {
    "**/codemirror.min.css": ("codemirror/lib/codemirror.css", "text/css"),
    "**/theme/dracula.min.css": ("codemirror/theme/dracula.css", "text/css"),
    "**/codemirror.min.js": ("codemirror/lib/codemirror.js", "application/javascript"),
    "**/addon/mode/simple.min.js": ("codemirror/addon/mode/simple.js", "application/javascript"),
    "**/javascript.min.js": ("codemirror/mode/javascript/javascript.js", "application/javascript"),
    "**/rust.min.js": ("codemirror/mode/rust/rust.js", "application/javascript"),
    "**/mode/xml/xml.min.js": ("codemirror/mode/xml/xml.js", "application/javascript"),
    "**/mode/css/css.min.js": ("codemirror/mode/css/css.js", "application/javascript"),
    "**/htmlmixed.min.js": ("codemirror/mode/htmlmixed/htmlmixed.js", "application/javascript"),
    "**/toml.min.js": ("codemirror/mode/toml/toml.js", "application/javascript"),
    "**/css/xterm.css": ("xterm/css/xterm.css", "text/css"),
    "**/lib/xterm.js": ("xterm/lib/xterm.js", "application/javascript"),
    "**/xterm-addon-fit.js": ("xterm-addon-fit/lib/xterm-addon-fit.js", "application/javascript"),
}


def instalar_rotas(page):
    faltando = [str(VENDOR / rel) for rel, _ in ASSETS.values()
                if not (VENDOR / rel).is_file()]
    if faltando:
        raise SystemExit(
            "Faltam as libs de teste. Rode tests/e2e/vendor.sh primeiro.\n"
            "Ausente: " + faltando[0])

    def fabrica(caminho, tipo):
        def handler(route):
            route.fulfill(status=200, body=caminho.read_bytes(), content_type=tipo)
        return handler

    for padrao, (rel, tipo) in ASSETS.items():
        page.route(padrao, fabrica(VENDOR / rel, tipo))


def abrir_navegador(pw):
    # No CI o chromium vem do "playwright install"; localmente dá para apontar
    # um binário já existente com PW_CHROMIUM.
    caminho = os.environ.get("PW_CHROMIUM")
    if caminho:
        return pw.chromium.launch(executable_path=caminho)
    return pw.chromium.launch()


def porta_ocupada():
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORTA)) == 0


def subir_servidor():
    if not os.path.isfile(BINARIO):
        raise SystemExit(f"Binário não encontrado: {BINARIO}\nRode: cargo build")
    proc = subprocess.Popen([BINARIO], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    for _ in range(60):
        if porta_ocupada():
            return proc
        if proc.poll() is not None:
            raise SystemExit("O servidor morreu ao subir.")
        time.sleep(0.5)
    proc.kill()
    raise SystemExit(f"O servidor não abriu a porta {PORTA}.")


def derrubar_servidor(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)
        if proc.poll() is None:
            proc.kill()


@contextlib.contextmanager
def servidor():
    proc = subir_servidor()
    try:
        yield proc
    finally:
        derrubar_servidor(proc)


# --- terminal ---

LER_BUFFER = """() => {
    const t = (typeof term !== 'undefined') ? term : null;
    if (!t) return '(sem term)';
    const linhas = [];
    for (let i = 0; i < t.buffer.active.length; i++) {
        linhas.push(t.buffer.active.getLine(i).translateToString(true));
    }
    return linhas.join('\\n');
}"""

FOCAR_TERMINAL = """() => {
    const t = document.querySelector('#terminal-container .xterm-helper-textarea');
    if (t) t.focus();
}"""


def ler_terminal(page):
    return page.evaluate(LER_BUFFER)


def digitar(page, texto):
    page.evaluate(FOCAR_TERMINAL)
    page.keyboard.type(texto)


def relatar(falhas, nome):
    if falhas:
        for f in falhas:
            print("FALHA:", f)
        raise SystemExit(1)
    print(f"OK: {nome}")
