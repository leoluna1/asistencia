# Recuperación de Cuenta + Cédula/Correo Únicos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un postulante con cuenta activa que olvidó su contraseña puede recuperarla con un código por correo; uno con cuenta inactiva es dirigido a verificar su correo en su lugar; el registro rechaza cédula **y correo** duplicados con un mensaje consistente que ofrece recuperar la cuenta.

**Architecture:** Reusa `Postulante.codigo_verificacion`/`codigo_generado_en` (ya existen para la verificación de correo del registro) para el código de recuperación — son mutuamente excluyentes (verificación = cuenta inactiva, recuperación = cuenta activa), cero columnas nuevas. Dos vistas DRF nuevas calcadas de `VerificarCorreoView`/`ReenviarCodigoView`. `Postulante.correo` pasa a `unique=True` (antes no lo era — hueco real encontrado durante este plan). Frontend: página `/recuperar` nueva, mismo wizard de 2 pasos que ya usa `/registro`.

**Tech Stack:** Django REST Framework (backend), Angular standalone components + Angular Material (frontend), mismos patrones ya establecidos en el repo.

**Spec:** `docs/superpowers/specs/2026-09-29-recuperacion-cuenta-design.md`

## Global Constraints

- Sin canal WhatsApp en esta iteración — solo correo (spec, "Fuera de alcance").
- Sin recuperación para agentes/`is_staff` — solo postulantes.
- `password_nueva` usa el mismo `min_length=8` que ya exige el registro — no se agrega `AUTH_PASSWORD_VALIDATORS` nuevo.
- Sin límite de intentos fallidos por cédula además del throttle por IP ya existente — mismo criterio que `VerificarCorreoView`/`ReenviarCodigoView` (decisión del 2026-09-27).
- Ningún componente de feature de Angular (`registro`/`login`/`verificar`/`dashboard`/`mi-postulante`) tiene `.spec.ts` — `recuperar.ts` sigue ese mismo precedente, se verifica con `tsc --noEmit` + manual/curl, no con tests unitarios de Angular.
- El mensaje de cédula/correo duplicado va en `error_messages['unique']` del **campo del modelo**, no en `extra_kwargs` del serializer — DRF arma `UniqueValidator` leyendo `model_field.error_messages['unique']`, confirmado contra el código real de `rest_framework/utils/field_mapping.py`.

## Review Focus

- **Confusión entre error de cédula y de correo en la carrera de `IntegrityError`**: con dos constraints únicos ahora (`cedula`, `correo`), un `except IntegrityError` que asuma siempre "es la cédula" le devolvería al usuario un mensaje de campo equivocado justo en el caso raro que más falta hace acertar. Task 4 lo verifica forzando la carrera contra `correo`, no solo contra `cedula`.
- **`solicitar-recuperacion` para una cuenta inactiva manda un código de todos modos**: si el chequeo de `is_active` se olvida o queda mal ordenado, una cuenta que nunca verificó su correo terminaría recibiendo (y pudiendo usar) un código de "recuperación" antes de haber probado nunca que el correo es suyo — mezclaría los dos flujos que el spec pide mantener separados. Task 1 lo verifica explícitamente con `mail.outbox` vacío.
- **`restablecer-password` con una contraseña nueva corta consume el código de todos modos**: si la validación de longitud ocurre después de limpiar `codigo_verificacion`, un intento rechazado por contraseña corta dejaría a la persona sin poder reintentar con el mismo código. Task 2 lo verifica confirmando que el código sigue intacto tras un intento con contraseña corta.
- **Migración de `correo` único rota por datos ya cargados**: si en algún entorno (no en el dev actual, ya verificado sin duplicados) hay dos postulantes con el mismo correo o con `correo=''` repetido, `migrate` falla a mitad de una demo. Task 4 documenta la verificación previa y dónde repetirla en otro entorno.
- **El hint de "Recuperar cuenta" aparece para cualquier error del registro, no solo cédula/correo duplicados**: si `registro.ts` mira el mensaje genérico en vez del campo puntual (`error.cedula`/`error.correo`), un error de foto o de teléfono mostraría por error un link de recuperación que no aplica. Task 7 lo verifica con un error en otro campo (ej. `foto`) y confirma que el hint NO aparece.

---

## Task 1: `POST /api/postulantes/solicitar-recuperacion/`

**Files:**
- Modify: `backend/asistencia/views.py` (nueva vista + import de `ScopedRateThrottle` ya existente)
- Modify: `backend/asistencia/urls.py` (nueva ruta)
- Modify: `backend/core/settings.py:230-254` (`DEFAULT_THROTTLE_RATES`, nuevo scope)
- Test: `backend/asistencia/tests/test_views.py` (nueva clase `SolicitarRecuperacionViewTest`)

