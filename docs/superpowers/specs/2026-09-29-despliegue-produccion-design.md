# Despliegue de producción — artefactos Docker/nginx/gunicorn

Fecha: 2026-09-29
Estado: aprobado en chat, pendiente de plan de implementación

## Contexto

El proyecto (`docs/00-REFERENCIA-PROYECTO.md`) ya fijó la arquitectura de
despliegue desde la investigación del 2026-09-03/06: un solo servidor Hetzner
(o DigitalOcean) con Docker corriendo Postgres + Django/gunicorn + nginx
sirviendo el build de Angular, TLS vía Let's Encrypt/Certbot, backups con
`pg_dump` + cron, object storage S3-compatible detrás de `USE_S3` (ya cableado
en `backend/core/settings.py`, sin probar contra un bucket real). Las ramas
`DEVOPS → TEST → PRODU` ya existen en el repo pero `PRODU`/`TEST` siguen en el
scaffold inicial (`3c4a2fb`) — nunca recibieron ninguno de los ~20 commits de
`DEVOPS`.

Lo único que faltaba era construir esos artefactos como código. Este spec
cubre esa construcción, no la decisión de arquitectura (ya tomada) ni el
aprovisionamiento real de un servidor.

## Objetivo

Dejar en el repo todo lo necesario para que, el día que exista un servidor
Hetzner/DO real con un dominio apuntando a él, levantar producción sea
`git clone` + copiar un `.env` real + `docker compose -f docker-compose.prod.yml
up -d`. Verificar localmente (sin servidor real) que las imágenes buildean y
el stack completo responde correctamente sirviendo el frontend y proxyando la
API.

## Fuera de alcance (confirmado con el usuario)

- **Aprovisionar el servidor real** (Hetzner/DO), comprar dominio, apuntar DNS.
- **Credenciales reales de S3-compatible u SMTP** — se documentan las
  variables de entorno que hacen falta, pero `.env.production.example` no
  lleva valores reales; `USE_S3=False` y `EMAIL_BACKEND` de consola siguen
  siendo el default hasta que el cliente las provea.
- **Certificado TLS real** — Certbot se deja configurado (servicio en el
  compose, volumen para los certs, bloque de nginx preparado para HTTPS una
  vez existan certs), pero no se puede emitir un certificado real sin un
  dominio público resolviendo al servidor. En este spec, nginx sirve HTTP
  plano; el bloque HTTPS queda comentado con instrucciones de cómo activarlo.
- **Política de retención de datos biométricos** — bloqueada en legal, ya
  documentado en la memoria/referencia del proyecto, no es un tema de infra.
- **CI/CD** (build/deploy automático en push a `PRODU`) — no se pidió, y son
  pocas personas desplegando manualmente por ahora; se puede agregar después
  sin rehacer nada de este spec.

## Arquitectura

```
                    ┌─────────────────────────────────────┐
                    │              nginx (80)              │
                    │  /            -> build Angular       │
                    │  /api/*       -> proxy_pass backend   │
                    │  /admin/*     -> proxy_pass backend   │
                    │  /static/*    -> proxy_pass backend   │
                    │  /media/*     -> alias volumen media  │
                    └───────────┬───────────────────────────┘
                                │
                    ┌───────────▼───────────────────────────┐
                    │         backend (gunicorn:8000)        │
                    │  Django + DRF + whitenoise (static)    │
                    │  facial.py (lock) + pool.py (embeddings)│
                    └───────────┬───────────────────────────┘
                                │
                    ┌───────────▼───────────────────────────┐
                    │        postgres:16-alpine              │
                    │  volumen nombrado (no el de dev)       │
                    └─────────────────────────────────────────┘

                    ┌─────────────────────────────────────┐
                    │  certbot (perfil opcional, no activo   │
                    │  por defecto hasta tener dominio real) │
                    └─────────────────────────────────────────┘
```

4 servicios en `docker-compose.prod.yml`: `postgres`, `backend`, `nginx`,
`certbot` (este último con `profiles: ["tls"]` en Compose — no arranca con un
`up -d` normal, solo cuando se invoca explícitamente una vez haya dominio).

## Componentes

### 1. `backend/Dockerfile`

Imagen `python:3.12-slim` (el proyecto no fija versión de Python en ningún
archivo — el `venv` local quedó en 3.9.6 por antigüedad, no por una decisión
deliberada; 3.12 es la LTS razonable hoy y Django 4.2 la soporta) con:

- Libs nativas de sistema: `libcairo2`, `libpango-1.0-0`, `libpangocairo-1.0-0`,
  `libgdk-pixbuf-2.0-0` (weasyprint — el equivalente Linux del
  `brew install cairo pango gdk-pixbuf` que ya documenta `requirements.txt`;
  en Linux el linker las resuelve solas, sin `DYLD_FALLBACK_LIBRARY_PATH`).
