#!/usr/bin/env bash
#
# khilios — разворачивание Telegram-бота.
#
# Ставится на ПАНЕЛЬНУЮ VPS, рядом с панелью. Отдельная машина боту не нужна:
# трафик он не носит, а к API панели ходит по localhost — то есть API панели
# не приходится открывать наружу вообще.
#
#   cp bot.env.example bot.env && nano bot.env && ./deploy-bot.sh
#
# ПРО LONG POLLING.
# Бот работает опросом, а не вебхуком, и это осознанно. Вебхук требует
# открытого наружу HTTPS-эндпоинта — то есть ещё одной публичной точки на
# машине, где лежит база всех пользователей и ключи. Ради 15-30 клиентов
# такой размен не нужен: опрос ничего не открывает и при этой нагрузке
# неотличим по скорости.
#
# Какой именно бот — задаётся в bot.env. План допускает Bedolaga,
# remnawave-shopbot или аналог: скрипт готовит машину и окружение, а сам
# бот ставится из своего репозитория своим compose.

set -euo pipefail

cd "$(dirname "$0")"

log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m [!]\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------------------
# 0. Конфиг
# --------------------------------------------------------------------------

[[ $EUID -eq 0 ]] || die "Запускать от root."
[[ -f bot.env ]] || die "Нет bot.env. Скопируй bot.env.example и заполни."

# shellcheck disable=SC1091
source ./bot.env

: "${BOT_REPO:?BOT_REPO не задан — репозиторий выбранного бота}"
: "${BOT_TOKEN:?BOT_TOKEN не задан — токен от @BotFather}"
: "${PANEL_API_URL:?PANEL_API_URL не задан, обычно http://127.0.0.1:3000}"
: "${PANEL_API_TOKEN:?PANEL_API_TOKEN не задан — создаётся в панели}"
: "${ADMIN_TELEGRAM_ID:?ADMIN_TELEGRAM_ID не задан — ваш Telegram ID}"
BOT_DIR="${BOT_DIR:-/opt/khilios-bot}"
BOT_BRANCH="${BOT_BRANCH:-main}"

command -v docker >/dev/null 2>&1 || die "Нет Docker. Сначала deploy-panel.sh."

# Панель должна быть жива: бот без неё поднимется, но работать не будет,
# и разбираться в этом потом дороже, чем упасть сейчас.
if ! curl -fsS --max-time 5 -o /dev/null "$PANEL_API_URL" 2>/dev/null; then
  warn "Панель не отвечает на $PANEL_API_URL."
  warn "Бот без неё не выдаст ни одного ключа. Проверь: docker compose ps в /opt/remnawave"
fi

log "Бот: $BOT_REPO ($BOT_BRANCH) -> $BOT_DIR"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl

# --------------------------------------------------------------------------
# 1. Код бота
# --------------------------------------------------------------------------

if [[ -d "$BOT_DIR/.git" ]]; then
  log "Обновляю существующую установку"
  git -C "$BOT_DIR" fetch --quiet origin "$BOT_BRANCH"
  git -C "$BOT_DIR" checkout --quiet "$BOT_BRANCH"
  git -C "$BOT_DIR" pull --quiet origin "$BOT_BRANCH"
else
  log "Клонирую"
  git clone --quiet --branch "$BOT_BRANCH" "$BOT_REPO" "$BOT_DIR"
fi

chmod 700 "$BOT_DIR"

# --------------------------------------------------------------------------
# 2. Секреты
# --------------------------------------------------------------------------
# Токен бота и токен платёжки — самые опасные строки во всём проекте.
# С токеном бота чужой человек пишет от вашего имени всем вашим клиентам.

log "Окружение"

ENV_FILE="$BOT_DIR/.env"

if [[ ! -f $ENV_FILE ]]; then
  for sample in .env.example .env.sample env.example; do
    if [[ -f "$BOT_DIR/$sample" ]]; then
      cp "$BOT_DIR/$sample" "$ENV_FILE"
      log "Взял за основу $sample"
      break
    fi
  done
  [[ -f $ENV_FILE ]] || : > "$ENV_FILE"
fi

