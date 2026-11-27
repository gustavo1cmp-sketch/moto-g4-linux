"""Bichinho do PC: mascote em pixel art que reage ao PC (página do painel no celular).

humor() é puro (testado no PC); desenhar() usa Pillow e roda no celular.
"""
import math

L, A = 160, 90  # tela em "pixels grandes"; cada um vira 12x12 na tela real
ESCALA = 12
CARINHO_DURA = 5  # segundos
QUENTE, ESFORCO_CPU, ESFORCO_GPU, PARADO = 80, 70, 80, 15
PARADO_POR = 120  # envios (~2 min) com CPU e GPU baixas para dormir

CEU_DIA, CEU_NOITE, CHAO, CHAO_PONTO = "#16202c", "#0b0f19", "#1f2a37", "#2c3a4b"
CORPO, CORPO_SOMBRA, CORPO_QUENTE, CORPO_QUENTE_SOMBRA = "#6fdc8c", "#4fb86c", "#ff8a65", "#e0663f"
OLHO, BRILHO, BOCHECHA, ANTENA, ANTENA_QUENTE = "#0d1117", "#ffffff", "#ff9eb5", "#3987e5", "#ff5252"
SUOR, NOTA, CORACAO, ZZZ, SOL, LUA, ESTRELA = "#7fc8ff", "#f0b429", "#ff5c8a", "#9da7b3", "#ffd166", "#e6edf3", "#59616b"

CORACAO_PX = (".XX.XX.", "XXXXXXX", "XXXXXXX", ".XXXXX.", "..XXX..", "...X...")
NOTA_PX = ("..XXX", "..X.X", "..X..", "XXX..", "XXX..")
Z_PX = ("XXXX", "..X.", ".X..", "XXXX")


def num(v):
    return "—" if v is None else f"{v:.0f}"


def humor(dados, hist, carinho_em, agora, hora):
    """(estado, frase) do bichinho. hist = {"cpu": [...], "gpu": [...]} (um valor por envio)."""
    cpu, gpu = dados.get("cpu"), dados.get("gpu")
    temps = [t for t in (dados.get("cpu_temp"), dados.get("gpu_temp")) if t is not None]
    midia = dados.get("midia") if isinstance(dados.get("midia"), dict) else None
    baixos = lambda serie: len(serie) >= PARADO_POR and all(v is not None and v < PARADO for v in serie[-PARADO_POR:])
    parado = baixos(hist.get("cpu", [])) and baixos(hist.get("gpu", []))

    if agora - carinho_em < CARINHO_DURA:
        return "carinho", "Hehe! Mais carinho!"
    if temps and max(temps) >= QUENTE:
        qual = "GPU" if dados.get("gpu_temp") == max(temps) else "CPU"
        return "quente", f"Tá quente aqui! {qual} a {max(temps):.0f} °C"
    if hora < 5 and not parado:
        return "tarde", "Já é madrugada... bora dormir?"
    if (cpu or 0) > ESFORCO_CPU or (gpu or 0) > ESFORCO_GPU:
        return "correndo", f"Correndo! CPU {num(cpu)}% · GPU {num(gpu)}%"
    if midia and midia.get("tocando"):
        return "dancando", "♪ " + (midia.get("titulo") or "Que som!")
    if parado:
        return "dormindo", "Zzz... o PC tá descansando."
    return "normal", "Tudo tranquilo por aqui."


def padrao(d, linhas, x, y, cor):
    for j, linha in enumerate(linhas):
        for i, c in enumerate(linha):
            if c == "X":
                d.point((x + i, y + j), fill=cor)


