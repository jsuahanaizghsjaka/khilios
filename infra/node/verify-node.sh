#!/usr/bin/env bash
#
# khilios — проверка ноды перед тем, как пускать на неё людей.
#
#   ./verify-node.sh <адрес> [dest] [ssh-порт]
#   ./verify-node.sh 203.0.113.20 www.cloudflare.com 2202
#
# Запускать С СВОЕЙ МАШИНЫ, а не с ноды: половина проверок в том и состоит,
# что нода выглядит снаружи так, как задумано.
#
# Зачем отдельный скрипт. deploy-node.sh отвечает на вопрос «отработал ли
# он», а не «работает ли нода». Между этими вопросами помещается: не тот
# dest, мёртвый xray при живом порте, открытый наружу порт панели и
# сертификат, по которому ноду видно насквозь. Всё это выясняется либо
# здесь за минуту, либо через неделю от пользователей.
#
# Проверка «с мобильного интернета» этот скрипт НЕ заменяет: блокировки
# живут у операторов, и снаружи РФ их не видно. Здесь проверяется то,
# что вообще можно проверить снаружи.

set -uo pipefail   # без -e: скрипт должен пройти все проверки, а не встать на первой

HOST="${1:-}"
DEST="${2:-www.cloudflare.com}"
SSH_PORT="${3:-}"
PORT=443

[[ -n "$HOST" ]] || { echo "Использование: $0 <адрес> [dest] [ssh-порт]" >&2; exit 2; }

ok()   { printf '  \033[1;32mok\033[0m    %s\n' "$*"; }
bad()  { printf '  \033[1;31mПЛОХО\033[0m %s\n' "$*"; FAILED=$((FAILED+1)); }
warn() { printf '  \033[1;33m  ?\033[0m   %s\n' "$*"; }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }

FAILED=0

command -v openssl >/dev/null || { echo "нужен openssl" >&2; exit 2; }

echo "Проверяю ноду $HOST (dest: $DEST)"

# --------------------------------------------------------------------------
head_ "1. Порт 443 открыт"
# --------------------------------------------------------------------------

if timeout 5 bash -c "</dev/tcp/$HOST/$PORT" 2>/dev/null; then
  ok "TCP $PORT принимает соединения"
else
  bad "TCP $PORT недоступен — xray не поднялся или файрвол закрыл"
fi

# --------------------------------------------------------------------------
head_ "2. Нода отвечает как настоящий $DEST"
# --------------------------------------------------------------------------
# Reality на чужие рукопожатия проксирует к настоящему dest. Значит для
# постороннего сканера нода обязана быть неотличима от него — включая
# сертификат. Если сертификат другой, маскировка не работает, и это
# видно любому, кто решит посмотреть.

node_cert() {
  timeout 10 openssl s_client -connect "$HOST:$PORT" -servername "$DEST" \
    </dev/null 2>/dev/null | openssl x509 -noout "$@" 2>/dev/null
}
real_cert() {
  timeout 10 openssl s_client -connect "$DEST:443" -servername "$DEST" \
    </dev/null 2>/dev/null | openssl x509 -noout "$@" 2>/dev/null
}

NODE_SUBJ=$(node_cert -subject)
NODE_ISSUER=$(node_cert -issuer)
NODE_NAMES=$(node_cert -ext subjectAltName | tr ',' '\n' | sed -n 's/.*DNS://p' | tr -d ' ')

if [[ -z "$NODE_SUBJ" ]]; then
  bad "TLS-рукопожатие не состоялось — нода не отвечает как TLS-сервер"
else
  ok "TLS-рукопожатие проходит"

  # Основная проверка: покрывает ли выданный сертификат сам DEST. Она не
  # требует второго запроса, поэтому не ломается, если настоящий сайт
  # отсюда недоступен, и прямо ловит главную ошибку — dest в конфиге
  # не тот, под который собирались маскироваться.
  covers=no
  while read -r name; do
    [[ -z "$name" ]] && continue
    if [[ "$name" == "$DEST" ]]; then covers=yes; break; fi
    # Подстановочное имя покрывает ровно ОДИН уровень: *.example.com — это
    # www.example.com, но не a.b.example.com. Сравниваем базу с DEST, у
    # которого срезана ровно одна метка, иначе проверка пропустит чужой dest.
    if [[ "$name" == \*.* && "${DEST#*.}" == "${name#\*.}" && "$DEST" == *.* ]]; then
      covers=yes; break
    fi
  done <<<"$NODE_NAMES"

  if [[ "$covers" == yes ]]; then
    ok "сертификат ноды выписан на $DEST"
  else
    bad "сертификат ноды НЕ покрывает $DEST — маскировка не та, что задумана"
    echo "        выдан на: ${NODE_SUBJ#subject=}"
    echo "        имена:    $(tr '\n' ' ' <<<"$NODE_NAMES")"
    echo "        Проверь dest в конфиге inbound."
  fi

  # Дополнительная проверка: тот же ли удостоверяющий центр, что у живого
  # сайта. Расходится — либо dest не тот, либо между вами и нодой стоит
  # перехват TLS, и тогда всем проверкам здесь верить нельзя.
  REAL_ISSUER=$(real_cert -issuer)
  if [[ -z "$REAL_ISSUER" ]]; then
    warn "настоящий $DEST отсюда недоступен, издателя сверить не с чем"
  elif [[ "$NODE_ISSUER" == "$REAL_ISSUER" ]]; then
    ok "издатель сертификата совпадает с настоящим $DEST"
  else
    bad "издатель НЕ совпадает с настоящим $DEST"
    echo "        нода:      ${NODE_ISSUER#issuer=}"
    echo "        настоящий: ${REAL_ISSUER#issuer=}"
  fi
