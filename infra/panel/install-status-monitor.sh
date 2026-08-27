#!/usr/bin/env bash
# Устанавливает минутный мониторинг status.json. Повторный запуск безопасен.

set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Запускать от root" >&2; exit 1; }
cd "$(dirname "$0")"

install -d -m 755 /etc/khilios /var/www/status
install -d -m 700 /var/lib/khilios-status
install -m 755 status-json.sh /usr/local/sbin/khilios-status-json

if [[ ! -e /etc/khilios/nodes.conf ]]; then
  install -m 640 nodes.conf.example /etc/khilios/nodes.conf
  echo "Создан /etc/khilios/nodes.conf — замените example-домены перед запуском." >&2
fi

if [[ ! -e /etc/khilios/status-monitor.env ]]; then
  install -m 600 /dev/null /etc/khilios/status-monitor.env
fi

cat > /etc/systemd/system/khilios-status.service <<'EOF'
[Unit]
Description=khilios node transport status snapshot
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=ALERT_ENV=/opt/khilios/infra/bot/bot.env
ExecStart=/usr/bin/flock -n /run/khilios-status/lock /usr/local/sbin/khilios-status-json
User=root
RuntimeDirectory=khilios-status
RuntimeDirectoryMode=0700
PrivateTmp=yes
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/var/www/status /var/lib/khilios-status
ProtectHome=yes
EOF

cat > /etc/systemd/system/khilios-status.timer <<'EOF'
[Unit]
Description=Run khilios transport checks every minute

[Timer]
OnBootSec=15s
OnUnitActiveSec=60s
AccuracySec=1s
Persistent=true
Unit=khilios-status.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now khilios-status.timer
systemctl start khilios-status.service
systemctl --no-pager --full status khilios-status.timer
