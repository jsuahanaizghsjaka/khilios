"""Тарифы и оплата.

Два правила, которые здесь нельзя нарушить.

**Автосписания нет.** Сайт обещает: «Автосписания нет — ни на пробном, ни
после него». Поэтому инвойс разовый, платёжное средство не сохраняется, и
никакого recurring в провайдере включать нельзя.

**На оплате гейта по каналу нет.** Платящий получает ключ сразу. Держать
оплаченный доступ в заложниках у подписки на канал — верный способ получить
первый возврат и первый плохой отзыв в один день.
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
from ..db import Db
from ..panel import PanelClient, PanelError, PanelUnavailable
from ..plans import BY_ID

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
async def buy(call: CallbackQuery, bot: Bot, config: Config) -> None:
    plan = BY_ID.get(call.data.removeprefix(kb.CB_BUY))
    if plan is None or plan.price_rub == 0:
        await call.answer()
        return

    if not config.payments_enabled:
        await call.answer(texts.PAYMENTS_OFF, show_alert=True)
        return

    await call.answer()
    await bot.send_invoice(
        chat_id=call.from_user.id,
        title=texts.PAY_INVOICE_TITLE.format(plan=plan.name),
        description=texts.PAY_INVOICE_DESC.format(
            devices=plan.devices, days=plan.days
        ),
        # payload несёт тариф до успешного платежа: на него мы будем смотреть
        # при выдаче, а не на сумму. Сумма может прийти с округлением провайдера.
        payload=f"plan:{plan.id}",
        provider_token=config.payment_token,
        currency="RUB",
        # Telegram считает в копейках.
        prices=[LabeledPrice(label=plan.name, amount=plan.price_rub * 100)],
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
    payment = message.successful_payment
    telegram_id = message.from_user.id
    charge_id = payment.telegram_payment_charge_id

    # Telegram умеет доставить successful_payment повторно. Без этой проверки
    # повторная доставка продлевает подписку второй раз бесплатно.
    if await db.charge_seen(charge_id):
        log.info("Повторная доставка платежа %s, пропускаю", charge_id)
        return

    plan = BY_ID.get(payment.invoice_payload.removeprefix("plan:"))
    if plan is None:
        log.error("Платёж %s с неизвестным тарифом %r", charge_id, payment.invoice_payload)
        await _alert_admin(bot, config, f"Платёж {charge_id} с неизвестным тарифом.")
        await message.answer(texts.ERROR_ISSUE_FAILED)
        return

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
        await _alert_admin(
            bot,
            config,
            f"Оплата прошла, ключ НЕ выдан.\n"
            f"Пользователь: {telegram_id}\nТариф: {plan.id}\n"
            f"Платёж: {charge_id}\nОшибка: {exc}",
        )
        await message.answer(
            texts.ERROR_ISSUE_FAILED,
            reply_markup=kb.support(config.support_url, config.channel),
        )
        return

    await db.save_subscription(
        telegram_id,
        state="active",
        panel_uuid=uuid,
        sub_url=sub_url,
        expires_at=expires_at,
        devices=plan.devices,
    )

    await message.answer(
        texts.PAY_OK.format(
            plan=plan.name,
            until=fmt.date(expires_at),
            devices=plan.devices,
            sub_url=sub_url,
        ),
        reply_markup=kb.after_issue(),
        disable_web_page_preview=True,
    )
    log.info("Оплата: %s, тариф %s, до %s", telegram_id, plan.id, expires_at)
    await _alert_admin(
        bot, config, f"Оплата: {plan.name}, {plan.price_rub} ₽, пользователь {telegram_id}"
    )


async def _alert_admin(bot: Bot, config: Config, text: str) -> None:
    try:
        await bot.send_message(config.admin_id, text)
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось уведомить админа: %s", exc)
