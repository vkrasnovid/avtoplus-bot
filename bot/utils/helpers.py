from datetime import date, time

from bot import config

_STATUS_RU = {
    "pending": "Ожидает",
    "confirmed": "Подтверждена",
    "completed": "Завершена",
    "cancelled": "Отменена",
}


def format_date(d: date) -> str:
    """Format date as ДД.ММ.ГГГГ"""
    return d.strftime("%d.%m.%Y")


def format_time(t: time) -> str:
    """Format time as ЧЧ:ММ"""
    return t.strftime("%H:%M")


def status_to_russian(status: str) -> str:
    return _STATUS_RU.get(status, status)


def is_admin(telegram_id: int) -> bool:
    return telegram_id == config.ADMIN_TELEGRAM_ID