def cenario(d, hora, quadro):
    noite = hora >= 18 or hora < 6
    d.rectangle((0, 0, L, A), fill=CEU_NOITE if noite else CEU_DIA)
    if noite:
        for i, (x, y) in enumerate(((20, 18), (45, 9), (70, 24), (110, 12), (128, 30), (150, 20))):
            if (quadro // 3 + i) % 5:  # estrelas piscando
                d.point((x, y), fill=ESTRELA)
        d.ellipse((134, 6, 146, 18), fill=LUA)
        d.ellipse((138, 4, 150, 16), fill=CEU_NOITE)  # lua minguante
    else:
        d.ellipse((134, 6, 148, 20), fill=SOL)
    d.rectangle((0, 74, L, A), fill=CHAO)
    for x in range(4, L, 11):
        d.point((x, 78 + (x // 11) % 3 * 3), fill=CHAO_PONTO)


def desenhar(Image, ImageDraw, estado, quadro, hora):
    """Imagem 160x90 do bichinho no estado dado; quadro = contador da animação (~4 por segundo)."""
    img = Image.new("RGB", (L, A))
    d = ImageDraw.Draw(img)
    cenario(d, hora, quadro)
    quente = estado == "quente"
    corpo, sombra = (CORPO_QUENTE, CORPO_QUENTE_SOMBRA) if quente else (CORPO, CORPO_SOMBRA)
    passo = quadro % 2
    pulo = {"dancando": [0, -3, 0, -2][quadro % 4], "correndo": -passo, "carinho": -(quadro % 2) * 2}.get(estado, 0)
    if estado == "normal":
        pulo = -1 if quadro % 8 < 4 else 0  # respirando
    x0 = 63 + {"correndo": 4, "dancando": [0, 1, 0, -1][quadro % 4]}.get(estado, 0)
    y0 = 46 + pulo
    if estado == "dormindo":
        y0 += 3  # deitadinho

    # sombra no chão
    d.ellipse((x0 + 4, 73, x0 + 30, 77), fill=CHAO_PONTO)
    # pés
    if estado == "correndo":
        d.rectangle((x0 + 7, 71 + passo, x0 + 11, 73), fill=sombra)
        d.rectangle((x0 + 23, 71 + 1 - passo, x0 + 27, 73), fill=sombra)
        for i, y in enumerate((52, 58, 64)):  # linhas de velocidade
            d.line((x0 - 14 + (quadro + i) % 3 * 2, y, x0 - 6, y), fill=ZZZ)
    elif estado != "dormindo":
        d.rectangle((x0 + 7, 71, x0 + 11, 73), fill=sombra)
        d.rectangle((x0 + 23, 71, x0 + 27, 73), fill=sombra)
    # corpo
    altura = 22 if estado == "dormindo" else 25
    d.ellipse((x0, y0, x0 + 34, y0 + altura), fill=corpo)
    d.ellipse((x0 + 4, y0 + altura - 7, x0 + 30, y0 + altura), fill=sombra)
    d.ellipse((x0 + 6, y0 + 3, x0 + 12, y0 + 7), fill=BRILHO if not quente else "#ffc2ad")
    # antena com luz
    if estado != "dormindo":
        d.line((x0 + 17, y0, x0 + 17, y0 - 6), fill=sombra)
        luz = ANTENA_QUENTE if quente else ANTENA
        if quadro % 4 < 3 or estado in ("quente", "correndo"):
            d.rectangle((x0 + 16, y0 - 8, x0 + 18, y0 - 6), fill=luz)
    # olhos
    ex1, ex2, ey = x0 + 11, x0 + 22, y0 + 9
    if estado in ("dormindo",):
        for ex in (ex1, ex2):
            d.line((ex - 1, ey + 2, ex + 2, ey + 2), fill=OLHO)
    elif estado in ("carinho", "dancando"):
        for ex in (ex1, ex2):  # olhinhos felizes ^ ^
            d.point((ex - 1, ey + 2), fill=OLHO); d.point((ex, ey + 1), fill=OLHO)
            d.point((ex + 1, ey + 1), fill=OLHO); d.point((ex + 2, ey + 2), fill=OLHO)
    elif estado == "tarde":
        for ex in (ex1, ex2):  # sonolento
            d.rectangle((ex, ey + 1, ex + 1, ey + 2), fill=OLHO)
            d.line((ex - 1, ey, ex + 2, ey), fill=sombra)
    elif quadro % 13 == 0:  # piscada
        for ex in (ex1, ex2):
            d.line((ex - 1, ey + 2, ex + 2, ey + 2), fill=OLHO)
    else:
        for ex in (ex1, ex2):
            d.rectangle((ex, ey, ex + 1, ey + 3), fill=OLHO)
            d.point((ex + 1, ey), fill=BRILHO)
    # boca
    bx, by = x0 + 17, y0 + 15
    if estado == "quente" or estado == "correndo":
        d.rectangle((bx - 1, by, bx + 1, by + 2), fill=OLHO)  # ofegante
    elif estado == "tarde":
        abre = quadro % 8 < 3
        d.ellipse((bx - 2, by - 1, bx + 2, by + (3 if abre else 1)), fill=OLHO)  # bocejo
    elif estado != "dormindo":
        d.line((bx - 2, by, bx - 1, by + 1), fill=OLHO); d.line((bx - 1, by + 1, bx + 1, by + 1), fill=OLHO)
        d.line((bx + 1, by + 1, bx + 2, by), fill=OLHO)
    # bochechas
    if estado in ("carinho", "dancando", "quente"):
        d.rectangle((x0 + 6, y0 + 13, x0 + 8, y0 + 14), fill=BOCHECHA)
        d.rectangle((x0 + 26, y0 + 13, x0 + 28, y0 + 14), fill=BOCHECHA)

    # efeitos
    if estado == "carinho":
        for i, (hx, base) in enumerate(((x0 - 6, 40), (x0 + 33, 34), (x0 + 14, 30))):
            padrao(d, CORACAO_PX, hx, base - (quadro + i * 3) % 10, CORACAO)
    elif estado == "dancando":
        for i, (nx, base) in enumerate(((x0 - 10, 44), (x0 + 38, 40))):
            padrao(d, NOTA_PX, nx + (quadro + i) % 2, base - (quadro * 2 + i * 5) % 14, NOTA)
    elif estado == "dormindo":
        for i in range(3):
            fase = (quadro + i * 4) % 12
            padrao(d, Z_PX, x0 + 30 + fase, y0 - 2 - fase * 2, ZZZ)
    elif estado == "quente":
        for i, sx in enumerate((x0 + 2, x0 + 31)):
            gy = y0 + 4 + (quadro * 2 + i * 3) % 12
            d.rectangle((sx, gy, sx + 1, gy + 2), fill=SUOR)
        for i in range(3):  # calor subindo
            hx = x0 + 6 + i * 11
            ondula = (quadro + i) % 2
            d.line((hx + ondula, y0 - 14, hx + 1 - ondula, y0 - 10), fill=ANTENA_QUENTE)
    elif estado == "tarde" and quadro % 8 < 3:
        padrao(d, Z_PX, x0 + 34, y0 - 4, ZZZ)
    return img


if __name__ == "__main__":  # prévia de todos os estados: python3 bichinho.py
    from PIL import Image, ImageDraw
    estados = ("normal", "carinho", "quente", "tarde", "correndo", "dancando", "dormindo")
    folha = Image.new("RGB", (L * 4, A * 2))
    for i, e in enumerate(estados):
        folha.paste(desenhar(Image, ImageDraw, e, 1, 22 if i % 2 else 14), ((i % 4) * L, (i // 4) * A))
    folha.resize((L * 4 * 4, A * 2 * 4), Image.NEAREST).save("/tmp/bichinho-estados.png")
    print("ok", math.pi > 3)
