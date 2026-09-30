# Despliegue de Producción (Docker/nginx/gunicorn) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dejar en el repo los artefactos de despliegue de producción (Dockerfiles de backend/frontend, `docker-compose.prod.yml`, config de nginx, backups, guía) para que, cuando exista un servidor Hetzner/DO real, levantar producción sea `git clone` + `.env` real + `docker compose up -d`.

**Architecture:** Un solo `docker-compose.prod.yml` con 4 servicios: `postgres` (fuente de verdad), `backend` (Django/DRF vía gunicorn con workers `gthread`, respetando el lock de concurrencia de `facial.py`), `nginx` (sirve el build de Angular, proxya `/api`/`/admin`/`/static` a gunicorn, sirve `/media` directo desde un volumen compartido) y `certbot` (perfil opcional, no arranca por defecto). Nada de esto toca `docker-compose.yml` de dev.

**Tech Stack:** Docker, docker-compose, nginx, gunicorn (worker class `gthread`), whitenoise, Python 3.12, Node 22 (build de Angular).

**Spec:** `docs/superpowers/specs/2026-09-29-despliegue-produccion-design.md`

## Global Constraints

- Sin aprovisionar servidor real, sin TLS real, sin credenciales S3/SMTP reales — todo queda documentado/parametrizado, no probado contra un proveedor real (spec, sección "Fuera de alcance").
- `docker-compose.prod.yml` es un archivo nuevo; no modifica `docker-compose.yml` de dev.
- Hosting objetivo: Hetzner o DigitalOcean, **no AWS** (`docs/00-REFERENCIA-PROYECTO.md`).
- Nada de Kubernetes, Celery+Redis, microservicio de IA aparte, ni base de datos gestionada — un solo servidor con Docker (`docs/00-REFERENCIA-PROYECTO.md`, "Qué NO agregar todavía").
- gunicorn debe usar `--worker-class gthread` (no `sync`, no `gevent`): el lock de `asistencia/facial.py::_lock_modelos` (commit `bff15c1`) serializa el pipeline ONNX **dentro de un proceso multi-hilo** — con workers `sync` de un solo hilo el lock es inofensivo pero innecesario; con `gthread` es indispensable para no repetir el bug de concurrencia ya encontrado.
- No se agrega CI/CD ni contenedor cron aparte — el backup se agenda con `cron` del host invocando `docker compose exec`.

## Review Focus

- **Manifest de whitenoise generado con el storage equivocado**: si `collectstatic` corre en el build de la imagen (DEBUG=True por defecto, sin `.env`), el manifest no usa `CompressedManifestStaticFilesStorage`, y en runtime (DEBUG=False) whitenoise busca un manifest que no coincide → 500 al pedir cualquier estático del admin. El entrypoint debe correr `collectstatic` en el arranque del contenedor (con las env vars reales ya cargadas), no en el `Dockerfile`. Task 2 lo verifica explícitamente.
- **`.env.production.example` silenciosamente ignorado por git**: el `.gitignore` raíz tiene `.env.*` sin una excepción para este nombre (solo existe `!.env.example`) — si no se agrega la excepción, el archivo queda sin trackear y parece "creado" pero nunca se comitea. Task 4 lo verifica con `git status`/`git add -n`.
- **`ALLOWED_HOSTS`/`Host` header rotos entre nginx y Django**: nginx reenvía `Host: $host` tal cual llega; si el `.env` de prueba no incluye ese mismo host en `DJANGO_ALLOWED_HOSTS`, Django devuelve 400 "Invalid HTTP_HOST header" en vez de servir la página — fácil de confundir con "nginx no conecta". Task 4 lo verifica con curl real contra `localhost`.
- **Ruta de `/media/` inconsistente entre nginx y Django**: `MEDIA_URL = 'media/'` genera URLs `/media/<archivo>`; el bloque `location /media/ { alias /media_files/; }` de nginx tiene que apuntar exactamente al mismo volumen que monta el backend en `/app/media`, con la barra final correcta (un alias mal armado sirve 404 para toda foto aunque el resto del sitio funcione). Task 4 lo verifica subiendo/leyendo un archivo de prueba a través del volumen.
- **Rotación de backups que borra de más o de menos**: `find -mtime +N -delete` es fácil de escribir con un signo invertido o una unidad equivocada y borrar backups recientes (o no borrar nunca los viejos) sin que ningún error lo avise. Task 5 lo verifica creando un archivo con fecha vieja simulada y confirmando que SOLO ese se borra.

