import csv
import datetime
import random

import cv2
import numpy as np
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncHour
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.timezone import get_current_timezone, is_naive, make_aware, now
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from . import pool
from .facial import (
    UMBRAL_COINCIDENCIA,
    RostroNoDetectado,
    calcular_embedding,
    detectar_rostro,
    es_rostro_real,
    validar_calidad_registro,
)
from .models import Asistencia, FotoPostulante, Postulante
from .serializers import (
    AsistenciaSerializer,
    FotoPostulanteSerializer,
    MiPostulanteSerializer,
    PostulanteSerializer,
    PostulanteVerificacionSerializer,
    TokenConRolSerializer,
)


def _leer_imagen(foto):
    """UploadedFile de Django -> imagen BGR de OpenCV, o None si no es una imagen válida."""
    datos = np.frombuffer(foto.read(), dtype=np.uint8)
    foto.seek(0)
    return cv2.imdecode(datos, cv2.IMREAD_COLOR)


def _procesar_foto_de_registro(foto) -> list[float]:
    """Lee, detecta y valida el encuadre de una foto de registro. Devuelve el
    embedding, o lanza ValidationError con el motivo puntual del rechazo."""
    imagen_bgr = _leer_imagen(foto)
    if imagen_bgr is None:
        raise ValidationError({"foto": "No se pudo leer la imagen."})

    try:
        imagen_bgr, rostro = detectar_rostro(imagen_bgr)
    except RostroNoDetectado:
        raise ValidationError(
            {"foto": "No se detectó un rostro en la foto. Sube una foto más clara, de frente."}
        )

    problema = validar_calidad_registro(imagen_bgr, rostro)
    if problema:
        raise ValidationError({"foto": problema})

    return calcular_embedding(imagen_bgr, rostro)


MINUTOS_EXPIRACION_CODIGO_VERIFICACION = 15


def _generar_y_enviar_codigo_verificacion(postulante):
    """Genera un código de 6 dígitos y lo manda al correo del postulante (ver
    VerificarCorreoView) — se llama solo cuando se crea la cuenta (is_active=False
    hasta verificar), nunca al reusar una ya verificada."""
    codigo = f"{random.randint(0, 999999):06d}"
    postulante.codigo_verificacion = codigo
    postulante.codigo_generado_en = now()
    postulante.save(update_fields=["codigo_verificacion", "codigo_generado_en"])
    send_mail(
        "Código de verificación — Policía Nacional",
        f"Tu código de verificación es: {codigo}\n"
        f"Vence en {MINUTOS_EXPIRACION_CODIGO_VERIFICACION} minutos.",
        None,  # usa DEFAULT_FROM_EMAIL
        [postulante.correo],
    )


