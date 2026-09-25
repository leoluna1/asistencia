import csv
import datetime

import cv2
import numpy as np
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncHour
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.timezone import get_current_timezone, is_naive, make_aware
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from .facial import (
    UMBRAL_COINCIDENCIA,
    RostroNoDetectado,
    calcular_embedding,
    detectar_rostro,
    es_rostro_real,
    mejor_coincidencia,
    validar_calidad_registro,
)
from .models import Asistencia, FotoPostulante, Postulante
from .serializers import (
    AsistenciaSerializer,
    FotoPostulanteSerializer,
    MiPostulanteSerializer,
    PostulanteSerializer,
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
        except IntegrityError:
            # Dos registros casi simultáneos con la misma cédula nueva (ej. doble
            # envío por conexión inestable en el kiosco) pueden pasar ambos la
            # validación del serializer (el UniqueValidator consulta la BD antes de
            # que ninguno haga commit) — el segundo INSERT choca acá. Se traduce al
            # mismo 400 que ya devuelve una cédula duplicada detectada a tiempo, en
            # vez de un 500 sin capturar.
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
        if usuario is None:
            usuario = User.objects.create_user(
                username=postulante.cedula, password=serializer.validated_data["password"]
            )
        serializer.save(embedding=embedding, usuario=usuario)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        embedding = _procesar_foto_de_registro(self.request.FILES["foto"])
        # username = cédula: el postulante se loguea después (/api/token/, mismo
        # endpoint JWT que ya usan los agentes) para revisar/corregir sus datos
        # antes del día de la prueba (ver MiPostulanteView).
        usuario = User.objects.create_user(
            username=serializer.validated_data["cedula"],
            password=serializer.validated_data["password"],
        )
        serializer.save(embedding=embedding, usuario=usuario)


class ProbarEncuadreView(APIView):
    """Chequeo en vivo, sin guardar nada: la cámara del registro manda un frame cada
    ~1s mientras el postulante se acomoda, y esto le dice si ya está bien encuadrado
    o qué corregir. Reusa la MISMA validar_calidad_registro que corre en el registro
    real (ver _procesar_foto_de_registro) — el aviso en vivo y el rechazo final nunca
    se contradicen."""

    # Público (ver nota en RegistroPostulanteView: evita 401 por un token viejo).
    authentication_classes = []

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

        # Candidatos: la foto principal de cada postulante + cualquier ángulo adicional
        # (FotoPostulante) — mejor_coincidencia ya trabaja sobre una lista plana de
        # (id, embedding), no necesita saber que dos filas son la misma persona.
        candidatos = list(
            Postulante.objects.exclude(embedding__isnull=True).values_list("id", "embedding")
        ) + list(FotoPostulante.objects.values_list("postulante_id", "embedding"))
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
    completo, así que sirve para distinguir los dos casos de forma confiable."""
    fecha = parse_date(valor)
    if fecha is not None:
        hora = datetime.time.min if limite_de_dia == "inicio" else datetime.time.max
        momento = datetime.datetime.combine(fecha, hora)
    else:
        momento = parse_datetime(valor)
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


class ExportarAsistenciasView(APIView):
    """Exporta TODAS las filas que matchean los filtros (no solo la página actual
    del dashboard) en CSV o PDF — mismos filtros que ListaAsistenciasView."""

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
        return self._pdf(queryset)

    def _csv(self, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="asistencias.csv"'
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
