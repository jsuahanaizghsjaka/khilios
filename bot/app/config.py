"""Конфигурация из окружения.

Всё читается один раз при старте и падает сразу, если чего-то не хватает.
Бот, поднявшийся без токена панели и обнаруживший это на первом живом
пользователе, — худший из возможных вариантов: деньги уже взяты.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _req(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} не задан в окружении. См. infra/bot/bot.env.example")
    return value


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int_opt(name: str) -> int | None:
    raw = _opt(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} должен быть числом, получено {raw!r}") from exc


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_id: int

    panel_api_url: str
    panel_api_token: str

    channel: str  # @username канала для гейта

    # Оплата появляется после модерации платёжки. До тех пор бот работает
    # и выдаёт триалы — это осознанно, см. bot.env.example.
    payment_token: str

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
    def payments_enabled(self) -> bool:
        return bool(self.payment_token)

    @property
    def antifraud_age_enabled(self) -> bool:
        return self.trial_max_telegram_id is not None


def load() -> Config:
    return Config(
        bot_token=_req("BOT_TOKEN"),
        admin_id=int(_req("ADMIN_TELEGRAM_ID")),
        panel_api_url=_opt("PANEL_API_URL", "http://127.0.0.1:3000").rstrip("/"),
        panel_api_token=_req("PANEL_API_TOKEN"),
        channel=_req("CHANNEL_USERNAME"),
        payment_token=_opt("PAYMENT_TOKEN"),
        support_url=_opt("SUPPORT_URL"),
        offer_url=_opt("OFFER_URL", "https://khilios.net/legal/offer"),
        privacy_url=_opt("PRIVACY_URL", "https://khilios.net/legal/privacy"),
        trial_max_telegram_id=_int_opt("TRIAL_MAX_TELEGRAM_ID"),
        db_path=_opt("DB_PATH", "/data/khilios.sqlite3"),
    )
