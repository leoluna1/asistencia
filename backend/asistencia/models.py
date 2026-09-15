from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from .validators import validar_cedula_ecuatoriana


class Postulante(models.Model):
    class Genero(models.TextChoices):
        MASCULINO = "M", "Masculino"
        FEMENINO = "F", "Femenino"
        OTRO = "OTRO", "Otro"

    nombres = models.CharField(max_length=150)
    apellidos = models.CharField(max_length=150)
    cedula = models.CharField(
        max_length=10, unique=True, validators=[validar_cedula_ecuatoriana]
    )
    estatura_cm = models.PositiveSmallIntegerField()
    # blank/null en estos cuatro: permite precargar el postulante por CSV (carga masiva,
    # ver management/commands/importar_postulantes.py) solo con los datos de la
    # convocatoria — completa el resto (más la foto) después, en el puesto de registro,
    # misma cédula. La API sí los exige en un alta nueva (ver PostulanteSerializer).
    fecha_nacimiento = models.DateField(null=True, blank=True)
    telefono = models.CharField(max_length=20, null=True, blank=True)
    correo = models.EmailField(null=True, blank=True)
    genero = models.CharField(max_length=10, choices=Genero.choices, null=True, blank=True)
    # blank/null: mismo motivo que los anteriores — llega vacía en la precarga por CSV.
    foto = models.ImageField(upload_to="postulantes/", blank=True, null=True)
    # ponytail: embedding de 128 floats (OpenCV SFace), comparado con numpy en Python al
    # momento de verificar — sin pgvector hasta que el volumen de postulantes lo justifique
    # (ver docs/00-REFERENCIA-PROYECTO.md).
    embedding = ArrayField(models.FloatField(), size=128, null=True, blank=True)
    # blank/null: a diferencia de los otros campos de arriba, esto no es "todavía no
    # completó su registro" — asignar sede es responsabilidad de la Policía Nacional,
    # no de este sistema ni del postulante. Llega ya puesta por la carga masiva CSV
    # (importar_postulantes, columna obligatoria ahí); el registro público ya no la
    # pide. Puede quedar sin valor si alguien se registra sin haber sido precargado.
    sede = models.CharField(max_length=100, blank=True, null=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    # Cuenta propia del postulante (username = cédula), creada junto con el registro
    # (ver RegistroPostulanteView) para que pueda volver a loguearse — vía el mismo
    # /api/token/ que ya usan los agentes — y revisar/corregir sus datos antes del día
    # de la prueba (ver MiPostulanteView). Null en la precarga por CSV: todavía no hay
    # cuenta hasta que el postulante complete su registro con foto y contraseña.
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="postulante",
    )

    def __str__(self):
        return f"{self.nombres} {self.apellidos} ({self.cedula})"


class FotoPostulante(models.Model):
    """Ángulo adicional de referencia para un postulante ya registrado (2-3 fotos
    de perfil/con-sin lentes mejoran el matching 1:N). No reemplaza a Postulante.foto
    (la principal, tomada en el registro) — se suma como candidato más en la lista
    plana de (id, embedding) que ya arma VerificarAsistenciaView, sin tocar
    mejor_coincidencia."""

    postulante = models.ForeignKey(
        Postulante, on_delete=models.CASCADE, related_name="fotos_adicionales"
    )
    foto = models.ImageField(upload_to="postulantes/adicionales/")
    embedding = ArrayField(models.FloatField(), size=128)
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Foto adicional de {self.postulante}"


class Asistencia(models.Model):
    class Metodo(models.TextChoices):
        AUTOMATICO = "AUTO", "Automático (reconocimiento facial)"
        MANUAL = "MANUAL", "Manual (forzado por agente)"

    # OneToOne: registro único de asistencia por postulante (decisión confirmada 2026-09-03),
    # no una entrada por cada prueba a la que esté citado.
    postulante = models.OneToOneField(
        Postulante, on_delete=models.CASCADE, related_name="asistencia"
    )
    sede = models.CharField(max_length=100)
    # db_index: el dashboard pide esto ordenado descendente cada pocos segundos —
    # con miles de postulantes, ordenar sin índice es el primer cuello de botella real.
    verificado_en = models.DateTimeField(auto_now_add=True, db_index=True)
    metodo = models.CharField(
        max_length=10, choices=Metodo.choices, default=Metodo.AUTOMATICO
    )
    confianza = models.FloatField(null=True, blank=True)
    # Auditoría del flujo de respaldo: reintento automático y, si falla, un agente fuerza
    # el paso manualmente — queda registrado quién lo hizo.
    forzado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asistencias_forzadas",
    )

    def __str__(self):
        return f"{self.postulante} — {self.verificado_en:%Y-%m-%d %H:%M}"
