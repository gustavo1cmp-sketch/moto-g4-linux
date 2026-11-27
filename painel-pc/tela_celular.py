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

import bichinho
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ENDERECO = ("172.16.42.1", 8766)  # só a rede USB; o Wi-Fi não alcança
PC = "172.16.42.2"
LARGURA, ALTURA = 1920, 1080  # desenho na horizontal; a tela física é 1080x1920
STRIDE_PX = 1088  # linha do framebuffer tem 4352 bytes (1088 px), não 1080
ROTACAO = "/var/lib/tela-painel/rotacao"  # "1" = girada 180°; toque no relógio alterna
DESCANSO_APOS = 30  # segundos sem dados do PC
PONTOS = 300  # 5 min com um envio por segundo
BRILHO, BRILHO_DESCANSO = 160, 12  # 255 esquenta o celular sem ganho visível em ambiente interno
LUZ = "/sys/class/leds/lcd-backlight/brightness"
TOQUE = "/dev/input/event2"  # synaptics_dsx_i2c
GB = 1024 ** 3

VAO_BOTAO, MARGEM = 12, 20
TOPO = 130  # faixa do relógio; os cartões começam abaixo dela
RELOGIO = (0, 0, 420, TOPO)  # área de toque que gira a tela
AREA_BICHINHO = (620, 400, 1300, 960)  # toque aqui = carinho
LADO_CAPA_GRANDE = 680
PAGINAS = ("painel", "tocando", "bichinho")  # arrastar para o lado troca a página; nova função = nova página aqui
ARRASTE_MIN = 220  # px de arraste na horizontal para virar a página
SERIES = ("cpu", "cpu_temp", "gpu", "gpu_temp")
PERFIS = (("silencioso", "Silencioso"), ("normal", "Normal"), ("jogo", "Jogo"))  # mesmos nomes do painel.py

# Visual "gamer": fundo quase preto com grade, bordas neon que mudam de cor com a temperatura.
FUNDO, GRADE, CARTAO, BOTAO, BOTAO_ATIVO = "#04060c", "#0b1222", "#0a0f1c", "#0e1526", "#1f2c4a"
TEXTO, SECUNDARIO, LINHA, DESCANSO_COR = "#e6f4ff", "#7d8ba3", "#1a2236", "#3a4560"
CIANO, ROXO, MAGENTA, VERMELHO, LARANJA, AVISO = "#00e5ff", "#a259ff", "#ff2bd6", "#ff3355", "#ff8c1a", "#ffd000"
COR_PERFIL = {"silencioso": CIANO, "normal": ROXO, "jogo": VERMELHO}
FONTES = "/usr/local/share/fonts/painel/"  # Orbitron e Rajdhani (licença OFL), copiadas de google/fonts
DIAS, MESES = ("SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM"), "JAN FEV MAR ABR MAI JUN JUL AGO SET OUT NOV DEZ".split()


def cor_nivel(v, limites=(60, 70, 80)):
    """Ciano (frio) → roxo → magenta → vermelho (quente)."""
    if v is None:
        return CIANO
    return next((c for c, lim in zip((CIANO, ROXO, MAGENTA), limites) if v < lim), VERMELHO)


def mistura(a, b, k):
    """Cor a misturada com b; k = quanto de a (0–1)."""
    ra, rb = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (a, b))
    return "#%02x%02x%02x" % tuple(round(x * k + y * (1 - k)) for x, y in zip(ra, rb))


def chanfro(caixa, c=26):
    """Polígono da caixa com os cantos superior esquerdo e inferior direito cortados (estilo HUD)."""
    x0, y0, x1, y1 = caixa
    return [(x0 + c, y0), (x1, y0), (x1, y1 - c), (x1 - c, y1), (x0, y1), (x0, y0 + c)]


