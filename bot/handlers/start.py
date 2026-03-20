import logging

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot import config
from bot.database import db
from bot.keyboards.admin import admin_main_kb
from bot.keyboards.client import main_menu_kb

logger = logging.getLogger(__name__)

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    telegram_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name or "Клиент"

    logger.debug("cmd_start: user_id=%s entered", telegram_id)

    user = await db.get_or_create_user(telegram_id, username, first_name)

    if user.telegram_id == telegram_id and not _was_existing(user):
        logger.info("New user registered: telegram_id=%s username=%s", telegram_id, username)

    if telegram_id == config.ADMIN_TELEGRAM_ID:
        logger.debug("cmd_start: user_id=%s is admin, showing admin keyboard", telegram_id)
        await message.answer(
            "Добро пожаловать в АвтоПлюс! Выберите действие:",
            reply_markup=admin_main_kb(),
        )
    else:
        logger.debug("cmd_start: user_id=%s is client, showing main menu", telegram_id)
        await message.answer(
            "Добро пожаловать в АвтоПлюс! Выберите действие:",
            reply_markup=main_menu_kb(),
        )


def _was_existing(user) -> bool:
    """Heuristic: user was existing if created_at differs from now by more than a second."""
    from datetime import datetime, timezone
    delta = datetime.now(timezone.utc).replace(tzinfo=None) - user.created_at.replace(tzinfo=None)
    return abs(delta.total_seconds()) > 1
