from rest_framework import serializers

from .models import Asistencia, FotoPostulante, Postulante


class PostulanteSerializer(serializers.ModelSerializer):
    # No es un campo del modelo: la vista la usa para crear la cuenta (User) del
    # postulante (ver RegistroPostulanteView), nunca se guarda en Postulante.
    password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = Postulante
        fields = [
            "id",
            "nombres",
            "apellidos",
            "cedula",
            "estatura_cm",
            "fecha_nacimiento",
            "telefono",
            "correo",
            "genero",
            "foto",
            "sede",
            "creado_en",
            "password",
        ]
        read_only_fields = ["id", "creado_en"]
        # El modelo permite estos campos vacíos (precarga por CSV, ver
        # importar_postulantes), pero un alta/completado por la API siempre los
        # necesita en el mismo request.
        extra_kwargs = {
            campo: {"required": True}
            for campo in ("foto", "fecha_nacimiento", "telefono", "correo", "genero")
        }

    def validate(self, attrs):
        # Contraseña obligatoria solo la primera vez que se completa el registro (alta
        # nueva, o precarga por CSV sin cuenta todavía) — no en una edición posterior
        # del propio postulante (ver MiPostulanteView), que ya tiene cuenta creada.
        sin_cuenta_todavia = self.instance is None or self.instance.usuario_id is None
        if sin_cuenta_todavia and not attrs.get("password"):
            raise serializers.ValidationError({"password": "Este campo es obligatorio."})
        return attrs

    def create(self, validated_data):
        validated_data.pop("password", None)  # la vista crea el User aparte
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("password", None)
        return super().update(instance, validated_data)


class MiPostulanteSerializer(PostulanteSerializer):
    """Autoservicio: el propio postulante consulta/corrige sus datos (ver
    MiPostulanteView). cedula y foto quedan de solo lectura acá — cambiarlas requiere
    rehacer el pipeline de reconocimiento facial (foto) o tocar la identidad misma
    (cédula), fuera del alcance de una autoedición de datos de contacto."""

    class Meta(PostulanteSerializer.Meta):
        fields = [c for c in PostulanteSerializer.Meta.fields if c != "password"]
        read_only_fields = PostulanteSerializer.Meta.read_only_fields + ["cedula", "foto"]


class FotoPostulanteSerializer(serializers.ModelSerializer):
    class Meta:
        model = FotoPostulante
        fields = ["id", "foto", "creado_en"]
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
