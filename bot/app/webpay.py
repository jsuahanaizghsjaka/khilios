"""Локальный веб-сервер для оплаты через ЮKassa.

Слушает только localhost — наружу его публикует Caddy на панельной машине,
проксируя $SUB_HOST/pay/* сюда же, где уже отдаётся страница подписки.
Открывать порт наружу напрямую не нужно: тот же принцип, что и у API
панели, к которой бот тоже ходит по localhost.

Два маршрута, и они разной природы:

  GET  /pay/{order_id}/return   — куда браузер возвращается после оплаты
                                   на странице ЮKassa. Косметика для
                                   человека, НЕ источник истины о платеже:
                                   пользователь может закрыть вкладку до
                                   редиректа, и это не должно ничего ломать.

  POST /pay/webhook/yookassa    — уведомление от ЮKassa. Единственное
                                   место, где заказ реально закрывается,
                                   и именно оно не доверяет присланному
                                   телу — см. предупреждение в yookassa.py.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiohttp import web

from .config import Config
from .db import Db
from .panel import PanelClient
from .plans import BY_ID
from .yookassa import YooKassaClient, YooKassaError, YooKassaUnavailable

log = logging.getLogger(__name__)

RETURN_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>khilios — оплата</title>
<style>
  body {{ font-family: system-ui, sans-serif; background: #0a0e14; color: #e6e9ef;
         display: flex; align-items: center; justify-content: center;
         min-height: 100vh; margin: 0; padding: 24px; text-align: center; }}
  .box {{ max-width: 360px; }}
  h1 {{ font-size: 20px; margin-bottom: 8px; }}
  p {{ color: #9aa4b2; line-height: 1.5; }}
  .ok {{ color: #34d399; }}
</style></head>
<body><div class="box">
  <h1 class="{cls}">{title}</h1>
  <p>{body}</p>
</div></body></html>
"""


def _page(title: str, body: str, ok: bool = False) -> web.Response:
    html = RETURN_PAGE.format(title=title, body=body, cls="ok" if ok else "")
    return web.Response(text=html, content_type="text/html")


async def handle_return(request: web.Request) -> web.Response:
    """Страница, куда возвращается браузер. Только читает статус из своей
    базы (уже обновлённый вебхуком, если он успел прийти), ничего не решает.
    Если вебхук ещё не пришёл — говорим правду: статус уточнится в боте."""
    db: Db = request.app["db"]
    order_id = request.match_info["order_id"]

    order = await db.get_web_order(order_id)
    if order is None:
        return _page("Заказ не найден", "Проверьте ссылку или начните оплату заново в боте.")

    if order["status"] == "succeeded":
        return _page(
            "Оплачено",
            "Ключ уже отправлен в Telegram-бот. Можно закрыть эту страницу.",
            ok=True,
        )

    return _page(
        "Обрабатываем оплату",
        "Обычно это занимает несколько секунд. Ключ придёт в бот — "
        "эту страницу можно закрыть прямо сейчас, ждать здесь не нужно.",
    )


