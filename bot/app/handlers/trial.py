"""Выдача пробного периода.

Порядок проверок взят из docs/bot-flow.md и намеренно начинается с канала:
гейт — единственный легальный канал привлечения у проекта, рефералка
заморожена до ответа юриста. Человек, дошедший до кнопки, подписывается
до того, как узнает результат остальных проверок.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from .. import fmt, gate, keyboards as kb, screens, texts
from ..config import Config
from ..db import Db
from ..panel import PanelClient, PanelError, PanelUnavailable
from ..plans import TRIAL
from .common import show_menu

log = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data.in_({kb.CB_TRIAL, kb.CB_GATE_CHECK}))
async def issue_trial(
    call: CallbackQuery,
    bot: Bot,
    db: Db,
    config: Config,
    panel: PanelClient,
) -> None:
    telegram_id = call.from_user.id
    user = await db.get_or_create(telegram_id)

    # 1. Гейт по подписке на канал.
    if not await gate.is_subscribed(bot, config.channel, telegram_id):
        text = texts.GATE_STILL_NOT if call.data == kb.CB_GATE_CHECK else texts.GATE
        await _edit(call, text, kb.gate(config.channel), screens.MENU)
        await call.answer()
        return

    # 2. Один триал на один Telegram ID. Проверяем по ID, не по имени:
    #    имя меняется за секунду.
    if user.had_trial:
        await _edit(
            call,
            texts.TRIAL_ALREADY + "\n\n" + texts.tariffs(),
            kb.tariffs(payments_enabled=config.payments_enabled),
            screens.TARIFFS,
        )
        await call.answer()
        return

    # 3. Отсечка по возрасту аккаунта.
    if gate.account_too_fresh(telegram_id, config.trial_max_telegram_id):
        log.info("Триал не выдан, свежий аккаунт: %s", telegram_id)
        await _edit(
            call,
            texts.TRIAL_TOO_FRESH + "\n\n" + texts.tariffs(),
            kb.tariffs(payments_enabled=config.payments_enabled),
            screens.TARIFFS,
        )
        await call.answer()
        return

    # 4. Создать пользователя в панели.
    await call.answer("Готовлю ключ…")
    try:
        uuid, sub_url, expires_at = await panel.create_user(
            telegram_id=telegram_id,
            days=TRIAL.days,
            devices=TRIAL.devices,
            tag="trial",
        )
    except (PanelError, PanelUnavailable) as exc:
        log.error("Не выдан триал для %s: %s", telegram_id, exc)
        await _edit(
            call,
            texts.ERROR_ISSUE_FAILED,
            kb.support(config.support_url, config.channel),
            screens.SUPPORT,
        )
        return

    await db.save_subscription(
        telegram_id,
        state="trial",
        panel_uuid=uuid,
        sub_url=sub_url,
        expires_at=expires_at,
        devices=TRIAL.devices,
        mark_trial=True,
    )

    # 5. Отдать ссылку.
    await _edit(
        call,
        texts.TRIAL_ISSUED.format(sub_url=sub_url, until=fmt.date(expires_at)),
        kb.after_issue(),
        screens.SUCCESS,
    )
    log.info("Триал выдан: %s до %s", telegram_id, expires_at)


async def _edit(
    call: CallbackQuery, text: str, markup, asset: str = screens.MENU
) -> None:
    """Обновить один экран, не добавляя повторные сообщения в чат."""
    await screens.edit(call, asset, text, markup)