---

## Task 1: Settings de producción en Django (whitenoise + STATIC_ROOT + seguridad) y dependencias nuevas

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/core/settings.py:44` (nuevo bloque de seguridad después de `ALLOWED_HOSTS`)
- Modify: `backend/core/settings.py:62-71` (`MIDDLEWARE`)
- Modify: `backend/core/settings.py:147` (bloque de `STATIC_URL`)

**Interfaces:**
- Produces: `STATIC_ROOT` (usado por `collectstatic` en Task 2), variables de entorno nuevas `CSRF_TRUSTED_ORIGINS`, `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` (documentadas en `.env.production.example`, Task 4).

- [ ] **Step 1: Agregar `gunicorn` y `whitenoise` a `requirements.txt`**

Editar `backend/requirements.txt`, agregando al final:

```
gunicorn  # servidor WSGI de producción (ver docs/DESPLIEGUE-PRODUCCION.md)
whitenoise  # sirve los estáticos del admin de Django sin configurar nginx aparte
```

- [ ] **Step 2: Instalar y verificar que no rompen nada**

Run: `cd backend && source venv/bin/activate && pip install -r requirements.txt`
Expected: instala `gunicorn` y `whitenoise` sin conflictos de versión.

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py test`
Expected: `Ran 123 tests ... OK` (agregar las dos dependencias no debe romper nada; `DEBUG=True` en tests, así que el bloque `if not DEBUG` de Step 4 no se activa todavía).

- [ ] **Step 3: Agregar el bloque de seguridad para producción**

En `backend/core/settings.py`, inmediatamente después de la línea
`ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])` (línea 44),
agregar:

```python

# Cabeceras/cookies seguras cuando corre detrás de nginx (ver
# docs/DESPLIEGUE-PRODUCCION.md). En DEBUG=True (dev) los defaults no
# cambian nada de lo que ya funciona hoy.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
# False hasta que exista un certificado real y se active el bloque HTTPS de
# frontend/nginx.conf -- activarlo antes tumbaría el sitio (redirige a un
# HTTPS que todavía no existe).
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=False)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=False)
```

- [ ] **Step 4: Agregar whitenoise al middleware y el storage de estáticos**

En `backend/core/settings.py`, modificar `MIDDLEWARE` (línea 62) insertando
whitenoise inmediatamente después de `SecurityMiddleware` (posición exigida
por whitenoise):

```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
```

Después, en el bloque de "Static files" (línea 147, después de
`STATIC_URL = 'static/'`), agregar:

```python
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Manifest con hash de contenido + gzip, servido por whitenoise sin nginx
# aparte. Solo en producción: en dev (DEBUG=True) collectstatic ni se corre,
# así que dejar el storage default ahí evita un manifest a medio generar.
if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
```

- [ ] **Step 5: Verificar que dev sigue intacto y que el modo producción no rompe el arranque**

Run: `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py test`
Expected: `Ran 123 tests ... OK` (sigue en verde; `DEBUG=True` en tests no
activa el `STATICFILES_STORAGE` nuevo).

