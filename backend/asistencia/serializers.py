from rest_framework import serializers

from .models import Postulante


class PostulanteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Postulante
        fields = [
            "id",
            "nombres",
            "apellidos",
            "cedula",
            "estatura_cm",
            "foto",
            "sede",
            "creado_en",
        ]
        read_only_fields = ["id", "creado_en"]
