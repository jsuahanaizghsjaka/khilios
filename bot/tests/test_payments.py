"""Оплата: выбор способа, разбор callback_data, защита от двойной выдачи.

Каждая проверка здесь закрывает случай, который стоит денег: показанный
способ, который не подключён; кнопка, не разбирающаяся обратно в тариф;
криптосчёт, выданный дважды.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import keyboards as kb
from app.db import Db
from app.handlers.billing import grant, payment_matches_plan
from app.plans import BY_ID, PAID


@pytest.fixture
async def db(tmp_path):
    store = Db(str(tmp_path / "pay.sqlite3"))
    await store.connect()
    yield store
    await store.close()


def _buttons(markup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row]


def _callbacks(markup) -> list[str]:
    return [
        b.callback_data
        for row in markup.inline_keyboard
        for b in row
        if b.callback_data
    ]


# --- выбор способа --------------------------------------------------------


def test_only_enabled_methods_are_shown():
    """Кнопка неподключённого способа — тупик, в который человек упирается
    уже с намерением заплатить."""
    markup = kb.pay_methods(
        "standard", card=True, webpay=False, stars=False, crypto=False, stars_price=165
    )
    labels = " ".join(_buttons(markup))
    assert "Telegram" in labels
    assert "на сайте" not in labels
    assert "Stars" not in labels
    assert "Крипто" not in labels


def test_all_methods_can_be_shown_together():
    markup = kb.pay_methods(
        "standard", card=True, webpay=True, stars=True, crypto=True, stars_price=165
    )
    assert len([c for c in _callbacks(markup) if c.startswith(kb.CB_PAY)]) == 4


def test_card_and_webpay_labels_are_distinguishable():
    """card и webpay — оба «карта или СБП», но разными путями. Одинаковые
    подписи означают, что человек не поймёт разницу между кнопками."""
    markup = kb.pay_methods(
        "standard", card=True, webpay=True, stars=False, crypto=False, stars_price=165
    )
    labels = _buttons(markup)
    card_label = next(b for b in labels if "Telegram" in b)
    webpay_label = next(b for b in labels if "сайте" in b)
    assert card_label != webpay_label


def test_stars_button_shows_price():
    markup = kb.pay_methods(
        "year", card=False, webpay=False, stars=True, crypto=False, stars_price=1100
    )
    assert any("1100" in b for b in _buttons(markup))


@pytest.mark.parametrize("plan_id", ["basic", "standard", "year"])
@pytest.mark.parametrize("method", ["card", "webpay", "stars", "crypto"])
def test_pay_callback_parses_back_to_plan_and_method(plan_id, method):
    """Разбор callback_data повторяет то, что делает хендлер. Если формат
    поедет, кнопка молча перестанет работать — без ошибки в логе."""
    data = f"{kb.CB_PAY}{plan_id}:{method}"

    raw = data.removeprefix(kb.CB_PAY)
    parsed_plan, _, parsed_method = raw.rpartition(":")

    assert parsed_plan == plan_id
    assert parsed_method == method
    assert BY_ID.get(parsed_plan) is not None


# --- цены -----------------------------------------------------------------


def test_paid_plans_have_stars_price():
    """Тариф с price_stars=0 отдался бы за ноль звёзд."""
    for plan in PAID:
        assert plan.price_stars > 0, f"{plan.id}: не задана цена в Stars"


def test_stars_price_is_in_sane_range_of_rub_price():
    """Не курс, а грубая ловушка на опечатку в разряде: 1100 вместо 110
    и наоборот. Точный курс задаёт Telegram, сверяется руками."""
    for plan in PAID:
        implied = plan.price_rub / plan.price_stars
        assert 0.5 < implied < 5, (
            f"{plan.id}: {plan.price_rub} ₽ за {plan.price_stars} ★ — "
            f"это {implied:.2f} ₽ за звезду, похоже на опечатку"
        )


@pytest.mark.parametrize(
    ("plan_id", "currency", "amount"),
    [
        ("basic", "RUB", 19_900),
        ("standard", "RUB", 29_900),
        ("year", "RUB", 199_000),
        ("basic", "XTR", 130),
        ("standard", "XTR", 196),
        ("year", "XTR", 1304),
    ],
)
def test_payment_amount_must_match_plan(plan_id, currency, amount):
    assert payment_matches_plan(BY_ID[plan_id], currency, amount) is True


@pytest.mark.parametrize(
    ("currency", "amount"),
    [("RUB", 1), ("XTR", 1), ("USD", 29900)],
)
def test_wrong_payment_amount_or_currency_is_rejected(currency, amount):
    assert payment_matches_plan(BY_ID["standard"], currency, amount) is False


# --- криптосчета ----------------------------------------------------------


async def test_crypto_invoice_settles_once(db):
    """Опрос идёт по расписанию, и один оплаченный счёт попадёт в выборку
    повторно. Второе списание должно вернуть False, а не выдать ключ снова."""
    await db.get_or_create(1)
    await db.add_crypto_invoice("inv-1", 1, "standard")

    assert await db.settle_crypto_invoice("inv-1") is True
    assert await db.settle_crypto_invoice("inv-1") is False


async def test_pending_excludes_settled(db):
    await db.get_or_create(1)
    await db.add_crypto_invoice("inv-1", 1, "standard")
    await db.add_crypto_invoice("inv-2", 1, "basic")

    assert len(await db.pending_crypto_invoices()) == 2

    await db.settle_crypto_invoice("inv-1")
    pending = await db.pending_crypto_invoices()

    assert [i[0] for i in pending] == ["inv-2"]


async def test_crypto_charge_id_is_idempotent_in_payments(db):
    """Криптоплатёж кладётся в payments с charge_id вида crypto:<id> —
    он должен работать той же защитой, что и telegram_payment_charge_id."""
    await db.get_or_create(1)
    charge = "crypto:inv-1"

    assert await db.charge_seen(charge) is False
    assert await db.add_payment(1, "standard", 299, charge) is True
    assert await db.charge_seen(charge) is True
    # Повторная запись того же charge_id — идемпотентно, а не исключение:
    # add_payment теперь атомарно проверяет уникальность сама.
    assert await db.add_payment(1, "standard", 299, charge) is False


# --- веб-заказы (ЮKassa) ---------------------------------------------------


async def test_web_order_settles_once(db):
    """Ровно та же защита, что у крипты: вебхук может прийти дважды."""
    await db.get_or_create(1)
    await db.create_web_order("order-1", 1, "standard", 299)
    await db.attach_yk_payment("order-1", "yk-1")

    assert await db.settle_web_order("order-1", "yk-1") is True
    assert await db.settle_web_order("order-1", "yk-1") is False


async def test_web_order_requires_matching_payment_id(db):
    """Заказ закрывается только тем платежом ЮKassa, который был выписан
    при его создании. Иначе чужой (или подставной) payment_id мог бы
    закрыть чужой заказ — вебхуку в этом модуле специально не доверяют,
    и эта проверка часть той же защиты."""
    await db.get_or_create(1)
    await db.create_web_order("order-1", 1, "standard", 299)
    await db.attach_yk_payment("order-1", "yk-1")

    assert await db.settle_web_order("order-1", "yk-wrong") is False

    order = await db.get_web_order("order-1")
    assert order["status"] == "pending"


async def test_web_order_can_be_canceled_before_payment(db):
    """Если ЮKassa не приняла запрос на создание платежа, заказ отменяется
    и не должен потом случайно закрыться устаревшим вебхуком."""
    await db.get_or_create(1)
    await db.create_web_order("order-1", 1, "standard", 299)
    await db.cancel_web_order("order-1")

    order = await db.get_web_order("order-1")
    assert order["status"] == "canceled"


async def test_get_web_order_returns_none_for_unknown_id(db):
    assert await db.get_web_order("no-such-order") is None


# --- продление действующей подписки --------------------------------------


async def test_paid_plan_extends_existing_subscription(db):
    """Новая покупка должна прибавить срок в Remnawave, не создать второго
    пользователя и не заменить действующую подписку новым ключом."""
    await db.get_or_create(42)
    await db.save_subscription(
        42,
        state="active",
        panel_uuid="panel-42",
        sub_url="https://sub.example/42",
        expires_at="2030-01-01T00:00:00+00:00",
        devices=2,
    )

    panel = SimpleNamespace(
        extend=AsyncMock(
            return_value=(
                "panel-42",
                "https://sub.example/42",
                "2030-01-31T00:00:00+00:00",
            )
        ),
        create_user=AsyncMock(),
    )
    bot = SimpleNamespace(send_photo=AsyncMock(), send_message=AsyncMock())
    reply = AsyncMock()

    issued = await grant(
        bot=bot,
        db=db,
        config=SimpleNamespace(admin_id=1, support_url="", channel="@khilios_vpn"),
        panel=panel,
        telegram_id=42,
        plan=BY_ID["basic"],
        charge_id="test-renewal-1",
        method="webpay",
        reply=reply,
    )

    assert issued is True
    panel.extend.assert_awaited_once_with("panel-42", days=30, devices=2)
    panel.create_user.assert_not_awaited()

    user = await db.get_or_create(42)
    assert user.panel_uuid == "panel-42"
    assert user.sub_url == "https://sub.example/42"
    assert user.expires_at == "2030-01-31T00:00:00+00:00"

    caption = bot.send_photo.await_args.kwargs["caption"]
    assert "подписка продлена" in caption
