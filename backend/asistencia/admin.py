from django.contrib import admin

from .models import Asistencia, FotoPostulante, Postulante


class FotoPostulanteInline(admin.TabularInline):
    model = FotoPostulante
    extra = 0
    readonly_fields = ("creado_en",)
    # embedding lo calcula el pipeline a partir de la foto, nunca se edita a mano.
    exclude = ("embedding",)


@admin.register(Postulante)
class PostulanteAdmin(admin.ModelAdmin):
    list_display = ("cedula", "nombres", "apellidos", "sede", "creado_en")
    search_fields = ("cedula", "nombres", "apellidos")
    list_filter = ("sede", "genero")
    # embedding lo calcula el pipeline de reconocimiento facial a partir de la foto,
    # nunca se edita a mano.
    exclude = ("embedding",)
    inlines = [FotoPostulanteInline]


@admin.register(Asistencia)
class AsistenciaAdmin(admin.ModelAdmin):
    list_display = ("postulante", "sede", "metodo", "verificado_en", "forzado_por")
    list_filter = ("sede", "metodo")
    autocomplete_fields = ("postulante",)
