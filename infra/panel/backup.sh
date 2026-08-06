#!/usr/bin/env bash
#
# khilios — бэкап панели.
#
# В cron на панельной VPS, раз в 6 часов:
#   0 */6 * * * /opt/khilios/infra/panel/backup.sh >> /var/log/khilios-backup.log 2>&1
#
# Бэкап, который ни разу не восстанавливали, — это не бэкап.
# Раз в месяц: разверни дамп на чистой VPS и засеки время. Записывай результат в runbook.

set -euo pipefail

PANEL_DIR="${PANEL_DIR:-/opt/remnawave}"
DB_CONTAINER="${DB_CONTAINER:-remnawave-db}"
DB_USER="${DB_USER:-postgres}"
DB_NAME="${DB_NAME:-postgres}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/khilios}"
KEEP="${KEEP:-28}"          # 28 штук по 6 часов = неделя истории

# Куда выгружать копию. Бэкап на той же машине, что и панель, не спасает
# ровно в том случае, ради которого делается. Заполни или потеряешь всё вместе с VPS.
#   REMOTE="user@backup-host:/srv/khilios"
REMOTE="${REMOTE:-}"

log() { printf '[%s] %s\n' "$(date -u +%F' '%T)" "$*"; }

mkdir -p "$BACKUP_DIR"
STAMP=$(date -u +%Y%m%d-%H%M%S)
OUT="$BACKUP_DIR/panel-$STAMP.tar.gz"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

log "Дамп базы из контейнера $DB_CONTAINER"
docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists > "$TMP/db.sql"

if [[ ! -s "$TMP/db.sql" ]]; then
  log "ОШИБКА: дамп пустой, бэкап не создан"
  exit 1
fi

log "Конфиги панели из $PANEL_DIR"
if [[ -d "$PANEL_DIR" ]]; then
  cp -a "$PANEL_DIR"/.env "$TMP/" 2>/dev/null || true
  cp -a "$PANEL_DIR"/docker-compose.yml "$TMP/" 2>/dev/null || true
fi

tar -czf "$OUT" -C "$TMP" .
chmod 600 "$OUT"
log "Готово: $OUT ($(du -h "$OUT" | cut -f1))"

if [[ -n "$REMOTE" ]]; then
  log "Выгрузка на $REMOTE"
  rsync -a --timeout=60 "$OUT" "$REMOTE/" && log "Выгружено" || log "ОШИБКА выгрузки — бэкап только локальный"
else
  log "ВНИМАНИЕ: REMOTE не задан, бэкап лежит на той же машине, что и панель"
fi

log "Чищу старые, оставляю $KEEP"
ls -1t "$BACKUP_DIR"/panel-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

log "Всего копий: $(ls -1 "$BACKUP_DIR"/panel-*.tar.gz 2>/dev/null | wc -l)"