class RegistroPostulanteView(generics.CreateAPIView):
    """Alta de un postulante: guarda sus datos y el embedding facial de su foto.

    Si la cédula ya existe precargada por lote (carga masiva, ver
    management/commands/importar_postulantes.py) pero todavía sin foto, este mismo
    endpoint completa ese registro en vez de rechazarlo como cédula duplicada — es
    la misma persona terminando su alta en el puesto de registro.
    """

    # Público a propósito (postulante autoregistrándose, sin cuenta todavía) — sin
    # esto, un token JWT viejo/expirado que haya quedado en el navegador (ej. un
    # agente que se logueó antes en ese mismo equipo) hace que DRF devuelva 401
    # antes de llegar a chequear el permiso, aunque el endpoint no exija login.
    authentication_classes = []
    queryset = Postulante.objects.all()
    serializer_class = PostulanteSerializer

    def create(self, request, *args, **kwargs):
        cedula = request.data.get("cedula")
        precargado = (
            Postulante.objects.filter(cedula=cedula).filter(Q(foto="") | Q(foto__isnull=True)).first()
            if cedula
            else None
        )
        if precargado:
            return self._completar_precarga(precargado, request)
        try:
            with transaction.atomic():
                return super().create(request, *args, **kwargs)
        except IntegrityError as error:
            # Dos registros casi simultáneos con la misma cédula O el mismo correo
            # nuevos (ej. doble envío por conexión inestable en el kiosco) pueden
            # pasar ambos la validación del serializer (el UniqueValidator consulta
            # la BD antes de que ninguno haga commit) — el segundo INSERT choca acá.
            # Se distingue por el nombre real de la restricción que violó Postgres
            # (psycopg2 lo expone en error.__cause__.diag), no por texto libre del
            # mensaje, para devolver el campo correcto en vez de asumir "cédula".
            constraint = getattr(getattr(error.__cause__, "diag", None), "constraint_name", "") or ""
            if "correo" in constraint:
                raise ValidationError({"correo": "Ya existe un postulante con este correo."})
            raise ValidationError({"cedula": "Ya existe un postulante con esta cédula."})

    def _completar_precarga(self, postulante, request):
        # instance=postulante, SIN partial: el frontend siempre manda el registro
        # completo (nombres/apellidos/estatura_cm ya vienen del CSV, pero
        # foto/fecha_nacimiento/telefono/correo/genero/password todavía no) — con
        # partial=True, DRF salta la validación de los campos required=True que
        # falten en el request en vez de rechazarlos, dejando completar la
        # precarga sin foto (KeyError sin capturar) o con datos nulos guardados.
        serializer = self.get_serializer(postulante, data=request.data)
        serializer.is_valid(raise_exception=True)
        embedding = _procesar_foto_de_registro(request.FILES["foto"])
        # La precarga puede ya tener cuenta propia si un agente le limpió la foto
        # después de completada (ej. mala foto, pide resubirla) — reusar esa
        # cuenta en vez de intentar crear una con el mismo username (cédula) dos
        # veces, que choca contra el unique constraint de User.
        usuario = postulante.usuario
        cuenta_nueva = usuario is None
        if cuenta_nueva:
            # is_active=False: no puede loguearse hasta verificar el correo (ver
            # VerificarCorreoView) — si ya tenía cuenta (agente le limpió la foto
            # para que la resuba), no se la vuelve a bloquear ni se le manda otro
            # código, ya la había verificado la primera vez.
            usuario = User.objects.create_user(
                username=postulante.cedula,
                password=serializer.validated_data["password"],
                is_active=False,
            )
        postulante_guardado = serializer.save(embedding=embedding, usuario=usuario)
        pool.invalidar()  # hay un rostro nuevo que el 1:N tiene que poder encontrar
        if cuenta_nueva:
            _generar_y_enviar_codigo_verificacion(postulante_guardado)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        embedding = _procesar_foto_de_registro(self.request.FILES["foto"])
        # username = cédula: el postulante se loguea después (/api/token/, mismo
        # endpoint JWT que ya usan los agentes) para revisar/corregir sus datos
        # antes del día de la prueba (ver MiPostulanteView). is_active=False: no
        # puede hacerlo hasta verificar el correo (ver VerificarCorreoView).
        usuario = User.objects.create_user(
            username=serializer.validated_data["cedula"],
            password=serializer.validated_data["password"],
            is_active=False,
        )
        postulante = serializer.save(embedding=embedding, usuario=usuario)
        pool.invalidar()  # hay un rostro nuevo que el 1:N tiene que poder encontrar
        _generar_y_enviar_codigo_verificacion(postulante)


class ProbarEncuadreView(APIView):
    """Chequeo en vivo, sin guardar nada: la cámara del registro manda un frame cada
    ~1s mientras el postulante se acomoda, y esto le dice si ya está bien encuadrado
    o qué corregir. Reusa la MISMA validar_calidad_registro que corre en el registro
    real (ver _procesar_foto_de_registro) — el aviso en vivo y el rechazo final nunca
    se contradicen."""

    # Público (ver nota en RegistroPostulanteView: evita 401 por un token viejo).
    authentication_classes = []
    # Scope propio y generoso (ver settings.py): esto polea cada ~900ms por
    # puesto de registro, así que con el piso global anon de 120/min dos puestos
    # detrás de la misma IP ya lo agotaban y la auto-captura se apagaba sola.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "encuadre"

    def post(self, request):
        foto = request.FILES.get("foto")
        if not foto:
            raise ValidationError({"foto": "Este campo es obligatorio."})

        imagen_bgr = _leer_imagen(foto)
        if imagen_bgr is None:
            return Response({"ok": False, "motivo": "No se pudo leer la imagen."})

        try:
            imagen_bgr, rostro = detectar_rostro(imagen_bgr)
        except RostroNoDetectado:
            return Response({"ok": False, "motivo": "No se detecta tu rostro."})

        problema = validar_calidad_registro(imagen_bgr, rostro)
        if problema:
            return Response({"ok": False, "motivo": problema})

        return Response({"ok": True})


