import logging
import traceback
from datetime import date

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot import config
from bot.database import db
from bot.database.models import PENDING, CONFIRMED
from bot.keyboards.client import booking_actions_kb, main_menu_kb
from bot.services import booking_service

logger = logging.getLogger(__name__)

router = Router()

_STATUS_RU = {
    "pending": "Ожидает",
    "confirmed": "Подтверждена",
    "completed": "Завершена",
    "cancelled": "Отменена",
}


@router.message(F.text == "Мои записи")
async def show_my_bookings(message: Message) -> None:
    telegram_id = message.from_user.id
    logger.debug("show_my_bookings: user_id=%s", telegram_id)

    user = await db.get_or_create_user(
        telegram_id,
        message.from_user.username,
        message.from_user.first_name or "Клиент",
    )

    bookings = await db.get_user_bookings(user.id)
    logger.debug("show_my_bookings: user_id=%s found %d bookings", telegram_id, len(bookings))

    if not bookings:
        await message.answer("У вас пока нет записей", reply_markup=main_menu_kb())
        return

    for booking in bookings:
        status_ru = _STATUS_RU.get(booking.status, booking.status)
        booking_date_obj = date.fromisoformat(booking.booking_date)
        text = (
            f"🚗 {booking.car_brand} {booking.car_model}\n"
            f"🔧 {booking.service}\n"
            f"📅 {booking_date_obj.strftime('%d.%m.%Y')} в {booking.booking_time}\n"
            f"Статус: {status_ru}"
        )
        if booking.status in (PENDING, CONFIRMED):
            await message.answer(text, reply_markup=booking_actions_kb(booking.id))
        else:
            await message.answer(text)


@router.callback_query(F.data.startswith("cancel_booking:"))
async def cancel_booking_callback(callback: CallbackQuery) -> None:
    booking_id = int(callback.data.split(":", 1)[1])
    telegram_id = callback.from_user.id
    logger.debug(
        "cancel_booking_callback: user_id=%s booking_id=%s", telegram_id, booking_id
    )

    user = await db.get_or_create_user(
        telegram_id,
        callback.from_user.username,
        callback.from_user.first_name or "Клиент",
    )

    try:
        success = await booking_service.cancel_booking(
            booking_id=booking_id, user_id=user.id
        )
    except Exception:
        logger.error("cancel_booking_callback failed:\n%s", traceback.format_exc())
        await callback.answer("Произошла ошибка. Попробуйте позже.", show_alert=True)
        return

    if not success:
        await callback.answer("Не удалось отменить запись.", show_alert=True)
        return

    logger.info(
        "Booking %s cancelled by user: user_id=%s", booking_id, telegram_id
    )

    booking = await db.get_booking_by_id(booking_id)
    await callback.message.edit_text(
        callback.message.text + "\nСтатус: Отменена"
    )
    await callback.answer("Запись отменена.")

    # Notify admin
    try:
        if booking:
            booking_date_obj = date.fromisoformat(booking.booking_date)
            admin_text = (
                f"Запись отменена: {callback.from_user.first_name} — "
                f"{booking_date_obj.strftime('%d.%m')} в {booking.booking_time}"
            )
            await callback.bot.send_message(
                chat_id=config.ADMIN_TELEGRAM_ID, text=admin_text
            )
    except Exception:
        logger.error(
            "cancel_booking_callback: failed to notify admin:\n%s", traceback.format_exc()
        )