Run:
```bash
DJANGO_DEBUG=False DJANGO_SECRET_KEY=verificacion-temporal-no-usar-en-real \
DJANGO_ALLOWED_HOSTS=localhost \
DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib python manage.py check
```
Expected: `System check identified no issues (0 silenced).` (confirma que el
bloque de seguridad nuevo no rompe `manage.py check` en modo producción).

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/core/settings.py
git commit -m "Agrega whitenoise/gunicorn y settings de seguridad para producción"
```

---

## Task 2: Dockerfile del backend + entrypoint

**Files:**
- Create: `backend/Dockerfile`
- Create: `backend/docker-entrypoint.sh`
- Create: `backend/.dockerignore`

**Interfaces:**
- Consumes: `STATIC_ROOT`/`STATICFILES_STORAGE` de Task 1 (para que `collectstatic` en el entrypoint genere el manifest correcto).
- Produces: imagen Docker `sc-pne-backend` escuchando en `:8000` vía gunicorn — consumida por `docker-compose.prod.yml` en Task 4.

- [ ] **Step 1: Crear `backend/.dockerignore`**

```
venv/
media/
staticfiles/
__pycache__/
*.pyc
.env
.git
```

- [ ] **Step 2: Crear `backend/docker-entrypoint.sh`**

```bash
#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn core.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --worker-class gthread
```

`collectstatic` corre acá (arranque del contenedor, con las env vars reales
del `.env` ya cargadas por `docker-compose.prod.yml`) y **no** en el
`Dockerfile` — ver el primer punto de "Review Focus": si corriera en el
build, `DEBUG` sería `True` (no hay `.env` en esa etapa) y el manifest de
whitenoise quedaría generado con el storage por defecto, no con
`CompressedManifestStaticFilesStorage`.

- [ ] **Step 3: Crear `backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim

# Libs nativas para weasyprint (equivalente Linux de brew install cairo pango
# gdk-pixbuf, ya documentado en requirements.txt) + libGL/libglib para
# opencv-python (trae dependencias de GUI que una imagen slim no tiene).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
```

- [ ] **Step 4: Verificar que la imagen buildea**

Run: `docker build -t sc-pne-backend:test ./backend`
Expected: termina con `Successfully tagged sc-pne-backend:test` (o el mensaje
equivalente de Buildx), sin errores de `apt-get`/`pip`.

- [ ] **Step 5: Verificar que las dependencias nuevas importan dentro de la imagen**

Run:
```bash
docker run --rm --entrypoint python sc-pne-backend:test -c \
    "import gunicorn, whitenoise; print('ok')"
```
Expected: imprime `ok`.

- [ ] **Step 6: Verificar `manage.py check` dentro de la imagen (sin Postgres)**

Run: `docker run --rm --entrypoint python sc-pne-backend:test manage.py check`
Expected: `System check identified no issues (0 silenced).` (usa el
`DEBUG=True` por defecto de la imagen sin `.env`, así que no exige
`DJANGO_SECRET_KEY` — es solo una prueba de que el código y las apps
instaladas cargan bien dentro del contenedor, sin depender de la base de
datos).

- [ ] **Step 7: Commit**

```bash
git add backend/Dockerfile backend/docker-entrypoint.sh backend/.dockerignore
git commit -m "Dockerfile de producción para el backend (gunicorn + gthread)"
```

---

## Task 3: Dockerfile del frontend + nginx.conf

**Files:**
- Create: `frontend/Dockerfile`
- Create: `frontend/nginx.conf`
- Create: `frontend/.dockerignore`

**Interfaces:**
- Produces: imagen Docker `sc-pne-frontend` sirviendo el build de Angular en `:80`, con `/api|/admin|/static` proxyado a un host `backend:8000` y `/media/` servido desde `/media_files` — ambos nombres (`backend`, `/media_files`) los define `docker-compose.prod.yml` en Task 4.

- [ ] **Step 1: Crear `frontend/.dockerignore`**

```
node_modules/
dist/
.angular/
```

- [ ] **Step 2: Crear `frontend/nginx.conf`**

```nginx
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location ~ ^/(api|admin|static)/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /media/ {
        alias /media_files/;
    }
}