- `opencv-python` tal cual está en requirements.txt hoy trae dependencias de
  GUI (`libGL`, `libSM`, etc.) que una imagen headless no tiene — se agregan
  `libgl1`/`libglib2.0-0` al Dockerfile en vez de cambiar el paquete Python
  (cambiar a `opencv-python-headless` es un cambio de dependencia que excede
  este spec de infra; se deja anotado como mejora futura de bajo riesgo).
- `pip install -r requirements.txt` + `gunicorn` + `whitenoise` (los dos
  nuevos, ver más abajo).
- `STATIC_ROOT` (nuevo, no existía en `settings.py` — se agrega).
- Entrypoint (`docker-entrypoint.sh`): `python manage.py migrate --noinput`,
  **`python manage.py collectstatic --noinput`** (en el arranque del
  contenedor, no en build time del Dockerfile — en build no existe `.env`
  real, `DEBUG` sería `True` por default y el manifest de whitenoise
  quedaría generado con el storage equivocado; corregido durante la
  implementación, ver el plan) y despues
  `exec gunicorn core.wsgi:application --bind 0.0.0.0:8000
  --workers ${GUNICORN_WORKERS:-3} --threads ${GUNICORN_THREADS:-4}
  --worker-class gthread`. `gthread` porque el lock de concurrencia en
  `facial.py` (`bff15c1`) ya está pensado para hilos dentro de un mismo
  proceso, no para workers `sync` de un solo hilo.

### 2. `frontend/Dockerfile`

Build multi-stage:

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
```

(la ruta exacta `dist/frontend/browser` se confirma contra el
`outputPath`/`browser` real de `angular.json` al implementar — Angular 17+
anida el build ahí por defecto).

### 3. `frontend/nginx.conf` (nuevo)

- `location /` → `try_files $uri $uri/ /index.html` (SPA routing de Angular).
- `location ~ ^/(api|admin|static)/` → `proxy_pass http://backend:8000;` +
  headers estándar (`X-Forwarded-For`, `X-Forwarded-Proto`, `Host`).
- **Sin** `location /media/` (cambiado en la auditoría de seguridad del
  2026-09-30): las fotos son biométricas y servirlas directo desde el volumen
  las dejaba públicas para cualquiera con la URL. Salen solo por
  `/api/fotos/<firma>/` (URL firmada, ver `FotoFirmadaField`).
- `client_max_body_size 6m` y `limit_req` (10/min por IP) en `/admin/login/`.
- `.env` de producción: `NUM_PROXIES=1` (el throttle de DRF toma la IP real
  que agrega nginx; sin esto un `X-Forwarded-For` falso evade los límites).
- Bloque HTTPS comentado (server en :443, `ssl_certificate`
  `/etc/letsencrypt/live/<dominio>/fullchain.pem`, redirect 80→443) con un
  comentario explicando qué descomentar y en qué orden una vez exista el
  certificado real.

### 4. Cambios en `backend/core/settings.py`

- `STATIC_ROOT = BASE_DIR / 'staticfiles'` (nuevo, no existía).
- `MIDDLEWARE`: agregar `'whitenoise.middleware.WhiteNoiseMiddleware'`
  inmediatamente después de `SecurityMiddleware` (posición exigida por
  whitenoise).
- `STORAGES['staticfiles']['BACKEND'] =
  'whitenoise.storage.CompressedManifestStaticFilesStorage'` cuando
  `DEBUG=False` (en dev, sin esto, para no romper `runserver` sin haber
  corrido `collectstatic`).
- Nuevas env vars de seguridad, todas condicionadas a `DEBUG=False` (no
  afectan dev): `CSRF_TRUSTED_ORIGINS` (lista, ej.
  `https://asistencia.ejemplo.gob.ec`), `SECURE_SSL_REDIRECT` (default
  `False` hasta que haya TLS real — activar cuando se descomente el bloque
  HTTPS de nginx), `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` (mismo
  criterio).
- `ALLOWED_HOSTS` ya lee de env (`DJANGO_ALLOWED_HOSTS`) — no cambia, solo se
  documenta en el `.env.production.example`.

### 5. `requirements.txt`

Agregar `gunicorn` y `whitenoise` (los dos nuevos; nada más cambia).

### 6. `docker-compose.prod.yml` (nuevo, no toca `docker-compose.yml` de dev)

- `postgres`: mismo `postgres:16-alpine`, volumen nombrado `pg_data_prod`
  (distinto del de dev), variables desde `.env`, **sin** puerto publicado al
  host (solo accesible entre contenedores — a diferencia de dev que expone
  `5434`).
