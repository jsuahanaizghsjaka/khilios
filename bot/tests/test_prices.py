"""Цены в боте обязаны совпадать с сайтом до рубля.

Тест читает web/lib/config.ts и сверяет с app/plans.py. Проверять это глазами
бесполезно: расхождение появляется через месяц, когда цену правят в одном
месте, а вспоминают про второе после первого спора с клиентом.
"""

from __future__ import annotations

import pathlib
import re

from app.plans import BY_ID

SITE_CONFIG = pathlib.Path(__file__).resolve().parents[2] / "web" / "lib" / "config.ts"

# id, price, devices из объектов PLANS. Порядок полей в файле фиксированный,
# но между ними могут стоять другие ключи — поэтому три отдельных поиска
# внутри блока одного тарифа, а не одна большая регулярка.
_BLOCK = re.compile(r"\{\s*(?:.|\n)*?\}", re.MULTILINE)


def _site_plans() -> dict[str, dict[str, int]]:
    source = SITE_CONFIG.read_text(encoding="utf-8")
    start = source.index("export const PLANS")
    body = source[start:]

    plans: dict[str, dict[str, int]] = {}
    for block in _BLOCK.findall(body):
        pid = re.search(r'id:\s*"([^"]+)"', block)
        price = re.search(r"price:\s*(\d+)", block)
        devices = re.search(r"devices:\s*(\d+)", block)
        if pid and price and devices:
            plans[pid.group(1)] = {
                "price": int(price.group(1)),
                "devices": int(devices.group(1)),
            }
    return plans


def test_site_config_is_readable():
    """Если сайт переехал или файл переименован — тест должен сказать это прямо,
    а не молча начать сверять пустой словарь и всегда проходить."""
    assert SITE_CONFIG.exists(), f"Нет {SITE_CONFIG}"
    assert _site_plans(), "Из web/lib/config.ts не разобрался ни один тариф"


def test_prices_match_site():
    for pid, site in _site_plans().items():
        assert pid in BY_ID, f"Тариф {pid} есть на сайте, но не в боте"
        bot_plan = BY_ID[pid]
        assert bot_plan.price_rub == site["price"], (
            f"{pid}: на сайте {site['price']} ₽, в боте {bot_plan.price_rub} ₽"
        )
        assert bot_plan.devices == site["devices"], (
            f"{pid}: на сайте {site['devices']} устройств, "
            f"в боте {bot_plan.devices}"
        )


def test_bot_has_no_extra_plans():
    """Тариф, которого нет на сайте, — это цена, которую клиент не видел."""
    site = _site_plans()
    extra = set(BY_ID) - set(site)
    assert not extra, f"В боте есть тарифы, которых нет на сайте: {extra}"
