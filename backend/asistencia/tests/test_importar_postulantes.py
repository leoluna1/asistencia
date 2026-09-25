"""Tests del comando de carga masiva (management/commands/importar_postulantes.py)."""
import tempfile
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase

from asistencia.models import Postulante


class ImportarPostulantesTest(TestCase):
    def _csv(self, contenido: str) -> str:
        archivo = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8"
        )
        archivo.write(contenido)
        archivo.close()
        return archivo.name

    def test_crea_postulantes_sin_foto_desde_el_csv(self):
        csv_path = self._csv(
            "nombres,apellidos,cedula,estatura_cm,sede\n"
            "Juan,Pérez,1710034065,175,Quito\n"
            "Ana,Lopez,1719141770,160,Cuenca\n"
        )
        call_command("importar_postulantes", csv_path)

        self.assertEqual(Postulante.objects.count(), 2)
        juan = Postulante.objects.get(cedula="1710034065")
        self.assertFalse(juan.foto)
        self.assertIsNone(juan.embedding)

    def test_omite_cedulas_que_ya_existen(self):
        Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065", estatura_cm=175, sede="Quito"
        )
        csv_path = self._csv(
            "nombres,apellidos,cedula,estatura_cm,sede\nJuan,Pérez,1710034065,175,Quito\n"
        )
        call_command("importar_postulantes", csv_path)
        self.assertEqual(Postulante.objects.count(), 1)

    def test_omite_cedula_con_digito_verificador_invalido(self):
        # Mismo checksum inválido que ya se usa en test_validators.py — un typo de
        # la lista oficial de convocatoria no debe quedar persistido en silencio.
        csv_path = self._csv(
            "nombres,apellidos,cedula,estatura_cm,sede\nJuan,Pérez,1234567890,175,Quito\n"
        )
        call_command("importar_postulantes", csv_path)
        self.assertEqual(Postulante.objects.count(), 0)

    def test_omite_estatura_invalida(self):
        csv_path = self._csv(
            "nombres,apellidos,cedula,estatura_cm,sede\nJuan,Pérez,1710034065,-5,Quito\n"
        )
        call_command("importar_postulantes", csv_path)
        self.assertEqual(Postulante.objects.count(), 0)

    def test_falla_si_faltan_columnas(self):
        csv_path = self._csv("nombres,apellidos,cedula\nJuan,Pérez,1710034065\n")
        with self.assertRaises(CommandError):
            call_command("importar_postulantes", csv_path)
