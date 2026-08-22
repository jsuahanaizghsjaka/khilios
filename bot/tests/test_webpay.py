"""Веб-сервер оплаты: вебхук ЮKassa не должен верить своему телу.

Это единственное место в проекте, где подтверждение платежа приходит
снаружи по HTTP, а не запрашивается нами самими (Telegram Payments и
крипта устроены иначе). Поэтому здесь особенно важно проверить именно
негативный случай: поддельный вебхук с status=succeeded в теле не должен
закрывать заказ, если реальный API говорит другое.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app import keyboards as kb, webpay
from app.db import Db
from app.yookassa import YooKassaError


@pytest.fixture
async def db(tmp_path):
    store = Db(str(tmp_path / "webpay.sqlite3"))
    await store.connect()
    yield store
    await store.close()


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))

    async def send_photo(self, chat_id, photo, *, caption, **kw):
        self.sent.append((chat_id, caption))


def _config():
    from app.config import Config

    return Config(
        bot_token="x",
        admin_id=999,
        panel_api_url="http://127.0.0.1:3000",
        panel_api_token="x",
        panel_internal_squads=("11111111-1111-1111-1111-111111111111",),
        channel="@ch",
        payment_token="",
        yookassa_shop_id="shop",
        yookassa_secret_key="secret",
        web_pay_host="sub.example.net",
        web_pay_port=8081,
        stars_enabled=False,
        crypto_token="",
        crypto_testnet=False,
        support_url="",
        offer_url="",
        privacy_url="",
        trial_max_telegram_id=None,
        db_path=":memory:",
    )


async def _make_client(aiohttp_client, db, *, yk, panel, bot):
    app = webpay.build_app(db=db, panel=panel, bot=bot, config=_config(), yookassa=yk)
    return await aiohttp_client(app)


async def test_happ_bridge_opens_subscription_in_app(aiohttp_client, db):
    panel = AsyncMock()
    bot = FakeBot()
    client = await _make_client(aiohttp_client, db, yk=None, panel=panel, bot=bot)
    sub_url = "https://sub.example.net/api/subscription/token?client=telegram"
    bridge_url = kb.happ_connect_url(sub_url, "sub.example.net")

    resp = await client.get(bridge_url.removeprefix("https://sub.example.net"))
    page = await resp.text()

    assert resp.status == 200
    assert "happ://add/https://sub.example.net/api/subscription/token" in page
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["Referrer-Policy"] == "no-referrer"


async def test_happ_bridge_rejects_foreign_subscription_host(aiohttp_client, db):
    panel = AsyncMock()
    bot = FakeBot()
    client = await _make_client(aiohttp_client, db, yk=None, panel=panel, bot=bot)
    bridge_url = kb.happ_connect_url(
        "https://attacker.example/subscription/token",
        "sub.example.net",
    )

    resp = await client.get(bridge_url.removeprefix("https://sub.example.net"))

    assert resp.status == 400


async def test_happ_bridge_rejects_invalid_token(aiohttp_client, db):
    panel = AsyncMock()
    bot = FakeBot()
    client = await _make_client(aiohttp_client, db, yk=None, panel=panel, bot=bot)

    resp = await client.get("/pay/happ?subscription=not-a-valid-link")

    assert resp.status == 400


async def test_webhook_ignores_forged_body_status(aiohttp_client, db):
    """Тело вебхука утверждает succeeded. Реальный статус в API — pending.
    Заказ не должен закрыться: это и есть смысл переспроса, см. yookassa.py."""
    await db.get_or_create(1)
    await db.create_web_order("order-1", 1, "standard", 299)
    await db.attach_yk_payment("order-1", "yk-1")

    yk = AsyncMock()
    yk.get_payment.return_value = ("pending", 299)  # реальный статус
    panel = AsyncMock()
    bot = FakeBot()

    client = await _make_client(aiohttp_client, db, yk=yk, panel=panel, bot=bot)
    resp = await client.post(
        "/pay/webhook/yookassa",
        json={"event": "payment.succeeded", "object": {"id": "yk-1", "status": "succeeded"}},
    )

    assert resp.status == 200
    yk.get_payment.assert_awaited_once_with("yk-1")

    order = await db.get_web_order("order-1")
    assert order["status"] == "pending"
    assert bot.sent == []


async def test_webhook_settles_order_when_api_confirms(aiohttp_client, db, monkeypatch):
    await db.get_or_create(1)
    await db.create_web_order("order-1", 1, "standard", 299)
    await db.attach_yk_payment("order-1", "yk-1")

    yk = AsyncMock()
    yk.get_payment.return_value = ("succeeded", 299)

    panel = AsyncMock()
    panel.create_user.return_value = ("uuid-1", "https://sub.example/x", "2030-01-01T00:00:00+00:00")
    bot = FakeBot()

    client = await _make_client(aiohttp_client, db, yk=yk, panel=panel, bot=bot)
    resp = await client.post(
        "/pay/webhook/yookassa",
        json={"event": "payment.succeeded", "object": {"id": "yk-1", "status": "succeeded"}},
    )

    assert resp.status == 200
    order = await db.get_web_order("order-1")
    assert order["status"] == "succeeded"
    # grant() шлёт два сообщения: покупателю ключ, админу — пинг о продаже.
    assert len(bot.sent) == 2
    assert bot.sent[0][0] == 1  # ключ ушёл тому пользователю, что в заказе


async def test_webhook_is_idempotent_on_repeated_delivery(aiohttp_client, db):
    """ЮKassa может доставить уведомление повторно. Второй раз не должен
    выдавать ключ снова."""
    await db.get_or_create(1)
    await db.create_web_order("order-1", 1, "standard", 299)
    await db.attach_yk_payment("order-1", "yk-1")

    yk = AsyncMock()
    yk.get_payment.return_value = ("succeeded", 299)
    panel = AsyncMock()
    panel.create_user.return_value = ("uuid-1", "https://sub.example/x", "2030-01-01T00:00:00+00:00")
    bot = FakeBot()

    client = await _make_client(aiohttp_client, db, yk=yk, panel=panel, bot=bot)
    body = {"event": "payment.succeeded", "object": {"id": "yk-1", "status": "succeeded"}}

    await client.post("/pay/webhook/yookassa", json=body)
    await client.post("/pay/webhook/yookassa", json=body)

    assert panel.create_user.await_count == 1
    # Ровно те же два сообщения, что и при однократной доставке — второй
    # вызов вебхука не должен добавить к ним ещё.
    assert len(bot.sent) == 2


async def test_webhook_rejects_amount_mismatch(aiohttp_client, db):
    """API подтверждает платёж на другую сумму, чем выставлял заказ (частичный
    возврат, ручная правка в кабинете). Ключ на полную сумму тарифа выдавать
    нельзя — тот же принцип, что payment_matches_plan для Telegram-платежей."""
    await db.get_or_create(1)
    await db.create_web_order("order-1", 1, "standard", 299)
    await db.attach_yk_payment("order-1", "yk-1")

    yk = AsyncMock()
    yk.get_payment.return_value = ("succeeded", 100)  # меньше заказанных 299
    panel = AsyncMock()
    bot = FakeBot()

    client = await _make_client(aiohttp_client, db, yk=yk, panel=panel, bot=bot)
    resp = await client.post(
        "/pay/webhook/yookassa",
        json={"event": "payment.succeeded", "object": {"id": "yk-1", "status": "succeeded"}},
    )

    assert resp.status == 200
    panel.create_user.assert_not_awaited()

    order = await db.get_web_order("order-1")
    assert order["status"] == "pending"
    assert any(chat_id == 999 for chat_id, _ in bot.sent)  # админу ушёл пинг


async def test_webhook_recovers_if_settle_never_ran(aiohttp_client, db):
    """grant() отработал (ключ выдан), но settle_web_order по каким-то
    причинам не выполнился — заказ остался pending. Повторная доставка
    вебхука должна закрыть заказ, а не выдать ключ ещё раз: защищает
    идемпотентность add_payment внутри grant(), а не порядок вызовов здесь."""
    await db.get_or_create(1)
    await db.create_web_order("order-1", 1, "standard", 299)
    await db.attach_yk_payment("order-1", "yk-1")
    # Имитируем «зависший» заказ: платёж уже записан в payments напрямую,
    # как это сделал бы первый (оборвавшийся) проход grant().
    await db.add_payment(1, "standard", 299, "yookassa:yk-1")

    yk = AsyncMock()
    yk.get_payment.return_value = ("succeeded", 299)
    panel = AsyncMock()
    panel.create_user.return_value = ("uuid-1", "https://sub.example/x", "2030-01-01T00:00:00+00:00")
    bot = FakeBot()

    client = await _make_client(aiohttp_client, db, yk=yk, panel=panel, bot=bot)
    resp = await client.post(
        "/pay/webhook/yookassa",
        json={"event": "payment.succeeded", "object": {"id": "yk-1", "status": "succeeded"}},
    )

    assert resp.status == 200
    # Ключ не выдаётся второй раз (panel.create_user не вызывается) —
    panel.create_user.assert_not_awaited()
    # но заказ теперь всё-таки закрыт, а не завис в pending навсегда.
    order = await db.get_web_order("order-1")
    assert order["status"] == "succeeded"


async def test_webhook_unknown_payment_id_alerts_admin_not_crashes(aiohttp_client, db):
    """Платёж подтверждён API, но в базе нет заказа с таким yk_payment_id —
    рассинхрон, а не повод падать. Админ получает пинг, сервис не падает."""
    yk = AsyncMock()
    yk.get_payment.return_value = ("succeeded", 299)
    panel = AsyncMock()
    bot = FakeBot()

    client = await _make_client(aiohttp_client, db, yk=yk, panel=panel, bot=bot)
    resp = await client.post(
        "/pay/webhook/yookassa",
        json={"event": "payment.succeeded", "object": {"id": "yk-unknown", "status": "succeeded"}},
    )

    assert resp.status == 200
    assert any(chat_id == 999 for chat_id, _ in bot.sent)  # админу ушёл пинг


async def test_webhook_malformed_body_returns_400(aiohttp_client, db):
    yk = AsyncMock()
    panel = AsyncMock()
    bot = FakeBot()

    client = await _make_client(aiohttp_client, db, yk=yk, panel=panel, bot=bot)
    resp = await client.post(
        "/pay/webhook/yookassa", data=b"not json", headers={"Content-Type": "application/json"}
    )

    assert resp.status == 400
    yk.get_payment.assert_not_awaited()


async def test_return_page_says_paid_when_order_settled(aiohttp_client, db):
    await db.get_or_create(1)
    await db.create_web_order("order-1", 1, "standard", 299)
    await db.attach_yk_payment("order-1", "yk-1")
    await db.settle_web_order("order-1", "yk-1")

    yk = AsyncMock()
    panel = AsyncMock()
    bot = FakeBot()

    client = await _make_client(aiohttp_client, db, yk=yk, panel=panel, bot=bot)
    resp = await client.get("/pay/order-1/return")
    text = await resp.text()

    assert resp.status == 200
    assert "Оплачено" in text


async def test_return_page_handles_unknown_order(aiohttp_client, db):
    yk = AsyncMock()
    panel = AsyncMock()
    bot = FakeBot()

    client = await _make_client(aiohttp_client, db, yk=yk, panel=panel, bot=bot)
    resp = await client.get("/pay/no-such-order/return")

    assert resp.status == 200
    assert "не найден" in (await resp.text())
