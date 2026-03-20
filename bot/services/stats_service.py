import logging
from datetime import date, timedelta

from bot.database import db

logger = logging.getLogger(__name__)

_STATUS_RU = {
    "pending": "Ожидает",
    "confirmed": "Подтверждена",
    "completed": "Завершена",
    "cancelled": "Отменена",
}


def _format_stats(stats: dict, period: str) -> str:
    total = sum(stats.values())
    lines = [f"📊 Статистика за {period}:", f"Всего записей: {total}"]
    for status, label in _STATUS_RU.items():
        count = stats.get(status, 0)
        lines.append(f"  {label}: {count}")
    return "\n".join(lines)


async def get_stats_today() -> str:
    today = date.today()
    logger.debug("get_stats_today: date=%s", today)
    stats = await db.get_stats_by_period(today, today)
    logger.debug("get_stats_today: result=%s", stats)
    return _format_stats(stats, "сегодня")


async def get_stats_week() -> str:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    logger.debug("get_stats_week: start=%s end=%s", week_start, today)
    stats = await db.get_stats_by_period(week_start, today)
    logger.debug("get_stats_week: result=%s", stats)
    return _format_stats(stats, "эту неделю")


async def get_stats_month() -> str:
    today = date.today()
    month_start = today.replace(day=1)
    logger.debug("get_stats_month: start=%s end=%s", month_start, today)
    stats = await db.get_stats_by_period(month_start, today)
    logger.debug("get_stats_month: result=%s", stats)
    return _format_stats(stats, "этот месяц")


async def get_popular_services() -> list[tuple[str, int]]:
    logger.debug("get_popular_services")
    result = await db.get_popular_services_from_db()
    logger.debug("get_popular_services: result=%s", result)
    return result


async def get_cancellation_rate() -> float:
    logger.debug("get_cancellation_rate")
    rate = await db.get_cancellation_rate_from_db()
    logger.debug("get_cancellation_rate: rate=%.2f%%", rate)
    return rate


async def format_full_stats() -> str:
    """Full stats text for admin — today, week, month, popular services, cancellation rate."""
    today_text = await get_stats_today()
    week_text = await get_stats_week()
    month_text = await get_stats_month()
    services = await get_popular_services()
    cancel_rate = await get_cancellation_rate()

    services_lines = "\n".join(
        f"  {i+1}. {name}: {count}" for i, (name, count) in enumerate(services)
    ) or "  Нет данных"

    return (
        f"{today_text}\n\n"
        f"{week_text}\n\n"
        f"{month_text}\n\n"
        f"🔝 Популярные услуги:\n{services_lines}\n\n"
        f"❌ Процент отмен: {cancel_rate:.1f}%"
    )
