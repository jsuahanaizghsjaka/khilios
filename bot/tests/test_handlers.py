"""Сборка роутеров и экранов.

Импорт пакета handlers прогоняет все декораторы aiogram — здесь всплывает
неправильно названный фильтр или несуществующий тип апдейта. Без этого теста
такое находится только на живом боте.
"""

from __future__ import annotations

import pytest

from app import handlers, keyboards as kb, screens, texts
from app.db import User
from app.handlers.common import menu_view, parse_start_payload
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


def _urls(markup) -> list[str]:
    return [b.url for row in markup.inline_keyboard for b in row if b.url]


def test_fresh_user_is_offered_trial():
    _, markup = menu_view(_user())
    assert any("Попробовать 7 дней" in button for button in _buttons(markup))


def test_user_who_had_trial_is_not_offered_it_again():
    user = _user(state="expired", trial_issued_at="2026-08-01T00:00:00+00:00")
    _, markup = menu_view(user)
    assert not any("Попробовать 7 дней" in button for button in _buttons(markup))


def test_active_subscriber_sees_their_subscription():
    user = _user(
        state="active",
        expires_at="2030-01-01T00:00:00+00:00",
        sub_url="https://sub.example/x",
        devices=5,
    )
    text, markup = menu_view(user)
    assert any("Моя подписка" in button for button in _buttons(markup))
    assert "активен до" in text


def test_active_subscription_has_renew_button():
    labels = _buttons(kb.renew())
    assert any("Продлить подписку" in button for button in labels)
    assert any("В меню" in button for button in labels)


def test_success_screen_allows_another_renewal():
    markup = kb.after_issue(
        "https://sub.example.net/api/subscription/token",
        "sub.example.net",
    )
    assert any("Продлить подписку" in button for button in _buttons(markup))


def test_success_screen_connects_through_happ_bridge_without_exposing_key():
    sub_url = "https://sub.example.net/api/subscription/secret-token"
    markup = kb.after_issue(sub_url, "sub.example.net")

    assert any("Подключиться к VPN" in button for button in _buttons(markup))
    assert _urls(markup)[0].startswith("https://sub.example.net/pay/happ?subscription=")
    assert all(sub_url not in url for url in _urls(markup))


def test_active_subscription_has_connect_renew_and_menu_buttons():
    markup = kb.active_subscription(
        "https://sub.example.net/api/subscription/token",
        "sub.example.net",
    )
    labels = _buttons(markup)

    assert any("Подключиться к VPN" in button for button in labels)
    assert any("Продлить подписку" in button for button in labels)
    assert any("В меню" in button for button in labels)


def test_subscription_messages_do_not_expose_raw_link():
    assert "{sub_url}" not in texts.TRIAL_ISSUED
    assert "{sub_url}" not in texts.SUB_ACTIVE
    assert "{sub_url}" not in texts.PAY_OK


def test_tariffs_explain_that_active_period_is_preserved():
    assert "купленный срок прибавится к текущему" in texts.tariffs()


def test_media_assets_exist_and_fit_telegram_captions():
    for asset in screens.ALL:
        path = screens.ASSET_DIR / asset
        assert path.is_file()
        assert path.stat().st_size < 10 * 1024 * 1024

    captions = [texts.MENU, texts.tariffs(), texts.INSTALL, texts.SUPPORT]
    assert all(len(caption) <= 1024 for caption in captions)


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


@pytest.mark.parametrize(
    ("payload", "plan_id", "node_id"),
    [
        ("plan_trial_de", "trial", "de"),
        ("plan_basic_se", "basic", "se"),
        ("plan_standard_nl", "standard", "nl"),
        ("plan_year_fi", "year", "fi"),
        ("site_start_de", None, "de"),
        ("site_final_fi", None, "fi"),
    ],
)
def test_site_deep_links_are_parsed(payload, plan_id, node_id):
    intent = parse_start_payload(payload)
    assert intent is not None
    assert intent.plan_id == plan_id
    assert intent.node_id == node_id
    assert intent.payload == payload


@pytest.mark.parametrize(
    "payload", ["plan_unknown_de", "plan_standard_xx", "garbage", "x" * 65]
)
def test_unknown_deep_links_fall_back_to_menu(payload):
    assert parse_start_payload(payload) is None


def test_consent_keeps_site_destination_within_telegram_limit():
    markup = kb.consent(
        "https://khilios.net/legal/offer",
        "https://khilios.net/legal/privacy",
        "plan_standard_de",
    )
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert callbacks == ["consent:plan_standard_de"]
    assert len(callbacks[0].encode()) <= 64


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
