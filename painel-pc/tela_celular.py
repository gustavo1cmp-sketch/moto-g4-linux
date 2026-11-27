"""Painel do PC desenhado direto na tela do Moto G4 (postmarketOS, /dev/fb0).

O PC envia os dados por POST /dados (rede USB) e recebe na resposta os botões tocados.
Roda no celular como serviço: /usr/local/bin/tela_celular.py
"""
import base64
import fcntl
import io
import json
import os
import struct
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ENDERECO = ("172.16.42.1", 8766)  # só a rede USB; o Wi-Fi não alcança
PC = "172.16.42.2"
LARGURA, ALTURA = 1920, 1080  # desenho na horizontal; a tela física é 1080x1920
STRIDE_PX = 1088  # linha do framebuffer tem 4352 bytes (1088 px), não 1080
GIRAR_ANTI_HORARIO = True  # False vira o painel de cabeça para baixo
DESCANSO_APOS = 30  # segundos sem dados do PC
PONTOS = 300  # 5 min com um envio por segundo
BRILHO, BRILHO_DESCANSO = 255, 12
LUZ = "/sys/class/leds/lcd-backlight/brightness"
TOQUE = "/dev/input/event2"  # synaptics_dsx_i2c
GB = 1024 ** 3

ACOES = ("anterior", "tocar", "proxima", "volume-menos", "mudo", "volume-mais")
LADO_BOTAO, VAO_BOTAO, MARGEM = 130, 12, 20
LADO_CAPA = LADO_BOTAO
LADO_CAPA_GRANDE = 680
PAGINAS = ("painel", "tocando")  # arrastar para o lado troca a página; nova função = nova página aqui
ARRASTE_MIN = 220  # px de arraste na horizontal para virar a página
SERIES = ("cpu", "cpu_temp", "gpu", "gpu_temp")
PERFIS = (("silencioso", "Silencioso"), ("normal", "Normal"), ("jogo", "Jogo"))  # mesmos nomes do painel.py

FUNDO, CARTAO, BOTAO, BOTAO_ATIVO = "#0d1117", "#161b22", "#21262d", "#3d444d"
TEXTO, SECUNDARIO, LINHA = "#e6edf3", "#9da7b3", "#30363d"
AZUL, LARANJA, QUENTE, AVISO, DESCANSO_COR = "#3987e5", "#d95926", "#ff7b72", "#f0b429", "#59616b"


def retangulo_botao(i):
    """Caixa (x0, y0, x1, y1) do botão i, alinhados à direita no topo."""
    total = len(ACOES) * LADO_BOTAO + (len(ACOES) - 1) * VAO_BOTAO
    x0 = LARGURA - MARGEM - total + i * (LADO_BOTAO + VAO_BOTAO)
    return x0, MARGEM, x0 + LADO_BOTAO, MARGEM + LADO_BOTAO


def cartoes():
    """Caixas dos quatro cartões: CPU e GPU em cima, RAM e perfil embaixo."""
    topo, vao = MARGEM * 2 + LADO_BOTAO + 10, 20
    meio = (LARGURA - 2 * MARGEM - vao) // 2
    alto_proc = (ALTURA - topo - MARGEM - vao) * 3 // 5
    col = lambda c: (MARGEM + c * (meio + vao), MARGEM + c * (meio + vao) + meio)
    (e0, e1), (d0, d1) = col(0), col(1)
    baixo = topo + alto_proc + vao
    return {"cpu": (e0, topo, e1, topo + alto_proc), "gpu": (d0, topo, d1, topo + alto_proc),
            "ram": (e0, baixo, e1, ALTURA - MARGEM), "perfil": (d0, baixo, d1, ALTURA - MARGEM)}


def retangulo_perfil(i):
    x0, y0, x1, y1 = cartoes()["perfil"]
    largura = (x1 - x0 - 64 - 2 * VAO_BOTAO) // len(PERFIS)
    bx = x0 + 32 + i * (largura + VAO_BOTAO)
    return bx, y0 + 100, bx + largura, y1 - 32


def botoes_tocando():
    """(ação, caixa) dos botões grandes da página Tocando agora."""
    lado, vao, x0 = 190, 28, 800
    linhas = ((("anterior", "tocar", "proxima"), 520, 190), (("volume-menos", "mudo", "volume-mais"), 750, 150))
    return [(acao, (x0 + i * (lado + vao), y, x0 + i * (lado + vao) + lado, y + alto))
            for acoes, y, alto in linhas for i, acao in enumerate(acoes)]


