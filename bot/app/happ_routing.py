"""Отдельный профиль маршрутизации Happ: через туннель идёт только Telegram.

ЗАЧЕМ ОН НУЖЕН ОТДЕЛЬНОЙ КНОПКОЙ.

Основной профиль — «всё через туннель, российское напрямую». Он правильный
для повседневной работы, но у него есть цена: весь трафик идёт за границу,
и когда узел перегружен или его пессимизируют, тормозит вообще всё.

Telegram же — тот случай, ради которого сервис чаще всего и покупают, и он
не требует гнать через туннель ничего лишнего: у Telegram свои сети, они
известны и умещаются в десяток подсетей. Профиль, где через VPN идёт только
он, даёт две вещи, которых не даёт основной:

  * скорость. Видео в YouTube, банк, игры и торренты идут напрямую с полной
    скоростью канала провайдера, туннель занят одним мессенджером;
  * живучесть. Если человек боится «включу VPN — сломается половина
    приложений», это профиль, который нельзя сломать в принципе.

КАК ЭТО УСТРОЕНО В HAPP.

Happ умеет несколько профилей маршрутизации, и они добавляются ссылкой
``happ://routing/add/<base64 профиля в JSON>``. Есть и вариант ``onadd``,
который сразу делает профиль активным, — мы им не пользуемся намеренно:
кнопка не должна молча переключать человеку весь его трафик.

Поле ``Name`` — ключ: профиль с тем же именем перезаписывается, а не
плодится. Поэтому имя здесь константа, а не что-то собираемое на лету.

СПИСКИ.

Домены и подсети Telegram, а не geosite-набор: имя набора зависит от версии
geo-файлов у клиента, и профиль с неизвестным именем Happ может отвергнуть
целиком. Явный список короткий, проверяемый и ничего не тянет извне.
Подсети — официальные, из core.telegram.org/resources/cidr.txt.
"""

from __future__ import annotations

import base64
import json

PROFILE_NAME = "Telegram"
SMART_PROFILE_NAME = "Умный режим"

# Домены Telegram и всё, что он тянет: медиа, превью ссылок, статика
# клиентов. Без cdn-доменов картинки и видео поедут напрямую и упрутся
# ровно в то, из-за чего Telegram и не работает.
TELEGRAM_DOMAINS = (
    "domain:telegram.org",
    "domain:telegram.me",
    "domain:t.me",
    "domain:telegra.ph",
    "domain:telesco.pe",
    "domain:tdesktop.com",
    "domain:cdn-telegram.org",
    "domain:telegram-cdn.org",
    "domain:comments.app",
    "domain:tx.me",
)

TELEGRAM_IPS = (
    "91.105.192.0/23",
    "91.108.4.0/22",
    "91.108.8.0/22",
    "91.108.12.0/22",
    "91.108.16.0/22",
    "91.108.20.0/22",
    "91.108.56.0/22",
    "95.161.64.0/20",
    "149.154.160.0/20",
    "185.76.151.0/24",
    "2001:67c:4e8::/48",
    "2001:b28:f23c::/47",
    "2001:b28:f23f::/48",
    "2a0a:f280::/32",
)

# Сервисы, которым нужен российский адрес. Явные суффиксы работают без
# зависимости от версии geosite-файлов в конкретной сборке Happ.
SMART_DIRECT_DOMAINS = (
    "domain:sberbank.ru",
    "domain:sber.ru",
    "domain:tbank.ru",
    "domain:tinkoff.ru",
    "domain:alfabank.ru",
    "domain:vtb.ru",
    "domain:raiffeisen.ru",
    "domain:gosuslugi.ru",
    "domain:nalog.gov.ru",
    "domain:mos.ru",
    "domain:yookassa.ru",
    "domain:sbp.nspk.ru",
    "domain:nspk.ru",
    "domain:ozon.ru",
    "domain:wildberries.ru",
    "domain:avito.ru",
    "domain:2gis.ru",
    "domain:yandex.ru",
    "domain:vk.com",
    "domain:mail.ru",
    "domain:rt.ru",
)

PRIVATE_IPS = (
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
)


def profile() -> dict[str, object]:
    """Профиль в том виде, в каком его понимает Happ.

    ``GlobalProxy`` выключен — это и есть суть: по умолчанию всё направо,
    в туннель уходит только то, что попало в списки Proxy*.
    """
    return {
        "Name": PROFILE_NAME,
        "GlobalProxy": "false",
        # Имена Telegram резолвим через туннель. Иначе провайдер отдаст
        # подменённый адрес, клиент честно пойдёт по нему, и маршрутизация
        # тут уже ничего не спасёт — она сработает для неверного IP.
        "RemoteDNSType": "DoH",
        "RemoteDNSDomain": "https://dns.google/dns-query",
        "RemoteDNSIP": "8.8.8.8",
        # Всё остальное — резолвер провайдера: российские сайты должны
        # получать ближний узел CDN, а не дальний европейский.
        "DomesticDNSType": "DoU",
        "DomesticDNSIP": "77.88.8.8",
        "DnsHosts": {},
        "DirectSites": [],
        "DirectIp": [],
        "ProxySites": list(TELEGRAM_DOMAINS),
        "ProxyIp": list(TELEGRAM_IPS),
        "BlockSites": [],
        "BlockIp": [],
        # IPIfNonMatch: сначала пробуем по имени, и только если ни одно
        # правило не совпало — резолвим и смотрим по адресу. Без этого
        # соединения, открытые сразу по IP, мимо правил и уйдут.
        "DomainStrategy": "IPIfNonMatch",
    }


def deep_link() -> str:
    """``happ://routing/add/...`` с профилем внутри.

    Базовый (не urlsafe) base64 без переносов — так его строит конструктор
    самого Happ. Паддинг оставляем: ссылка живёт в пути, а не в query, и
    обрезать его не от чего.
    """
    raw = json.dumps(profile(), ensure_ascii=False, separators=(",", ":"))
    encoded = base64.b64encode(raw.encode()).decode()
    return f"happ://routing/add/{encoded}"


def smart_profile() -> dict[str, object]:
    """Всё через VPN, а банки, госсервисы и локальная сеть — напрямую."""
    return {
        "Name": SMART_PROFILE_NAME,
        "GlobalProxy": "true",
        "RemoteDNSType": "DoH",
        "RemoteDNSDomain": "https://dns.google/dns-query",
        "RemoteDNSIP": "8.8.8.8",
        "DomesticDNSType": "DoU",
        "DomesticDNSIP": "77.88.8.8",
        "DnsHosts": {},
        "DirectSites": list(SMART_DIRECT_DOMAINS),
        "DirectIp": list(PRIVATE_IPS),
        "ProxySites": [],
        "ProxyIp": [],
        "BlockSites": [],
        "BlockIp": [],
        "DomainStrategy": "IPIfNonMatch",
    }


def smart_deep_link() -> str:
    raw = json.dumps(smart_profile(), ensure_ascii=False, separators=(",", ":"))
    encoded = base64.b64encode(raw.encode()).decode()
    return f"happ://routing/add/{encoded}"
