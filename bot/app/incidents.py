"""Обнаружение аварий на узлах и рассылка пострадавшим.

Закрывает две самые частые жалобы на рынке VPN, которые ни один конкурент
не закрывает: «опять вручную перебирать серверы» и «не понимаю, это у меня
или у всех». Ответ на обе один — сервис пишет первым, до того как человек
начнёт разбираться сам.

ОТКУДА БЕРЁТСЯ СОСТОЯНИЕ. Из того же status.json, что читает сайт, —
его генерирует infra/panel/status-json.sh раз в 5 минут. Своей проверки
узлов здесь нет намеренно: две независимые проверки разошлись бы в
показаниях, и тогда страница статуса и бот говорили бы людям разное про
один и тот же узел. Один источник — одна правда.

ЧЕГО ЭТА ПРОВЕРКА НЕ ВИДИТ. Ровно того же, чего не видит страница статуса:
блокировку у российского оператора. Панель стоит за границей, и для неё
заблокированная нода выглядит живой. Такие случаи приходят от людей и
выставляются вручную через файл override — бот подхватит их так же, как
автоматические, потому что читает итоговый файл, а не сырые проверки.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import pathlib
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Живым считается файл не старше этого. Если status-json.sh перестал
# запускаться (умер cron, кончилось место), файл замирает в последнем
# состоянии — и рассылать по нему тревоги нельзя: получится «узел лежит»
# про давно поднятый узел. Молчание здесь честнее уверенного вранья,
# ровно как на странице статуса (см. web/lib/status.ts).
STALE_AFTER = dt.timedelta(minutes=15)

# Состояния, при которых узел считается пригодным к работе.
HEALTHY = {"up"}


@dataclass(frozen=True)
class NodeState:
    name: str
    region: str
    state: str


@dataclass(frozen=True)
class Incident:
    """Смена состояния узла, о которой стоит сказать людям."""

    node: str
    region: str
    was: str
    now: str

    @property
    def recovered(self) -> bool:
        return self.now in HEALTHY


def read_status(path: str) -> tuple[list[NodeState], bool]:
    """Прочитать status.json. Возвращает (узлы, свежий ли файл).

    Ошибку чтения не поднимаем: файла может не быть до первого запуска
    cron, и это не повод ронять фоновой цикл бота.
    """
    file = pathlib.Path(path)
    if not file.is_file():
        log.debug("status.json ещё нет: %s", path)
        return [], False

    try:
        doc = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Не прочитал status.json: %s", exc)
        return [], False

    generated = _parse_time(doc.get("generated_at"))
    fresh = generated is not None and (
        dt.datetime.now(dt.timezone.utc) - generated
    ) < STALE_AFTER

    nodes = [
        NodeState(
            name=str(n.get("name", "")),
            region=str(n.get("region", "")),
            state=str(n.get("state", "")),
        )
        for n in doc.get("nodes", [])
        if n.get("name")
    ]

    if not fresh and nodes:
        log.warning(
            "status.json устарел (%s) — тревоги не рассылаю, проверь cron "
            "status-json.sh на панели",
            doc.get("generated_at"),
        )

    return nodes, fresh


def diff(previous: dict[str, str], current: list[NodeState]) -> list[Incident]:
    """Что изменилось со времени прошлой проверки.

    Только переходы, а не текущее состояние: лежащий узел не должен
    порождать сообщение каждые пять минут. Узел, которого раньше не
    видели, инцидентом не считается — иначе первый запуск бота разошлёт
    тревогу по всем узлам, которые просто ещё не заводили.
    """
    events: list[Incident] = []

    for node in current:
        was = previous.get(node.name)
        if was is None or was == node.state:
            continue
        events.append(
            Incident(node=node.name, region=node.region, was=was, now=node.state)
        )

    return events


def healthy_names(nodes: list[NodeState]) -> list[str]:
    return [n.region or n.name for n in nodes if n.state in HEALTHY]


def _parse_time(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
