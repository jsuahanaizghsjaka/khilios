"""Админские команды. Доступны только ADMIN_TELEGRAM_ID."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ..config import Config
from ..db import Db

router = Router()


@router.message(Command("stats"))
async def stats(message: Message, db: Db, config: Config) -> None:
    # Молча игнорируем чужих: ответ «у вас нет прав» подтверждает,
    # что команда существует.
    if message.from_user.id != config.admin_id:
        return

    data = await db.stats()
    lines = [
        "<b>Сводка</b>",
        "",
        f"Триал активен: {data.get('trial', 0)}",
        f"Оплачено:      {data.get('active', 0)}",
        f"Истекло:       {data.get('expired', 0)}",
        f"Без подписки:  {data.get('ready', 0)}",
        f"Без согласия:  {data.get('new', 0)}",
        f"Возвраты:      {data.get('refunded', 0)}",
        "",
        f"Платежей: {data.get('payments', 0)} на {data.get('revenue_rub', 0)} ₽",
    ]
    await message.answer("\n".join(lines))


@router.message(Command("health"))
async def health(message: Message, config: Config, panel) -> None:
    if message.from_user.id != config.admin_id:
        return

    alive = await panel.ping()
    yes = lambda ok: "да" if ok else "нет"  # noqa: E731

    lines = [
        f"Панель: {'отвечает' if alive else 'НЕ ОТВЕЧАЕТ'}",
        "",
        "Способы оплаты:",
        f"  карта и СБП в Telegram: {yes(config.card_enabled)}",
        f"  карта и СБП на сайте (ЮKassa): {yes(config.web_pay_enabled)}",
        f"  Telegram Stars: {yes(config.stars_enabled)}",
        f"  криптовалюта: {yes(config.crypto_enabled)}"
        + (" (ТЕСТОВАЯ СЕТЬ)" if config.crypto_testnet else ""),
        "",
        f"Отсечка по возрасту: "
        f"{'включена' if config.antifraud_age_enabled else 'ВЫКЛЮЧЕНА (порог не задан)'}",
    ]

    if not config.payments_enabled:
        lines.append("")
        lines.append("Оплата выключена целиком — бот выдаёт только триалы.")

    await message.answer("\n".join(lines))
