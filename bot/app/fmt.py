"""Форматирование дат для показа пользователю.

Всё, что видит человек, — в московском времени: сервисом пользуются из России,
и «до 14 августа 03:00 UTC» читается как ошибка, а не как точность.
"""

from __future__ import annotations

import datetime as dt

MSK = dt.timezone(dt.timedelta(hours=3))

_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        parsed = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "—"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    local = parsed.astimezone(MSK)
    return f"{local.day} {_MONTHS[local.month - 1]} {local.year}"
