from django.urls import path

from .views import RegistroPostulanteView, VerificarAsistenciaView

urlpatterns = [
    path("postulantes/", RegistroPostulanteView.as_view(), name="registro-postulante"),
    path("verificar/", VerificarAsistenciaView.as_view(), name="verificar-asistencia"),
]