- `backend`: build desde `backend/Dockerfile`, `env_file: .env`, volumen
  compartido `media_files:/app/media` (para que nginx lo lea), depende de
  `postgres` (`condition: service_healthy` con healthcheck de `pg_isready`).
- `nginx`: build desde `frontend/Dockerfile`, puertos `80:80` (y `443:443`
  comentado junto al bloque HTTPS), monta `media_files` como solo-lectura,
  monta un volumen para certs de Let's Encrypt (vacío hasta que exista TLS
  real).
- `certbot` (`profiles: ["tls"]`): imagen oficial `certbot/certbot`, monta el
  mismo volumen de certs + el webroot de nginx para el challenge HTTP-01;
  instrucciones de uso (comando exacto) en un comentario y en el README de
  despliegue.

### 7. Backups

Script `scripts/backup-postgres.sh` (nuevo) que corre `pg_dump` dentro del
contenedor de `postgres` y escribe a un volumen `backups/` con nombre
`sc_pne_YYYYMMDD.sql.gz`, más un `find ... -mtime +7 -delete` para no acumular
indefinidamente. Se agenda con `cron` en el host (documentado en el README de
despliegue, ej. `0 3 * * * docker exec sc-pne-postgres-prod
/scripts/backup-postgres.sh`) — no un contenedor cron aparte, para no sumar un
quinto servicio por algo que corre una vez al día.

### 8. `.env.production.example` (nuevo)

Todas las variables que hoy lee `settings.py`, con comentarios de qué son y
sin valores reales: `DJANGO_SECRET_KEY` (instrucción de cómo generar una),
`DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS`, `DB_NAME`/`DB_USER`/
`DB_PASSWORD`/`DB_HOST=postgres`/`DB_PORT=5432`, `USE_S3` + las 5 variables de
AWS/S3 (comentadas, solo se activan si `USE_S3=True`), `EMAIL_BACKEND`/
`EMAIL_HOST`/`EMAIL_HOST_USER`/`EMAIL_HOST_PASSWORD` (comentadas, default
consola), `CSRF_TRUSTED_ORIGINS`, `GUNICORN_WORKERS`/`GUNICORN_THREADS`.

### 9. `docs/DESPLIEGUE-PRODUCCION.md` (nuevo)

Guía corta paso a paso para cuando exista el servidor real: provisionar
Hetzner (referencia al análisis de costos ya hecho en
`00-REFERENCIA-PROYECTO.md`), instalar Docker, copiar el repo, crear `.env`
real a partir del example, primer `docker compose -f docker-compose.prod.yml
up -d --build`, cómo emitir el certificado con el perfil `certbot`, cómo
activar el bloque HTTPS de nginx después, cómo restaurar un backup
(`gunzip -c backup.sql.gz | docker exec -i ... psql`).

## Verificación (sin servidor real)

- `docker compose -f docker-compose.prod.yml build` termina sin error para
  los 3 servicios con imagen propia.
- `docker compose -f docker-compose.prod.yml up -d` (con un `.env` de prueba
  local, valores dummy pero válidos — `DJANGO_ALLOWED_HOSTS=localhost`) deja
  los 3 contenedores healthy.
- `curl localhost/` devuelve el `index.html` de Angular.
- `curl localhost/admin/login/` devuelve el login de Django (prueba que el
  proxy a gunicorn y whitenoise para su CSS funcionan).
- `curl -X POST localhost/api/token/` con credenciales de prueba devuelve
  401/200 según corresponda (prueba que `/api/` llega a Django).
- Backend arriba con `python manage.py check --deploy` (comando estándar de
  Django) sin warnings nuevos que no estén ya documentados como pendientes
  (ej. TLS, que sabemos que falta a propósito).
- Los 123 tests de backend + 17 de frontend existentes NO deben romperse por
  estos cambios (los cambios de `settings.py` están condicionados a
  `DEBUG=False`, que los tests no activan).

## Próximos pasos manuales del usuario (fuera de este spec)

1. Contratar el servidor (Hetzner recomendado por costo, ver
   `00-REFERENCIA-PROYECTO.md`) y apuntar un dominio a su IP.
2. Conseguir credenciales reales de object storage S3-compatible y/o SMTP si
   se quieren activar antes de la prueba real (opcional, ambos siguen
   funcionando con el fallback local/consola sin esto).
3. Correr el perfil `certbot` una vez el dominio resuelva, y descomentar el
   bloque HTTPS de nginx.
4. Resolver con el área legal de la Policía Nacional la política de
   retención de datos biométricos antes de operar con datos reales en
   producción (ya documentado, no es parte de esta infra).
