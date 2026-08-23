#!/usr/bin/env bash
#
# khilios — MTProto-прокси (mtg) с Fake TLS.
#
# Ставится на ОДНУ из нод. Это лид-магнит и вход в воронку, а не продукт:
# 1 апреля 2026 тысячи MTProxy-серверов отвалились за ночь. Считай его расходником
# и не строй ничего, что сломается вместе с ним.
#
#   MTG_DOMAIN=www.cloudflare.com MTG_PORT=2443 ./deploy-mtproto.sh
#
# Запускать от root, после deploy-node.sh.

set -euo pipefail

log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m [!]\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Запускать от root."

# Домен для Fake TLS: под него прокси маскируется. Нужен крупный живой сайт,
# который не заблокирован и до которого есть маршрут из РФ.
MTG_DOMAIN="${MTG_DOMAIN:-www.cloudflare.com}"

# 4443 и 8443 заняты Reality/XHTTP, поэтому MTProto получает отдельный порт.
MTG_PORT="${MTG_PORT:-2443}"

CONFIG=/etc/mtg.toml

log "Установка mtg (домен маскировки: $MTG_DOMAIN, порт: $MTG_PORT)"

apt-get update -qq
apt-get install -y -qq curl jq tar

if ! command -v mtg >/dev/null 2>&1; then
  ARCH=$(uname -m)
  case "$ARCH" in
    x86_64)  MTG_ARCH=amd64 ;;
    aarch64) MTG_ARCH=arm64 ;;
    *) die "Неизвестная архитектура: $ARCH" ;;
  esac

  URL=$(curl -fsSL https://api.github.com/repos/9seconds/mtg/releases/latest \
        | jq -r --arg a "linux-$MTG_ARCH" '.assets[] | select(.name | contains($a)) | .browser_download_url' \
        | head -n1)
  [[ -n "$URL" ]] || die "Не нашёл релиз mtg под linux-$MTG_ARCH. Скачай вручную с github.com/9seconds/mtg/releases"

  log "Скачиваю $URL"
  TMP=$(mktemp -d)
  curl -fsSL "$URL" -o "$TMP/mtg.tar.gz"
  tar -xzf "$TMP/mtg.tar.gz" -C "$TMP"
  install -m 755 "$(find "$TMP" -name mtg -type f | head -n1)" /usr/local/bin/mtg
  rm -rf "$TMP"
fi

mtg --version

# --------------------------------------------------------------------------
# Секрет и конфиг
# --------------------------------------------------------------------------
# Секрет генерируется один раз. Перегенерация = все выданные ссылки мертвы,
# поэтому при повторном запуске скрипта старый секрет сохраняется.

if [[ -f $CONFIG ]] && grep -q '^secret' $CONFIG; then
  SECRET=$(grep '^secret' $CONFIG | cut -d'"' -f2)
  log "Использую существующий секрет (ссылки у людей не сломаются)"
else
  SECRET=$(mtg generate-secret --hex "$MTG_DOMAIN")
  log "Сгенерирован новый секрет"
fi

cat > $CONFIG <<EOF
secret = "$SECRET"
bind-to = "0.0.0.0:$MTG_PORT"

[defense.anti-replay]
enabled = true
max-size = "1mib"
EOF
chmod 600 $CONFIG

# adtag — спонсируемый канал, тег берётся у @MTProxybot.
# Поддержка adtag зависит от версии mtg: проверь `mtg --help` и README своей версии.
# Если версия не умеет — вариант официальный MTProxy (флаг -P <tag>), он умеет точно,
# но без Fake TLS. Fake TLS сейчас важнее: без маскировки прокси живёт считаные недели.
# Прежде чем раздавать ссылку, реши этот вопрос — иначе канал не будет расти,
# а прокси ради канала и ставится.

cat > /etc/systemd/system/mtg.service <<EOF
[Unit]
Description=mtg MTProto proxy
After=network.target

[Service]
ExecStart=/usr/local/bin/mtg run $CONFIG
Restart=always
RestartSec=3
LimitNOFILE=1000000
DynamicUser=yes
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now mtg
sleep 2
systemctl is-active --quiet mtg || die "mtg не поднялся: journalctl -u mtg -n 50"

command -v ufw >/dev/null && ufw allow "$MTG_PORT"/tcp comment 'mtproto' >/dev/null

log "Готово. Ссылки для раздачи:"
mtg access $CONFIG | jq -r '.. | strings | select(startswith("tg://") or startswith("https://t.me"))' 2>/dev/null \
  || mtg access $CONFIG

cat <<EOF

--------------------------------------------------------------------
 Проверь до раздачи:
   1. Ссылка открывается в Telegram и прокси подключается
   2. Спонсируемый канал виден в клиенте (иначе adtag не работает)
   3. Порт $MTG_PORT доступен снаружи: nc -zv <ip> $MTG_PORT

 Статус:   systemctl status mtg
 Логи:     journalctl -u mtg -f
 Конфиг:   $CONFIG
--------------------------------------------------------------------
EOF
