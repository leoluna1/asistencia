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
from rest_framework_simplejwt.tokens import AccessToken

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
            "cedula": "1710034065",  # cédula válida (checksum real), ver validators.py
            "estatura_cm": 175,
            "fecha_nacimiento": "1995-05-20",
            "telefono": "0991234567",
            "correo": "juan.perez@example.com",
            "genero": "M",
            "sede": "Quito",
            "foto": _foto("rostro_real.jpg"),
            "password": "clave-segura-123",
        }
        datos.update(overrides)
        return datos

    def test_registra_postulante_con_foto_valida(self):
        response = self.client.post(self.url, self._datos(), format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertNotIn("embedding", response.data)

        postulante = Postulante.objects.get(cedula="1710034065")
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

    def test_completa_un_postulante_precargado_por_csv_en_vez_de_rechazarlo(self):
        precargado = Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065",
            estatura_cm=175, sede="Quito",
        )
        response = self.client.post(
            self.url, self._datos(foto=_foto("rostro_real.jpg")), format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(Postulante.objects.count(), 1)

        precargado.refresh_from_db()
        self.assertTrue(precargado.foto)
        self.assertEqual(len(precargado.embedding), 128)
        # La precarga por CSV no traía estos datos — se completan junto con la foto.
        self.assertEqual(str(precargado.fecha_nacimiento), "1995-05-20")
        self.assertEqual(precargado.correo, "juan.perez@example.com")

    def test_rechaza_cedula_con_digito_verificador_invalido(self):
        response = self.client.post(
            self.url, self._datos(cedula="1234567890"), format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cedula", response.data)
        self.assertEqual(Postulante.objects.count(), 0)

    def test_se_registra_sin_sede_asignar_sede_no_es_responsabilidad_de_este_sistema(self):
        datos = self._datos()
        del datos["sede"]
        response = self.client.post(self.url, datos, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertIsNone(Postulante.objects.get(cedula="1710034065").sede)

    def test_rechaza_si_falta_un_campo_nuevo_obligatorio(self):
        datos = self._datos()
        del datos["telefono"]
        response = self.client.post(self.url, datos, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("telefono", response.data)


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class AgregarFotoPostulanteViewTest(APITestCase):
    def setUp(self):
        self.postulante = Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065",
            estatura_cm=175, sede="Quito",
            foto=_foto("rostro_real.jpg"),
            embedding=get_embedding(cv2_leer("rostro_real.jpg")),
        )
        self.url = f"/api/postulantes/{self.postulante.id}/fotos/"

    def test_agrega_foto_adicional_con_su_embedding(self):
        response = self.client.post(self.url, {"foto": _foto("rostro_real.jpg")}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(self.postulante.fotos_adicionales.count(), 1)
        self.assertEqual(len(self.postulante.fotos_adicionales.get().embedding), 128)

    def test_rechaza_foto_sin_rostro(self):
        foto_sin_rostro = SimpleUploadedFile(
            "sin_rostro.jpg", _imagen_lisa_jpeg(), content_type="image/jpeg"
        )
        response = self.client.post(self.url, {"foto": foto_sin_rostro}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.postulante.fotos_adicionales.count(), 0)

    def test_404_si_el_postulante_no_existe(self):
        response = self.client.post(
            "/api/postulantes/99999/fotos/", {"foto": _foto("rostro_real.jpg")}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ProbarEncuadreViewTest(APITestCase):
    """Chequeo en vivo de la cámara (ver ProbarEncuadreView) — no guarda nada, no
    necesita @override_settings(MEDIA_ROOT=...) porque nunca escribe un archivo."""

    url = "/api/postulantes/probar-encuadre/"

    def test_foto_bien_encuadrada_devuelve_ok(self):
        response = self.client.post(self.url, {"foto": _foto("rostro_real.jpg")}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["ok"])

    def test_sin_rostro_devuelve_motivo(self):
        foto_sin_rostro = SimpleUploadedFile(
            "sin_rostro.jpg", _imagen_lisa_jpeg(), content_type="image/jpeg"
        )
        response = self.client.post(self.url, {"foto": foto_sin_rostro}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["ok"])
        self.assertIn("motivo", response.data)

    def test_no_requiere_login(self):
        # Es parte del flujo público de registro, antes de que exista cualquier cuenta.
        response = self.client.post(self.url, {"foto": _foto("rostro_real.jpg")}, format="multipart")
        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_token_viejo_o_invalido_en_el_navegador_no_lo_rechaza(self):
        # Regresión: el interceptor de Angular manda el token guardado en localStorage
        # a TODAS las requests, incluidas las de este endpoint público. Un token
        # inválido/expirado (ej. de un agente logueado antes en el mismo equipo) hacía
        # que DRF devolviera 401 antes de llegar a chequear el permiso, aunque la vista
        # no exige login — por eso authentication_classes = [] en la vista.
        self.client.credentials(HTTP_AUTHORIZATION="Bearer un-token-invalido-o-vencido")
        response = self.client.post(self.url, {"foto": _foto("rostro_real.jpg")}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)


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

    def test_encuentra_coincidencia_solo_por_foto_adicional(self):
        # Postulante sin embedding principal (caso límite), solo con un ángulo
        # adicional — prueba que VerificarAsistenciaView suma FotoPostulante al
        # pool de candidatos, no solo Postulante.embedding.
        self.postulante.embedding = None
        self.postulante.save()
        from asistencia.models import FotoPostulante

        FotoPostulante.objects.create(
            postulante=self.postulante,
            foto=_foto("rostro_real.jpg", "adicional.jpg"),
            embedding=get_embedding(cv2_leer("rostro_real.jpg")),
        )

        response = self.client.post(
            self.url, {"sede": "Quito", "foto": _foto("rostro_real.jpg")}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data["verificado"])

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
        self.agente = User.objects.create_user(username="agente1", password="clave-segura-123", is_staff=True)
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
        self.agente = User.objects.create_user(username="agente1", password="clave-segura-123", is_staff=True)

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
        ids = [fila["id"] for fila in response.data["results"]]
        self.assertEqual(ids, [segunda.id, primera.id])

    def test_lista_paginada_para_soportar_miles_de_filas(self):
        postulante = Postulante.objects.create(
            nombres="Ana", apellidos="Lopez", cedula="1111111111",
            estatura_cm=160, sede="Quito", foto=_foto("rostro_real.jpg", "a.jpg"),
        )
        Asistencia.objects.create(postulante=postulante, sede="Quito")

        self.client.force_authenticate(self.agente)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("count", response.data)
        self.assertIn("results", response.data)


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class MiPostulanteViewTest(APITestCase):
    url = "/api/mi-postulante/"

    def setUp(self):
        self.usuario = User.objects.create_user(username="1710034065", password="clave-segura-123")
        self.postulante = Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065",
            estatura_cm=175, sede="Quito", correo="juan@example.com",
            foto=_foto("rostro_real.jpg"), usuario=self.usuario,
        )

    def test_requiere_autenticacion(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_postulante_ve_sus_propios_datos(self):
        self.client.force_authenticate(self.usuario)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["cedula"], "1710034065")
        self.assertEqual(response.data["correo"], "juan@example.com")

    def test_postulante_corrige_su_telefono(self):
        self.client.force_authenticate(self.usuario)
        response = self.client.patch(self.url, {"telefono": "0987654321"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.postulante.refresh_from_db()
        self.assertEqual(self.postulante.telefono, "0987654321")

    def test_no_puede_cambiar_su_cedula(self):
        self.client.force_authenticate(self.usuario)
        response = self.client.patch(self.url, {"cedula": "1710034073"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.postulante.refresh_from_db()
        self.assertEqual(self.postulante.cedula, "1710034065")  # no cambió, es de solo lectura

    def test_postulante_no_puede_ver_el_dashboard(self):
        self.client.force_authenticate(self.usuario)
        response = self.client.get("/api/asistencias/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_postulante_no_puede_forzar_asistencia(self):
        self.client.force_authenticate(self.usuario)
        response = self.client.post("/api/asistencia/manual/", {"cedula": "1710034065", "sede": "Quito"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class LoginDePostulanteTest(APITestCase):
    """El registro crea una cuenta (ver RegistroPostulanteView) con la que el
    postulante puede loguearse después por el mismo /api/token/ que usan los
    agentes — este test cubre ese camino de punta a punta."""

    def test_se_loguea_con_la_cuenta_creada_al_registrarse(self):
        datos = {
            "nombres": "Juan", "apellidos": "Pérez", "cedula": "1710034065",
            "estatura_cm": 175, "fecha_nacimiento": "1995-05-20",
            "telefono": "0991234567", "correo": "juan@example.com", "genero": "M",
            "sede": "Quito", "foto": _foto("rostro_real.jpg"), "password": "clave-segura-123",
        }
        self.client.post("/api/postulantes/", datos, format="multipart")

        response = self.client.post(
            "/api/token/", {"username": "1710034065", "password": "clave-segura-123"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn("access", response.data)


class TokenConRolTest(APITestCase):
    """El frontend usa el mismo login para agentes y postulantes (ver
    LoginDePostulanteTest) — necesita saber cuál es cuál para no dejar
    navegar al dashboard a un postulante (ListaAsistenciasView/
    ForzarAsistenciaView ya lo rechazan con 403, pero sin esto la pantalla
    quedaba accesible y vacía en vez de bloqueada)."""

    def test_token_de_postulante_trae_is_staff_false(self):
        datos = {
            "nombres": "Juan", "apellidos": "Pérez", "cedula": "1710034065",
            "estatura_cm": 175, "fecha_nacimiento": "1995-05-20",
            "telefono": "0991234567", "correo": "juan@example.com", "genero": "M",
            "sede": "Quito", "foto": _foto("rostro_real.jpg"), "password": "clave-segura-123",
        }
        self.client.post("/api/postulantes/", datos, format="multipart")

        response = self.client.post(
            "/api/token/", {"username": "1710034065", "password": "clave-segura-123"}
        )
        access = AccessToken(response.data["access"])
        self.assertFalse(access["is_staff"])

    def test_token_de_agente_trae_is_staff_true(self):
        User.objects.create_user("agente1", password="clave-agente-123", is_staff=True)

        response = self.client.post(
            "/api/token/", {"username": "agente1", "password": "clave-agente-123"}
        )
        access = AccessToken(response.data["access"])
        self.assertTrue(access["is_staff"])
