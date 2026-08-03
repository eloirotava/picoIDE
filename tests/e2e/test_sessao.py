"""A sessão de terminal vive no servidor, não no websocket.

O que está em jogo: fechar a aba no meio de uma compilação não pode matar a
compilação. Estes testes trabalham direto no websocket, sem navegador, porque
o que precisa ser provado é o ciclo de vida no servidor.
"""

import asyncio
import json
import subprocess
import sys

import websockets

from helpers import servidor

WS = "ws://127.0.0.1:8080/api/ws"
MARCA_PROCESSO = "sleep 4242"


async def anuncio(ws):
    """Primeira mensagem do servidor: qual sessão nos coube."""
    async with asyncio.timeout(10):
        while True:
            msg = await ws.recv()
            if isinstance(msg, str):
                try:
                    dados = json.loads(msg)
                except ValueError:
                    continue
                if dados.get("type") == "sessao":
                    return dados["id"], dados["reatou"]


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


def processos_marcados():
    saida = subprocess.run(["ps", "-eo", "args"], capture_output=True,
                           text=True).stdout
    return [l for l in saida.splitlines()
            if MARCA_PROCESSO in l and "ps -eo" not in l]


async def test_processo_sobrevive_a_fechar_a_aba():
    ws = await websockets.connect(WS, ping_interval=None)
    sessao, _ = await anuncio(ws)
    await drenar(ws, 1.5)
    # Faz as vezes de um "cargo build" longo.
    await enviar(ws, f"{MARCA_PROCESSO} &\n")
    await drenar(ws, 2)
    assert processos_marcados(), "o processo nem chegou a subir"

    await ws.close()
    await asyncio.sleep(3)
    assert processos_marcados(), \
        "o processo morreu junto com a aba: a sessão não é persistente"
    print("OK: o processo continua rodando depois de fechar a aba")
    return sessao


async def test_reatar_devolve_o_mesmo_shell(sessao):
    async with websockets.connect(f"{WS}?sessao={sessao}",
                                  ping_interval=None) as ws:
        id_novo, reatou = await anuncio(ws)
        historico = await drenar(ws, 2)
        await enviar(ws, "echo VALOR=$MARCA\n")
        saida = await drenar(ws, 3)

    assert reatou, "o servidor não reconheceu a sessão"
    assert id_novo == sessao, f"veio outra sessão: {id_novo!r}"
    assert MARCA_PROCESSO in historico, \
        f"o histórico da sessão não voltou: {historico[-300:]!r}"
    assert "VALOR=persistiu" in saida, \
        f"o shell é outro processo (a variável se perdeu): {saida[-300:]!r}"
    print("OK: reatar devolve o mesmo shell, com histórico e estado")


async def test_id_desconhecido_abre_shell_novo():
    """Servidor reiniciado deixa o navegador com um id velho; isso não é erro."""
    async with websockets.connect(f"{WS}?sessao=nao-existe-esse-id",
                                  ping_interval=None) as ws:
        id_novo, reatou = await anuncio(ws)
        await drenar(ws, 1.5)
        await enviar(ws, "echo VIVO\n")
        saida = await drenar(ws, 3)

    assert not reatou, "disse que reatou numa sessão inexistente"
    assert id_novo != "nao-existe-esse-id", "aceitou o id inventado"
    assert "VIVO" in saida, f"o shell novo não subiu: {saida!r}"
    print("OK: id desconhecido abre shell novo em vez de dar erro")


async def test_sessao_encerrada_nao_reata():
    async with websockets.connect(WS, ping_interval=None) as ws:
        sessao, _ = await anuncio(ws)
        await drenar(ws, 1.5)
        await enviar(ws, "exit\n")
        await drenar(ws, 5)

    async with websockets.connect(f"{WS}?sessao={sessao}",
                                  ping_interval=None) as ws:
        id_novo, reatou = await anuncio(ws)

    assert not reatou, "reatou numa sessão cujo shell já tinha morrido"
    assert id_novo != sessao, "reaproveitou o id de uma sessão morta"
    print("OK: sessão encerrada com exit não é reatada")


async def main():
    sessao = await test_processo_sobrevive_a_fechar_a_aba()

    # Marca o shell para o teste seguinte provar que é o mesmo processo.
    async with websockets.connect(f"{WS}?sessao={sessao}",
                                  ping_interval=None) as ws:
        await anuncio(ws)
        await enviar(ws, "MARCA=persistiu\n")
        await drenar(ws, 2)

    await test_reatar_devolve_o_mesmo_shell(sessao)
    await test_id_desconhecido_abre_shell_novo()
    await test_sessao_encerrada_nao_reata()


if __name__ == "__main__":
    with servidor():
        try:
            asyncio.run(main())
        except AssertionError as e:
            print("FALHA:", e)
            sys.exit(1)
        finally:
            subprocess.run(["pkill", "-x", "sleep"], capture_output=True)
