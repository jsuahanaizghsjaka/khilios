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
    # Цена в Telegram Stars. Задаётся отдельным числом, а не пересчётом из
    # рублей по коэффициенту: курс Stars задаёт Telegram, он меняется, и
    # захардкоженный коэффициент однажды начнёт продавать год за половину
    # цены — молча, без единой ошибки в логе.
    #
    # Курс задан владельцем от якоря 299 ₽ = 196 ★ (≈ 1,525 ₽ за звезду),
    # остальные тарифы посчитаны по той же пропорции. Это близко к реальному
    # курсу Telegram на август 2026, но курс он меняет — СВЕРИТЬ ПЕРЕД
    # ЗАПУСКОМ: откройте покупку Stars у себя и гляньте, сколько рублей стоит
    # нужное количество. Расхождение с рублёвой ценой больше 10% в любую
    # сторону — это либо потерянная выручка, либо жалоба.
    price_stars: int = 0


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
        price_stars=130,
        days=30,
        devices=2,
        note="Если устройств немного: телефон и ноутбук.",
    ),
    Plan(
        id="standard",
        name="Стандарт",
        price_rub=299,
        price_stars=196,
        days=30,
        devices=5,
        note="Хватает на всю семью. Лимит честный: пять — это пять.",
    ),
    Plan(
        id="year",
        name="Год",
        price_rub=1990,
        price_stars=1304,
        days=365,
        devices=5,
        note="166 ₽ в месяц.",
    ),
]

BY_ID: dict[str, Plan] = {p.id: p for p in [TRIAL, *PAID]}
