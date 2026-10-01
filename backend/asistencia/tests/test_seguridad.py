"""Auditoría de seguridad pre-producción (2026-09-30): un test por hallazgo."""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIRequestFactory, APITestCase
from rest_framework.request import Request

from asistencia.models import Postulante
from asistencia.tests.test_views import FIXTURES_DIR, MEDIA_TMP, _foto
from asistencia.views import RestablecerPasswordView, _leer_imagen


class ThrottleNoSeEvadeConXForwardedForTest(APITestCase):
    def test_cabecera_falsa_no_resetea_el_cupo(self):
        cache.clear()
        vista = RestablecerPasswordView()
        throttle = vista.get_throttles()[0]
        factory = APIRequestFactory()
        permitidos = [
            throttle.allow_request(
                Request(factory.post("/", HTTP_X_FORWARDED_FOR=f"1.2.3.{i}")), vista
            )
            for i in range(8)
        ]
        cache.clear()
        self.assertEqual(permitidos.count(True), 5)  # límite real: 5/min


class CodigoSeInvalidaTrasIntentosFallidosTest(APITestCase):
    url = "/api/postulantes/restablecer-password/"

    def setUp(self):
        cache.clear()
        usuario = User.objects.create_user(username="1710034065", password="clave-vieja-123")
        self.postulante = Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065", estatura_cm=175,
            correo="juan@example.com", usuario=usuario,
            codigo_verificacion="123456", codigo_generado_en=timezone.now(),
        )

    def test_quinto_codigo_incorrecto_invalida_el_codigo(self):
        for _ in range(5):
            cache.clear()  # aislar del throttle por IP: esto prueba el límite por código
            self.client.post(
                self.url,
                {"cedula": "1710034065", "codigo": "000000", "password_nueva": "Clave-nueva-456"},
            )
        cache.clear()
        response = self.client.post(
            self.url,
            {"cedula": "1710034065", "codigo": "123456", "password_nueva": "Clave-nueva-456"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.postulante.refresh_from_db()
        self.assertIsNone(self.postulante.codigo_verificacion)

    def test_password_comun_es_rechazada(self):
        response = self.client.post(
            self.url, {"cedula": "1710034065", "codigo": "123456", "password_nueva": "12345678"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password_nueva", response.data)


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class RegistroNoPisaDatosOficialesTest(APITestCase):
    url = "/api/postulantes/"

    def setUp(self):
        self.client.force_authenticate(User.objects.create_user(username="agente", is_staff=True))

    def _datos(self, **extra):
        return {
            "nombres": "Impostor", "apellidos": "X", "cedula": "1710034065",
            "estatura_cm": 199, "sede": "Otra", "fecha_nacimiento": "1995-05-20",
            "telefono": "0991234567", "correo": "impostor@example.com", "genero": "M",
            "foto": _foto("rostro_real.jpg"), "password": "Clave-segura-123", **extra,
        }

    def test_completar_precarga_conserva_nombres_estatura_y_sede_del_csv(self):
        Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065", estatura_cm=165, sede="Quito"
        )
        response = self.client.post(self.url, self._datos(), format="multipart")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        p = Postulante.objects.get(cedula="1710034065")
        self.assertEqual((p.nombres, p.apellidos, p.estatura_cm, p.sede), ("Juan", "Pérez", 165, "Quito"))

    def test_anonimo_no_reemplaza_la_foto_de_una_cuenta_ya_creada(self):
        usuario = User.objects.create_user(username="1710034065", password="x")
        Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065", estatura_cm=165,
            correo="juan@example.com", usuario=usuario,
        )  # sin foto: un agente se la limpió
        response = self.client.post(self.url, self._datos(), format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Postulante.objects.get().correo, "juan@example.com")

    def test_registro_nuevo_ignora_la_sede_enviada(self):
        response = self.client.post(self.url, self._datos(), format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertIsNone(Postulante.objects.get().sede)

    def test_password_comun_es_rechazada(self):
        response = self.client.post(self.url, self._datos(password="12345678"), format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)


class MiPostulanteNoEditaDatosOficialesTest(APITestCase):
    def test_no_cambia_nombres_estatura_sede_ni_correo(self):
        usuario = User.objects.create_user(username="1710034065", password="x")
        Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065", estatura_cm=165,
            sede="Quito", correo="juan@example.com", usuario=usuario,
        )
        self.client.force_authenticate(usuario)
        self.client.patch(
            "/api/mi-postulante/",
            {"nombres": "Otro", "apellidos": "Y", "estatura_cm": 190, "sede": "Guayaquil",
             "correo": "otro@example.com"},
        )
        p = Postulante.objects.get()
        self.assertEqual(
            (p.nombres, p.apellidos, p.estatura_cm, p.sede, p.correo),
            ("Juan", "Pérez", 165, "Quito", "juan@example.com"),
        )


class VerificarExigeAgenteTest(APITestCase):
    def test_anonimo_no_puede_marcar_asistencia(self):
        response = self.client.post("/api/verificar/", {"sede": "Quito"})
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_postulante_logueado_no_puede_marcar_asistencia(self):
        self.client.force_authenticate(User.objects.create_user(username="1710034065"))
        response = self.client.post("/api/verificar/", {"sede": "Quito"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class ImagenGiganteSeRechazaTest(APITestCase):
    def test_archivo_de_mas_de_5mb_no_se_decodifica(self):
        # JPEG real + relleno al final (los decodificadores lo ignoran): válida pero >5 MB.
        real = (FIXTURES_DIR / "rostro_real.jpg").read_bytes()
        enorme = SimpleUploadedFile("x.jpg", real + b"\0" * (5 * 1024 * 1024))
        self.assertIsNone(_leer_imagen(enorme))



@override_settings(MEDIA_ROOT=MEDIA_TMP, DEBUG=False)
class FotosSoloConUrlFirmadaTest(APITestCase):
    def setUp(self):
        usuario = User.objects.create_user(username="1710034065", password="x")
        self.postulante = Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065", estatura_cm=165,
            foto=_foto("rostro_real.jpg"), usuario=usuario,
        )
        self.client.force_authenticate(usuario)

    def test_la_api_devuelve_una_url_firmada_que_sirve_la_foto(self):
        url = self.client.get("/api/mi-postulante/").data["foto"]
        self.assertNotIn("/media/", url)
        self.client.force_authenticate(None)  # un <img> no manda el token
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(b"".join(response.streaming_content)[:2], b"\xff\xd8")  # JPEG

    def test_firma_alterada_da_404(self):
        url = self.client.get("/api/mi-postulante/").data["foto"]
        self.assertEqual(self.client.get(url[:-4] + "xxx/").status_code, status.HTTP_404_NOT_FOUND)

    def test_ruta_media_directa_no_existe(self):
        self.assertEqual(
            self.client.get("/media/" + self.postulante.foto.name).status_code,
            status.HTTP_404_NOT_FOUND,
        )


# --- Auditoría completa (run-1, 2026-10-01): hallazgos prioritarios 1-6 ---
from unittest.mock import patch  # noqa: E402

from asistencia import pool  # noqa: E402

E1 = [1.0] + [0.0] * 127
E2 = [0.0, 1.0] + [0.0] * 126


def _staff():
    return User.objects.create_user(username="agente", is_staff=True)


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class MiPostulanteNoReemplazaFotoTest(APITestCase):
    def test_patch_de_foto_no_cambia_la_foto(self):
        usuario = User.objects.create_user(username="1710034065", password="x")
        p = Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065", estatura_cm=165,
            foto=_foto("rostro_real.jpg"), usuario=usuario,
        )
        antes = p.foto.name
        self.client.force_authenticate(usuario)
        self.client.patch("/api/mi-postulante/", {"foto": _foto("rostro_spoof.jpg")}, format="multipart")
        p.refresh_from_db()
        self.assertEqual(p.foto.name, antes)


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class RegistroSupervisadoTest(APITestCase):
    def test_anonimo_no_puede_registrar(self):
        response = self.client.post("/api/postulantes/", {"cedula": "1710034065"}, format="multipart")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_anonimo_no_puede_usar_el_sondeo_de_encuadre(self):
        response = self.client.post("/api/postulantes/probar-encuadre/", {}, format="multipart")
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class RostroDuplicadoTest(APITestCase):
    def setUp(self):
        pool.invalidar()
        self.client.force_authenticate(_staff())
        Postulante.objects.create(
            nombres="Victima", apellidos="V", cedula="1710034073", estatura_cm=170, embedding=E1,
        )

    def _datos(self):
        return {
            "nombres": "Señuelo", "apellidos": "D", "cedula": "1710034065", "estatura_cm": 170,
            "fecha_nacimiento": "1995-05-20", "telefono": "0991234567",
            "correo": "d@example.com", "genero": "M", "foto": _foto("rostro_real.jpg"),
            "password": "Clave-segura-123",
        }

    def test_registro_rechaza_un_rostro_de_otra_cedula(self):
        with patch("asistencia.views.calcular_embedding", return_value=E1):
            response = self.client.post("/api/postulantes/", self._datos(), format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn("foto", response.data)
        self.assertFalse(Postulante.objects.filter(cedula="1710034065").exists())

    def test_registro_acepta_un_rostro_nuevo(self):
        with patch("asistencia.views.calcular_embedding", return_value=E2):
            response = self.client.post("/api/postulantes/", self._datos(), format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class FotoAdicionalDelPropioRostroTest(APITestCase):
    def setUp(self):
        pool.invalidar()
        self.usuario = User.objects.create_user(username="1710034065", password="x")
        self.p = Postulante.objects.create(
            nombres="A", apellidos="A", cedula="1710034065", estatura_cm=170,
            embedding=E1, usuario=self.usuario,
        )
        self.client.force_authenticate(self.usuario)
        self.url = f"/api/postulantes/{self.p.id}/fotos/"

    def test_rechaza_un_rostro_que_no_es_el_del_dueno(self):
        with patch("asistencia.views.calcular_embedding", return_value=E2):
            response = self.client.post(self.url, {"foto": _foto("rostro_real.jpg")}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.p.fotos_adicionales.count(), 0)

    def test_acepta_otro_angulo_del_mismo_rostro(self):
        with patch("asistencia.views.calcular_embedding", return_value=E1):
            response = self.client.post(self.url, {"foto": _foto("rostro_real.jpg")}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)


class AdminNoEditaFotosTest(APITestCase):
    def test_foto_es_de_solo_lectura_en_el_admin(self):
        from django.contrib import admin as dj_admin
        from asistencia.admin import FotoPostulanteInline
        ma = dj_admin.site._registry[Postulante]
        self.assertIn("foto", ma.readonly_fields)
        self.assertIn("foto", FotoPostulanteInline.readonly_fields)
        self.assertFalse(FotoPostulanteInline(Postulante, dj_admin.site).has_add_permission(None, None))


class CuentaDeshabilitadaNoSeReactivaTest(APITestCase):
    def test_reenviar_codigo_rechaza_una_cuenta_ya_verificada_y_deshabilitada(self):
        cache.clear()
        usuario = User.objects.create_user(username="1710034065", password="x", is_active=False)
        Postulante.objects.create(
            nombres="J", apellidos="P", cedula="1710034065", estatura_cm=170,
            correo="j@example.com", usuario=usuario, correo_verificado=True,
        )
        response = self.client.post("/api/postulantes/reenviar-codigo/", {"cedula": "1710034065"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verificar_correo_marca_correo_verificado(self):
        cache.clear()
        usuario = User.objects.create_user(username="1710034065", password="x", is_active=False)
        p = Postulante.objects.create(
            nombres="J", apellidos="P", cedula="1710034065", estatura_cm=170, correo="j@example.com",
            usuario=usuario, codigo_verificacion="123456", codigo_generado_en=timezone.now(),
        )
        self.client.post("/api/postulantes/verificar-correo/", {"cedula": "1710034065", "codigo": "123456"})
        p.refresh_from_db()
        self.assertTrue(p.correo_verificado)


# --- Pendientes #7-#17 de la auditoría run-1 ---
import datetime as _dt  # noqa: E402

from asistencia.views import _validar_codigo  # noqa: E402
from rest_framework.exceptions import ValidationError as DRFValidationError  # noqa: E402


def _postulante_activo(**extra):
    usuario = User.objects.create_user(username="1710034065", password="Clave-vieja-123")
    return Postulante.objects.create(
        nombres="J", apellidos="P", cedula="1710034065", estatura_cm=170,
        correo="j@example.com", usuario=usuario, correo_verificado=True, **extra,
    )


class ReenvioConEsperaTest(APITestCase):
    def test_no_se_puede_pedir_otro_codigo_antes_de_un_minuto(self):
        cache.clear()
        p = _postulante_activo(codigo_verificacion="123456", codigo_generado_en=timezone.now(), intentos_codigo=4)
        response = self.client.post("/api/postulantes/reenviar-codigo/", {"cedula": p.cedula})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        p.refresh_from_db()
        self.assertEqual(p.intentos_codigo, 4)  # no se reseteó el presupuesto

    def test_pasado_un_minuto_si_se_puede(self):
        cache.clear()
        p = _postulante_activo(
            codigo_verificacion="123456",
            codigo_generado_en=timezone.now() - _dt.timedelta(seconds=61),
        )
        response = self.client.post("/api/postulantes/reenviar-codigo/", {"cedula": p.cedula})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)


class CodigoAtomicoTest(APITestCase):
    def test_instancia_vieja_no_acepta_un_codigo_ya_anulado(self):
        p = _postulante_activo(codigo_verificacion="123456", codigo_generado_en=timezone.now())
        vieja = Postulante.objects.get(pk=p.pk)  # snapshot tomado antes de agotar intentos
        for _ in range(5):
            with self.assertRaises(DRFValidationError):
                _validar_codigo(Postulante.objects.get(pk=p.pk), "000000")
        with self.assertRaises(DRFValidationError):
            _validar_codigo(vieja, "123456")

    def test_incremento_sobre_snapshot_viejo_no_pierde_intentos(self):
        p = _postulante_activo(codigo_verificacion="123456", codigo_generado_en=timezone.now())
        snapshots = [Postulante.objects.get(pk=p.pk) for _ in range(5)]  # 5 requests "simultáneos"
        for s in snapshots:
            with self.assertRaises(DRFValidationError):
                _validar_codigo(s, "000000")
        p.refresh_from_db()
        self.assertIsNone(p.codigo_verificacion)


class ResetRevocaTokensTest(APITestCase):
    def test_token_anterior_deja_de_servir_tras_restablecer(self):
        cache.clear()
        p = _postulante_activo()
        access = self.client.post(
            "/api/token/", {"username": p.cedula, "password": "Clave-vieja-123"}
        ).data["access"]
        p.codigo_verificacion, p.codigo_generado_en = "123456", timezone.now()
        p.save()
        r = self.client.post(
            "/api/postulantes/restablecer-password/",
            {"cedula": p.cedula, "codigo": "123456", "password_nueva": "Clave-nueva-456!"},
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(self.client.get("/api/mi-postulante/").status_code, status.HTTP_401_UNAUTHORIZED)


class TopeDePixelesTest(APITestCase):
    def test_imagen_de_muchos_megapixeles_no_se_decodifica(self):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("L", (5000, 5000)).save(buf, "PNG")  # 25 MP, pocos KB comprimida
        self.assertLess(buf.tell(), 1024 * 1024)
        self.assertIsNone(_leer_imagen(SimpleUploadedFile("x.png", buf.getvalue())))


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class TopeDeFotosAdicionalesTest(APITestCase):
    def test_cuarta_foto_adicional_es_rechazada(self):
        pool.invalidar()
        p = _postulante_activo(embedding=E1)
        for _ in range(3):
            p.fotos_adicionales.create(foto=_foto("rostro_real.jpg"), embedding=E1)
        self.client.force_authenticate(p.usuario)
        with patch("asistencia.views.calcular_embedding", return_value=E1):
            r = self.client.post(f"/api/postulantes/{p.id}/fotos/", {"foto": _foto("rostro_real.jpg")}, format="multipart")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(p.fotos_adicionales.count(), 3)


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class PrecargaAtomicaTest(APITestCase):
    def setUp(self):
        pool.invalidar()
        self.client.force_authenticate(_staff())
        Postulante.objects.create(nombres="J", apellidos="P", cedula="1710034065", estatura_cm=165, sede="Q")

    def _datos(self):
        return {
            "cedula": "1710034065", "fecha_nacimiento": "1995-05-20", "telefono": "0991234567",
            "correo": "j@example.com", "genero": "M", "foto": _foto("rostro_real.jpg"),
            "password": "Clave-segura-123", "nombres": "x", "apellidos": "x", "estatura_cm": 1,
        }

    def test_user_huerfano_da_400_y_no_500(self):
        User.objects.create_user(username="1710034065")  # quedó de un intento anterior
        with patch("asistencia.views.calcular_embedding", return_value=E1):
            r = self.client.post("/api/postulantes/", self._datos(), format="multipart")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_fallo_al_guardar_no_deja_user_huerfano(self):
        from django.db import IntegrityError
        with patch("asistencia.views.calcular_embedding", return_value=E1), patch(
            "asistencia.serializers.PostulanteSerializer.update", side_effect=IntegrityError("x")
        ):
            r = self.client.post("/api/postulantes/", self._datos(), format="multipart")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(username="1710034065").exists())


class CacheCompartidoTest(APITestCase):
    def test_throttles_usan_un_cache_compartido_entre_workers(self):
        # LocMem es por proceso: con 3 workers de gunicorn cada límite se triplicaba.
        from django.core.cache import caches
        from django.core.cache.backends.db import DatabaseCache
        self.assertIsInstance(caches["default"], DatabaseCache)