def gesto(inicio, fim):
    """("virar", +1/-1) para arraste na horizontal; ("tocar", ponto) para toque. Pontos no desenho."""
    dx, dy = fim[0] - inicio[0], fim[1] - inicio[1]
    if abs(dx) >= ARRASTE_MIN and abs(dx) > 2 * abs(dy):
        return "virar", 1 if dx < 0 else -1  # arrastar para a esquerda mostra a próxima página
    return "tocar", inicio


def botao_em(x, y, pagina=0):
    """Ação do botão sob o ponto (coordenadas do desenho), ou None. Inclui o vão: alvo maior que o ícone."""
    if PAGINAS[pagina] == "tocando":
        for acao, (x0, y0, x1, y1) in botoes_tocando():
            if x0 - 14 <= x < x1 + 14 and y0 - 14 <= y < y1 + 14:
                return acao
        return None
    for i, acao in enumerate(ACOES):
        x0, y0, x1, y1 = retangulo_botao(i)
        if x0 - VAO_BOTAO // 2 <= x < x1 + VAO_BOTAO // 2 and y0 - MARGEM <= y < y1 + VAO_BOTAO:
            return acao
    for i, (nome, _) in enumerate(PERFIS):
        x0, y0, x1, y1 = retangulo_perfil(i)
        if x0 - VAO_BOTAO // 2 <= x < x1 + VAO_BOTAO // 2 and y0 - VAO_BOTAO <= y < y1 + VAO_BOTAO:
            return "perfil-" + nome
    return None


def toque_para_desenho(px, py, anti_horario=GIRAR_ANTI_HORARIO):
    """Converte o toque (tela em pé, 1080x1920) para as coordenadas do desenho deitado."""
    if anti_horario:
        return LARGURA - 1 - py, px
    return py, ALTURA - 1 - px


def num(v, casas=0):
    if v is None:
        return "—"
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(parte, total):
    return None if parte is None or not total else 100 * parte / total


class Estado:
    def __init__(self):
        self.trava = threading.Lock()
        self.dados = None
        self.recebido = 0.0
        self.historico = {s: deque(maxlen=PONTOS) for s in SERIES}
        self.acoes = []
        self.apertado = {}  # acao -> instante do toque (realce rápido)
        self.mudou = threading.Event()
        self.capa, self.capa_grande, self.capa_id = None, None, None
        self.pagina = 0

    def virar(self, passo):
        with self.trava:
            self.pagina = min(max(self.pagina + passo, 0), len(PAGINAS) - 1)
        self.mudou.set()

    def receber(self, dados):
        with self.trava:
            if time.monotonic() - self.recebido > DESCANSO_APOS:
                for h in self.historico.values():  # voltando do descanso, a série não é contínua
                    h.clear()
            self.dados, self.recebido = dados, time.monotonic()
            for s in SERIES:
                self.historico[s].append(dados.get(s))
            acoes, self.acoes = self.acoes, []
        capa = dados.pop("capa", None)
        midia = dados.get("midia")
        if capa and isinstance(midia, dict):
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(base64.b64decode(capa))).convert("RGB")
                caber = lambda lado: img.resize((max(1, round(img.width * lado / max(img.size))),
                                                 max(1, round(img.height * lado / max(img.size)))), Image.LANCZOS)
                with self.trava:  # ampliada se preciso: a capa do Spotify chega com uns 300 px
                    self.capa, self.capa_grande, self.capa_id = caber(LADO_CAPA), caber(LADO_CAPA_GRANDE), midia.get("id")
            except Exception:  # capa ilegível: segue sem ela
                pass
        return acoes, self.capa_id

    def tocar(self, acao):
        with self.trava:
            if len(self.acoes) < 10:
                self.acoes.append(acao)
            self.apertado[acao] = time.monotonic()
        self.mudou.set()


