from django.contrib import admin

from .models import Asistencia, FotoPostulante, Postulante


class FotoPostulanteInline(admin.TabularInline):
    model = FotoPostulante
    extra = 0
    # foto de solo lectura: cambiarla acá no recalcula el embedding, y el rostro
    # viejo seguía matcheando en el kiosco. Para revocar un rostro, borrar la fila.
    readonly_fields = ("foto", "creado_en")
    # embedding lo calcula el pipeline a partir de la foto, nunca se edita a mano.
    exclude = ("embedding",)

    def has_add_permission(self, request, obj=None):
        # Sin embedding (NOT NULL) el alta desde acá ni siquiera podía guardarse;
        # las fotos adicionales se suman por la API, que corre el pipeline.
        return False


@admin.register(Postulante)
class PostulanteAdmin(admin.ModelAdmin):
    list_display = ("cedula", "nombres", "apellidos", "sede", "creado_en")
    search_fields = ("cedula", "nombres", "apellidos")
    list_filter = ("sede", "genero")
    # Mismo motivo que en el inline: editar la foto no recalcula el embedding.
    readonly_fields = ("foto",)
    # embedding lo calcula el pipeline de reconocimiento facial a partir de la foto,
    # nunca se edita a mano.
    exclude = ("embedding",)
    inlines = [FotoPostulanteInline]


@admin.register(Asistencia)
class AsistenciaAdmin(admin.ModelAdmin):
    list_display = ("postulante", "sede", "metodo", "verificado_en", "forzado_por")
    list_filter = ("sede", "metodo")
    autocomplete_fields = ("postulante",)
