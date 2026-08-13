"""Гейт по подписке на канал и антифрод на триале.

Обоснование механики — docs/bot-flow.md. Здесь только реализация, но одно
решение стоит повторить прямо в коде, потому что интуиция подсказывает
обратное: **при сломанной проверке мы пускаем.**

Сломанная проверка, которая всех отсекает, выглядит как «бот молчит и никого
не пускает» — вы теряете всех пришедших за то время, пока не заметите.
Сломанная проверка, которая всех пускает, стоит нескольких неподписанных
триалов. Второе дешевле на порядок.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

log = logging.getLogger(__name__)

# Подписчик: обычный участник, админ, создатель.
SUBSCRIBED = {"member", "administrator", "creator"}


async def is_subscribed(bot: Bot, channel: str, telegram_id: int) -> bool:
    """Подписан ли пользователь на канал.

    Бот должен быть администратором канала — иначе Telegram не даст спросить.
    Достаточно прав только на просмотр участников.
    """
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=telegram_id)
    except TelegramAPIError as exc:
        # Бота выкинули из админов, канал переименован, Telegram недоступен.
        # Пускаем и пишем в лог — см. комментарий в шапке модуля.
        log.warning("Проверка подписки сломалась, пускаем без неё: %s", exc)
        return True

    status = member.status

    # restricted — человек подписан, но ограничен в правах писать. Нам от него
    # комментарии и не нужны, поэтому смотрим на is_member, а не на статус.
    if status == "restricted":
        return bool(getattr(member, "is_member", False))

    return status in SUBSCRIBED


def account_too_fresh(telegram_id: int, max_id: int | None) -> bool:
    """Аккаунт слишком свежий для триала.

    Точного возраста Telegram не отдаёт, но ID выдаются возрастающими, и
    порядок величины по ним виден — для отсечки этого достаточно.

    max_id=None означает, что порог не откалиброван. Тогда проверка выключена
    и пропускает всех: неоткалиброванный порог, поставленный наугад, отсекает
    либо никого, либо всех, и второе обнаруживается слишком поздно.
    """
    if max_id is None:
        return False
    return telegram_id > max_id
