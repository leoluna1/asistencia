"""Tests del pipeline de reconocimiento facial y anti-spoofing (asistencia/facial.py).

Fixtures en tests/fixtures/: imágenes de muestra del propio proyecto
minivision-ai/Silent-Face-Anti-Spoofing (Apache 2.0) — rostro_real.jpg es una
foto en vivo (image_T1.jpg) y rostro_spoof.jpg es una foto de una foto
(image_F1.jpg), el ataque que el anti-spoofing tiene que bloquear.
"""
from pathlib import Path

import cv2
import numpy as np
from django.test import SimpleTestCase

from asistencia.facial import (
    RostroNoDetectado,
    calcular_embedding,
    detectar_rostro,
    es_rostro_real,
    get_embedding,
    mejor_coincidencia,
    posible_gorra,
    validar_calidad_registro,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _leer_fixture(nombre: str) -> np.ndarray:
    return cv2.imread(str(FIXTURES_DIR / nombre))


class DetectarRostroTest(SimpleTestCase):
    def test_encuentra_rostro_en_foto_real(self):
        imagen, rostro = detectar_rostro(_leer_fixture("rostro_real.jpg"))
        self.assertEqual(imagen.ndim, 3)
        self.assertEqual(rostro.shape, (15,))  # x, y, w, h, 5 landmarks (x,y), score

    def test_lanza_excepcion_si_no_hay_rostro(self):
        imagen_vacia = np.full((300, 300, 3), 128, dtype=np.uint8)
        with self.assertRaises(RostroNoDetectado):
            detectar_rostro(imagen_vacia)


class EmbeddingTest(SimpleTestCase):
    def test_get_embedding_devuelve_128_floats(self):
        embedding = get_embedding(_leer_fixture("rostro_real.jpg"))
        self.assertEqual(len(embedding), 128)
        self.assertTrue(all(isinstance(v, float) for v in embedding))

    def test_calcular_embedding_es_consistente_con_get_embedding(self):
        imagen, rostro = detectar_rostro(_leer_fixture("rostro_real.jpg"))
        self.assertEqual(calcular_embedding(imagen, rostro), get_embedding(_leer_fixture("rostro_real.jpg")))


class AntiSpoofingTest(SimpleTestCase):
    def test_detecta_rostro_real_como_real(self):
        imagen, rostro = detectar_rostro(_leer_fixture("rostro_real.jpg"))
        es_real, confianza = es_rostro_real(imagen, rostro)
        self.assertTrue(es_real)
        self.assertGreater(confianza, 0.5)

    def test_detecta_foto_de_foto_como_spoof(self):
        imagen, rostro = detectar_rostro(_leer_fixture("rostro_spoof.jpg"))
        es_real, _confianza = es_rostro_real(imagen, rostro)
        self.assertFalse(es_real)


def _rostro(x=140, y=100, w=200, h=280, ojos=(190, 180, 290, 180), nariz=(240, 230), score=0.95):
    """Fila sintética estilo YuNet, para probar validar_calidad_registro sin
    depender de una foto real por cada caso de rechazo."""
    ox1, oy1, ox2, oy2 = ojos
    nx, ny = nariz
    return np.array([x, y, w, h, ox1, oy1, ox2, oy2, nx, ny, 0, 0, 0, 0, score])


class ValidarCalidadRegistroTest(SimpleTestCase):
    # Brillo uniforme y alto a propósito: deja que cada test ejercite SU condición
    # puntual sin toparse antes con el chequeo de luz (ver test_rechaza_poca_luz).
    IMAGEN = np.full((480, 480, 3), 200, dtype=np.uint8)

    def test_rostro_bien_encuadrado_pasa(self):
        self.assertIsNone(validar_calidad_registro(self.IMAGEN, _rostro()))

    def test_rechaza_score_bajo(self):
        self.assertIsNotNone(validar_calidad_registro(self.IMAGEN, _rostro(score=0.5)))

    def test_rechaza_poca_luz(self):
        imagen_oscura = np.full((480, 480, 3), 10, dtype=np.uint8)
        self.assertIsNotNone(validar_calidad_registro(imagen_oscura, _rostro()))

    def test_rechaza_rostro_lejano(self):
        self.assertIsNotNone(validar_calidad_registro(self.IMAGEN, _rostro(w=50, h=70)))

    def test_rechaza_rostro_no_centrado(self):
        self.assertIsNotNone(validar_calidad_registro(self.IMAGEN, _rostro(x=10, y=10)))

    def test_rechaza_cabeza_inclinada(self):
        rostro = _rostro(ojos=(190, 150, 290, 220))  # 70px de diferencia vertical entre ojos
        self.assertIsNotNone(validar_calidad_registro(self.IMAGEN, rostro))

    def test_rechaza_rostro_girado(self):
        rostro = _rostro(nariz=(285, 230))  # nariz pegada al ojo derecho, no centrada
        self.assertIsNotNone(validar_calidad_registro(self.IMAGEN, rostro))


class PosibleGorraTest(SimpleTestCase):
    def test_frente_oscura_vs_mejillas_claras_se_marca_como_gorra(self):
        imagen = np.full((480, 480, 3), 200, dtype=np.uint8)
        rostro = _rostro()
        x, y, w, h = int(rostro[0]), int(rostro[1]), int(rostro[2]), int(rostro[3])
        imagen[y : y + int(h * 0.12), x : x + w] = 20  # franja superior oscura (gorra)
        self.assertTrue(posible_gorra(imagen, rostro))

    def test_brillo_uniforme_no_se_marca_como_gorra(self):
        imagen = np.full((480, 480, 3), 200, dtype=np.uint8)
        self.assertFalse(posible_gorra(imagen, _rostro()))


class MejorCoincidenciaTest(SimpleTestCase):
    def test_sin_candidatos_devuelve_none(self):
        self.assertIsNone(mejor_coincidencia([1.0, 0.0], []))

    def test_elige_el_candidato_mas_similar(self):
        consulta = [1.0, 0.0, 0.0]
        candidatos = [
            (1, [0.0, 1.0, 0.0]),  # ortogonal: similitud 0
            (2, [1.0, 0.0, 0.0]),  # idéntico: similitud 1
            (3, [-1.0, 0.0, 0.0]),  # opuesto: similitud -1
        ]
        id_ganador, similitud = mejor_coincidencia(consulta, candidatos)
        self.assertEqual(id_ganador, 2)
        self.assertAlmostEqual(similitud, 1.0)
