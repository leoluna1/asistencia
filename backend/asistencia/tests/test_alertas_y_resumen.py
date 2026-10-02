"""Alerta de intento repetido en el kiosco/panel y PDF de resumen (2026-10-01)."""
import datetime
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from asistencia import pool
from asistencia.facial import get_embedding
from asistencia.models import Asistencia, Postulante
from asistencia.tests.test_views import MEDIA_TMP, _foto, cv2_leer

URL_INTENTOS = "/api/asistencias/intentos-repetidos/"


@override_settings(MEDIA_ROOT=MEDIA_TMP)
class IntentoRepetidoTest(APITestCase):
    def setUp(self):
        pool.invalidar()
        self.agente = User.objects.create_user(username="agente", is_staff=True)
        self.client.force_authenticate(self.agente)
        self.p = Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065", estatura_cm=170,
            foto=_foto("rostro_real.jpg"), embedding=get_embedding(cv2_leer("rostro_real.jpg")),
        )

    def _verificar(self, sede):
        return self.client.post("/api/verificar/", {"sede": sede, "foto": _foto("rostro_real.jpg")}, format="multipart")

    def test_segundo_paso_por_el_kiosco_queda_registrado_y_avisa_la_sede_original(self):
        self._verificar("Quito")
        r = self._verificar("Guayaquil")
        self.assertTrue(r.data["ya_registrado"])
        self.assertEqual(r.data["sede_original"], "Quito")
        self.assertEqual(self.p.intentos_repetidos.count(), 1)
        self.assertEqual(self.p.intentos_repetidos.get().sede, "Guayaquil")

    def test_primer_paso_no_es_intento_repetido(self):
        self._verificar("Quito")
        self.assertEqual(self.p.intentos_repetidos.count(), 0)

    def test_el_panel_lista_los_intentos_de_las_ultimas_24_horas(self):
        Asistencia.objects.create(postulante=self.p, sede="Quito")
        reciente = self.p.intentos_repetidos.create(sede="Guayaquil")
        viejo = self.p.intentos_repetidos.create(sede="Cuenca")
        type(viejo).objects.filter(pk=viejo.pk).update(intentado_en=timezone.now() - datetime.timedelta(days=2))
        r = self.client.get(URL_INTENTOS)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual([i["id"] for i in r.data], [reciente.id])
        fila = r.data[0]
        self.assertEqual(fila["cedula"], "1710034065")
        self.assertEqual(fila["sede"], "Guayaquil")
        self.assertEqual(fila["sede_original"], "Quito")
        self.assertIn("primera_asistencia", fila)

    def test_intentos_solo_para_agentes(self):
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(URL_INTENTOS).status_code, (401, 403))
        self.client.force_authenticate(User.objects.create_user(username="1710034073"))
        self.assertEqual(self.client.get(URL_INTENTOS).status_code, status.HTTP_403_FORBIDDEN)


class PdfResumenTest(APITestCase):
    def test_pdf_resumen_funciona_con_mas_de_2000_asistencias(self):
        # El PDF de listado estaba topado en 2000 filas (500 s con 20k): el
        # resumen se agrega en la base y no depende de la cantidad.
        postulantes = Postulante.objects.bulk_create(
            Postulante(nombres="N", apellidos="A", cedula=f"9{i:09d}", estatura_cm=170) for i in range(2001)
        )
        Asistencia.objects.bulk_create(
            Asistencia(postulante=p, sede="Quito" if i % 2 else "Cuenca") for i, p in enumerate(postulantes)
        )
        self.client.force_authenticate(User.objects.create_user(username="agente", is_staff=True))
        from django.template.loader import render_to_string as real
        with patch("asistencia.views.render_to_string", side_effect=real) as render:
            r = self.client.get("/api/asistencias/exportar/", {"formato": "pdf"})
        self.assertEqual(r.status_code, status.HTTP_200_OK, getattr(r, "data", None))
        self.assertTrue(r.content.startswith(b"%PDF"))
        contexto = render.call_args[0][1]
        self.assertEqual(contexto["total"], 2001)
        self.assertEqual({f["sede"]: f["total"] for f in contexto["por_sede"]}, {"Quito": 1000, "Cuenca": 1001})
        self.assertNotIn("asistencias", contexto)  # sin listado fila por fila
