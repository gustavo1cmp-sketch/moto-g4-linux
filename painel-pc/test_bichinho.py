import unittest

import bichinho

PARADO = {"cpu": [5] * 200, "gpu": [3] * 200}
NORMAL = {"cpu": [30] * 200, "gpu": [20] * 200}


def humor(dados=None, hist=NORMAL, carinho=-100.0, agora=1000.0, hora=15):
    base = {"cpu": 30, "gpu": 20, "cpu_temp": 50, "gpu_temp": 45}
    base.update(dados or {})
    return bichinho.humor(base, hist, carinho, agora, hora)[0]


class Humor(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(humor(), "normal")

    def test_carinho_recente_vence_tudo(self):
        self.assertEqual(humor({"gpu_temp": 90}, carinho=998.0), "carinho")

    def test_carinho_passa_depois_de_uns_segundos(self):
        self.assertEqual(humor(carinho=990.0), "normal")

    def test_calor(self):
        self.assertEqual(humor({"cpu_temp": 81}), "quente")

    def test_madrugada_com_pc_em_uso(self):
        self.assertEqual(humor(hora=2), "tarde")

    def test_madrugada_com_pc_parado_dorme(self):
        self.assertEqual(humor({"cpu": 5, "gpu": 3}, hist=PARADO, hora=2), "dormindo")

    def test_esforco(self):
        self.assertEqual(humor({"gpu": 95}), "correndo")

    def test_musica(self):
        self.assertEqual(humor({"midia": {"titulo": "X", "tocando": True}}), "dancando")

    def test_musica_pausada_nao_danca(self):
        self.assertEqual(humor({"midia": {"titulo": "X", "tocando": False}}), "normal")

    def test_pc_parado_dorme(self):
        self.assertEqual(humor({"cpu": 5, "gpu": 3}, hist=PARADO), "dormindo")

    def test_sem_dados_nao_quebra(self):
        self.assertEqual(bichinho.humor({}, {"cpu": [], "gpu": []}, -100.0, 1000.0, 15)[0], "normal")

    def test_frase_cita_a_temperatura(self):
        frase = bichinho.humor({"gpu_temp": 84, "cpu_temp": 50}, NORMAL, -100.0, 1000.0, 15)[1]
        self.assertIn("84", frase)


if __name__ == "__main__":
    unittest.main()
