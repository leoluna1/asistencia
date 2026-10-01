from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Asistencia, FotoPostulante, Postulante


class FotoFirmadaField(serializers.ImageField):
    """Las fotos son biométricas: nunca se exponen por /media/ (cualquiera con la URL
    las veía). La API devuelve /api/fotos/<nombre firmado>/ — solo quien recibió la
    URL de una respuesta autorizada la tiene, y no se puede fabricar sin SECRET_KEY.
    ponytail: firma sin vencimiento, para que el navegador pueda cachearla; pasar a
    TimestampSigner si hace falta que una URL filtrada caduque."""

    def to_representation(self, value):
        if not value:
            return None
        url = reverse("foto-firmada", args=[signing.Signer(salt="foto").sign(value.name)])
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url


class TokenConRolSerializer(TokenObtainPairSerializer):
    """Igual al token estándar de SimpleJWT, pero agrega `is_staff` al payload.

    El frontend lo necesita para distinguir agente de postulante sin una
    llamada extra a la API: ambos roles comparten el mismo login
    (`/api/token/`), y el dashboard debe ser solo para agentes (ver
    `ListaAsistenciasView`/`ForzarAsistenciaView`, que ya exigen `IsAdminUser`
    del lado del backend — esto solo expone el mismo dato al frontend para que
    la UI pueda bloquear la navegación en vez de mostrar una pantalla vacía).
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["is_staff"] = user.is_staff
        return token


class PostulanteSerializer(serializers.ModelSerializer):
    # No es un campo del modelo: la vista la usa para crear la cuenta (User) del
    # postulante (ver RegistroPostulanteView), nunca se guarda en Postulante.
    password = serializers.CharField(write_only=True, required=False, min_length=8)
    foto = FotoFirmadaField()

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
        # sede la asigna la Policía (CSV), no el formulario público.
        read_only_fields = ["id", "creado_en", "sede"]
        # El modelo permite estos campos vacíos (precarga por CSV, ver
        # importar_postulantes), pero un alta/completado por la API siempre los
        # necesita en el mismo request.
        extra_kwargs = {
            campo: {"required": True}
            for campo in ("foto", "fecha_nacimiento", "telefono", "correo", "genero")
        } | {
            # correo es unique=True a nivel de modelo (ver migración 0010) pero
            # sigue siendo null=True/blank=True para permitir la precarga por CSV
            # sin completar -- la API, en cambio, siempre lo exige (igual que los
            # demás campos de este dict). allow_blank=False solo NO alcanza: con
            # allow_null=True (heredado de null=True del modelo) DRF convierte ""
            # en None en vez de rechazarlo ("por motivos históricos", ver
            # CharField.validate_empty_values) -- sin allow_null=False acá, dos
            # postulantes mandando correo="" quedaban con correo=None (sin chocar
            # el unique, pero sin error tampoco, y sin correo real para mandarles
            # nada, ver SolicitarRecuperacionView).
            "correo": {"required": True, "allow_blank": False, "allow_null": False},
        }

    def validate(self, attrs):
        # Contraseña obligatoria solo la primera vez que se completa el registro (alta
        # nueva, o precarga por CSV sin cuenta todavía) — no en una edición posterior
        # del propio postulante (ver MiPostulanteView), que ya tiene cuenta creada.
        sin_cuenta_todavia = self.instance is None or self.instance.usuario_id is None
        if sin_cuenta_todavia and not attrs.get("password"):
            raise serializers.ValidationError({"password": "Este campo es obligatorio."})
        if attrs.get("password"):
            try:
                validate_password(attrs["password"])
            except DjangoValidationError as error:
                raise serializers.ValidationError({"password": error.messages})
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

    # Declarado de nuevo: foto es un campo DECLARADO en el padre, y DRF ignora
    # read_only_fields para los campos declarados (solo aplica a los autogenerados).
    foto = FotoFirmadaField(read_only=True)

    class Meta(PostulanteSerializer.Meta):
        fields = [c for c in PostulanteSerializer.Meta.fields if c != "password"]
        # nombres/apellidos/estatura/sede son datos oficiales de la convocatoria
        # (la estatura es requisito de ingreso); correo es el canal de recuperación:
        # cambiarlo sin reverificar era una forma de quedarse con la cuenta.
        read_only_fields = PostulanteSerializer.Meta.read_only_fields + [
            "cedula", "foto", "nombres", "apellidos", "estatura_cm", "correo",
        ]


class PostulanteVerificacionSerializer(serializers.ModelSerializer):
    """Respuesta de /api/verificar/ (kiosco, solo agentes). Cédula y foto de
    registro para que el agente compare la cédula física y la cara con la persona
    frente a la cámara: un nombre solo no delata una suplantación. Sin teléfono,
    correo ni el resto de los datos personales — el kiosco no los necesita."""

    foto = FotoFirmadaField(read_only=True)

    class Meta:
        model = Postulante
        fields = ["id", "nombres", "apellidos", "cedula", "foto"]
        read_only_fields = fields


class FotoPostulanteSerializer(serializers.ModelSerializer):
    foto = FotoFirmadaField()

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
    postulante_foto = FotoFirmadaField(source="postulante.foto", read_only=True)

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