**Interfaces:**
- Consumes: `_generar_y_enviar_codigo_verificacion(postulante)` (ya existe en `views.py:76`), `Postulante.usuario`/`.codigo_verificacion` (ya existen).
- Produces: endpoint `POST /api/postulantes/solicitar-recuperacion/` — body `{cedula}` → `200 {"enviado": true}` o `400` con `{"cedula": [...]}`. Consumido por `PostulantesService.solicitarRecuperacion` en Task 5.

- [ ] **Step 1: Escribir los tests (fallando)**

Agregar a `backend/asistencia/tests/test_views.py`, después de la clase
`ReenviarCodigoViewTest` (línea 384):

```python
class SolicitarRecuperacionViewTest(APITestCase):
    url = "/api/postulantes/solicitar-recuperacion/"

    def setUp(self):
        self.usuario = User.objects.create_user(
            username="1710034065", password="clave-vieja-123", is_active=True
        )
        self.postulante = Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065",
            estatura_cm=175, sede="Quito", correo="juan@example.com",
            usuario=self.usuario,
        )

    def test_cuenta_activa_recibe_un_codigo_por_correo(self):
        response = self.client.post(self.url, {"cedula": "1710034065"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.postulante.refresh_from_db()
        self.assertIsNotNone(self.postulante.codigo_verificacion)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["juan@example.com"])

    def test_cuenta_inactiva_no_recibe_codigo_y_avisa_verificar_primero(self):
        self.usuario.is_active = False
        self.usuario.save()
        response = self.client.post(self.url, {"cedula": "1710034065"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("verificó su correo", response.data["cedula"][0])
        self.postulante.refresh_from_db()
        self.assertIsNone(self.postulante.codigo_verificacion)
        self.assertEqual(len(mail.outbox), 0)

    def test_cedula_inexistente_es_error_de_validacion(self):
        response = self.client.post(self.url, {"cedula": "9999999999"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(mail.outbox), 0)

    def test_postulante_precargado_sin_cuenta_es_error_de_validacion(self):
        Postulante.objects.create(
            nombres="Ana", apellidos="Lopez", cedula="0401843263", estatura_cm=160,
        )
        response = self.client.post(self.url, {"cedula": "0401843263"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(len(mail.outbox), 0)
```

- [ ] **Step 2: Correr los tests y confirmar que fallan**

Run: `cd backend && source venv/bin/activate && DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py test asistencia.tests.test_views.SolicitarRecuperacionViewTest -v 2`
Expected: `404` en vez de `200`/`400` esperados (la URL todavía no existe) —
todos los tests de esta clase fallan.

- [ ] **Step 3: Implementar la vista**

En `backend/asistencia/views.py`, agregar después de `ReenviarCodigoView`
(línea 278, antes de la línea en blanco final del archivo):

```python

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
```

- [ ] **Step 4: Wireear la ruta**

En `backend/asistencia/urls.py`, agregar `SolicitarRecuperacionView` al
import (junto a `ReenviarCodigoView`) y la ruta después de
`reenviar-codigo`:

```python
    path(
        "postulantes/solicitar-recuperacion/",
        SolicitarRecuperacionView.as_view(),
        name="solicitar-recuperacion",
    ),
```

- [ ] **Step 5: Agregar el throttle scope**

En `backend/core/settings.py`, dentro de `DEFAULT_THROTTLE_RATES` (después
de `'reenviar-codigo': '5/min',`, línea 253), agregar:

```python
        'solicitar-recuperacion': '10/min',
```

- [ ] **Step 6: Correr los tests y confirmar que pasan**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py test asistencia.tests.test_views.SolicitarRecuperacionViewTest -v 2`
Expected: 4 tests, todos `OK`.

- [ ] **Step 7: Correr la suite completa**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py test`
Expected: `Ran 127 tests ... OK` (123 existentes + 4 nuevos).

- [ ] **Step 8: Commit**

```bash
git add backend/asistencia/views.py backend/asistencia/urls.py backend/core/settings.py backend/asistencia/tests/test_views.py
git commit -m "Agrega POST /api/postulantes/solicitar-recuperacion/"
```

---

## Task 2: `POST /api/postulantes/restablecer-password/`

**Files:**
- Modify: `backend/asistencia/views.py`
- Modify: `backend/asistencia/urls.py`
- Modify: `backend/core/settings.py`
- Test: `backend/asistencia/tests/test_views.py` (nueva clase `RestablecerPasswordViewTest`)

