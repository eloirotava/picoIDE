"""Múltiplos arquivos e múltiplos terminais.

O que dificilmente se pega "no olho": cada aba precisa ser mesmo independente.
Dois arquivos abertos não podem compartilhar o texto, o autosave não pode
gravar no arquivo errado depois de trocar de aba, e dois terminais precisam ser
dois shells de verdade — não a mesma sessão pintada duas vezes.
"""

import pathlib
import tempfile

from playwright.sync_api import sync_playwright

from helpers import (URL, abrir_navegador, exigir_offline, ler_terminal,
                     relatar, servidor)


def texto_do_editor(page):
    return page.evaluate("() => document.querySelector('.CodeMirror').CodeMirror.getValue()")


def clicar_aba(page, barra, nome):
    page.locator(f"{barra} .aba", has_text=nome).first.click()


def testar_arquivos(page, pasta, falhas):
    (pasta / "alfa.txt").write_text("conteudo do alfa")
    (pasta / "beta.txt").write_text("conteudo do beta")

    page.fill("#root-path-input", str(pasta))
    page.press("#root-path-input", "Enter")
    page.wait_for_selector("#file-list >> text=alfa.txt", timeout=15000)

    page.click("#file-list >> text=alfa.txt")
    page.wait_for_function(
        "() => document.getElementById('current-file').textContent === 'alfa.txt'",
        timeout=15000)
    page.click("#file-list >> text=beta.txt")
    page.wait_for_function(
        "() => document.getElementById('current-file').textContent === 'beta.txt'",
        timeout=15000)

    if page.locator("#abas-arquivos .aba").count() != 2:
        falhas.append("abrir dois arquivos não deu duas abas")
    if texto_do_editor(page) != "conteudo do beta":
        falhas.append("a aba ativa não mostra o conteúdo do arquivo dela")

    # Voltar para a primeira aba tem de trazer o texto dela de volta.
    clicar_aba(page, "#abas-arquivos", "alfa.txt")
    page.wait_for_timeout(500)
    if texto_do_editor(page) != "conteudo do alfa":
        falhas.append("trocar de aba não trouxe o conteúdo do outro arquivo")

    # Editar aqui e trocar de aba: o autosave tem de gravar em alfa.txt, e não
    # no arquivo que passou a estar na frente.
    page.evaluate("""() => {
        const cm = document.querySelector('.CodeMirror').CodeMirror;
        cm.setValue('alfa editado');
    }""")
    page.wait_for_timeout(300)
    clicar_aba(page, "#abas-arquivos", "beta.txt")
    page.wait_for_timeout(7000)   # o autosave dispara 5s depois da edição

    if (pasta / "alfa.txt").read_text() != "alfa editado":
        falhas.append("o autosave não gravou o arquivo que foi editado")
    if (pasta / "beta.txt").read_text() != "conteudo do beta":
        falhas.append("o autosave gravou no arquivo errado depois da troca de aba")

    # Fechar uma aba deixa a outra viva.
    page.locator("#abas-arquivos .aba", has_text="beta.txt").first \
        .locator(".fechar").click()
    page.wait_for_timeout(500)
    if page.locator("#abas-arquivos .aba").count() != 1:
        falhas.append("fechar uma aba não deixou exatamente uma")
    if texto_do_editor(page) != "alfa editado":
        falhas.append("depois de fechar a aba, a restante não ficou ativa")

    print("OK: abas de arquivo são independentes e o autosave acerta o alvo")


def testar_terminais(page, falhas):
    if page.locator(".abas-terminais .aba").count() != 1:
        falhas.append("não começou com exatamente um terminal")

    page.click(".abas-terminais .nova-aba")
    page.wait_for_timeout(3000)
    if page.locator(".abas-terminais .aba").count() != 2:
        falhas.append("o + não abriu um segundo terminal")

    # Só uma tela visível por vez, senão os dois terminais brigariam pela área.
    if page.locator(".terminal-tela.ativa").count() != 1:
        falhas.append("mais de uma tela de terminal visível ao mesmo tempo")

    # Marca o terminal 2 e confere que o 1 não viu nada: prova que são shells
    # distintos, e não a mesma sessão desenhada duas vezes.
    page.keyboard.type("echo MARCA_DO_SEGUNDO\n")
    page.wait_for_timeout(2500)
    if "MARCA_DO_SEGUNDO" not in ler_terminal(page):
        falhas.append("o segundo terminal não respondeu ao que foi digitado")

    clicar_aba(page, ".abas-terminais", "Terminal 1")
    page.wait_for_timeout(1500)
    if "MARCA_DO_SEGUNDO" in ler_terminal(page):
        falhas.append("os dois terminais são a mesma sessão")

    # Fechar o segundo deixa o primeiro em pé.
    page.locator(".abas-terminais .aba", has_text="Terminal 2").first \
        .locator(".fechar").click()
    page.wait_for_timeout(2000)
    if page.locator(".abas-terminais .aba").count() != 1:
        falhas.append("fechar um terminal não deixou exatamente um")

    page.keyboard.type("echo AINDA_VIVO\n")
    page.wait_for_timeout(2500)
    if "AINDA_VIVO" not in ler_terminal(page):
        falhas.append("o terminal restante parou de funcionar")

    # O FitAddon calcula as linhas a partir da altura do pai menos o padding do
    # próprio .xterm. Com o padding no lugar errado ele conta uma linha a mais
    # do que cabe, e a última fica cortada para fora da página.
    vazamento = page.evaluate("""() => {
        const tela = document.querySelector('.terminal-tela.ativa');
        const screen = tela.querySelector('.xterm-screen');
        return screen.getBoundingClientRect().bottom
             - tela.getBoundingClientRect().bottom;
    }""")
    if vazamento > 0:
        falhas.append(f"o terminal passa {vazamento:.1f}px do fim da área visível")

    print("OK: terminais são sessões distintas e fechar um não afeta o outro")
    print("OK: o conteúdo do terminal cabe na área sem cortar linha")