class VerificarCorreoView(APIView):
    """Confirma que el correo dado en el registro es del propio postulante — la
    cuenta se crea con is_active=False (ver RegistroPostulanteView) hasta que esto
    pasa; Django ya rechaza el login de una cuenta inactiva sin más código."""

    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "verificar-correo"

    def post(self, request):
        cedula = request.data.get("cedula")
        codigo = request.data.get("codigo")
        if not cedula or not codigo:
            raise ValidationError({"codigo": "Cédula y código son obligatorios."})

        try:
            postulante = Postulante.objects.select_related("usuario").get(cedula=cedula)
        except Postulante.DoesNotExist:
            raise ValidationError({"cedula": "No existe un registro con esa cédula."})

        if not postulante.usuario or not postulante.codigo_verificacion:
            raise ValidationError(
                {"codigo": "No hay ninguna verificación pendiente para esta cédula."}
            )

        vencido = now() - postulante.codigo_generado_en > datetime.timedelta(
            minutes=MINUTOS_EXPIRACION_CODIGO_VERIFICACION
        )
        if vencido:
            raise ValidationError({"codigo": "El código expiró. Pedí uno nuevo."})
        if codigo != postulante.codigo_verificacion:
            raise ValidationError({"codigo": "Código incorrecto."})

        postulante.usuario.is_active = True
        postulante.usuario.save(update_fields=["is_active"])
        postulante.codigo_verificacion = None
        postulante.codigo_generado_en = None
        postulante.save(update_fields=["codigo_verificacion", "codigo_generado_en"])
        return Response({"verificado": True})


class ReenviarCodigoView(APIView):
    """Genera y manda un código nuevo, invalidando el anterior — para cuando
    expiró o no llegó el correo (ver VerificarCorreoView)."""

    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "reenviar-codigo"

    def post(self, request):
        cedula = request.data.get("cedula")
        if not cedula:
            raise ValidationError({"cedula": "Este campo es obligatorio."})

        try:
            postulante = Postulante.objects.select_related("usuario").get(cedula=cedula)
        except Postulante.DoesNotExist:
            raise ValidationError({"cedula": "No existe un registro con esa cédula."})
        if not postulante.usuario:
            raise ValidationError({"cedula": "No hay ningún registro pendiente para esta cédula."})

        _generar_y_enviar_codigo_verificacion(postulante)
        return Response({"reenviado": True})


class SolicitarRecuperacionView(APIView):
    """Pide un código de recuperación de contraseña por correo — solo para
    cuentas ya activas. Reusa el mismo codigo_verificacion/codigo_generado_en
    que usa la verificación de correo del registro (ver VerificarCorreoView):
    son mutuamente excluyentes (verificación = cuenta inactiva, recuperación
    = cuenta activa), nunca compiten por el campo al mismo tiempo."""

    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "solicitar-recuperacion"

    def post(self, request):
        cedula = request.data.get("cedula")
        if not cedula:
            raise ValidationError({"cedula": "Este campo es obligatorio."})

        try:
            postulante = Postulante.objects.select_related("usuario").get(cedula=cedula)
        except Postulante.DoesNotExist:
            raise ValidationError({"cedula": "No existe un registro con esa cédula."})
        if not postulante.usuario:
            raise ValidationError({"cedula": "No hay ningún registro pendiente para esta cédula."})
        if not postulante.usuario.is_active:
            raise ValidationError(
                {
                    "cedula": "Esta cuenta todavía no verificó su correo. Pedí que te "
                    "reenvíen el código de verificación en vez de recuperar la contraseña."
                }
            )

        _generar_y_enviar_codigo_verificacion(postulante)
        return Response({"enviado": True})


