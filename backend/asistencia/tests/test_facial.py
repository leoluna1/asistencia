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
