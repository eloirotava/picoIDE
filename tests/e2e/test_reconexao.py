"""O terminal precisa voltar sozinho quando a conexão cai de verdade.

Derruba o servidor com o navegador aberto, sobe de novo e confere que o
terminal reconectou sem intervenção. Depois confere que um `exit` (fechamento
limpo) NÃO vira um laço de reconexão.
"""

import time

from playwright.sync_api import sync_playwright

from helpers import (URL, abrir_navegador, derrubar_servidor, digitar,
                     exigir_offline, ler_terminal, relatar, subir_servidor)


def esperar_no_terminal(page, texto, tentativas=20, intervalo=1500):
    for _ in range(tentativas):
        if texto in ler_terminal(page):
            return True
        page.wait_for_timeout(intervalo)
    return False


def run(pw):
    falhas = []
    servidor = subir_servidor()
    navegador = abrir_navegador(pw)
    page = navegador.new_page()
    externas = []
    exigir_offline(page, externas)
    page.goto(URL)
    page.wait_for_selector("#file-list .file-item", timeout=20000)
    page.wait_for_timeout(1500)

    # --- queda de rede ---
    print("derrubando o servidor...")
    derrubar_servidor(servidor)
    page.wait_for_timeout(2500)
    if "perdida" not in ler_terminal(page):
        falhas.append(f"não avisou da queda:\n{ler_terminal(page)[:300]}")

    print("subindo o servidor de novo...")
    servidor = subir_servidor()
    time.sleep(2)

    if not esperar_no_terminal(page, "Reconectado"):
        falhas.append(f"não reconectou sozinho:\n{ler_terminal(page)[:600]}")

    digitar(page, "echo VIVO_DEPOIS_DA_RECONEXAO\r")
    page.wait_for_timeout(3000)
    if "VIVO_DEPOIS_DA_RECONEXAO" not in ler_terminal(page):
        falhas.append(f"o shell não responde depois da reconexão:\n{ler_terminal(page)[-500:]}")

    # --- exit: fechamento limpo, não deve reconectar em laço ---
    print("testando exit...")
    digitar(page, "exit\r")
    page.wait_for_timeout(4000)
    tela = ler_terminal(page)
    if "encerrada" not in tela:
        falhas.append(f"não avisou que a sessão encerrou:\n{tela[-500:]}")
    elif "Reconectando" in tela.split("encerrada")[-1]:
        falhas.append("reconectou em laço depois de um exit limpo")

    # uma tecla reabre a sessão sob demanda
    digitar(page, "\r")
    page.wait_for_timeout(3000)
    digitar(page, "echo SESSAO_NOVA\r")
    page.wait_for_timeout(3000)
    if "SESSAO_NOVA" not in ler_terminal(page):
        falhas.append(f"não reabriu a sessão sob demanda:\n{ler_terminal(page)[-500:]}")

    if externas:
        falhas.append(f"a página buscou recurso fora do servidor: {externas}")

    navegador.close()
    derrubar_servidor(servidor)
    relatar(falhas, "o terminal reconecta sozinho e trata o exit corretamente")


if __name__ == "__main__":
    with sync_playwright() as pw:
        run(pw)
