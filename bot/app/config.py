"""Конфигурация из окружения.

Всё читается один раз при старте и падает сразу, если чего-то не хватает.
Бот, поднявшийся без токена панели и обнаруживший это на первом живом
пользователе, — худший из возможных вариантов: деньги уже взяты.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    """Read both Compose-style and ``docker run --env-file`` values.

    Docker Compose removes balanced quotes from env-file values, while
    ``docker run --env-file`` passes them through literally.  Deployment and
    one-off health checks use both paths, so accepting either representation
    keeps UUIDs and URLs identical in both environments.
    """
    value = os.getenv(name, default).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value


def _req(name: str) -> str:
    value = _env(name)
    if not value:
        raise RuntimeError(f"{name} не задан в окружении. См. infra/bot/bot.env.example")
    return value


def _opt(name: str, default: str = "") -> str:
    return _env(name, default)


def _flag(name: str) -> bool:
    # Пустое значение — выключено. Явное "false"/"0"/"no" тоже: иначе
    # STARS_ENABLED="false" в env читалось бы как включено, и это ровно та
    # ошибка, которую никто не замечает, пока не увидит лишнюю кнопку.
    return _opt(name).lower() in {"1", "true", "yes", "on"}


def _int_opt(name: str) -> int | None:
    raw = _opt(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} должен быть числом, получено {raw!r}") from exc


def _uuid_list_req(name: str) -> tuple[str, ...]:
    raw = _req(name)
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not values:
        raise RuntimeError(f"{name} должен содержать хотя бы один UUID")
    try:
        return tuple(str(uuid.UUID(value)) for value in values)
    except ValueError as exc:
        raise RuntimeError(
            f"{name} должен быть списком UUID через запятую, получено {raw!r}"
        ) from exc


def _uuid_list_opt(name: str) -> tuple[str, ...]:
    """Необязательный список UUID.

    Отдельные squad'ы режимов вводятся постепенно. Пустая переменная должна
    выключать только конкретный режим, а не ронять уже работающий бот.
    """
    raw = _opt(name)
    if not raw:
        return ()
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    try:
        return tuple(str(uuid.UUID(value)) for value in values)
    except ValueError as exc:
        raise RuntimeError(
            f"{name} должен быть списком UUID через запятую, получено {raw!r}"
        ) from exc


def _webhook_secret_opt(name: str) -> str:
    value = _opt(name)
    if value and not re.fullmatch(r"[A-Za-z0-9]{32,}", value):
        raise RuntimeError(
            f"{name} должен содержать минимум 32 латинские буквы/цифры"
        )
    return value


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_id: int

    panel_api_url: str
    panel_api_token: str
    panel_internal_squads: tuple[str, ...]

    channel: str  # @username канала для гейта

    # Оплата картой и СБП через Telegram Payments: токен провайдера
    # (ЮKassa) из @BotFather. Появляется после модерации. До тех пор бот
    # работает и выдаёт триалы — это осознанно, см. bot.env.example.
    payment_token: str

    # Оплата картой и СБП напрямую через ЮKassa: веб-чекаут вместо формы
    # внутри Telegram. Другая пара ключей, не токен из BotFather — берётся
    # в личном кабинете ЮKassa. Оба способа независимы и могут работать
    # одновременно, пока не решите оставить один.
    yookassa_shop_id: str
    yookassa_secret_key: str

    # Публичное имя, на которое Caddy проксирует локальный веб-сервер бота
    # (см. app/webpay.py). Это SUB_HOST панели, путь /pay/* — там же, где
    # уже отдаётся страница подписки. Без схемы, вида sub.basaltworks.ru.
    web_pay_host: str

    # На каком порту слушать локальный веб-сервер оплаты. Наружу не
    # открывается вообще — Caddy проксирует его так же, как API панели.
    web_pay_port: int

    # Telegram Stars. Токен не нужен вообще: Stars — внутренняя валюта
    # Telegram, счёт выставляется с пустым provider_token. Поэтому способ
    # включается флагом, а не наличием ключа.
    stars_enabled: bool

    # Крипта через @CryptoBot. Пустой токен = способ выключен.
    crypto_token: str
    crypto_testnet: bool

    support_url: str
    offer_url: str
    privacy_url: str

    # Антифрод по возрасту аккаунта. Telegram точного возраста не отдаёт,
    # но ID выдаются возрастающими, и порядок величины по ним виден.
    # Аккаунты с ID выше этого порога триал не получают.
    #
    # Значение НЕ захардкожено намеренно: угадать его из головы нельзя, а
    # ошибка в большую сторону не делает ничего, в меньшую — отсекает всех
    # пришедших. Как откалибровать — в bot/README.md.
    trial_max_telegram_id: int | None

    db_path: str

    # Откуда бот читает состояние узлов для рассылки об авариях. Тот же
    # файл, что отдаётся сайту: генерирует infra/panel/status-json.sh по
    # cron. Бот стоит на панельной машине, поэтому читает его с диска —
    # без сети и без авторизации.
    status_json_path: str

    # Режимы Remnawave. PANEL_INTERNAL_SQUADS остаётся безопасным fallback,
    # поэтому старый env продолжает работать до создания отдельных squad'ов.
    panel_trial_squads: tuple[str, ...] = ()
    panel_protect_squads: tuple[str, ...] = ()
    panel_mobile_squads: tuple[str, ...] = ()
    panel_speed_squads: tuple[str, ...] = ()
    panel_resilient_squads: tuple[str, ...] = ()
    remnawave_webhook_secret: str = ""

    @property
    def card_enabled(self) -> bool:
        """Карта и СБП через Telegram Payments (форма внутри Telegram)."""
        return bool(self.payment_token)

    @property
    def web_pay_enabled(self) -> bool:
        """Карта и СБП через веб-чекаут ЮKassa (отдельная страница)."""
        return bool(self.yookassa_shop_id and self.yookassa_secret_key)

    @property
    def crypto_enabled(self) -> bool:
        return bool(self.crypto_token)

    @property
    def payments_enabled(self) -> bool:
        """Хоть один способ оплаты доступен.

        Кнопки тарифов показываются по этому признаку: тариф, который не
        купить ни одним способом, — это кнопка, ведущая в тупик.
        """
        return (
            self.card_enabled
            or self.web_pay_enabled
            or self.stars_enabled
            or self.crypto_enabled
        )

    @property
    def antifraud_age_enabled(self) -> bool:
        return self.trial_max_telegram_id is not None

    @staticmethod
    def _merge_squads(*groups: tuple[str, ...]) -> tuple[str, ...]:
        # dict сохраняет порядок и убирает дубли: порядок squad'ов затем
        # стабильно попадает в ответы панели и проще сравнивается в тестах.
        return tuple(dict.fromkeys(item for group in groups for item in group))

    @property
    def protect_squads(self) -> tuple[str, ...]:
        return self.panel_protect_squads or self.panel_internal_squads

    @property
    def paid_squads(self) -> tuple[str, ...]:
        return self._merge_squads(self.protect_squads, self.panel_mobile_squads)

    @property
    def trial_squads(self) -> tuple[str, ...]:
        return self.panel_trial_squads or self.protect_squads

    def squads_for_mode(self, mode: str) -> tuple[str, ...]:
        """Полный состав squad'ов для атомарного переключения режима."""
        if mode == "protect":
            return self.protect_squads
        if mode in {"mobile", "smart"}:
            return self.paid_squads
        if mode == "speed":
            if not self.panel_speed_squads:
                return ()
            return self._merge_squads(self.protect_squads, self.panel_speed_squads)
        if mode == "resilient":
            if not self.panel_resilient_squads:
                return ()
            return self._merge_squads(
                self.protect_squads, self.panel_resilient_squads
            )
        return ()


