#!/usr/bin/env bash
#
# khilios — генератор status.json для публичной страницы статуса.
#
# Запускается на панельной VPS по cron раз в 5 минут:
#   */5 * * * * /opt/khilios/infra/panel/status-json.sh >> /var/log/khilios-status.log 2>&1
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

log() { printf '[%s] %s\n' "$(date -u +%F' '%T)" "$*"; }

command -v jq >/dev/null || { log "ОШИБКА: нужен jq (apt install jq)"; exit 1; }
[[ -f $NODES_CONF ]] || { log "ОШИБКА: нет $NODES_CONF"; exit 1; }

# nodes.conf — по строке на ноду, поля через |
#   имя|регион|адрес|порт
# Имя и регион уходят наружу, адрес и порт — нет. В status.json адреса не попадают:
# публичный список серверов это подарок тому, кто их блокирует.
#
#   fi-1|Финляндия|203.0.113.20|4443
#   nl-1|Нидерланды|198.51.100.7|9443

# status-override — ручное переопределение, по строке на ноду:
#   fi-1=down
# Ставится, когда пользователи сообщили о блокировке, а автопроверка её не видит.
# Убирается после переезда. Файла может не быть — это норма.

now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
entries=()

while IFS='|' read -r name region host port; do
  # пустые строки и комментарии
  [[ -z "${name// /}" || "$name" == \#* ]] && continue

  name="${name// /}"
  port="${port:-4443}"

  state=down
  latency_ms=null
  started_ms=$(date +%s%3N)
  if timeout "$TIMEOUT" bash -c "</dev/tcp/$host/$port" 2>/dev/null; then
    state=up
    finished_ms=$(date +%s%3N)
    latency_ms=$((finished_ms - started_ms))

    # Это измерение не обещает скорость конкретному абоненту: оно показывает
    # отклик от панели до узла. Долгий ответ всё же полезен — такой узел не
    # стоит рекомендовать первым, даже если TCP-порт формально открыт.
    if ((latency_ms > 450)); then
      state=degraded
    fi
  fi

  # Ручное переопределение сильнее автопроверки: человек знает про
  # блокировку то, чего не знает TCP-соединение из-за границы.
  if [[ -f $OVERRIDE ]]; then
    forced=$(grep -E "^${name}=" "$OVERRIDE" 2>/dev/null | tail -n1 | cut -d= -f2 | tr -d '[:space:]' || true)
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

  log "$name ($region): $state"

  entries+=("$(jq -nc \
    --arg name "$name" \
    --arg region "$region" \
    --arg state "$state" \
    --arg checked_at "$now" \
    --argjson latency_ms "$latency_ms" \
    '{name: $name, region: $region, state: $state, checked_at: $checked_at,
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