class RestablecerPasswordView(APIView):
    """Confirma el código de recuperación y establece la contraseña nueva
    — ver SolicitarRecuperacionView."""

    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "restablecer-password"

    def post(self, request):
        cedula = request.data.get("cedula")
        codigo = request.data.get("codigo")
        password_nueva = request.data.get("password_nueva")
        if not cedula or not codigo or not password_nueva:
            raise ValidationError(
                {"codigo": "Cédula, código y contraseña nueva son obligatorios."}
            )
        if len(password_nueva) < 8:
            raise ValidationError(
                {"password_nueva": "Asegúrese de que este campo tenga al menos 8 caracteres."}
            )

        try:
            postulante = Postulante.objects.select_related("usuario").get(cedula=cedula)
        except Postulante.DoesNotExist:
            raise ValidationError({"cedula": "No existe un registro con esa cédula."})

        if not postulante.usuario or not postulante.codigo_verificacion:
            raise ValidationError(
                {"codigo": "No hay ninguna recuperación pendiente para esta cédula."}
            )

        vencido = now() - postulante.codigo_generado_en > datetime.timedelta(
            minutes=MINUTOS_EXPIRACION_CODIGO_VERIFICACION
        )
        if vencido:
            raise ValidationError({"codigo": "El código expiró. Pedí uno nuevo."})
        if codigo != postulante.codigo_verificacion:
            raise ValidationError({"codigo": "Código incorrecto."})

        postulante.usuario.set_password(password_nueva)
        postulante.usuario.save(update_fields=["password"])
        postulante.codigo_verificacion = None
        postulante.codigo_generado_en = None
        postulante.save(update_fields=["codigo_verificacion", "codigo_generado_en"])
        return Response({"restablecido": True})


class AgregarFotoPostulanteView(generics.CreateAPIView):
    """Suma un ángulo adicional de referencia a un postulante ya registrado (ver
    FotoPostulante). El postulante ya tiene su foto principal; esto es opcional,
    para cuando 2-3 fotos mejoran el matching 1:N (perfil, con/sin lentes, etc.)."""

    # Requiere login (a diferencia del registro/verificación, que son públicos a
    # propósito): sin esto, cualquiera podía sumar su propio rostro al pool de
    # matching de OTRO postulante (postulante_id es un entero adivinable en la URL)
    # y hacerse pasar por él en /api/verificar/ — ver el chequeo de dueño abajo.
    permission_classes = [IsAuthenticated]
    serializer_class = FotoPostulanteSerializer

    def perform_create(self, serializer):
        postulante = get_object_or_404(Postulante, pk=self.kwargs["postulante_id"])
        # Solo el propio postulante (autoservicio, mismo criterio que
        # MiPostulanteView) o un agente (is_staff) pueden sumarle una foto —
        # nunca un tercero autenticado como otro postulante.
        es_el_propio_postulante = postulante.usuario_id == self.request.user.id
        if not (self.request.user.is_staff or es_el_propio_postulante):
            raise PermissionDenied("No puedes agregar fotos a otro postulante.")
        embedding = _procesar_foto_de_registro(self.request.FILES["foto"])
        serializer.save(postulante=postulante, embedding=embedding)
        pool.invalidar()  # un ángulo más para el 1:N de este postulante


class MiPostulanteView(generics.RetrieveUpdateAPIView):
    """Autoservicio: el postulante ya logueado (cuenta creada en el registro, ver
    RegistroPostulanteView) consulta o corrige sus propios datos antes del día de la
    prueba — cedula y foto quedan de solo lectura (ver MiPostulanteSerializer)."""

    permission_classes = [IsAuthenticated]
    serializer_class = MiPostulanteSerializer

    def get_object(self):
        return get_object_or_404(Postulante, usuario=self.request.user)


