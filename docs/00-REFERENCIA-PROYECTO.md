# Referencia del proyecto — SC20260826001 (asistencia)

Documento de referencia generado a partir de todo lo que existía en la carpeta al 2026-09-03.
No reemplaza al plan paso a paso (`PLAN-PASO-A-PASO.md`), que todavía no existe — sirve como
punto de partida para escribirlo.

## Qué es el proyecto

Sistema de verificación de identidad para postulantes de la Policía Nacional del Ecuador
(código interno `SECURE_CODE`, referencia `SC20260826001`).

## Objetivo (aclarado por el cliente, 2026-09-03)

Hoy, el ingreso de un postulante a rendir una prueba es 100% manual: un agente de policía le
pide las reglas en papel, lo busca en hojas físicas, lo hace firmar, y recién ahí lo deja pasar
a la prueba. Este sistema tiene que **eliminar todo ese proceso manual** reemplazándolo por
verificación facial.

### Flujo objetivo

1. **Registro previo** (antes del día de la prueba): el postulante se registra en el sistema
   con foto (rostro), nombres, apellidos, cédula, estatura, entre otros datos por definir.
2. **Día de la prueba**: el postulante se sienta frente a un computador con una cámara de alta
   resolución. El sistema lo verifica contra la foto ya registrada en máximo ~2 segundos y, si
   coincide, lo deja pasar directo a rendir la prueba — sin papel, sin firma, sin búsqueda manual.
3. **Dashboard de asistencia**: los agentes de policía necesitan un panel para ver en tiempo
   real quién ya se verificó/ingresó y quién falta.

### Roles

- **Postulante**: se registra previamente (foto + datos personales) y el día de la prueba solo
  se sienta a verificarse.
- **Agente/administrador**: supervisa el proceso desde el dashboard; probablemente también
  gestiona o valida el registro previo de postulantes.

### Alcance confirmado: solo asistencia (2026-09-03)

El sistema **no hace nada más que esto**: registro previo del postulante (foto + datos) →
en cada prueba que le toque rendir, se sienta, el reconocimiento facial lo identifica entre los
registrados (1:N) y marca su asistencia → pasa. No califica examen, no gestiona otros trámites.

### Decisiones de diseño (confirmadas con el cliente, 2026-09-03)

1. **Fallback ante falla de verificación**: reintento automático (2-3 intentos, reacomodar
   luz/posición) y si sigue fallando, escala a un agente en sitio que verifica manualmente y
   fuerza el paso. Implica: la UI de verificación necesita un estado "escalar a agente" y el
   backend necesita un endpoint de "marcar asistencia manual" auditable (quién la forzó, cuándo).
2. **Modelo de asistencia**: registro único de "entró", no por prueba específica. Un postulante
   tiene una sola marca de asistencia aunque esté citado a más de una prueba/fecha — más simple:
   no hace falta modelar "prueba" como entidad separada de la asistencia en sí.
3. **Escala**: varias sedes simultáneas el día de la prueba, cada una con sus propios puestos de
   verificación, todas reportando al mismo dashboard central. Implica: el modelo de datos
   necesita campo `sede` desde el inicio (no se puede asumir sede única), y el backend central
   debe soportar escrituras concurrentes desde varias ubicaciones — con la escala esperada
   (cientos/miles de posturas, no millones de requests/segundo) esto no necesita nada especial
   más allá de Postgres + Django normales, solo no olvidar el campo `sede` en el modelo.
