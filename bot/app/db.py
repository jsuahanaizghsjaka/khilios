"""Хранилище. SQLite, один файл.

Почему не Postgres: пятнадцать-тридцать пользователей в одном файле, который
бэкап забирает целиком вместе с каталогом бота. Отдельный контейнер с базой
здесь не даёт ничего, кроме ещё одного места, где всё может сломаться.

Хранится ровно то, что перечислено в docs/bot-flow.md: Telegram ID, состояние,
даты, факты оплат, факт выдачи триала. Больше не собираем — каждое лишнее поле
это и ответственность при утечке, и лишний ответ при запросе госоргана.
"""

from __future__ import annotations

import asyncio
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

-- Атомарный реестр обработанных charge_id. Отдельная таблица позволяет
-- безопасно обновить существующую базу, где payments ещё не имела UNIQUE.
CREATE TABLE IF NOT EXISTS processed_charges (
    charge_id   TEXT PRIMARY KEY,
    recorded_at TEXT NOT NULL
);

-- Триггер и INSERT в payments выполняются одной SQLite-транзакцией. Поэтому
-- две одновременные доставки одного события не успеют обе выдать подписку.
CREATE TRIGGER IF NOT EXISTS claim_payment_charge
BEFORE INSERT ON payments
WHEN NEW.charge_id IS NOT NULL
BEGIN
    INSERT INTO processed_charges (charge_id, recorded_at)
    VALUES (NEW.charge_id, NEW.created_at);
END;

-- Счета на оплату криптовалютой. Живут отдельно от payments, потому что это
-- разные факты: здесь счёт выставлен, там деньги получены. Запись переезжает
-- в payments только после подтверждения от API — см. crypto.py.
CREATE TABLE IF NOT EXISTS crypto_invoices (
    invoice_id  TEXT PRIMARY KEY,
    telegram_id INTEGER NOT NULL,
    plan_id     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    settled_at  TEXT
);