class VerificarAsistenciaView(APIView):
    """1:N — recibe una foto de cámara y busca coincidencia entre todos los postulantes."""

    # Público (ver nota en RegistroPostulanteView: evita 401 por un token viejo) — el
    # kiosco de verificación no loguea a nadie, cualquier postulante puede sentarse.
    authentication_classes = []
    # Throttle propio y más estricto que el piso global (ver settings.py): sin esto,
    # cualquiera con acceso de red al backend (no solo el kiosco físico) podía mandar
    # fotos al voleo intentando encontrar coincidencia 1:N y recibir en la respuesta
    # los datos personales (foto, teléfono, correo, etc.) de un postulante real.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "verificar"

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
            imagen_bgr, rostro = detectar_rostro(imagen_bgr)
        except RostroNoDetectado:
            return Response({"verificado": False, "motivo": "no_se_detecto_rostro"})

        # Anti-spoofing antes de comparar identidad: sin esto, una foto de otra persona
        # mostrada a la cámara podría marcarle la asistencia (riesgo confirmado en
        # docs/00-REFERENCIA-PROYECTO.md, inaceptable en un proceso de reclutamiento).
        es_real, confianza_vida = es_rostro_real(imagen_bgr, rostro)
        if not es_real:
            return Response(
                {
                    "verificado": False,
                    "motivo": "posible_suplantacion",
                    "confianza_vida": confianza_vida,
                }
            )

        embedding_consulta = calcular_embedding(imagen_bgr, rostro)

        # Candidatos desde el pool en memoria (ver pool.py): la foto principal de
        # cada postulante + cualquier ángulo adicional, en una matriz ya
        # normalizada. Antes esto releía los 20 MB de embeddings desde Postgres
        # en CADA verificación (875 ms de los 1,1 s totales, medido con 20.005
        # postulantes) para comparar contra datos que casi nunca cambian.
        ids, matriz = pool.obtener()
        resultado = pool.mejor_coincidencia_en_pool(embedding_consulta, ids, matriz)

        # Red de seguridad contra un pool desactualizado: si no hay coincidencia,
        # puede ser alguien que se registró recién (en otro worker, que no vio
        # nuestro invalidar()) — se relee y se reintenta UNA vez antes de
        # rechazarlo. Un "sin coincidencia" real paga esa relectura, pero es el
        # caso raro y de ahí se pasa al override manual del agente igual.
        if (
            resultado is None or resultado[1] < UMBRAL_COINCIDENCIA
        ) and pool.edad_segundos() > 2:
            ids, matriz = pool.obtener(forzar=True)
            resultado = pool.mejor_coincidencia_en_pool(embedding_consulta, ids, matriz)

        if resultado is None or resultado[1] < UMBRAL_COINCIDENCIA:
            return Response(
                {
                    "verificado": False,
                    "motivo": "sin_coincidencia",
                    "confianza": resultado[1] if resultado else None,
                }
            )

        postulante_id, confianza = resultado
        postulante = Postulante.objects.filter(id=postulante_id).first()
        if postulante is None:
            # El pool puede tener hasta SEGUNDOS_FRESCURA de atraso: si un agente
            # borró ese registro (ej. un duplicado) en el medio, el id ya no
            # existe. Se relee y se reintenta una vez; sin esto la verificación
            # tiraba un 500 en vez de seguir atendiendo a la fila.
            ids, matriz = pool.obtener(forzar=True)
            resultado = pool.mejor_coincidencia_en_pool(embedding_consulta, ids, matriz)
            if resultado is None or resultado[1] < UMBRAL_COINCIDENCIA:
                return Response({"verificado": False, "motivo": "sin_coincidencia"})
            postulante_id, confianza = resultado
            postulante = get_object_or_404(Postulante, id=postulante_id)

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
                "postulante": PostulanteVerificacionSerializer(postulante).data,
                "verificado_en": asistencia.verificado_en,
            }
        )


def _parsear_fecha(valor, *, limite_de_dia):
    """Acepta tanto un datetime ISO 8601 completo como una fecha sola (typical de
    un date picker, ej. "2026-09-24") — en ese caso se interpreta como el
    principio o el final de ese día según `limite_de_dia` ("inicio"/"fin").
    Devuelve None si no se puede interpretar (el llamante decide ignorar el
    filtro en vez de romper la request con un valor mal formado).

    Ojo: se prueba parse_date() ANTES que parse_datetime() a propósito —
    parse_datetime("2026-09-24") no devuelve None como cabría esperar de un
    valor sin hora, sino esa fecha a medianoche, lo que rompería silenciosamente
    el límite "fin" (quedaría en medianoche en vez de fin de día). parse_date()
    es estricto con el formato YYYY-MM-DD y sí devuelve None ante un datetime
    completo, así que sirve para distinguir los dos casos de forma confiable.

    Ojo también: parse_date()/parse_datetime() devuelven None ante un valor con
    una FORMA irreconocible, pero no ante uno con la forma correcta y un valor
    imposible (ej. "2026-02-30" o "...T25:00:00") — ahí intentan construir el
    date/datetime directo y dejan escapar el ValueError sin capturar. Se atajan
    acá para que, como dice el docstring, un valor mal formado se ignore en vez
    de tirar 500."""
    try:
        fecha = parse_date(valor)
    except ValueError:
        fecha = None
    if fecha is not None:
        hora = datetime.time.min if limite_de_dia == "inicio" else datetime.time.max
        momento = datetime.datetime.combine(fecha, hora)
    else:
        try:
            momento = parse_datetime(valor)
        except ValueError:
            momento = None
        if momento is None:
            return None
    if is_naive(momento):
        momento = make_aware(momento, get_current_timezone())
    return momento


