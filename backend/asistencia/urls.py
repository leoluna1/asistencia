from django.urls import path

from .views import (
    AgregarFotoPostulanteView,
    ExportarAsistenciasView,
    ForzarAsistenciaView,
    ListaAsistenciasView,
    MiPostulanteView,
    ProbarEncuadreView,
    RegistroPostulanteView,
    ReenviarCodigoView,
    RestablecerPasswordView,
    ResumenAsistenciasView,
    SolicitarRecuperacionView,
    VerificarAsistenciaView,
    VerificarCorreoView,
)

urlpatterns = [
    path("postulantes/", RegistroPostulanteView.as_view(), name="registro-postulante"),
    path(
        "postulantes/<int:postulante_id>/fotos/",
        AgregarFotoPostulanteView.as_view(),
        name="agregar-foto-postulante",
    ),
    path("postulantes/probar-encuadre/", ProbarEncuadreView.as_view(), name="probar-encuadre"),
    path("postulantes/verificar-correo/", VerificarCorreoView.as_view(), name="verificar-correo"),
    path("postulantes/reenviar-codigo/", ReenviarCodigoView.as_view(), name="reenviar-codigo"),
    path(
        "postulantes/solicitar-recuperacion/",
        SolicitarRecuperacionView.as_view(),
        name="solicitar-recuperacion",
    ),
    path(
        "postulantes/restablecer-password/",
        RestablecerPasswordView.as_view(),
        name="restablecer-password",
    ),
    path("mi-postulante/", MiPostulanteView.as_view(), name="mi-postulante"),
    path("verificar/", VerificarAsistenciaView.as_view(), name="verificar-asistencia"),
    path("asistencia/manual/", ForzarAsistenciaView.as_view(), name="forzar-asistencia"),
    path("asistencias/", ListaAsistenciasView.as_view(), name="lista-asistencias"),
    path("asistencias/resumen/", ResumenAsistenciasView.as_view(), name="resumen-asistencias"),
    path("asistencias/exportar/", ExportarAsistenciasView.as_view(), name="exportar-asistencias"),
]
