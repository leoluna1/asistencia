# Recuperación de cuenta por correo + mensaje de cédula duplicada

Fecha: 2026-09-29
Estado: aprobado en chat, pendiente de plan de implementación

## Contexto

El postulante ya tiene cuenta propia (`User` de Django, `username=cedula`,
creada en `RegistroPostulanteView`, ver `docs/00-REFERENCIA-PROYECTO.md` y
`project-asistencia-overview` en memoria) y ya existe un mecanismo de código
de 6 dígitos por correo para **activar** esa cuenta (`VerificarCorreoView`/
`ReenviarCodigoView`, commit `a7665c3`). Lo que no existe es una forma de
recuperarla si el postulante olvida su contraseña — el usuario lo pidió el
2026-09-29 después de ver en vivo el flujo de verificación de correo (no la
duplicidad de cédula en sí, esa parte se describió, no se mostró): hoy un
formulario de registro que recibe una cédula ya registrada devuelve
"Ya existe postulante con este cedula." (verificado contra el servidor real
el mismo día — mensaje traducido automáticamente por Django, sin acento ni
artículo) sin guiar a la persona a ningún lado.

La cédula **ya está protegida contra duplicados** (`Postulante.cedula` con
`unique=True` + `validar_cedula_ecuatoriana`) — no es un problema de
integridad de datos, es un problema de UX: no hay salida para alguien que
se topa con ese error porque ya se había registrado antes.

Decisión de canal (confirmada con el usuario): el código de recuperación
va **solo por correo** en esta iteración, reusando la infraestructura de
`_generar_y_enviar_codigo_verificacion` que ya existe. WhatsApp queda
descartado por ahora — requeriría una cuenta de WhatsApp Business, plantillas
de mensaje aprobadas por Meta y una integración nueva de punta a punta; se
reconsidera más adelante solo si en la prueba real se ve que los postulantes
no revisan su correo (el modelo ya guarda `telefono`, así que agregarlo
después no exige rediseñar nada de lo que este spec construye).

## Objetivo

1. Un postulante con cuenta **activa** que olvidó su contraseña puede
   pedir un código por correo y establecer una contraseña nueva, sin
   intervención de un agente.
2. Un postulante con cuenta **inactiva** (nunca verificó su correo) que
   intenta "recuperar" es dirigido a reenviar el código de verificación
   en su lugar — no se mezclan los dos flujos.
3. El formulario de registro, ante una cédula ya registrada, ofrece un
   camino claro ("¿Ya tenés cuenta? Recuperar cuenta") en vez del mensaje
   genérico actual.

## Fuera de alcance

- **WhatsApp como canal** — ver "Contexto" arriba, decisión ya tomada de
  no hacerlo en esta iteración.
- **Recuperación para agentes** (`is_staff`, cuentas de Django admin) —
  el pedido es específicamente sobre postulantes; un agente que pierde su
  contraseña sigue el camino que ya existía antes de este spec (un
  superusuario se la resetea desde el admin).
- **Política de contraseñas más estricta** — se mantiene el mismo
  `min_length=8` que ya usa el registro hoy; no se agrega
  `AUTH_PASSWORD_VALIDATORS` nuevo ni reglas de complejidad, para no
  introducir una regla que el propio registro no exige todavía.
- **Límite de intentos fallidos por cédula** — igual que
  `VerificarCorreoView`/`ReenviarCodigoView` (decisión ya tomada el
  2026-09-27, ver memoria del proyecto): el throttle por IP es la barrera
  real, una segunda capa sería redundante a esta escala.

## Diseño

### 1. Backend: reusar los campos existentes, no agregar columnas

`Postulante.codigo_verificacion`/`codigo_generado_en` (ya existen, usados
hoy solo por `VerificarCorreoView`) se reusan para recuperación de
contraseña. Son mutuamente excluyentes en la práctica: una cuenta con
`codigo_verificacion` pendiente de activación tiene `is_active=False`;
recuperación de contraseña solo aplica a cuentas con `is_active=True`. Nunca
compiten por el mismo campo al mismo tiempo, así que no hace falta
diferenciar "para qué era el código" en ningún lado — cero migración nueva.

