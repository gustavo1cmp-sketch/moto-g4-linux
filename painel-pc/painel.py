"""Painel do PC: lê os sensores, manda à tela do celular (rede USB) e serve a página em localhost."""
import asyncio
import base64
import ctypes
import json
import shutil
import struct
import subprocess
import threading
import time
import urllib.request
import uuid
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORTA = 8765
CELULAR = "http://172.16.42.1:8766/dados"  # tela_celular.py no postmarketOS, pela rede USB
PAGINA = Path(__file__).with_name("index.html")
SEM_JANELA = subprocess.CREATE_NO_WINDOW  # com pythonw, evita janelas piscando

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenFileMappingW.restype = wintypes.HANDLE
kernel32.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.MapViewOfFile.restype = ctypes.c_void_p
kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class MemoriaRam(ctypes.Structure):
    _fields_ = [("tamanho", wintypes.DWORD), ("uso", wintypes.DWORD)] + [
        (nome, ctypes.c_uint64)
        for nome in ("total", "livre", "pag_total", "pag_livre", "virt_total", "virt_livre", "ext_livre")
    ]


def ler_sensores(dados):
    """Converte a memória compartilhada do MSI Afterburner em {nome: valor}."""
    if dados[:4] != b"MHAM":
        return {}
    cabecalho, quantidade, tamanho = struct.unpack_from("<III", dados, 8)
    sensores = {}
    for i in range(quantidade):
        inicio = cabecalho + i * tamanho
        nome = dados[inicio : inicio + 260].split(b"\0")[0].decode("latin1")
        valor = struct.unpack_from("<f", dados, inicio + 1300)[0]
        if valor < 1e38:  # FLT_MAX = sensor sem leitura
            sensores[nome] = valor
    return sensores


def sensores_afterburner():
    alca = kernel32.OpenFileMappingW(4, False, "MAHMSharedMemory")  # 4 = somente leitura
    if not alca:
        return {}  # Afterburner fechado
    try:
        base = kernel32.MapViewOfFile(alca, 4, 0, 0, 0)
        if not base:
            return {}
        try:
            _, _, cabecalho, quantidade, tamanho = struct.unpack("<4sIIII", ctypes.string_at(base, 20))
            return ler_sensores(ctypes.string_at(base, cabecalho + quantidade * tamanho))
        finally:
            kernel32.UnmapViewOfFile(base)
    finally:
        kernel32.CloseHandle(alca)


