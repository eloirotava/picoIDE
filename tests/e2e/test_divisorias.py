"""Divisórias arrastáveis: largura da árvore e altura do terminal.

O que dificilmente se vê no olho: o xterm não se reajusta sozinho. Depois de
mudar a altura, o shell precisa saber as novas dimensões — senão continua
quebrando linha pela geometria antiga, e o texto some pela direita. Por isso o
teste não se contenta em medir a caixa: pergunta ao próprio shell, com
`stty size`, quantas linhas e colunas ele acha que tem.
"""

import pathlib
import tempfile

from playwright.sync_api import sync_playwright

from helpers import URL, abrir_navegador, exigir_offline, ler_terminal, relatar, servidor


def caixa(page, seletor, dimensao):
    return page.evaluate(
        f"() => document.querySelector('{seletor}').getBoundingClientRect().{dimensao}")


def arrastar(page, seletor, dx, dy):
    caixa_div = page.locator(seletor).bounding_box()
    x = caixa_div["x"] + caixa_div["width"] / 2
    y = caixa_div["y"] + caixa_div["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    # Em dois passos: um arrasto de um pulo só não dispara os mousemove
    # intermediários, e é neles que o redimensionamento acontece.
    page.mouse.move(x + dx / 2, y + dy / 2)
    page.mouse.move(x + dx, y + dy)
    page.mouse.up()
    page.wait_for_timeout(800)


def run(pw, falhas):
    antes = len(falhas)
    navegador = abrir_navegador(pw)
    page = navegador.new_page(viewport={"width": 1280, "height": 800})
    erros = []
    page.on("pageerror", lambda e: erros.append(str(e)))
    exigir_offline(page, [])

    page.goto(URL)
    page.wait_for_selector("#file-list .file-item", timeout=20000)
    page.wait_for_timeout(3500)

    # --- largura da árvore ---
    largura_antes = caixa(page, "#sidebar", "width")
    arrastar(page, "#divisoria-lateral", 120, 0)
    largura_depois = caixa(page, "#sidebar", "width")
    if largura_depois < largura_antes + 80:
        falhas.append(
            f"arrastar não alargou a árvore: {largura_antes} -> {largura_depois}")

    # --- altura do terminal ---
    altura_antes = caixa(page, "#terminal-container", "height")
    linhas_antes = page.evaluate("() => window.term.rows")
    arrastar(page, "#divisoria-terminal", 0, -150)
    altura_depois = caixa(page, "#terminal-container", "height")
    if altura_depois < altura_antes + 100:
        falhas.append(
            f"arrastar não aumentou o terminal: {altura_antes} -> {altura_depois}")

    linhas_depois = page.evaluate("() => window.term.rows")
    if linhas_depois <= linhas_antes:
        falhas.append(
            f"o terminal não ganhou linhas: {linhas_antes} -> {linhas_depois}")

    # O ponto do teste: o shell tem de concordar com a tela. Se o resize não
    # tivesse sido enviado ao PTY, o stty responderia a geometria antiga.
    page.evaluate("() => document.querySelector("
                  "'.terminal-tela.ativa .xterm-helper-textarea').focus()")
    page.keyboard.type("stty size\n")
    page.wait_for_timeout(2500)
    tela = ler_terminal(page)
    colunas = page.evaluate("() => window.term.cols")
    esperado = f"{linhas_depois} {colunas}"
    if esperado not in tela:
        falhas.append(
            f"o shell não soube do novo tamanho: esperava {esperado!r} "
            f"no stty size\n{tela[-300:]}")

    # --- os tamanhos sobrevivem ao reload ---
    page.reload()
    page.wait_for_selector("#file-list .file-item", timeout=20000)
    page.wait_for_timeout(3000)
    if abs(caixa(page, "#sidebar", "width") - largura_depois) > 2:
        falhas.append("a largura da árvore não voltou depois do reload")
    if abs(caixa(page, "#terminal-container", "height") - altura_depois) > 2:
        falhas.append("a altura do terminal não voltou depois do reload")

    # --- os limites impedem sumir com um painel ---
    arrastar(page, "#divisoria-lateral", -900, 0)
    if caixa(page, "#sidebar", "width") < 100:
        falhas.append("deu para encolher a árvore além do limite")

    if erros:
        falhas.append(f"erros de JS na página: {erros}")

    navegador.close()
    if len(falhas) == antes:
        print("OK: arrastar redimensiona, o shell aprende o tamanho e o ajuste persiste")


if __name__ == "__main__":
    falhas = []
    with tempfile.TemporaryDirectory():
        with servidor():
            with sync_playwright() as pw:
                run(pw, falhas)
    relatar(falhas, "divisórias arrastáveis")
