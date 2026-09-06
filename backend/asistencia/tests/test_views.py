"""Tests de los endpoints de la API (asistencia/views.py).

Usa las mismas fixtures que test_facial.py — ver el docstring de ese archivo
para su procedencia y licencia.
"""
import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from asistencia.facial import get_embedding
from asistencia.models import Asistencia, Postulante

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MEDIA_TMP = tempfile.mkdtemp(prefix="asistencia-tests-media-")


def _foto(nombre: str, nombre_subido: str = "foto.jpg") -> SimpleUploadedFile:
    contenido = (FIXTURES_DIR / nombre).read_bytes()
    return SimpleUploadedFile(nombre_subido, contenido, content_type="image/jpeg")


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class RegistroPostulanteViewTest(APITestCase):
    url = "/api/postulantes/"

    def _datos(self, **overrides):
        datos = {
            "nombres": "Juan",
            "apellidos": "Pérez",
            "cedula": "1234567890",
            "estatura_cm": 175,
            "sede": "Quito",
            "foto": _foto("rostro_real.jpg"),
        }
        datos.update(overrides)
        return datos

    def test_registra_postulante_con_foto_valida(self):
        response = self.client.post(self.url, self._datos(), format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertNotIn("embedding", response.data)

        postulante = Postulante.objects.get(cedula="1234567890")
        self.assertIsNotNone(postulante.embedding)
        self.assertEqual(len(postulante.embedding), 128)

    def test_rechaza_foto_sin_rostro_detectable(self):
        foto_sin_rostro = SimpleUploadedFile(
            "sin_rostro.jpg",
            _imagen_lisa_jpeg(),
            content_type="image/jpeg",
        )
        response = self.client.post(self.url, self._datos(foto=foto_sin_rostro), format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("foto", response.data)
        self.assertEqual(Postulante.objects.count(), 0)

    def test_cedula_duplicada_es_rechazada(self):
        self.client.post(self.url, self._datos(), format="multipart")
        response = self.client.post(
            self.url, self._datos(foto=_foto("rostro_real.jpg")), format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cedula", response.data)


def _imagen_lisa_jpeg() -> bytes:
    """Bytes de un JPEG válido pero sin ningún rostro (para probar el rechazo)."""
    import cv2
    import numpy as np

    imagen = np.full((300, 300, 3), 128, dtype=np.uint8)
    ok, buffer = cv2.imencode(".jpg", imagen)
    assert ok
    return buffer.tobytes()


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class VerificarAsistenciaViewTest(APITestCase):
    url = "/api/verificar/"

    def setUp(self):
        self.postulante = Postulante.objects.create(
            nombres="Juan",
            apellidos="Pérez",
            cedula="1234567890",
            estatura_cm=175,
            sede="Quito",
            foto=_foto("rostro_real.jpg"),
            embedding=get_embedding(cv2_leer("rostro_real.jpg")),
        )

    def test_verifica_postulante_registrado(self):
        response = self.client.post(
            self.url, {"sede": "Quito", "foto": _foto("rostro_real.jpg")}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["verificado"])
        self.assertFalse(response.data["ya_registrado"])
        self.assertEqual(Asistencia.objects.count(), 1)
        self.assertEqual(Asistencia.objects.get().metodo, Asistencia.Metodo.AUTOMATICO)

    def test_segunda_verificacion_no_duplica_asistencia(self):
        self.client.post(self.url, {"sede": "Quito", "foto": _foto("rostro_real.jpg")}, format="multipart")
        response = self.client.post(
            self.url, {"sede": "Guayaquil", "foto": _foto("rostro_real.jpg")}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["verificado"])
        self.assertTrue(response.data["ya_registrado"])
        self.assertEqual(Asistencia.objects.count(), 1)
        # No se pisa la sede de la primera verificación con la segunda.
        self.assertEqual(Asistencia.objects.get().sede, "Quito")

    def test_rechaza_intento_de_suplantacion_con_foto_de_foto(self):
        response = self.client.post(
            self.url, {"sede": "Quito", "foto": _foto("rostro_spoof.jpg")}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["verificado"])
        self.assertEqual(response.data["motivo"], "posible_suplantacion")
        self.assertEqual(Asistencia.objects.count(), 0)

    def test_sin_rostro_detectado(self):
        foto_sin_rostro = SimpleUploadedFile(
            "sin_rostro.jpg", _imagen_lisa_jpeg(), content_type="image/jpeg"
        )
        response = self.client.post(
            self.url, {"sede": "Quito", "foto": foto_sin_rostro}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["verificado"])
        self.assertEqual(response.data["motivo"], "no_se_detecto_rostro")

    def test_sin_coincidencia_si_no_hay_postulantes_registrados(self):
        Postulante.objects.all().delete()
        response = self.client.post(
            self.url, {"sede": "Quito", "foto": _foto("rostro_real.jpg")}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["verificado"])
        self.assertEqual(response.data["motivo"], "sin_coincidencia")

    def test_falta_sede_es_error_de_validacion(self):
        response = self.client.post(self.url, {"foto": _foto("rostro_real.jpg")}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_falta_foto_es_error_de_validacion(self):
        response = self.client.post(self.url, {"sede": "Quito"}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


def cv2_leer(nombre: str):
    import cv2

    return cv2.imread(str(FIXTURES_DIR / nombre))


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class ForzarAsistenciaViewTest(APITestCase):
    url = "/api/asistencia/manual/"

    def setUp(self):
        self.agente = User.objects.create_user(username="agente1", password="clave-segura-123")
        self.postulante = Postulante.objects.create(
            nombres="Juan",
            apellidos="Pérez",
            cedula="1234567890",
            estatura_cm=175,
            sede="Quito",
            foto=_foto("rostro_real.jpg"),
        )

    def test_requiere_autenticacion(self):
        response = self.client.post(self.url, {"cedula": "1234567890", "sede": "Quito"})
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_agente_autenticado_fuerza_asistencia(self):
        self.client.force_authenticate(self.agente)
        response = self.client.post(self.url, {"cedula": "1234567890", "sede": "Quito"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["verificado"])
        self.assertEqual(response.data["metodo"], Asistencia.Metodo.MANUAL)
        self.assertEqual(response.data["forzado_por"], "agente1")

        asistencia = Asistencia.objects.get()
        self.assertEqual(asistencia.forzado_por, self.agente)

    def test_cedula_inexistente_es_error_de_validacion(self):
        self.client.force_authenticate(self.agente)
        response = self.client.post(self.url, {"cedula": "0000000000", "sede": "Quito"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_no_duplica_si_ya_tenia_asistencia_automatica(self):
        Asistencia.objects.create(
            postulante=self.postulante, sede="Quito", metodo=Asistencia.Metodo.AUTOMATICO, confianza=0.9
        )
        self.client.force_authenticate(self.agente)
        response = self.client.post(self.url, {"cedula": "1234567890", "sede": "Guayaquil"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["ya_registrado"])
        self.assertEqual(Asistencia.objects.count(), 1)
        # No se pisa el método automático original con el intento manual posterior.
        self.assertEqual(Asistencia.objects.get().metodo, Asistencia.Metodo.AUTOMATICO)


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class ListaAsistenciasViewTest(APITestCase):
    url = "/api/asistencias/"

    def setUp(self):
        self.agente = User.objects.create_user(username="agente1", password="clave-segura-123")

    def test_requiere_autenticacion(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_lista_las_asistencias_mas_recientes_primero(self):
        p1 = Postulante.objects.create(
            nombres="Ana", apellidos="Lopez", cedula="1111111111",
            estatura_cm=160, sede="Quito", foto=_foto("rostro_real.jpg", "a.jpg"),
        )
        p2 = Postulante.objects.create(
            nombres="Luis", apellidos="Diaz", cedula="2222222222",
            estatura_cm=180, sede="Quito", foto=_foto("rostro_real.jpg", "b.jpg"),
        )
        primera = Asistencia.objects.create(postulante=p1, sede="Quito")
        segunda = Asistencia.objects.create(postulante=p2, sede="Quito")

        self.client.force_authenticate(self.agente)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [fila["id"] for fila in response.data]
        self.assertEqual(ids, [segunda.id, primera.id])
