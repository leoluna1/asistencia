"""Siembra postulantes (y opcionalmente asistencias) falsos para probar el
sistema al volumen real de la convocatoria (~20.000 postulantes).

NO es parte del producto: existe para medir los caminos críticos antes del día
de la prueba — el matching 1:N de /api/verificar/, el polling del dashboard y
la exportación CSV/PDF — sin esperar a tener 20.000 personas reales.

Uso:
    python manage.py cargar_datos_prueba --cantidad 20000 --con-asistencia
    python manage.py cargar_datos_prueba --limpiar

Los postulantes de prueba usan cédulas válidas (mismo algoritmo módulo-10 que
valida el modelo) del bloque `240XXXXXX`, para poder borrarlos después sin
tocar los postulantes reales. Comparten un único archivo de foto en disco: el
ImageField solo guarda la ruta, y duplicar 20.000 JPEG serían ~1,2 GB inútiles.
"""
import random
import shutil
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from asistencia.models import Asistencia, Postulante

# Bloque reservado para datos de prueba: provincia 24, tercer dígito 0 (ambos
# válidos para el algoritmo de cédula), los 6 siguientes son el contador.
PREFIJO_PRUEBA = "240"
COEFICIENTES = (2, 1, 2, 1, 2, 1, 2, 1, 2)

FOTO_COMPARTIDA = "postulantes/carga_prueba.jpg"
FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "rostro_real.jpg"

NOMBRES = [
    "Juan", "María", "Carlos", "Ana", "Luis", "Rosa", "Jorge", "Elena",
    "Diego", "Paola", "Andrés", "Silvia", "Marco", "Gabriela", "Pedro", "Lucía",
]
APELLIDOS = [
    "Pérez", "Gómez", "Muñoz", "Torres", "Vaca", "Chimbo", "Quishpe", "Salazar",
    "Andrade", "Cevallos", "Zambrano", "Paredes", "Guerrero", "Ríos", "Ortega",
]
SEDES = ["Quito", "Guayaquil", "Cuenca", "Ambato", "Machala", "Portoviejo"]


def _digito_verificador(nueve: str) -> int:
    total = 0
    for digito, coeficiente in zip(nueve, COEFICIENTES):
        producto = int(digito) * coeficiente
        total += producto - 9 if producto > 9 else producto
    return (10 - total % 10) % 10


def cedula_de_prueba(indice: int) -> str:
    nueve = f"{PREFIJO_PRUEBA}{indice:06d}"
    return f"{nueve}{_digito_verificador(nueve)}"