def testar_copiar_colar(page, falhas):
    """Copiar é ao selecionar; o Ctrl+C fica sendo só o SIGINT."""
    focar = ("() => document.querySelector("
             "'.terminal-tela.ativa .xterm-helper-textarea').focus()")

    # Ctrl+C não pode ter virado copiar: no terminal ele interrompe, e é para
    # continuar assim mesmo COM texto selecionado na tela.
    page.evaluate(focar)
    page.keyboard.type("sleep 90\n")
    page.wait_for_timeout(1500)
    page.evaluate("() => window.term.selectAll()")
    page.wait_for_timeout(600)
    page.evaluate(focar)
    page.keyboard.press("Control+c")
    page.wait_for_timeout(1500)
    page.evaluate(focar)
    page.keyboard.type("echo INTERROMPEU\n")
    page.wait_for_timeout(2500)
    if "INTERROMPEU" not in ler_terminal(page):
        falhas.append("Ctrl+C deixou de interromper o processo")

    # Selecionar já copia. Forçamos o caminho sem Clipboard API, que é o que
    # roda de verdade: acessar o servidor por http://IP não é contexto seguro.
    page.evaluate("""() => Object.defineProperty(window, 'isSecureContext',
                        { value: false, configurable: true })""")
    page.evaluate("() => window.term.clearSelection()")
    page.wait_for_timeout(300)
    page.evaluate("() => window.term.selectAll()")
    page.wait_for_timeout(1200)   # a cópia espera a seleção assentar
    page.evaluate("() => window.term.clearSelection()")

    # Confere colando num textarea comum, com Ctrl+V nativo: não usa a API.
    page.evaluate("""() => {
        const a = document.createElement('textarea');
        a.id = 'prova-clipboard';
        a.style.cssText = 'position:fixed;top:0;left:0;z-index:9999';
        document.body.appendChild(a);
        a.focus();
    }""")
    page.keyboard.press("Control+v")
    page.wait_for_timeout(800)
    prova = page.evaluate("() => document.getElementById('prova-clipboard').value")
    if "INTERROMPEU" not in (prova or ""):
        falhas.append(f"selecionar não copiou: {str(prova)[:80]!r}")
    page.evaluate("() => document.getElementById('prova-clipboard').remove()")

    print("OK: selecionar já copia, e o Ctrl+C segue interrompendo")


def testar_restauracao(pw, pasta, falhas):
    """As duas listas de abas precisam voltar depois do F5."""
    navegador = abrir_navegador(pw)
    page = navegador.new_page()
    exigir_offline(page, [])
    page.goto(URL)
    page.wait_for_selector("#file-list .file-item", timeout=20000)

    page.fill("#root-path-input", str(pasta))
    page.press("#root-path-input", "Enter")
    page.wait_for_selector("#file-list >> text=alfa.txt", timeout=15000)
    page.click("#file-list >> text=alfa.txt")
    page.wait_for_timeout(500)
    page.click("#file-list >> text=beta.txt")
    page.wait_for_timeout(500)
    page.click(".abas-terminais .nova-aba")
    page.wait_for_timeout(2500)

    page.reload()
    page.wait_for_selector("#file-list .file-item", timeout=20000)
    page.wait_for_timeout(4000)

    if page.locator("#abas-arquivos .aba").count() != 2:
        falhas.append("as abas de arquivo não voltaram depois do reload")
    if page.locator(".abas-terminais .aba").count() != 2:
        falhas.append("as abas de terminal não voltaram depois do reload")

    navegador.close()
    print("OK: as duas listas de abas voltam depois do reload")


if __name__ == "__main__":
    falhas = []
    with tempfile.TemporaryDirectory() as tmp:
        pasta = pathlib.Path(tmp)
        with servidor():
            with sync_playwright() as pw:
                navegador = abrir_navegador(pw)
                page = navegador.new_page()
                erros = []
                page.on("pageerror", lambda e: erros.append(str(e)))
                exigir_offline(page, [])
                page.goto(URL)
                page.wait_for_selector("#file-list .file-item", timeout=20000)
                page.wait_for_timeout(2000)

                testar_arquivos(page, pasta, falhas)
                testar_terminais(page, falhas)
                testar_copiar_colar(page, falhas)
                if erros:
                    falhas.append(f"erros de JS na página: {erros}")
                navegador.close()

                testar_restauracao(pw, pasta, falhas)
    relatar(falhas, "múltiplos arquivos e múltiplos terminais")
