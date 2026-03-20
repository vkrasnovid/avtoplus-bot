import logging
from datetime import date, time

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot import config

logger = logging.getLogger(__name__)


def main_menu_kb() -> ReplyKeyboardMarkup:
    logger.debug("Building main_menu_kb")
    keyboard = [
        [KeyboardButton(text="Записаться"), KeyboardButton(text="Мои записи")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def services_kb() -> InlineKeyboardMarkup:
    logger.debug("Building services_kb: %d services", len(config.SERVICES))
    buttons = [
        [InlineKeyboardButton(text=service, callback_data=f"service:{service}")]
        for service in config.SERVICES
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def dates_kb(dates: list[date]) -> InlineKeyboardMarkup:
    logger.debug("Building dates_kb: %d dates", len(dates))
    buttons = []
    row: list[InlineKeyboardButton] = []
    for d in dates:
        label = d.strftime("%d.%m")
        row.append(InlineKeyboardButton(text=label, callback_data=f"date:{d.isoformat()}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def slots_kb(slots: list[time]) -> InlineKeyboardMarkup:
    logger.debug("Building slots_kb: %d slots", len(slots))
    buttons = []
    row: list[InlineKeyboardButton] = []
    for slot in slots:
        label = slot.strftime("%H:%M")
        row.append(InlineKeyboardButton(text=label, callback_data=f"slot:{label}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_kb() -> InlineKeyboardMarkup:
    logger.debug("Building confirm_kb")
    buttons = [
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_booking"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_booking_flow"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def booking_actions_kb(booking_id: int) -> InlineKeyboardMarkup:
    logger.debug("Building booking_actions_kb: booking_id=%s", booking_id)
    buttons = [
        [
            InlineKeyboardButton(
                text="❌ Отменить запись",
                callback_data=f"cancel_booking:{booking_id}",
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
