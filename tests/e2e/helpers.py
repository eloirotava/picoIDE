"""Utilidades compartilhadas pelos testes de ponta a ponta."""

import contextlib
import os
import pathlib
import socket
import subprocess
import time

RAIZ = pathlib.Path(__file__).resolve().parents[2]
BINARIO = os.environ.get("PICOIDE_BIN", str(RAIZ / "target" / "debug" / "meu-mini-ide"))
# Numa máquina que já roda um picoIDE de verdade, a 8080 está ocupada; o
# PICOIDE_PORTA move a suíte inteira de porta sem mexer no que está no ar.
PORTA = int(os.environ.get("PICOIDE_PORTA", "8080"))
URL = os.environ.get("PICOIDE_URL", f"http://127.0.0.1:{PORTA}")
WS = URL.replace("http://", "ws://").replace("https://", "wss://") + "/api/ws"


def exigir_offline(page, externas):
    """Corta todo request que não seja para o próprio servidor.

    O servidor pode não ter internet, então a interface tem de se sustentar só com
    o que vem embutido no executável. Bloquear em vez de deixar passar é o que
    faz um `<script src="https://cdn...">` reintroduzido virar teste vermelho,
    e não um sucesso que só falha no host do usuário.
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
    # Sem esta checagem, um picoIDE já no ar faz a espera abaixo terminar na
    # hora e a suíte inteira testar o servidor errado — falhando por motivos
    # que não existem no binário que se queria testar.
    if porta_ocupada():
        raise SystemExit(
            f"A porta {PORTA} já está ocupada por outro processo.\n"
            f"Pare-o ou rode com PICOIDE_PORTA=<outra>.")
    proc = subprocess.Popen([BINARIO, "--porta", str(PORTA)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

# Com várias abas de terminal, as telas inativas continuam montadas; e com a
# tela dividida há mais de uma visível ao mesmo tempo. O alvo é a do painel em
# foco, que é o mesmo que o window.term dos testes enxerga.
FOCAR_TERMINAL = """() => {
    const t = document.querySelector('.grupo-terminal.foco .terminal-tela.ativa .xterm-helper-textarea')
           || document.querySelector('.terminal-tela.ativa .xterm-helper-textarea')
           || document.querySelector('#terminal-container .xterm-helper-textarea');
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