async def handle_webhook(request: web.Request) -> web.Response:
    """Уведомление от ЮKassa. Отвечаем 200 в любом случае, кроме
    невалидного JSON: ЮKassa повторяет доставку при не-200, и вечные
    повторы на наш собственный баг — это шум, а не защита."""
    yk: YooKassaClient = request.app["yookassa"]
    db: Db = request.app["db"]
    panel: PanelClient = request.app["panel"]
    bot: Bot = request.app["bot"]
    config: Config = request.app["config"]

    try:
        payload = await request.json()
    except ValueError:
        log.warning("Вебхук ЮKassa: тело не JSON")
        return web.Response(status=400)

    yk_payment_id = ((payload or {}).get("object") or {}).get("id")
    if not yk_payment_id:
        log.warning("Вебхук ЮKassa без id платежа: %s", payload)
        return web.Response(status=200)

    # НЕ верим payload["object"]["status"] — переспрашиваем API напрямую,
    # статус и сумму разом. Разбор см. в шапке yookassa.py.
    try:
        real_status, real_amount_rub = await yk.get_payment(yk_payment_id)
    except (YooKassaError, YooKassaUnavailable) as exc:
        log.error("Не удалось проверить платёж %s: %s", yk_payment_id, exc)
        return web.Response(status=200)

    if real_status != "succeeded":
        log.info("Платёж %s: статус %s, не закрываю заказ", yk_payment_id, real_status)
        return web.Response(status=200)

    order = await _find_order_by_payment(db, yk_payment_id)
    if order is None:
        log.error("Платёж %s подтверждён, но заказ в базе не найден", yk_payment_id)
        await _alert_admin(bot, config, f"Оплата ЮKassa {yk_payment_id} без заказа в базе — проверить руками.")
        return web.Response(status=200)

    if real_amount_rub != order["amount_rub"]:
        # Не сверка на честность заказа (order_id и yk_payment_id уже
        # совпали), а защита от рассинхрона: если сумма в ЮKassa когда-либо
        # разойдётся с той, что мы выставили при создании (частичный
        # возврат, ручная правка в личном кабинете), выдавать полный тариф
        # по неполной сумме нельзя — тот же принцип, что payment_matches_plan
        # для Telegram-платежей.
        log.error(
            "Заказ %s: сумма ЮKassa %s ₽ не совпадает с ожидаемой %s ₽",
            order["order_id"], real_amount_rub, order["amount_rub"],
        )
        await _alert_admin(
            bot, config,
            f"Оплата ЮKassa {yk_payment_id}: сумма {real_amount_rub} ₽ "
            f"не совпадает с заказом {order['order_id']} ({order['amount_rub']} ₽). "
            f"Заказ НЕ закрыт, ключ не выдан.",
        )
        return web.Response(status=200)

    plan = BY_ID.get(order["plan_id"])
    if plan is None:
        log.error("Заказ %s на неизвестный тариф %r", order["order_id"], order["plan_id"])
        await _alert_admin(bot, config, f"Оплата прошла, тариф {order['plan_id']!r} не найден. Заказ {order['order_id']}.")
        return web.Response(status=200)

    # Импорт внутри функции: webpay не должен тянуть весь пакет handlers
    # при импорте модуля, как и scheduler по той же причине.
    from .handlers.billing import grant

    async def _reply(text: str, **kw) -> None:
        await bot.send_message(order["telegram_id"], text, **kw)

    # grant() ВПЕРЕДИ settle_web_order, а не наоборот. add_payment внутри
    # grant() сама атомарно защищена от повторной выдачи по charge_id
    # (processed_charges, см. db.py) — значит именно она, а не порядок
    # вызовов здесь, гарантирует «не выдать дважды». А вот обратный порядок
    # был бы опасен: упади процесс между settle_web_order (заказ уже
    # succeeded) и grant() — повторный вебхук нашёл бы заказ уже закрытым,
    # молча вышел бы и ключ так и не был бы выдан, без единого пинга админу.
    # При текущем порядке тот же сбой самовосстанавливается: заказ останется
    # pending, следующая доставка вебхука повторит grant() (безопасно за счёт
    # идемпотентности) и на этот раз успешно закроет заказ.
    await grant(
        bot=bot,
        db=db,
        config=config,
        panel=panel,
        telegram_id=order["telegram_id"],
        plan=plan,
        charge_id=f"yookassa:{yk_payment_id}",
        method="yookassa_web",
        reply=_reply,
    )

    await db.settle_web_order(order["order_id"], yk_payment_id)

    return web.Response(status=200)


async def _find_order_by_payment(db: Db, yk_payment_id: str) -> dict | None:
    async with db.conn.execute(
        "SELECT order_id, telegram_id, plan_id, amount_rub, status "
        "FROM web_orders WHERE yk_payment_id = ?",
        (yk_payment_id,),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def _alert_admin(bot: Bot, config: Config, text: str) -> None:
    try:
        await bot.send_message(config.admin_id, text)
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось уведомить админа: %s", exc)


def build_app(
    *, db: Db, panel: PanelClient, bot: Bot, config: Config, yookassa: YooKassaClient
) -> web.Application:
    app = web.Application()
    app["db"] = db
    app["panel"] = panel
    app["bot"] = bot
    app["config"] = config
    app["yookassa"] = yookassa

    app.router.add_get("/pay/{order_id}/return", handle_return)
    app.router.add_post("/pay/webhook/yookassa", handle_webhook)

    return app


async def run(config: Config, app: web.Application) -> web.AppRunner:
    """Запускает сервер на localhost и возвращает runner для остановки
    при завершении бота. Порт не публикуется наружу — см. шапку модуля."""
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", config.web_pay_port)
    await site.start()
    log.info("Веб-сервер оплаты слушает 127.0.0.1:%d", config.web_pay_port)
    return runner
