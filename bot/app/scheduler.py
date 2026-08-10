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
from .config import Config
from .crypto import CryptoClient, CryptoError, CryptoUnavailable
from .db import Db
from .panel import PanelClient, PanelError, PanelUnavailable
from .plans import BY_ID

log = logging.getLogger(__name__)

# Напоминания привязаны к дням, поэтому раз в час достаточно.
HOURLY_SECONDS = 3600

# А вот криптосчёт опрашивается часто и намеренно: человек заплатил и ждёт
# ключ. Час ожидания после оплаты — это возврат и плохой отзыв, даже если
# формально всё работает.
CRYPTO_SECONDS = 20


async def run(
    bot: Bot,
    db: Db,
    panel: PanelClient,
    config: Config,
    crypto: CryptoClient | None,
) -> None:
    """Два независимых цикла с разной частотой.

    Разделены намеренно: общий тик пришлось бы делать по частоте самого
    срочного дела, и тогда напоминания об истечении пересчитывались бы
    каждые двадцать секунд впустую.
    """
    tasks = [asyncio.create_task(_loop_hourly(bot, db, panel))]
    if crypto is not None:
        tasks.append(asyncio.create_task(_loop_crypto(bot, db, panel, config, crypto)))

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        raise


async def _loop_hourly(bot: Bot, db: Db, panel: PanelClient) -> None:
    while True:
        try:
            await _tick(bot, db, panel)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            # Упавший цикл не должен уносить бота: без напоминаний он
            # работает, без хендлеров — нет.
            log.exception("Ошибка в фоновом цикле")
        await asyncio.sleep(HOURLY_SECONDS)


async def _loop_crypto(
    bot: Bot,
    db: Db,
    panel: PanelClient,
    config: Config,
    crypto: CryptoClient,
) -> None:
    # Импорт внутри функции, чтобы не тянуть весь пакет хендлеров при
    # импорте планировщика: цикла зависимостей нет, но и лишней связи между
    # фоновым циклом и роутерами тоже быть не должно.
    from .handlers.billing import grant

    while True:
        try:
            pending = await db.pending_crypto_invoices()
            if pending:
                by_id = {inv: (tg, plan_id) for inv, tg, plan_id in pending}
                paid = await crypto.paid_invoice_ids(list(by_id))

                for invoice_id in paid:
                    telegram_id, plan_id = by_id[invoice_id]
                    plan = BY_ID.get(plan_id)
                    if plan is None:
                        log.error("Счёт %s на неизвестный тариф %r", invoice_id, plan_id)
                        continue

                    # Отмечаем оплаченным ДО выдачи: если выдача упадёт,
                    # деньги всё равно записаны и админ получит пинг.
                    # Повторная выдача при этом невозможна — settle вернёт
                    # False на втором проходе.
                    if not await db.settle_crypto_invoice(invoice_id):
                        continue

                    await grant(
                        bot=bot,
                        db=db,
                        config=config,
                        panel=panel,
                        telegram_id=telegram_id,
                        plan=plan,
                        charge_id=f"crypto:{invoice_id}",
                        method="crypto",
                        # telegram_id привязан значением по умолчанию, а не
                        # захвачен из цикла: сейчас grant вызывается сразу и
                        # разницы нет, но стоит вынести вызов из итерации —
                        # и все ключи уедут последнему в пачке.
                        reply=lambda text, _tid=telegram_id, **kw: bot.send_message(
                            _tid, text, **kw
                        ),
                    )
        except asyncio.CancelledError:
            raise
        except (CryptoError, CryptoUnavailable) as exc:
            log.warning("Опрос криптосчетов не удался: %s", exc)
        except Exception:  # noqa: BLE001
            log.exception("Ошибка в цикле криптооплат")

        await asyncio.sleep(CRYPTO_SECONDS)


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
