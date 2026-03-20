import logging
import traceback
from datetime import date, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.database import db

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _send_reminders(bot: Bot) -> None:
    tomorrow = date.today() + timedelta(days=1)
    logger.debug("Reminder check started: target_date=%s", tomorrow)
    try:
        bookings = await db.get_pending_reminders(tomorrow)
        logger.debug("Reminder check: found %d pending reminders for date=%s",
                     len(bookings), tomorrow)

        for booking in bookings:
            user = await db.get_user_by_id(booking.user_id)
            if user is None:
                logger.warning(
                    "Reminder: user not found for booking_id=%s user_id=%s",
                    booking.id, booking.user_id,
                )
                continue

            text = (
                f"Напоминаем: завтра в {booking.booking_time} у вас запись на "
                f"{booking.service}. Ждём вас!"
            )
            try:
                await bot.send_message(chat_id=user.telegram_id, text=text)
                await db.mark_reminder_sent(booking.id)
                logger.info(
                    "Reminder sent: booking_id=%s telegram_id=%s",
                    booking.id, user.telegram_id,
                )
            except TelegramForbiddenError:
                logger.warning(
                    "Reminder not sent (user blocked bot): booking_id=%s telegram_id=%s",
                    booking.id, user.telegram_id,
                )
            except Exception:
                logger.error(
                    "Reminder send error for booking_id=%s:\n%s",
                    booking.id, traceback.format_exc(),
                )
    except Exception:
        logger.error("Reminder scheduler job failed:\n%s", traceback.format_exc())


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Create and configure the reminder scheduler. Call start() separately."""
    global _scheduler
    logger.debug("Setting up reminder scheduler")
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _send_reminders,
        trigger="cron",
        minute=0,  # every hour at :00
        kwargs={"bot": bot},
        id="send_reminders",
        replace_existing=True,
    )
    _scheduler = scheduler
    logger.debug("Reminder job scheduled: cron every hour")
    return scheduler


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler
