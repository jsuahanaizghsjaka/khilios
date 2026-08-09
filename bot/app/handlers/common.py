"""Старт, согласие, меню, инструкции, поддержка."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import fmt, keyboards as kb, texts
from ..config import Config
from ..db import Db, User

router = Router()


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
    message = target.message if isinstance(target, CallbackQuery) else target
    if isinstance(target, CallbackQuery):
        await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    else:
        await message.answer(text, reply_markup=markup, disable_web_page_preview=True)


@router.message(CommandStart())
async def start(message: Message, db: Db, config: Config) -> None:
    user = await db.get_or_create(message.from_user.id)

    # Согласие на обработку ПД — один раз, при первом /start. Мы оператор
    # персональных данных с первого пользователя, а не с первого платежа.
    if not user.has_consent:
        await message.answer(
            texts.CONSENT.format(offer=config.offer_url, privacy=config.privacy_url),
            reply_markup=kb.consent(config.offer_url, config.privacy_url),
            disable_web_page_preview=True,
        )
        return

    await show_menu(message, user)


@router.callback_query(F.data == kb.CB_CONSENT)
async def consent(call: CallbackQuery, db: Db) -> None:
    await db.set_consent(call.from_user.id)
    user = await db.get(call.from_user.id)
    await show_menu(call, user)
    await call.answer()


@router.callback_query(F.data == kb.CB_MENU)
async def back_to_menu(call: CallbackQuery, db: Db) -> None:
    user = await db.get_or_create(call.from_user.id)
    await show_menu(call, user)
    await call.answer()


@router.callback_query(F.data == kb.CB_SUB)
async def my_subscription(call: CallbackQuery, db: Db) -> None:
    user = await db.get_or_create(call.from_user.id)

    if user.state in {"trial", "active"} and user.sub_url:
        plan = "Пробный" if user.state == "trial" else "Платный"
        text = texts.SUB_ACTIVE.format(
            plan=plan,
            devices=user.devices or 1,
            until=fmt.date(user.expires_at),
            days=user.days_left or 0,
            sub_url=user.sub_url,
        )
        markup = kb.back_to_menu()
    elif user.state == "expired":
        text = texts.SUB_EXPIRED.format(until=fmt.date(user.expires_at))
        markup = kb.renew()
    else:
        text = texts.SUB_NONE
        markup = kb.back_to_menu()

    await call.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    await call.answer()


@router.callback_query(F.data == kb.CB_INSTALL)
async def install(call: CallbackQuery, config: Config) -> None:
    await call.message.edit_text(
        texts.INSTALL,
        reply_markup=kb.install(config.support_url),
        disable_web_page_preview=True,
    )
    await call.answer()


@router.callback_query(F.data == kb.CB_SUPPORT)
async def support(call: CallbackQuery, config: Config) -> None:
    await call.message.edit_text(
        texts.SUPPORT,
        reply_markup=kb.support(config.support_url, config.channel),
        disable_web_page_preview=True,
    )
    await call.answer()


@router.message(Command("help"))
async def help_command(message: Message, config: Config) -> None:
    await message.answer(
        texts.SUPPORT,
        reply_markup=kb.support(config.support_url, config.channel),
        disable_web_page_preview=True,
    )
