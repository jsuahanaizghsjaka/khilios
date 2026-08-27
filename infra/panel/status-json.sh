#!/usr/bin/env bash
#
# khilios — генератор status.json для публичной страницы статуса.
#
# Запускается на панельной VPS systemd-таймером раз в минуту. Установщик:
#   /opt/khilios/infra/panel/install-status-monitor.sh
#
# Результат кладётся туда, откуда его отдаёт веб-сервер панели, а сайт на
# Vercel читает его по STATUS_URL и показывает.
#
# ЧТО ЭТА ПРОВЕРКА ЛОВИТ, А ЧТО НЕТ.
# Ловит: нода умерла, VPS выключилась, процесс упал, порт не слушается.
# Это большинство аварий, и они здесь видны сразу.
# НЕ ловит: блокировку у российских операторов. Панель стоит за границей,
# и для неё заблокированная нода выглядит совершенно живой. Такое приходит
# от пользователей — и тогда состояние выставляется вручную через файл
# override (см. ниже), после чего страница обновится в течение пяти минут.

set -euo pipefail

NODES_CONF="${NODES_CONF:-/etc/khilios/nodes.conf}"
OVERRIDE="${OVERRIDE:-/etc/khilios/status-override}"
OUT="${OUT:-/var/www/status/status.json}"
TIMEOUT="${TIMEOUT:-4}"
STATE_DIR="${STATE_DIR:-/var/lib/khilios-status}"
ALERT_ENV="${ALERT_ENV:-/etc/khilios/status-monitor.env}"

log() { printf '[%s] %s\n' "$(date -u +%F' '%T)" "$*"; }

command -v jq >/dev/null || { log "ОШИБКА: нужен jq (apt install jq)"; exit 1; }
[[ -f $NODES_CONF ]] || { log "ОШИБКА: нет $NODES_CONF"; exit 1; }

# nodes.conf — по строке на ноду, поля через |
#   имя|регион|адрес|порт|режим|транспорт
# Имя и регион уходят наружу, адрес и порт — нет. В status.json адреса не попадают:
# публичный список серверов это подарок тому, кто их блокирует.
#
#   fi-protect|Финляндия|hel1.example.net|443|Защита|XHTTP + Reality
#   fi-mobile|Финляндия|hel1.example.net|8443|Мобильный|gRPC + Reality

# status-override — ручное переопределение, по строке на ноду:
#   fi-1=down
# Ставится, когда пользователи сообщили о блокировке, а автопроверка её не видит.
# Убирается после переезда. Файла может не быть — это норма.

now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
entries=()
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

# Необязательный root-only файл:
#   STATUS_ALERT_BOT_TOKEN=...
#   STATUS_ALERT_CHAT_ID=...
# Алерты идут только владельцу. Пользователям статус показывается по кнопке.
if [[ -r $ALERT_ENV ]]; then
  # shellcheck disable=SC1090
  source "$ALERT_ENV"
fi
STATUS_ALERT_BOT_TOKEN="${STATUS_ALERT_BOT_TOKEN:-${BOT_TOKEN:-}}"
STATUS_ALERT_CHAT_ID="${STATUS_ALERT_CHAT_ID:-${ADMIN_TELEGRAM_ID:-}}"

alert_owner() {
  local message=$1
  [[ -n "${STATUS_ALERT_BOT_TOKEN:-}" && -n "${STATUS_ALERT_CHAT_ID:-}" ]] || return 0
  local payload
  payload=$(jq -nc --arg chat_id "$STATUS_ALERT_CHAT_ID" --arg text "$message" \
    '{chat_id: $chat_id, text: $text, disable_web_page_preview: true}')
  curl -fsS --max-time 8 -H 'Content-Type: application/json' \
    -d "$payload" "https://api.telegram.org/bot${STATUS_ALERT_BOT_TOKEN}/sendMessage" \
    >/dev/null || log "ПРЕДУПРЕЖДЕНИЕ: алерт владельцу не отправлен"
}