**Interfaces:**
- Consumes: `MINUTOS_EXPIRACION_CODIGO_VERIFICACION` (ya existe, `views.py:73`), `Postulante.codigo_verificacion`/`.codigo_generado_en`/`.usuario`.
- Produces: endpoint `POST /api/postulantes/restablecer-password/` — body `{cedula, codigo, password_nueva}` → `200 {"restablecido": true}` o `400`. Consumido por `PostulantesService.restablecerPassword` en Task 5.

- [ ] **Step 1: Escribir los tests (fallando)**

Agregar a `backend/asistencia/tests/test_views.py`, después de la clase
`SolicitarRecuperacionViewTest` (Task 1):

```python
class RestablecerPasswordViewTest(APITestCase):
    url = "/api/postulantes/restablecer-password/"

    def setUp(self):
        self.usuario = User.objects.create_user(
            username="1710034065", password="clave-vieja-123", is_active=True
        )
        self.postulante = Postulante.objects.create(
            nombres="Juan", apellidos="Pérez", cedula="1710034065",
            estatura_cm=175, sede="Quito", correo="juan@example.com",
            usuario=self.usuario, codigo_verificacion="123456",
            codigo_generado_en=timezone.now(),
        )

    def test_codigo_correcto_restablece_la_contrasena(self):
        response = self.client.post(
            self.url,
            {"cedula": "1710034065", "codigo": "123456", "password_nueva": "clave-nueva-456"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.postulante.refresh_from_db()
        self.assertIsNone(self.postulante.codigo_verificacion)

        login = self.client.post(
            "/api/token/", {"username": "1710034065", "password": "clave-nueva-456"}
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK, login.data)

    def test_codigo_incorrecto_no_cambia_la_contrasena(self):
        response = self.client.post(
            self.url,
            {"cedula": "1710034065", "codigo": "000000", "password_nueva": "clave-nueva-456"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        login = self.client.post(
            "/api/token/", {"username": "1710034065", "password": "clave-vieja-123"}
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)

    def test_codigo_vencido_no_cambia_la_contrasena(self):
        self.postulante.codigo_generado_en = timezone.now() - datetime.timedelta(minutes=16)
        self.postulante.save()
        response = self.client.post(
            self.url,
            {"cedula": "1710034065", "codigo": "123456", "password_nueva": "clave-nueva-456"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_nueva_corta_es_rechazada_sin_consumir_el_codigo(self):
        response = self.client.post(
            self.url,
            {"cedula": "1710034065", "codigo": "123456", "password_nueva": "corta"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.postulante.refresh_from_db()
        self.assertEqual(self.postulante.codigo_verificacion, "123456")

    def test_cedula_inexistente_es_error_de_validacion(self):
        response = self.client.post(
            self.url,
            {"cedula": "9999999999", "codigo": "123456", "password_nueva": "clave-nueva-456"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
```

- [ ] **Step 2: Correr los tests y confirmar que fallan**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py test asistencia.tests.test_views.RestablecerPasswordViewTest -v 2`
Expected: `404` en todos (la URL todavía no existe).

- [ ] **Step 3: Implementar la vista**

En `backend/asistencia/views.py`, agregar después de
`SolicitarRecuperacionView` (Task 1):

```python

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
```

- [ ] **Step 4: Wireear la ruta**

En `backend/asistencia/urls.py`, agregar `RestablecerPasswordView` al
import y la ruta después de `solicitar-recuperacion` (Task 1):

```python
    path(
        "postulantes/restablecer-password/",
        RestablecerPasswordView.as_view(),
        name="restablecer-password",
    ),
```

- [ ] **Step 5: Agregar el throttle scope**

En `backend/core/settings.py`, después de
`'solicitar-recuperacion': '10/min',` (Task 1, Step 5):

```python
        'restablecer-password': '5/min',
```

- [ ] **Step 6: Correr los tests y confirmar que pasan**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py test asistencia.tests.test_views.RestablecerPasswordViewTest -v 2`
Expected: 6 tests, todos `OK`.

