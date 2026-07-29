"""Recarregar a página não pode jogar o usuário de volta na raiz.

Abre uma pasta, expande a árvore, abre um arquivo, dá F5 e confere que tudo
voltou: pasta, árvore, arquivo, conteúdo no editor e a pasta do terminal.
"""

from playwright.sync_api import sync_playwright

from helpers import (RAIZ, URL, abrir_navegador, digitar, instalar_rotas,
                     ler_terminal, relatar, servidor)

PASTA = str(RAIZ)


def run(pw):
    navegador = abrir_navegador(pw)
    page = navegador.new_page()
    erros = []
    page.on("pageerror", lambda e: erros.append(str(e)))
    instalar_rotas(page)

    page.goto(URL)
    page.wait_for_selector("#file-list .file-item", timeout=20000)

    # Navega para a pasta do projeto
    page.fill("#root-path-input", PASTA)
    page.press("#root-path-input", "Enter")
    page.wait_for_selector("#file-list >> text=Cargo.toml", timeout=15000)

    # Expande src/ para testar a memória da árvore
    page.click("#file-list >> text=📁 src")
    page.wait_for_selector("#file-list >> text=main.rs", timeout=15000)

    # Abre um arquivo
    page.click("#file-list >> text=📄 README.md")
    page.wait_for_function(
        "() => document.getElementById('current-file').textContent === 'README.md'",
        timeout=15000)

    print("antes do reload -> pasta:", page.input_value("#root-path-input"),
          "| arquivo:", page.text_content("#current-file"))

    page.reload()
    page.wait_for_selector("#file-list .file-item", timeout=20000)
    page.wait_for_timeout(2500)

    terminal = ler_terminal(page)
    if PASTA not in terminal:
        # o prompt pode estar abreviado; conferimos com um pwd explícito
        digitar(page, "pwd\r")
        page.wait_for_timeout(2500)
        terminal = ler_terminal(page)

    pasta = page.input_value("#root-path-input")
    arquivo = page.text_content("#current-file")
    lista = page.text_content("#file-list")
    editor = page.evaluate(
        "() => document.querySelector('.CodeMirror').CodeMirror.getValue()")

    print("depois do reload -> pasta:", pasta, "| arquivo:", arquivo,
          "| src expandida:", "📂" in lista)

    falhas = []
    if pasta != PASTA:
        falhas.append(f"a pasta voltou para {pasta!r} em vez de {PASTA!r}")
    if "Cargo.toml" not in lista:
        falhas.append("a árvore não recarregou na pasta salva")
    if "main.rs" not in lista:
        falhas.append("a pasta src não continuou expandida")
    if arquivo != "README.md":
        falhas.append(f"o arquivo aberto não foi restaurado: {arquivo!r}")
    if "picoIDE" not in editor:
        falhas.append(f"o editor ficou sem o conteúdo do arquivo: {editor[:80]!r}")
    if PASTA not in terminal:
        falhas.append(f"o terminal não abriu na pasta salva:\n{terminal[-400:]}")
    if erros:
        falhas.append(f"erros de JS na página: {erros}")

    navegador.close()
    relatar(falhas, "a sessão sobrevive ao reload")


if __name__ == "__main__":
    with servidor():
        with sync_playwright() as pw:
            run(pw)
