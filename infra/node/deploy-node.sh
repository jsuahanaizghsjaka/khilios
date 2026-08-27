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
: "${PANEL_IP:?PANEL_IP не задан — IP панельной VPS, только ей открывается порт ноды}"

# Remnawave 3 использует NODE_PORT + SECRET_KEY. Старые установки ноды
# использовали APP_PORT + SSL_CERT. Поддерживаем обе схемы, чтобы повторный
# запуск скрипта не отрезал уже подключённую к панели ноду.
APP_PORT="${NODE_PORT:-${APP_PORT:-2222}}"
if [[ -n "${SECRET_KEY:-}" ]]; then
  REMNAWAVE_ENV_MODE=secret_key
elif [[ -n "${SSL_CERT:-}" ]]; then
  REMNAWAVE_ENV_MODE=ssl_cert
else
  die "Нет SECRET_KEY (Remnawave 3) или SSL_CERT (старая нода) в node.env."
fi
SSH_PORT="${SSH_PORT:-22}"
HARDEN_SSH="${HARDEN_SSH:-yes}"
VPN_TCP_PORTS="${VPN_TCP_PORTS:-443 4443 8443}"
# В отличие от TCP пустое значение здесь осмысленно: UDP/Hysteria2 нельзя
# включать до отдельного canary-теста. Используем `-`, а не `:-`, чтобы
# VPN_UDP_PORTS="" действительно оставлял UDP-порты закрытыми.
VPN_UDP_PORTS="${VPN_UDP_PORTS-443}"
# Панель 3.2.3 несовместима с Remnawave Node 3.3.x: новый Node отвечает
# TLS alert 40 ещё до запуска Xray. Версию образа закрепляем явно, а не
# используем latest. При обновлении панели этот параметр меняется отдельно
# и одинаково на всех нодах после сверки официальной матрицы совместимости.
REMNAWAVE_NODE_IMAGE="${REMNAWAVE_NODE_IMAGE:-remnawave/node:3.2.2}"

read -r -a VPN_TCP_PORT_LIST <<< "$VPN_TCP_PORTS"
read -r -a VPN_UDP_PORT_LIST <<< "$VPN_UDP_PORTS"

