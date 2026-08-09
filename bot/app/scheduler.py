"""Напоминания об истечении и отключение просроченных.

Автопродления нет — так обещано на сайте. Значит напоминание это единственное,
что стоит между человеком и молча кончившейся подпиской. Пользователь, у
которого доступ пропал без предупреждения, не продлевает — он уходит и
рассказывает почему.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from . import fmt, keyboards as kb, texts
from .db import Db
from .panel import PanelClient, PanelError, PanelUnavailable

log = logging.getLogger(__name__)

# Раз в час достаточно: напоминания привязаны к дням, а не к минутам.
TICK_SECONDS = 3600

REMINDERS = (("d3", 3), ("d1", 1), ("d0", 0))


async def run(bot: Bot, db: Db, panel: PanelClient) -> None:
    while True:
        try:
            await _tick(bot, db, panel)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            # Упавший цикл не должен уносить бота: без напоминаний он
            # работает, без хендлеров — нет.
            log.exception("Ошибка в фоновом цикле")
        await asyncio.sleep(TICK_SECONDS)


async def _tick(bot: Bot, db: Db, panel: PanelClient) -> None:
    for kind, days_ahead in REMINDERS:
        for user in await db.due_for_reminder(kind, days_ahead):
            text = texts.REMIND[kind].format(until=fmt.date(user.expires_at))
            if await _send(bot, user.telegram_id, text, kb.renew()):
                await db.mark_reminded(user.telegram_id, user.expires_at, kind)

    for user in await db.expired():
        if user.panel_uuid:
            try:
                await panel.disable(user.panel_uuid)
            except (PanelError, PanelUnavailable) as exc:
                # Не отключилось — не трогаем состояние, попробуем на следующем
                # тике. Пометить «expired» в базе, оставив ключ рабочим в панели,
                # значит раздавать доступ бесплатно и не знать об этом.
                log.error("Не отключён %s: %s", user.telegram_id, exc)
                continue

        await db.set_state(user.telegram_id, "expired")
        await _send(bot, user.telegram_id, texts.EXPIRED_NOTICE, kb.renew())
        log.info("Подписка истекла: %s", user.telegram_id)


async def _send(bot: Bot, telegram_id: int, text: str, markup) -> bool:
    try:
        await bot.send_message(telegram_id, text, reply_markup=markup)
        return True
    except TelegramAPIError as exc:
        # Заблокировал бота или удалил аккаунт. Это нормально и не ошибка:
        # помечаем отправленным, чтобы не долбиться каждый час.
        log.info("Не доставлено %s: %s", telegram_id, exc)
        return True
