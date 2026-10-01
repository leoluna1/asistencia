#!/bin/sh
set -e

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENCION_DIAS="${RETENCION_DIAS:-7}"
FECHA=$(date +%Y%m%d_%H%M%S)
ARCHIVO="$BACKUP_DIR/sc_pne_${FECHA}.sql.gz"
TMP="$BACKUP_DIR/.sc_pne_${FECHA}.sql"

mkdir -p "$BACKUP_DIR"
trap 'rm -f "$TMP" "$TMP.gz"' EXIT
# A archivo y no `pg_dump | gzip`: en un pipe, set -e solo ve el código de gzip,
# y un pg_dump fallido dejaba un .gz válido pero vacío — que después la
# rotación usaba de excusa para borrar los backups buenos.
# --clean --if-exists: el dump se puede restaurar sobre la base ya migrada.
pg_dump --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "$TMP"
gzip "$TMP"
mv "$TMP.gz" "$ARCHIVO"
echo "Backup escrito en $ARCHIVO"

# Solo se llega acá si el backup salió bien.
find "$BACKUP_DIR" -name 'sc_pne_*.sql.gz' -mtime "+${RETENCION_DIAS}" -delete
