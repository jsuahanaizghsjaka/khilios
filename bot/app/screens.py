"""Фирменные медиакарточки для ключевых экранов Telegram-бота."""

from __future__ import annotations

from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, Message

ASSET_DIR = Path(__file__).with_name("assets")

MENU = "menu.jpg"
CONNECT = "connect.jpg"
TARIFFS = "tariffs.jpg"
SUCCESS = "success.jpg"
SUPPORT = "support.jpg"

ALL = (MENU, CONNECT, TARIFFS, SUCCESS, SUPPORT)


def photo(asset: str) -> FSInputFile:
    """Создать свежий upload-объект: aiogram не переиспользует открытый файл."""
    return FSInputFile(ASSET_DIR / asset)


async def send(
    message: Message,
    asset: str,
    text: str,
    markup,
) -> None:
    await message.answer_photo(
        photo(asset),
        caption=text,
        reply_markup=markup,
        show_caption_above_media=False,
    )


async def edit(
    call: CallbackQuery,
    asset: str,
    text: str,
    markup,
) -> None:
    """Обновить медиакарточку или заменить старое текстовое сообщение.

    Первый экран до согласия остаётся текстовым из-за юридических ссылок.
    После согласия он один раз заменяется карточкой, а дальше весь интерфейс
    живёт в одном сообщении и не засоряет чат повторяющимися картинками.
    """
    message = call.message
    if getattr(message, "photo", None):
        try:
            await message.edit_media(
                InputMediaPhoto(media=photo(asset), caption=text),
                reply_markup=markup,
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        return

    try:
        await message.delete()
    except TelegramBadRequest:
        # Старые сообщения иногда уже нельзя удалить. В таком случае не
        # теряем кнопку и текст, даже если карточку показать не получится.
        await message.edit_text(
            text,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
        return

    await send(message, asset, text, markup)
