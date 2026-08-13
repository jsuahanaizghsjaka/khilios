"""Конфигурация из окружения.

Всё читается один раз при старте и падает сразу, если чего-то не хватает.
Бот, поднявшийся без токена панели и обнаруживший это на первом живом
пользователе, — худший из возможных вариантов: деньги уже взяты.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass


def _req(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} не задан в окружении. См. infra/bot/bot.env.example")
    return value


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


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


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_id: int

    panel_api_url: str
    panel_api_token: str
    panel_internal_squads: tuple[str, ...]

    channel: str  # @username канала для гейта

    # Оплата картой и через СБП: токен провайдера (ЮKassa) из @BotFather.
    # Появляется после модерации. До тех пор бот работает и выдаёт триалы —
    # это осознанно, см. bot.env.example.
    payment_token: str

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

    @property
    def card_enabled(self) -> bool:
        return bool(self.payment_token)

    @property
    def crypto_enabled(self) -> bool:
        return bool(self.crypto_token)

    @property
    def payments_enabled(self) -> bool:
        """Хоть один способ оплаты доступен.

        Кнопки тарифов показываются по этому признаку: тариф, который не
        купить ни одним способом, — это кнопка, ведущая в тупик.
        """
        return self.card_enabled or self.stars_enabled or self.crypto_enabled

    @property
    def antifraud_age_enabled(self) -> bool:
        return self.trial_max_telegram_id is not None


def load() -> Config:
    return Config(
        bot_token=_req("BOT_TOKEN"),
        admin_id=int(_req("ADMIN_TELEGRAM_ID")),
        panel_api_url=_opt("PANEL_API_URL", "http://127.0.0.1:3000").rstrip("/"),
        panel_api_token=_req("PANEL_API_TOKEN"),
        panel_internal_squads=_uuid_list_req("PANEL_INTERNAL_SQUADS"),
        channel=_req("CHANNEL_USERNAME"),
        payment_token=_opt("PAYMENT_TOKEN"),
        stars_enabled=_flag("STARS_ENABLED"),
        crypto_token=_opt("CRYPTO_PAY_TOKEN"),
        crypto_testnet=_flag("CRYPTO_TESTNET"),
        support_url=_opt("SUPPORT_URL"),
        offer_url=_opt("OFFER_URL", "https://khilios.net/legal/offer"),
        privacy_url=_opt("PRIVACY_URL", "https://khilios.net/legal/privacy"),
        trial_max_telegram_id=_int_opt("TRIAL_MAX_TELEGRAM_ID"),
        db_path=_opt("DB_PATH", "/data/khilios.sqlite3"),
    )