(( ${#VPN_TCP_PORT_LIST[@]} > 0 )) || die "VPN_TCP_PORTS не содержит портов."

for vpn_port in "${VPN_TCP_PORT_LIST[@]}" "${VPN_UDP_PORT_LIST[@]}"; do
  [[ "$vpn_port" =~ ^[0-9]+$ ]] \
    && (( vpn_port >= 1 && vpn_port <= 65535 )) \
    || die "Некорректный VPN-порт: $vpn_port"
done

grep -qiE 'ubuntu' /etc/os-release || warn "Не Ubuntu. Скрипт писан под Ubuntu 22.04/24.04, дальше на свой риск."

log "Нода: $NODE_NAME | порт ноды: $APP_PORT | SSH: $SSH_PORT | панель: $PANEL_IP"
log "VPN TCP: $VPN_TCP_PORTS | VPN UDP: ${VPN_UDP_PORTS:-нет}"

export DEBIAN_FRONTEND=noninteractive

# --------------------------------------------------------------------------
# 1. Базовые пакеты
# --------------------------------------------------------------------------

log "Обновление системы и базовые пакеты"
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq ca-certificates curl gnupg ufw fail2ban chrony jq \
  unattended-upgrades

timedatectl set-timezone UTC
systemctl enable --now chrony >/dev/null 2>&1 || true

# --------------------------------------------------------------------------
# 2. Сеть: BBR и лимиты
# --------------------------------------------------------------------------

log "Тюнинг сети (BBR, fq, лимиты файловых дескрипторов)"
# В некоторых образах tcp_bbr собран модулем и не подгружается от одного
# sysctl. Без этого ядро молча оставляет cubic/hybla, хотя конфиг просит BBR.
if modprobe tcp_bbr 2>/dev/null; then
  printf 'tcp_bbr\n' > /etc/modules-load.d/khilios-bbr.conf
else
  warn "Модуль tcp_bbr недоступен: оставляю алгоритм ядра по умолчанию."
fi
cat > /etc/sysctl.d/99-khilios.conf <<'EOF'
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_fastopen = 3
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.core.netdev_max_backlog = 16384
net.core.somaxconn = 32768
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_notsent_lowat = 16384
net.ipv4.tcp_fin_timeout = 15
net.ipv4.ip_local_port_range = 10000 65535
net.ipv4.ip_forward = 1
net.netfilter.nf_conntrack_max = 262144
fs.file-max = 1048576
EOF
sysctl --system >/dev/null

cat > /etc/security/limits.d/99-khilios.conf <<'EOF'
* soft nofile 1048576
* hard nofile 1048576
root soft nofile 1048576
root hard nofile 1048576
EOF

if [[ "$(sysctl -n net.ipv4.tcp_congestion_control)" != "bbr" ]]; then
  warn "BBR не включился. Ядро без поддержки? Не блокер, но скорость будет хуже."
fi

# --------------------------------------------------------------------------
# 2b. MSS clamping — лечение «подключается, но ничего не грузится»
# --------------------------------------------------------------------------
# Симптом, ради которого это здесь: на мобильном интернете VPN «работает»
# ровно до первого крупного ответа. Handshake проходит (пакеты мелкие),
# страница начинает грузиться и виснет.
#
# Причина. У сотовых операторов трафик абонента идёт в туннеле GTP, и MTU
# на этом участке меньше 1500 — обычно 1400-1440. Наша нода про это не
# знает и анонсирует MSS под 1500. Пакет не влезает, роутер по пути обязан
# прислать ICMP «Fragmentation Needed» — и вот его-то мобильные сети и
# сжирают. Отправитель не узнаёт, что пакет не дошёл, и молча ретранслирует
# один и тот же сегмент до таймаута. Это классический PMTU black hole, и
# со стороны он выглядит именно как «VPN плохо работает на мобильном».
#
# Лечение: подписывать в каждом SYN такой MSS, который реально пролезает.
# clamp-mss-to-pmtu берёт его из известного MTU маршрута, а не из догадки.
#
# tcp_mtu_probing выше — второй эшелон: он вытягивает соединение, если MSS
# всё равно оказался велик. Одного его мало, он реагирует уже на потери.

log "MSS clamping (лечит зависания на мобильных сетях)"
apt-get install -y -qq iptables >/dev/null 2>&1 || true

cat > /usr/local/sbin/khilios-mss.sh <<'EOF'
#!/usr/bin/env bash
# Подгоняет MSS исходящих соединений под реальный MTU пути.
# -D перед -A: скрипт должен быть идемпотентным, иначе после каждой
# перезагрузки правил становится на одно больше.
set -u
for bin in iptables ip6tables; do
  command -v "$bin" >/dev/null 2>&1 || continue
  "$bin" -t mangle -D POSTROUTING -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true
  "$bin" -t mangle -A POSTROUTING -p tcp --tcp-flags SYN,RST SYN \
    -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true
done
EOF
chmod 755 /usr/local/sbin/khilios-mss.sh

# Через systemd, а не iptables-persistent: пакет тянет интерактивный
# debconf и сохраняет заодно всё, что оказалось в таблицах на тот момент,
# включая правила docker. Здесь же восстанавливается ровно одно правило.
cat > /etc/systemd/system/khilios-mss.service <<'EOF'
[Unit]
Description=khilios: clamp TCP MSS to path MTU
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/khilios-mss.sh

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now khilios-mss.service >/dev/null 2>&1 \
  || warn "Не удалось включить khilios-mss.service — проверь iptables вручную."

if iptables -t mangle -C POSTROUTING -p tcp --tcp-flags SYN,RST SYN \
     -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null; then
  log "MSS clamping активен"
else
  warn "MSS clamping не встал. На мобильных сетях возможны зависания загрузки."
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
# Наружу смотрят только явно перечисленные VPN-порты и SSH.
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

for vpn_port in "${VPN_TCP_PORT_LIST[@]}"; do
  ufw allow "$vpn_port"/tcp comment 'khilios-vpn-tcp' >/dev/null
done

for vpn_port in "${VPN_UDP_PORT_LIST[@]}"; do
  ufw allow "$vpn_port"/udp comment 'khilios-vpn-udp' >/dev/null
done

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

if [[ "$REMNAWAVE_ENV_MODE" == secret_key ]]; then
  # SECRET_KEY в Remnawave 3 — составная строка, формат которой является
  # частью TLS-аутентификации. Нельзя разворачивать её через source +
  # heredoc: кавычки исходного dotenv тогда теряются и панель отвечает
  # ssl/tls alert handshake failure. Переносим обе строки побайтно.
  grep -E '^(NODE_PORT|SECRET_KEY)=' node.env > /opt/remnanode/.env
  [[ "$(grep -c '^SECRET_KEY=' /opt/remnanode/.env)" -eq 1 ]] \
    || die "В node.env должна быть ровно одна строка SECRET_KEY=."
  if ! grep -q '^NODE_PORT=' /opt/remnanode/.env; then
    printf 'NODE_PORT=%s\n' "$APP_PORT" >> /opt/remnanode/.env
  fi
else
  cat > /opt/remnanode/.env <<EOF
APP_PORT=$APP_PORT
$SSL_CERT
EOF
fi
chmod 600 /opt/remnanode/.env

cat > /opt/remnanode/docker-compose.yml <<EOF
services:
  remnanode:
    image: $REMNAWAVE_NODE_IMAGE
    container_name: remnanode
    hostname: remnanode
    restart: always
    network_mode: host
    env_file:
      - .env
    ulimits:
      nofile:
        soft: 1048576
        hard: 1048576
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
 VPN TCP:     $VPN_TCP_PORTS
 VPN UDP:     ${VPN_UDP_PORTS:-нет}
 SSH:         ssh -p $SSH_PORT root@$PUBLIC_IP

 Дальше в панели (docs/architecture.md, набор протоколов):
   1. Nodes -> Create -> адрес $PUBLIC_IP, порт $APP_PORT
   2. Повесить на ноду входы из профиля и сверить их порты со списком выше:
        - VLESS + Reality TCP 443 — основной вход. Именно 443, а не высокий
          порт: Reality притворяется обращением к чужому сайту, а настоящий
          HTTPS живёт на 443. На мобильных сетях это решает.
        - VLESS + XHTTP TCP 8443 — альтернативный транспорт
      Для NL — 9443 и 10443, потому что 443 занят Caddy; эта нода на
      мобильном интернете будет работать хуже остальных.
   3. Все входы — в один Internal Squad, чтобы пользователь получил их одной
      подпиской и Happ мог автоматически выбрать рабочий транспорт.
   4. Выдать тестового пользователя и проверить С МОБИЛЬНОГО ИНТЕРНЕТА,
      а не с домашнего Wi-Fi — блокировки живут у операторов. Проверить
      отдельно Reality и XHTTP.

 Логи:        docker logs -f remnanode
 Перезапуск:  cd /opt/remnanode && docker compose restart
--------------------------------------------------------------------
EOF
