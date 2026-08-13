"""Планировщик должен иметь полный и однозначный набор напоминаний."""

from app.scheduler import REMINDERS
from app.texts import REMIND


def test_all_scheduler_reminders_have_texts_and_unique_offsets():
    assert REMINDERS == (("d3", 3), ("d1", 1), ("d0", 0))
    assert {kind for kind, _ in REMINDERS} == set(REMIND)
    assert len({days for _, days in REMINDERS}) == len(REMINDERS)
