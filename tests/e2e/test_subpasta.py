"""Rodar atrás de um proxy em subpasta (https://host/picoide/).

O caso: um Caddy com `uri strip_prefix /picoide` na frente. O servidor continua
vendo `/api/...` normal — quem precisa se virar é a página, que não pode montar
os endereços a partir da raiz do site, senão pede `/vendor/...` e leva 404.

Por isso o teste sobe um proxy de verdade, que tira o prefixo e repassa também
o WebSocket: uma checagem só no HTML não pegaria o terminal.
"""

import asyncio
import pathlib
import threading

from playwright.sync_api import sync_playwright

from helpers import PORTA, abrir_navegador, relatar, servidor

PREFIXO = "/picoide"
# Porta só do proxy do teste; se a instância estiver justamente nela
# (PICOIDE_PORTA=8099), o proxy se muda para os dois não brigarem.
PORTA_PROXY = 8099 if PORTA != 8099 else 8100
ALVO = ("127.0.0.1", PORTA)


async def _encanar(origem, destino):
    try:
        while True:
            dados = await origem.read(65536)
            if not dados:
                break
            destino.write(dados)
            await destino.drain()
    except Exception:
        pass
    finally:
        try:
            destino.close()
        except Exception:
            pass


async def _atender(cliente_r, cliente_w):
    try:
        cabecalho = await cliente_r.readuntil(b"\r\n\r\n")
    except Exception:
        cliente_w.close()
        return

    linhas = cabecalho.split(b"\r\n")
    metodo, caminho, versao = linhas[0].split(b" ", 2)

    # O `route /picoide*` do Caddy só trata o que casa o prefixo: o que cai
    # fora dele não chega ao picoIDE. Recusar aqui é o que faz este teste
    # valer — um proxy que repassasse tudo deixaria passar exatamente o bug
    # que ele existe para pegar (pedir /vendor/... a partir da raiz).
    if not caminho.startswith(PREFIXO.encode()):
        cliente_w.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n"
                        b"Connection: close\r\n\r\n")
        await cliente_w.drain()
        cliente_w.close()
        return

    # E isto é o `uri strip_prefix /picoide`.
    caminho = caminho[len(PREFIXO):] or b"/"
    if not caminho.startswith(b"/"):
        caminho = b"/" + caminho

    virou_ws = any(l.lower().startswith(b"upgrade:") for l in linhas)
    if not virou_ws:
        # Sem keep-alive o proxy pode ser burro: cada requisição é uma conexão,
        # e não há requisição seguinte para reescrever nesta.
        linhas = [l for l in linhas if not l.lower().startswith(b"connection:")]
        linhas.insert(1, b"Connection: close")

    linhas[0] = b" ".join([metodo, caminho, versao])
    alvo_r, alvo_w = await asyncio.open_connection(*ALVO)
    alvo_w.write(b"\r\n".join(linhas))
    await alvo_w.drain()

    await asyncio.gather(_encanar(alvo_r, cliente_w), _encanar(cliente_r, alvo_w))


def subir_proxy():
    """Sobe o proxy numa thread própria e devolve como pará-lo."""
    pronto = threading.Event()
    laco = None

    async def principal():
        nonlocal laco
        laco = asyncio.get_running_loop()
        servidor_proxy = await asyncio.start_server(_atender, "127.0.0.1", PORTA_PROXY)
        pronto.set()
        async with servidor_proxy:
            await servidor_proxy.serve_forever()

    def rodar():
        # Parar o laço de fora faz o asyncio.run levantar; não é falha do teste.
        try:
            asyncio.run(principal())
        except RuntimeError:
            pass

    thread = threading.Thread(target=rodar, daemon=True)
    thread.start()
    pronto.wait(timeout=10)
    return lambda: laco.call_soon_threadsafe(laco.stop)


def run(pw, falhas):
    antes = len(falhas)
    base = f"http://127.0.0.1:{PORTA_PROXY}{PREFIXO}/"

    navegador = abrir_navegador(pw)
    page = navegador.new_page()
    erros, ruins = [], []
    page.on("pageerror", lambda e: erros.append(str(e)))
    page.on("response", lambda r: ruins.append(f"{r.status} {r.url}")
            if r.status >= 400 else None)

    page.goto(base)

    # A árvore só aparece se /picoide/api/files respondeu: prova que o fetch
    # foi montado a partir da subpasta, e não da raiz.
    try:
        page.wait_for_selector("#file-list .file-item", timeout=20000)
    except Exception:
        falhas.append("a árvore não carregou atrás da subpasta")

    # O CodeMirror só existe se os assets relativos vieram; se tivessem ido
    # para a raiz, a página abriria sem editor nenhum.
    if not page.evaluate("() => !!window.CodeMirror"):
        falhas.append("os assets não carregaram na subpasta (CodeMirror ausente)")
    if not page.evaluate("() => !!window.Terminal"):
        falhas.append("o xterm não carregou na subpasta")

    # E o terminal, que é o único que passa por WebSocket. Se os assets não
    # vieram, nem existe terminal na página: reportamos isso em vez de deixar
    # estourar um traceback que não diz nada.
    page.wait_for_timeout(4000)
    try:
        page.evaluate("() => document.querySelector("
                      "'.terminal-tela.ativa .xterm-helper-textarea').focus()")
        page.keyboard.type("echo FUNCIONA_NA_SUBPASTA\n")
        page.wait_for_timeout(2500)
        tela = page.evaluate("""() => { const t = window.term; const l = [];
            for (let i = 0; i < t.buffer.active.length; i++)
                l.push(t.buffer.active.getLine(i).translateToString(true));
            return l.join('\\n'); }""")
    except Exception as e:
        tela = ""
        falhas.append(f"o terminal nem chegou a existir na subpasta: {e}")
    if "FUNCIONA_NA_SUBPASTA" not in tela:
        falhas.append(f"o terminal não funcionou atrás da subpasta:\n{tela[-300:]}")

    if erros:
        falhas.append(f"erros de JS na página: {erros}")
    if ruins:
        falhas.append(f"requisições com erro: {ruins[:5]}")

    navegador.close()
    if len(falhas) == antes:
        print("OK: a interface inteira funciona servida em /picoide/")


if __name__ == "__main__":
    falhas = []
    with servidor():
        parar = subir_proxy()
        try:
            with sync_playwright() as pw:
                run(pw, falhas)
        finally:
            parar()
    relatar(falhas, "rodar atrás de um proxy em subpasta")
