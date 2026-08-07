"""Terminais lado a lado: arrastar uma aba divide a área em painéis.

O que dificilmente se vê "no olho": ao rearranjar os painéis as telas do xterm
são MOVIDAS de lugar, nunca recriadas. Se alguma fosse recriada, o terminal
perderia o que estava escrito e a conexão junto — e a tela continuaria parecendo
certa, só que vazia. Por isso o teste escreve uma marca em cada painel e cobra
que ela sobreviva a cada divisão, a cada arrasto de divisória e ao reload.

Também prova o que só se percebe compilando: cada painel avisa o SEU shell do
tamanho que coube a ele. Dois `stty size` com respostas diferentes na mesma tela
é o que separa "dois terminais" de "dois desenhos do mesmo terminal".
"""

import tempfile

from playwright.sync_api import sync_playwright

from helpers import URL, abrir_navegador, exigir_offline, relatar, servidor


def paineis(page):
    """Texto visível de cada painel, na ordem em que estão na tela."""
    return page.evaluate("""() => Array.from(
        document.querySelectorAll('.grupo-terminal')).map(g => {
            const linhas = g.querySelector('.terminal-tela.ativa .xterm-rows');
            if (!linhas) return '';
            return Array.from(linhas.children)
                        .map(l => l.textContent).join('\\n');
        })""")


def caixa_do_painel(page, i):
    return page.evaluate(
        f"() => document.querySelectorAll('.grupo-terminal')[{i}]"
        ".getBoundingClientRect().toJSON()")


def digitar_em(page, i, texto):
    """Escreve no painel i, clicando nele antes para lhe dar o teclado."""
    caixa = caixa_do_painel(page, i)
    page.mouse.click(caixa["x"] + caixa["width"] / 2,
                     caixa["y"] + caixa["height"] / 2)
    page.wait_for_timeout(300)
    page.keyboard.type(texto)
    page.wait_for_timeout(2000)


def arrastar_aba(page, nome, destino, fracao_x, fracao_y):
    """Arrasta a aba `nome` para um ponto relativo do painel `destino`."""
    aba = page.locator(".abas-terminais .aba", has_text=nome).first.bounding_box()
    alvo = page.evaluate(
        f"() => document.querySelectorAll('.grupo-terminal')[{destino}]"
        ".querySelector('.telas-terminais').getBoundingClientRect().toJSON()")
    x = alvo["x"] + alvo["width"] * fracao_x
    y = alvo["y"] + alvo["height"] * fracao_y

    page.mouse.move(aba["x"] + aba["width"] / 2, aba["y"] + aba["height"] / 2)
    page.mouse.down()
    # Em passos: um pulo só não dispara os mousemove intermediários, e é neles
    # que o arrasto começa e o alvo da solta é calculado.
    page.mouse.move(x, y, steps=8)
    page.mouse.move(x, y)
    page.mouse.up()
    page.wait_for_timeout(1500)


def linhas_do_stty(texto):
    """Devolve o '<linhas> <colunas>' que o shell respondeu, se já respondeu."""
    for linha in reversed(texto.splitlines()):
        partes = linha.split()
        if len(partes) == 2 and all(p.isdigit() for p in partes):
            return linha.strip()
    return None


def testar_dividir(page, falhas):
    page.click(".abas-terminais .nova-aba")
    page.wait_for_timeout(3000)
    if page.locator(".abas-terminais .aba").count() != 2:
        falhas.append("o + não abriu um segundo terminal")

    digitar_em(page, 0, "echo MARCA_DOIS\n")

    # O gesto do recurso: pegar a aba e soltá-la na borda direita da área.
    arrastar_aba(page, "Terminal 2", 0, 0.9, 0.5)

    if page.locator(".grupo-terminal").count() != 2:
        falhas.append("arrastar a aba para a borda não criou um segundo painel")
        return False
    if page.locator(".terminal-tela.ativa").count() != 2:
        falhas.append("os dois painéis não estão visíveis ao mesmo tempo")

    esquerdo, direito = caixa_do_painel(page, 0), caixa_do_painel(page, 1)
    if direito["x"] <= esquerdo["x"]:
        falhas.append("soltar na borda direita não pôs o painel à direita")

    # A tela do terminal 2 foi movida para o painel novo, não recriada: o que
    # ele já tinha escrito continua lá.
    texto = paineis(page)
    if not any("MARCA_DOIS" in t for t in texto):
        falhas.append("o terminal perdeu a tela ao mudar de painel")
    print("OK: arrastar a aba para a borda abre um painel ao lado, com a tela intacta")
    return True


def testar_independencia(page, falhas):
    """Cada painel é um shell, e cada um sabe do tamanho que coube a ele."""
    digitar_em(page, 0, "echo SO_NO_ESQUERDO\n")
    digitar_em(page, 1, "echo SO_NO_DIREITO\n")
    esquerdo, direito = paineis(page)[:2]
    if "SO_NO_ESQUERDO" not in esquerdo or "SO_NO_DIREITO" not in direito:
        falhas.append("o que foi digitado não saiu no painel em que se clicou")
    if "SO_NO_DIREITO" in esquerdo or "SO_NO_ESQUERDO" in direito:
        falhas.append("os dois painéis estão mostrando o mesmo shell")

    digitar_em(page, 0, "stty size\n")
    digitar_em(page, 1, "stty size\n")
    medidas = [linhas_do_stty(t) for t in paineis(page)[:2]]
    if not all(medidas):
        falhas.append(f"algum shell não respondeu ao stty size: {medidas}")
    print("OK: cada painel é um shell independente")
    return medidas


