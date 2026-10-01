# Despliegue de producción

Ver `docs/superpowers/specs/2026-09-29-despliegue-produccion-design.md` para
el diseño completo. Esta guía es la lista de pasos para cuando exista un
servidor real. Todos los comandos se probaron localmente contra el stack de
`docker-compose.prod.yml`.

## 1. Contratar el servidor

Hetzner recomendado por costo (ver `docs/00-REFERENCIA-PROYECTO.md`, sección
"Hosting con cifras reales") — un CX de 4GB/2vCPU alcanza, sin GPU. Instalar
Docker + Docker Compose plugin en el servidor y abrir solo los puertos 22, 80
y 443 en el firewall.

## 2. Clonar el repo y configurar el entorno

```bash
git clone <url-del-repo> && cd asistencia
git checkout PRODU          # rama de producción: mergear DEVOPS -> PRODU antes
cp .env.production.example .env
```

Editar `.env` con valores reales:
- `DJANGO_SECRET_KEY`: generar con
  `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` (sin `$`:
  compose interpreta `$VAR` dentro de `.env`; lo mismo para `DB_PASSWORD`). Con
  `DJANGO_DEBUG=False` el backend **no arranca** si tiene menos de 50
  caracteres (protege contra dejar un placeholder).
- `DJANGO_ALLOWED_HOSTS`: para el primer arranque, `localhost,<ip-del-servidor>`
  (sin esto Django responde 400 "Invalid HTTP_HOST header" a todo `/api` y
  `/admin`, y parece que el proxy no conecta). El dominio se agrega en la
  sección 4.
- `CSRF_TRUSTED_ORIGINS`: el dominio con esquema (`https://...`), en la
  sección 4.
- `NUM_PROXIES=1`: ya viene así; no tocar (sin esto, un `X-Forwarded-For`
  falso evade los límites de intentos).
- `DB_PASSWORD`: una contraseña real, no la de dev. Postgres la toma solo en el
  primer arranque (al crear el volumen): cambiarla después en `.env` no cambia
  la de la base, y el backend queda en "password authentication failed".
- `USE_S3`/`EMAIL_*`: ver sección 8.

Los modelos de reconocimiento facial (`.onnx`) no están en git: el build de la
imagen del backend los descarga con `backend/asistencia/ml_models/download.sh`
y verifica su sha256 (si un modelo cambió upstream, el build falla a propósito).

## 3. Primer arranque

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps   # postgres y backend healthy, nginx running
```

En este punto el sitio responde en `http://<ip-del-servidor>/` (HTTP plano,
sin TLS todavía). **Solo para verificar que levanta: NO dar acceso a
postulantes ni agentes reales hasta completar la sección 4.** Sin TLS,
contraseñas, JWT, cookies del admin, códigos de recuperación y fotos
biométricas viajan en claro por la red (Wi-Fi de la sede, NAT, ISP).

Chequeo rápido:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/admin/login/   # 200
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/api/token/     # 405
docker compose -f docker-compose.prod.yml exec backend python manage.py check --deploy
```

`check --deploy` debe mostrar solo W004/W008/W012/W016 (TLS/HSTS) hasta
terminar la sección 4.

## 4. Emitir el certificado TLS (una vez el dominio ya resuelve al servidor)

```bash
docker compose -f docker-compose.prod.yml run --rm certbot certonly \
    --webroot -w /var/www/certbot \
    -d TU_DOMINIO_AQUI \
    --email TU_CORREO_AQUI --agree-tos --no-eff-email
```

(El bloque :80 activo de `frontend/nginx.conf` ya sirve
`/.well-known/acme-challenge/` desde el volumen de certbot.)

Después:
1. En `frontend/nginx.conf`, descomentar el bloque HTTPS y el bloque :80 que
   redirige a https, reemplazar las ocurrencias de `TU_DOMINIO_AQUI`, y borrar
   el bloque catch-all `server_name _` de arriba.
2. En `docker-compose.prod.yml`, descomentar el puerto `"443:443"` del
   servicio `nginx`. En `.env`, agregar el dominio a `DJANGO_ALLOWED_HOSTS` y
   poner `CSRF_TRUSTED_ORIGINS=https://TU_DOMINIO_AQUI`.
