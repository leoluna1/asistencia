from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models


class Postulante(models.Model):
    nombres = models.CharField(max_length=150)
    apellidos = models.CharField(max_length=150)
    cedula = models.CharField(max_length=10, unique=True)
    estatura_cm = models.PositiveSmallIntegerField()
    foto = models.ImageField(upload_to="postulantes/")
    # ponytail: embedding de 512 floats (SFace/Dlib vía deepface), comparado con numpy en
    # Python al momento de verificar — sin pgvector hasta que el volumen de postulantes lo
    # justifique (ver docs/00-REFERENCIA-PROYECTO.md).
    embedding = ArrayField(models.FloatField(), size=512, null=True, blank=True)
    sede = models.CharField(max_length=100)
    creado_en = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombres} {self.apellidos} ({self.cedula})"


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
    verificado_en = models.DateTimeField(auto_now_add=True)
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
