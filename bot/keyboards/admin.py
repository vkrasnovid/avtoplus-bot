import logging
from datetime import date

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

logger = logging.getLogger(__name__)


def admin_main_kb() -> ReplyKeyboardMarkup:
    logger.debug("Building admin_main_kb")
    keyboard = [
        [KeyboardButton(text="Записи сегодня"), KeyboardButton(text="Записи завтра")],
        [KeyboardButton(text="Выбрать дату"), KeyboardButton(text="Статистика")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def admin_date_picker_kb(dates: list[date]) -> InlineKeyboardMarkup:
    logger.debug("Building admin_date_picker_kb: %d dates", len(dates))
    buttons = []
    row: list[InlineKeyboardButton] = []
    for d in dates:
        label = d.strftime("%d.%m")
        row.append(
            InlineKeyboardButton(text=label, callback_data=f"admin_date:{d.isoformat()}")
        )
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def booking_manage_kb(booking_id: int) -> InlineKeyboardMarkup:
    logger.debug("Building booking_manage_kb: booking_id=%s", booking_id)
    buttons = [
        [
            InlineKeyboardButton(
                text="✅ Подтвердить",
                callback_data=f"admin_confirm:{booking_id}",
            ),
            InlineKeyboardButton(
                text="✔️ Завершить",
                callback_data=f"admin_complete:{booking_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="❌ Отменить",
                callback_data=f"admin_cancel:{booking_id}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
