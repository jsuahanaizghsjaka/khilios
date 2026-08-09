"""Точка входа.

Long polling, а не вебхук, и это осознанно: вебхук требует открытого наружу
HTTPS-эндпоинта, то есть ещё одной публичной точки на машине, где лежит база
всех пользователей и ключи. Ради пятнадцати-тридцати клиентов такой размен не
нужен — опрос ничего не открывает и при этой нагрузке неотличим по скорости.
"""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from . import config as config_module
from . import handlers, scheduler
from .db import Db
from .panel import PanelClient

log = logging.getLogger("khilios")


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    # aiogram на INFO печатает каждый апдейт — в логе это шум, в котором
    # тонут собственные сообщения бота.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def main() -> None:
    _setup_logging()
    config = config_module.load()

    db = Db(config.db_path)
    await db.connect()

    panel = PanelClient(config.panel_api_url, config.panel_api_token)

    # Проверки на старте. Бот поднимется в любом случае — падать из-за
    # недоступной панели нельзя, она может подняться через минуту, — но
    # оба состояния должны быть видны в логе сразу, а не выясняться
    # на первом живом пользователе.
    if not await panel.ping():
        log.error("ПАНЕЛЬ НЕ ОТВЕЧАЕТ или токен не принят. Ключи выдаваться не будут.")
    if not config.antifraud_age_enabled:
        log.warning(
            "TRIAL_MAX_TELEGRAM_ID не задан — отсечка по возрасту аккаунта ВЫКЛЮЧЕНА. "
            "Триал можно выносить новыми аккаунтами. Как откалибровать — bot/README.md"
        )
    if not config.payments_enabled:
        log.warning("PAYMENT_TOKEN пуст — оплата выключена, бот выдаёт только триалы.")

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Зависимости раздаются диспетчером: хендлер объявляет их в сигнатуре
    # и получает готовыми. Глобальных синглтонов нет намеренно — их нельзя
    # подменить в тесте.
    dp = Dispatcher(db=db, config=config, panel=panel)
    dp.include_router(handlers.router())

    background = asyncio.create_task(scheduler.run(bot, db, panel))

    try:
        log.info("Бот запущен, канал гейта: %s", config.channel)
        await dp.start_polling(bot)
    finally:
        background.cancel()
        await panel.close()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