def _filtrar_asistencias(queryset, request):
    """Filtros combinables que comparten los 3 endpoints de asistencias (lista,
    resumen y exportación) — un valor mal formado o desconocido se ignora en vez
    de romper la request; el dashboard no debería caerse por un query param raro."""
    q = request.query_params.get("q")
    if q:
        queryset = queryset.filter(
            Q(postulante__nombres__icontains=q)
            | Q(postulante__apellidos__icontains=q)
            | Q(postulante__cedula__icontains=q)
        )

    desde = request.query_params.get("desde")
    if desde:
        momento = _parsear_fecha(desde, limite_de_dia="inicio")
        if momento:
            queryset = queryset.filter(verificado_en__gte=momento)

    hasta = request.query_params.get("hasta")
    if hasta:
        momento = _parsear_fecha(hasta, limite_de_dia="fin")
        if momento:
            queryset = queryset.filter(verificado_en__lte=momento)

    metodo = request.query_params.get("metodo")
    if metodo in Asistencia.Metodo.values:
        queryset = queryset.filter(metodo=metodo)

    return queryset


class ListaAsistenciasView(generics.ListAPIView):
    """Lista en vivo del dashboard: las asistencias más recientes primero, con
    filtros opcionales (q/desde/hasta/metodo) para buscar/acotar sin perder el
    polling en vivo. El cliente hace polling cada 3-5s."""

    # IsAdminUser (is_staff), no solo IsAuthenticated: desde que los postulantes
    # también tienen cuenta propia (ver Postulante.usuario), un login válido ya no
    # alcanza para distinguir agente de postulante — is_staff sí.
    permission_classes = [IsAdminUser]
    serializer_class = AsistenciaSerializer

    def get_queryset(self):
        queryset = Asistencia.objects.select_related("postulante").order_by("-verificado_en")
        return _filtrar_asistencias(queryset, self.request)


class ResumenAsistenciasView(APIView):
    """Agregados para los gráficos del dashboard (por sede, por hora, por método),
    calculados en la base de datos — nunca trae todas las filas a Python. Mismos
    filtros que ListaAsistenciasView, para que gráficos/tabla/exportación
    muestren siempre el mismo recorte de datos."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        queryset = _filtrar_asistencias(Asistencia.objects.all(), request)

        por_sede = list(
            queryset.values("sede").annotate(total=Count("id")).order_by("-total")
        )
        por_hora = list(
            queryset.annotate(hora=TruncHour("verificado_en"))
            .values("hora")
            .annotate(total=Count("id"))
            .order_by("hora")
        )
        por_metodo = list(
            queryset.values("metodo").annotate(total=Count("id")).order_by("metodo")
        )

        return Response({"por_sede": por_sede, "por_hora": por_hora, "por_metodo": por_metodo})


_CARACTERES_FORMULA_CSV = ("=", "+", "-", "@", "\t", "\r")


def _celda_csv_segura(valor):
    """Antepone una comilla simple si el valor empieza con un caracter que
    Excel/Sheets interpreta como inicio de fórmula (CWE-1236) — nombres/apellidos
    vienen del autoregistro del postulante (texto libre), no son un dato
    confiable para escribir tal cual en un CSV que un agente puede abrir en
    Excel."""
    valor = str(valor)
    if valor.startswith(_CARACTERES_FORMULA_CSV):
        return "'" + valor
    return valor


# Tope de filas del PDF. Medido el 2026-09-28 con datos de prueba al volumen
# real de la convocatoria: weasyprint tarda ~4,8 ms por fila hasta unas 2.000
# (9,7 s), pero a 20.004 filas se degrada a 25 ms/fila — 500 s y 1,8 GB de RAM.
# Eso en producción no termina nunca: el proxy corta la request a los 30-60 s y
# el worker se queda quemando memoria, dejando sin atender a los puestos de
# verificación. Un PDF de 20.000 filas son ~400 páginas que nadie lee: para el
# volumen completo está el CSV, que sale en 1,6 s.
MAX_FILAS_PDF = 2000


class ExportarAsistenciasView(APIView):
    """Exporta TODAS las filas que matchean los filtros (no solo la página actual
    del dashboard) en CSV o PDF — mismos filtros que ListaAsistenciasView.
    El PDF está topado en MAX_FILAS_PDF filas; el CSV no tiene límite."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        formato = request.query_params.get("formato")
        if formato not in ("csv", "pdf"):
            raise ValidationError({"formato": "Debe ser 'csv' o 'pdf'."})

        queryset = _filtrar_asistencias(
            Asistencia.objects.select_related("postulante").order_by("-verificado_en"),
            request,
        )

        if formato == "csv":
            return self._csv(queryset)

        total = queryset.count()
        if total > MAX_FILAS_PDF:
            raise ValidationError(
                {
                    "formato": (
                        f"El PDF está limitado a {MAX_FILAS_PDF} filas y el filtro "
                        f"actual tiene {total}. Acotá por fecha, método o búsqueda, "
                        f"o exportá en CSV, que no tiene límite."
                    )
                }
            )
        return self._pdf(queryset)

    def _csv(self, queryset):
        # charset explícito + BOM (﻿): nombres/apellidos son texto libre del
        # autoregistro y pueden traer tildes/ñ (ej. "José Muñoz") — sin esto Excel
        # en Windows asume la codificación del sistema en vez de UTF-8 y las
        # rompe (mojibake). El BOM es el truco estándar que Excel usa para
        # detectar UTF-8 en un CSV.
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="asistencias.csv"'
        response.write("﻿")
        writer = csv.writer(response)
        writer.writerow(["Cédula", "Nombres", "Apellidos", "Sede", "Método", "Hora"])
        for asistencia in queryset:
            writer.writerow(
                [
                    _celda_csv_segura(asistencia.postulante.cedula),
                    _celda_csv_segura(asistencia.postulante.nombres),
                    _celda_csv_segura(asistencia.postulante.apellidos),
                    _celda_csv_segura(asistencia.sede),
                    asistencia.get_metodo_display(),
                    asistencia.verificado_en.strftime("%Y-%m-%d %H:%M"),
                ]
            )
        return response

    def _pdf(self, queryset):
        # Import local (no en el tope del archivo): weasyprint solo hace falta
        # para este único endpoint, no vale la pena pagar su costo de import en
        # cada arranque del server por una exportación que se usa ocasionalmente.
        from weasyprint import HTML

        html = render_to_string(
            "asistencia/reporte_asistencias.html",
            {"asistencias": queryset, "total": queryset.count()},
        )
        pdf = HTML(string=html).write_pdf()
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="asistencias.pdf"'
        return response


