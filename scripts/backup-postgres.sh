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