# Bloque HTTPS: descomentar cuando exista un dominio real con certificado
# emitido (ver docs/DESPLIEGUE-PRODUCCION.md, sección TLS) y activar además
# SECURE_SSL_REDIRECT=True en el .env del backend. Reemplazar TU_DOMINIO_AQUI
# por el dominio real en las 2 líneas marcadas.
#
# server {
#     listen 443 ssl;
#     server_name TU_DOMINIO_AQUI;
#
#     ssl_certificate     /etc/letsencrypt/live/TU_DOMINIO_AQUI/fullchain.pem;
#     ssl_certificate_key /etc/letsencrypt/live/TU_DOMINIO_AQUI/privkey.pem;
#
#     root /usr/share/nginx/html;
#     index index.html;
#
#     location / {
#         try_files $uri $uri/ /index.html;
#     }
#
#     location ~ ^/(api|admin|static)/ {
#         proxy_pass http://backend:8000;
#         proxy_set_header Host $host;
#         proxy_set_header X-Real-IP $remote_addr;
#         proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
#         proxy_set_header X-Forwarded-Proto $scheme;
#     }
#
#     location /media/ {
#         alias /media_files/;
#     }
# }
#
# server {
#     listen 80;
#     server_name TU_DOMINIO_AQUI;
#
#     location /.well-known/acme-challenge/ {
#         root /var/www/certbot;
#     }
#
#     location / {
#         return 301 https://$host$request_uri;
#     }
# }
```

- [ ] **Step 3: Crear `frontend/Dockerfile`**

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npx ng build --configuration production

FROM nginx:1.27-alpine
COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

- [ ] **Step 4: Verificar que la imagen buildea**

Run: `docker build -t sc-pne-frontend:test ./frontend`
Expected: termina con `Successfully tagged sc-pne-frontend:test`, sin errores
de `npm ci`/`ng build`.

- [ ] **Step 5: Verificar que sirve el build de Angular (aislado, sin backend)**

Run:
```bash
docker run --rm -d -p 8080:80 --name sc-pne-frontend-test sc-pne-frontend:test
sleep 1
curl -s http://localhost:8080/ | grep -o '<title>[^<]*</title>'
docker stop sc-pne-frontend-test
```
Expected: imprime `<title>Registro y Asistencia — Policía Nacional</title>`.

- [ ] **Step 6: Commit**

```bash
git add frontend/Dockerfile frontend/nginx.conf frontend/.dockerignore
git commit -m "Dockerfile de producción para el frontend (build Angular + nginx)"
```

---

## Task 4: `docker-compose.prod.yml` + `.env.production.example` + verificación del stack completo

**Files:**
- Create: `docker-compose.prod.yml`
- Create: `.env.production.example`
- Modify: `.gitignore` (excepción para `.env.production.example`)

**Interfaces:**
- Consumes: imagen `backend` de Task 2 (puerto `8000`), imagen `nginx`/frontend de Task 3 (espera un host `backend` resoluble y un volumen montado en `/media_files`).
- Produces: red Docker Compose donde `backend` es resoluble por nombre de servicio desde `nginx` — nombre fijo del que depende Task 5 (`postgres` como nombre de servicio/host).

- [ ] **Step 1: Agregar la excepción al `.gitignore` raíz**

En el `.gitignore` de la raíz del repo, en el bloque que ya tiene
`.env`/`.env.*`/`!.env.example`, agregar una línea más:

```
!.env.production.example
```

(Sin esto, Step 6 de esta tarea confirmaría que el archivo nunca queda
trackeado — ver el segundo punto de "Review Focus".)

- [ ] **Step 2: Crear `.env.production.example` en la raíz del repo**

```bash
# Copiar a `.env` (mismo directorio que docker-compose.prod.yml) y completar
# con valores reales antes de `docker compose -f docker-compose.prod.yml up`.
# Ninguno de estos valores es real -- ver docs/DESPLIEGUE-PRODUCCION.md.

# Generar con: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
DJANGO_SECRET_KEY=

DJANGO_DEBUG=False
# Dominio(s) reales separados por coma, ej: asistencia.policia.gob.ec
DJANGO_ALLOWED_HOSTS=
# Mismo dominio con esquema, ej: https://asistencia.policia.gob.ec
CSRF_TRUSTED_ORIGINS=

