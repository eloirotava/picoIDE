"""Testa o websocket do terminal: pasta inicial, TERM, keepalive e fechamento."""

import asyncio
import json
import logging
import sys

import websockets

from helpers import RAIZ, servidor

WS = "ws://127.0.0.1:8080/api/ws"
PASTA = str(RAIZ)

# Com o log em DEBUG a lib registra cada frame; usamos isso para provar que os
# Pings do keepalive chegaram de fato.
frames = []


class Espiao(logging.Handler):
    def emit(self, record):
        frames.append(record.getMessage())


async def drenar(ws, segundos):
    saida = b""
    try:
        async with asyncio.timeout(segundos):
            while True:
                msg = await ws.recv()
                saida += msg if isinstance(msg, bytes) else msg.encode()
    except (TimeoutError, websockets.ConnectionClosed):
        pass
    return saida.decode(errors="replace")


async def enviar(ws, texto):
    await ws.send(json.dumps({"type": "input", "data": texto}))


async def test_pasta_inicial_e_term():
    async with websockets.connect(f"{WS}?cwd={PASTA}", ping_interval=None) as ws:
        await drenar(ws, 1.5)
        await enviar(ws, "pwd; echo TERM=$TERM\n")
        saida = await drenar(ws, 3)
    assert PASTA in saida, f"o shell não nasceu em {PASTA}: {saida!r}"
    assert "TERM=xterm-256color" in saida, f"TERM não definido: {saida!r}"
    print("OK: o shell nasce na pasta pedida e com TERM definido")


async def test_pasta_inexistente_nao_derruba():
    async with websockets.connect(f"{WS}?cwd=/pasta/que/nao/existe", ping_interval=None) as ws:
        await drenar(ws, 1.5)
        await enviar(ws, "echo VIVO\n")
        saida = await drenar(ws, 3)
    assert "VIVO" in saida, f"o shell não subiu com pasta inválida: {saida!r}"
    print("OK: pasta inexistente cai no padrão em vez de quebrar")


async def test_exit_fecha_limpo():
    """Fechamento limpo importa: é o que faz o navegador não reabrir shell em loop."""
    async with websockets.connect(WS, ping_interval=None) as ws:
        await drenar(ws, 1.5)
        await enviar(ws, "exit\n")
        try:
            async with asyncio.timeout(10):
                while True:
                    await ws.recv()
        except websockets.ConnectionClosedOK:
            print("OK: o servidor fecha limpo quando o shell termina")
            return
        except TimeoutError:
            raise AssertionError("o servidor não fechou a conexão depois do exit")


async def test_keepalive():
    """ping_interval=None: o cliente não manda nada, então todo PING é do servidor."""
    frames.clear()
    async with websockets.connect(WS, ping_interval=None) as ws:
        await drenar(ws, 50)
        await enviar(ws, "echo AINDA_VIVO\n")
        saida = await drenar(ws, 4)
    assert "AINDA_VIVO" in saida, f"a conexão morreu ociosa: {saida!r}"
    pings = [f for f in frames if "< PING" in f]
    assert pings, "nenhum Ping veio do servidor; o keepalive não está agindo"
    print(f"OK: {len(pings)} Pings do servidor e conexão viva após 50s ociosa")


async def main():
    # No logger raiz para pegar qualquer logger interno da lib, sem depender do
    # nome exato que ela usa.
    logging.getLogger().addHandler(Espiao())
    logging.getLogger().setLevel(logging.DEBUG)
    await test_pasta_inicial_e_term()
    await test_pasta_inexistente_nao_derruba()
    await test_exit_fecha_limpo()
    await test_keepalive()
    print("=> TESTES DO TERMINAL PASSARAM")


if __name__ == "__main__":
    with servidor():
        try:
            asyncio.run(main())
        except AssertionError as e:
            print("FALHA:", e)
            sys.exit(1)