def servidor(estado):
    class Pedido(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.client_address[0] != PC or self.path != "/dados":
                return self.send_error(403)
            try:
                tamanho = int(self.headers.get("Content-Length", 0))
                dados = json.loads(self.rfile.read(min(tamanho, 2 << 20)))  # cabe a capa do álbum
                if not isinstance(dados, dict):
                    raise ValueError
            except ValueError:
                return self.send_error(400)
            acoes, capa_id = estado.receber(dados)
            corpo = json.dumps({"acoes": acoes, "capa_id": capa_id}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            estado.mudou.set()

        def log_message(self, *args):
            pass

    while True:  # o IP da rndis0 pode demorar a aparecer no boot
        try:
            ThreadingHTTPServer(ENDERECO, Pedido).serve_forever()
        except OSError:
            time.sleep(3)


def ler_toques(estado):
    abs_info = lambda fd, codigo: struct.unpack("6i", fcntl.ioctl(fd, 0x80184540 + codigo, b"\0" * 24))
    while True:
        try:
            fd = os.open(TOQUE, os.O_RDONLY)
            _, max_x = abs_info(fd, 0x35)[1:3]
            _, max_y = abs_info(fd, 0x36)[1:3]
            x = y = inicio = None
            while True:
                _, _, tipo, codigo, valor = struct.unpack("llHHi", os.read(fd, 24))
                if tipo == 3 and codigo == 0x35:
                    x = valor * 1079 // max(max_x, 1)
                elif tipo == 3 and codigo == 0x36:
                    y = valor * 1919 // max(max_y, 1)
                elif tipo == 1 and codigo == 0x14A and valor == 0 and x is not None and y is not None:  # dedo levantado
                    tipo_gesto, valor_gesto = gesto(inicio or toque_para_desenho(x, y), toque_para_desenho(x, y))
                    if tipo_gesto == "virar":
                        estado.virar(valor_gesto)
                    else:
                        acao = botao_em(*valor_gesto, pagina=estado.pagina)
                        if acao:
                            estado.tocar(acao)
                    x = y = inicio = None
                    continue
                if inicio is None and x is not None and y is not None:  # primeiro ponto do dedo
                    inicio = toque_para_desenho(x, y)
        except OSError:
            time.sleep(5)


def luz(valor):
    try:
        with open(LUZ, "w") as f:
            f.write(str(valor))
    except OSError:
        pass


class Tela:
    def __init__(self):
        from PIL import Image, ImageDraw, ImageFont
        self.Image, self.ImageDraw = Image, ImageDraw
        fonte = lambda tamanho, negrito=False: ImageFont.truetype(
            "/usr/share/fonts/dejavu/DejaVuSans%s.ttf" % ("-Bold" if negrito else ""), tamanho)
        self.f = {"hora": fonte(88), "titulo": fonte(46, True), "valor": fonte(96), "valor_menor": fonte(80),
                  "detalhe": fonte(36), "musica": fonte(38, True), "grande_titulo": fonte(64, True), "grande_artista": fonte(44), "pequena": fonte(30), "aviso": fonte(36), "descanso": fonte(300),
                  "descanso_txt": fonte(40)}
        self.fb = os.open("/dev/fb0", os.O_RDWR)
        self.var = bytearray(160)
        fcntl.ioctl(self.fb, 0x4600, self.var)  # FBIOGET_VSCREENINFO

    def mostrar(self, img):
        girada = img.transpose(self.Image.Transpose.ROTATE_90 if GIRAR_ANTI_HORARIO else self.Image.Transpose.ROTATE_270)
        quadro = self.Image.new("RGB", (STRIDE_PX, 1920))
        quadro.paste(girada, (0, 0))
        os.lseek(self.fb, 0, 0)
        os.write(self.fb, quadro.tobytes("raw", "RGBX"))
        struct.pack_into("<II", self.var, 16, 0, 0)
        fcntl.ioctl(self.fb, 0x4606, self.var)  # FBIOPAN_DISPLAY: o painel "command mode" só atualiza assim

    def texto(self, d, xy, txt, fonte, cor, ancora="la"):
        d.text(xy, txt, font=self.f[fonte], fill=cor, anchor=ancora)

    def descanso(self, hora):
        img = self.Image.new("RGB", (LARGURA, ALTURA), "black")
        d = self.ImageDraw.Draw(img)
        self.texto(d, (LARGURA // 2, ALTURA // 2 - 30), hora, "descanso", DESCANSO_COR, "mm")
        self.texto(d, (LARGURA // 2, ALTURA // 2 + 170), "PC sem resposta", "descanso_txt", DESCANSO_COR, "mm")
        return img

    def icone(self, d, acao, caixa):
        x0, y0, x1, y1 = caixa
        k = min(x1 - x0, y1 - y0) / 130  # desenhado para botões de 130 px; escala para os maiores
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        u = lambda v: round(v * k)
        s = u(26)
        tri_dir = lambda x: [(x - s, cy - s), (x - s, cy + s), (x + s, cy)]
        tri_esq = lambda x: [(x + s, cy - s), (x + s, cy + s), (x - s, cy)]
        caixa_ = lambda a, b, c, e: d.rectangle((cx + u(a), cy + u(b), cx + u(c), cy + u(e)), fill=TEXTO)
        if acao == "anterior":
            caixa_(-34, -26, -26, 26)
            d.polygon(tri_esq(cx + u(4)), fill=TEXTO)
        elif acao == "proxima":
            d.polygon(tri_dir(cx - u(4)), fill=TEXTO)
            caixa_(26, -26, 34, 26)
        elif acao == "tocar":
            d.polygon([(cx - u(34), cy - s), (cx - u(34), cy + s), (cx + u(6), cy)], fill=TEXTO)
            caixa_(12, -26, 20, 26)
            caixa_(28, -26, 36, 26)
        else:
            alto = [(-34, -10), (-22, -10), (-4, -26), (-4, 26), (-22, 10), (-34, 10)]
            d.polygon([(cx + u(a), cy + u(b)) for a, b in alto], fill=TEXTO)
            if acao in ("volume-menos", "volume-mais"):
                caixa_(8, -4, 36, 4)
            if acao == "volume-mais":
                caixa_(18, -14, 26, 14)
            elif acao == "mudo":
                d.line((cx + u(8), cy - u(12), cx + u(32), cy + u(12)), fill=TEXTO, width=u(7))
                d.line((cx + u(8), cy + u(12), cx + u(32), cy - u(12)), fill=TEXTO, width=u(7))

    def tocando(self, hora, dados, apertado, capa_grande):
        img = self.Image.new("RGB", (LARGURA, ALTURA), FUNDO)
        d = self.ImageDraw.Draw(img)
        self.texto(d, (MARGEM + 8, MARGEM + LADO_BOTAO // 2), hora, "hora", TEXTO, "lm")
        midia = dados.get("midia")
        if not isinstance(midia, dict):
            self.texto(d, (LARGURA // 2, ALTURA // 2), "Nada tocando no PC", "valor_menor", SECUNDARIO, "mm")
            return img
        if capa_grande is not None:
            img.paste(capa_grande, (60 + (LADO_CAPA_GRANDE - capa_grande.width) // 2, 600 - capa_grande.height // 2))
        else:
            d.rounded_rectangle((60, 600 - LADO_CAPA_GRANDE // 2, 60 + LADO_CAPA_GRANDE, 600 + LADO_CAPA_GRANDE // 2), 24, fill=CARTAO)
        largura = LARGURA - MARGEM - 800
        self.texto(d, (800, 380), self.cortar(d, midia.get("titulo") or "", "grande_titulo", largura), "grande_titulo", TEXTO, "ls")
        artista = midia.get("artista") or ""
        if not midia.get("tocando"):
            artista = "Pausado" + (" · " + artista if artista else "")
        self.texto(d, (800, 400), self.cortar(d, artista, "grande_artista", largura), "grande_artista", SECUNDARIO, "lt")
        agora = time.monotonic()
        for acao, caixa in botoes_tocando():
            ativo = agora - apertado.get(acao, 0) < 0.3
            d.rounded_rectangle(caixa, 28, fill=BOTAO_ATIVO if ativo else BOTAO)
            self.icone(d, acao, caixa)
        return img

    def pontos(self, img, pagina):
        """Bolinhas embaixo: qual página está à mostra."""
        d = self.ImageDraw.Draw(img)
        x = LARGURA // 2 - (len(PAGINAS) - 1) * 14
        for i in range(len(PAGINAS)):
            d.ellipse((x - 5, ALTURA - 15, x + 5, ALTURA - 5), fill=TEXTO if i == pagina else LINHA)
            x += 28

    def grafico(self, d, caixa, valores, cor, piso, rotulo, direita):
        x0, y0, x1, y1 = caixa
        self.texto(d, (x0, y0), rotulo, "pequena", SECUNDARIO)
        self.texto(d, (x1, y0), direita, "pequena", SECUNDARIO, "ra")
        topo, base = y0 + 44, y1
        d.line((x0, base, x1, base), fill=LINHA, width=2)
        pontos, n = [], len(valores)
        for i, v in enumerate(valores):
            if v is None:
                continue
            frac = (min(max(v, piso), 100) - piso) / (100 - piso)
            pontos.append((x0 + (x1 - x0) * (PONTOS - n + i) / (PONTOS - 1), base - 2 - (base - topo - 4) * frac))
        if len(pontos) > 1:
            d.line(pontos, fill=cor, width=4, joint="curve")

    def temp(self, v):
        if v is None:
            return "— °C", SECUNDARIO
        return (num(v) + " °C (alta)", QUENTE) if v >= 80 else (num(v) + " °C", SECUNDARIO)

    def cartao_processador(self, d, caixa, nome, uso, detalhe_resto, temp_v, hist_uso, hist_temp):
        x0, y0, x1, y1 = caixa
        d.rounded_rectangle(caixa, 24, fill=CARTAO)
        px0, px1 = x0 + 32, x1 - 32
        self.texto(d, (px0, y0 + 30), nome, "titulo", SECUNDARIO)
        self.texto(d, (px1, y0 + 14), num(uso) + "%", "valor", TEXTO, "ra")
        txt_temp, cor_temp = self.temp(temp_v)
        self.texto(d, (px0, y0 + 112), txt_temp, "detalhe", cor_temp)
        largura_temp = d.textlength(txt_temp, font=self.f["detalhe"])
        self.texto(d, (px0 + largura_temp, y0 + 112), detalhe_resto, "detalhe", SECUNDARIO)
        altura = (y1 - 24 - (y0 + 175)) // 2
        g1 = (px0, y0 + 175, px1, y0 + 175 + altura - 16)
        g2 = (px0, y0 + 175 + altura + 8, px1, y1 - 24)
        self.grafico(d, g1, hist_uso, AZUL, 0, "Uso, 5 min", "0–100%")
        lidos = [v for v in hist_temp if v is not None]
        self.grafico(d, g2, hist_temp, LARANJA, 20, "Temperatura",
                     "máx %s °C (escala 20–100)" % (num(max(lidos)) if lidos else "—"))

    def cartao_barra(self, d, caixa, nome, valor, detalhe):
        x0, y0, x1, y1 = caixa
        d.rounded_rectangle(caixa, 24, fill=CARTAO)
        px0, px1 = x0 + 32, x1 - 32
        self.texto(d, (px0, y0 + 30), nome, "titulo", SECUNDARIO)
        self.texto(d, (px0, y0 + 100), num(valor) + "%", "valor_menor", TEXTO)
        self.texto(d, (px0, y0 + 205), detalhe, "detalhe", SECUNDARIO)
        by = y1 - 52
        d.rounded_rectangle((px0, by, px1, by + 20), 10, fill=LINHA)
        if valor:
            d.rounded_rectangle((px0, by, px0 + (px1 - px0) * min(valor, 100) / 100, by + 20), 10, fill=AZUL)

    def cartao_perfil(self, d, ativo, apertado):
        x0, y0, x1, y1 = caixa = cartoes()["perfil"]
        d.rounded_rectangle(caixa, 24, fill=CARTAO)
        self.texto(d, (x0 + 32, y0 + 30), "Perfil", "titulo", SECUNDARIO)
        if ativo is None:
            self.texto(d, (x1 - 32, y0 + 36), "outro plano no Windows", "detalhe", SECUNDARIO, "ra")
        agora = time.monotonic()
        for i, (nome, rotulo) in enumerate(PERFIS):
            b = retangulo_perfil(i)
            cor = AZUL if nome == ativo else BOTAO_ATIVO if agora - apertado.get("perfil-" + nome, 0) < 0.3 else BOTAO
            d.rounded_rectangle(b, 20, fill=cor)
            self.texto(d, ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2), rotulo, "musica", TEXTO, "mm")

    def cortar(self, d, txt, fonte, largura):
        """Encurta o texto com reticências até caber na largura."""
        if d.textlength(txt, font=self.f[fonte]) <= largura:
            return txt
        while txt and d.textlength(txt + "…", font=self.f[fonte]) > largura:
            txt = txt[:-1]
        return txt.rstrip() + "…"

    def musica(self, img, d, midia, capa):
        x, fim, meio = 300, retangulo_botao(0)[0] - 24, MARGEM + LADO_BOTAO // 2
        if capa is not None:
            img.paste(capa, (x, meio - capa.height // 2))
            x += LADO_CAPA + 22
        artista = midia.get("artista") or ""
        if not midia.get("tocando"):
            artista = "Pausado" + (" · " + artista if artista else "")
        self.texto(d, (x, meio - 6), self.cortar(d, midia.get("titulo") or "", "musica", fim - x), "musica", TEXTO, "ls")
        self.texto(d, (x, meio + 6), self.cortar(d, artista, "detalhe", fim - x), "detalhe", SECUNDARIO, "lt")

    def painel(self, hora, dados, hist, apertado, capa=None):
        img = self.Image.new("RGB", (LARGURA, ALTURA), FUNDO)
        d = self.ImageDraw.Draw(img)
        self.texto(d, (MARGEM + 8, MARGEM + LADO_BOTAO // 2), hora, "hora", TEXTO, "lm")
        midia = dados.get("midia")
        if isinstance(midia, dict):  # a música tem prioridade sobre o aviso do Afterburner no topo
            self.musica(img, d, midia, capa)
        elif not dados.get("afterburner"):
            self.texto(d, (560, MARGEM + LADO_BOTAO // 2), "Abra o MSI Afterburner", "aviso", AVISO, "lm")
        agora = time.monotonic()
        for i, acao in enumerate(ACOES):
            caixa = retangulo_botao(i)
            ativo = agora - apertado.get(acao, 0) < 0.3
            d.rounded_rectangle(caixa, 20, fill=BOTAO_ATIVO if ativo else BOTAO)
            self.icone(d, acao, caixa)
        c = cartoes()
        vram = "—" if dados.get("vram_mb") is None else num(dados["vram_mb"] / 1024, 1)
        if dados.get("vram_total_mb"):
            vram += " / " + num(dados["vram_total_mb"] / 1024, 1)
        self.cartao_processador(d, c["cpu"], "CPU", dados.get("cpu"),
                                " · %s W" % num(dados.get("cpu_watts")), dados.get("cpu_temp"), hist["cpu"], hist["cpu_temp"])
        self.cartao_processador(d, c["gpu"], "GPU", dados.get("gpu"),
                                " · %s W · fan %s%% · VRAM %s GB" % (num(dados.get("gpu_watts")), num(dados.get("gpu_fan")), vram),
                                dados.get("gpu_temp"), hist["gpu"], hist["gpu_temp"])
        ram_u, ram_t = dados.get("ram_usada"), dados.get("ram_total")
        dis_u, dis_t = dados.get("disco_usado"), dados.get("disco_total")
        livres = None if dis_u is None or dis_t is None else (dis_t - dis_u) / GB
        self.cartao_barra(d, c["ram"], "RAM", pct(ram_u, ram_t), "%s de %s GB · Disco C: %s GB livres" % (
            num(ram_u and ram_u / GB, 1), num(ram_t and ram_t / GB, 1), num(livres)))
        self.cartao_perfil(d, dados.get("perfil"), apertado)
        return img


def main():
    estado = Estado()
    threading.Thread(target=servidor, args=(estado,), daemon=True).start()
    threading.Thread(target=ler_toques, args=(estado,), daemon=True).start()
    tela = Tela()
    brilho_atual = None
    while True:
        hora = time.strftime("%H:%M")
        with estado.trava:
            ativo = estado.dados is not None and time.monotonic() - estado.recebido <= DESCANSO_APOS
            dados = dict(estado.dados or {})
            hist = {s: list(h) for s, h in estado.historico.items()}
            apertado = dict(estado.apertado)
            midia = dados.get("midia")
            mesma = isinstance(midia, dict) and midia.get("id") == estado.capa_id
            capa, capa_grande = (estado.capa, estado.capa_grande) if mesma else (None, None)
            pagina = estado.pagina
        brilho = BRILHO if ativo else BRILHO_DESCANSO
        if brilho != brilho_atual:
            luz(brilho)
            brilho_atual = brilho
        if not ativo:
            tela.mostrar(tela.descanso(hora))
        else:
            if PAGINAS[pagina] == "tocando":
                img = tela.tocando(hora, dados, apertado, capa_grande)
            else:
                img = tela.painel(hora, dados, hist, apertado, capa)
            tela.pontos(img, pagina)
            tela.mostrar(img)
        estado.mudou.wait(1)
        estado.mudou.clear()


if __name__ == "__main__":
    main()
