"""Тарифы.

Цифры обязаны совпадать с web/lib/config.ts до рубля. Разные цены на сайте
и в боте — первая причина спора с клиентом и первый повод не доверять.

Если правите здесь — правьте и там, одним коммитом.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    price_rub: int
    days: int
    devices: int
    note: str


TRIAL = Plan(
    id="trial",
    name="Пробный",
    price_rub=0,
    days=7,
    devices=1,
    note="Без карты и без автосписания.",
)

PAID: list[Plan] = [
    Plan(
        id="basic",
        name="Базовый",
        price_rub=199,
        days=30,
        devices=2,
        note="Если устройств немного: телефон и ноутбук.",
    ),
    Plan(
        id="standard",
        name="Стандарт",
        price_rub=299,
        days=30,
        devices=5,
        note="Хватает на всю семью. Лимит честный: пять — это пять.",
    ),
    Plan(
        id="year",
        name="Год",
        price_rub=1990,
        days=365,
        devices=5,
        note="166 ₽ в месяц.",
    ),
]

BY_ID: dict[str, Plan] = {p.id: p for p in [TRIAL, *PAID]}
