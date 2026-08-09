"""Сборка роутеров и экранов.

Импорт пакета handlers прогоняет все декораторы aiogram — здесь всплывает
неправильно названный фильтр или несуществующий тип апдейта. Без этого теста
такое находится только на живом боте.
"""

from __future__ import annotations

import pytest

from app import handlers, keyboards as kb, texts
from app.db import User
from app.handlers.common import menu_view
from app.plans import BY_ID


def _user(**over) -> User:
    base = dict(
        telegram_id=1,
        state="ready",
        consent_at="2026-08-09T00:00:00+00:00",
        trial_issued_at=None,
        panel_uuid=None,
        sub_url=None,
        expires_at=None,
        devices=None,
    )
    base.update(over)
    return User(**base)


def test_routers_assemble():
    assert handlers.router() is not None


def _buttons(markup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row]


def test_fresh_user_is_offered_trial():
    _, markup = menu_view(_user())
    assert "Попробовать 7 дней" in _buttons(markup)


def test_user_who_had_trial_is_not_offered_it_again():
    user = _user(state="expired", trial_issued_at="2026-08-01T00:00:00+00:00")
    _, markup = menu_view(user)
    assert "Попробовать 7 дней" not in _buttons(markup)


def test_active_subscriber_sees_their_subscription():
    user = _user(
        state="active",
        expires_at="2030-01-01T00:00:00+00:00",
        sub_url="https://sub.example/x",
        devices=5,
    )
    text, markup = menu_view(user)
    assert "Моя подписка" in _buttons(markup)
    assert "активен до" in text


def test_tariffs_keyboard_hides_buy_buttons_without_payment_token():
    """Пока платёжка на модерации, кнопка «купить» вести никуда не должна."""
    without = _buttons(kb.tariffs(payments_enabled=False))
    assert not [b for b in without if "₽" in b]

    with_payments = _buttons(kb.tariffs(payments_enabled=True))
    assert len([b for b in with_payments if "₽" in b]) == 3


@pytest.mark.parametrize("plan_id", ["basic", "standard", "year"])
def test_buy_callback_resolves_to_a_plan(plan_id):
    """callback_data кнопки должен разбираться обратно в тариф —
    иначе кнопка молча ничего не делает."""
    data = f"{kb.CB_BUY}{plan_id}"
    assert BY_ID.get(data.removeprefix(kb.CB_BUY)) is not None


# Словарь из docs/bot-checklist.md: бот — такая же публичная площадка,
# как сайт, и текст в нём читается так же.
FORBIDDEN = [
    "обход блокировок",
    "обходит блокировки",
    "запрещённы",
    "доступ ко всему интернету",
    "без ограничений",
    "работает всегда",
]


def test_texts_avoid_forbidden_vocabulary():
    blob = "\n".join(
        value
        for name, value in vars(texts).items()
        if isinstance(value, str) and not name.startswith("_")
    )
    blob += "\n" + texts.tariffs()
    blob += "\n" + "\n".join(texts.REMIND.values())

    lowered = blob.lower()
    found = [phrase for phrase in FORBIDDEN if phrase in lowered]
    assert not found, f"Запрещённые формулировки в текстах бота: {found}"
