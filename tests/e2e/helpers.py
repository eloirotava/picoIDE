"""Utilidades compartilhadas pelos testes de ponta a ponta."""

import contextlib
import os
import pathlib
import socket
import subprocess
import time

RAIZ = pathlib.Path(__file__).resolve().parents[2]
BINARIO = os.environ.get("PICOIDE_BIN", str(RAIZ / "target" / "debug" / "meu-mini-ide"))
URL = os.environ.get("PICOIDE_URL", "http://127.0.0.1:8080")
PORTA = 8080


def exigir_offline(page, externas):
    """Corta todo request que não seja para o próprio servidor.

    A placa pode não ter internet, então a interface tem de se sustentar só com
    o que vem embutido no executável. Bloquear em vez de deixar passar é o que
    faz um `<script src="https://cdn...">` reintroduzido virar teste vermelho,
    e não um sucesso que só falha na placa do usuário.
    """
    def handler(route, request):
        if request.url.startswith(URL):
            route.continue_()
        else:
            externas.append(request.url)
            route.abort()

    page.route("**/*", handler)


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
