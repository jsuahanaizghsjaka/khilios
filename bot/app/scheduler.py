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

from . import fmt, incidents, keyboards as kb, texts
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

# Порядок важен: сначала раннее предупреждение, затем более срочные. Каждый
# вид фиксируется отдельно в reminders и для одного срока отправляется один раз.
REMINDERS = (("d3", 3), ("d1", 1), ("d0", 0))

# status.json обновляется раз в 5 минут (cron на панели). Опрашивать чаще
# смысла нет — увидим тот же файл, — а реже значит опоздать с тревогой.
INCIDENT_SECONDS = 60

# Пауза между сообщениями при рассылке. Telegram режет отправку примерно
# на 30 сообщениях в секунду, и при аварии мы шлём всем разом — то есть
# ровно в тот момент, когда упереться в лимит хуже всего.
BROADCAST_PAUSE = 0.05


async def run(
    bot: Bot,
    db: Db,
    panel: PanelClient,
    config: Config,
    crypto: CryptoClient | None,
) -> None:
    """Независимые циклы с разной частотой.

    Разделены намеренно: общий тик пришлось бы делать по частоте самого
    срочного дела, и тогда напоминания об истечении пересчитывались бы
    каждые двадцать секунд впустую.
    """
    tasks = [
        asyncio.create_task(_loop_hourly(bot, db, panel)),
        asyncio.create_task(_loop_incidents(bot, db, config)),
    ]
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
                    # Сначала grant атомарно пишет charge_id в payments, затем
                    # счёт уходит из очереди. Если процесс оборвётся между
                    # шагами, повторный тик увидит charge_id и не выдаст срок
                    # второй раз, но факт оплаты уже останется в базе.
                    await db.settle_crypto_invoice(invoice_id)
        except asyncio.CancelledError:
            raise
        except (CryptoError, CryptoUnavailable) as exc:
            log.warning("Опрос криптосчетов не удался: %s", exc)
        except Exception:  # noqa: BLE001
            log.exception("Ошибка в цикле криптооплат")

        await asyncio.sleep(CRYPTO_SECONDS)


async def _loop_incidents(bot: Bot, db: Db, config: Config) -> None:
    """Следит за состоянием узлов и пишет людям первым, когда что-то легло.

    Это и есть отстройка от рынка: конкуренты пассивны — выдали ключ и
    исчезли, а человек сам гадает, у него сломалось или у всех, и сам
    перебирает узлы. Здесь наоборот.
    """
    while True:
        try:
            await _incident_tick(bot, db, config)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Ошибка в цикле аварий")

        await asyncio.sleep(INCIDENT_SECONDS)


async def _incident_tick(bot: Bot, db: Db, config: Config) -> None:
    nodes, fresh = incidents.read_status(config.status_json_path)
    if not nodes:
        return

    known = await db.known_node_states()

    if not fresh:
        # Файл замер: cron умер или панели плохо. Состояния всё равно
        # запоминаем — иначе, когда он оживёт, разница накопится и уедет
        # пачкой тревог задним числом. А вот рассылать по устаревшему
        # файлу нельзя: получится «узел лежит» про давно поднятый узел.
        for node in nodes:
            if known.get(node.name) != node.state:
                await db.remember_node_state(node.name, node.state)
        return

    events = incidents.diff(known, nodes)

    # Новые узлы просто запоминаем без рассылки — см. incidents.diff().
    for node in nodes:
        if node.name not in known:
            await db.remember_node_state(node.name, node.state)

    if not events:
        return

    healthy = incidents.healthy_names(nodes)
    recipients = await db.active_subscribers()

    for event in events:
        text = _incident_text(event, healthy)
        log.info(
            "Авария: %s %s -> %s, получателей %d",
            event.node, event.was, event.now, len(recipients),
        )

        for telegram_id in recipients:
            await _send(bot, telegram_id, text, kb.back_to_menu())
            await asyncio.sleep(BROADCAST_PAUSE)

        await db.remember_node_state(event.node, event.now)

        # Админу — тем же сообщением, чтобы он узнал об аварии не от
        # клиентов. Отдельный текст не нужен: важен факт и время.
        await _send(bot, config.admin_id, text, kb.back_to_menu())


def _incident_text(event: incidents.Incident, healthy: list[str]) -> str:
    region = event.region or event.node

    if event.recovered:
        return texts.NODE_RECOVERED.format(region=region)

    if not healthy:
        return texts.ALL_NODES_DOWN

    others = texts.OTHERS_WORKING.format(names=", ".join(healthy))
    template = texts.NODE_DEGRADED if event.now == "degraded" else texts.NODE_DOWN
    return template.format(region=region, others=others)


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