class ForzarAsistenciaView(APIView):
    """Override manual: un agente autenticado fuerza el paso cuando la verificación
    automática falla y se agotaron los reintentos (decisión de fallback confirmada)."""

    # Ver nota de IsAdminUser en ListaAsistenciasView — mismo motivo.
    permission_classes = [IsAdminUser]

    def post(self, request):
        cedula = request.data.get("cedula")
        sede = request.data.get("sede")
        if not cedula:
            raise ValidationError({"cedula": "Este campo es obligatorio."})
        if not sede:
            raise ValidationError({"sede": "Este campo es obligatorio."})

        try:
            postulante = Postulante.objects.get(cedula=cedula)
        except Postulante.DoesNotExist:
            raise ValidationError(
                {"cedula": "No existe un postulante registrado con esa cédula."}
            )

        # Igual que en la verificación automática: registro único, no se duplica ni se
        # pisa el método si ya había pasado (auto o manual) por otro puesto.
        asistencia, creada = Asistencia.objects.get_or_create(
            postulante=postulante,
            defaults={
                "sede": sede,
                "metodo": Asistencia.Metodo.MANUAL,
                "forzado_por": request.user,
            },
        )

        return Response(
            {
                "verificado": True,
                "ya_registrado": not creada,
                "metodo": asistencia.metodo,
                "forzado_por": asistencia.forzado_por.get_username()
                if asistencia.forzado_por
                else None,
                "postulante": PostulanteSerializer(postulante, context={"request": request}).data,
                "verificado_en": asistencia.verificado_en,
            }
        )


class TokenConRolView(TokenObtainPairView):
    """Reemplaza a TokenObtainPairView en /api/token/ — mismo endpoint, mismo
    contrato, solo agrega `is_staff` al JWT (ver TokenConRolSerializer)."""

    serializer_class = TokenConRolSerializer
    # Throttle propio (ver settings.py): sin esto no había ningún límite a los
    # intentos de contraseña contra este endpoint, compartido por agentes y postulantes.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"
