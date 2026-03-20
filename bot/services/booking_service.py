import logging
import traceback
from datetime import date, time, timedelta

from bot import config
from bot.database import db
from bot.database.models import Booking, PENDING, CONFIRMED, CANCELLED

logger = logging.getLogger(__name__)


def get_available_dates() -> list[date]:
    """Return the next BOOKING_DAYS_AHEAD working days (Mon–Fri), starting from tomorrow."""
    logger.debug(
        "get_available_dates: BOOKING_DAYS_AHEAD=%d", config.BOOKING_DAYS_AHEAD
    )
    result: list[date] = []
    current = date.today() + timedelta(days=1)
    while len(result) < config.BOOKING_DAYS_AHEAD:
        if current.weekday() < 5:  # 0=Mon ... 4=Fri
            result.append(current)
        current += timedelta(days=1)
    logger.debug("get_available_dates: returning %d dates", len(result))
    return result


async def get_available_slots(booking_date: date) -> list[time]:
    """Return available time slots for the given date."""
    logger.debug(
        "get_available_slots: date=%s WORKING_HOURS=%d-%d MAX_SLOTS_PER_HOUR=%d",
        booking_date,
        config.WORKING_HOURS_START,
        config.WORKING_HOURS_END,
        config.MAX_SLOTS_PER_HOUR,
    )
    all_slots = [
        time(hour=h, minute=0)
        for h in range(config.WORKING_HOURS_START, config.WORKING_HOURS_END)
    ]

    available: list[time] = []
    date_str = booking_date.isoformat()
    for slot in all_slots:
        time_str = slot.strftime("%H:%M")
        count = await db.get_slot_count(date_str, time_str)
        if count < config.MAX_SLOTS_PER_HOUR:
            available.append(slot)
        else:
            logger.debug("Slot full: date=%s time=%s count=%d", date_str, time_str, count)

    logger.debug("get_available_slots: date=%s available=%d/%d",
                 booking_date, len(available), len(all_slots))
    return available


async def create_booking(
    user_id: int,
    car_brand: str,
    car_model: str,
    service: str,
    booking_date: date,
    booking_time: time,
) -> Booking | None:
    """Create a booking with slot availability check (atomic)."""
    date_str = booking_date.isoformat()
    time_str = booking_time.strftime("%H:%M")
    logger.debug(
        "create_booking: user_id=%s car=%s %s service=%s date=%s time=%s",
        user_id, car_brand, car_model, service, date_str, time_str,
    )
    try:
        count = await db.get_slot_count(date_str, time_str)
        if count >= config.MAX_SLOTS_PER_HOUR:
            logger.warning(
                "Slot already full: date=%s time=%s count=%d user_id=%s",
                date_str, time_str, count, user_id,
            )
            return None

        booking = await db.create_booking(
            user_id=user_id,
            car_brand=car_brand,
            car_model=car_model,
            service=service,
            booking_date=date_str,
            booking_time=time_str,
        )
        logger.info(
            "Booking created successfully: booking_id=%s user_id=%s service=%s date=%s time=%s",
            booking.id, user_id, service, date_str, time_str,
        )
        return booking
    except Exception:
        logger.error("create_booking failed:\n%s", traceback.format_exc())
        raise


async def cancel_booking(
    booking_id: int,
    user_id: int | None = None,
    cancel_reason: str | None = None,
) -> bool:
    """Cancel a booking. If user_id is provided, verify ownership."""
    logger.debug(
        "cancel_booking: booking_id=%s user_id=%s", booking_id, user_id
    )
    try:
        booking = await db.get_booking_by_id(booking_id)
        if booking is None:
            logger.warning("cancel_booking: booking_id=%s not found", booking_id)
            return False

        if user_id is not None and booking.user_id != user_id:
            logger.warning(
                "cancel_booking: user_id=%s tried to cancel booking_id=%s owned by user_id=%s",
                user_id, booking_id, booking.user_id,
            )
            return False

        if booking.status in (CANCELLED, "completed"):
            logger.warning(
                "cancel_booking: invalid status=%s for booking_id=%s",
                booking.status, booking_id,
            )
            return False

        result = await db.update_booking_status(
            booking_id, CANCELLED, cancel_reason=cancel_reason
        )
        if result:
            logger.info(
                "Booking cancelled: booking_id=%s user_id=%s reason=%s",
                booking_id, user_id, cancel_reason,
            )
        return result
    except Exception:
        logger.error("cancel_booking failed:\n%s", traceback.format_exc())
        raise


async def get_user_bookings(user_id: int) -> list[Booking]:
    logger.debug("get_user_bookings: user_id=%s", user_id)
    return await db.get_user_bookings(user_id)