while IFS='|' read -r name region host port mode transport; do
  # пустые строки и комментарии
  [[ -z "${name// /}" || "$name" == \#* ]] && continue

  name="${name// /}"
  port="${port:-4443}"
  mode="${mode:-Основной}"
  transport="${transport:-TCP}"

  if [[ ! $host =~ ^[A-Za-z0-9._:-]+$ || ! $port =~ ^[0-9]+$ ]] \
      || (( port < 1 || port > 65535 )); then
    log "$name: некорректный адрес или порт в nodes.conf, строка пропущена"
    continue
  fi

  state_key=$(printf '%s' "$name" | tr -c 'A-Za-z0-9_.-' '_')
  failures_file="$STATE_DIR/$state_key.failures"
  previous_file="$STATE_DIR/$state_key.state"
  failures=0
  [[ -r $failures_file ]] && read -r failures < "$failures_file" || true
  [[ $failures =~ ^[0-9]+$ ]] || failures=0
  previous=unknown
  [[ -r $previous_file ]] && read -r previous < "$previous_file" || true

  state=degraded
  latency_ms=null
  started_ms=$(date +%s%3N)
  if timeout "$TIMEOUT" bash -c "</dev/tcp/$host/$port" 2>/dev/null; then
    failures=0
    state=up
    finished_ms=$(date +%s%3N)
    latency_ms=$((finished_ms - started_ms))

    # Это измерение не обещает скорость конкретному абоненту: оно показывает
    # отклик от панели до узла. Долгий ответ всё же полезен — такой узел не
    # стоит рекомендовать первым, даже если TCP-порт формально открыт.
    if ((latency_ms > 450)); then
      state=degraded
    fi
  else
    failures=$((failures + 1))
    # Одиночная потеря пакета не превращает рабочую локацию в аварию.
    # Down ставится только после трёх последовательных неудач.
    if (( failures >= 3 )); then
      failures=3
      state=down
    fi
  fi
  printf '%s\n' "$failures" > "$failures_file"

  # Ручное переопределение сильнее автопроверки: человек знает про
  # блокировку то, чего не знает TCP-соединение из-за границы.
  if [[ -f $OVERRIDE ]]; then
    forced=$(awk -F= -v wanted="$name" '$1 == wanted { value=$2 } END { print value }' \
      "$OVERRIDE" 2>/dev/null | tr -d '[:space:]' || true)
    if [[ -n "$forced" ]]; then
      case "$forced" in
        up|degraded|down)
          log "$name: автопроверка $state, переопределено вручную -> $forced"
          state="$forced"
          ;;
        *) log "$name: неизвестное значение в override: '$forced', игнорирую" ;;
      esac
    fi
  fi

  if [[ $state != "$previous" ]]; then
    if [[ $state == down ]]; then
      alert_owner "🔴 khilios: ${region} · ${mode} не отвечает три проверки подряд. Пользовательской рассылки нет; проверьте ноду и статус."
    elif [[ $previous == down && $state == up ]]; then
      alert_owner "🟢 khilios: ${region} · ${mode} снова отвечает."
    fi
  fi
  printf '%s\n' "$state" > "$previous_file"

  log "$name ($region · $mode): $state"

  entries+=("$(jq -nc \
    --arg name "$name" \
    --arg region "$region" \
    --arg mode "$mode" \
    --arg transport "$transport" \
    --arg state "$state" \
    --arg checked_at "$now" \
    --argjson latency_ms "$latency_ms" \
    '{name: $name, region: $region, mode: $mode, transport: $transport,
      state: $state, checked_at: $checked_at,
      latency_ms: $latency_ms}')")
done < "$NODES_CONF"

if ((${#entries[@]} == 0)); then
  log "ОШИБКА: в $NODES_CONF нет ни одной ноды, status.json не переписан"
  exit 1
fi

mkdir -p "$(dirname "$OUT")"
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

printf '%s\n' "${entries[@]}" \
  | jq -s --arg generated_at "$now" '{generated_at: $generated_at, nodes: .}' > "$TMP"

# Пишем атомарно: иначе сайт может успеть прочитать файл на середине записи
# и показать пустую таблицу вместо статуса.
mv "$TMP" "$OUT"
chmod 644 "$OUT"
trap - EXIT

log "Готово: $OUT (${#entries[@]} нод)"
