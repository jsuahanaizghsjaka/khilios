"""Старт, согласие, меню, инструкции, поддержка."""

from __future__ import annotations

from dataclasses import dataclass

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import fmt, keyboards as kb, screens, texts
from ..config import Config
from ..db import Db, User
from ..plans import BY_ID

router = Router()

NODES = {
    "se": "Швеция",
    "de": "Германия",
    "nl": "Нидерланды",
    "fi": "Финляндия",
}


@dataclass(frozen=True)
class StartIntent:
    """Проверенное намерение из Telegram deep link нового сайта."""

    destination: str
    plan_id: str | None = None
    node_id: str | None = None

    @property
    def payload(self) -> str:
        base = f"plan_{self.plan_id}" if self.plan_id else self.destination
        return f"{base}_{self.node_id}" if self.node_id else base


def parse_start_payload(payload: str) -> StartIntent | None:
    """Разобрать только известные payload, не доверяя произвольной строке.

    Сайт передаёт ``site_start_de``, ``site_final_de`` или
    ``plan_standard_de``. Неизвестное значение ведёт в обычное меню и нигде
    не сохраняется.
    """
    raw = payload.strip().lower()
    if not raw or len(raw) > 64:
        return None

    node_id = None
    for candidate in NODES:
        suffix = f"_{candidate}"
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            node_id = candidate
            break

    if raw in {"site_start", "site_final"}:
        return StartIntent(destination=raw, node_id=node_id)

    if raw.startswith("plan_"):
        plan_id = raw.removeprefix("plan_")
        if plan_id in BY_ID:
            return StartIntent(
                destination="plan", plan_id=plan_id, node_id=node_id
            )

    return None


def _message_start_payload(message: Message) -> str:
    parts = (message.text or "").split(maxsplit=1)
    return parts[1] if len(parts) == 2 else ""


def _intent_note(intent: StartIntent) -> str:
    if not intent.node_id:
        return ""
    return (
        f"<b>Точка с сайта: {NODES[intent.node_id]}.</b> "
        "Подписка включает все доступные узлы — при необходимости точку "
        "можно сменить в приложении."
    )


def menu_view(user: User) -> tuple[str, object]:
    """Текст и клавиатура главного меню под состояние пользователя.

    Одна функция на все входы в меню: иначе «Назад» и /start показывают
    разные экраны одному и тому же человеку.
    """
    has_sub = user.state in {"trial", "active"}
    can_trial = not user.had_trial and user.state in {"ready", "expired", "refunded"}

    if has_sub:
        days = user.days_left or 0
        kind = "Пробный период" if user.state == "trial" else "Подписка"
        status = f"{kind} активен до {fmt.date(user.expires_at)} (осталось дней: {days})."
        text = texts.MENU_WITH_SUB.format(status_line=status)
    elif user.state == "expired":
        text = texts.MENU_WITH_SUB.format(
            status_line=f"Подписка закончилась {fmt.date(user.expires_at)}."
        )
    else:
        text = texts.MENU

    return text, kb.menu(has_sub=has_sub, can_trial=can_trial)


async def show_menu(target: Message | CallbackQuery, user: User) -> None:
    text, markup = menu_view(user)
    if isinstance(target, CallbackQuery):
        await screens.edit(target, screens.MENU, text, markup)
    else:
        await screens.send(target, screens.MENU, text, markup)


async def show_start_intent(
    target: Message | CallbackQuery,
    user: User,
    intent: StartIntent | None,
    config: Config,
) -> None:
    """Открыть экран, который пользователь выбрал на сайте."""
    if intent is None or intent.plan_id is None:
        text, markup = menu_view(user)
        asset = screens.MENU
    elif intent.plan_id == "trial":
        if user.had_trial:
            text = texts.TRIAL_ALREADY + "\n\n" + texts.tariffs()
            markup = kb.tariffs(payments_enabled=config.payments_enabled)
            asset = screens.TARIFFS
        else:
            text, markup = menu_view(user)
            asset = screens.MENU
    else:
        asset = screens.TARIFFS
        plan = BY_ID[intent.plan_id]
        if config.payments_enabled:
            text = texts.PICK_METHOD.format(
                plan=plan.name,
                price=plan.price_rub,
                devices=plan.devices,
                days=plan.days,
            )
            markup = kb.pay_methods(
                plan.id,
                card=config.card_enabled,
                webpay=config.web_pay_enabled,
                stars=config.stars_enabled and plan.price_stars > 0,
                crypto=config.crypto_enabled,
                stars_price=plan.price_stars,
            )
        else:
            text = texts.tariffs() + "\n\n" + texts.PAYMENTS_OFF
            markup = kb.tariffs(payments_enabled=False)

    note = _intent_note(intent) if intent else ""
    if note:
        text = note + "\n\n" + text

    if isinstance(target, CallbackQuery):
        await screens.edit(target, asset, text, markup)
    else:
        await screens.send(target, asset, text, markup)


