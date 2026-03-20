import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Required settings
def _get_required(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise ValueError(f"Required environment variable '{key}' is missing or empty")
    return value


def _get_int(key: str, default: int | None = None) -> int:
    value = os.getenv(key)
    if value is None:
        if default is not None:
            return default
        raise ValueError(f"Required environment variable '{key}' is missing")
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Environment variable '{key}' must be an integer, got: {value!r}")


BOT_TOKEN: str = _get_required("BOT_TOKEN")
ADMIN_TELEGRAM_ID: int = _get_int("ADMIN_TELEGRAM_ID")
TIMEZONE: str = os.getenv("TIMEZONE", "Europe/Moscow")
WORKING_HOURS_START: int = _get_int("WORKING_HOURS_START", 9)
WORKING_HOURS_END: int = _get_int("WORKING_HOURS_END", 18)
MAX_SLOTS_PER_HOUR: int = _get_int("MAX_SLOTS_PER_HOUR", 4)
BOOKING_DAYS_AHEAD: int = _get_int("BOOKING_DAYS_AHEAD", 14)

# Fixed list of services
SERVICES: list[str] = [
    "Замена масла",
    "Диагностика двигателя",
    "Шиномонтаж",
    "Замена тормозных колодок",
    "Развал-схождение",
    "ТО (техобслуживание)",
    "Ремонт подвески",
    "Диагностика ходовой",
]

logger.debug(
    "Config loaded: ADMIN_TELEGRAM_ID=%s, TIMEZONE=%s, WORKING_HOURS=%s-%s, "
    "MAX_SLOTS_PER_HOUR=%s, BOOKING_DAYS_AHEAD=%s, SERVICES_COUNT=%d",
    ADMIN_TELEGRAM_ID,
    TIMEZONE,
    WORKING_HOURS_START,
    WORKING_HOURS_END,
    MAX_SLOTS_PER_HOUR,
    BOOKING_DAYS_AHEAD,
    len(SERVICES),
)
