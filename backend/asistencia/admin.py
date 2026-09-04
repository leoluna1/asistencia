from django.contrib import admin

from .models import Asistencia, Postulante


@admin.register(Postulante)
class PostulanteAdmin(admin.ModelAdmin):
    list_display = ("cedula", "nombres", "apellidos", "sede", "creado_en")
    search_fields = ("cedula", "nombres", "apellidos")
    list_filter = ("sede",)
    # embedding lo calcula el pipeline de reconocimiento facial a partir de la foto,
    # nunca se edita a mano.
    exclude = ("embedding",)


@admin.register(Asistencia)
class AsistenciaAdmin(admin.ModelAdmin):
    list_display = ("postulante", "sede", "metodo", "verificado_en", "forzado_por")
    list_filter = ("sede", "metodo")
    autocomplete_fields = ("postulante",)