@router.message(CommandStart())
async def start(message: Message, db: Db, config: Config) -> None:
    user = await db.get_or_create(message.from_user.id)
    intent = parse_start_payload(_message_start_payload(message))

    # Согласие на обработку ПД — один раз, при первом /start. Мы оператор
    # персональных данных с первого пользователя, а не с первого платежа.
    if not user.has_consent:
        await message.answer(
            texts.CONSENT.format(offer=config.offer_url, privacy=config.privacy_url),
            reply_markup=kb.consent(
                config.offer_url,
                config.privacy_url,
                intent.payload if intent else "",
            ),
            disable_web_page_preview=True,
        )
        return

    await show_start_intent(message, user, intent, config)


@router.callback_query(
    (F.data == kb.CB_CONSENT) | F.data.startswith(f"{kb.CB_CONSENT}:")
)
async def consent(call: CallbackQuery, db: Db, config: Config) -> None:
    await db.set_consent(call.from_user.id)
    user = await db.get(call.from_user.id)
    payload = call.data.partition(":")[2]
    await show_start_intent(call, user, parse_start_payload(payload), config)
    await call.answer()


@router.callback_query(F.data == kb.CB_MENU)
async def back_to_menu(call: CallbackQuery, db: Db) -> None:
    user = await db.get_or_create(call.from_user.id)
    await show_menu(call, user)
    await call.answer()


@router.callback_query(F.data == kb.CB_SUB)
async def my_subscription(call: CallbackQuery, db: Db, config: Config) -> None:
    user = await db.get_or_create(call.from_user.id)

    if user.state in {"trial", "active"} and user.sub_url:
        plan = "Пробный" if user.state == "trial" else "Платный"
        text = texts.SUB_ACTIVE.format(
            plan=plan,
            devices=user.devices or 1,
            until=fmt.date(user.expires_at),
            days=user.days_left or 0,
        )
        markup = kb.active_subscription(user.sub_url, config.web_pay_host)
    elif user.state == "expired":
        text = texts.SUB_EXPIRED.format(until=fmt.date(user.expires_at))
        markup = kb.renew()
    else:
        text = texts.SUB_NONE
        markup = kb.back_to_menu()

    asset = screens.SUCCESS if user.state in {"trial", "active"} else screens.TARIFFS
    await screens.edit(call, asset, text, markup)
    await call.answer()


@router.callback_query(F.data == kb.CB_INSTALL)
async def install(call: CallbackQuery, config: Config, db: Db) -> None:
    user = await db.get_or_create(call.from_user.id)
    sub_url = user.sub_url if user.state in {"trial", "active"} else None
    await screens.edit(
        call,
        screens.CONNECT,
        texts.INSTALL,
        kb.install(
            config.support_url,
            sub_url=sub_url,
            web_pay_host=config.web_pay_host,
        ),
    )
    await call.answer()


@router.callback_query(F.data == kb.CB_SUPPORT)
async def support(call: CallbackQuery, config: Config) -> None:
    await screens.edit(
        call,
        screens.SUPPORT,
        texts.SUPPORT,
        kb.support(config.support_url, config.channel),
    )
    await call.answer()


@router.message(Command("help"))
async def help_command(message: Message, config: Config) -> None:
    await screens.send(
        message,
        screens.SUPPORT,
        texts.SUPPORT,
        kb.support(config.support_url, config.channel),
    )
