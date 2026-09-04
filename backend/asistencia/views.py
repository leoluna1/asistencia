import cv2
import numpy as np
from rest_framework import generics
from rest_framework.exceptions import ValidationError

from .facial import RostroNoDetectado, get_embedding
from .models import Postulante
from .serializers import PostulanteSerializer


class RegistroPostulanteView(generics.CreateAPIView):
    """Alta de un postulante: guarda sus datos y el embedding facial de su foto."""

    queryset = Postulante.objects.all()
    serializer_class = PostulanteSerializer

    def perform_create(self, serializer):
        foto = self.request.FILES["foto"]
        datos = np.frombuffer(foto.read(), dtype=np.uint8)
        foto.seek(0)  # el ImageField todavía necesita leer el archivo para guardarlo
        imagen_bgr = cv2.imdecode(datos, cv2.IMREAD_COLOR)
        if imagen_bgr is None:
            raise ValidationError({"foto": "No se pudo leer la imagen."})

        try:
            embedding = get_embedding(imagen_bgr)
        except RostroNoDetectado:
            raise ValidationError(
                {"foto": "No se detectó un rostro en la foto. Sube una foto más clara, de frente."}
            )

        serializer.save(embedding=embedding)