### 2. Dos vistas nuevas, mismo estilo que `VerificarCorreoView`/`ReenviarCodigoView`

**`POST /api/postulantes/solicitar-recuperacion/`** — body `{cedula}`.
Público (`authentication_classes = []`, mismo motivo que el resto de
`asistencia/views.py`: un JWT viejo en el navegador no debe devolver 401
antes de llegar al permiso). Throttle scope nuevo `solicitar-recuperacion`,
10/min (igual que `verificar-correo`).

- Cédula no existe → mismo estilo de error que `ReenviarCodigoView`:
  `ValidationError({"cedula": "No existe un registro con esa cédula."})`.
  Sigue el mismo precedente de la app (los endpoints existentes ya
  revelan existencia de cédula por diseño, no es un cambio de postura de
  seguridad nuevo).
- Cédula existe pero `postulante.usuario` es `None` (precargado por CSV,
  nunca completó su registro) → mismo mensaje que ya usa
  `ReenviarCodigoView`: `ValidationError({"cedula": "No hay ningún
  registro pendiente para esta cédula."})`.
- Cuenta existe pero **inactiva** → `ValidationError({"cedula": "Esta
  cuenta todavía no verificó su correo. Pedí que te reenvíen el código de
  verificación en vez de recuperar la contraseña."})` — no genera ni manda
  ningún código; dirige al flujo correcto.
- Cuenta activa → `_generar_y_enviar_codigo_verificacion(postulante)`
  (reusada tal cual, sin cambios) y `Response({"enviado": True})`.

**`POST /api/postulantes/restablecer-password/`** — body `{cedula, codigo,
password_nueva}`. Público, throttle scope nuevo `restablecer-password`,
5/min (igual que `reenviar-codigo`).

- Misma validación de expiración (`MINUTOS_EXPIRACION_CODIGO_VERIFICACION
  = 15`, constante ya existente) y de código incorrecto que
  `VerificarCorreoView`, calcada.
- `password_nueva`: mismo `min_length=8` que ya exige
  `PostulanteSerializer.password` en el registro — se valida a mano en la
  vista (`if len(password_nueva) < 8: raise ValidationError(...)`), no
  hace falta un serializer nuevo para un solo campo.
- Al acertar: `usuario.set_password(password_nueva)` +
  `usuario.save(update_fields=["password"])`, limpia
  `codigo_verificacion`/`codigo_generado_en` (mismo patrón que
  `VerificarCorreoView`), `Response({"restablecido": True})`.

### 3. Mensaje de cédula duplicada en el registro (backend)

Hoy, una cédula duplicada en `RegistroPostulanteView.create()` puede llegar
por dos caminos con dos textos distintos (verificado contra el servidor
real el 2026-09-29): el `UniqueValidator` automático de DRF, que devuelve
"Ya existe postulante con este cedula." (traducción automática de Django,
sin acento y sin artículo — no es el error en inglés que se asumió antes de
verificarlo, pero sigue siendo un texto descuidado) si el serializer la
rechaza antes del INSERT; o el `except IntegrityError` ya existente (línea
129 de `views.py`), que devuelve "Ya existe un postulante con esta
cédula." — mejor redactado, pero un texto distinto para el mismo caso. Se
homogeniza el primer camino agregando `error_messages={'unique': 'Ya existe
un postulante con esta cédula.'}` al campo `cedula` en
`PostulanteSerializer` para que ambos caminos devuelvan exactamente el
mismo texto — el frontend (punto 6) no distingue por texto, pero igual
conviene que un humano leyendo la respuesta vea un mensaje consistente.

### 4. Frontend: nueva página `/recuperar`

Mismo patrón de wizard de 2 pasos que ya usa `/registro`
(`features/recuperar/recuperar.ts/html/scss`, standalone component):

