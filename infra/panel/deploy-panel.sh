#!/usr/bin/env bash
#
# khilios — разворачивание панельной VPS с нуля.
#
# Парный скрипт к infra/node/deploy-node.sh. Запускать от root на ЧИСТОЙ
# Ubuntu 22.04 / 24.04, до того как поднимать ноды: ноды получают SSL_CERT
# из панели, значит панель должна существовать первой.
#
#   cp panel.env.example panel.env && nano panel.env && ./deploy-panel.sh
#
# ГЛАВНОЕ РЕШЕНИЕ ЭТОГО СКРИПТА.
# Панель отдаёт две совершенно разные вещи с одного процесса:
#   1. админку — её не должен видеть никто, кроме вас;
#   2. страницу подписки — её обязан открыть каждый пользователь.
# Поэтому наружу торчит не панель, а Caddy, и он разводит эти две вещи по
# разным именам: админка доступна только с вашего адреса, подписка — всем.
# Открытая в интернет админка Remnawave — это не «неаккуратно», это конец
# сервиса: вместе с ней уходят все ключи и вся база пользователей.

set -euo pipefail

cd "$(dirname "$0")"

log()  { printf '\n\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m [!]\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

# --------------------------------------------------------------------------
# 0. Конфиг
# --------------------------------------------------------------------------

[[ $EUID -eq 0 ]] || die "Запускать от root."
[[ -f panel.env ]] || die "Нет panel.env. Скопируй panel.env.example и заполни."

# shellcheck disable=SC1091
source ./panel.env

: "${ADMIN_HOST:?ADMIN_HOST не задан — имя для админки, например panel.example.net}"
: "${SUB_HOST:?SUB_HOST не задан — имя для страницы подписки, например sub.example.net}"
: "${ADMIN_IP:?ADMIN_IP не задан — ваш адрес, только с него открывается админка}"
: "${ACME_EMAIL:?ACME_EMAIL не задан — почта для TLS-сертификатов}"
SSH_PORT="${SSH_PORT:-22}"
HARDEN_SSH="${HARDEN_SSH:-yes}"
PANEL_DIR="${PANEL_DIR:-/opt/remnawave}"
SUB_PATH="${SUB_PATH:-/api/sub}"

grep -qiE 'ubuntu' /etc/os-release || warn "Не Ubuntu, дальше на свой риск."

log "Панель: $ADMIN_HOST (доступ только с $ADMIN_IP) | подписка: $SUB_HOST"

export DEBIAN_FRONTEND=noninteractive

# --------------------------------------------------------------------------
# 1. Пакеты и время
# --------------------------------------------------------------------------

log "Обновление системы"
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq ca-certificates curl gnupg ufw fail2ban chrony jq rsync openssl

timedatectl set-timezone UTC
systemctl enable --now chrony >/dev/null 2>&1 || true

# --------------------------------------------------------------------------
# 2. SSH
# --------------------------------------------------------------------------

if [[ "$HARDEN_SSH" == "yes" ]]; then
  log "SSH на порт $SSH_PORT"

  if [[ -s /root/.ssh/authorized_keys ]]; then
    DISABLE_PASSWORDS=yes
  else
    DISABLE_PASSWORDS=no
    warn "Нет ключа в /root/.ssh/authorized_keys — вход по паролю оставлен."
    warn "Положи ключ и перезапусти, иначе панель висит с паролем наружу."
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

  # Ubuntu 23.04+ слушает ssh через systemd-сокет, и тогда порт задаёт сокет,
  # а Port из sshd_config молча игнорируется — новый порт не открывается, а
  # закрыть старый успевает файрвол ниже, и машина остаётся без входа. Поэтому
  # при активном сокете правим сам сокет и НЕ трогаем ssh.service: настройки
  # авторизации sshd читает при каждом входящем соединении, отдельный
  # рестарт демона тут не нужен и только создаёт второго слушателя на порту.
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

  # Проверяем ФАКТ, а не намерение. Ровно здесь скрипт однажды запер машину:
  # порт в конфиге поменялся, sshd остался на 22, а файрвол ниже открыл
  # только новый порт — и внутрь стало не попасть вообще. Причина была в
  # systemd-сокете, но причина неважна: если новый порт не слушается,
  # закрывать старый нельзя ни при каких обстоятельствах.
  sleep 1
  if ss -tln 2>/dev/null | grep -qE "[:.]${SSH_PORT}([[:space:]]|$)"; then
    SSH_MOVED=yes
    log "SSH слушает $SSH_PORT"
  else
    SSH_MOVED=no
    warn "SSH НЕ слушает $SSH_PORT — оставляю порт 22 открытым."
    warn "Разберись с этим до того, как закрывать 22."
  fi

  warn "НЕ ЗАКРЫВАЙ сессию, пока не проверишь: ssh -p $SSH_PORT root@<ip>"
else
  SSH_MOVED=no
fi

# --------------------------------------------------------------------------
# 3. Файрвол
# --------------------------------------------------------------------------
# Порт самой панели наружу не открывается вообще. К нему ходит только Caddy
# с этой же машины, поэтому в ufw его нет и быть не должно.

log "Файрвол"
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow "$SSH_PORT"/tcp comment 'ssh' >/dev/null

# Порт 22 остаётся открытым НАМЕРЕННО, даже когда SSH переехал.
# Скрипт не имеет права оставить машину без входа: цена закрытого 22 при
# неработающем новом порте — поездка в консоль хостера, а если консоль
# недоступна, то и полная переустановка. Цена лишнего открытого порта —
# фоновый брутфорс, который и так отбивает fail2ban и запрет входа по паролю.
# Закрывается вручную, после того как вход по новому порту ПРОВЕРЕН — команда
# печатается в конце скрипта.
ufw allow 22/tcp comment 'ssh-fallback: закрыть после проверки нового порта' >/dev/null

ufw allow 80/tcp comment 'acme' >/dev/null
ufw allow 443/tcp comment 'caddy' >/dev/null
ufw --force enable >/dev/null
ufw status numbered

systemctl enable --now fail2ban >/dev/null 2>&1 || true

# --------------------------------------------------------------------------
# 4. Docker
# --------------------------------------------------------------------------

if ! command -v docker >/dev/null 2>&1; then
  log "Установка Docker"
  curl -fsSL https://get.docker.com | sh
else
  log "Docker уже стоит"
fi
systemctl enable --now docker >/dev/null

# Docker может быть предустановлен образом БЕЗ плагина compose — тогда
# `docker compose` не команда, а ошибка разбора флагов, и панель не
# поднимается. Установка самого Docker через get.docker.com плагин приносит,
# но предустановленный — нет. Проверяем по факту, а не по наличию docker.
if ! docker compose version >/dev/null 2>&1; then
  log "Ставлю плагин docker compose"
  apt-get install -y -qq docker-compose-v2 2>/dev/null \
    || apt-get install -y -qq docker-compose-plugin \
    || die "Не удалось поставить плагин docker compose. Поставь вручную и перезапусти."
fi

cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "3" }
}
EOF
systemctl restart docker