4. **Dashboard**: lista en vivo simple (nombre, foto, hora de verificación, estado) — es el MVP,
   sin filtros avanzados ni exportación todavía. Con polling cada 3-5s alcanza (ver "Qué NO
   agregar todavía": nada de websockets/Channels hasta que polling se sienta lento).
5. **Retención de datos biométricos**: **pendiente de definición legal** — el cliente no tiene
   todavía una política de cuánto tiempo se conservan foto/cédula/embedding tras cerrado el
   proceso de reclutamiento. Se construye el sistema igual, pero **antes de ir a producción**
   hay que resolver esto con el área legal (dato sensible en un proceso estatal) y dejar el
   borrado/anonimización como una tarea de mantenimiento, no como bloqueante del desarrollo.

## Stack definido en el README

| Capa | Tecnología |
| --- | --- |
| Frontend | Angular |
| Backend | Python (Django + Django REST Framework) |
| Reconocimiento facial | InsightFace, invocado en proceso desde Django (sin microservicio aparte) — **corregido, ver sección "Investigación profunda"**: el modelo preentrenado de InsightFace no tiene licencia comercial, se reemplaza por `deepface`+`SFace`/`Dlib` |
| Base de datos | PostgreSQL |
| Hosting | DigitalOcean o Hetzner (**no AWS**) |

## Infraestructura ya existente

- `docker-compose.yml` levanta un Postgres local:
  - contenedor `sc-pne-postgres`, imagen `postgres:16-alpine`
  - DB `sc_pne`, usuario `sc_pne`, password `sc_pne_local` (solo local, no usar en producción)
  - expuesto en `localhost:5434`
- `.gitignore` ya contempla Node/Angular (`node_modules`, `dist`, `.angular`) y Python/Django
  (`venv`, `__pycache__`, `staticfiles`), más `.env*`.

## Flujo de trabajo previsto (según README)

Ramas: `feature/...` → `DEVOPS` (integración diaria) → `TEST` (QA/demo) → `PRODU` (producción).
Regla: nunca trabajar directo en `PRODU`.

## Vacíos / pendientes detectados

Esto es lo que falta antes de poder ejecutar el flujo que describe el propio README:

1. **La carpeta no es un repositorio git todavía** — no hay `.git`. Hay que inicializarlo y crear
   las ramas `DEVOPS`, `TEST`, `PRODU` antes de poder seguir el flujo descrito.
2. **`docs/PLAN-PASO-A-PASO.md` no existe** — el README lo señala como el primer paso a leer.
3. **`docs/CHECKLIST-DIA-1.md` no existe** — segundo paso señalado por el README.
4. No hay todavía estructura de proyecto Angular ni Django (no hay `package.json`,
   `manage.py`, `requirements.txt`, etc.) — el repo está en estado de scaffold puro.
5. El objetivo funcional ya está claro (ver sección "Objetivo" arriba), pero quedan preguntas
   abiertas de diseño (flujo de respaldo ante fallo de verificación, alcance del dashboard,
   retención de datos biométricos, concurrencia por sede).

## Stack técnico completo (investigación, 2026-09-03)

Ninguna versión anotada aquí es time-sensitive — son librerías maduras. Filtrado con criterio
ponytail: solo lo que la escala real de este proyecto (una prueba, pocas sedes, cientos/miles de
postulantes) necesita, no lo que "podría hacer falta algún día".

### Identificación: 1:N confirmado (2026-09-03)

El cliente confirmó que el sistema **solo hace asistencia, nada más**: el postulante se sienta,
el reconocimiento facial lo identifica y marca su asistencia, sin ningún paso previo de ingresar
cédula/QR. Es **1:N puro** — el rostro busca su coincidencia entre todos los postulantes
registrados para esa prueba, no contra un identificador dado por el postulante.

Con la escala esperada (una prueba, cientos/pocos miles de postulantes registrados), 1:N con
numpy vectorizado sigue siendo rápido (milisegundos) — no cambia la recomendación de evitar
`pgvector` por ahora (ver sección de base de datos). Si en el futuro el volumen de postulantes
crece mucho, ahí sí se mide y se agrega índice vectorial.

### Backend
- Django + Django REST Framework (ya decidido).
- `django-environ` — leer `.env` (ya contemplado en `.gitignore`).
- `Pillow` — validar/redimensionar la foto antes de pasarla a InsightFace.
- `djangorestframework-simplejwt` — auth del dashboard, si Angular corre en dominio/puerto
  distinto en producción (lo normal para una SPA separada del backend).
- `gunicorn` detrás de `nginx` como servidor de aplicación.
- `whitenoise` — sirve estáticos del admin de Django sin configurar nginx aparte para eso.

### Reconocimiento facial — CORREGIDO (ver hallazgo de licencia más abajo)
- ~~`insightface` con modelo `buffalo_l`~~ — **retirado**, ver "Hallazgo crítico" abajo.
- `deepface` (Python, MIT) como wrapper, con `model_name="SFace"` (Apache 2.0) o `"Dlib"`
  (dominio público) y `detector_backend="yunet"` (Apache 2.0) — pipeline 100% libre de
  restricciones comerciales.
- `onnxruntime` (CPU) — no hace falta GPU para uno o pocos computadores verificando en paralelo;
  cada verificación en CPU moderna toma ~100–300ms.
- Comparación de embeddings: distancia coseno con `numpy` — no necesita librería extra.
- `Silent-Face-Anti-Spoofing` (MiniVision, Apache 2.0) — detección de vida, ver sección
  "Anti-spoofing" abajo.

### Base de datos
- PostgreSQL (ya decidido).
- Embedding facial: `ArrayField(FloatField())` de Django (nativo de Postgres). Con cientos o
  pocos miles de postulantes, comparar contra todos con numpy vectorizado toma milisegundos —
  **no** instalar `pgvector` todavía; solo si el volumen crece a decenas de miles y esa
  comparación se mide como cuello de botella real.
- Fotos: `ImageField`, disco local en dev; `django-storages` + DigitalOcean Spaces o Hetzner
  Object Storage (S3-compatible) en producción.

### Frontend
- Angular (ya decidido) + `HttpClient` nativo.
- Captura de cámara: API nativa del navegador `getUserMedia` + `<video>`/`<canvas>` para el
  frame — cero librerías de terceros.
- UI: Angular Material — cubre tablas de dashboard y formularios de registro sin sumar una
  segunda librería de componentes (PrimeNG, ng-bootstrap, etc.).
- Estado: servicios + RxJS (ya viene con Angular). Nada de NgRx para 2–3 pantallas (registro,
  verificación, dashboard).
- Gráficas: `ngx-charts` solo si el dashboard pide gráficos además de una tabla en vivo.

### Infraestructura / deploy
- Docker + docker-compose (ya iniciado).
- Nginx: sirve el build estático de Angular y hace proxy a Gunicorn para `/api`.
- TLS vía Let's Encrypt/Certbot (o el proxy gestionado del hosting).
- DigitalOcean o Hetzner (ya decidido, sin AWS) — un droplet/CX normal alcanza; no hace falta
  GPU, ni con el modelo anterior ni con el nuevo, a esta escala.
- Backups: `pg_dump` programado (cron) o snapshot del proveedor.

### Hardware (no es software, pero es parte del requerimiento)
- Cámara web ≥1080p con autoenfoque (ej. Logitech C920/Brio) por cada puesto de verificación —
  la nitidez de la imagen pesa más en la precisión del matching que el modelo de IA elegido.

### Qué NO agregar todavía
`pgvector`, Celery + Redis, Django Channels/websockets, microservicio de IA aparte, NgRx,
Kubernetes, segunda librería de componentes UI. Cada uno se agrega solo cuando una medición real
—no una suposición— diga que hace falta.

## Investigación profunda: licencias, anti-spoofing y hosting (2026-09-03)

Verificado con fuentes actuales (no solo memoria) porque tiene implicaciones legales para un
sistema estatal. Fuentes al final del documento.

### Hallazgo crítico: InsightFace no se puede usar así en producción

El **código** de InsightFace es MIT (libre). Pero los **modelos preentrenados** del model zoo
(`buffalo_l`, `buffalo_s`, `antelopev2`, etc. — los que el README daba por hecho usar) están
licenciados **solo para investigación no comercial**. Usarlos en un sistema pagado/estatal en
producción sin comprarles licencia comercial (contacto: `recognition-oss-pack@insightface.ai`)
es un incumplimiento de licencia, no un detalle menor.

**Corrección al stack**: se retira `insightface` como dependencia por defecto. En su lugar:

1. **`deepface`** (MIT) como wrapper de todo el pipeline (detectar → alinear → generar
   embedding → comparar), con:
2. **Modelo de reconocimiento** `SFace` (Apache 2.0, MobileFaceNet vía OpenCV Zoo, liviano y
   pensado para tiempo real) o `Dlib` (modelo ResNet de dlib, **dominio público**, 99.38% en el
   benchmark LFW, usado en producción hace 8+ años vía la librería `face_recognition`).
3. **Detector** `yunet` (Apache 2.0, de OpenCV).

Para este caso de uso (sujeto cooperando, sentado de frente, buena luz, pool de cientos/miles de
candidatos, no millones) cualquiera de los dos modelos rinde de sobra — no hace falta el modelo
"más preciso del mercado a nivel de investigación", hace falta uno sin riesgo legal que funcione
bien en cámara controlada. Todo lo demás de la investigación anterior (Django, Angular,
PostgreSQL sin pgvector, docker-compose) no cambia.

### Por qué tampoco sirve "usar una API de nube y ya"

Microsoft **prohíbe explícitamente** el uso de Azure Face API (identificación/verificación) para
departamentos de policía desde 2020 — está baneado por política aunque se pague, y el resto de
funciones de identificación quedan detrás de un proceso de aprobación ("Limited Access"). Esto,
sumado a que el README ya descarta AWS, confirma que un modelo open-source corriendo en el propio
servidor (el plan original) es la única opción viable — no hay atajo de API de nube para este
caso de uso.

### Anti-spoofing / detección de vida — pieza nueva, no contemplada antes

Riesgo real y específico de este sistema: un postulante podría intentar marcar la asistencia de
otra persona mostrando una foto o video de esa persona en vez de su propio rostro — grave en un
proceso de reclutamiento policial. La investigación anterior no cubría esto.

- **`Silent-Face-Anti-Spoofing`** (MiniVision, Apache 2.0) — modelo liviano (MiniFASNet) que
  distingue rostro real de foto/pantalla, corre en CPU, mismo estilo de integración que el
  reconocimiento (invocado en proceso desde Django).
- Alternativa sin modelo adicional (más ponytail): pedir un microgesto durante los 2 segundos
  (parpadeo/leve giro) y verificarlo con landmarks de MediaPipe FaceMesh — pero es menos robusto.
- Recomendado: usar el modelo dedicado. Este es de los pocos casos donde la dependencia extra sí
  se justifica — un falso positivo (dejar pasar una foto) es inaceptable en un examen de policía,
  no es una feature especulativa.

### Hosting con cifras reales

- Hetzner es 3–5× más barato en cómputo puro que proveedores con sede en EE.UU. (ej. 4GB/2vCPU:
  ~US$4.50/mes en Hetzner vs ~US$24/mes en un equivalente de DigitalOcean).
- Postgres gestionado en DigitalOcean arranca en ~US$15/mes; Hetzner no tiene oferta equivalente
  de Postgres gestionado. Para este proyecto (una sola instancia, tráfico bajo, ya se planeaba
  Postgres propio vía docker-compose) no hace falta base de datos gestionada — `pg_dump` + cron
  alcanza, ya estaba contemplado.
- **Recomendación**: Hetzner por costo — un solo servidor con Docker (Postgres + Django + nginx
  sirviendo Angular), sin base de datos gestionada ni GPU.

### Fuentes
- [Enterprise Face Recognition Model Licensing | InsightFace](https://www.insightface.ai/solutions/face-recognition-licensing)
- [Can buffalo_* models be used in production application? · Issue #2486 · deepinsight/insightface](https://github.com/deepinsight/insightface/issues/2486)
- [insightface/python-package/README.md · deepinsight/insightface](https://github.com/deepinsight/insightface/blob/master/python-package/README.md)
- [ageitgey/face_recognition](https://github.com/ageitgey/face_recognition) y [dlib face recognition (blog.dlib.net)](http://blog.dlib.net/2017/02/high-quality-face-recognition-with-deep.html)
- [opencv/face_recognition_sface · Hugging Face](https://huggingface.co/opencv/face_recognition_sface)
- [serengil/deepface · GitHub](https://github.com/serengil/deepface)
- [minivision-ai/Silent-Face-Anti-Spoofing · GitHub](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing)
- [Limited Access features of Face | Microsoft Learn](https://learn.microsoft.com/en-us/legal/cognitive-services/computer-vision/limited-access-identity)
- [Microsoft Strengthens Ban on Police Use of Azure AI for Facial Recognition - ID Tech](https://idtechwire.com/microsoft-strengthens-ban-on-police-use-of-azure-ai-for-facial-recognition/)
- [Cloud VPS Cost Comparison 2026: Hetzner vs Vultr vs DigitalOcean](https://apicalculators.com/blog/cloud-vps-cost-comparison-2026)
- [DigitalOcean Managed PostgreSQL: Pricing, Features & When to Use It in 2026](https://infratally.com/articles/digitalocean-managed-postgres-deep-dive.html)

## Próximos pasos sugeridos

- Confirmar el alcance funcional real de "asistencia" (lista de preguntas arriba).
- Inicializar el repo git y las 3 ramas.
- Escribir `docs/PLAN-PASO-A-PASO.md` con las fases del proyecto.
- Escribir `docs/CHECKLIST-DIA-1.md` con las tareas concretas de arranque (crear proyecto
  Django, crear proyecto Angular, conectar a Postgres vía docker-compose, etc.).