- [ ] **Step 7: Correr la suite completa**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py test`
Expected: `Ran 133 tests ... OK` (127 de Task 1 + 6 nuevos).

- [ ] **Step 8: Commit**

```bash
git add backend/asistencia/views.py backend/asistencia/urls.py backend/core/settings.py backend/asistencia/tests/test_views.py
git commit -m "Agrega POST /api/postulantes/restablecer-password/"
```

---

## Task 3: Mensaje consistente de cédula duplicada

**Files:**
- Modify: `backend/asistencia/models.py:16-18` (campo `cedula`)
- Modify: `backend/asistencia/tests/test_views.py:90-96` (fortalece `test_cedula_duplicada_es_rechazada` existente)
- Create: `backend/asistencia/migrations/00XX_alter_postulante_cedula_error_message.py` (autogenerada)

**Interfaces:**
- Produces: `Postulante.cedula` con `error_messages={"unique": "Ya existe un postulante con esta cédula."}` — el texto exacto que Task 7 (frontend) va a poder mostrar consistente sin importar qué camino del backend lo generó.

- [ ] **Step 1: Fortalecer el test existente (fallando)**

En `backend/asistencia/tests/test_views.py`, reemplazar
`test_cedula_duplicada_es_rechazada` (línea 90-96):

```python
    def test_cedula_duplicada_da_el_mismo_mensaje_en_ambos_caminos(self):
        self.client.post(self.url, self._datos(), format="multipart")
        response = self.client.post(
            self.url, self._datos(foto=_foto("rostro_real.jpg")), format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["cedula"][0], "Ya existe un postulante con esta cédula."
        )
```

- [ ] **Step 2: Correr el test y confirmar que falla**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py test asistencia.tests.test_views.RegistroPostulanteViewTest.test_cedula_duplicada_da_el_mismo_mensaje_en_ambos_caminos -v 2`
Expected: falla — el mensaje real hoy es "Ya existe postulante con este
cedula." (sin "un"/"esta"/acento).

- [ ] **Step 3: Agregar el mensaje al campo del modelo**

En `backend/asistencia/models.py`, modificar el campo `cedula` (línea
16-18):

```python
    cedula = models.CharField(
        max_length=10,
        unique=True,
        validators=[validar_cedula_ecuatoriana],
        error_messages={"unique": "Ya existe un postulante con esta cédula."},
    )
```

- [ ] **Step 4: Generar la migración**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py makemigrations asistencia`
Expected: crea una migración nueva (`AlterField` sobre `cedula`) — Django
trackea `error_messages` como parte del estado del campo aunque no cambie
nada en la base de datos real.

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py migrate`
Expected: aplica sin error (no hay cambio de esquema real).

- [ ] **Step 5: Correr el test y confirmar que pasa**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py test asistencia.tests.test_views.RegistroPostulanteViewTest.test_cedula_duplicada_da_el_mismo_mensaje_en_ambos_caminos -v 2`
Expected: `OK`.

- [ ] **Step 6: Correr la suite completa**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py test`
Expected: `Ran 133 tests ... OK` (mismo número que Task 2 — se modificó un
test existente, no se sumó uno).

- [ ] **Step 7: Commit**

```bash
git add backend/asistencia/models.py backend/asistencia/migrations/ backend/asistencia/tests/test_views.py
git commit -m "Mensaje consistente cuando la cédula ya está registrada"
```

---

## Task 4: El correo tampoco puede duplicarse

**Files:**
- Modify: `backend/asistencia/models.py:26` (campo `correo`)
- Modify: `backend/asistencia/views.py:110-129` (`RegistroPostulanteView.create`, distingue el `IntegrityError` por constraint)
- Modify: `backend/asistencia/tests/test_views.py` (tests nuevos)
- Create: `backend/asistencia/migrations/00XX_alter_postulante_correo.py` (autogenerada)

**Interfaces:**
- Produces: `Postulante.correo` único, con el mismo patrón de mensaje que `cedula` (Task 3) — `error.correo` disponible para Task 7 (frontend).

- [ ] **Step 1: Verificar que la base actual no tiene duplicados (antes de tocar nada)**

Run:
```bash
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py shell -c "
from django.db.models import Count
from asistencia.models import Postulante
dups = (Postulante.objects.exclude(correo__isnull=True).exclude(correo='')
        .values('correo').annotate(n=Count('id')).filter(n__gt=1))
print(list(dups))
"
```
Expected: `[]` (lista vacía). Si NO está vacía, resolver esos duplicados a
mano antes de seguir — `makemigrations`/`migrate` en el Step 4 fallaría.

- [ ] **Step 2: Escribir los tests (fallando)**

Agregar a `backend/asistencia/tests/test_views.py`, dentro de
`RegistroPostulanteViewTest` (después de
`test_cedula_duplicada_da_el_mismo_mensaje_en_ambos_caminos`, Task 3):