DB_NAME=sc_pne
DB_USER=sc_pne
# Password real, no la de dev (sc_pne_local)
DB_PASSWORD=

# Fotos de postulantes: False = disco local (funciona igual sin esto).
# True activa object storage S3-compatible (Hetzner Object Storage o
# DigitalOcean Spaces, docs/00-REFERENCIA-PROYECTO.md) -- requiere completar
# las 5 variables AWS_* de abajo.
USE_S3=False
# AWS_ACCESS_KEY_ID=
# AWS_SECRET_ACCESS_KEY=
# AWS_STORAGE_BUCKET_NAME=
# AWS_S3_ENDPOINT_URL=
# AWS_S3_CUSTOM_DOMAIN=

# Código de verificación de correo: sin esto, el código sigue imprimiéndose
# en los logs del contenedor backend (`docker compose logs backend`), nada
# de correos reales. Completar cuando la Policía Nacional defina un
# proveedor SMTP.
# EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
# EMAIL_HOST=
# EMAIL_HOST_USER=
# EMAIL_HOST_PASSWORD=
# DEFAULT_FROM_EMAIL=

# gunicorn: ajustar según CPU del servidor real (regla de dedo: workers =
# 2xCPU+1). El default alcanza de sobra para la escala de una convocatoria
# (ver docs/00-REFERENCIA-PROYECTO.md, "Escala").
GUNICORN_WORKERS=3
GUNICORN_THREADS=4

# Activar junto con el bloque HTTPS de frontend/nginx.conf cuando exista un
# certificado real -- False hasta entonces (ver Task 1 de este plan).
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
```

- [ ] **Step 3: Crear `docker-compose.prod.yml` en la raíz del repo**

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: sc-pne-postgres-prod
    environment:
      POSTGRES_DB: ${DB_NAME}
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pg_data_prod:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d ${DB_NAME}"]
      interval: 5s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  backend:
    build: ./backend
    env_file: .env
    environment:
      DB_HOST: postgres
      DB_PORT: 5432
    volumes:
      - media_files:/app/media
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped

  nginx:
    build: ./frontend
    ports:
      - "80:80"
      # - "443:443"  # descomentar junto con el bloque HTTPS de frontend/nginx.conf
    volumes:
      - media_files:/media_files:ro
      - certbot_certs:/etc/letsencrypt:ro
      - certbot_webroot:/var/www/certbot:ro
    depends_on:
      - backend
    restart: unless-stopped

  certbot:
    image: certbot/certbot
    profiles: ["tls"]
    volumes:
      - certbot_certs:/etc/letsencrypt
      - certbot_webroot:/var/www/certbot

volumes:
  pg_data_prod:
  media_files:
  certbot_certs:
  certbot_webroot:
```

- [ ] **Step 4: Confirmar que `.env.production.example` va a quedar trackeado**

Run: `git add -n .env.production.example`
Expected: imprime `add '.env.production.example'` (no un mensaje vacío/
silencioso, que indicaría que el `.gitignore` lo sigue bloqueando).

- [ ] **Step 5: Crear un `.env` temporal de prueba local (no se comitea)**

Crear, en la raíz del repo, un archivo `.env` (ya cubierto por
`.gitignore`, no hace falta tocarlo) con valores dummy pero válidos:

```
DJANGO_SECRET_KEY=verificacion-temporal-no-usar-en-real
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=http://localhost
DB_NAME=sc_pne_prod_test
DB_USER=sc_pne
DB_PASSWORD=sc_pne_test_password
GUNICORN_WORKERS=3
GUNICORN_THREADS=4
```

- [ ] **Step 6: Levantar el stack completo y esperar a que esté sano**

Run: `docker compose -f docker-compose.prod.yml up -d --build`
Expected: los 3 servicios (`postgres`, `backend`, `nginx`) arrancan.