def load() -> Config:
    return Config(
        bot_token=_req("BOT_TOKEN"),
        admin_id=int(_req("ADMIN_TELEGRAM_ID")),
        panel_api_url=_opt("PANEL_API_URL", "http://127.0.0.1:3002").rstrip("/"),
        panel_api_token=_req("PANEL_API_TOKEN"),
        panel_internal_squads=_uuid_list_req("PANEL_INTERNAL_SQUADS"),
        channel=_req("CHANNEL_USERNAME"),
        payment_token=_opt("PAYMENT_TOKEN"),
        yookassa_shop_id=_opt("YOOKASSA_SHOP_ID"),
        yookassa_secret_key=_opt("YOOKASSA_SECRET_KEY"),
        web_pay_host=_opt("WEB_PAY_HOST", "sub.basaltworks.ru"),
        web_pay_port=int(_opt("WEB_PAY_PORT", "8081")),
        stars_enabled=_flag("STARS_ENABLED"),
        crypto_token=_opt("CRYPTO_PAY_TOKEN"),
        crypto_testnet=_flag("CRYPTO_TESTNET"),
        support_url=_opt("SUPPORT_URL"),
        offer_url=_opt("OFFER_URL", "https://khilios.net/legal/offer"),
        privacy_url=_opt("PRIVACY_URL", "https://khilios.net/legal/privacy"),
        trial_max_telegram_id=_int_opt("TRIAL_MAX_TELEGRAM_ID"),
        db_path=_opt("DB_PATH", "/data/khilios.sqlite3"),
        status_json_path=_opt("STATUS_JSON_PATH", "/var/www/status/status.json"),
        panel_trial_squads=_uuid_list_opt("PANEL_TRIAL_SQUADS"),
        panel_protect_squads=_uuid_list_opt("PANEL_PROTECT_SQUADS"),
        panel_mobile_squads=_uuid_list_opt("PANEL_MOBILE_SQUADS"),
        panel_speed_squads=_uuid_list_opt("PANEL_SPEED_SQUADS"),
        panel_resilient_squads=_uuid_list_opt("PANEL_RESILIENT_SQUADS"),
        remnawave_webhook_secret=_webhook_secret_opt(
            "REMNAWAVE_WEBHOOK_SECRET"
        ),
    )