# --------------------------------------------------------------------------
# 5. Панель
# --------------------------------------------------------------------------
# Compose и .env берём у самого проекта, а не переписываем сюда. Вендорить
# чужой compose — значит получить тихо разъехавшийся конфиг через два релиза:
# скрипт будет разворачивать вчерашнюю схему базы поверх сегодняшнего образа.

log "Подготовка $PANEL_DIR"
install -d -m 700 "$PANEL_DIR"
cd "$PANEL_DIR"

if [[ ! -f docker-compose.yml ]]; then
  log "Скачиваю docker-compose.yml проекта"
  curl -fsSL -o docker-compose.yml \
    https://raw.githubusercontent.com/remnawave/backend/main/docker-compose-prod.yml \
    || die "Не скачался compose. Возьми актуальный из документации Remnawave вручную."
fi

if [[ ! -f .env ]]; then
  log "Скачиваю шаблон .env и генерирую секреты"
  curl -fsSL -o .env.sample \
    https://raw.githubusercontent.com/remnawave/backend/main/.env.sample \
    || die "Не скачался .env.sample. Возьми из документации вручную."
  cp .env.sample .env

  # Секреты генерируем здесь, чтобы в конфиге не остались значения из примера.
  # Забытый дефолтный JWT в панели — это чужой вход с правами администратора.
  gen() { openssl rand -hex 32; }
  DB_PASS="$(openssl rand -hex 16)"

  sed -i "s|^JWT_AUTH_SECRET=.*|JWT_AUTH_SECRET=$(gen)|"     .env 2>/dev/null || true
  sed -i "s|^JWT_API_TOKENS_SECRET=.*|JWT_API_TOKENS_SECRET=$(gen)|" .env 2>/dev/null || true
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$DB_PASS|" .env 2>/dev/null || true

  # Пароль базы живёт в двух местах: POSTGRES_PASSWORD и строка подключения
  # DATABASE_URL. Заменить только первое — панель поднимется и не сможет
  # подключиться к собственной базе, а выглядеть это будет как «панель
  # стартует и падает» без внятной причины. Собираем URL заново из частей.
  PG_USER="$(grep -oP '^POSTGRES_USER=\K.*' .env 2>/dev/null | tr -d '"' || true)"
  PG_DB="$(grep -oP '^POSTGRES_DB=\K.*' .env 2>/dev/null | tr -d '"' || true)"
  PG_HOST="$(grep -oP '^DATABASE_URL=.*@\K[^:/]+' .env 2>/dev/null || true)"
  PG_PORT="$(grep -oP '^DATABASE_URL=.*@[^:/]+:\K[0-9]+' .env 2>/dev/null || true)"

  if [[ -n "$PG_USER" && -n "$PG_DB" && -n "$PG_HOST" ]]; then
    sed -i "s|^DATABASE_URL=.*|DATABASE_URL=\"postgresql://$PG_USER:$DB_PASS@$PG_HOST:${PG_PORT:-5432}/$PG_DB\"|" .env
  else
    warn "Не разобрал DATABASE_URL — впиши в него пароль из POSTGRES_PASSWORD вручную."
  fi

  # Домены. Без этого в шаблоне остаётся panel.domain.com, и каждая выданная
  # ссылка на подписку указывает на чужой несуществующий домен — у всех
  # пользователей сразу и молча.
  sed -i "s|^PANEL_DOMAIN=.*|PANEL_DOMAIN=$ADMIN_HOST|" .env 2>/dev/null || true
  sed -i "s|^SUB_PUBLIC_DOMAIN=.*|SUB_PUBLIC_DOMAIN=$SUB_HOST$SUB_PATH|" .env 2>/dev/null || true

  chmod 600 .env
