#!/usr/bin/env python3
"""Сборка правил роутинга для клиентов из одного списка доменов.

    python3 build-routing.py          # собрать
    python3 build-routing.py --check  # проверить, что собранное совпадает

Зачем генератор, а не два конфига руками. Клиентов минимум два формата
(Xray и sing-box), список доменов один и тот же, и правится он в спешке —
когда у кого-то не открылся банк. Два файла, которые правят руками,
разъезжаются на второй правке, а обнаруживается это словами «у меня
работает, а у него нет», то есть худшим из возможных способов.

--check стоит в CI: он ловит ровно один случай — поправили список,
забыли пересобрать.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
SOURCE = HERE / "direct-domains.txt"

XRAY_OUT = HERE / "xray-routing.json"
SINGBOX_OUT = HERE / "singbox-routing.json"

# Наборы geosite/geoip, которые клиент подтягивает сам. Дополняют список
# доменов: там перечислено то, что известно нам, здесь — то, что ведут
# сообща и обновляют чаще, чем мы.
#
# VERIFY: имена наборов зависят от того, какой geosite.dat положен в клиент.
# Проверить до раздачи подписки — см. README.md, раздел «Проверка».
GEOSITE_DIRECT = ["geosite:category-ru"]
GEOIP_DIRECT = ["geoip:ru"]

# DNS для российских имён — системный, то есть провайдерский.
#
# Это не мелочь и не про приватность. Российские сайты живут на российских
# CDN, и адрес узла зависит от того, откуда пришёл запрос. Резолвим через
# зарубежный DoH — получаем дальний узел, и «напрямую» превращается в
# «напрямую, но втрое медленнее». Плюс часть банков просто не отвечает
# на адреса, выданные не тому региону.
DNS_LOCAL = "localhost"

# Для всего остального — DoH через туннель. Открытый резолвер провайдера
# на заблокированных именах отвечает подменёнными адресами, и никакой
# протокол этого не исправит: клиент честно пойдёт по неверному адресу.
DNS_REMOTE = "https://1.1.1.1/dns-query"


def load_domains() -> list[str]:
    if not SOURCE.exists():
        sys.exit(f"Нет файла со списком: {SOURCE}")

    domains: list[str] = []
    seen: set[str] = set()

    for lineno, raw in enumerate(SOURCE.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip().lower()
        if not line:
            continue

        # Дешёвые проверки, которые ловят самые частые опечатки. Неверная
        # строка не ломает сборку заметно — она просто перестаёт совпадать,
        # и банк «иногда не работает».
        for bad, why in (
            ("/", "путь"),
            (":", "схема или порт"),
            ("*", "звёздочка"),
            (" ", "пробел"),
        ):
            if bad in line:
                sys.exit(f"{SOURCE}:{lineno}: в имени {line!r} лишний {why}")

        if line.startswith(".") or line.endswith("."):
            sys.exit(f"{SOURCE}:{lineno}: имя {line!r} начинается или кончается точкой")

        if line in seen:
            sys.exit(f"{SOURCE}:{lineno}: {line!r} уже есть в списке")

        seen.add(line)
        domains.append(line)

    if not domains:
        sys.exit(f"{SOURCE}: список пуст")

    return domains


def build_xray(domains: list[str]) -> dict:
    direct_domains = GEOSITE_DIRECT + [f"domain:{d}" for d in domains]

    return {
        "_comment": "Собрано build-routing.py из direct-domains.txt. Руками не править.",
        "dns": {
            "servers": [
                # skipFallback: не переспрашивать российские имена у
                # зарубежного резолвера, если системный не ответил сразу.
                # Без этого «медленный ответ» тихо превращается в дальний CDN.
                {
                    "address": DNS_LOCAL,
                    "domains": direct_domains,
                    "skipFallback": True,
                },
                DNS_REMOTE,
            ],
            "queryStrategy": "UseIP",
        },
        "routing": {
            # IPIfNonMatch: если по имени не совпало, resolve и проверить по IP.
            # Иначе российский сервис, к которому клиент пошёл по голому адресу,
            # уедет в туннель.
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {
                    "type": "field",
                    "outboundTag": "direct",
                    "ip": ["geoip:private"],
                },
                {
                    "type": "field",
                    "outboundTag": "direct",
                    "domain": direct_domains,
                },
                {
                    "type": "field",
                    "outboundTag": "direct",
                    "ip": GEOIP_DIRECT,
                },
                # Всё, что не опознано как российское, идёт в туннель.
                # Правило последнее и намеренно всеядное: «по умолчанию
                # напрямую» означало бы, что новый заблокированный сайт
                # не работает, пока его не внесли руками.
                {
                    "type": "field",
                    "outboundTag": "proxy",
                    "network": "tcp,udp",
                },
            ],
        },
    }


def build_singbox(domains: list[str]) -> dict:
    return {
        "_comment": "Собрано build-routing.py из direct-domains.txt. Руками не править.",
        "route": {
            "rules": [
                {"ip_is_private": True, "outbound": "direct"},
                {"domain_suffix": domains, "outbound": "direct"},
                {"rule_set": ["geosite-ru", "geoip-ru"], "outbound": "direct"},
            ],
            "final": "proxy",
        },
        "dns": {
            "servers": [
                {"tag": "local", "address": "local", "detour": "direct"},
                {"tag": "remote", "address": DNS_REMOTE, "detour": "proxy"},
            ],
            "rules": [
                {"domain_suffix": domains, "server": "local"},
                {"rule_set": ["geosite-ru"], "server": "local"},
            ],
            "final": "remote",
        },
    }


def dump(path: pathlib.Path, data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="не писать файлы, а проверить, что они совпадают с собранным",
    )
    args = parser.parse_args()

    domains = load_domains()
    outputs = {
        XRAY_OUT: dump(XRAY_OUT, build_xray(domains)),
        SINGBOX_OUT: dump(SINGBOX_OUT, build_singbox(domains)),
    }

    if args.check:
        stale = [
            path.name
            for path, content in outputs.items()
            if not path.exists() or path.read_text(encoding="utf-8") != content
        ]
        if stale:
            print(
                "Собранные правила устарели: " + ", ".join(stale),
                file=sys.stderr,
            )
            print("Выполните: python3 infra/panel/routing/build-routing.py", file=sys.stderr)
            return 1
        print(f"Правила актуальны, доменов в списке: {len(domains)}")
        return 0

    for path, content in outputs.items():
        path.write_text(content, encoding="utf-8")
        print(f"{path.name}: {len(domains)} доменов")

    return 0


if __name__ == "__main__":
    sys.exit(main())