# Дописываем свои значения в конец: у большинства загрузчиков .env
# последнее определение побеждает, а исходный шаблон остаётся на виду
# со всеми комментариями к остальным переменным.
{
  echo ""
  echo "# --- khilios: добавлено deploy-bot.sh $(date -u +%F) ---"
  echo "BOT_TOKEN=$BOT_TOKEN"
  echo "TELEGRAM_BOT_TOKEN=$BOT_TOKEN"
  echo "PANEL_API_URL=$PANEL_API_URL"
  echo "REMNAWAVE_URL=$PANEL_API_URL"
  echo "PANEL_API_TOKEN=$PANEL_API_TOKEN"
  echo "REMNAWAVE_TOKEN=$PANEL_API_TOKEN"
  echo "ADMIN_TELEGRAM_ID=$ADMIN_TELEGRAM_ID"
  echo "ADMIN_IDS=$ADMIN_TELEGRAM_ID"
  [[ -n "${PAYMENT_TOKEN:-}" ]] && echo "PAYMENT_TOKEN=$PAYMENT_TOKEN"
  [[ -n "${SUPPORT_URL:-}" ]]   && echo "SUPPORT_URL=$SUPPORT_URL"
  [[ -n "${OFFER_URL:-}" ]]     && echo "OFFER_URL=$OFFER_URL"
  [[ -n "${PRIVACY_URL:-}" ]]   && echo "PRIVACY_URL=$PRIVACY_URL"
} >> "$ENV_FILE"

chmod 600 "$ENV_FILE"

warn "Имена переменных у разных ботов разные — скрипт пишет несколько"
warn "вариантов сразу. Открой $ENV_FILE и убери лишние, оставив те,"
warn "что понимает твой бот. Дубли с чужими именами не опасны, но мешают."

# --------------------------------------------------------------------------
# 3. Запуск
# --------------------------------------------------------------------------

cd "$BOT_DIR"
[[ -f docker-compose.yml || -f compose.yml ]] \
  || die "В репозитории нет compose-файла. Смотри README бота: возможно, он ставится иначе."

log "Запуск"
docker compose pull -q || warn "pull не прошёл, продолжаю"
docker compose up -d

# --------------------------------------------------------------------------
# 4. Проверка
# --------------------------------------------------------------------------

log "Проверка"
sleep 6
docker compose ps

# Проверяем, что токен вообще рабочий, до того как ждать сообщений в чате.
BOT_INFO=$(curl -fsS --max-time 10 "https://api.telegram.org/bot$BOT_TOKEN/getMe" 2>/dev/null || echo "")
if echo "$BOT_INFO" | grep -q '"ok":true'; then
  BOT_NAME=$(echo "$BOT_INFO" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')
  echo "  [ok] токен рабочий, бот @$BOT_NAME"
else
  warn "Telegram не принял токен. Проверь BOT_TOKEN у @BotFather."
fi

# Вебхук и опрос несовместимы: если у бота остался вебхук от прошлых
# экспериментов, опрос не получит ни одного сообщения, и выглядеть это
# будет как «бот молчит без ошибок» — худший вид поломки.
WH=$(curl -fsS --max-time 10 "https://api.telegram.org/bot$BOT_TOKEN/getWebhookInfo" 2>/dev/null || echo "")
WH_URL=$(echo "$WH" | sed -n 's/.*"url":"\([^"]*\)".*/\1/p')
if [[ -n "$WH_URL" ]]; then
  warn "У бота установлен вебхук: $WH_URL"
  warn "При работе опросом он должен быть снят, иначе бот молча не получит ничего:"
  warn "  curl -s 'https://api.telegram.org/bot\$BOT_TOKEN/deleteWebhook'"
else
  echo "  [ok] вебхук не установлен, опрос будет работать"
fi

cat <<EOF

--------------------------------------------------------------------
 Бот развёрнут в $BOT_DIR

 Дальше — настройка внутри бота. Список того, что должно быть
 включено и выключено именно в нашем проекте:

   docs/bot-checklist.md

 Там же то, что легко забыть и дорого вспомнить:
   - рефералка ВЫКЛЮЧЕНА до ответа юриста
   - автопродления НЕТ, сайт это обещает
   - один триал на аккаунт, иначе триал выносят за вечер
   - HWID-лимит включается в панели, не в боте

 ВАЖНО: добавь бота в бэкап. Если у него своя база, она не попадает
 в дамп панели, и при потере VPS уедут подписки и история оплат.
 См. BOT_DIR и BOT_DB_CONTAINER в infra/panel/backup.sh

 Логи:       cd $BOT_DIR && docker compose logs -f
 Перезапуск: cd $BOT_DIR && docker compose restart
--------------------------------------------------------------------
EOF
