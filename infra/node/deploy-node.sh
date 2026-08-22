#!/usr/bin/env bash
#
# khilios — разворачивание ноды с нуля.
#
# Запускать от root на ЧИСТОЙ Ubuntu 22.04 / 24.04.
# Цель — 20 минут от «купил VPS» до «нода в панели и раздаёт».
#
#   cp node.env.example node.env && nano node.env && ./deploy-node.sh
#
# Скрипт идемпотентный: повторный запуск на той же машине безопасен.
#
# ВАЖНО: правки руками после скрипта — это баг в скрипте.
# Не чини на месте: почини здесь и прогони заново. Иначе через месяц
# ни одна нода не будет похожа на другую, а в блокировку они уходят пачками.

set -euo pipefail

cd "$(dirname "$0")"

log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m [!]\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------------------
# 0. Конфиг и проверки
# --------------------------------------------------------------------------

[[ $EUID -eq 0 ]] || die "Запускать от root."
[[ -f node.env ]] || die "Нет node.env. Скопируй node.env.example и заполни."

# shellcheck disable=SC1091
source ./node.env

: "${NODE_NAME:?NODE_NAME не задан в node.env}"
: "${SSL_CERT:?SSL_CERT не задан — возьми в панели: Nodes -> Create -> строка SSL_CERT}"
: "${PANEL_IP:?PANEL_IP не задан — IP панельной VPS, только ей открывается порт ноды}"
APP_PORT="${APP_PORT:-2222}"
SSH_PORT="${SSH_PORT:-22}"
HARDEN_SSH="${HARDEN_SSH:-yes}"

grep -qiE 'ubuntu' /etc/os-release || warn "Не Ubuntu. Скрипт писан под Ubuntu 22.04/24.04, дальше на свой риск."

log "Нода: $NODE_NAME | порт ноды: $APP_PORT | SSH: $SSH_PORT | панель: $PANEL_IP"

export DEBIAN_FRONTEND=noninteractive

# --------------------------------------------------------------------------
# 1. Базовые пакеты
# --------------------------------------------------------------------------

log "Обновление системы и базовые пакеты"
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq ca-certificates curl gnupg ufw fail2ban chrony jq

timedatectl set-timezone UTC
systemctl enable --now chrony >/dev/null 2>&1 || true

# --------------------------------------------------------------------------
# 2. Сеть: BBR и лимиты
# --------------------------------------------------------------------------

log "Тюнинг сети (BBR, fq, лимиты файловых дескрипторов)"
cat > /etc/sysctl.d/99-khilios.conf <<'EOF'
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_fastopen = 3
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_mtu_probing = 1
net.ipv4.ip_forward = 1
fs.file-max = 1000000
EOF
sysctl --system >/dev/null

cat > /etc/security/limits.d/99-khilios.conf <<'EOF'
* soft nofile 1000000
* hard nofile 1000000
EOF

if [[ "$(sysctl -n net.ipv4.tcp_congestion_control)" != "bbr" ]]; then
  warn "BBR не включился. Ядро без поддержки? Не блокер, но скорость будет хуже."
fi

# --------------------------------------------------------------------------
# 3. SSH
# --------------------------------------------------------------------------
# Порядок важен: сначала правило файрвола на новый порт, потом рестарт sshd.
# Пароли отключаем ТОЛЬКО если ключ уже лежит — иначе запрёмся снаружи.

if [[ "$HARDEN_SSH" == "yes" ]]; then
  log "Настройка SSH (порт $SSH_PORT)"

  KEYS_FILE="/root/.ssh/authorized_keys"
  if [[ -s "$KEYS_FILE" ]]; then
    DISABLE_PASSWORDS=yes
  else
    DISABLE_PASSWORDS=no
    warn "В $KEYS_FILE нет ключей — вход по паролю оставлен включённым."
    warn "Положи ключ и перезапусти скрипт, иначе нода висит с паролем наружу."
  fi

  cat > /etc/ssh/sshd_config.d/99-khilios.conf <<EOF
Port $SSH_PORT
PermitRootLogin prohibit-password
PubkeyAuthentication yes
PasswordAuthentication $([[ $DISABLE_PASSWORDS == yes ]] && echo no || echo yes)
ChallengeResponseAuthentication no
X11Forwarding no
ClientAliveInterval 60
EOF

  # Ubuntu 23.04+ слушает ssh через systemd-сокет: тогда порт задаёт сокет,
  # а Port из sshd_config игнорируется. Правим сокет, иначе новый порт не
  # откроется, а старый закроет файрвол — и нода останется без входа.
  if systemctl is-active --quiet ssh.socket; then
    install -d /etc/systemd/system/ssh.socket.d
    cat > /etc/systemd/system/ssh.socket.d/99-khilios.conf <<EOF
[Socket]
ListenStream=
ListenStream=$SSH_PORT
EOF
    systemctl daemon-reload
    systemctl restart ssh.socket
  else
    systemctl restart ssh 2>/dev/null || systemctl restart sshd
  fi

  # Проверяем факт, а не намерение: если новый порт не слушается, закрывать
  # старый нельзя. На панели этот случай однажды стоил доступа к машине.
  sleep 1
  if ss -tln 2>/dev/null | grep -qE "[:.]${SSH_PORT}([[:space:]]|$)"; then
    log "SSH слушает $SSH_PORT"
  else
    warn "SSH НЕ слушает $SSH_PORT — порт 22 останется открытым."
  fi

  warn "НЕ ЗАКРЫВАЙ текущую сессию, пока не проверишь вход в новом окне: ssh -p $SSH_PORT root@<ip>"