```python
    def test_correo_duplicado_es_rechazado(self):
        self.client.post(self.url, self._datos(), format="multipart")
        response = self.client.post(
            self.url,
            self._datos(cedula="0401843263", foto=_foto("rostro_real.jpg")),
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["correo"][0], "Ya existe un postulante con este correo."
        )

    def test_dos_registros_simultaneos_con_mismo_correo_da_400_no_500(self):
        # Mismo mecanismo que test_dos_registros_simultaneos_con_misma_cedula_da_400_no_500
        # (arriba), pero forzando la carrera contra el constraint de correo, no el
        # de cédula -- confirma que el except IntegrityError los distingue.
        self.client.post(self.url, self._datos(), format="multipart")
        with patch("rest_framework.validators.UniqueValidator.__call__", return_value=None):
            response = self.client.post(
                self.url,
                self._datos(cedula="0401843263", foto=_foto("rostro_real.jpg")),
                format="multipart",
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("correo", response.data)
        self.assertEqual(
            Postulante.objects.filter(correo="juan.perez@example.com").count(), 1
        )
```

- [ ] **Step 3: Correr los tests y confirmar que fallan**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py test asistencia.tests.test_views.RegistroPostulanteViewTest.test_correo_duplicado_es_rechazado asistencia.tests.test_views.RegistroPostulanteViewTest.test_dos_registros_simultaneos_con_mismo_correo_da_400_no_500 -v 2`
Expected: ambos fallan — hoy `correo` no es único, el segundo registro con
el mismo correo se crea sin error.

- [ ] **Step 4: Agregar `unique=True` al campo del modelo**

En `backend/asistencia/models.py`, modificar el campo `correo` (línea 26):

```python
    correo = models.EmailField(
        null=True,
        blank=True,
        unique=True,
        error_messages={"unique": "Ya existe un postulante con este correo."},
    )
```

- [ ] **Step 5: Generar y aplicar la migración**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py makemigrations asistencia`
Expected: crea una migración `AlterField` sobre `correo` (esta vez sí
cambia el esquema real: agrega un índice único).

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py migrate`
Expected: aplica sin error (ya se verificó en el Step 1 que no hay
duplicados).

- [ ] **Step 6: Distinguir el `IntegrityError` por constraint**

En `backend/asistencia/views.py`, en `RegistroPostulanteView.create()`
(línea 119-129), reemplazar:

```python
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
```

por:

```python
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
```

- [ ] **Step 7: Correr los tests y confirmar que pasan**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py test asistencia.tests.test_views.RegistroPostulanteViewTest -v 2`
Expected: todos `OK`, incluidos los 2 nuevos.

- [ ] **Step 8: Correr la suite completa**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py test`
Expected: `Ran 135 tests ... OK` (133 de Task 3 + 2 nuevos).

- [ ] **Step 9: Commit**

```bash
git add backend/asistencia/models.py backend/asistencia/views.py backend/asistencia/migrations/ backend/asistencia/tests/test_views.py
git commit -m "El correo tampoco puede duplicarse entre postulantes"
```

---

## Task 5: Frontend — servicio + página `/recuperar`

**Files:**
- Modify: `frontend/src/app/core/postulantes.service.ts` (2 métodos nuevos)
- Modify: `frontend/src/app/app.routes.ts` (ruta nueva)
- Create: `frontend/src/app/features/recuperar/recuperar.ts`
- Create: `frontend/src/app/features/recuperar/recuperar.html`
- Create: `frontend/src/app/features/recuperar/recuperar.scss`

**Interfaces:**
- Consumes: `POST solicitar-recuperacion`/`restablecer-password` (Tasks 1-2), `primerMensajeDeError` (`core/errores.ts`, ya existe), `soloDigitos` (`core/validators.ts`, ya existe), `InlineMessage`/`app-mensaje` (ya existe).
- Produces: ruta `/recuperar` — consumida por Task 6 (link en login) y Task 7 (link en registro).

- [ ] **Step 1: Agregar los 2 métodos al servicio**

En `frontend/src/app/core/postulantes.service.ts`, agregar al final de la
clase `PostulantesService` (después de `reenviarCodigo`, línea 83):

```typescript

  solicitarRecuperacion(cedula: string): Promise<void> {
    return firstValueFrom(
      this.http.post<void>(`${API_BASE_URL}/postulantes/solicitar-recuperacion/`, { cedula })
    );
  }

  restablecerPassword(cedula: string, codigo: string, passwordNueva: string): Promise<void> {
    return firstValueFrom(
      this.http.post<void>(`${API_BASE_URL}/postulantes/restablecer-password/`, {
        cedula,
        codigo,
        password_nueva: passwordNueva
      })
    );
  }
```

- [ ] **Step 2: Crear `recuperar.ts`**

```typescript
import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { InlineMessage } from '../../shared/inline-message/inline-message';
import { PostulantesService } from '../../core/postulantes.service';
import { primerMensajeDeError } from '../../core/errores';
import { soloDigitos } from '../../core/validators';

