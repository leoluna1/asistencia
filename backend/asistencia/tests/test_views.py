"""Tests de los endpoints de la API (asistencia/views.py).

Usa las mismas fixtures que test_facial.py — ver el docstring de ese archivo
para su procedencia y licencia.
"""
import datetime
import secrets
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import AccessToken

from asistencia import pool
from asistencia.facial import get_embedding
from asistencia.models import Asistencia, Postulante

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MEDIA_TMP = tempfile.mkdtemp(prefix="asistencia-tests-media-")


def _foto(nombre: str, nombre_subido: str = "foto.jpg") -> SimpleUploadedFile:
    contenido = (FIXTURES_DIR / nombre).read_bytes()
    return SimpleUploadedFile(nombre_subido, contenido, content_type="image/jpeg")


def _autenticar_agente(client):
    """El registro y el sondeo de encuadre los opera un agente en el puesto de
    registro (ver RegistroPostulanteView)."""
    client.force_authenticate(User.objects.create_user(username="agente-registro", is_staff=True))


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class RegistroPostulanteViewTest(APITestCase):
    url = "/api/postulantes/"

    def setUp(self):
        _autenticar_agente(self.client)

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

    def test_cuenta_queda_inactiva_hasta_verificar_el_correo(self):
        self.client.post(self.url, self._datos(), format="multipart")
        postulante = Postulante.objects.get(cedula="1710034065")
        self.assertFalse(postulante.usuario.is_active)
        self.assertIsNotNone(postulante.codigo_verificacion)
        self.assertEqual(len(postulante.codigo_verificacion), 6)

    def test_manda_el_codigo_de_verificacion_por_correo(self):
        self.client.post(self.url, self._datos(), format="multipart")
        self.assertEqual(len(mail.outbox), 1)
        postulante = Postulante.objects.get(cedula="1710034065")
        self.assertEqual(mail.outbox[0].to, ["juan.perez@example.com"])
        self.assertIn(postulante.codigo_verificacion, mail.outbox[0].body)

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

    def test_cedula_duplicada_da_el_mismo_mensaje_en_ambos_caminos(self):
        self.client.post(self.url, self._datos(), format="multipart")
        response = self.client.post(
            self.url, self._datos(foto=_foto("rostro_real.jpg")), format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["cedula"][0], "Ya existe un postulante con esta cédula."
        )

    def test_correo_duplicado_es_rechazado(self):
        self.client.post(self.url, self._datos(), format="multipart")
        response = self.client.post(
            self.url,
            self._datos(cedula="0401843263", foto=_foto("rostro_real.jpg")),
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["correo"][0], "Ya existe un postulante con este correo."
        )

    def test_dos_registros_simultaneos_con_mismo_correo_da_400_no_500(self):
        # Mismo mecanismo que test_dos_registros_simultaneos_con_misma_cedula_da_400_no_500
        # (arriba), pero forzando la carrera contra el constraint de correo, no el
        # de cédula -- confirma que el except IntegrityError los distingue.
        self.client.post(self.url, self._datos(), format="multipart")
        # En la carrera real el chequeo de rostro duplicado también lee la BD antes
        # de cualquier commit (misma ventana que el UniqueValidator).
        with patch("rest_framework.validators.UniqueValidator.__call__", return_value=None), patch(
            "asistencia.views._rechazar_rostro_de_otro"
        ):
            response = self.client.post(
                self.url,
                self._datos(cedula="0401843263", foto=_foto("rostro_real.jpg")),
                format="multipart",
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("correo", response.data)
        self.assertEqual(
            Postulante.objects.filter(correo="juan.perez@example.com").count(), 1
        )

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

    def test_completar_precarga_rechaza_si_falta_la_foto(self):
        Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065",
            estatura_cm=175, sede="Quito",
        )
        datos = self._datos()
        del datos["foto"]
        response = self.client.post(self.url, datos, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("foto", response.data)
        self.assertEqual(Postulante.objects.get(cedula="1710034065").usuario, None)

    def test_completar_precarga_rechaza_si_falta_un_campo_nuevo_obligatorio(self):
        Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065",
            estatura_cm=175, sede="Quito",
        )
        datos = self._datos()
        del datos["correo"]
        response = self.client.post(self.url, datos, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("correo", response.data)

    def test_completar_precarga_con_cuenta_nueva_tambien_queda_inactiva(self):
        Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065",
            estatura_cm=175, sede="Quito",
        )
        self.client.post(self.url, self._datos(), format="multipart")
        postulante = Postulante.objects.get(cedula="1710034065")
        self.assertFalse(postulante.usuario.is_active)
        self.assertIsNotNone(postulante.codigo_verificacion)
        self.assertEqual(len(mail.outbox), 1)

    def test_dos_registros_simultaneos_con_misma_cedula_da_400_no_500(self):
        # Simula la ventana de carrera: el UniqueValidator del serializer solo
        # consulta la BD (sin lock), así que dos requests casi simultáneos con una
        # cédula nueva pueden pasar validación antes de que cualquiera haga commit.
        # Se desactiva el validador para forzar ese mismo estado y confirmar que el
        # segundo INSERT, que sí choca contra la restricción unique real, se
        # traduce a un 400 en vez de un 500 sin capturar.
        self.client.post(self.url, self._datos(), format="multipart")
        # En la carrera real el chequeo de rostro duplicado también lee la BD antes
        # de cualquier commit (misma ventana que el UniqueValidator).
        with patch("rest_framework.validators.UniqueValidator.__call__", return_value=None), patch(
            "asistencia.views._rechazar_rostro_de_otro"
        ):
            response = self.client.post(
                self.url, self._datos(foto=_foto("rostro_real.jpg")), format="multipart"
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cedula", response.data)
        self.assertEqual(Postulante.objects.filter(cedula="1710034065").count(), 1)


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class AgregarFotoPostulanteViewTest(APITestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username="1710034065", password="clave-segura-123")
        self.postulante = Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065",
            estatura_cm=175, sede="Quito",
            foto=_foto("rostro_real.jpg"),
            embedding=get_embedding(cv2_leer("rostro_real.jpg")),
            usuario=self.usuario,
        )
        self.url = f"/api/postulantes/{self.postulante.id}/fotos/"

    def test_requiere_autenticacion(self):
        response = self.client.post(self.url, {"foto": _foto("rostro_real.jpg")}, format="multipart")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.assertEqual(self.postulante.fotos_adicionales.count(), 0)

    def test_no_puede_agregar_foto_a_otro_postulante(self):
        # Antes de este fix, cualquiera podía sumar su propio rostro al pool de
        # matching de OTRO postulante y hacerse pasar por él en /api/verificar/.
        otro_usuario = User.objects.create_user(username="0100000001", password="clave-otra-123")
        self.client.force_authenticate(otro_usuario)
        response = self.client.post(self.url, {"foto": _foto("rostro_real.jpg")}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.postulante.fotos_adicionales.count(), 0)

    def test_el_propio_postulante_agrega_su_foto_adicional(self):
        self.client.force_authenticate(self.usuario)
        response = self.client.post(self.url, {"foto": _foto("rostro_real.jpg")}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(self.postulante.fotos_adicionales.count(), 1)
        self.assertEqual(len(self.postulante.fotos_adicionales.get().embedding), 128)

    def test_un_agente_agrega_foto_a_cualquier_postulante(self):
        agente = User.objects.create_user(username="agente1", password="clave-agente-123", is_staff=True)
        self.client.force_authenticate(agente)
        response = self.client.post(self.url, {"foto": _foto("rostro_real.jpg")}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_rechaza_foto_sin_rostro(self):
        self.client.force_authenticate(self.usuario)
        foto_sin_rostro = SimpleUploadedFile(
            "sin_rostro.jpg", _imagen_lisa_jpeg(), content_type="image/jpeg"
        )
        response = self.client.post(self.url, {"foto": foto_sin_rostro}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.postulante.fotos_adicionales.count(), 0)

    def test_404_si_el_postulante_no_existe(self):
        self.client.force_authenticate(self.usuario)
        response = self.client.post(
            "/api/postulantes/99999/fotos/", {"foto": _foto("rostro_real.jpg")}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class ProbarEncuadreViewTest(APITestCase):
    """Chequeo en vivo de la cámara (ver ProbarEncuadreView) — no guarda nada, no
    necesita @override_settings(MEDIA_ROOT=...) porque nunca escribe un archivo."""

    url = "/api/postulantes/probar-encuadre/"

    def setUp(self):
        _autenticar_agente(self.client)

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



def _imagen_lisa_jpeg() -> bytes:
    """Bytes de un JPEG válido pero sin ningún rostro (para probar el rechazo)."""
    import cv2
    import numpy as np

    imagen = np.full((300, 300, 3), 128, dtype=np.uint8)
    ok, buffer = cv2.imencode(".jpg", imagen)
    assert ok
    return buffer.tobytes()


class VerificarCorreoViewTest(APITestCase):
    url = "/api/postulantes/verificar-correo/"

    def setUp(self):
        self.usuario = User.objects.create_user(
            username="1710034065", password="clave-segura-123", is_active=False
        )
        self.postulante = Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065",
            estatura_cm=175, sede="Quito", correo="juan@example.com",
            usuario=self.usuario, codigo_verificacion="123456",
            codigo_generado_en=timezone.now(),
        )

    def test_codigo_correcto_activa_la_cuenta(self):
        response = self.client.post(self.url, {"cedula": "1710034065", "codigo": "123456"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.is_active)
        self.postulante.refresh_from_db()
        self.assertIsNone(self.postulante.codigo_verificacion)

    def test_codigo_incorrecto_no_activa_la_cuenta(self):
        response = self.client.post(self.url, {"cedula": "1710034065", "codigo": "000000"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.usuario.refresh_from_db()
        self.assertFalse(self.usuario.is_active)

    def test_codigo_vencido_no_activa_la_cuenta(self):
        self.postulante.codigo_generado_en = timezone.now() - datetime.timedelta(minutes=16)
        self.postulante.save()
        response = self.client.post(self.url, {"cedula": "1710034065", "codigo": "123456"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.usuario.refresh_from_db()
        self.assertFalse(self.usuario.is_active)

    def test_cedula_inexistente_es_error_de_validacion(self):
        response = self.client.post(self.url, {"cedula": "9999999999", "codigo": "123456"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class ReenviarCodigoViewTest(APITestCase):
    url = "/api/postulantes/reenviar-codigo/"

    def setUp(self):
        self.usuario = User.objects.create_user(
            username="1710034065", password="clave-segura-123", is_active=False
        )
        self.postulante = Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065",
            estatura_cm=175, sede="Quito", correo="juan@example.com",
            usuario=self.usuario, codigo_verificacion="123456",
            codigo_generado_en=timezone.now() - datetime.timedelta(minutes=20),
        )

    def test_genera_un_codigo_nuevo_que_invalida_el_anterior(self):
        response = self.client.post(self.url, {"cedula": "1710034065"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.postulante.refresh_from_db()
        self.assertNotEqual(self.postulante.codigo_verificacion, "123456")
        self.assertEqual(len(mail.outbox), 1)
        # El código viejo ya no sirve.
        response = self.client.post(
            "/api/postulantes/verificar-correo/", {"cedula": "1710034065", "codigo": "123456"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cedula_inexistente_es_error_de_validacion(self):
        response = self.client.post(self.url, {"cedula": "9999999999"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class SolicitarRecuperacionViewTest(APITestCase):
    url = "/api/postulantes/solicitar-recuperacion/"

    def setUp(self):
        self.usuario = User.objects.create_user(
            username="1710034065", password="clave-vieja-123", is_active=True
        )
        self.postulante = Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065",
            estatura_cm=175, sede="Quito", correo="juan@example.com",
            usuario=self.usuario,
        )

    def test_cuenta_activa_recibe_un_codigo_por_correo(self):
        response = self.client.post(self.url, {"cedula": "1710034065"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.postulante.refresh_from_db()
        self.assertIsNotNone(self.postulante.codigo_verificacion)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["juan@example.com"])

    def test_cuenta_inactiva_no_recibe_codigo_y_avisa_verificar_primero(self):
        self.usuario.is_active = False
        self.usuario.save()
        response = self.client.post(self.url, {"cedula": "1710034065"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("verificó su correo", response.data["cedula"])
        self.postulante.refresh_from_db()
        self.assertIsNone(self.postulante.codigo_verificacion)
        self.assertEqual(len(mail.outbox), 0)

    def test_cedula_inexistente_es_error_de_validacion(self):
        response = self.client.post(self.url, {"cedula": "9999999999"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(mail.outbox), 0)

    def test_cuenta_sin_correo_no_puede_recuperar(self):
        # Hallazgo de la revisión final: una cuenta activa sin correo (ej. si se
        # lo borraron editando /api/mi-postulante/, ver el fix de allow_null en
        # PostulanteSerializer) no debe "enviar" un código a ningún lado -- con
        # el backend de consola es silencioso, pero con SMTP real reventaría
        # después de haber prometido un código.
        self.postulante.correo = None
        self.postulante.save()
        response = self.client.post(self.url, {"cedula": "1710034065"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(mail.outbox), 0)
        self.postulante.refresh_from_db()
        self.assertIsNone(self.postulante.codigo_verificacion)

    def test_codigo_usa_secrets_no_random_no_criptografico(self):
        # Este código ahora protege un reset de contraseña, no solo la activación
        # de la cuenta -- debe generarse con un CSPRNG (secrets.randbelow), no con
        # random.randint (Mersenne Twister, reconstruible tras suficientes muestras).
        with patch(
            "asistencia.views.secrets.randbelow", wraps=secrets.randbelow
        ) as randbelow_mock:
            response = self.client.post(self.url, {"cedula": "1710034065"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        randbelow_mock.assert_called_once_with(1_000_000)

    def test_postulante_precargado_sin_cuenta_es_error_de_validacion(self):
        Postulante.objects.create(
            nombres="Ana", apellidos="Lopez", cedula="0401843263", estatura_cm=160,
        )
        response = self.client.post(self.url, {"cedula": "0401843263"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(mail.outbox), 0)


class RestablecerPasswordViewTest(APITestCase):
    url = "/api/postulantes/restablecer-password/"

    def setUp(self):
        # Sin esto, el contador de throttle (127.0.0.1, scope restablecer-password
        # 5/min) se arrastra entre tests de la misma corrida -- con 6 tests en esta
        # clase, el sexto POST ya cae en 429 en vez del status esperado.
        cache.clear()
        self.usuario = User.objects.create_user(
            username="1710034065", password="clave-vieja-123", is_active=True
        )
        self.postulante = Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065",
            estatura_cm=175, sede="Quito", correo="juan@example.com",
            usuario=self.usuario, codigo_verificacion="123456",
            codigo_generado_en=timezone.now(),
        )

    def test_cuenta_inactiva_no_puede_restablecer(self):
        # Hallazgo de la revisión final: una cuenta inactiva con un código de
        # VERIFICACIÓN de registro pendiente (no de recuperación) no debe poder
        # "restablecer" -- eso consumiría el código de activación sin activar la
        # cuenta, dejando a la persona sin poder ni verificar ni loguear.
        self.usuario.is_active = False
        self.usuario.save()
        response = self.client.post(
            self.url,
            {"cedula": "1710034065", "codigo": "123456", "password_nueva": "clave-nueva-456"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.postulante.refresh_from_db()
        self.assertEqual(self.postulante.codigo_verificacion, "123456")

    def test_codigo_correcto_restablece_la_contrasena(self):
        response = self.client.post(
            self.url,
            {"cedula": "1710034065", "codigo": "123456", "password_nueva": "clave-nueva-456"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.postulante.refresh_from_db()
        self.assertIsNone(self.postulante.codigo_verificacion)

        login = self.client.post(
            "/api/token/", {"username": "1710034065", "password": "clave-nueva-456"}
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK, login.data)

    def test_codigo_incorrecto_no_cambia_la_contrasena(self):
        response = self.client.post(
            self.url,
            {"cedula": "1710034065", "codigo": "000000", "password_nueva": "clave-nueva-456"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        login = self.client.post(
            "/api/token/", {"username": "1710034065", "password": "clave-vieja-123"}
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)

    def test_codigo_vencido_no_cambia_la_contrasena(self):
        self.postulante.codigo_generado_en = timezone.now() - datetime.timedelta(minutes=16)
        self.postulante.save()
        response = self.client.post(
            self.url,
            {"cedula": "1710034065", "codigo": "123456", "password_nueva": "clave-nueva-456"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_nueva_corta_es_rechazada_sin_consumir_el_codigo(self):
        response = self.client.post(
            self.url,
            {"cedula": "1710034065", "codigo": "123456", "password_nueva": "corta"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.postulante.refresh_from_db()
        self.assertEqual(self.postulante.codigo_verificacion, "123456")

    def test_cedula_inexistente_es_error_de_validacion(self):
        response = self.client.post(
            self.url,
            {"cedula": "9999999999", "codigo": "123456", "password_nueva": "clave-nueva-456"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class VerificarAsistenciaViewTest(APITestCase):
    url = "/api/verificar/"

    def setUp(self):
        # El pool de embeddings (ver pool.py) vive en memoria del proceso, no en
        # la transacción del test: sin esto arrastra ids de postulantes creados
        # en un test anterior que el rollback ya borró.
        pool.invalidar()
        # El kiosco de verificación exige agente logueado (ver VerificarAsistenciaView).
        self.client.force_authenticate(User.objects.create_user(username="kiosco", is_staff=True))
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

    def test_no_expone_pii_del_postulante_en_la_respuesta_publica(self):
        # /api/verificar/ antes no exigía login — cualquiera con acceso de red
        # podía mandar fotos al voleo buscando coincidencia 1:N y recibir foto/teléfono/correo/fecha de
        # nacimiento/género/estatura de un postulante real. El kiosco solo
        # muestra nombre y apellido en pantalla (ver verificar.html), no hace
        # falta exponer el resto acá.
        self.postulante.telefono = "0991234567"
        self.postulante.correo = "juan@example.com"
        self.postulante.save()

        response = self.client.post(
            self.url, {"sede": "Quito", "foto": _foto("rostro_real.jpg")}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        datos_postulante = response.data["postulante"]
        self.assertEqual(set(datos_postulante.keys()), {"id", "nombres", "apellidos", "cedula", "foto"})

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

    def _crear_asistencia(self, cedula, nombres, apellidos, sede, metodo, verificado_en=None):
        postulante = Postulante.objects.create(
            nombres=nombres, apellidos=apellidos, cedula=cedula,
            estatura_cm=170, sede=sede, foto=_foto("rostro_real.jpg", f"{cedula}.jpg"),
        )
        asistencia = Asistencia.objects.create(postulante=postulante, sede=sede, metodo=metodo)
        if verificado_en is not None:
            Asistencia.objects.filter(pk=asistencia.pk).update(verificado_en=verificado_en)
            asistencia.refresh_from_db()
        return asistencia

    def test_filtra_por_nombre_o_cedula(self):
        self._crear_asistencia(
            "1111111111", "Ana", "Lopez", "Quito", Asistencia.Metodo.AUTOMATICO
        )
        self._crear_asistencia(
            "2222222222", "Luis", "Diaz", "Quito", Asistencia.Metodo.AUTOMATICO
        )
        self.client.force_authenticate(self.agente)

        response = self.client.get(self.url, {"q": "Lopez"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        nombres = [fila["postulante_nombres"] for fila in response.data["results"]]
        self.assertEqual(nombres, ["Ana"])

        response = self.client.get(self.url, {"q": "2222222222"})
        cedulas = [fila["postulante_cedula"] for fila in response.data["results"]]
        self.assertEqual(cedulas, ["2222222222"])

    def test_filtra_por_rango_de_fecha(self):
        antigua = self._crear_asistencia(
            "1111111111", "Ana", "Lopez", "Quito", Asistencia.Metodo.AUTOMATICO,
            verificado_en=timezone.now() - datetime.timedelta(days=5),
        )
        reciente = self._crear_asistencia(
            "2222222222", "Luis", "Diaz", "Quito", Asistencia.Metodo.AUTOMATICO,
        )
        self.client.force_authenticate(self.agente)

        desde = (timezone.now() - datetime.timedelta(days=1)).isoformat()
        response = self.client.get(self.url, {"desde": desde})
        ids = [fila["id"] for fila in response.data["results"]]
        self.assertEqual(ids, [reciente.id])

        hasta = (timezone.now() - datetime.timedelta(days=1)).isoformat()
        response = self.client.get(self.url, {"hasta": hasta})
        ids = [fila["id"] for fila in response.data["results"]]
        self.assertEqual(ids, [antigua.id])

    def test_filtra_por_rango_de_fecha_solo_dia(self):
        # Un date picker típico manda solo "2026-09-24" (sin hora) — debe
        # interpretarse como el día completo, no fallar silenciosamente.
        hoy = self._crear_asistencia(
            "1111111111", "Ana", "Lopez", "Quito", Asistencia.Metodo.AUTOMATICO
        )
        self.client.force_authenticate(self.agente)

        # fecha LOCAL (America/Guayaquil), no la fecha UTC de timezone.now().date() —
        # son distintas cerca de la medianoche, y es la fecha local la que un date
        # picker manda.
        hoy_str = timezone.localtime(timezone.now()).date().isoformat()
        response = self.client.get(self.url, {"desde": hoy_str, "hasta": hoy_str})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [fila["id"] for fila in response.data["results"]]
        self.assertEqual(ids, [hoy.id])

    def test_filtra_por_metodo(self):
        self._crear_asistencia(
            "1111111111", "Ana", "Lopez", "Quito", Asistencia.Metodo.AUTOMATICO
        )
        self._crear_asistencia(
            "2222222222", "Luis", "Diaz", "Quito", Asistencia.Metodo.MANUAL
        )
        self.client.force_authenticate(self.agente)

        response = self.client.get(self.url, {"metodo": "MANUAL"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        metodos = [fila["metodo"] for fila in response.data["results"]]
        self.assertEqual(metodos, ["MANUAL"])

    def test_metodo_invalido_no_rompe_ni_filtra(self):
        self._crear_asistencia(
            "1111111111", "Ana", "Lopez", "Quito", Asistencia.Metodo.AUTOMATICO
        )
        self.client.force_authenticate(self.agente)

        response = self.client.get(self.url, {"metodo": "LO-QUE-SEA"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_fecha_invalida_no_rompe_ni_filtra(self):
        self._crear_asistencia(
            "1111111111", "Ana", "Lopez", "Quito", Asistencia.Metodo.AUTOMATICO
        )
        self.client.force_authenticate(self.agente)

        response = self.client.get(self.url, {"desde": "no-es-una-fecha"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_fecha_bien_formada_pero_fuera_de_rango_no_rompe_ni_filtra(self):
        # "2026-02-30" matchea el regex de fecha de Django (\d{4}-\d{1,2}-\d{1,2})
        # pero no es un día real: parse_date() prueba primero fromisoformat (lanza
        # ValueError, la captura) y cae a un segundo intento por regex que llama
        # datetime.date(2026, 2, 30) directo — ESE ValueError no lo capturaba nadie
        # y salía como 500, contradiciendo el propio comentario de la función ("un
        # valor mal formado se ignora en vez de romper la request").
        self._crear_asistencia(
            "1111111111", "Ana", "Lopez", "Quito", Asistencia.Metodo.AUTOMATICO
        )
        self.client.force_authenticate(self.agente)

        response = self.client.get(self.url, {"desde": "2026-02-30"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_datetime_bien_formado_pero_fuera_de_rango_no_rompe_ni_filtra(self):
        # Mismo problema que arriba pero por el lado de parse_datetime() (hora 25
        # no existe) — cubre la otra rama de _parsear_fecha.
        self._crear_asistencia(
            "1111111111", "Ana", "Lopez", "Quito", Asistencia.Metodo.AUTOMATICO
        )
        self.client.force_authenticate(self.agente)

        response = self.client.get(self.url, {"desde": "2026-01-01T25:00:00"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_combina_varios_filtros(self):
        self._crear_asistencia(
            "1111111111", "Ana", "Lopez", "Quito", Asistencia.Metodo.AUTOMATICO
        )
        self._crear_asistencia(
            "2222222222", "Ana", "Diaz", "Quito", Asistencia.Metodo.MANUAL
        )
        self.client.force_authenticate(self.agente)

        response = self.client.get(self.url, {"q": "Ana", "metodo": "MANUAL"})
        cedulas = [fila["postulante_cedula"] for fila in response.data["results"]]
        self.assertEqual(cedulas, ["2222222222"])


class ResumenAsistenciasViewTest(APITestCase):
    url = "/api/asistencias/resumen/"

    def setUp(self):
        self.agente = User.objects.create_user(
            username="agente1", password="clave-segura-123", is_staff=True
        )

    def _crear_asistencia(self, cedula, sede, metodo, verificado_en=None):
        postulante = Postulante.objects.create(
            nombres="Test", apellidos="Test", cedula=cedula,
            estatura_cm=170, sede=sede, foto=_foto("rostro_real.jpg", f"{cedula}.jpg"),
        )
        asistencia = Asistencia.objects.create(postulante=postulante, sede=sede, metodo=metodo)
        if verificado_en is not None:
            Asistencia.objects.filter(pk=asistencia.pk).update(verificado_en=verificado_en)
        return asistencia

    def test_requiere_autenticacion(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_postulante_no_puede_ver_el_resumen(self):
        usuario = User.objects.create_user(username="9999999999", password="clave-segura-123")
        self.client.force_authenticate(usuario)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_agrega_por_sede_y_metodo(self):
        self._crear_asistencia("1111111111", "Quito", Asistencia.Metodo.AUTOMATICO)
        self._crear_asistencia("2222222222", "Quito", Asistencia.Metodo.MANUAL)
        self._crear_asistencia("3333333333", "Guayaquil", Asistencia.Metodo.AUTOMATICO)
        self.client.force_authenticate(self.agente)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        por_sede = {fila["sede"]: fila["total"] for fila in response.data["por_sede"]}
        self.assertEqual(por_sede, {"Quito": 2, "Guayaquil": 1})

        por_metodo = {fila["metodo"]: fila["total"] for fila in response.data["por_metodo"]}
        self.assertEqual(por_metodo, {"AUTO": 2, "MANUAL": 1})

    def test_agrupa_por_hora(self):
        base = timezone.now().replace(minute=0, second=0, microsecond=0)
        self._crear_asistencia("1111111111", "Quito", Asistencia.Metodo.AUTOMATICO, verificado_en=base)
        self._crear_asistencia(
            "2222222222", "Quito", Asistencia.Metodo.AUTOMATICO,
            verificado_en=base + datetime.timedelta(minutes=10),
        )
        self._crear_asistencia(
            "3333333333", "Quito", Asistencia.Metodo.AUTOMATICO,
            verificado_en=base + datetime.timedelta(hours=1),
        )
        self.client.force_authenticate(self.agente)

        response = self.client.get(self.url)
        totales = sorted(fila["total"] for fila in response.data["por_hora"])
        self.assertEqual(totales, [1, 2])

    def test_respeta_filtros(self):
        self._crear_asistencia("1111111111", "Quito", Asistencia.Metodo.AUTOMATICO)
        self._crear_asistencia("2222222222", "Quito", Asistencia.Metodo.MANUAL)
        self.client.force_authenticate(self.agente)

        response = self.client.get(self.url, {"metodo": "MANUAL"})
        por_metodo = {fila["metodo"]: fila["total"] for fila in response.data["por_metodo"]}
        self.assertEqual(por_metodo, {"MANUAL": 1})

    def test_fecha_fuera_de_rango_no_rompe_el_resumen(self):
        # Ver el mismo caso en ListaAsistenciasViewTest — _filtrar_asistencias es
        # compartida por los 3 endpoints de asistencias.
        self._crear_asistencia("1111111111", "Quito", Asistencia.Metodo.AUTOMATICO)
        self.client.force_authenticate(self.agente)
        response = self.client.get(self.url, {"desde": "2026-02-30"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_vacio_no_rompe(self):
        self.client.force_authenticate(self.agente)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data, {"por_sede": [], "por_hora": [], "por_metodo": []}
        )


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class ExportarAsistenciasViewTest(APITestCase):
    url = "/api/asistencias/exportar/"

    def setUp(self):
        self.agente = User.objects.create_user(
            username="agente1", password="clave-segura-123", is_staff=True
        )
        self.postulante = Postulante.objects.create(
            nombres="Ana", apellidos="Lopez", cedula="1111111111",
            estatura_cm=170, sede="Quito", foto=_foto("rostro_real.jpg", "a.jpg"),
        )
        self.asistencia = Asistencia.objects.create(postulante=self.postulante, sede="Quito")

    def test_requiere_autenticacion(self):
        response = self.client.get(self.url, {"formato": "csv"})
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_formato_faltante_es_400(self):
        self.client.force_authenticate(self.agente)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_formato_invalido_es_400(self):
        self.client.force_authenticate(self.agente)
        response = self.client.get(self.url, {"formato": "xml"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_fecha_fuera_de_rango_no_rompe_la_exportacion(self):
        # Ver el mismo caso en ListaAsistenciasViewTest — _filtrar_asistencias es
        # compartida por los 3 endpoints de asistencias.
        self.client.force_authenticate(self.agente)
        response = self.client.get(self.url, {"formato": "csv", "desde": "2026-02-30"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_exporta_csv(self):
        self.client.force_authenticate(self.agente)
        response = self.client.get(self.url, {"formato": "csv"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment", response["Content-Disposition"])

        contenido = response.content.decode("utf-8-sig")
        self.assertIn("1111111111", contenido)
        self.assertIn("Ana", contenido)
        lineas = [linea for linea in contenido.strip().split("\r\n") if linea]
        self.assertEqual(len(lineas), 2)  # encabezado + 1 fila

    def test_csv_usa_utf8_con_bom_para_que_excel_no_rompa_tildes(self):
        # Content-Type sin charset + sin BOM: Excel en Windows asume la
        # codificación del sistema (ej. Windows-1252) en vez de UTF-8, y
        # "José Muñoz" se ve como mojibake ("JosÃ© MuÃ±oz") al abrir el CSV. El
        # BOM (﻿) es el truco estándar que Excel usa para detectar UTF-8.
        postulante = Postulante.objects.create(
            nombres="José", apellidos="Muñoz", cedula="4444444444",
            estatura_cm=170, sede="Quito", foto=_foto("rostro_real.jpg", "d.jpg"),
        )
        Asistencia.objects.create(postulante=postulante, sede="Quito")
        self.client.force_authenticate(self.agente)

        response = self.client.get(self.url, {"formato": "csv", "q": "4444444444"})
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))
        contenido = response.content.decode("utf-8-sig")
        self.assertIn("José", contenido)
        self.assertIn("Muñoz", contenido)

    def test_exporta_pdf(self):
        self.client.force_authenticate(self.agente)
        response = self.client.get(self.url, {"formato": "pdf"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

    def _segunda_asistencia(self):
        otro = Postulante.objects.create(
            nombres="Luis", apellidos="Diaz", cedula="1719141770",
            estatura_cm=180, sede="Quito", foto=_foto("rostro_real.jpg", "z.jpg"),
        )
        return Asistencia.objects.create(postulante=otro, sede="Quito")

    @patch("asistencia.views.MAX_FILAS_PDF", 1)
    def test_pdf_rechaza_una_exportacion_demasiado_grande(self):
        # Medido el 2026-09-28 con 20.004 asistencias: el PDF tardaba 500 s y
        # usaba 1,8 GB de RAM — en producción el proxy corta a los 30-60 s y el
        # worker queda quemando memoria. Mejor un 400 que explique qué hacer.
        self._segunda_asistencia()
        self.client.force_authenticate(self.agente)

        response = self.client.get(self.url, {"formato": "pdf"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mensaje = str(response.data)
        self.assertIn("CSV", mensaje)  # le dice al agente por dónde salir
        self.assertIn("2", mensaje)  # cuántas filas tiene el filtro actual

    @patch("asistencia.views.MAX_FILAS_PDF", 1)
    def test_el_limite_del_pdf_no_afecta_al_csv(self):
        # El CSV es justamente la salida para el volumen completo (1,6 s y
        # 1,8 MB con 20.004 filas) — el límite es solo del PDF.
        self._segunda_asistencia()
        self.client.force_authenticate(self.agente)

        response = self.client.get(self.url, {"formato": "csv"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        lineas = [l for l in response.content.decode("utf-8-sig").strip().split("\r\n") if l]
        self.assertEqual(len(lineas), 3)  # encabezado + 2 filas

    @patch("asistencia.views.MAX_FILAS_PDF", 1)
    def test_pdf_dentro_del_limite_se_exporta_igual(self):
        self.client.force_authenticate(self.agente)
        response = self.client.get(self.url, {"formato": "pdf"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_exporta_respetando_filtros(self):
        otro = Postulante.objects.create(
            nombres="Luis", apellidos="Diaz", cedula="2222222222",
            estatura_cm=180, sede="Guayaquil", foto=_foto("rostro_real.jpg", "b.jpg"),
        )
        Asistencia.objects.create(postulante=otro, sede="Guayaquil", metodo=Asistencia.Metodo.MANUAL)
        self.client.force_authenticate(self.agente)

        response = self.client.get(self.url, {"formato": "csv", "metodo": "MANUAL"})
        contenido = response.content.decode("utf-8")
        self.assertIn("2222222222", contenido)
        self.assertNotIn("1111111111", contenido)

    def test_csv_neutraliza_inyeccion_de_formulas(self):
        # nombres/apellidos vienen del autoregistro del postulante (texto libre) —
        # si alguien registra un nombre que empieza con =/+/-/@, Excel/Sheets lo
        # puede interpretar como fórmula al abrir el CSV exportado (CWE-1236).
        # Mitigación estándar: anteponer una comilla simple a esos valores.
        maligno = Postulante.objects.create(
            nombres="=cmd|'/c calc'!A1",
            apellidos="Lopez",
            cedula="3333333333",
            estatura_cm=170,
            sede="Quito",
            foto=_foto("rostro_real.jpg", "c.jpg"),
        )
        Asistencia.objects.create(postulante=maligno, sede="Quito")
        self.client.force_authenticate(self.agente)

        response = self.client.get(self.url, {"formato": "csv", "q": "3333333333"})
        contenido = response.content.decode("utf-8")
        self.assertNotIn("\n=cmd", contenido)
        self.assertNotIn(",=cmd", contenido)
        self.assertIn("'=cmd|'/c calc'!A1", contenido)


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

    def setUp(self):
        _autenticar_agente(self.client)

    def test_no_se_puede_loguear_antes_de_verificar_el_correo(self):
        datos = {
            "nombres": "Juan", "apellidos": "Pérez", "cedula": "1710034065",
            "estatura_cm": 175, "fecha_nacimiento": "1995-05-20",
            "telefono": "0991234567", "correo": "juan@example.com", "genero": "M",
            "sede": "Quito", "foto": _foto("rostro_real.jpg"), "password": "clave-segura-123",
        }
        self.client.post("/api/postulantes/", datos, format="multipart")
        self.client.force_authenticate(None)

        response = self.client.post(
            "/api/token/", {"username": "1710034065", "password": "clave-segura-123"}
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_se_loguea_con_la_cuenta_creada_al_registrarse_una_vez_verificado_el_correo(self):
        datos = {
            "nombres": "Juan", "apellidos": "Pérez", "cedula": "1710034065",
            "estatura_cm": 175, "fecha_nacimiento": "1995-05-20",
            "telefono": "0991234567", "correo": "juan@example.com", "genero": "M",
            "sede": "Quito", "foto": _foto("rostro_real.jpg"), "password": "clave-segura-123",
        }
        self.client.post("/api/postulantes/", datos, format="multipart")
        self.client.force_authenticate(None)
        codigo = Postulante.objects.get(cedula="1710034065").codigo_verificacion
        self.client.post(
            "/api/postulantes/verificar-correo/", {"cedula": "1710034065", "codigo": codigo}
        )

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
        _autenticar_agente(self.client)
        self.client.post("/api/postulantes/", datos, format="multipart")
        self.client.force_authenticate(None)
        codigo = Postulante.objects.get(cedula="1710034065").codigo_verificacion
        self.client.post(
            "/api/postulantes/verificar-correo/", {"cedula": "1710034065", "codigo": codigo}
        )

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


class ThrottlingTest(APITestCase):
    """Antes no había ningún límite a los intentos de login ni al fisgoneo del
    1:N de /api/verificar/ (ver revisión de seguridad: ese endpoint es público y
    devuelve datos del postulante si hay coincidencia) — cubre que el throttle
    scope quede realmente wireado en ambas vistas, no solo declarado en settings.

    THROTTLE_RATES se parchea a un límite chico por test (en vez de usar el real,
    120/10/30 por minuto) para no depender de esperar un minuto real ni de que
    ningún otro test haya "gastado" cupo contra la misma IP/caché de proceso."""

    def setUp(self):
        cache.clear()

    def test_login_se_bloquea_tras_superar_el_limite_de_intentos(self):
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"login": "2/min"}):
            for _ in range(2):
                self.client.post("/api/token/", {"username": "x", "password": "y"})
            respuesta = self.client.post("/api/token/", {"username": "x", "password": "y"})
        self.assertEqual(respuesta.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_verificar_se_bloquea_tras_superar_el_limite_de_intentos(self):
        self.client.force_authenticate(User.objects.create_user(username="kiosco", is_staff=True))
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"verificar": "1/min"}):
            self.client.post("/api/verificar/", {})
            respuesta = self.client.post("/api/verificar/", {})
        self.assertEqual(respuesta.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_el_sondeo_de_encuadre_tiene_su_propio_cupo(self):
        # Polea cada ~900ms por puesto de registro: si cayera en el piso global
        # `anon` (120/min), dos puestos detrás de la misma IP lo agotan y la
        # auto-captura se apaga sin avisar (camera-capture.ts ignora el error).
        _autenticar_agente(self.client)
        with patch.dict(
            ScopedRateThrottle.THROTTLE_RATES, {"encuadre": "1/min", "user": "1000/min"}
        ):
            self.client.post("/api/postulantes/probar-encuadre/", {})
            respuesta = self.client.post("/api/postulantes/probar-encuadre/", {})
        self.assertEqual(respuesta.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
