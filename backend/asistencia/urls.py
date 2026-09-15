from django.urls import path

from .views import (
    AgregarFotoPostulanteView,
    ForzarAsistenciaView,
    ListaAsistenciasView,
    MiPostulanteView,
    ProbarEncuadreView,
    RegistroPostulanteView,
    VerificarAsistenciaView,
)

urlpatterns = [
    path("postulantes/", RegistroPostulanteView.as_view(), name="registro-postulante"),
    path(
        "postulantes/<int:postulante_id>/fotos/",
        AgregarFotoPostulanteView.as_view(),
        name="agregar-foto-postulante",
    ),
    path("postulantes/probar-encuadre/", ProbarEncuadreView.as_view(), name="probar-encuadre"),
    path("mi-postulante/", MiPostulanteView.as_view(), name="mi-postulante"),
    path("verificar/", VerificarAsistenciaView.as_view(), name="verificar-asistencia"),
    path("asistencia/manual/", ForzarAsistenciaView.as_view(), name="forzar-asistencia"),
    path("asistencias/", ListaAsistenciasView.as_view(), name="lista-asistencias"),
]
