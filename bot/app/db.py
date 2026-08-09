"""Хранилище. SQLite, один файл.

Почему не Postgres: пятнадцать-тридцать пользователей в одном файле, который
бэкап забирает целиком вместе с каталогом бота. Отдельный контейнер с базой
здесь не даёт ничего, кроме ещё одного места, где всё может сломаться.

Хранится ровно то, что перечислено в docs/bot-flow.md: Telegram ID, состояние,
даты, факты оплат, факт выдачи триала. Больше не собираем — каждое лишнее поле
это и ответственность при утечке, и лишний ответ при запросе госоргана.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id     INTEGER PRIMARY KEY,
    state           TEXT NOT NULL DEFAULT 'new',
    consent_at      TEXT,
    trial_issued_at TEXT,
    panel_uuid      TEXT,
    sub_url         TEXT,
    expires_at      TEXT,
    devices         INTEGER,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id  INTEGER NOT NULL,
    plan_id      TEXT NOT NULL,
    amount_rub   INTEGER NOT NULL,
    charge_id    TEXT,
    created_at   TEXT NOT NULL
);

-- Напоминания об истечении. Ключ включает expires_at, поэтому новый оплаченный
-- период получает свой комплект напоминаний, а старые записи ему не мешают.
CREATE TABLE IF NOT EXISTS reminders (
    telegram_id INTEGER NOT NULL,
    expires_at  TEXT NOT NULL,
    kind        TEXT NOT NULL,
    sent_at     TEXT NOT NULL,
    PRIMARY KEY (telegram_id, expires_at, kind)
);
"""


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


@dataclass
class User:
    telegram_id: int
    state: str
    consent_at: str | None
    trial_issued_at: str | None
    panel_uuid: str | None
    sub_url: str | None
    expires_at: str | None
    devices: int | None

    @property
    def has_consent(self) -> bool:
        return bool(self.consent_at)

    @property
    def had_trial(self) -> bool:
        # Факт выдачи остаётся навсегда, в том числе после удаления подписки.
        # Иначе «удалить и получить второй триал» становится инструкцией.
        return bool(self.trial_issued_at)

    @property
    def expires_dt(self) -> dt.datetime | None:
        if not self.expires_at:
            return None
        try:
            return dt.datetime.fromisoformat(self.expires_at)
        except ValueError:
            return None

    @property
    def days_left(self) -> int | None:
        exp = self.expires_dt
        if exp is None:
            return None
        delta = exp - dt.datetime.now(dt.timezone.utc)
        return max(0, delta.days)