@Component({
  selector: 'app-recuperar',
  standalone: true,
  imports: [
    FormsModule,
    RouterLink,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressSpinnerModule,
    InlineMessage
  ],
  templateUrl: './recuperar.html',
  styleUrl: './recuperar.scss'
})
export class Recuperar {
  cedula = '';
  codigo = '';
  passwordNueva = '';

  readonly paso = signal<'cedula' | 'codigo'>('cedula');
  readonly enviando = signal(false);
  readonly error = signal<string | null>(null);
  readonly restableciendo = signal(false);
  readonly errorCodigo = signal<string | null>(null);
  readonly exito = signal(false);

  constructor(
    private postulantes: PostulantesService,
    private router: Router
  ) {}

  onCedulaInput(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.cedula = soloDigitos(input.value, 10);
    input.value = this.cedula;
  }

  async solicitarCodigo(): Promise<void> {
    if (this.cedula.length !== 10) return;
    this.enviando.set(true);
    this.error.set(null);
    try {
      await this.postulantes.solicitarRecuperacion(this.cedula);
      this.paso.set('codigo');
    } catch (e: any) {
      this.error.set(primerMensajeDeError(e?.error) || 'No se pudo enviar el código.');
    } finally {
      this.enviando.set(false);
    }
  }

  async restablecer(): Promise<void> {
    if (!this.codigo || this.passwordNueva.length < 8) return;
    this.restableciendo.set(true);
    this.errorCodigo.set(null);
    try {
      await this.postulantes.restablecerPassword(this.cedula, this.codigo, this.passwordNueva);
      this.exito.set(true);
    } catch (e: any) {
      this.errorCodigo.set(
        primerMensajeDeError(e?.error) || 'No se pudo restablecer la contraseña.'
      );
    } finally {
      this.restableciendo.set(false);
    }
  }

  irALogin(): void {
    this.router.navigate(['/login']);
  }
}
```

- [ ] **Step 3: Crear `recuperar.html`**

```html
<div class="pantalla">
  <mat-card appearance="outlined" class="tarjeta">
    <h2>Recuperar cuenta</h2>

    @if (exito()) {
      <app-mensaje tipo="ok">
        Contraseña restablecida. Ya podés ingresar con tu contraseña nueva.
      </app-mensaje>
      <button mat-flat-button color="primary" (click)="irALogin()">Ir a ingresar</button>
    } @else if (paso() === 'cedula') {
      <p class="requisito">Ingresá tu cédula para recibir un código por correo.</p>

      <mat-form-field appearance="outline">
        <mat-label>Cédula</mat-label>
        <input
          matInput
          required
          inputmode="numeric"
          [value]="cedula"
          (input)="onCedulaInput($event)"
          (keyup.enter)="solicitarCodigo()"
        />
        <mat-hint>10 dígitos, sin espacios ni guiones.</mat-hint>
      </mat-form-field>

      @if (error()) {
        <app-mensaje tipo="error">{{ error() }}</app-mensaje>
      }

      <button
        mat-flat-button
        color="primary"
        [disabled]="cedula.length !== 10 || enviando()"
        (click)="solicitarCodigo()"
      >
        @if (enviando()) {
          <mat-progress-spinner diameter="18" mode="indeterminate" />
        } @else {
          Enviar código
        }
      </button>

      <a routerLink="/login">Volver a ingresar</a>
    } @else {
      <p class="requisito">Ingresá el código de 6 dígitos y tu contraseña nueva.</p>

      <mat-form-field appearance="outline">
        <mat-label>Código</mat-label>
        <input matInput required inputmode="numeric" maxlength="6" [(ngModel)]="codigo" />
      </mat-form-field>

      <mat-form-field appearance="outline">
        <mat-label>Contraseña nueva</mat-label>
        <input
          matInput
          required
          type="password"
          [(ngModel)]="passwordNueva"
          (keyup.enter)="restablecer()"
        />
        <mat-hint>Mínimo 8 caracteres.</mat-hint>
      </mat-form-field>

      @if (errorCodigo()) {
        <app-mensaje tipo="error">{{ errorCodigo() }}</app-mensaje>
      }

      <button
        mat-flat-button
        color="primary"
        [disabled]="!codigo || passwordNueva.length < 8 || restableciendo()"
        (click)="restablecer()"
      >
        @if (restableciendo()) {
          <mat-progress-spinner diameter="18" mode="indeterminate" />
        } @else {
          Restablecer
        }
      </button>
    }
  </mat-card>
</div>
```

- [ ] **Step 4: Crear `recuperar.scss`**

```scss
// estilos específicos de recuperar (por ahora ninguno — ver .pantalla/.tarjeta
// en styles.scss, .requisito en registro.scss se copia si hace falta acá)

