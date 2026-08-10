"""Оплата: выбор способа, разбор callback_data, защита от двойной выдачи.

Каждая проверка здесь закрывает случай, который стоит денег: показанный
способ, который не подключён; кнопка, не разбирающаяся обратно в тариф;
криптосчёт, выданный дважды.
"""

from __future__ import annotations

import pytest

from app import keyboards as kb
from app.db import Db
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
        "standard", card=True, stars=False, crypto=False, stars_price=165
    )
    labels = " ".join(_buttons(markup))
    assert "МИР" in labels
    assert "Stars" not in labels
    assert "Крипто" not in labels


def test_all_methods_can_be_shown_together():
    markup = kb.pay_methods(
        "standard", card=True, stars=True, crypto=True, stars_price=165
    )
    assert len([c for c in _callbacks(markup) if c.startswith(kb.CB_PAY)]) == 3


def test_stars_button_shows_price():
    markup = kb.pay_methods(
        "year", card=False, stars=True, crypto=False, stars_price=1100
    )
    assert any("1100" in b for b in _buttons(markup))


@pytest.mark.parametrize("plan_id", ["basic", "standard", "year"])
@pytest.mark.parametrize("method", ["card", "stars", "crypto"])
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
    await db.add_payment(1, "standard", 299, charge)
    assert await db.charge_seen(charge) is True