3. En `.env`, poner `SECURE_SSL_REDIRECT=True`, `SESSION_COOKIE_SECURE=True`,
   `CSRF_COOKIE_SECURE=True`. Una vez comprobado que HTTPS anda, agregar
   `SECURE_HSTS_SECONDS=31536000` (empezar con 3600 un día si hay dudas: HSTS
   no se deshace fácil en los navegadores que ya lo vieron).
4. `docker compose -f docker-compose.prod.yml up -d --build nginx backend`.

Renovación: Let's Encrypt expira cada 90 días. Cron del host:

```
0 4 * * 1 cd /ruta/asistencia && docker compose -f docker-compose.prod.yml run --rm certbot renew && docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

## 5. Datos iniciales y cuentas

Primer administrador (también es agente: `is_staff`):

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py createsuperuser
```

Los demás agentes se crean desde `/admin/` (Usuarios → marcar "Es staff").
El kiosco de verificación **y el puesto de registro** exigen un agente con
sesión iniciada: el registro es supervisado (el agente ve la cédula física).

Carga del padrón oficial (CSV con columnas `nombres,apellidos,cedula,estatura_cm,sede`):

```bash
docker compose -f docker-compose.prod.yml cp padron.csv backend:/tmp/padron.csv
docker compose -f docker-compose.prod.yml exec backend python manage.py importar_postulantes /tmp/padron.csv
```

## 6. Backups

Las fotos y los embeddings son datos biométricos: los backups contienen todo
eso. Guardarlos con acceso restringido (solo root del host) y, si se copian
fuera del servidor, cifrados.

Base de datos (cron del host, rota a 7 días dentro del volumen `backups_prod`):

```
0 3 * * * docker exec sc-pne-postgres-prod sh /scripts/backup-postgres.sh >> /var/log/sc-pne-backup.log 2>&1
```

Fotos (no van en el `pg_dump`; viven en el volumen `media_files`):

```
30 3 * * * docker run --rm -v asistencia-prod_media_files:/m:ro -v /root/backups-media:/b alpine tar czf /b/media_$(date +\%Y\%m\%d).tgz -C /m . && find /root/backups-media -name 'media_*.tgz' -mtime +7 -delete
```

(El prefijo `asistencia-prod_` es el `name:` de `docker-compose.prod.yml`;
confirmar con `docker volume ls`.)

Restaurar la base (probado: los dumps llevan `--clean --if-exists`, así que
se aplican sobre la base existente):

```bash
docker compose -f docker-compose.prod.yml stop backend
docker exec sc-pne-postgres-prod ls -t /backups          # elegir el archivo
docker exec sc-pne-postgres-prod sh -c \
    'gunzip -c /backups/sc_pne_AAAAMMDD_HHMMSS.sql.gz | psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose -f docker-compose.prod.yml start backend
```

`ON_ERROR_STOP=1` hace que un error corte la restauración en vez de dejarla a
medias sin avisar. Los backups viven dentro del volumen `backups_prod`, no en
el disco del host: para copiarlos afuera,
`docker cp sc-pne-postgres-prod:/backups ./backups-copia`.

## 7. Actualizar a una nueva versión

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs --tail 50 backend
```

El entrypoint del backend aplica las migraciones y `collectstatic` solo. nginx
re-resuelve el backend cada 10 s, así que redeployar solo el backend
(`up -d --build backend`) no deja a nginx apuntando a una IP vieja.

## 8. Pendientes antes de operar con postulantes reales

- **Correo (SMTP)**: sin `EMAIL_*`, el código de activación de cuenta y el de
  recuperación de contraseña **no le llegan a nadie** — se imprimen en
  `docker compose -f docker-compose.prod.yml logs backend`. El postulante no
  puede activar su cuenta sin ese código. Configurar un proveedor real antes de
  abrir el registro (o, como paso transitorio, que el agente del puesto lea el
  código de los logs).
- Object storage (`USE_S3`): opcional; sin él las fotos quedan en el disco del
  servidor (volumen `media_files`), incluidas en el backup de la sección 6.
- Retención de datos biométricos y aviso/consentimiento (LOPDP): pendiente de
  definición legal con la Policía Nacional antes de operar con datos reales
  (ver `docs/00-REFERENCIA-PROYECTO.md`).
