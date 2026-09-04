import cv2
import numpy as np
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .facial import UMBRAL_COINCIDENCIA, RostroNoDetectado, get_embedding, mejor_coincidencia
from .models import Asistencia, Postulante
from .serializers import PostulanteSerializer


def _leer_imagen(foto):
    """UploadedFile de Django -> imagen BGR de OpenCV, o None si no es una imagen válida."""
    datos = np.frombuffer(foto.read(), dtype=np.uint8)
    foto.seek(0)
    return cv2.imdecode(datos, cv2.IMREAD_COLOR)


class RegistroPostulanteView(generics.CreateAPIView):
    """Alta de un postulante: guarda sus datos y el embedding facial de su foto."""

    queryset = Postulante.objects.all()
    serializer_class = PostulanteSerializer

    def perform_create(self, serializer):
        imagen_bgr = _leer_imagen(self.request.FILES["foto"])
        if imagen_bgr is None:
            raise ValidationError({"foto": "No se pudo leer la imagen."})

        try:
            embedding = get_embedding(imagen_bgr)
        except RostroNoDetectado:
            raise ValidationError(
                {"foto": "No se detectó un rostro en la foto. Sube una foto más clara, de frente."}
            )

        serializer.save(embedding=embedding)


class VerificarAsistenciaView(APIView):
    """1:N — recibe una foto de cámara y busca coincidencia entre todos los postulantes."""

    def post(self, request):
        sede = request.data.get("sede")
        if not sede:
            raise ValidationError({"sede": "Este campo es obligatorio."})

        foto = request.FILES.get("foto")
        if not foto:
            raise ValidationError({"foto": "Este campo es obligatorio."})

        imagen_bgr = _leer_imagen(foto)
        if imagen_bgr is None:
            raise ValidationError({"foto": "No se pudo leer la imagen."})

        try:
            embedding_consulta = get_embedding(imagen_bgr)
        except RostroNoDetectado:
            return Response({"verificado": False, "motivo": "no_se_detecto_rostro"})

        candidatos = list(
            Postulante.objects.exclude(embedding__isnull=True).values_list("id", "embedding")
        )
        resultado = mejor_coincidencia(embedding_consulta, candidatos)

        if resultado is None or resultado[1] < UMBRAL_COINCIDENCIA:
            return Response(
                {
                    "verificado": False,
                    "motivo": "sin_coincidencia",
                    "confianza": resultado[1] if resultado else None,
                }
            )

        postulante_id, confianza = resultado
        postulante = Postulante.objects.get(id=postulante_id)

        # Registro único de asistencia (decisión confirmada): si ya existía, no se duplica,
        # solo se informa que ya estaba marcada.
        asistencia, creada = Asistencia.objects.get_or_create(
            postulante=postulante,
            defaults={
                "sede": sede,
                "metodo": Asistencia.Metodo.AUTOMATICO,
                "confianza": confianza,
            },
        )

        return Response(
            {
                "verificado": True,
                "ya_registrado": not creada,
                "confianza": confianza,
                "postulante": PostulanteSerializer(postulante, context={"request": request}).data,
                "verificado_en": asistencia.verificado_en,
            }
        )