-- Заказы на оплату через веб-чекаут ЮKassa. Живут отдельно от payments по
-- той же причине, что и crypto_invoices: здесь заказ создан, там деньги
-- получены. status идёт из терминологии ЮKassa (pending/succeeded/canceled),
-- а не своя — чтобы при разборе не переводить туда-обратно.
CREATE TABLE IF NOT EXISTS web_orders (
    order_id      TEXT PRIMARY KEY,
    telegram_id   INTEGER NOT NULL,
    plan_id       TEXT NOT NULL,
    amount_rub    INTEGER NOT NULL,
    yk_payment_id TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TEXT NOT NULL,
    settled_at    TEXT
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
        self._payment_lock = asyncio.Lock()

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        # WAL — чтобы фоновая рассылка напоминаний не блокировала хендлеры.
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.executescript(SCHEMA)
        # Миграция без потери платёжной истории.
        await self._conn.execute(
            "INSERT OR IGNORE INTO processed_charges (charge_id, recorded_at) "
            "SELECT charge_id, MIN(created_at) FROM payments "
            "WHERE charge_id IS NOT NULL GROUP BY charge_id"
        )
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
        if user is None:
            # Недостижимо после успешного INSERT OR IGNORE, но не assert:
            # под `python -O` он вырезается, и вместо внятной ошибки здесь
            # хендлер уронит AttributeError на None где-то через два вызова.
            raise RuntimeError(f"Пользователь {telegram_id} не создался")
        return user

    async def get(self, telegram_id: int) -> User | None:
        async with self.conn.execute(
            "SELECT telegram_id, state, consent_at, trial_issued_at, panel_uuid, "
            "sub_url, expires_at, devices FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ) as cur:
            row = await cur.fetchone()
        return User(**dict(row)) if row else None

    # Имена колонок нельзя передать параметром, поэтому они подставляются
    # в текст запроса — и единственное, что отделяет это от SQL-инъекции,
    # белый список. Сегодня во все вызовы `_update` имена приходят литералами
    # из кода, но стоит один раз написать `_update(tid, **данные_из_апдейта)` —
    # и без списка это станет дырой, которую никто не заметит на ревью.
    _UPDATABLE = frozenset(
        {
            "state",
            "consent_at",
            "trial_issued_at",
            "panel_uuid",
            "sub_url",
            "expires_at",
            "devices",
            "updated_at",
        }
    )

    async def _update(self, telegram_id: int, **fields) -> None:
        if not fields:
            return

        unknown = set(fields) - self._UPDATABLE
        if unknown:
            raise ValueError(f"Недопустимые поля для UPDATE: {sorted(unknown)}")

        fields["updated_at"] = now()
        assignments = ", ".join(f"{k} = ?" for k in fields)
        await self.conn.execute(
            # Подавление разобрано, а не поставлено «чтобы не мешало»: имена
            # колонок прошли белый список выше, значения идут параметрами.
            # Снять его нельзя — замечание вернётся, а список останется
            # единственной настоящей защитой.
            f"UPDATE users SET {assignments} WHERE telegram_id = ?",  # nosec B608  # noqa: S608
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
    ) -> bool:
        """Атомарно записать платёж. False — charge_id уже обработан."""
        # Одна aiosqlite.Connection разделяется всеми хендлерами. Lock не
        # даёт rollback второго дубля отменить ещё не закоммиченный первый.
        async with self._payment_lock:
            try:
                await self.conn.execute(
                    "INSERT INTO payments "
                    "(telegram_id, plan_id, amount_rub, charge_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (telegram_id, plan_id, amount_rub, charge_id, now()),
                )
                await self.conn.commit()
                return True
            except aiosqlite.IntegrityError:
                await self.conn.rollback()
                if charge_id is not None and await self.charge_seen(charge_id):
                    return False
                raise

    async def charge_seen(self, charge_id: str) -> bool:
        """Платёж с таким charge_id уже записан.

        Telegram может доставить successful_payment повторно. Без этой проверки
        повторная доставка продлевает подписку второй раз бесплатно.
        """
        async with self.conn.execute(
            "SELECT 1 FROM processed_charges WHERE charge_id = ? LIMIT 1", (charge_id,)
        ) as cur:
            return await cur.fetchone() is not None

    # ------------------------------------------------------------------
    # Счета на криптооплату
    # ------------------------------------------------------------------

    async def add_crypto_invoice(
        self, invoice_id: str, telegram_id: int, plan_id: str
    ) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO crypto_invoices "
            "(invoice_id, telegram_id, plan_id, created_at) VALUES (?, ?, ?, ?)",
            (invoice_id, telegram_id, plan_id, now()),
        )
        await self.conn.commit()

    async def pending_crypto_invoices(self) -> list[tuple[str, int, str]]:
        """Счета, по которым ещё не подтверждена оплата.

        Отдаём все неоплаченные, а не только свежие: счёт с истёкшим сроком
        API просто не вернёт как оплаченный, а вот преждевременно забыть
        про счёт, по которому деньги пришли, — это потерянный платёж.
        """
        async with self.conn.execute(
            "SELECT invoice_id, telegram_id, plan_id FROM crypto_invoices "
            "WHERE settled_at IS NULL ORDER BY created_at"
        ) as cur:
            return [
                (r["invoice_id"], r["telegram_id"], r["plan_id"])
                for r in await cur.fetchall()
            ]

    async def settle_crypto_invoice(self, invoice_id: str) -> bool:
        """Отметить счёт оплаченным. False — если уже был отмечен.

        Возврат False и есть защита от повторной выдачи: опрос идёт по
        расписанию, и один и тот же оплаченный счёт попадёт в выборку
        дважды, если между тиками что-то пошло не так.
        """
        cur = await self.conn.execute(
            "UPDATE crypto_invoices SET settled_at = ? "
            "WHERE invoice_id = ? AND settled_at IS NULL",
            (now(), invoice_id),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Заказы веб-чекаута (ЮKassa)
    # ------------------------------------------------------------------

    async def create_web_order(
        self, order_id: str, telegram_id: int, plan_id: str, amount_rub: int
    ) -> None:
        await self.conn.execute(
            "INSERT INTO web_orders "
            "(order_id, telegram_id, plan_id, amount_rub, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (order_id, telegram_id, plan_id, amount_rub, now()),
        )
        await self.conn.commit()

    async def get_web_order(self, order_id: str) -> dict | None:
        async with self.conn.execute(
            "SELECT order_id, telegram_id, plan_id, amount_rub, yk_payment_id, "
            "status FROM web_orders WHERE order_id = ?",
            (order_id,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def attach_yk_payment(self, order_id: str, yk_payment_id: str) -> None:
        """Записать ID платежа ЮKassa, полученный при создании заказа.

        Нужен, чтобы сверять входящий вебхук с ожидаемым платежом, а не
        доверять только order_id из URL — id платежа ЮKassa непредсказуем
        и не подделывается тем, кто просто знает наш собственный order_id.
        """
        await self.conn.execute(
            "UPDATE web_orders SET yk_payment_id = ? WHERE order_id = ?",
            (yk_payment_id, order_id),
        )
        await self.conn.commit()

    async def settle_web_order(self, order_id: str, yk_payment_id: str) -> bool:
        """Отметить заказ оплаченным. False — если уже был отмечен или
        yk_payment_id не совпадает с записанным при создании заказа.

        Второе условие — не формальность: без сверки чужой вебхук с
        подставным order_id из другого заказа мог бы закрыть этот как
        оплаченный, не имея отношения к реальному платежу.
        """
        cur = await self.conn.execute(
            "UPDATE web_orders SET status = 'succeeded', settled_at = ? "
            "WHERE order_id = ? AND yk_payment_id = ? AND status = 'pending'",
            (now(), order_id, yk_payment_id),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def cancel_web_order(self, order_id: str) -> None:
        await self.conn.execute(
            "UPDATE web_orders SET status = 'canceled' "
            "WHERE order_id = ? AND status = 'pending'",
            (order_id,),
        )
        await self.conn.commit()

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
