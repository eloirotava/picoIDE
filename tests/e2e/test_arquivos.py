"""Subir e baixar arquivos.

O caso que motiva: tirar da placa um binário que o build acabou de gerar, e
colocar um arquivo lá sem precisar de scp. Por isso os testes usam conteúdo
binário aleatório e conferem byte a byte — um bug de encoding ou um truncamento
no meio do caminho passaria despercebido com texto curto.
"""

import os
import pathlib
import sys
import tempfile
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

from helpers import URL, abrir_navegador, exigir_offline, relatar, servidor

TAMANHO = 3_000_000  # grande o bastante para sair em vários pedaços


def url_de(rota, caminho):
    return f"{URL}/api/{rota}?path=" + urllib.parse.quote(str(caminho))


def subir(caminho, dados):
    req = urllib.request.Request(url_de("upload", caminho), data=dados,
                                 method="POST")
    with urllib.request.urlopen(req) as r:
        return r.status, r.read().decode()


def baixar(caminho):
    with urllib.request.urlopen(url_de("download", caminho)) as r:
        return r.status, r.headers.get("Content-Disposition"), r.read()


def codigo_do_erro(rota, caminho, dados=None):
    try:
        req = urllib.request.Request(url_de(rota, caminho), data=dados,
                                     method="POST" if dados is not None else "GET")
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def testes_http(pasta, falhas):
    original = os.urandom(TAMANHO)

    destino = pasta / "enviado.bin"
    status, corpo = subir(destino, original)
    if status != 200:
        falhas.append(f"upload devolveu {status}")
    if not destino.is_file() or destino.read_bytes() != original:
        falhas.append("o arquivo gravado no disco não bate com o enviado")
    if corpo.strip() != str(TAMANHO):
        falhas.append(f"o servidor reportou {corpo!r} bytes, esperado {TAMANHO}")

    _, disposicao, dados = baixar(destino)
    if dados != original:
        falhas.append("o download não bate byte a byte com o original")
    if "attachment" not in (disposicao or ""):
        falhas.append(f"Content-Disposition sem attachment: {disposicao!r}")

    # Acento em nome de arquivo é o caso comum aqui, e cabeçalho HTTP não
    # aceita byte cru: o navegador precisa do filename* para salvar certo.
    com_acento = pasta / "relatório final.bin"
    subir(com_acento, b"conteudo")
    _, disposicao, _ = baixar(com_acento)
    if "filename*=UTF-8''relat%C3%B3rio%20final.bin" not in (disposicao or ""):
        falhas.append(f"nome com acento não sobreviveu ao cabeçalho: {disposicao!r}")

    if codigo_do_erro("download", pasta) != 400:
        falhas.append("baixar uma pasta devia dar 400")
    if codigo_do_erro("download", pasta / "nao-existe") != 404:
        falhas.append("baixar arquivo inexistente devia dar 404")
    if codigo_do_erro("upload", pasta, b"x") != 400:
        falhas.append("gravar por cima de uma pasta devia dar 400")

    print("OK: upload e download preservam o arquivo byte a byte")


def testes_navegador(pw, pasta, falhas):
    navegador = abrir_navegador(pw)
    page = navegador.new_page(accept_downloads=True)
    erros = []
    page.on("pageerror", lambda e: erros.append(str(e)))
    externas = []
    exigir_offline(page, externas)

    page.goto(URL)
    page.wait_for_selector("#file-list .file-item", timeout=20000)
    page.fill("#root-path-input", str(pasta))
    page.press("#root-path-input", "Enter")
    page.wait_for_selector("#file-list >> text=enviado.bin", timeout=15000)

    # Upload pela interface: o mesmo caminho que o botão 📤 dispara.
    origem = pasta / "da-maquina.txt"
    origem.write_text("veio do navegador")
    page.set_input_files("#input-arquivos", str(origem))
    try:
        page.wait_for_selector("#file-list >> text=da-maquina.txt", timeout=15000)
    except Exception:
        falhas.append("o arquivo enviado pela interface não apareceu na árvore")

    # Download pelo ⬇ da linha do arquivo.
    linha = page.locator(".linha-arquivo", has_text="enviado.bin").first
    try:
        with page.expect_download(timeout=20000) as info:
            linha.locator(".btn-baixar").click()
        baixado = pathlib.Path(info.value.path())
        if baixado.read_bytes() != (pasta / "enviado.bin").read_bytes():
            falhas.append("o download pela interface veio diferente do arquivo")
    except Exception as e:
        falhas.append(f"o botão de baixar não disparou download: {e}")

    if erros:
        falhas.append(f"erros de JS na página: {erros}")
    if externas:
        falhas.append(f"a página buscou recurso fora do servidor: {externas}")

    navegador.close()
    print("OK: a interface envia pelo seletor e baixa pelo botão da linha")


if __name__ == "__main__":
    falhas = []
    with tempfile.TemporaryDirectory() as tmp:
        pasta = pathlib.Path(tmp)
        with servidor():
            testes_http(pasta, falhas)
            with sync_playwright() as pw:
                testes_navegador(pw, pasta, falhas)
    relatar(falhas, "subir e baixar arquivos")
