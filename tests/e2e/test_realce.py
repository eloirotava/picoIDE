"""Realce de sintaxe por tipo de arquivo.

Não basta o modo estar embutido: ele só vale se o CodeMirror realmente o
aplicar ao abrir o arquivo. Por isso o teste pergunta ao editor qual modo ficou
ativo, e confere que o texto saiu de fato colorido — um modo que não carrega
deixa a tela sem nenhum token, sem erro nenhum aparecer.
"""

import pathlib
import tempfile

from playwright.sync_api import sync_playwright

from helpers import URL, abrir_navegador, exigir_offline, relatar, servidor

# nome do arquivo -> pedaço esperado do modo que o CodeMirror deve ativar
CASOS = {
    "main.c": ("clike", "int main(void) { return 0; }"),
    "app.cpp": ("clike", "#include <vector>\nint main() {}"),
    "lib.h": ("clike", "#define X 1"),
    "script.py": ("python", "def f(x):\n    return x"),
    "lib.rs": ("rust", "fn main() { let x = 1; }"),
    "run.sh": ("shell", "echo ola"),
    "config.yaml": ("yaml", "chave: valor"),
    "LEIAME.md": ("markdown", "# titulo"),
    "Dockerfile": ("dockerfile", "FROM alpine"),
    "srv.go": ("go", "package main"),
    "a.lua": ("lua", "local x = 1"),
    "b.rb": ("ruby", "puts 1"),
    "c.sql": ("sql", "SELECT 1;"),
    "CMakeLists.txt": ("cmake", "project(x)"),
    "d.json": ("javascript", '{"a": 1}'),
    "e.toml": ("toml", "[x]\ny = 1"),
    "f.css": ("css", "a { color: red; }"),
    "g.html": ("htmlmixed", "<p>oi</p>"),
    "h.diff": ("diff", "--- a\n+++ b"),
    "i.ini": ("properties", "chave=valor"),
}


def run(pw, pasta, falhas):
    for nome, (_, conteudo) in CASOS.items():
        (pasta / nome).write_text(conteudo)
    (pasta / "notas.log").write_text("apenas texto solto")

    navegador = abrir_navegador(pw)
    page = navegador.new_page()
    erros = []
    page.on("pageerror", lambda e: erros.append(str(e)))
    exigir_offline(page, [])

    page.goto(URL)
    page.wait_for_selector("#file-list .file-item", timeout=20000)
    page.fill("#root-path-input", str(pasta))
    page.press("#root-path-input", "Enter")
    page.wait_for_selector("#file-list >> text=main.c", timeout=15000)

    for nome, (modo_esperado, _) in CASOS.items():
        page.click(f"#file-list >> text={nome}")
        try:
            page.wait_for_function(
                "n => document.getElementById('current-file').textContent === n",
                arg=nome, timeout=10000)
        except Exception:
            falhas.append(f"{nome} não abriu")
            continue

        aplicado = page.evaluate("""() => {
            const cm = document.querySelector('.CodeMirror').CodeMirror;
            const m = cm.getMode();
            return { nome: m.name || '', modo: cm.getOption('mode'),
                     // Qualquer span de token serve: listar classes à mão
                     // deixava de fora .cm-meta (o #define do C) e
                     // .cm-positive (as linhas do diff).
                     tokens: cm.getWrapperElement()
                               .querySelectorAll('[class*="cm-"]').length };
        }""")

        if modo_esperado not in str(aplicado["nome"]) and \
                modo_esperado not in str(aplicado["modo"]):
            falhas.append(
                f"{nome}: esperava modo {modo_esperado}, veio "
                f"{aplicado['nome']!r} / {aplicado['modo']!r}")
        elif aplicado["tokens"] == 0:
            # O modo certo sem nenhum token quer dizer que o arquivo do modo
            # não carregou: o CodeMirror aceita o nome e não colore nada.
            falhas.append(f"{nome}: modo {modo_esperado} não coloriu nada")

    # Extensão desconhecida vira texto puro. O padrão antigo era JavaScript, o
    # que pintava um .log de cores erradas — pior do que sem realce.
    page.click("#file-list >> text=notas.log")
    page.wait_for_timeout(1000)
    modo_log = page.evaluate(
        "() => document.querySelector('.CodeMirror').CodeMirror.getOption('mode')")
    if "javascript" in str(modo_log):
        falhas.append(f"arquivo desconhecido caiu em javascript: {modo_log!r}")

    if erros:
        falhas.append(f"erros de JS na página: {erros}")

    navegador.close()
    if not falhas:
        print(f"OK: {len(CASOS)} tipos de arquivo abrem com o realce certo")


if __name__ == "__main__":
    falhas = []
    with tempfile.TemporaryDirectory() as tmp:
        with servidor():
            with sync_playwright() as pw:
                run(pw, pathlib.Path(tmp), falhas)
    relatar(falhas, "realce de sintaxe por tipo de arquivo")
