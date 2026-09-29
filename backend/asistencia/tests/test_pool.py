"""Tests del pool de embeddings en memoria (asistencia/pool.py).

Motivo del pool (medido con 20.005 postulantes sembrados, 2026-09-28): la
verificación 1:N tardaba 1,1 s por persona, de los cuales 875 ms eran traer los
20,5 MB de embeddings desde Postgres — en CADA request. El reconocimiento
facial en sí son 11 ms. Con varios puestos verificando a la vez eso tumba la
base el día de la prueba.
"""
import numpy as np
from django.test import TestCase

from asistencia import pool
from asistencia.models import FotoPostulante, Postulante


def _embedding(semilla: int) -> list[float]:
    rng = np.random.default_rng(semilla)
    vector = rng.normal(size=128)
    return (vector / np.linalg.norm(vector)).tolist()


class PoolEmbeddingsTest(TestCase):
    def setUp(self):
        pool.invalidar()
        self.ana = Postulante.objects.create(
            nombres="Ana", apellidos="Lopez", cedula="1710034065",
            estatura_cm=165, embedding=_embedding(1),
        )
        self.luis = Postulante.objects.create(
            nombres="Luis", apellidos="Diaz", cedula="1719141770",
            estatura_cm=180, embedding=_embedding(2),
        )

    def tearDown(self):
        pool.invalidar()

    def test_encuentra_al_postulante_correcto(self):
        ids, matriz = pool.obtener()
        encontrado = pool.mejor_coincidencia_en_pool(self.luis.embedding, ids, matriz)
        self.assertIsNotNone(encontrado)
        self.assertEqual(encontrado[0], self.luis.id)
        self.assertAlmostEqual(encontrado[1], 1.0, places=5)

    def test_da_el_mismo_resultado_que_leer_todo_de_la_base(self):
        # El pool es una optimización: no puede cambiar a quién identifica.
        from asistencia.facial import mejor_coincidencia

        candidatos = list(Postulante.objects.values_list("id", "embedding"))
        esperado = mejor_coincidencia(self.ana.embedding, candidatos)

        ids, matriz = pool.obtener()
        obtenido = pool.mejor_coincidencia_en_pool(self.ana.embedding, ids, matriz)

        self.assertEqual(obtenido[0], esperado[0])
        self.assertAlmostEqual(obtenido[1], esperado[1], places=6)

    def test_incluye_las_fotos_adicionales(self):
        # Un ángulo adicional apunta al MISMO postulante (ver FotoPostulante).
        FotoPostulante.objects.create(
            postulante=self.ana, foto="postulantes/x.jpg", embedding=_embedding(3)
        )
        pool.invalidar()
        ids, matriz = pool.obtener()
        self.assertEqual(len(ids), 3)
        encontrado = pool.mejor_coincidencia_en_pool(_embedding(3), ids, matriz)
        self.assertEqual(encontrado[0], self.ana.id)

    def test_ignora_postulantes_sin_embedding(self):
        # Precarga por CSV: existe el postulante pero todavía no dio la foto.
        Postulante.objects.create(
            nombres="Sin", apellidos="Foto", cedula="0102030405", estatura_cm=170
        )
        pool.invalidar()
        ids, _ = pool.obtener()
        self.assertEqual(len(ids), 2)

    def test_reusa_la_matriz_entre_llamadas(self):
        ids1, matriz1 = pool.obtener()
        ids2, matriz2 = pool.obtener()
        self.assertIs(matriz1, matriz2)  # mismo objeto: no volvió a la base

    def test_invalidar_obliga_a_releer(self):
        _, matriz1 = pool.obtener()
        pool.invalidar()
        _, matriz2 = pool.obtener()
        self.assertIsNot(matriz1, matriz2)

    def test_un_postulante_nuevo_aparece_tras_invalidar(self):
        pool.obtener()
        nuevo = Postulante.objects.create(
            nombres="Nueva", apellidos="Persona", cedula="0914818815",
            estatura_cm=170, embedding=_embedding(9),
        )
        pool.invalidar()  # lo hace RegistroPostulanteView al crear el registro
        ids, matriz = pool.obtener()
        self.assertEqual(pool.mejor_coincidencia_en_pool(nuevo.embedding, ids, matriz)[0], nuevo.id)

    def test_pool_vacio_no_rompe(self):
        Postulante.objects.all().delete()
        pool.invalidar()
        ids, matriz = pool.obtener()
        self.assertEqual(len(ids), 0)
        self.assertIsNone(pool.mejor_coincidencia_en_pool(_embedding(1), ids, matriz))