fi

# Проверка идёт при КАЖДОМ запуске, а не только при создании .env: файл могли
# править руками между прогонами. Пускать панель с дефолтным секретом или
# чужим доменом нельзя — оба отказа тихие и оба стоят всей базы.
if grep -qiE '^[A-Z_]+=("?)(change_me|changeme)' .env; then
  warn "В .env остались незаполненные значения:"
  grep -niE '^[A-Z_]+=("?)(change_me|changeme)' .env
  warn "Часть из них не нужна (например токен бота панели — у нас свой бот)."
  warn "Но JWT-секреты и пароль базы обязаны быть заполнены."
fi

if grep -qE '^(PANEL_DOMAIN|SUB_PUBLIC_DOMAIN)=.*domain\.com' .env; then
  die "В .env остались домены из примера (domain.com). Впиши $ADMIN_HOST и $SUB_HOST$SUB_PATH и запусти снова."
fi

log "Запуск панели"
docker compose pull -q || warn "docker compose pull не прошёл, продолжаю"
docker compose up -d

# --------------------------------------------------------------------------
# 6. Caddy
# --------------------------------------------------------------------------
# Сертификаты Caddy выпускает сам. Условие: A-записи ADMIN_HOST и SUB_HOST
# уже смотрят на этот сервер, иначе ACME не пройдёт.
#
# ADMIN_HOST — только с ADMIN_IP. Если у вас динамический адрес, вместо
# allowlist используйте SSH-туннель и вообще не публикуйте админку:
#   ssh -p PORT -L 8080:127.0.0.1:3000 root@panel
# Это надёжнее любого списка адресов.

log "Caddy"
install -d -m 755 /etc/caddy

cat > /etc/caddy/Caddyfile <<EOF
{
	email $ACME_EMAIL
}

# Админка. Всё, что не с вашего адреса, получает 403 и не видит даже формы входа.
$ADMIN_HOST {
	@notme not remote_ip $ADMIN_IP
	respond @notme 403

	reverse_proxy 127.0.0.1:3000
}

# Локальный API для бота. Remnawave 3.x проверяет proxy-заголовки и закрывает
# прямое соединение с 127.0.0.1:3000 без ответа. Этот listener доступен только
# на loopback и добавляет те же заголовки, что публичный reverse proxy.
http://127.0.0.1:3002 {
	reverse_proxy 127.0.0.1:3000 {
		header_up Host $ADMIN_HOST
		header_up X-Forwarded-Proto https
		header_up X-Forwarded-Host $ADMIN_HOST
	}
}