def vram_total_mb():
    try:
        saida = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True, creationflags=SEM_JANELA,
        ).stdout
        return float(saida.splitlines()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


VRAM_TOTAL = vram_total_mb()


def coletar():
    s = sensores_afterburner()
    ram = MemoriaRam(tamanho=ctypes.sizeof(MemoriaRam))
    kernel32.GlobalMemoryStatusEx(ctypes.byref(ram))
    disco = shutil.disk_usage("C:\\")
    return {
        "afterburner": bool(s),
        "cpu": s.get("CPU usage"),
        "cpu_temp": s.get("CPU temperature"),
        "cpu_watts": s.get("CPU power"),
        "gpu": s.get("GPU usage"),
        "gpu_temp": s.get("GPU temperature"),
        "gpu_watts": s.get("Power"),
        "gpu_fan": s.get("Fan speed"),
        "vram_mb": s.get("Memory usage"),
        "vram_total_mb": VRAM_TOTAL,
        "ram_usada": ram.total - ram.livre,
        "ram_total": ram.total,
        "disco_usado": disco.used,
        "disco_total": disco.total,
        "perfil": perfil_ativo(),
    }


# Lista fixa: o celular só consegue apertar estas teclas, nunca rodar comandos.
TECLAS_MIDIA = {
    "anterior": 0xB1, "tocar": 0xB3, "proxima": 0xB0,
    "volume-menos": 0xAE, "mudo": 0xAD, "volume-mais": 0xAF,
}


# nome: (plano de energia do Windows, perfil salvo no MSI Afterburner)
PERFIS = {
    "silencioso": ("a1841308-3541-4fab-bc81-f71556f20b4a", 3),  # Economia de energia + GPU limitada
    "normal": ("381b4222-f694-41f0-9685-ff5bb260df2e", 2),  # Equilibrado + GPU de fábrica
    "jogo": ("e5f2bba9-82bc-4002-9c89-c406f3fb877a", 1),  # Desempenho Máximo + overclock
}


def aplicar_perfil(nome):
    plano, perfil_gpu = PERFIS[nome]
    subprocess.run(["powercfg", "/setactive", plano], capture_output=True, timeout=10, creationflags=SEM_JANELA)
    # O Afterburner exige administrador; a tarefa (criada por instalar_perfis.ps1) já roda elevada, sem o aviso do Windows.
    subprocess.run(["schtasks", "/run", "/tn", f"Painel do PC\\Afterburner perfil {perfil_gpu}"],
                   capture_output=True, timeout=10, creationflags=SEM_JANELA)


def perfil_ativo():
    """Perfil cujo plano de energia está ativo no Windows, ou None."""
    guid = ctypes.c_void_p()
    if ctypes.windll.powrprof.PowerGetActiveScheme(None, ctypes.byref(guid)):
        return None
    try:
        ativo = str(uuid.UUID(bytes_le=ctypes.string_at(guid, 16)))
    finally:
        kernel32.LocalFree(guid)
    return next((nome for nome, (plano, _) in PERFIS.items() if plano == ativo), None)


def enviar_tecla(codigo):
    for soltar in (0, 2):  # aperta e solta; 1 = tecla estendida
        ctypes.windll.user32.keybd_event(codigo, 0, 1 | soltar, 0)


class Pedido(BaseHTTPRequestHandler):
    def do_POST(self):
        porta = self.server.server_port
        # Barra outros sites abertos no PC: o cabeçalho próprio exige uma permissão
        # (CORS) que nunca damos, e o Host impede apontar um domínio para cá.
        if (self.headers.get("Host") not in (f"localhost:{porta}", f"127.0.0.1:{porta}")
                or self.headers.get("X-Painel") != "1"):
            return self.send_error(403)
        codigo = TECLAS_MIDIA.get(self.path.removeprefix("/midia/"))
        if codigo is None or not self.path.startswith("/midia/"):
            return self.send_error(404)
        enviar_tecla(codigo)
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        if self.path == "/":
            self.responder("text/html", PAGINA.read_bytes())
        elif self.path == "/dados":
            self.responder("application/json", json.dumps(coletar()).encode())
        else:
            self.send_error(404)

    def responder(self, tipo, corpo):
        self.send_response(200)
        self.send_header("Content-Type", tipo + "; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *args):
        pass


class Servidor(ThreadingHTTPServer):
    allow_reuse_address = False  # no Windows, evita duas cópias na mesma porta


capa_ultima = (None, None)  # (id da música, bytes da capa): a capa só é lida quando a música muda
capa_no_celular = None  # id da capa que o celular disse ter


async def _ler_midia():
    global capa_ultima
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Gerente,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as Estado,
    )
    from winrt.windows.storage.streams import Buffer, InputStreamOptions

    sessao = (await Gerente.request_async()).get_current_session()
    if sessao is None:
        return None, None
    p = await sessao.try_get_media_properties_async()
    if not p.title:
        return None, None
    info = {"id": f"{p.title}|{p.artist}", "titulo": p.title, "artista": p.artist,
            "tocando": sessao.get_playback_info().playback_status == Estado.PLAYING}
    if capa_ultima[0] != info["id"]:
        capa = None
        try:  # sem capa, a música ainda aparece
            fluxo = await p.thumbnail.open_read_async()
            buf = Buffer(min(fluxo.size, 1 << 20))
            await fluxo.read_async(buf, buf.capacity, InputStreamOptions.READ_AHEAD)
            capa = bytes(buf)
        except Exception:
            pass
        if not capa:  # o navegador costuma mandar a miniatura depois do título: tenta de novo no próximo envio
            return info, None
        capa_ultima = (info["id"], capa)
    return info, capa_ultima[1]


def ler_midia():
    """Música tocando no Windows (Spotify, navegador...): (info, capa em bytes), ou (None, None)."""
    try:
        return asyncio.run(_ler_midia())
    except Exception:  # sem o pacote winrt ou app de mídia instável: o painel segue sem a música
        return None, None


def enviar_ao_celular():
    """Manda os dados à tela do celular; a resposta traz os botões tocados lá."""
    global capa_no_celular
    dados = coletar()
    dados["midia"], capa = ler_midia()
    if capa and dados["midia"]["id"] != capa_no_celular:
        dados["capa"] = base64.b64encode(capa).decode()
    pedido = urllib.request.Request(CELULAR, data=json.dumps(dados).encode(),
                                    headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(pedido, timeout=3) as resposta:
        resposta = json.loads(resposta.read())
    capa_no_celular = resposta.get("capa_id")
    for acao in resposta.get("acoes", []):
        if not isinstance(acao, str):
            continue
        if acao in TECLAS_MIDIA:
            enviar_tecla(TECLAS_MIDIA[acao])
        elif acao.startswith("perfil-") and acao.removeprefix("perfil-") in PERFIS:
            aplicar_perfil(acao.removeprefix("perfil-"))


def alimentar_celular():
    while True:
        try:
            enviar_ao_celular()
            time.sleep(1)
        except (OSError, ValueError, AttributeError):
            time.sleep(5)  # celular desligado, reiniciando ou sem cabo


if __name__ == "__main__":
    servidor = Servidor(("127.0.0.1", PORTA), Pedido)  # só este PC (e o celular, via USB)
    threading.Thread(target=alimentar_celular, daemon=True).start()
    print(f"Painel em http://localhost:{PORTA}  (feche esta janela para parar)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