Run: `docker compose -f docker-compose.prod.yml ps`
Expected: `postgres` en estado `healthy`, `backend`/`nginx` en `running`.

- [ ] **Step 7: Verificar que el frontend responde**

Run: `curl -s http://localhost/ | grep -o '<title>[^<]*</title>'`
Expected: `<title>Registro y Asistencia — Policía Nacional</title>`.

- [ ] **Step 8: Verificar que `/admin` llega al backend (whitenoise + proxy)**

Run: `curl -s -o /dev/null -w '%{http_code}\n' http://localhost/admin/login/`
Expected: `200` (no `502`/`504`, que indicarían que nginx no encuentra a
`backend`, y no `400`, que indicaría un problema de `ALLOWED_HOSTS` — ver
tercer punto de "Review Focus").

- [ ] **Step 8b: Verificar que whitenoise sirve el CSS del admin con el manifest correcto (Review Focus: timing de `collectstatic`)**

Un `200` en `/admin/login/` no prueba que sus estáticos carguen — la página
HTML se sirve igual aunque el CSS enlazado dé 404. Extraer la URL real del
CSS con hash que generó el manifest y pedirla aparte:

Run:
```bash
CSS_HREF=$(curl -s http://localhost/admin/login/ | grep -o '/static/admin/css/base[^"]*\.css' | head -1)
echo "$CSS_HREF"
curl -s -o /dev/null -w '%{http_code}\n' "http://localhost$CSS_HREF"
```
Expected: `$CSS_HREF` tiene un hash en el nombre (ej.
`/static/admin/css/base.abcd1234.css`, no `base.css` a secas — confirma que
`CompressedManifestStaticFilesStorage` sí generó el manifest); el segundo
`curl` devuelve `200`.

- [ ] **Step 9: Verificar que `/api` llega al backend**

