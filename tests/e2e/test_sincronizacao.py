"""Sincroniza abas abertas sem perder uma edição local concorrente."""

import pathlib
import tempfile

from playwright.sync_api import sync_playwright

from helpers import URL, abrir_navegador, exigir_offline, relatar, servidor


def editor(page):
    return page.evaluate(
        "() => document.querySelector('.CodeMirror').CodeMirror.getValue()")


def trocar_texto(page, texto):
    page.evaluate(
        "texto => document.querySelector('.CodeMirror').CodeMirror.setValue(texto)",
        texto)


def run(page, pasta, falhas):
    arquivo = pasta / "observado.txt"
    arquivo.write_text("original")

    page.fill("#root-path-input", str(pasta))
    page.press("#root-path-input", "Enter")
    page.wait_for_selector("#file-list >> text=observado.txt", timeout=15000)
    page.click("#file-list >> text=observado.txt")
    page.wait_for_function(
        "() => document.getElementById('current-file').textContent === 'observado.txt'",
        timeout=15000)

    # Aba limpa: a versão externa entra automaticamente no editor.
    arquivo.write_text("mudança externa")
    page.evaluate("() => atualizarArquivosAbertos()")
    if editor(page) != "mudança externa":
        falhas.append("uma aba limpa não acompanhou a mudança externa")
    # ativarAba ignora eventos programáticos nos primeiros 100 ms; deixa esse
    # guarda terminar antes de simular a digitação real do usuário.
    page.wait_for_timeout(300)

    # Aba suja: o autosave condicional deve receber 409, preservar os dois
    # lados e pedir uma decisão em vez de sobrescrever silenciosamente.
    trocar_texto(page, "edição local")
    arquivo.write_text("edição concorrente no disco")
    page.wait_for_timeout(6000)
    if arquivo.read_text() != "edição concorrente no disco":
        falhas.append("o autosave sobrescreveu uma alteração externa")
    if editor(page) != "edição local":
        falhas.append("o conflito descartou a edição local")
    if "conflito externo" not in page.text_content("#current-file"):
        falhas.append("o conflito não ficou visível na interface")

    # Salvar manualmente é a resolução explícita: com confirmação, a
    # versão local vence e passa a ser a nova revisão conhecida.
    page.click("#btn-salvar")
    page.wait_for_timeout(500)
    if arquivo.read_text() != "edição local":
        falhas.append("confirmar o conflito não salvou a versão local")

    # Remoção externa também bloqueia o autosave; recriar exige confirmação.
    arquivo.unlink()
    page.evaluate("() => atualizarArquivosAbertos()")
    if "removido no disco" not in page.text_content("#current-file"):
        falhas.append("a remoção externa não foi mostrada na aba")
    trocar_texto(page, "conteúdo recriado")
    page.wait_for_timeout(6000)
    if arquivo.exists():
        falhas.append("o autosave recriou sozinho um arquivo removido")

    page.click("#btn-salvar")
    page.wait_for_timeout(500)
    if not arquivo.exists() or arquivo.read_text() != "conteúdo recriado":
        falhas.append("a confirmação não recriou o arquivo removido")


if __name__ == "__main__":
    falhas = []
    with tempfile.TemporaryDirectory() as tmp:
        with servidor():
            with sync_playwright() as pw:
                navegador = abrir_navegador(pw)
                page = navegador.new_page()
                erros = []
                externas = []
                page.on("pageerror", lambda e: erros.append(str(e)))
                page.on("dialog", lambda dialog: dialog.accept())
                exigir_offline(page, externas)
                page.goto(URL)
                page.wait_for_selector("#file-list .file-item", timeout=20000)
                run(page, pathlib.Path(tmp), falhas)
                navegador.close()
                if erros:
                    falhas.append(f"erros de JS na página: {erros}")
                if externas:
                    falhas.append(f"a página buscou recurso externo: {externas}")
    relatar(falhas, "sincronização segura de arquivos abertos")