fi

# --------------------------------------------------------------------------
# 4. Файрвол
# --------------------------------------------------------------------------
# Наружу смотрят только 443 (VLESS/Reality) и SSH.
# Порт ноды открыт исключительно панели — он не должен быть виден сканерам.

log "Файрвол"
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow "$SSH_PORT"/tcp comment 'ssh' >/dev/null

# Порт 22 остаётся открытым намеренно — страховка на случай, если SSH не
# переехал на новый порт. Закрывается вручную после проверки входа:
#   ufw delete allow 22/tcp
# Нода без входа — это не «неудобно», это переустановка с нуля.
ufw allow 22/tcp comment 'ssh-fallback: закрыть после проверки' >/dev/null

ufw allow 443/tcp comment 'vless-reality' >/dev/null
ufw allow 443/udp comment 'vless-reality-udp' >/dev/null
ufw allow from "$PANEL_IP" to any port "$APP_PORT" proto tcp comment 'remnanode <- panel' >/dev/null
ufw --force enable >/dev/null
ufw status numbered

systemctl enable --now fail2ban >/dev/null 2>&1 || true

# --------------------------------------------------------------------------
# 5. Docker
# --------------------------------------------------------------------------

if ! command -v docker >/dev/null 2>&1; then
  log "Установка Docker"
  curl -fsSL https://get.docker.com | sh
else
  log "Docker уже стоит, пропускаю"
fi
systemctl enable --now docker >/dev/null

# Предустановленный образом Docker может быть БЕЗ плагина compose — тогда
# `docker compose up` не поднимет ноду. get.docker.com плагин приносит,
# предустановленный — нет. Проверяем по факту.
if ! docker compose version >/dev/null 2>&1; then
  log "Ставлю плагин docker compose"
  apt-get install -y -qq docker-compose-v2 2>/dev/null \
    || apt-get install -y -qq docker-compose-plugin \
    || die "Не удалось поставить плагин docker compose. Поставь вручную и перезапусти."
fi

# Логи контейнеров без ротации съедают диск за пару недель.
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "3" }
}
EOF
systemctl restart docker

# --------------------------------------------------------------------------
# 6. Remnawave node
# --------------------------------------------------------------------------
# SSL_CERT — публичный сертификат панели, панель отдаёт его при создании ноды.
# Контракт переменных сверяй с версией образа, которую разворачиваешь:
#   docker run --rm remnawave/node:latest env

log "Разворачивание remnanode"
install -d -m 700 /opt/remnanode

cat > /opt/remnanode/.env <<EOF
APP_PORT=$APP_PORT
$SSL_CERT
EOF
chmod 600 /opt/remnanode/.env

cat > /opt/remnanode/docker-compose.yml <<'EOF'
services:
  remnanode:
    image: remnawave/node:latest
    container_name: remnanode
    hostname: remnanode
    restart: always
    network_mode: host
    env_file:
      - .env
    logging:
      driver: json-file
      options:
        max-size: "20m"
        max-file: "3"
EOF

cd /opt/remnanode
docker compose pull -q
docker compose up -d --force-recreate

# --------------------------------------------------------------------------
# 7. Проверка
# --------------------------------------------------------------------------

log "Проверка"
sleep 5

docker compose ps

if ss -tlnp 2>/dev/null | grep -q ":$APP_PORT "; then
  echo "  [ok] порт $APP_PORT слушается"
else
  warn "порт $APP_PORT не слушается — смотри: docker logs remnanode"
fi

PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || echo '?')"

cat <<EOF

--------------------------------------------------------------------
 Нода "$NODE_NAME" готова.

 IP:          $PUBLIC_IP
 Порт ноды:   $APP_PORT   (открыт только для $PANEL_IP)
 SSH:         ssh -p $SSH_PORT root@$PUBLIC_IP

 Дальше в панели (docs/architecture.md, набор протоколов):
   1. Nodes -> Create -> адрес $PUBLIC_IP, порт $APP_PORT
   2. Два инбаунда на этой ноде, оба на 443, разные транспорты — не мешают
      друг другу и не открывают лишних портов:
        - VLESS + Reality, TCP 443 — основной
        - VLESS + XHTTP, UDP 443 (QUIC) — скоростной
      Третьего протокола на эту машину НЕ добавлять: каждый лишний
      слушатель — отпечаток для DPI-сканера, палит и остальные тоже.
   3. Оба инбаунда — в один Internal Squad, чтобы подписка отдавала сразу
      обе точки подключения одному пользователю.
   4. Выдать тестового пользователя и проверить С МОБИЛЬНОГО ИНТЕРНЕТА,
      а не с домашнего Wi-Fi — блокировки живут у операторов. Проверить
      именно оба профиля: XHTTP по UDP режут чаще, чем TCP-Reality.

 Логи:        docker logs -f remnanode
 Перезапуск:  cd /opt/remnanode && docker compose restart
--------------------------------------------------------------------
EOF
