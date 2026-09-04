from django.urls import path

from .views import RegistroPostulanteView

urlpatterns = [
    path("postulantes/", RegistroPostulanteView.as_view(), name="registro-postulante"),
]