def testar_divisoria(page, falhas, medidas_antes):
    largura_antes = caixa_do_painel(page, 0)["width"]
    divisoria = page.locator(".divisao > .divisoria").first.bounding_box()
    x = divisoria["x"] + divisoria["width"] / 2
    y = divisoria["y"] + divisoria["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x - 150, y, steps=6)
    page.mouse.move(x - 150, y)
    page.mouse.up()
    page.wait_for_timeout(1200)

    largura_depois = caixa_do_painel(page, 0)["width"]
    if largura_depois > largura_antes - 100:
        falhas.append(
            f"a divisória entre painéis não moveu: {largura_antes} -> {largura_depois}")

    # O ponto: o shell do painel encolhido tem de aprender a largura nova,
    # senão continua quebrando linha pela geometria antiga.
    digitar_em(page, 0, "stty size\n")
    if linhas_do_stty(paineis(page)[0]) == medidas_antes[0]:
        falhas.append("o shell do painel não soube do novo tamanho")
    print("OK: a divisória entre painéis move, e o shell aprende o tamanho")


def testar_2x2(page, falhas):
    """Dois painéis viram quatro: um novo terminal embaixo de cada um."""
    for painel in (0, 1):
        page.locator(".grupo-terminal").nth(painel).locator(".dividir-aba").click()
        page.wait_for_timeout(2500)
        # O ⊞ divide ao lado; arrastar a aba nova para baixo faz o 2x2.
        nome = f"Terminal {3 + painel}"
        alvo = page.locator(".grupo-terminal").count() - 1
        arrastar_aba(page, nome, alvo, 0.5, 0.9)

    if page.locator(".grupo-terminal").count() != 4:
        falhas.append(
            f"não deu para chegar a quatro painéis: "
            f"{page.locator('.grupo-terminal').count()}")
        return
    if page.locator(".terminal-tela.ativa").count() != 4:
        falhas.append("os quatro painéis não estão todos visíveis")

    # Em 2x2 há uma divisória vertical entre as colunas e uma horizontal dentro
    # de cada coluna: três ao todo, todas arrastáveis.
    if page.locator(".divisao > .divisoria").count() != 3:
        falhas.append("faltou divisória entre algum par de painéis")
    print("OK: dá para chegar a quatro terminais à vista, 2x2")


def testar_reload(page, falhas):
    antes = [c["width"] for c in
             (caixa_do_painel(page, i) for i in range(4))]
    page.reload()
    page.wait_for_selector(".grupo-terminal", timeout=20000)
    page.wait_for_timeout(5000)

    if page.locator(".grupo-terminal").count() != 4:
        falhas.append("a divisão em painéis não voltou depois do reload")
        return
    depois = [caixa_do_painel(page, i)["width"] for i in range(4)]
    if any(abs(a - b) > 4 for a, b in zip(antes, depois)):
        falhas.append(f"os painéis voltaram com outro tamanho: {antes} -> {depois}")

    # Cada painel reatou a SUA sessão, e não uma qualquer.
    texto = paineis(page)
    if sum("SO_NO_ESQUERDO" in t for t in texto) != 1:
        falhas.append("as sessões não voltaram cada uma no seu painel")
    print("OK: os painéis, os tamanhos e as sessões voltam depois do reload")


def testar_juntar(page, falhas):
    """Soltar no meio de outro painel devolve a aba para lá."""
    antes = page.locator(".grupo-terminal").count()
    arrastar_aba(page, "Terminal 1", 3, 0.5, 0.5)
    if page.locator(".grupo-terminal").count() != antes - 1:
        falhas.append("soltar no meio de outro painel não juntou os dois")
    if page.locator(".grupo-terminal").nth(2).locator(".aba").count() != 2:
        falhas.append("a aba não foi parar no painel em que foi solta")
    print("OK: soltar no meio junta os terminais num painel só")


def testar_fechar(page, falhas):
    antes = page.locator(".grupo-terminal").count()
    page.locator(".abas-terminais .aba", has_text="Terminal 2").first \
        .locator(".fechar").click()
    page.wait_for_timeout(2500)
    if page.locator(".grupo-terminal").count() != antes - 1:
        falhas.append("fechar o único terminal de um painel não fechou o painel")

    # O que sobrou tem de continuar funcionando, e ocupando o espaço vago.
    digitar_em(page, 0, "echo SOBREVIVI\n")
    if not any("SOBREVIVI" in t for t in paineis(page)):
        falhas.append("os painéis restantes pararam de funcionar")
    print("OK: fechar o último terminal de um painel fecha o painel")


def run(pw, falhas):
    navegador = abrir_navegador(pw)
    page = navegador.new_page(viewport={"width": 1280, "height": 900})
    erros = []
    page.on("pageerror", lambda e: erros.append(str(e)))
    exigir_offline(page, [])

    page.goto(URL)
    page.wait_for_selector("#file-list .file-item", timeout=20000)
    page.wait_for_timeout(3500)

    # O terminal precisa de espaço para os painéis não baterem no piso de 60px.
    page.evaluate("() => ajustarMedida('--alt-terminal', 520)")
    page.wait_for_timeout(500)

    if testar_dividir(page, falhas):
        medidas = testar_independencia(page, falhas)
        testar_divisoria(page, falhas, medidas)
        testar_2x2(page, falhas)
        testar_reload(page, falhas)
        testar_juntar(page, falhas)
        testar_fechar(page, falhas)

    if erros:
        falhas.append(f"erros de JS na página: {erros}")
    navegador.close()


if __name__ == "__main__":
    falhas = []
    with tempfile.TemporaryDirectory():
        with servidor():
            with sync_playwright() as pw:
                run(pw, falhas)
    relatar(falhas, "terminais lado a lado")
