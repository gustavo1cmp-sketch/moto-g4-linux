import http.client
import json
import struct
import threading
import unittest
from unittest import mock

import painel


def bloco(sensores, assinatura=b"MHAM"):
    """Monta a memória compartilhada no formato do MSI Afterburner."""
    cabecalho = struct.pack("<4sIIII", assinatura, 0x20000, 32, len(sensores), 1324).ljust(32, b"\0")
    entradas = b""
    for nome, valor in sensores:
        entrada = bytearray(1324)
        entrada[: len(nome)] = nome.encode()
        struct.pack_into("<f", entrada, 1300, valor)
        entradas += bytes(entrada)
    return cabecalho + entradas


class LerSensores(unittest.TestCase):
    def test_le_nome_e_valor(self):
        dados = bloco([("CPU temperature", 46.5), ("GPU usage", 7)])
        self.assertEqual(painel.ler_sensores(dados), {"CPU temperature": 46.5, "GPU usage": 7.0})

    def test_ignora_sensor_sem_leitura(self):
        sem_leitura = 3.4028234663852886e38  # FLT_MAX
        self.assertEqual(painel.ler_sensores(bloco([("Fan speed", sem_leitura)])), {})

    def test_assinatura_invalida_nao_retorna_nada(self):
        dados = bloco([("CPU usage", 1)], assinatura=b"\xad\xde\0\0")
        self.assertEqual(painel.ler_sensores(dados), {})


class ControlesDeMidia(unittest.TestCase):
    def setUp(self):
        self.servidor = painel.Servidor(("127.0.0.1", 0), painel.Pedido)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        # Só o envio da tecla é substituído, para o teste não mexer no som do PC.
        troca = mock.patch.object(painel, "enviar_tecla")
        self.tecla = troca.start()
        self.addCleanup(troca.stop)
        self.addCleanup(self.servidor.server_close)
        self.addCleanup(self.servidor.shutdown)

    def post(self, caminho, cabecalhos):
        conexao = http.client.HTTPConnection("127.0.0.1", self.servidor.server_port, timeout=5)
        self.addCleanup(conexao.close)
        conexao.request("POST", caminho, headers=cabecalhos)
        return conexao.getresponse().status

    def test_acao_conhecida_envia_a_tecla(self):
        self.assertEqual(self.post("/midia/tocar", {"X-Painel": "1"}), 204)
        self.tecla.assert_called_once_with(0xB3)

    def test_acao_desconhecida_e_recusada(self):
        self.assertEqual(self.post("/midia/desligar", {"X-Painel": "1"}), 404)
        self.tecla.assert_not_called()

    def test_sem_o_cabecalho_do_painel_e_recusado(self):
        self.assertEqual(self.post("/midia/tocar", {}), 403)
        self.tecla.assert_not_called()

    def test_endereco_de_outro_site_e_recusado(self):
        cabecalhos = {"X-Painel": "1", "Host": "site-qualquer.example:8765"}
        self.assertEqual(self.post("/midia/tocar", cabecalhos), 403)
        self.tecla.assert_not_called()


class EnviarAoCelular(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, painel, "capa_no_celular", painel.capa_no_celular)
        painel.capa_no_celular = None

    def enviar(self, resposta, midia=(None, None)):
        """Simula o celular respondendo ao envio dos dados com a lista de botões tocados."""
        corpo = mock.Mock()
        corpo.read.return_value = resposta
        abrir = mock.MagicMock()
        abrir.return_value.__enter__.return_value = corpo
        with mock.patch.object(painel.urllib.request, "urlopen", abrir), \
                mock.patch.object(painel, "coletar", return_value={"cpu": 10}), \
                mock.patch.object(painel, "ler_midia", return_value=midia), \
                mock.patch.object(painel, "enviar_tecla") as tecla:
            painel.enviar_ao_celular()
        pedido = abrir.call_args.args[0]
        return pedido, tecla

    def test_manda_os_dados_por_post(self):
        pedido, _ = self.enviar(b'{"acoes": []}')
        self.assertEqual(pedido.full_url, "http://172.16.42.1:8766/dados")
        self.assertEqual(json.loads(pedido.data), {"cpu": 10, "midia": None})

    def test_capa_vai_quando_o_celular_nao_tem(self):
        midia = ({"id": "Música|Banda", "titulo": "Música"}, b"jpeg")
        pedido, _ = self.enviar(b'{"acoes": [], "capa_id": "M\\u00fasica|Banda"}', midia)
        self.assertEqual(json.loads(pedido.data)["capa"], "anBlZw==")
        self.assertEqual(painel.capa_no_celular, "Música|Banda")

    def test_capa_nao_se_repete(self):
        painel.capa_no_celular = "Música|Banda"
        pedido, _ = self.enviar(b'{"acoes": []}', ({"id": "Música|Banda"}, b"jpeg"))
        self.assertNotIn("capa", json.loads(pedido.data))

    def test_botao_tocado_aperta_a_tecla(self):
        _, tecla = self.enviar(b'{"acoes": ["tocar", "mudo"]}')
        self.assertEqual(tecla.call_args_list, [mock.call(0xB3), mock.call(0xAD)])

    def test_acao_desconhecida_e_ignorada(self):
        with mock.patch.object(painel, "aplicar_perfil") as perfil:
            _, tecla = self.enviar(b'{"acoes": ["desligar", 5, "perfil-turbo", "jogo"]}')
        tecla.assert_not_called()
        perfil.assert_not_called()

    def test_botao_de_perfil_aplica_o_perfil(self):
        with mock.patch.object(painel, "aplicar_perfil") as perfil:
            self.enviar(b'{"acoes": ["perfil-jogo"]}')
        perfil.assert_called_once_with("jogo")


class Perfis(unittest.TestCase):
    def test_perfil_ativo_le_o_plano_do_windows(self):
        # Equilibrado = normal; outro plano qualquer (ex.: Alto desempenho) = nenhum perfil.
        self.assertIn(painel.perfil_ativo(), (*painel.PERFIS, None))

    def test_aplicar_troca_plano_e_roda_a_tarefa_do_afterburner(self):
        with mock.patch.object(painel.subprocess, "run") as rodar:
            painel.aplicar_perfil("jogo")
        comandos = [c.args[0] for c in rodar.call_args_list]
        self.assertEqual(comandos[0], ["powercfg", "/setactive", "e5f2bba9-82bc-4002-9c89-c406f3fb877a"])
        self.assertEqual(comandos[1], ["schtasks", "/run", "/tn", "Painel do PC\\Afterburner perfil 1"])


if __name__ == "__main__":
    unittest.main()
