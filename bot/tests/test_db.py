"""Хранилище: антифрод по триалу, идемпотентность платежей, напоминания."""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from app.db import Db


@pytest.fixture
async def db(tmp_path):
    store = Db(str(tmp_path / "test.sqlite3"))
    await store.connect()
    yield store
    await store.close()


async def test_new_user_starts_without_consent(db):
    user = await db.get_or_create(1)
    assert user.state == "new"
    assert user.has_consent is False
    assert user.had_trial is False


async def test_consent_moves_to_ready(db):
    await db.get_or_create(1)
    await db.set_consent(1)
    user = await db.get(1)
    assert user.has_consent is True
    assert user.state == "ready"


async def test_trial_flag_survives_expiry(db):
    """Один триал на один Telegram ID. Факт выдачи остаётся навсегда —
    иначе «дождись истечения и возьми второй» становится инструкцией."""
    await db.get_or_create(1)
    await db.save_subscription(
        1,
        state="trial",
        panel_uuid="u",
        sub_url="https://sub.example/x",
        expires_at="2026-08-01T00:00:00+00:00",
        devices=1,
        mark_trial=True,
    )
    await db.set_state(1, "expired")

    user = await db.get(1)
    assert user.state == "expired"
    assert user.had_trial is True


async def test_repeated_charge_is_detected(db):
    """Telegram умеет доставить successful_payment дважды. Без этой проверки
    повторная доставка продлевает подписку второй раз бесплатно."""
    await db.get_or_create(1)
    assert await db.charge_seen("charge-1") is False
    assert await db.add_payment(1, "standard", 299, "charge-1") is True
    assert await db.charge_seen("charge-1") is True
    assert await db.add_payment(1, "standard", 299, "charge-1") is False


async def test_simultaneous_duplicate_charge_is_claimed_once(db):
    await db.get_or_create(1)
    results = await asyncio.gather(
        db.add_payment(1, "standard", 299, "charge-race"),
        db.add_payment(1, "standard", 299, "charge-race"),
    )
    assert sorted(results) == [False, True]


async def test_reminder_is_sent_once_per_period(db):
    soon = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)
    expires = soon.isoformat(timespec="seconds")

    await db.get_or_create(1)
    await db.save_subscription(
        1,
        state="active",
        panel_uuid="u",
        sub_url="https://sub.example/x",
        expires_at=expires,
        devices=5,
    )

    due = await db.due_for_reminder("d3", 3)
    assert [u.telegram_id for u in due] == [1]

    await db.mark_reminded(1, expires, "d3")
    assert await db.due_for_reminder("d3", 3) == []


async def test_new_period_gets_fresh_reminders(db):
    """Продлился — значит напоминания для нового срока идут заново."""
    first = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)).isoformat(
        timespec="seconds"
    )
    await db.get_or_create(1)
    await db.save_subscription(
        1, state="active", panel_uuid="u", sub_url="s", expires_at=first, devices=5
    )
    await db.mark_reminded(1, first, "d3")

    second = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2, hours=1)).isoformat(
        timespec="seconds"
    )
    await db.save_subscription(
        1, state="active", panel_uuid="u", sub_url="s", expires_at=second, devices=5
    )

    due = await db.due_for_reminder("d3", 3)
    assert [u.telegram_id for u in due] == [1]


async def test_expired_returns_only_past_subscriptions(db):
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat(
        timespec="seconds"
    )
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=5)).isoformat(
        timespec="seconds"
    )

    await db.get_or_create(1)
    await db.save_subscription(
        1, state="trial", panel_uuid="a", sub_url="s", expires_at=past, devices=1
    )
    await db.get_or_create(2)
    await db.save_subscription(
        2, state="active", panel_uuid="b", sub_url="s", expires_at=future, devices=5
    )

    assert [u.telegram_id for u in await db.expired()] == [1]