1. **Paso "cedula"**: input de cédula (mismo filtro/validación módulo-10
   que ya vive en `core/validators.ts`) + botón "Enviar código". Al
   confirmar, llama `POST solicitar-recuperacion` y pasa a paso "codigo".
2. **Paso "codigo"**: input de código (6 dígitos, mismo estilo que el paso
   de verificación de `registro.ts`) + input de contraseña nueva + botón
   "Restablecer" + link "Reenviar código" (reusa
   `PostulantesService.reenviarCodigo` — mismo endpoint que ya usa el
   registro, funciona igual para una cuenta activa). Al confirmar, llama
   `POST restablecer-password` y en éxito navega a `/login` con un mensaje
   de éxito (mismo patrón que ya usa `registro.ts` al final del alta).

Nueva ruta en `app.routes.ts`: `{ path: 'recuperar', loadComponent: ... }`,
junto a `registro`/`login` (sin guard, es pública).

`PostulantesService` (`core/postulantes.service.ts`) suma 2 métodos:
`solicitarRecuperacion(cedula: string): Promise<void>` y
`restablecerPassword(cedula: string, codigo: string, passwordNueva:
string): Promise<void>` — mismo estilo que `verificarCorreo`/
`reenviarCodigo` ya existentes.

### 5. Frontend: link "¿Olvidaste tu contraseña?" en login

`login.html` suma un link a `/recuperar` debajo del botón "Ingresar" (mismo
estilo `routerLink` que ya usa el nav global).

### 6. Frontend: hint de recuperación en el registro ante cédula duplicada

En `registro.ts`, el catch que hoy hace
`this.error.set(primerMensajeDeError(e?.error) || 'No se pudo registrar al
postulante.')` se extiende: si la respuesta trae específicamente
`e?.error?.cedula` (no cualquier otro campo), además del mensaje se
muestra un link a `/recuperar` — "¿Ya tenés cuenta con esta cédula?
Recuperar cuenta". Se mira la presencia del campo `cedula` en el error, no
el texto del mensaje (parsear texto es frágil y ya se evitó ese patrón en
`mensajeDeErrorDeBlob`, ver commit `0cd0286`).

## Verificación

- Tests backend nuevos (TDD, mismo estilo que `test_views.py` ya tiene
  para `VerificarCorreoView`/`ReenviarCodigoView`): cuenta activa pide
  recuperación → código generado y enviado (`django.core.mail.outbox`, ya
  el patrón que usan los tests existentes de esas dos vistas — ver
  `test_views.py:74-77`); cuenta inactiva pide
  recuperación → error dirigiendo a verificación, sin generar código;
  cédula inexistente → error; código correcto restablece y permite login
  con la contraseña nueva (`POST /api/token/` con la nueva contraseña);
  código incorrecto/expirado → rechazado, contraseña vieja sigue
  funcionando.
- Los 123 tests backend existentes no deben romperse.
- Frontend: `ng test` (17 tests existentes) sigue en verde. Ningún
  componente de feature (`registro`/`login`/`verificar`/`dashboard`/
  `mi-postulante`) tiene `.spec.ts` hoy — solo lo tienen módulos de lógica
  pura (`core/errores.ts`, `core/filtros-asistencia.ts`,
  `core/resumen-charts.ts`) y un componente compartido
  (`inline-message`) — así que `recuperar.ts` sigue ese mismo precedente:
  sin test unitario, verificado con `tsc --noEmit` + Playwright/manual
  contra el servidor real, igual que se verificó `registro`/`verificar`.
- Probado de punta a punta contra el servidor real corriendo (no solo
  tests), igual que se hizo con la verificación de correo el 27/09:
  registro con cédula ya usada → ver el link de recuperación → pedir
  código → código real leído de la BD o del backend de consola (sigue
  `EMAIL_BACKEND` de consola hasta que haya SMTP real, ver conversación
  previa) → restablecer → login con la contraseña nueva.
