"""Тарифы и оплата.

Пять рельсов, четыре механики:

- **карта МИР и СБП через Telegram** — Telegram Payments с токеном
  провайдера (ЮKassa), форму рисует сам Telegram;
- **карта МИР и СБП веб-чекаутом** — прямой вызов API ЮKassa, форму
  рисует страница ЮKassa (redirect), подтверждение приходит вебхуком
  на локальный сервер бота, см. webpay.py и yookassa.py;
- **Telegram Stars** — тот же Telegram Payments, но валюта XTR и пустой
  токен провайдера: Stars внутренняя валюта, посредник не нужен;
- **криптовалюта** — @CryptoBot, оплата подтверждается опросом,
  см. crypto.py.

Первые два Telegram-способа приходят готовым событием `successful_payment`
и потому делят один обработчик. Крипта подтверждается опросом в
scheduler.py. Веб-чекаут подтверждается вебхуком в webpay.py и вызывает
grant() напрямую оттуда — здесь для него только создание заказа и ссылки.

Три правила, которые здесь нельзя нарушить.

**Автосписания нет ни при одном способе.** Сайт обещает: «Автосписания нет —
ни на пробном, ни после него». Значит счёт разовый, платёжное средство не
сохраняется, recurring в провайдере не включается.

**На оплате гейта по каналу нет.** Платящий получает ключ сразу. Держать
оплаченный доступ в заложниках у подписки на канал — верный способ получить
первый возврат и первый плохой отзыв в один день.

**Выдача идёт одним путём для всех способов.** `grant()` — единственное
место, где подписка превращается в ключ. Три копии этой логики разъехались
бы на первой же правке, и разъехались бы молча.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import (
    CallbackQuery,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from .. import fmt, keyboards as kb, texts
from ..config import Config
from ..crypto import CryptoClient, CryptoError, CryptoUnavailable
from ..db import Db
from ..panel import PanelClient, PanelError, PanelUnavailable
from ..plans import BY_ID, Plan
from ..yookassa import YooKassaClient, YooKassaError, YooKassaUnavailable, new_order_id

log = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data == kb.CB_TARIFFS)
async def tariffs(call: CallbackQuery, config: Config) -> None:
    text = texts.tariffs()
    if not config.payments_enabled:
        text += "\n\n" + texts.PAYMENTS_OFF
    await call.message.edit_text(
        text,
        reply_markup=kb.tariffs(payments_enabled=config.payments_enabled),
        disable_web_page_preview=True,
    )
    await call.answer()


@router.callback_query(F.data.startswith(kb.CB_BUY))
async def pick_method(call: CallbackQuery, config: Config) -> None:
    plan = BY_ID.get(call.data.removeprefix(kb.CB_BUY))
    if plan is None or plan.price_rub == 0:
        await call.answer()
        return

    if not config.payments_enabled:
        await call.answer(texts.PAYMENTS_OFF, show_alert=True)
        return

    await call.message.edit_text(
        texts.PICK_METHOD.format(
            plan=plan.name,
            price=plan.price_rub,
            devices=plan.devices,
            days=plan.days,
        ),
        reply_markup=kb.pay_methods(
            plan.id,
            card=config.card_enabled,
            webpay=config.web_pay_enabled,
            # Stars предлагаем только если цена в них проставлена: тариф
            # с price_stars=0 отдался бы бесплатно.
            stars=config.stars_enabled and plan.price_stars > 0,
            crypto=config.crypto_enabled,
            stars_price=plan.price_stars,
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith(kb.CB_PAY))
async def start_payment(
    call: CallbackQuery,
    bot: Bot,
    db: Db,
    config: Config,
    crypto: CryptoClient | None,
    yookassa: YooKassaClient | None,
) -> None:
    raw = call.data.removeprefix(kb.CB_PAY)
    plan_id, _, method = raw.rpartition(":")
    plan = BY_ID.get(plan_id)

    if plan is None or plan.price_rub == 0:
        await call.answer()
        return

    if method == "card" and config.card_enabled:
        await call.answer()
        await _send_card_invoice(bot, call.from_user.id, plan, config)

    elif method == "webpay" and config.web_pay_enabled and yookassa is not None:
        await _send_web_checkout(call, db, config, yookassa, plan)

    elif method == "stars" and config.stars_enabled and plan.price_stars > 0:
        await call.answer()
        await _send_stars_invoice(bot, call.from_user.id, plan)

    elif method == "crypto" and config.crypto_enabled and crypto is not None:
        await _send_crypto_invoice(call, db, crypto, plan)

    else:
        # Способ выключили между показом кнопки и нажатием.
        await call.answer(texts.PAYMENTS_OFF, show_alert=True)


async def _send_card_invoice(
    bot: Bot, chat_id: int, plan: Plan, config: Config
) -> None:
    await bot.send_invoice(
        chat_id=chat_id,
        title=texts.PAY_INVOICE_TITLE.format(plan=plan.name),
        description=texts.PAY_INVOICE_DESC.format(devices=plan.devices, days=plan.days),
        # payload несёт тариф до успешного платежа: на него смотрим при
        # выдаче, а не на сумму — её провайдер может округлить.
        payload=f"plan:{plan.id}",
        provider_token=config.payment_token,
        currency="RUB",
        prices=[LabeledPrice(label=plan.name, amount=plan.price_rub * 100)],
    )


async def _send_stars_invoice(bot: Bot, chat_id: int, plan: Plan) -> None:
    await bot.send_invoice(
        chat_id=chat_id,
        title=texts.PAY_INVOICE_TITLE.format(plan=plan.name),
        description=texts.PAY_INVOICE_DESC.format(devices=plan.devices, days=plan.days),
        payload=f"plan:{plan.id}",
        # Stars — внутренняя валюта Telegram: провайдера нет, токен пустой,
        # сумма в целых звёздах, а не в сотых долях, как у обычных валют.
        # Пустая строка здесь — требование API, а не забытый секрет:
        # непустой токен с валютой XTR Telegram отвергает.
        provider_token="",  # nosec B106
        currency="XTR",
        prices=[LabeledPrice(label=plan.name, amount=plan.price_stars)],
    )


async def _send_web_checkout(
    call: CallbackQuery, db: Db, config: Config, yookassa: YooKassaClient, plan: Plan
) -> None:
    """Заказ веб-чекаута. Создаём его в базе ДО обращения к ЮKassa: order_id
    нужен как Idempotence-Key, а не наоборот — так повторный клик по кнопке
    из-за медленной сети не создаст в ЮKassa два разных платежа."""
    await call.answer()

    order_id = new_order_id()
    await db.create_web_order(order_id, call.from_user.id, plan.id, plan.price_rub)

    return_url = f"https://{config.web_pay_host}/pay/{order_id}/return"

    try:
        yk_payment_id, pay_url = await yookassa.create_payment(
            order_id=order_id,
            amount_rub=plan.price_rub,
            plan_name=plan.name,
            return_url=return_url,
        )
    except (YooKassaError, YooKassaUnavailable) as exc:
        log.error("Не создан веб-заказ для %s: %s", call.from_user.id, exc)
        await db.cancel_web_order(order_id)
        await call.message.edit_text(texts.WEBPAY_OFF, reply_markup=kb.back_to_menu())
        return

    await db.attach_yk_payment(order_id, yk_payment_id)

    await call.message.edit_text(
        texts.WEBPAY_INVOICE.format(price=plan.price_rub),
        reply_markup=kb.crypto_invoice(pay_url),
    )


async def _send_crypto_invoice(
    call: CallbackQuery, db: Db, crypto: CryptoClient, plan: Plan
) -> None:
    await call.answer("Выставляю счёт…")
    try:
        invoice_id, url = await crypto.create_invoice(
            amount_rub=plan.price_rub,
            plan_id=plan.id,
            telegram_id=call.from_user.id,
        )
    except (CryptoError, CryptoUnavailable) as exc:
        log.error("Не выставлен счёт для %s: %s", call.from_user.id, exc)
        await call.message.edit_text(texts.CRYPTO_OFF, reply_markup=kb.back_to_menu())
        return

    await db.add_crypto_invoice(invoice_id, call.from_user.id, plan.id)

    await call.message.edit_text(
        texts.CRYPTO_INVOICE.format(price=plan.price_rub),
        reply_markup=kb.crypto_invoice(url),
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, bot: Bot) -> None:
    plan = BY_ID.get(query.invoice_payload.removeprefix("plan:"))
    if plan is None:
        await bot.answer_pre_checkout_query(
            query.id, ok=False, error_message="Тариф больше не доступен."
        )
        return
    await bot.answer_pre_checkout_query(query.id, ok=True)


@router.message(F.successful_payment)
async def paid(
    message: Message,
    db: Db,
    config: Config,
    panel: PanelClient,
    bot: Bot,
) -> None:
    """Карта, СБП и Stars приходят сюда одинаково."""
    payment = message.successful_payment
    charge_id = payment.telegram_payment_charge_id

    # Telegram умеет доставить successful_payment повторно. Без этой проверки
    # повторная доставка продлевает подписку второй раз бесплатно.
    if await db.charge_seen(charge_id):
        log.info("Повторная доставка платежа %s, пропускаю", charge_id)
        return

    plan = BY_ID.get(payment.invoice_payload.removeprefix("plan:"))
    if plan is None:
        log.error("Платёж %s с неизвестным тарифом %r", charge_id, payment.invoice_payload)
        await alert_admin(bot, config, f"Платёж {charge_id} с неизвестным тарифом.")
        await message.answer(texts.ERROR_ISSUE_FAILED)
        return

    # В Stars сумма приходит в звёздах, в рублях — в копейках. Для учёта
    # пишем рублёвую цену тарифа: сводка в /stats должна быть в одной
    # валюте, иначе «выручка» станет суммой рублей со звёздами.
    method = "stars" if payment.currency == "XTR" else "card"

    await grant(
        bot=bot,
        db=db,
        config=config,
        panel=panel,
        telegram_id=message.from_user.id,
        plan=plan,
        charge_id=charge_id,
        method=method,
        reply=message.answer,
    )


async def grant(
    *,
    bot: Bot,
    db: Db,
    config: Config,
    panel: PanelClient,
    telegram_id: int,
    plan: Plan,
    charge_id: str,
    method: str,
    reply,
) -> bool:
    """Записать платёж и выдать ключ. Единственный путь выдачи.

    Возвращает True, если ключ выдан. Вызывается и из обработчика
    Telegram-платежей, и из опроса криптосчетов — поэтому reply передаётся
    функцией: у опроса нет исходного сообщения, ему нужен send_message.
    """
    # Деньги записываем ДО обращения к панели. Если панель не ответит, факт
    # оплаты всё равно зафиксирован — иначе при разборе «я платил» опереться
    # будет не на что.
    await db.add_payment(telegram_id, plan.id, plan.price_rub, charge_id)

    user = await db.get_or_create(telegram_id)

    try:
        if user.panel_uuid:
            uuid, sub_url, expires_at = await panel.extend(
                user.panel_uuid, days=plan.days, devices=plan.devices
            )
        else:
            uuid, sub_url, expires_at = await panel.create_user(
                telegram_id=telegram_id,
                days=plan.days,
                devices=plan.devices,
                tag=plan.id,
            )
    except (PanelError, PanelUnavailable) as exc:
        # Худший случай: деньги взяты, ключа нет. Пользователю — честный текст
        # и поддержка, админу — немедленный пинг, чтобы выдать руками.
        log.error("Оплата %s прошла, панель не ответила: %s", charge_id, exc)
        await alert_admin(
            bot,
            config,
            f"Оплата прошла, ключ НЕ выдан.\n"
            f"Пользователь: {telegram_id}\nТариф: {plan.id}\nСпособ: {method}\n"
            f"Платёж: {charge_id}\nОшибка: {exc}",
        )
        await reply(
            texts.ERROR_ISSUE_FAILED,
            reply_markup=kb.support(config.support_url, config.channel),
        )
        return False

    await db.save_subscription(
        telegram_id,
        state="active",
        panel_uuid=uuid,
        sub_url=sub_url,
        expires_at=expires_at,
        devices=plan.devices,
    )

    await reply(
        texts.PAY_OK.format(
            plan=plan.name,
            until=fmt.date(expires_at),
            devices=plan.devices,
            sub_url=sub_url,
        ),
        reply_markup=kb.after_issue(),
        disable_web_page_preview=True,
    )

    log.info("Оплата (%s): %s, тариф %s, до %s", method, telegram_id, plan.id, expires_at)
    await alert_admin(
        bot,
        config,
        f"Оплата ({method}): {plan.name}, {plan.price_rub} ₽, пользователь {telegram_id}",
    )
    return True


async def alert_admin(bot: Bot, config: Config, text: str) -> None:
    try:
        await bot.send_message(config.admin_id, text)
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось уведомить админа: %s", exc)