.requisito {
  margin: 0;
  color: var(--pne-tinta-suave);
  font-size: 0.9rem;
}
```

- [ ] **Step 5: Agregar la ruta**

En `frontend/src/app/app.routes.ts`, agregar después de la ruta `login`:

```typescript
  {
    path: 'recuperar',
    loadComponent: () => import('./features/recuperar/recuperar').then((m) => m.Recuperar)
  },
```

- [ ] **Step 6: Verificar que compila**

Run: `cd frontend && npx tsc --noEmit`
Expected: sin errores.

- [ ] **Step 7: Verificar visualmente contra el servidor real**

Con `docker compose up -d` (Postgres) + `python manage.py runserver` +
`npm start` corriendo (ver memoria del proyecto para el entorno completo),
navegar a `http://localhost:4200/recuperar` y confirmar que la pantalla
"cedula" se ve con la identidad navy/dorado del resto de la app (misma
`.pantalla`/`.tarjeta` que `/login`).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/app/core/postulantes.service.ts frontend/src/app/app.routes.ts frontend/src/app/features/recuperar/
git commit -m "Página /recuperar: pedir código y restablecer contraseña"
```

---

## Task 6: Link "¿Olvidaste tu contraseña?" en login

**Files:**
- Modify: `frontend/src/app/features/login/login.ts` (import `RouterLink`)
- Modify: `frontend/src/app/features/login/login.html`

**Interfaces:**
- Consumes: ruta `/recuperar` (Task 5).

- [ ] **Step 1: Agregar `RouterLink` a los imports del componente**

En `frontend/src/app/features/login/login.ts`, agregar el import y sumarlo
al array `imports` del `@Component`:

```typescript
import { Router, RouterLink } from '@angular/router';
```

```typescript
  imports: [
    FormsModule,
    RouterLink,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressSpinnerModule,
    InlineMessage
  ],
```

- [ ] **Step 2: Agregar el link al template**

En `frontend/src/app/features/login/login.html`, después del botón
"Ingresar" (antes de `</mat-card>`):

```html
    <a routerLink="/recuperar">¿Olvidaste tu contraseña?</a>
```

- [ ] **Step 3: Verificar que compila**

Run: `cd frontend && npx tsc --noEmit`
Expected: sin errores.

- [ ] **Step 4: Verificar visualmente**

Navegar a `http://localhost:4200/login` y confirmar que el link aparece
debajo del botón "Ingresar" y que hacer click navega a `/recuperar` (mismo
patrón ya usado en el screenshot del usuario — ver conversación).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/features/login/
git commit -m "Link '¿Olvidaste tu contraseña?' en la pantalla de login"
```

---

## Task 7: Hint de recuperación en el registro ante cédula/correo duplicado

**Files:**
- Modify: `frontend/src/app/features/registro/registro.ts`
- Modify: `frontend/src/app/features/registro/registro.html`

**Interfaces:**
- Consumes: ruta `/recuperar` (Task 5), respuesta de error de
  `POST /api/postulantes/` con `error.cedula`/`error.correo` (Tasks 3-4).

- [ ] **Step 1: Agregar `RouterLink` y un signal para detectar el caso**

En `frontend/src/app/features/registro/registro.ts`:

Agregar el import:
```typescript
import { RouterLink } from '@angular/router';
```

Sumarlo a `imports` del `@Component` (junto a `FormsModule`).

Agregar un signal nuevo junto a `readonly error = signal<string | null>(null);`
(línea 65):

```typescript
  readonly errorEsCuentaDuplicada = signal(false);