class Command(BaseCommand):
    help = "Siembra postulantes de prueba para medir el sistema a escala real."

    def add_arguments(self, parser):
        parser.add_argument("--cantidad", type=int, default=100)
        parser.add_argument(
            "--con-asistencia",
            action="store_true",
            help="Marca también la asistencia de cada postulante sembrado.",
        )
        parser.add_argument(
            "--limpiar",
            action="store_true",
            help="Borra TODOS los datos de prueba (cédulas 240XXXXXX) y sale.",
        )

    def handle(self, *args, **options):
        # Guarda de seguridad: este comando crea personas que no existen. En una
        # base de producción eso contamina la convocatoria real.
        if not settings.DEBUG:
            raise CommandError(
                "Solo corre con DJANGO_DEBUG=True — es una herramienta de prueba, "
                "nunca debe sembrar datos falsos en producción."
            )

        de_prueba = Postulante.objects.filter(cedula__startswith=PREFIJO_PRUEBA)

        if options["limpiar"]:
            borrados = de_prueba.count()
            de_prueba.delete()  # las asistencias caen por CASCADE
            self.stdout.write(self.style.SUCCESS(f"Borrados {borrados} postulantes de prueba."))
            return

        cantidad = options["cantidad"]
        existentes = set(de_prueba.values_list("cedula", flat=True))
        self._preparar_foto()

        inicio = time.monotonic()
        rng = random.Random(42)  # determinista: dos corridas dan los mismos datos
        creados = self._crear_postulantes(cantidad, existentes, rng)
        self.stdout.write(f"Postulantes sembrados: {creados} en {time.monotonic() - inicio:.1f}s")

        if options["con_asistencia"]:
            inicio = time.monotonic()
            marcadas = self._marcar_asistencias(rng)
            self.stdout.write(f"Asistencias marcadas: {marcadas} en {time.monotonic() - inicio:.1f}s")

        total = Postulante.objects.count()
        self.stdout.write(self.style.SUCCESS(f"Total de postulantes en la base: {total}"))

    def _preparar_foto(self):
        """Copia la foto fixture UNA vez a MEDIA_ROOT; todos los de prueba la comparten."""
        destino = Path(settings.MEDIA_ROOT) / FOTO_COMPARTIDA
        if not destino.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(FIXTURE, destino)

    def _crear_postulantes(self, cantidad, existentes, rng) -> int:
        lote = []
        creados = 0
        indice = 0
        while creados < cantidad:
            cedula = cedula_de_prueba(indice)
            indice += 1
            if cedula in existentes:
                continue
            lote.append(
                Postulante(
                    nombres=rng.choice(NOMBRES),
                    apellidos=f"{rng.choice(APELLIDOS)} {rng.choice(APELLIDOS)}",
                    cedula=cedula,
                    estatura_cm=rng.randint(155, 195),
                    fecha_nacimiento=f"{rng.randint(1995, 2007)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                    telefono=f"09{rng.randint(10000000, 99999999)}",
                    correo=f"prueba{cedula}@example.com",
                    genero=rng.choice(["M", "F"]),
                    foto=FOTO_COMPARTIDA,
                    sede=rng.choice(SEDES),
                    embedding=_embedding_aleatorio(rng),
                )
            )
            creados += 1
            if len(lote) >= 1000:
                Postulante.objects.bulk_create(lote)
                lote = []
                self.stdout.write(f"  ... {creados}/{cantidad}", ending="\r")
        if lote:
            Postulante.objects.bulk_create(lote)
        return creados

    def _marcar_asistencias(self, rng) -> int:
        """Asistencia para cada postulante de prueba que todavía no tenga una,
        repartidas en las últimas 8 horas para que los gráficos por hora del
        dashboard tengan forma realista."""
        sin_asistencia = Postulante.objects.filter(
            cedula__startswith=PREFIJO_PRUEBA, asistencia__isnull=True
        ).values_list("id", "sede")

        lote = []
        for postulante_id, sede in sin_asistencia.iterator(chunk_size=2000):
            lote.append(
                Asistencia(
                    postulante_id=postulante_id,
                    sede=sede or "Quito",
                    metodo=rng.choices(
                        [Asistencia.Metodo.AUTOMATICO, Asistencia.Metodo.MANUAL], [95, 5]
                    )[0],
                    confianza=round(rng.uniform(0.40, 0.95), 4),
                )
            )
        Asistencia.objects.bulk_create(lote, batch_size=1000)

        # verificado_en es auto_now_add: bulk_create lo deja todo en "ahora", lo
        # que dejaría el gráfico por hora del dashboard con una sola barra. Se
        # reparte en un solo UPDATE (20.000 updates fila por fila tardan ~1min).
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE asistencia_asistencia AS a
                SET verificado_en = NOW() - (random() * INTERVAL '8 hours')
                FROM asistencia_postulante AS p
                WHERE a.postulante_id = p.id AND p.cedula LIKE %s
                """,
                [f"{PREFIJO_PRUEBA}%"],
            )
        return len(lote)


def _embedding_aleatorio(rng):
    """Vector unitario de 128 dimensiones, como los que devuelve SFace.

    Aleatorio a propósito: dos personas distintas tienen que dar similitud
    coseno cercana a 0 (bien por debajo del UMBRAL_COINCIDENCIA de 0.363), que
    es justo lo que pasa entre rostros distintos de verdad. Si todos
    compartieran el embedding de la foto fixture, el 1:N encontraría 20.000
    coincidencias perfectas y la prueba no mediría nada real.
    """
    vector = [rng.gauss(0, 1) for _ in range(128)]
    norma = sum(componente * componente for componente in vector) ** 0.5
    return [componente / norma for componente in vector]
