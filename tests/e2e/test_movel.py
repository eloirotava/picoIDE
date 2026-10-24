"""A interface estreita é um terminal: teclas de CLI, caixa de texto e histórico."""

import re
import tempfile
import time

from playwright.sync_api import sync_playwright

from helpers import URL, abrir_navegador, exigir_offline, relatar, servidor


def texto_terminal(page):
    return page.evaluate("""() => {
        const b = window.term.buffer.active, linhas = [];
        for (let i = 0; i < b.length; i++) linhas.push(b.getLine(i).translateToString(true));
        return linhas.join('\\n');
    }""")


def esperar_no_terminal(page, padrao, falhas, msg, timeout=10):
    fim = time.time() + timeout
    while time.time() < fim:
        if re.search(padrao, texto_terminal(page)):
            return True
        time.sleep(0.2)
    falhas.append(msg)
    return False


def topo_visivel(page):
    return page.evaluate("window.term.buffer.active.viewportY")


def arrastar(page, x, y0, y1):
    """Arrasto de um dedo só, via eventos de toque reais do CDP."""
    cdp = page.context.new_cdp_session(page)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y0}]})
    passos = 12
    for i in range(1, passos + 1):
        y = y0 + (y1 - y0) * i / passos
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y}]})
        time.sleep(0.03)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    time.sleep(1.2)  # deixa a inércia assentar


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
    page.wait_for_function("window.term && window.term.rows > 5", timeout=20000)

    viewport = page.locator('meta[name="viewport"]').get_attribute("content") or ""
    if "width=device-width" not in viewport:
        falhas.append("a página móvel não declarou a viewport do telefone")

    for tecla in ("Esc", "^C", "Ctrl", "Tab", "⇧Tab", "↑", "↓", "←", "→", "⏎",
                  "Rol↑", "Rol↓", "⤓", "Pg↑", "Pg↓", "Texto", "📁", "📝"):
        if not page.locator(f'#mobile-keybar [data-tecla="{tecla}"]').count():
            falhas.append(f"faltou a tecla móvel {tecla!r}")
    if page.locator("#mobile-pager").count():
        falhas.append("a pílula flutuante de telas voltou a cobrir o terminal")

    # O terminal não pode passar por baixo da faixa de teclas.
    sobra = page.evaluate("""() => document.getElementById('mobile-keybar').getBoundingClientRect().top
        - document.getElementById('terminal-container').getBoundingClientRect().bottom""")
    if sobra < -1:
        falhas.append(f"o terminal fica {-sobra:.0f}px atrás da faixa de teclas")

    # Arquivos e editor abrem por cima, sem slide, e o mesmo botão volta.
    page.locator('#mobile-keybar [data-tela="files"]').click()
    page.wait_for_selector("body.mobile-files")
    if not page.locator("#sidebar").is_visible():
        falhas.append("o botão de arquivos não mostrou a árvore")
    transicao = page.evaluate("getComputedStyle(document.getElementById('sidebar')).transitionDuration")
    if transicao not in ("0s", ""):
        falhas.append(f"a troca de tela ainda anima ({transicao})")
    page.locator('#mobile-keybar [data-tela="editor"]').click()
    page.wait_for_selector("body.mobile-editor")
    page.locator('#mobile-keybar [data-tela="editor"]').click()
    page.wait_for_selector("body.mobile-terminal")

    # Caixa de composição: texto de várias linhas chega como uma colagem só
    # (bracketed paste), e o Enter final é que executa.
    page.locator('#mobile-keybar [data-tecla="Texto"]').click()
    page.wait_for_selector("#texto-compor", state="visible")
    sobra = page.evaluate("""() => document.getElementById('mobile-compor').getBoundingClientRect().top
        - document.getElementById('terminal-container').getBoundingClientRect().bottom""")
    if sobra < -1:
        falhas.append("a caixa de texto cobre o fim do terminal")
    page.fill("#texto-compor", "echo composto-$((6*7))")
    page.click("#btn-enviar-compor")
    esperar_no_terminal(page, r"composto-42", falhas, "o texto da caixa não foi executado no shell")
    if page.input_value("#texto-compor"):
        falhas.append("a caixa de texto não foi limpa depois de enviar")

    page.fill("#texto-compor", "")
    page.locator('#mobile-keybar [data-tecla="Texto"]').click()
    page.wait_for_selector("#texto-compor", state="hidden")

    # Histórico: gera saída longa, arrasta para baixo e o topo sobe.
    page.evaluate("""() => window.term.focus()""")
    page.keyboard.type("seq 1 400\n")
    esperar_no_terminal(page, r"(?m)^400$", falhas, "o seq não terminou")
    time.sleep(0.5)
    base = topo_visivel(page)
    if base < 100:
        falhas.append(f"o scrollback não guardou a saída (viewportY={base})")
    caixa = page.locator("#terminal-container").bounding_box()
    x = caixa["x"] + caixa["width"] / 2
    arrastar(page, x, caixa["y"] + 120, caixa["y"] + 520)
    depois = topo_visivel(page)
    if depois >= base - 10:
        falhas.append(f"arrastar o dedo não rolou o histórico ({base} -> {depois})")
    if page.locator("#sidebar").is_visible():
        falhas.append("arrastar no terminal trocou de tela")

    page.locator('#mobile-keybar [data-tecla="⤓"]').click()
    if topo_visivel(page) != base:
        falhas.append("o botão ⤓ não voltou ao fim do histórico")
    page.locator('#mobile-keybar [data-tecla="Rol↑"]').click()
    if topo_visivel(page) >= base:
        falhas.append("o botão Rol↑ não subiu o histórico")

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
