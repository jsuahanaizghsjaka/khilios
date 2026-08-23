"""Обнаружение аварий: что считается инцидентом, а что молчанием.

Цена ошибки здесь несимметрична и в обе стороны неприятна: пропустили
аварию — человек сидит и гадает, ради чего всё и делалось; послали лишнее
— разослали спам всей базе разом, и от бота отписываются. Поэтому граничные
случаи проверяются отдельно, а не «на живую».
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from app import incidents
from app.db import Db


def _doc(nodes, *, age_minutes: int = 0) -> str:
    generated = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=age_minutes)
    return json.dumps(
        {
            "generated_at": generated.isoformat(timespec="seconds"),
            "nodes": [
                {"name": n, "region": r, "state": s, "checked_at": "x"}
                for n, r, s in nodes
            ],
        }
    )


@pytest.fixture
async def db(tmp_path):
    store = Db(str(tmp_path / "incidents.sqlite3"))
    await store.connect()
    yield store
    await store.close()


# --- чтение файла ---------------------------------------------------------


def test_missing_file_is_not_an_error(tmp_path):
    """До первого запуска cron файла нет. Это не повод ронять цикл."""
    nodes, fresh = incidents.read_status(str(tmp_path / "nope.json"))
    assert nodes == []
    assert fresh is False


def test_broken_json_is_not_an_error(tmp_path):
    path = tmp_path / "status.json"
    path.write_text("{не json", encoding="utf-8")

    nodes, fresh = incidents.read_status(str(path))
    assert nodes == []
    assert fresh is False


def test_fresh_file_is_parsed(tmp_path):
    path = tmp_path / "status.json"
    path.write_text(_doc([("fi-1", "Финляндия", "up")]), encoding="utf-8")

    nodes, fresh = incidents.read_status(str(path))
    assert fresh is True
    assert nodes[0].name == "fi-1"
    assert nodes[0].region == "Финляндия"
    assert nodes[0].state == "up"


def test_stale_file_is_flagged_not_trusted(tmp_path):
    """Замерший файл — признак умершего cron, а не рабочего состояния.
    Рассылать по нему нельзя: скажем «лежит» про давно поднятый узел."""
    path = tmp_path / "status.json"
    path.write_text(
        _doc([("fi-1", "Финляндия", "down")], age_minutes=60), encoding="utf-8"
    )

    nodes, fresh = incidents.read_status(str(path))
    assert nodes  # узлы разобрали
    assert fresh is False  # но доверять им нельзя


# --- что считается инцидентом --------------------------------------------


def test_state_change_is_an_incident():
    previous = {"fi-1": "up"}
    current = [incidents.NodeState("fi-1", "Финляндия", "down")]

    events = incidents.diff(previous, current)
    assert len(events) == 1
    assert events[0].was == "up"
    assert events[0].now == "down"
    assert events[0].recovered is False


def test_unchanged_state_is_silence():
    """Лежащий узел не должен слать сообщение каждые пять минут."""
    previous = {"fi-1": "down"}
    current = [incidents.NodeState("fi-1", "Финляндия", "down")]

    assert incidents.diff(previous, current) == []


def test_recovery_is_an_incident():
    previous = {"fi-1": "down"}
    current = [incidents.NodeState("fi-1", "Финляндия", "up")]

    events = incidents.diff(previous, current)
    assert events[0].recovered is True


def test_unknown_node_is_not_an_incident():
    """Первый запуск бота не должен разослать тревогу по всему парку."""
    current = [
        incidents.NodeState("fi-1", "Финляндия", "up"),
        incidents.NodeState("se-1", "Швеция", "down"),
    ]
    assert incidents.diff({}, current) == []


def test_healthy_names_lists_only_working_nodes():
    nodes = [
        incidents.NodeState("fi-1", "Финляндия", "up"),
        incidents.NodeState("se-1", "Швеция", "down"),
        incidents.NodeState("nl-1", "Нидерланды", "degraded"),
    ]
    assert incidents.healthy_names(nodes) == ["Финляндия"]


# --- кому шлём ------------------------------------------------------------


async def test_only_active_subscribers_get_alerts(db):
    """Человеку с истёкшей подпиской сообщение про упавший узел — спам:
    у него и так не работает, и причина другая."""
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=5)).isoformat()
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()

    await db.get_or_create(1)
    await db.save_subscription(
        1, state="active", panel_uuid="a", sub_url="s", expires_at=future, devices=5
    )

    await db.get_or_create(2)
    await db.save_subscription(
        2, state="active", panel_uuid="b", sub_url="s", expires_at=past, devices=5
    )

    await db.get_or_create(3)  # вообще без подписки

    assert await db.active_subscribers() == [1]


async def test_node_state_survives_restart(db):
    """Состояние живёт в базе, а не в памяти: иначе перезапуск бота
    выглядел бы как «все узлы изменились» и разослал бы тревогу разом."""
    await db.remember_node_state("fi-1", "up")
    assert await db.known_node_states() == {"fi-1": "up"}

    await db.remember_node_state("fi-1", "down")
    assert await db.known_node_states() == {"fi-1": "down"}
