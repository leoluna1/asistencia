"""Carga masiva de postulantes desde un CSV externo (ej. la convocatoria oficial),
sin foto todavía — cada quien completa su registro con la foto después, en el
puesto de registro, con la misma cédula (ver RegistroPostulanteView).

Uso: python manage.py importar_postulantes convocatoria.csv
Columnas esperadas: nombres,apellidos,cedula,estatura_cm,sede
"""
import csv

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from asistencia.models import Postulante

COLUMNAS_REQUERIDAS = {"nombres", "apellidos", "cedula", "estatura_cm", "sede"}


class Command(BaseCommand):
    help = "Precarga postulantes desde un CSV (nombres,apellidos,cedula,estatura_cm,sede)."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")

    def handle(self, csv_path, **options):
        with open(csv_path, newline="", encoding="utf-8") as archivo:
            lector = csv.DictReader(archivo)
            faltantes = COLUMNAS_REQUERIDAS - set(lector.fieldnames or [])
            if faltantes:
                raise CommandError(f"Faltan columnas en el CSV: {', '.join(sorted(faltantes))}")

            creados = omitidos = 0
            for numero_fila, fila in enumerate(lector, start=2):
                cedula = fila["cedula"].strip()
                if not cedula:
                    self.stderr.write(f"Fila {numero_fila}: sin cédula, omitida.")
                    omitidos += 1
                    continue
                if Postulante.objects.filter(cedula=cedula).exists():
                    self.stderr.write(f"Fila {numero_fila}: cédula {cedula} ya existe, omitida.")
                    omitidos += 1
                    continue

                postulante = Postulante(
                    nombres=fila["nombres"].strip(),
                    apellidos=fila["apellidos"].strip(),
                    cedula=cedula,
                    estatura_cm=int(fila["estatura_cm"]),
                    sede=fila["sede"].strip(),
                )
                try:
                    # .create() no corre los validators del modelo (ej. dígito
                    # verificador de la cédula, ver validators.py) — full_clean()
                    # sí, para que un typo en la lista oficial de convocatoria no
                    # quede persistido en silencio con datos que la API pública
                    # habría rechazado.
                    postulante.full_clean()
                except ValidationError as error:
                    detalle = "; ".join(f"{campo}: {', '.join(mensajes)}" for campo, mensajes in error.message_dict.items())
                    self.stderr.write(f"Fila {numero_fila}: datos inválidos ({detalle}), omitida.")
                    omitidos += 1
                    continue

                postulante.save()
                creados += 1

        self.stdout.write(self.style.SUCCESS(f"Creados: {creados}. Omitidos: {omitidos}."))
