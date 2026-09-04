from rest_framework import serializers

from .models import Asistencia, Postulante


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


class AsistenciaSerializer(serializers.ModelSerializer):
    """Fila de la lista en vivo del dashboard (MVP): solo lo que decidió el cliente
    mostrar — nombre, foto, hora, sede, método. Sin filtros ni exportación todavía."""

    postulante_cedula = serializers.CharField(source="postulante.cedula", read_only=True)
    postulante_nombres = serializers.CharField(source="postulante.nombres", read_only=True)
    postulante_apellidos = serializers.CharField(source="postulante.apellidos", read_only=True)
    postulante_foto = serializers.ImageField(source="postulante.foto", read_only=True)

    class Meta:
        model = Asistencia
        fields = [
            "id",
            "postulante_cedula",
            "postulante_nombres",
            "postulante_apellidos",
            "postulante_foto",
            "sede",
            "metodo",
            "confianza",
            "verificado_en",
        ]