fi

# Если вы сидите за корпоративным прокси с подменой сертификатов, проверки
# выше показывают его сертификат, а не сертификат ноды, и ничего не значат.
# Запускайте с обычной домашней сети.

# --------------------------------------------------------------------------
head_ "3. Dest пригоден для маскировки"
# --------------------------------------------------------------------------
# Reality требует от dest TLS 1.3 и HTTP/2. Сайт без них ломает маскировку
# тихо: соединение вроде есть, но выглядит оно неправильно.

TLS13=$(timeout 10 openssl s_client -connect "$DEST:443" -servername "$DEST" -tls1_3 \
        </dev/null 2>/dev/null | grep -c "TLSv1.3" || true)
if [[ "${TLS13:-0}" -gt 0 ]]; then
  ok "$DEST поддерживает TLS 1.3"
else
  bad "$DEST не отвечает по TLS 1.3 — как dest не годится"
fi

ALPN=$(timeout 10 openssl s_client -connect "$DEST:443" -servername "$DEST" -alpn h2 \
       </dev/null 2>/dev/null | grep -i "ALPN protocol" || true)
if grep -qi "h2" <<<"$ALPN"; then
  ok "$DEST поддерживает HTTP/2"
else
  warn "HTTP/2 у $DEST не подтвердился: $ALPN"
fi

# --------------------------------------------------------------------------
head_ "4. Наружу не торчит лишнее"
# --------------------------------------------------------------------------
# Порт ноды (remnanode) должен быть открыт только панели. Если он виден
# отсюда — значит виден и всем остальным.

for p in 2222 3000 5432 6379 8080; do
  if timeout 3 bash -c "</dev/tcp/$HOST/$p" 2>/dev/null; then
    bad "порт $p открыт наружу, а не должен"
  fi
done
ok "служебные порты снаружи закрыты"

if [[ -n "$SSH_PORT" ]]; then
  if timeout 5 bash -c "</dev/tcp/$HOST/$SSH_PORT" 2>/dev/null; then
    ok "SSH на $SSH_PORT отвечает"
  else
    bad "SSH на $SSH_PORT недоступен — как ты будешь чинить ноду в аварии?"
  fi
  if timeout 3 bash -c "</dev/tcp/$HOST/22" 2>/dev/null; then
    warn "порт 22 тоже открыт — перенос SSH не доведён до конца"
  fi
fi

# --------------------------------------------------------------------------
head_ "5. На самой ноде"
# --------------------------------------------------------------------------

if [[ -n "$SSH_PORT" ]] && command -v ssh >/dev/null 2>&1; then
  # Кавычки одинарные намеренно: команда должна раскрываться на ноде, а не здесь.
  # shellcheck disable=SC2016
  R=$(timeout 20 ssh -p "$SSH_PORT" -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
        "root@$HOST" '
          echo "BBR=$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null)"
          echo "NODE=$(docker inspect -f "{{.State.Status}}" remnanode 2>/dev/null)"
          echo "DISK=$(df --output=pcent / | tail -1 | tr -d " %")"
        ' 2>/dev/null || true)

  if [[ -z "$R" ]]; then
    warn "по SSH зайти не удалось, проверки на ноде пропущены"
  else
    if grep -q "BBR=bbr" <<<"$R"; then
      ok "BBR включён"
    else
      warn "BBR не активен, скорость будет хуже"
    fi

    if grep -q "NODE=running" <<<"$R"; then
      ok "контейнер remnanode работает"
    else
      bad "remnanode не в состоянии running"
    fi

    D=$(sed -n 's/^DISK=//p' <<<"$R")
    if [[ -n "$D" ]] && (( D > 80 )); then
      bad "диск занят на ${D}% — логи съедят остаток и нода встанет"
    elif [[ -n "$D" ]]; then
      ok "диск занят на ${D}%"
    fi
  fi
else
  warn "ssh-порт не указан, проверки на самой ноде пропущены"
fi

# --------------------------------------------------------------------------
echo
if (( FAILED == 0 )); then
  printf '\033[1;32mВсё чисто.\033[0m Осталось единственное, что нельзя проверить отсюда:\n'
  echo "подключиться с мобильного интернета РФ. Блокировки живут у операторов,"
  echo "и снаружи их не видно ни одной из проверок выше."
  exit 0
else
  printf '\033[1;31mПровалено проверок: %s.\033[0m Людей на ноду не пускать.\n' "$FAILED"
  exit 1
fi
