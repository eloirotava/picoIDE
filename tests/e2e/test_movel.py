"""A interface estreita prioriza o terminal e conserva atalhos de CLI."""

import tempfile

from playwright.sync_api import sync_playwright

from helpers import URL, abrir_navegador, exigir_offline, relatar, servidor


def run(pw, falhas):
    navegador = abrir_navegador(pw)
    # is_mobile faz o Chromium usar a viewport real de telefone; sem a meta
    # viewport uma página desktop pareceria estreita aqui por engano.
    page = navegador.new_page(
        viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    erros = []
    page.on("pageerror", lambda e: erros.append(str(e)))
    exigir_offline(page, [])
    page.goto(URL)
    page.wait_for_selector("body.mobile-terminal", timeout=20000)

    viewport = page.locator('meta[name="viewport"]').get_attribute("content") or ""
    if "width=device-width" not in viewport:
        falhas.append("a página móvel não declarou a viewport do telefone")

    for tecla in ("Esc", "Ctrl", "Tab", "↑", "↓", "←", "→", "Pg↑", "Pg↓"):
        if not page.locator(f'#mobile-keybar [data-tecla="{tecla}"]').count():
            falhas.append(f"faltou a tecla móvel {tecla!r}")

    # Os seletores não dependem de haver um arquivo específico na máquina: a
    # troca de tela é útil mesmo antes de entrar em qualquer projeto.
    page.locator('#mobile-pager [data-tela="files"]').click()
    page.wait_for_selector("body.mobile-files")
    page.locator('#mobile-pager [data-tela="editor"]').click()
    page.wait_for_selector("body.mobile-editor")
    page.locator('#mobile-pager [data-tela="terminal"]').click()
    page.wait_for_selector("body.mobile-terminal")

    if erros:
        falhas.append(f"erros de JS na tela móvel: {erros}")
    navegador.close()


if __name__ == "__main__":
    falhas = []
    with tempfile.TemporaryDirectory():
        with servidor():
            with sync_playwright() as pw:
                run(pw, falhas)
    relatar(falhas, "interface móvel")