```

- [ ] **Step 2: Setear el signal en el catch de `registrar()`**

En `registrar()` (línea 142-169), reemplazar el bloque `catch`:

```typescript
    } catch (e: any) {
      this.error.set(primerMensajeDeError(e?.error) || 'No se pudo registrar al postulante.');
      return;
```

por:

```typescript
    } catch (e: any) {
      this.error.set(primerMensajeDeError(e?.error) || 'No se pudo registrar al postulante.');
      // Se mira la presencia del campo puntual en el error (no el texto del
      // mensaje, frágil): "¿ya tenés cuenta?" solo aplica cuando el motivo del
      // rechazo es justo una cédula o un correo ya registrados.
      this.errorEsCuentaDuplicada.set(!!(e?.error?.cedula || e?.error?.correo));
      return;
```

- [ ] **Step 3: Limpiar el signal al reintentar**

En `retomarFoto()` (línea 132-136), agregar la limpieza junto a
`this.error.set(null);`:

```typescript
  retomarFoto(): void {
    this.foto.set(null);
    this.fotoPreview.set(null);
    this.error.set(null);
    this.errorEsCuentaDuplicada.set(false);
  }
```

- [ ] **Step 4: Mostrar el link en el template**

En `frontend/src/app/features/registro/registro.html`, dentro del paso
`'foto'` (línea 115-117), después del bloque `@if (error())`:

```html
      @if (error()) {
        <app-mensaje tipo="error">{{ error() }}</app-mensaje>
      }
      @if (errorEsCuentaDuplicada()) {
        <a routerLink="/recuperar">¿Ya tenés cuenta? Recuperar cuenta</a>
      }
```

- [ ] **Step 5: Verificar que compila**

Run: `cd frontend && npx tsc --noEmit`
Expected: sin errores.

- [ ] **Step 6: Verificar contra el servidor real — caso positivo**

Con el backend real corriendo, completar el formulario de `/registro` con
una cédula ya registrada (ej. la que quedó de pruebas anteriores) hasta
llegar al paso de la foto y enviar — confirmar que aparece el mensaje de
error Y el link "¿Ya tenés cuenta? Recuperar cuenta" (Review Focus: no
solo el 200/400, el link visible).

- [ ] **Step 7: Verificar contra el servidor real — caso negativo (Review Focus)**

Provocar un error que NO sea de cédula/correo (ej. subir una foto sin
rostro detectable, ver `test_rechaza_foto_sin_rostro_detectable` para el
mismo caso en el backend) y confirmar que el mensaje de error aparece pero
el link "Recuperar cuenta" **no** aparece — el hint no debe mostrarse para
cualquier error del formulario.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/app/features/registro/
git commit -m "Hint de recuperación cuando el registro rechaza cédula/correo duplicado"
```

---

## Task 8: Verificación final de punta a punta

**Files:** ninguno (solo verificación manual — no hay cambios de código en esta tarea).

- [ ] **Step 1: Suite completa de backend**

Run: `cd backend && source venv/bin/activate && DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py test`
Expected: `Ran 135 tests ... OK`.

- [ ] **Step 2: Suite completa de frontend**

Run: `cd frontend && npm test -- --watch=false`
Expected: `17 passed` (sin cambios — Task 5/6/7 no agregaron `.spec.ts`,
ver Global Constraints).

Run: `npx tsc --noEmit`
Expected: sin errores.

- [ ] **Step 3: Flujo de recuperación de punta a punta contra el servidor real**

Con `docker compose up -d`, `manage.py runserver` y `npm start` corriendo:

1. En el navegador, ir a `/login`, click en "¿Olvidaste tu contraseña?" →
   confirma que llega a `/recuperar`.
2. Escribir la cédula de un postulante de prueba con cuenta **activa**
   (ver memoria del proyecto para la cédula/clave de prueba vigente) →
   "Enviar código".
3. Leer el código real desde la terminal de `manage.py runserver`
   (`EMAIL_BACKEND` sigue siendo de consola — ver conversación previa
   sobre SMTP real todavía pendiente) o consultando
   `Postulante.objects.get(cedula=...).codigo_verificacion` por
   `manage.py shell`.
4. Escribir el código y una contraseña nueva → "Restablecer" → confirma
   el mensaje de éxito.
5. Ir a `/login` y loguearse con la cédula y la contraseña **nueva** →
   confirma que entra.
6. Por Bash (no tipeado en el navegador — ver nota de seguridad de la
   sesión del 23/09 en memoria del proyecto, sigue aplicando):
   `curl -X POST http://localhost:8000/api/token/ -d "username=<cedula>&password=<password-vieja>"`
   → confirma `401` (la contraseña vieja ya no sirve).

- [ ] **Step 4: Cuenta inactiva no puede "recuperar" (Review Focus)**

Registrar un postulante nuevo (queda inactivo hasta verificar correo, sin
completar ese paso) y en `/recuperar` pedir un código con esa cédula →
confirma que el mensaje dice que hay que verificar el correo primero, y
que la terminal de `manage.py runserver` **no** imprime ningún código
nuevo (no se generó ni se mandó).

- [ ] **Step 5: Cédula y correo duplicados en el registro (Review Focus)**

En `/registro`, completar el formulario con una cédula ya registrada →
confirma mensaje + link "Recuperar cuenta". Repetir con una cédula nueva
pero un correo ya registrado → mismo resultado, mensaje de correo
duplicado + mismo link.

- [ ] **Step 6: Confirmar que ningún commit quedó suelto**

Run: `git status`
Expected: working tree limpio (todos los commits de Tasks 1-7 ya hechos).
