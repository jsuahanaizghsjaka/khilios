"""Клавиатуры.

Все callback_data собраны здесь константами: строковый литерал, набранный
в двух местах по-разному, — это кнопка, которая молча ничего не делает.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .plans import PAID

CB_CONSENT = "consent"
CB_MENU = "menu"
CB_TRIAL = "trial"
CB_GATE_CHECK = "gate_check"
CB_TARIFFS = "tariffs"
CB_SUB = "sub"
CB_INSTALL = "install"
CB_SUPPORT = "support"
CB_BUY = "buy:"  # + plan_id — открывает выбор способа оплаты
CB_PAY = "pay:"  # + plan_id + ":" + method (card / stars / crypto)

HAPP_URL = "https://happ.su/main/ru"


def consent(offer_url: str, privacy_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Оферта", url=offer_url)
    kb.button(text="Политика", url=privacy_url)
    kb.button(text="Согласен, продолжить", callback_data=CB_CONSENT)
    kb.adjust(2, 1)
    return kb.as_markup()


def menu(*, has_sub: bool, can_trial: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if can_trial:
        kb.button(text="Попробовать 7 дней", callback_data=CB_TRIAL)
    if has_sub:
        kb.button(text="Моя подписка", callback_data=CB_SUB)
    kb.button(text="Тарифы", callback_data=CB_TARIFFS)
    kb.button(text="Как подключить", callback_data=CB_INSTALL)
    kb.button(text="Поддержка", callback_data=CB_SUPPORT)
    kb.adjust(1, 1, 2, 1)
    return kb.as_markup()


def gate(channel: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Открыть канал", url=f"https://t.me/{channel.lstrip('@')}")
    kb.button(text="Я подписался", callback_data=CB_GATE_CHECK)
    kb.adjust(1)
    return kb.as_markup()


def tariffs(*, payments_enabled: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if payments_enabled:
        for plan in PAID:
            kb.button(
                text=f"{plan.name} — {plan.price_rub} ₽",
                callback_data=f"{CB_BUY}{plan.id}",
            )
    kb.button(text="Назад", callback_data=CB_MENU)
    kb.adjust(1)
    return kb.as_markup()


def pay_methods(
    plan_id: str, *, card: bool, stars: bool, crypto: bool, stars_price: int
) -> InlineKeyboardMarkup:
    """Способы оплаты для выбранного тарифа.

    Показываются только доступные: кнопка способа, который не подключён, —
    это тупик, в который человек упирается уже с намерением заплатить.
    """
    kb = InlineKeyboardBuilder()
    if card:
        kb.button(text="Картой МИР или СБП", callback_data=f"{CB_PAY}{plan_id}:card")
    if stars:
        kb.button(
            text=f"Telegram Stars — {stars_price} ★",
            callback_data=f"{CB_PAY}{plan_id}:stars",
        )
    if crypto:
        kb.button(text="Криптовалютой", callback_data=f"{CB_PAY}{plan_id}:crypto")
    kb.button(text="Назад к тарифам", callback_data=CB_TARIFFS)
    kb.adjust(1)
    return kb.as_markup()


def crypto_invoice(url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Оплатить", url=url)
    kb.button(text="В меню", callback_data=CB_MENU)
    kb.adjust(1)
    return kb.as_markup()


def after_issue() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Скачать приложение", url=HAPP_URL)
    kb.button(text="Как подключить", callback_data=CB_INSTALL)
    kb.button(text="В меню", callback_data=CB_MENU)
    kb.adjust(1)
    return kb.as_markup()


def install(support_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Скачать приложение", url=HAPP_URL)
    if support_url:
        kb.button(text="Написать в поддержку", url=support_url)
    kb.button(text="В меню", callback_data=CB_MENU)
    kb.adjust(1)
    return kb.as_markup()


def support(support_url: str, channel: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if support_url:
        kb.button(text="Написать в поддержку", url=support_url)
    kb.button(text="Канал", url=f"https://t.me/{channel.lstrip('@')}")
    kb.button(text="В меню", callback_data=CB_MENU)
    kb.adjust(1)
    return kb.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data=CB_MENU)]]
    )


def renew() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Продлить", callback_data=CB_TARIFFS)]
        ]
    )