# Страница подписки. Открыта всем, но только по пути подписки:
# на этом же имени не должно быть ничего лишнего.
$SUB_HOST {
	# status.json для публичной страницы статуса на сайте.
	# Его генерирует status-json.sh раз в 5 минут, а сайт читает по STATUS_URL.
	# Отдаётся статикой, мимо панели: страница статуса должна пережить
	# ровно тот случай, ради которого её и заводят — когда панели плохо.
	# Наружу уходят только имя узла, регион и состояние, адресов в файле нет.
	handle /status/* {
		root * /var/www
		file_server
	}

	# Веб-чекаут ЮKassa: страница возврата после оплаты и вебхук. Слушает
	# бот на 127.0.0.1:8081 (WEB_PAY_PORT в bot.env), см. app/webpay.py.
	# Живёт на этом же имени специально — платёжной странице нужен HTTPS
	# и публичный домен, заводить под неё третий поддомен незачем.
	handle /pay/* {
		reverse_proxy 127.0.0.1:8081
	}

	handle $SUB_PATH* {
		reverse_proxy 127.0.0.1:3000
	}
	handle {
		respond 404
	}
}
EOF

if ! command -v caddy >/dev/null 2>&1; then
  apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https
  curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  echo "deb [signed-by=/usr/share/keyrings/caddy-stable-archive-keyring.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main" \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  apt-get install -y -qq caddy
fi

caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile \
  || die "Caddyfile не прошёл проверку, панель не публикую"

systemctl enable --now caddy >/dev/null
systemctl reload caddy 2>/dev/null || systemctl restart caddy

# --------------------------------------------------------------------------
# 7. Бэкапы и статус
# --------------------------------------------------------------------------
# Ставим сразу, а не «потом когда-нибудь»: панель без бэкапа живёт до первого
# отказа диска, а страница статуса без крона просто врёт устаревшими данными.

log "Бэкапы и генератор статуса в cron"
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)"
install -d -m 755 /etc/khilios

# Каталог создаём здесь, а не в status-json.sh: Caddy отдаёт его статикой,
# и без каталога первый же запрос до первого крона получил бы 404.
install -d -m 755 /var/www /var/www/status

[[ -f /etc/khilios/nodes.conf ]] || cat > /etc/khilios/nodes.conf <<'EOF'
# имя|регион|адрес|порт  — адреса наружу не уходят, см. status-json.sh
# fi-1|Финляндия|203.0.113.20|4443
# nl-1|Нидерланды|198.51.100.7|9443
EOF

cat > /etc/cron.d/khilios <<EOF
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
0 */6 * * * root $SCRIPTS_DIR/backup.sh >> /var/log/khilios-backup.log 2>&1
*/5 * * * * root $SCRIPTS_DIR/status-json.sh >> /var/log/khilios-status.log 2>&1
EOF
chmod 644 /etc/cron.d/khilios

# --------------------------------------------------------------------------
# 8. Проверка
# --------------------------------------------------------------------------

log "Проверка"
sleep 5
docker compose ps

PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || echo '?')"

if ss -tlnp 2>/dev/null | grep -q ':3000 '; then
  echo "  [ok] панель слушает 3000 локально"
else
  warn "порт 3000 не слушается — docker compose logs"
fi

if ufw status | grep -qE '^3000'; then
  warn "ВНИМАНИЕ: порт 3000 открыт в ufw. Он не должен быть открыт наружу."
else
  echo "  [ok] порт панели наружу закрыт"
fi

cat <<EOF

--------------------------------------------------------------------
 Панель поднята.

 IP:        $PUBLIC_IP
 Админка:   https://$ADMIN_HOST   (только с $ADMIN_IP)
 Подписка:  https://$SUB_HOST$SUB_PATH
 Статус:    https://$SUB_HOST/status/status.json
            это значение идёт в STATUS_URL на Vercel
 SSH:       ssh -p $SSH_PORT root@$PUBLIC_IP
            порт 22 пока ОТКРЫТ — это страховка, см. пункт 0

 Дальше:
   0. ПРОВЕРИТЬ новый порт из другого окна, не закрывая текущее:
        ssh -p $SSH_PORT root@$PUBLIC_IP "echo ok"
      Ответило — закрыть запасной вход:
        ufw delete allow 22/tcp
      Не ответило — НЕ закрывать 22 и разбираться: без него вход
      останется только через консоль хостера, а она бывает недоступна
      ровно тогда, когда нужна$([[ "${SSH_MOVED:-no}" == "no" ]] && echo "

      ВНИМАНИЕ: при этом запуске SSH на $SSH_PORT НЕ поднялся.
      Порт 22 сейчас единственный вход — не закрывай его.")
   1. A-записи $ADMIN_HOST и $SUB_HOST → $PUBLIC_IP.
      Для админки и подписки — DNS-only, без прокси Cloudflare:
      сертификат выпускает Caddy, второй TLS сверху всё сломает
   2. Открыть админку, создать администратора СРАЗУ.
      Панель со свободной регистрацией = чужая панель
   3. Nodes -> Create, скопировать SSL_CERT, дальше deploy-node.sh на ноде
   4. Вписать ноды в /etc/khilios/nodes.conf, прогнать status-json.sh
      руками и открыть https://$SUB_HOST/status/status.json в браузере.
      Пустой ответ здесь = пустая страница статуса на сайте
   5. Заполнить REMOTE в backup.sh, иначе бэкап лежит рядом с панелью
      и не спасает ровно в том случае, ради которого делается
   6. Учения: восстановить панель из бэкапа на чистую VPS, засечь время

 Логи:      cd $PANEL_DIR && docker compose logs -f
 Caddy:     journalctl -u caddy -f
--------------------------------------------------------------------
EOF
