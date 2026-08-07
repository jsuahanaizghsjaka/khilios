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

# Бот. У него своя база, и в дамп панели она НЕ попадает: панель знает про
# ключи и трафик, а подписки, оплаты и начисленные дни живут у бота.
# Если это не заполнить, при потере VPS панель восстановится как ни в чём
# не бывало, а кто за что платил — исчезнет. Хуже всего то, что выяснится
# это в момент восстановления, когда уже поздно.
BOT_DIR="${BOT_DIR:-/opt/khilios-bot}"
BOT_DB_CONTAINER="${BOT_DB_CONTAINER:-}"   # пусто, если у бота база в файле
BOT_DB_USER="${BOT_DB_USER:-postgres}"
BOT_DB_NAME="${BOT_DB_NAME:-postgres}"

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

# --- Бот ---

if [[ -n "$BOT_DB_CONTAINER" ]]; then
  log "Дамп базы бота из контейнера $BOT_DB_CONTAINER"
  if docker exec "$BOT_DB_CONTAINER" pg_dump -U "$BOT_DB_USER" -d "$BOT_DB_NAME" \
       --clean --if-exists > "$TMP/bot-db.sql" 2>/dev/null && [[ -s "$TMP/bot-db.sql" ]]; then
    log "База бота сохранена"
  else
    # Не валим весь бэкап: панель уже выгружена, и потерять её из-за бота
    # было бы обменом плохого на худшее. Но и молчать нельзя.
    log "ОШИБКА: база бота не выгрузилась. Бэкап НЕПОЛНЫЙ, разберись сегодня"
    rm -f "$TMP/bot-db.sql"
  fi
elif [[ -d "$BOT_DIR" ]]; then
  log "У бота не задан BOT_DB_CONTAINER — забираю каталог целиком"
fi

if [[ -d "$BOT_DIR" ]]; then
  # Файловая база (sqlite и подобное) и конфиг бота. node_modules и .git
  # в бэкапе не нужны: они восстанавливаются из репозитория за минуту,
  # а размер копии раздувают в разы.
  #
  # Копируем через tar, а не rsync: rsync здесь нужен только для выгрузки
  # наружу, и если его вдруг нет, каталог бота молча уезжал пустым —
  # бэкап выглядел успешным, а данных бота в нём не было.
  mkdir -p "$TMP/bot"
  if tar -cf - -C "$BOT_DIR" \
        --exclude=.git --exclude=node_modules --exclude=__pycache__ \
        --exclude='*.log' . 2>/dev/null | tar -xf - -C "$TMP/bot" 2>/dev/null; then
    log "Каталог бота сохранён"
  else
    log "ОШИБКА: каталог бота не скопирован. Бэкап НЕПОЛНЫЙ"
  fi
fi

tar -czf "$OUT" -C "$TMP" .
chmod 600 "$OUT"
log "Готово: $OUT ($(du -h "$OUT" | cut -f1))"

if [[ -n "$REMOTE" ]] && ! command -v rsync >/dev/null 2>&1; then
  log "ОШИБКА: REMOTE задан, но rsync не установлен — копия наружу НЕ уехала"
  log "        apt-get install -y rsync"
elif [[ -n "$REMOTE" ]]; then
  log "Выгрузка на $REMOTE"
  if rsync -a --timeout=60 "$OUT" "$REMOTE/"; then
    log "Выгружено"
  else
    log "ОШИБКА выгрузки — бэкап только локальный"
  fi
else
  log "ВНИМАНИЕ: REMOTE не задан, бэкап лежит на той же машине, что и панель"
fi

log "Чищу старые, оставляю $KEEP"
# Имена вида panel-YYYYmmdd-HHMMSS.tar.gz, поэтому сортировка по алфавиту
# совпадает с сортировкой по времени. sort -r — новые сверху, tail — всё лишнее.
mapfile -t stale < <(find "$BACKUP_DIR" -maxdepth 1 -name 'panel-*.tar.gz' | sort -r | tail -n +$((KEEP + 1)))
if ((${#stale[@]} > 0)); then
  rm -f "${stale[@]}"
  log "Удалено: ${#stale[@]}"
fi

log "Всего копий: $(find "$BACKUP_DIR" -maxdepth 1 -name 'panel-*.tar.gz' | wc -l)"
