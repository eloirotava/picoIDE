"""A árvore só repinta quando tem coisa nova.

A barra lateral se atualiza sozinha a cada 10s. Repintar o DOM mesmo sem
mudança fazia a barra piscar, e ainda derrubava a seleção de texto e a posição
da rolagem. Estes testes prendem as duas pontas: não mexer quando nada mudou, e
continuar mostrando quando mudou de verdade — inclusive dentro de subpasta
aberta, que é o caso que um "só olha a raiz" deixaria passar.
"""

import pathlib
import tempfile

from playwright.sync_api import sync_playwright

from helpers import URL, abrir_navegador, exigir_offline, relatar, servidor

# O auto-refresh da interface roda a cada 10s; esperamos com folga.
ESPERA_REFRESH = 14000


def marcar(page):
    """Carimba os nós atuais para saber depois se sobreviveram ao refresh."""
    page.evaluate("""() => {
        document.querySelectorAll('#file-list .file-item')
            .forEach(n => n.dataset.carimbo = 'original');
    }""")


def sobreviveram(page):
    return page.evaluate("""() => {
        const nos = Array.from(document.querySelectorAll('#file-list .file-item'));
        return nos.length > 0 && nos.every(n => n.dataset.carimbo === 'original');
    }""")


def run(pw, pasta, falhas):
    (pasta / "um.txt").write_text("a")
    (pasta / "dois.txt").write_text("b")
    sub = pasta / "subpasta"
    sub.mkdir()
    (sub / "dentro.txt").write_text("c")

    navegador = abrir_navegador(pw)
    page = navegador.new_page()
    erros = []
    page.on("pageerror", lambda e: erros.append(str(e)))
    externas = []
    exigir_offline(page, externas)

    page.goto(URL)
    page.wait_for_selector("#file-list .file-item", timeout=20000)
    page.fill("#root-path-input", str(pasta))
    page.press("#root-path-input", "Enter")
    page.wait_for_selector("#file-list >> text=um.txt", timeout=15000)

    # Abre a subpasta: ela precisa continuar sendo vigiada mesmo quando a raiz
    # não muda.
    page.click("#file-list >> text=📁 subpasta")
    page.wait_for_selector("#file-list >> text=dentro.txt", timeout=15000)
    page.wait_for_timeout(1000)

    # 1) Sem novidade: os nós têm de ser os mesmos objetos depois do refresh.
    marcar(page)
    page.wait_for_timeout(ESPERA_REFRESH)
    if not sobreviveram(page):
        falhas.append("a árvore foi repintada mesmo sem nada ter mudado (pisca)")
    else:
        print("OK: sem novidade, a árvore não é repintada")

    # 2) Arquivo novo na raiz aparece sozinho.
    (pasta / "tres.txt").write_text("d")
    try:
        page.wait_for_selector("#file-list >> text=tres.txt", timeout=ESPERA_REFRESH)
        print("OK: arquivo novo na raiz aparece sozinho")
    except Exception:
        falhas.append("arquivo novo na raiz não apareceu no refresh automático")

    # 3) Arquivo novo dentro da subpasta aberta também aparece: é o caso que se
    #    perde ao pular o repinte olhando só a raiz.
    marcar(page)
    (sub / "novo-dentro.txt").write_text("e")
    try:
        page.wait_for_selector("#file-list >> text=novo-dentro.txt",
                               timeout=ESPERA_REFRESH)
        print("OK: arquivo novo dentro de subpasta aberta aparece sozinho")
    except Exception:
        falhas.append("arquivo novo dentro da subpasta aberta não apareceu")

    if erros:
        falhas.append(f"erros de JS na página: {erros}")
    if externas:
        falhas.append(f"a página buscou recurso fora do servidor: {externas}")

    navegador.close()


if __name__ == "__main__":
    falhas = []
    with tempfile.TemporaryDirectory() as tmp:
        with servidor():
            with sync_playwright() as pw:
                run(pw, pathlib.Path(tmp), falhas)
    relatar(falhas, "a árvore só repinta quando muda")
