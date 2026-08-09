"""Гейт по подписке и антифрод.

Главное, что здесь проверяется, — поведение при СЛОМАННОЙ проверке.
Оно контринтуитивное (пускаем всех), и именно поэтому его легко «починить»
в обратную сторону, не заметив, что тем самым потерян весь входящий поток.
"""

from __future__ import annotations

import pytest
from aiogram.exceptions import TelegramAPIError

from app.gate import account_too_fresh, is_subscribed


class FakeMember:
    def __init__(self, status: str, is_member: bool | None = None) -> None:
        self.status = status
        if is_member is not None:
            self.is_member = is_member


class FakeBot:
    def __init__(self, result) -> None:
        self._result = result

    async def get_chat_member(self, chat_id, user_id):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


@pytest.mark.parametrize("status", ["member", "administrator", "creator"])
async def test_subscribed_statuses_pass(status):
    bot = FakeBot(FakeMember(status))
    assert await is_subscribed(bot, "@ch", 1) is True


@pytest.mark.parametrize("status", ["left", "kicked"])
async def test_not_subscribed_statuses_fail(status):
    bot = FakeBot(FakeMember(status))
    assert await is_subscribed(bot, "@ch", 1) is False


async def test_restricted_but_member_passes():
    """Ограничен в правах писать, но подписан. Комментарии нам не нужны."""
    bot = FakeBot(FakeMember("restricted", is_member=True))
    assert await is_subscribed(bot, "@ch", 1) is True


async def test_restricted_and_not_member_fails():
    bot = FakeBot(FakeMember("restricted", is_member=False))
    assert await is_subscribed(bot, "@ch", 1) is False


async def test_broken_check_lets_everyone_in():
    """Бота выкинули из админов канала — выдаём триал без проверки.

    Сломанная проверка, которая всех отсекает, теряет весь поток за то время,
    пока её не заметили. Сломанная проверка, которая всех пускает, стоит
    нескольких неподписанных триалов.
    """
    bot = FakeBot(TelegramAPIError(method=None, message="chat not found"))
    assert await is_subscribed(bot, "@ch", 1) is True


def test_age_cutoff_blocks_fresh_accounts():
    assert account_too_fresh(9_000_000_001, 9_000_000_000) is True
    assert account_too_fresh(8_999_999_999, 9_000_000_000) is False


def test_age_cutoff_disabled_when_not_calibrated():
    """Порог не задан — проверка пропускает всех, а не отсекает всех."""
    assert account_too_fresh(9_999_999_999, None) is False
