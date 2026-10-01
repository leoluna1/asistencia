#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py createcachetable
python manage.py collectstatic --noinput

exec gunicorn core.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --worker-class gthread \
    --timeout 60 \
    --access-logfile -
