#!/usr/bin/env python3
"""khilios — сколько нод окупается при каком числе платящих.

    python3 infra/economics.py               # таблица
    python3 infra/economics.py --nodes 18    # разбор одного варианта

Смысл в том, чтобы решение «добавить ноду» принималось по цифре, а не по
ощущению. Нода стоит денег каждый месяц, а платящий приходит один раз.
"""

import argparse

PRICE = 299          # тариф «Стандарт», ₽/мес
ACQUIRING = 0.05     # комиссия платёжной системы
TAX = 0.04           # НПД при продаже физлицам
PANEL = 700          # панельная VPS, ₽/мес
NODE = 500           # нода, ₽/мес (средняя по ЕС; Швейцария дороже, см. scaling.md)
USERS_PER_NODE = 40  # техническая ёмкость одной ноды


def net_per_user(price: int = PRICE) -> float:
    """Сколько остаётся с одного платящего после комиссии и налога."""
    return price * (1 - ACQUIRING - TAX)


def monthly_cost(nodes: int) -> int:
    return PANEL + NODE * nodes


def breakeven_users(nodes: int) -> int:
    """Сколько платящих нужно, чтобы инфраструктура вышла в ноль."""
    import math
    return math.ceil(monthly_cost(nodes) / net_per_user())


def profit(nodes: int, users: int) -> float:
    return users * net_per_user() - monthly_cost(nodes)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, help="разобрать один вариант")
    ap.add_argument("--users", type=int, default=30, help="сколько платящих (по умолчанию цель плана)")
    args = ap.parse_args()

    n = net_per_user()
    print(f"Тариф {PRICE} ₽, чистыми с платящего {n:.0f} ₽ "
          f"(минус {ACQUIRING:.0%} платёжке и {TAX:.0%} налога)")
    print(f"Панель {PANEL} ₽/мес, нода {NODE} ₽/мес, ёмкость ноды ~{USERS_PER_NODE} юзеров\n")

    if args.nodes:
        nodes, users = args.nodes, args.users
        print(f"{nodes} нод при {users} платящих:")
        print(f"  расходы:    {monthly_cost(nodes):>6} ₽/мес")
        print(f"  выручка:    {users * n:>6.0f} ₽/мес")
        print(f"  итог:       {profit(nodes, users):>+6.0f} ₽/мес")
        print(f"  окупаются с {breakeven_users(nodes)} платящих")
        print(f"  ёмкость:    {nodes * USERS_PER_NODE} юзеров "
              f"({nodes * USERS_PER_NODE // max(users, 1)}-кратный запас)")
        return

    print(f"{'нод':>4} {'расходы':>9} {'нужно платящих':>15} "
          f"{'при 30 платящих':>17} {'ёмкость':>9}")
    print("-" * 58)
    for nodes in (2, 3, 4, 5, 6, 8, 10, 12, 18):
        p = profit(nodes, 30)
        mark = "" if p >= 0 else "  ← минус"
        print(f"{nodes:>4} {monthly_cost(nodes):>7} ₽ {breakeven_users(nodes):>15} "
              f"{p:>+15.0f} ₽ {nodes * USERS_PER_NODE:>8}{mark}")


if __name__ == "__main__":
    main()
