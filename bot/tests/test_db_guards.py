"""Защита от подстановки чужих имён колонок в UPDATE.

Имена колонок нельзя передать параметром SQL, поэтому они попадают в текст
запроса. Единственное, что отделяет это от инъекции, — белый список, и он
должен быть проверен тестом: иначе его однажды снимут «потому что мешает».
"""

from __future__ import annotations

import pytest

from app.db import Db


@pytest.fixture
async def db(tmp_path):
    store = Db(str(tmp_path / "guards.sqlite3"))
    await store.connect()
    yield store
    await store.close()


async def test_unknown_column_is_rejected(db):
    await db.get_or_create(1)
    with pytest.raises(ValueError, match="Недопустимые поля"):
        await db._update(1, state="active", devices_x="5")


async def test_injection_attempt_in_column_name_is_rejected(db):
    await db.get_or_create(1)
    with pytest.raises(ValueError):
        await db._update(1, **{"state = 'active', trial_issued_at": None})

    # Состояние не изменилось: запрос не выполнялся вообще.
    user = await db.get(1)
    assert user.state == "new"
    assert user.had_trial is False


async def test_allowed_columns_still_work(db):
    await db.get_or_create(1)
    await db._update(1, state="active", devices=5)
    user = await db.get(1)
    assert user.state == "active"
    assert user.devices == 5