def cartoes():
    """Caixas dos quatro cartões: CPU e GPU em cima, RAM e perfil embaixo."""
    topo, vao = TOPO, 20
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
    if RELOGIO[0] <= x < RELOGIO[2] and RELOGIO[1] <= y < RELOGIO[3]:
        return "girar"
    if PAGINAS[pagina] == "bichinho":
        x0, y0, x1, y1 = AREA_BICHINHO
        return "carinho" if x0 <= x < x1 and y0 <= y < y1 else None
    if PAGINAS[pagina] == "tocando":
        for acao, (x0, y0, x1, y1) in botoes_tocando():
            if x0 - 14 <= x < x1 + 14 and y0 - 14 <= y < y1 + 14:
                return acao
        return None
    for i, (nome, _) in enumerate(PERFIS):
        x0, y0, x1, y1 = retangulo_perfil(i)
        if x0 - VAO_BOTAO // 2 <= x < x1 + VAO_BOTAO // 2 and y0 - VAO_BOTAO <= y < y1 + VAO_BOTAO:
            return "perfil-" + nome
    return None


def toque_para_desenho(px, py, girada=False):
    """Converte o toque (tela em pé, 1080x1920) para as coordenadas do desenho deitado."""
    if not girada:
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
        self.capa_grande, self.capa_id = None, None
        self.pagina = 0
        self.carinho_em = float("-inf")
        try:
            with open(ROTACAO) as f:
                self.girada = f.read().strip() == "1"
        except OSError:
            self.girada = False

    def girar(self):
        with self.trava:
            self.girada = not self.girada
        try:
            os.makedirs(os.path.dirname(ROTACAO), exist_ok=True)
            with open(ROTACAO, "w") as f:
                f.write("1" if self.girada else "0")
        except OSError:  # sem gravar, vale só até reiniciar
            pass
        self.mudou.set()

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
                    self.capa_grande, self.capa_id = caber(LADO_CAPA_GRANDE), midia.get("id")
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
                # Dedo levantado: esta tela (synaptics, protocolo B) não manda BTN_TOUCH, só ABS_MT_TRACKING_ID = -1.
                # shortcut: pensado para um dedo; com dois, o segundo pode encerrar o gesto do primeiro.
                elif ((tipo == 3 and codigo == 0x39 and valor == -1) or (tipo == 1 and codigo == 0x14A and valor == 0)) \
                        and x is not None and y is not None:
                    fim = toque_para_desenho(x, y, estado.girada)
                    tipo_gesto, valor_gesto = gesto(inicio or fim, fim)
                    if tipo_gesto == "virar":
                        estado.virar(valor_gesto)
                    else:
                        acao = botao_em(*valor_gesto, pagina=estado.pagina)
                        if acao == "girar":
                            estado.girar()
                        elif acao == "carinho":
                            estado.carinho_em = time.monotonic()
                            estado.mudou.set()
                        elif acao:
                            estado.tocar(acao)
                    x = y = inicio = None
                    continue
                if inicio is None and x is not None and y is not None:  # primeiro ponto do dedo
                    inicio = toque_para_desenho(x, y, estado.girada)
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
        from PIL import ImageChops, ImageFilter
        self.ImageChops, self.ImageFilter = ImageChops, ImageFilter

        def orbitron(tamanho):  # números e títulos; só tem letras sem acento
            f = ImageFont.truetype(FONTES + "Orbitron.ttf", tamanho)
            f.set_variation_by_name("Bold")
            return f
        rajdhani = lambda tamanho, negrito=False: ImageFont.truetype(
            FONTES + "Rajdhani-%s.ttf" % ("Bold" if negrito else "SemiBold"), tamanho)
        self.f = {"hora": orbitron(78), "titulo": orbitron(40), "valor": orbitron(92), "valor_menor": orbitron(76),
                  "data": rajdhani(44, True), "detalhe": rajdhani(42), "musica": rajdhani(48, True),
                  "grande_titulo": rajdhani(82, True), "grande_artista": rajdhani(54), "pequena": rajdhani(34),
                  "aviso": rajdhani(46, True), "descanso": orbitron(240), "descanso_txt": rajdhani(48),
                  "balao": ImageFont.truetype("/usr/share/fonts/dejavu/DejaVuSans.ttf", 44)}  # tem ♪
        self.fundos = {}
        self.fb = os.open("/dev/fb0", os.O_RDWR)
        self.var = bytearray(160)
        fcntl.ioctl(self.fb, 0x4600, self.var)  # FBIOGET_VSCREENINFO
        # FBIOBLANK/UNBLANK: o driver do toque (synaptics) só sai do modo de espera com este aviso de "tela acesa".
        fcntl.ioctl(self.fb, 0x4611, 0)

    def mostrar(self, img, girada=False):
        girada = img.transpose(self.Image.Transpose.ROTATE_270 if girada else self.Image.Transpose.ROTATE_90)
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

    def fundo(self, molduras):
        """Grade + linha neon do topo + molduras brilhantes [(caixa, cor)]; o brilho é caro, então fica em cache."""
        chave = tuple(molduras)
        if chave not in self.fundos:
            if len(self.fundos) > 12:
                self.fundos.clear()
            img = self.Image.new("RGB", (LARGURA, ALTURA), FUNDO)
            d = self.ImageDraw.Draw(img)
            for x in range(0, LARGURA, 48):
                d.line((x, 0, x, ALTURA), fill=GRADE)
            for y in range(0, ALTURA, 48):
                d.line((0, y, LARGURA, y), fill=GRADE)
            for caixa, _ in molduras:
                d.polygon(chanfro(caixa), fill=CARTAO)
            # brilho desenhado em 1/4 do tamanho, borrado e ampliado: o mesmo efeito, bem mais rápido
            brilho = self.Image.new("RGB", (LARGURA // 4, ALTURA // 4), "black")
            b = self.ImageDraw.Draw(brilho)
            for caixa, cor in molduras:
                pts = [(x / 4, y / 4) for x, y in chanfro(caixa)]
                b.line(pts + [pts[0]], fill=cor, width=2)
            for x in range(LARGURA // 4):  # linha do topo, degradê ciano → magenta
                b.point((x, (TOPO - 13) // 4), fill=mistura(MAGENTA, CIANO, x / (LARGURA / 4)))
            brilho = brilho.filter(self.ImageFilter.GaussianBlur(3)).resize((LARGURA, ALTURA), self.Image.BILINEAR)
            img = self.ImageChops.add(img, brilho)
            d = self.ImageDraw.Draw(img)
            for x in range(0, LARGURA, 2):
                d.line((x, TOPO - 13, x + 1, TOPO - 13), fill=mistura(MAGENTA, CIANO, x / LARGURA), width=2)
            for caixa, cor in molduras:
                pts = chanfro(caixa)
                d.line(pts + [pts[0]], fill=cor, width=3)
                claro = mistura("#ffffff", cor, 0.45)  # cantos cortados mais fortes
                d.line((pts[5], pts[0]), fill=claro, width=7)
                d.line((pts[2], pts[3]), fill=claro, width=7)
            self.fundos[chave] = img
        return self.fundos[chave].copy()

    def topo(self, d, hora):
        self.texto(d, (MARGEM + 8, TOPO // 2 - 6), hora, "hora", TEXTO, "lm")
        agora = time.localtime()
        data = "%s %02d %s" % (DIAS[agora.tm_wday], agora.tm_mday, MESES[agora.tm_mon - 1])
        x = MARGEM + 8 + d.textlength(hora, font=self.f["hora"]) + 34
        self.texto(d, (x, TOPO // 2 - 2), data, "data", CIANO, "lm")

    def botao(self, d, caixa, cor, ativo, apertado, c=22):
        """Botão chanfrado: o ativo ganha fundo tingido e borda dupla (brilho falso, sem borrar)."""
        pts = chanfro(caixa, c)
        fundo = BOTAO_ATIVO if apertado else mistura(cor, CARTAO, 0.22) if ativo else BOTAO
        d.polygon(pts, fill=fundo)
        if ativo:
            x0, y0, x1, y1 = caixa
            fora = chanfro((x0 - 6, y0 - 6, x1 + 6, y1 + 6), c + 2)
            d.line(fora + [fora[0]], fill=mistura(cor, FUNDO, 0.35), width=3)
        d.line(pts + [pts[0]], fill=cor if ativo else mistura(cor, FUNDO, 0.45), width=3)
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
        quadro_capa = (60, 600 - LADO_CAPA_GRANDE // 2, 60 + LADO_CAPA_GRANDE, 600 + LADO_CAPA_GRANDE // 2)
        midia = dados.get("midia")
        img = self.fundo(((quadro_capa, CIANO),) if isinstance(midia, dict) else ())
        d = self.ImageDraw.Draw(img)
        self.topo(d, hora)
        if not isinstance(midia, dict):
            self.texto(d, (LARGURA // 2, ALTURA // 2), "NADA TOCANDO", "valor_menor", SECUNDARIO, "mm")
            return img
        if capa_grande is not None:
            img.paste(capa_grande, (60 + (LADO_CAPA_GRANDE - capa_grande.width) // 2, 600 - capa_grande.height // 2))
            d = self.ImageDraw.Draw(img)
            pts = chanfro(quadro_capa)  # corta os cantos da capa para seguir a moldura
            d.polygon([(quadro_capa[0], quadro_capa[1]), pts[0], pts[5]], fill=FUNDO)
            d.polygon([(quadro_capa[2], quadro_capa[3]), pts[2], pts[3]], fill=FUNDO)
            d.line(pts + [pts[0]], fill=CIANO, width=3)
        largura = LARGURA - MARGEM - 800
        self.texto(d, (800, 380), self.cortar(d, midia.get("titulo") or "", "grande_titulo", largura), "grande_titulo", TEXTO, "ls")
        artista = midia.get("artista") or ""
        tocando = midia.get("tocando")
        if not tocando:
            artista = "PAUSADO" + (" · " + artista if artista else "")
        self.texto(d, (800, 404), self.cortar(d, artista, "grande_artista", largura), "grande_artista",
                   CIANO if tocando else AVISO, "lt")
        agora = time.monotonic()
        for acao, caixa in botoes_tocando():
            principal = acao == "tocar"
            self.botao(d, caixa, MAGENTA if principal else CIANO, principal, agora - apertado.get(acao, 0) < 0.3, 30)
            self.icone(d, acao, caixa)
        return img
    def bichinho(self, hora, dados, hist, carinho_em):
        agora = time.monotonic()
        estado, frase = bichinho.humor(dados, hist, carinho_em, agora, time.localtime().tm_hour)
        pequeno = bichinho.desenhar(self.Image, self.ImageDraw, estado, int(agora * 4), time.localtime().tm_hour)
        img = pequeno.resize((LARGURA, ALTURA), self.Image.NEAREST)
        d = self.ImageDraw.Draw(img)
        self.texto(d, (MARGEM + 8, TOPO // 2 + 4), hora, "hora", TEXTO, "lm")
        frase = self.cortar(d, frase, "balao", 1300)
        largura = d.textlength(frase, font=self.f["balao"]) + 80
        x0, y0, y1 = LARGURA // 2 - largura // 2, 220, 330
        d.rounded_rectangle((x0, y0, x0 + largura, y1), 36, fill=TEXTO)
        d.polygon([(LARGURA // 2 - 26, y1 - 2), (LARGURA // 2 + 26, y1 - 2), (LARGURA // 2, y1 + 34)], fill=TEXTO)
        self.texto(d, (LARGURA // 2, (y0 + y1) // 2), frase, "balao", FUNDO, "mm")
        numeros = "CPU %s%% · %s °C        GPU %s%% · %s °C" % tuple(
            num(dados.get(k)) for k in ("cpu", "cpu_temp", "gpu", "gpu_temp"))
        self.texto(d, (LARGURA // 2, ALTURA - 70), numeros, "detalhe", SECUNDARIO, "mm")
        return img

    def pontos(self, img, pagina):
        """Tracinhos embaixo: qual página está à mostra."""
        d = self.ImageDraw.Draw(img)
        x = LARGURA // 2 - (len(PAGINAS) * 52 - 12) // 2
        for i in range(len(PAGINAS)):
            d.polygon([(x + 6, ALTURA - 14), (x + 40, ALTURA - 14), (x + 34, ALTURA - 6), (x, ALTURA - 6)],
                      fill=CIANO if i == pagina else LINHA)
            x += 52
    def grafico(self, img, d, caixa, valores, cor, piso, rotulo, direita):
        x0, y0, x1, y1 = caixa
        self.texto(d, (x0, y0), rotulo, "pequena", SECUNDARIO)
        self.texto(d, (x1, y0), direita, "pequena", SECUNDARIO, "ra")
        topo, base = y0 + 46, y1
        meio = (topo + base) // 2
        for x in range(x0, x1, 18):  # linha de 50% tracejada
            d.line((x, meio, x + 8, meio), fill=LINHA)
        d.line((x0, base, x1, base), fill=LINHA, width=2)
        pontos, n = [], len(valores)
        for i, v in enumerate(valores):
            if v is None:
                continue
            frac = (min(max(v, piso), 100) - piso) / (100 - piso)
            pontos.append((x0 + (x1 - x0) * (PONTOS - n + i) / (PONTOS - 1), base - 2 - (base - topo - 4) * frac))
        if len(pontos) < 2:
            return
        d.polygon(pontos + [(pontos[-1][0], base - 1), (pontos[0][0], base - 1)], fill=mistura(cor, CARTAO, 0.16))
        # brilho da linha: desenhada grossa em meia resolução, borrada e somada à imagem
        area = (x0 - 12, topo - 12, x1 + 12, base + 12)
        tam = (area[2] - area[0], area[3] - area[1])
        camada = self.Image.new("RGB", (tam[0] // 2, tam[1] // 2), "black")
        self.ImageDraw.Draw(camada).line([((x - area[0]) / 2, (y - area[1]) / 2) for x, y in pontos],
                                         fill=mistura(cor, "#000000", 0.8), width=4)
        camada = camada.filter(self.ImageFilter.GaussianBlur(3)).resize(tam)
        img.paste(self.ImageChops.add(img.crop(area), camada), area[:2])
        d.line(pontos, fill=cor, width=4, joint="curve")
        d.line(pontos, fill=mistura("#ffffff", cor, 0.5), width=1)
    def temp(self, v):
        if v is None:
            return "— °C", SECUNDARIO
        return (num(v) + " °C (ALTA)" if v >= 80 else num(v) + " °C"), cor_nivel(v)
    def cartao_processador(self, img, d, caixa, nome, uso, detalhe_resto, temp_v, hist_uso, hist_temp):
        x0, y0, x1, y1 = caixa
        cor = cor_nivel(temp_v)
        px0, px1 = x0 + 40, x1 - 36
        self.texto(d, (px0, y0 + 34), nome, "titulo", cor)
        self.texto(d, (px1, y0 + 18), num(uso) + "%", "valor", TEXTO, "ra")
        txt_temp, cor_temp = self.temp(temp_v)
        self.texto(d, (px0, y0 + 108), txt_temp, "detalhe", cor_temp)
        largura_temp = d.textlength(txt_temp, font=self.f["detalhe"])
        self.texto(d, (px0 + largura_temp, y0 + 108), detalhe_resto, "detalhe", SECUNDARIO)
        altura = (y1 - 28 - (y0 + 175)) // 2
        g1 = (px0, y0 + 175, px1, y0 + 175 + altura - 16)
        g2 = (px0, y0 + 175 + altura + 8, px1, y1 - 28)
        self.grafico(img, d, g1, hist_uso, cor, 0, "USO · 5 MIN", "0–100%")
        lidos = [v for v in hist_temp if v is not None]
        self.grafico(img, d, g2, hist_temp, LARANJA, 20, "TEMPERATURA",
                     "máx %s °C (escala 20–100)" % (num(max(lidos)) if lidos else "—"))
    def cartao_barra(self, d, caixa, nome, valor, detalhe):
        x0, y0, x1, y1 = caixa
        cor = cor_nivel(valor, (60, 75, 90))
        px0, px1 = x0 + 40, x1 - 36
        self.texto(d, (px0, y0 + 34), nome, "titulo", cor)
        self.texto(d, (px1, y0 + 18), num(valor) + "%", "valor_menor", TEXTO, "ra")
        self.texto(d, (px0, y0 + 150), detalhe, "detalhe", SECUNDARIO)
        n, vao, by, alto = 24, 8, y1 - 80, 34  # barra em segmentos inclinados
        larg = (px1 - px0 - (n - 1) * vao) / n
        cheios = round(min(valor or 0, 100) / 100 * n)
        for i in range(n):
            x = px0 + i * (larg + vao)
            cs = mistura("#ffffff", cor, 0.35) if i == cheios - 1 else cor if i < cheios else LINHA
            d.polygon([(x + 8, by), (x + larg, by), (x + larg - 8, by + alto), (x, by + alto)], fill=cs)
    def cartao_perfil(self, d, ativo, apertado):
        x0, y0, x1, y1 = cartoes()["perfil"]
        self.texto(d, (x0 + 40, y0 + 34), "PERFIL", "titulo", COR_PERFIL.get(ativo, SECUNDARIO))
        if ativo is None:
            self.texto(d, (x1 - 36, y0 + 40), "outro plano no Windows", "detalhe", SECUNDARIO, "ra")
        agora = time.monotonic()
        for i, (nome, rotulo) in enumerate(PERFIS):
            b = retangulo_perfil(i)
            self.botao(d, b, COR_PERFIL[nome], nome == ativo, agora - apertado.get("perfil-" + nome, 0) < 0.3)
            self.texto(d, ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2 + 4), rotulo.upper(), "musica",
                       TEXTO if nome == ativo else SECUNDARIO, "mm")
    def cortar(self, d, txt, fonte, largura):
        """Encurta o texto com reticências até caber na largura."""
        if d.textlength(txt, font=self.f[fonte]) <= largura:
            return txt
        while txt and d.textlength(txt + "…", font=self.f[fonte]) > largura:
            txt = txt[:-1]
        return txt.rstrip() + "…"

    def painel(self, hora, dados, hist, apertado):
        c = cartoes()
        ram = pct(dados.get("ram_usada"), dados.get("ram_total"))
        img = self.fundo(((c["cpu"], cor_nivel(dados.get("cpu_temp"))), (c["gpu"], cor_nivel(dados.get("gpu_temp"))),
                          (c["ram"], cor_nivel(ram, (60, 75, 90))),
                          (c["perfil"], COR_PERFIL.get(dados.get("perfil"), DESCANSO_COR))))
        d = self.ImageDraw.Draw(img)
        self.topo(d, hora)
        if not dados.get("afterburner"):
            self.texto(d, (LARGURA - MARGEM - 8, TOPO // 2 - 4), "ABRA O MSI AFTERBURNER", "aviso", AVISO, "rm")
        vram = "—" if dados.get("vram_mb") is None else num(dados["vram_mb"] / 1024, 1)
        if dados.get("vram_total_mb"):
            vram += " / " + num(dados["vram_total_mb"] / 1024, 1)
        self.cartao_processador(img, d, c["cpu"], "CPU", dados.get("cpu"),
                                " · %s W" % num(dados.get("cpu_watts")), dados.get("cpu_temp"), hist["cpu"], hist["cpu_temp"])
        self.cartao_processador(img, d, c["gpu"], "GPU", dados.get("gpu"),
                                " · %s W · fan %s%% · VRAM %s GB" % (num(dados.get("gpu_watts")), num(dados.get("gpu_fan")), vram),
                                dados.get("gpu_temp"), hist["gpu"], hist["gpu_temp"])
        ram_u, ram_t = dados.get("ram_usada"), dados.get("ram_total")
        dis_u, dis_t = dados.get("disco_usado"), dados.get("disco_total")
        livres = None if dis_u is None or dis_t is None else (dis_t - dis_u) / GB
        self.cartao_barra(d, c["ram"], "RAM", ram, "%s de %s GB · Disco C: %s GB livres" % (
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
            capa_grande = estado.capa_grande if mesma else None
            pagina, girada, carinho_em = estado.pagina, estado.girada, estado.carinho_em
        brilho = BRILHO if ativo else BRILHO_DESCANSO
        if brilho != brilho_atual:
            luz(brilho)
            brilho_atual = brilho
        if not ativo:
            tela.mostrar(tela.descanso(hora), girada)
        else:
            if PAGINAS[pagina] == "tocando":
                img = tela.tocando(hora, dados, apertado, capa_grande)
            elif PAGINAS[pagina] == "bichinho":
                img = tela.bichinho(hora, dados, hist, carinho_em)
            else:
                img = tela.painel(hora, dados, hist, apertado)
            tela.pontos(img, pagina)
            tela.mostrar(img, girada)
        estado.mudou.wait(0.25 if ativo and PAGINAS[pagina] == "bichinho" else 1)  # só o bichinho anima
        estado.mudou.clear()


if __name__ == "__main__":
    main()
