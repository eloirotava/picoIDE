"""Recarregar a página não pode jogar o usuário de volta na raiz.

Abre uma pasta, expande a árvore, abre um arquivo, dá F5 e confere que tudo
voltou: pasta, árvore, arquivo e conteúdo no editor.

O terminal tem exigência mais forte que "abriu na pasta certa": ele precisa ser
o MESMO shell de antes do reload, com o estado intacto e o histórico de volta na
tela. É o que garante que uma compilação não morre quando a aba recarrega.
"""

from playwright.sync_api import sync_playwright

from helpers import (RAIZ, URL, abrir_navegador, digitar, exigir_offline,
                     ler_terminal, relatar, servidor)

PASTA = str(RAIZ)


def run(pw):
    navegador = abrir_navegador(pw)
    page = navegador.new_page()
    erros = []
    page.on("pageerror", lambda e: erros.append(str(e)))
    externas = []
    exigir_offline(page, externas)

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

    # Marca o shell: uma variável (só existe neste processo) e uma linha na
    # tela (só existe neste histórico). Um shell novo não teria nem uma nem outra.
    digitar(page, "MARCA_SESSAO=sobreviveu\r")
    page.wait_for_timeout(800)
    digitar(page, "echo LINHA_ANTES_DO_RELOAD\r")
    page.wait_for_timeout(1500)

    print("antes do reload -> pasta:", page.input_value("#root-path-input"),
          "| arquivo:", page.text_content("#current-file"))

    page.reload()
    page.wait_for_selector("#file-list .file-item", timeout=20000)
    page.wait_for_timeout(2500)

    # A variável só responde se for o mesmo processo do shell.
    historico = ler_terminal(page)
    digitar(page, "echo VALOR=$MARCA_SESSAO\r")
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
    if "VALOR=sobreviveu" not in terminal:
        falhas.append(
            "o terminal virou um shell novo no reload (a variável se perdeu):\n"
            f"{terminal[-400:]}")
    if "LINHA_ANTES_DO_RELOAD" not in historico:
        falhas.append(
            "o histórico da sessão não voltou na tela depois do reload:\n"
            f"{historico[-400:]}")
    if erros:
        falhas.append(f"erros de JS na página: {erros}")
    if externas:
        falhas.append(f"a página buscou recurso fora do servidor: {externas}")

    navegador.close()
    relatar(falhas, "a sessão sobrevive ao reload")


if __name__ == "__main__":
    with servidor():
        with sync_playwright() as pw:
            run(pw)