Run: `curl -s -o /dev/null -w '%{http_code}\n' http://localhost/api/token/`
Expected: `405` (Method Not Allowed — `TokenConRolView` solo acepta `POST`;
confirma que la request atravesó nginx y llegó a Django, no que "no
conecta").

- [ ] **Step 10: Verificar `manage.py check --deploy` dentro del stack real**

Run: `docker compose -f docker-compose.prod.yml exec backend python manage.py check --deploy`
Expected: solo advertencias esperadas y ya conocidas sobre TLS/HSTS (`W004`,
`W008`, `W012`, `W016` — todas relacionadas a que `SECURE_SSL_REDIRECT`/
`SESSION_COOKIE_SECURE`/HSTS siguen en `False` a propósito, ver Task 1);
ninguna advertencia nueva no relacionada con TLS.

- [ ] **Step 11: Verificar el volumen de medios (Review Focus: ruta `/media/`)**

Run:
```bash
docker compose -f docker-compose.prod.yml exec backend sh -c \
    "mkdir -p media/prueba && echo contenido-de-prueba > media/prueba/archivo.txt"
curl -s http://localhost/media/prueba/archivo.txt
```
Expected: imprime `contenido-de-prueba` (confirma que `nginx` lee del mismo
volumen `media_files` donde escribe `backend`, con la ruta/alias correctos).

- [ ] **Step 12: Apagar y limpiar**

Run: `docker compose -f docker-compose.prod.yml down -v`
Expected: se detienen y borran los contenedores y volúmenes de prueba
(`pg_data_prod`, `media_files`, etc. — datos dummy, no hay nada real que
perder). Borrar también el `.env` temporal del Step 5 (no se comitea, era
solo para esta verificación).

- [ ] **Step 13: Commit**

```bash
git add docker-compose.prod.yml .env.production.example .gitignore
git commit -m "docker-compose.prod.yml: orquesta postgres+backend+nginx+certbot"
```

---

## Task 5: Script de backups + wiring en el compose de producción

**Files:**
- Create: `scripts/backup-postgres.sh`
- Modify: `docker-compose.prod.yml` (servicio `postgres`: agrega volumen de scripts y de backups)

**Interfaces:**
- Consumes: servicio `postgres` de Task 4 (mismo `container_name: sc-pne-postgres-prod`, mismas env vars `POSTGRES_DB`/`POSTGRES_USER` ya definidas ahí).

- [ ] **Step 1: Crear `scripts/backup-postgres.sh`**

```bash
#!/bin/sh
set -e

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENCION_DIAS="${RETENCION_DIAS:-7}"
FECHA=$(date +%Y%m%d_%H%M%S)
ARCHIVO="$BACKUP_DIR/sc_pne_${FECHA}.sql.gz"

mkdir -p "$BACKUP_DIR"
pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" | gzip > "$ARCHIVO"
echo "Backup escrito en $ARCHIVO"

find "$BACKUP_DIR" -name 'sc_pne_*.sql.gz' -mtime "+${RETENCION_DIAS}" -delete
```

- [ ] **Step 2: Montar el script y el volumen de backups en `docker-compose.prod.yml`**

En el servicio `postgres` de `docker-compose.prod.yml` (creado en Task 4),
agregar a su lista `volumes` (que hoy solo tiene `pg_data_prod`):

```yaml
      - ./scripts/backup-postgres.sh:/scripts/backup-postgres.sh:ro
      - backups_prod:/backups
```

Y agregar `backups_prod:` a la lista de `volumes:` de nivel superior del
archivo (junto a `pg_data_prod`, `media_files`, etc.).

- [ ] **Step 3: Verificar permisos de ejecución**

Run: `chmod +x scripts/backup-postgres.sh`

- [ ] **Step 4: Levantar solo Postgres para probar el script**

Recrear el `.env` temporal de prueba de Task 4 Step 5 si ya se había
borrado, luego:

Run: `docker compose -f docker-compose.prod.yml up -d postgres`
Expected: `sc-pne-postgres-prod` queda `healthy`.

- [ ] **Step 5: Ejecutar el backup y confirmar que escribe el archivo**

Run: `docker compose -f docker-compose.prod.yml exec postgres sh /scripts/backup-postgres.sh`
Expected: imprime `Backup escrito en /backups/sc_pne_<fecha>.sql.gz`.

Run: `docker compose -f docker-compose.prod.yml exec postgres ls /backups`
Expected: lista el archivo `.sql.gz` recién creado.

- [ ] **Step 6: Verificar la rotación (Review Focus: no debe borrar de más ni de menos)**

Run:
```bash
docker compose -f docker-compose.prod.yml exec postgres sh -c \
    "touch -t 202001010000 /backups/sc_pne_viejo_test.sql.gz && ls /backups"
```
Expected: se ven 2 archivos: el reciente del Step 5 y
`sc_pne_viejo_test.sql.gz` con fecha simulada de 2020.

Run: `docker compose -f docker-compose.prod.yml exec postgres sh /scripts/backup-postgres.sh`

Run: `docker compose -f docker-compose.prod.yml exec postgres ls /backups`
Expected: `sc_pne_viejo_test.sql.gz` desapareció (más viejo que
`RETENCION_DIAS=7`), pero el backup reciente del Step 5 y el nuevo de este
Step siguen ahí (más nuevos que 7 días).

- [ ] **Step 7: Apagar y limpiar**

Run: `docker compose -f docker-compose.prod.yml down -v`

- [ ] **Step 8: Commit**

```bash
git add scripts/backup-postgres.sh docker-compose.prod.yml
git commit -m "Script de backup diario de Postgres con rotación de 7 días"
```

---

## Task 6: Guía de despliegue (`docs/DESPLIEGUE-PRODUCCION.md`)

**Files:**
- Create: `docs/DESPLIEGUE-PRODUCCION.md`

**Interfaces:**
- Consumes: nombres y comandos exactos de Tasks 1-5 (Dockerfiles, `docker-compose.prod.yml`, `.env.production.example`, `scripts/backup-postgres.sh`) — es documentación, no código; no produce interfaces nuevas.

- [ ] **Step 1: Escribir `docs/DESPLIEGUE-PRODUCCION.md`**

```markdown
# Despliegue de producción

Ver `docs/superpowers/specs/2026-09-29-despliegue-produccion-design.md` para
el diseño completo. Esta guía es la lista de pasos para cuando exista un
servidor real.

## 1. Contratar el servidor

Hetzner recomendado por costo (ver `docs/00-REFERENCIA-PROYECTO.md`, sección
"Hosting con cifras reales") — un CX de 4GB/2vCPU alcanza, sin GPU. Instalar
Docker + Docker Compose plugin en el servidor.

## 2. Clonar el repo y configurar el entorno

```bash
git clone <url-del-repo> && cd asistencia
git checkout PRODU
cp .env.production.example .env
```

Editar `.env` con valores reales:
- `DJANGO_SECRET_KEY`: generar con
  `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`.
- `DJANGO_ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS`: el dominio real una vez
  apuntado el DNS.
- `DB_PASSWORD`: una contraseña real, no la de dev.
- `USE_S3`/`EMAIL_*`: dejar como están (local/consola) hasta tener
  credenciales reales de un proveedor — el sistema funciona igual sin esto,
  ver `docs/superpowers/specs/2026-09-29-despliegue-produccion-design.md`.

## 3. Primer arranque

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps   # confirmar los 3 servicios healthy/running
```

En este punto el sitio responde en `http://<ip-del-servidor>/` (HTTP plano,
sin TLS todavía).

## 4. Emitir el certificado TLS (una vez el dominio ya resuelve al servidor)

```bash
docker compose -f docker-compose.prod.yml run --rm certbot certonly \
    --webroot -w /var/www/certbot \
    -d TU_DOMINIO_AQUI \
    --email TU_CORREO_AQUI --agree-tos --no-eff-email
```

Después:
1. En `frontend/nginx.conf`, descomentar el bloque HTTPS y reemplazar las 2
   ocurrencias de `TU_DOMINIO_AQUI`.
2. En `docker-compose.prod.yml`, descomentar el puerto `"443:443"` del
   servicio `nginx`.
3. En `.env`, poner `SECURE_SSL_REDIRECT=True`, `SESSION_COOKIE_SECURE=True`,
   `CSRF_COOKIE_SECURE=True`.
4. `docker compose -f docker-compose.prod.yml up -d --build nginx backend`.

Renovación: correr el mismo comando `certbot certonly` (o `certbot renew`)
periódicamente vía cron del host — Let's Encrypt expira cada 90 días.

## 5. Backups

Agendar en el cron del host (fuera de Docker):

```
0 3 * * * docker exec sc-pne-postgres-prod sh /scripts/backup-postgres.sh >> /var/log/sc-pne-backup.log 2>&1
```

Restaurar un backup:

```bash
gunzip -c sc_pne_20260101_030000.sql.gz | \
    docker exec -i sc-pne-postgres-prod psql -U sc_pne -d sc_pne
```

## 6. Pendientes que no son de infraestructura

- Retención de datos biométricos: pendiente de definición legal con la
  Policía Nacional antes de operar con datos reales en producción (ver
  `docs/00-REFERENCIA-PROYECTO.md`).
- Credenciales reales de object storage/SMTP: el sistema funciona sin ellas
  (disco local + código de verificación en los logs del contenedor), se
  agregan cuando el cliente las provea, sin redeploy de código.
```

- [ ] **Step 2: Revisar que los comandos coinciden con los usados en Tasks 1-5**

Releer `docs/DESPLIEGUE-PRODUCCION.md` contra los `docker compose`/`git`
comandos efectivamente usados en las verificaciones de Tasks 4 y 5 (nombres
de servicios, `container_name`, rutas de archivos) — corregir cualquier
comando que se haya escrito de memoria y no coincida exactamente.

- [ ] **Step 3: Commit**

```bash
git add docs/DESPLIEGUE-PRODUCCION.md
git commit -m "Guía de despliegue de producción paso a paso"
```