class Db:
    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        # WAL — чтобы фоновая рассылка напоминаний не блокировала хендлеры.
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Db.connect() не вызван")
        return self._conn

    # ------------------------------------------------------------------
    # Пользователи
    # ------------------------------------------------------------------

    async def get_or_create(self, telegram_id: int) -> User:
        await self.conn.execute(
            "INSERT OR IGNORE INTO users (telegram_id, state, created_at, updated_at) "
            "VALUES (?, 'new', ?, ?)",
            (telegram_id, now(), now()),
        )
        await self.conn.commit()
        user = await self.get(telegram_id)
        assert user is not None
        return user

    async def get(self, telegram_id: int) -> User | None:
        async with self.conn.execute(
            "SELECT telegram_id, state, consent_at, trial_issued_at, panel_uuid, "
            "sub_url, expires_at, devices FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ) as cur:
            row = await cur.fetchone()
        return User(**dict(row)) if row else None

    async def _update(self, telegram_id: int, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = now()
        assignments = ", ".join(f"{k} = ?" for k in fields)
        await self.conn.execute(
            f"UPDATE users SET {assignments} WHERE telegram_id = ?",
            (*fields.values(), telegram_id),
        )
        await self.conn.commit()

    async def set_consent(self, telegram_id: int) -> None:
        await self._update(telegram_id, consent_at=now(), state="ready")

    async def set_state(self, telegram_id: int, state: str) -> None:
        await self._update(telegram_id, state=state)

    async def save_subscription(
        self,
        telegram_id: int,
        *,
        state: str,
        panel_uuid: str,
        sub_url: str,
        expires_at: str,
        devices: int,
        mark_trial: bool = False,
    ) -> None:
        fields = {
            "state": state,
            "panel_uuid": panel_uuid,
            "sub_url": sub_url,
            "expires_at": expires_at,
            "devices": devices,
        }
        if mark_trial:
            fields["trial_issued_at"] = now()
        await self._update(telegram_id, **fields)

    # ------------------------------------------------------------------
    # Оплаты
    # ------------------------------------------------------------------

    async def add_payment(
        self, telegram_id: int, plan_id: str, amount_rub: int, charge_id: str | None
    ) -> None:
        await self.conn.execute(
            "INSERT INTO payments (telegram_id, plan_id, amount_rub, charge_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (telegram_id, plan_id, amount_rub, charge_id, now()),
        )
        await self.conn.commit()

    async def charge_seen(self, charge_id: str) -> bool:
        """Платёж с таким charge_id уже записан.

        Telegram может доставить successful_payment повторно. Без этой проверки
        повторная доставка продлевает подписку второй раз бесплатно.
        """
        async with self.conn.execute(
            "SELECT 1 FROM payments WHERE charge_id = ? LIMIT 1", (charge_id,)
        ) as cur:
            return await cur.fetchone() is not None

    # ------------------------------------------------------------------
    # Напоминания
    # ------------------------------------------------------------------

    async def due_for_reminder(self, kind: str, days_ahead: int) -> list[User]:
        """Кому пора слать напоминание вида kind.

        Автопродления нет (обещано на сайте), поэтому напоминание — единственное,
        что стоит между пользователем и молча закончившейся подпиской.
        """
        target = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days_ahead)
        async with self.conn.execute(
            "SELECT u.telegram_id, u.state, u.consent_at, u.trial_issued_at, "
            "       u.panel_uuid, u.sub_url, u.expires_at, u.devices "
            "FROM users u "
            "LEFT JOIN reminders r "
            "  ON r.telegram_id = u.telegram_id "
            " AND r.expires_at = u.expires_at "
            " AND r.kind = ? "
            "WHERE u.state IN ('trial', 'active') "
            "  AND u.expires_at IS NOT NULL "
            "  AND u.expires_at <= ? "
            "  AND r.telegram_id IS NULL",
            (kind, target.isoformat(timespec="seconds")),
        ) as cur:
            rows = await cur.fetchall()
        return [User(**dict(r)) for r in rows]

    async def mark_reminded(self, telegram_id: int, expires_at: str, kind: str) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO reminders (telegram_id, expires_at, kind, sent_at) "
            "VALUES (?, ?, ?, ?)",
            (telegram_id, expires_at, kind, now()),
        )
        await self.conn.commit()

    async def expired(self) -> list[User]:
        async with self.conn.execute(
            "SELECT telegram_id, state, consent_at, trial_issued_at, panel_uuid, "
            "sub_url, expires_at, devices FROM users "
            "WHERE state IN ('trial', 'active') AND expires_at IS NOT NULL "
            "AND expires_at <= ?",
            (now(),),
        ) as cur:
            rows = await cur.fetchall()
        return [User(**dict(r)) for r in rows]

    # ------------------------------------------------------------------
    # Админская сводка
    # ------------------------------------------------------------------

    async def stats(self) -> dict[str, int]:
        async with self.conn.execute(
            "SELECT state, COUNT(*) AS n FROM users GROUP BY state"
        ) as cur:
            by_state = {r["state"]: r["n"] for r in await cur.fetchall()}
        async with self.conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount_rub), 0) AS total FROM payments"
        ) as cur:
            row = await cur.fetchone()
        by_state["payments"] = row["n"]
        by_state["revenue_rub"] = row["total"]
        return by_state
