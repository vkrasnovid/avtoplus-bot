import logging
import traceback
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.database import db
from bot.database.models import CONFIRMED, COMPLETED, CANCELLED
from bot.keyboards.admin import admin_date_picker_kb, admin_main_kb, booking_manage_kb
from bot.services import booking_service, stats_service
from bot.utils.helpers import is_admin

logger = logging.getLogger(__name__)

router = Router()

_STATUS_RU = {
    "pending": "Ожидает",
    "confirmed": "Подтверждена",
    "completed": "Завершена",
    "cancelled": "Отменена",
}


class AdminStates(StatesGroup):
    waiting_cancel_reason = State()
    waiting_date_pick = State()


# ── Guard helper ───────────────────────────────────────────────────────────

def _guard_message(message: Message) -> bool:
    if not is_admin(message.from_user.id):
        logger.warning(
            "Non-admin tried to access admin handler: user_id=%s", message.from_user.id
        )
        return False
    return True


def _guard_callback(callback: CallbackQuery) -> bool:
    if not is_admin(callback.from_user.id):
        logger.warning(
            "Non-admin tried to access admin callback: user_id=%s", callback.from_user.id
        )
        return False
    return True


# ── Format bookings list ───────────────────────────────────────────────────

def _format_booking_line(booking) -> str:
    status_ru = _STATUS_RU.get(booking.status, booking.status)
    return (
        f"#{booking.id} — {booking.car_brand} {booking.car_model} — "
        f"{booking.service} — {booking.booking_time} [{status_ru}]"
    )


async def _send_bookings_for_date(
    target_date: date,
    message: Message,
) -> None:
    bookings = await db.get_bookings_by_date(target_date)
    date_str = target_date.strftime("%d.%m.%Y")
    if not bookings:
        await message.answer(f"Нет записей на {date_str}.")
        return

    await message.answer(f"Записи на {date_str} ({len(bookings)} шт.):")
    for booking in bookings:
        user = await db.get_user_by_id(booking.user_id)
        username_str = f"@{user.username}" if user and user.username else "нет"
        first_name = user.first_name if user else "?"
        text = (
            f"#{booking.id}\n"
            f"👤 {first_name} ({username_str})\n"
            f"🚗 {booking.car_brand} {booking.car_model}\n"
            f"🔧 {booking.service}\n"
            f"⏰ {booking.booking_time}\n"
            f"Статус: {_STATUS_RU.get(booking.status, booking.status)}"
        )
        await message.answer(text, reply_markup=booking_manage_kb(booking.id))


# ── Handlers ───────────────────────────────────────────────────────────────

@router.message(F.text == "Записи сегодня")
async def bookings_today(message: Message) -> None:
    if not _guard_message(message):
        return
    logger.debug("admin action=bookings_today user_id=%s", message.from_user.id)
    await _send_bookings_for_date(date.today(), message)


@router.message(F.text == "Записи завтра")
async def bookings_tomorrow(message: Message) -> None:
    if not _guard_message(message):
        return
    logger.debug("admin action=bookings_tomorrow user_id=%s", message.from_user.id)
    await _send_bookings_for_date(date.today() + timedelta(days=1), message)


@router.message(F.text == "Выбрать дату")
async def choose_date(message: Message, state: FSMContext) -> None:
    if not _guard_message(message):
        return
    logger.debug("admin action=choose_date user_id=%s", message.from_user.id)
    dates = booking_service.get_available_dates()
    await state.set_state(AdminStates.waiting_date_pick)
    await message.answer("Выберите дату:", reply_markup=admin_date_picker_kb(dates))


@router.callback_query(AdminStates.waiting_date_pick, F.data.startswith("admin_date:"))
async def handle_date_pick(callback: CallbackQuery, state: FSMContext) -> None:
    if not _guard_callback(callback):
        await callback.answer()
        return
    date_str = callback.data.split(":", 1)[1]
    target_date = date.fromisoformat(date_str)
    logger.debug("admin action=date_pick date=%s user_id=%s", date_str, callback.from_user.id)
    await state.clear()
    await callback.message.edit_text(f"Выбрана дата: {target_date.strftime('%d.%m.%Y')}")
    await _send_bookings_for_date(target_date, callback.message)
    await callback.answer()


@router.message(F.text == "Статистика")
async def show_stats(message: Message) -> None:
    if not _guard_message(message):
        return
    logger.debug("admin action=stats user_id=%s", message.from_user.id)
    stats_text = await stats_service.format_full_stats()
    await message.answer(stats_text)


# ── Booking management callbacks ───────────────────────────────────────────

@router.callback_query(F.data.startswith("admin_confirm:"))
async def admin_confirm_booking(callback: CallbackQuery) -> None:
    if not _guard_callback(callback):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    booking_id = int(callback.data.split(":", 1)[1])
    logger.debug("admin action=confirm booking_id=%d user_id=%s", booking_id, callback.from_user.id)

    booking = await db.get_booking_by_id(booking_id)
    if booking is None:
        await callback.answer("Запись не найдена.", show_alert=True)
        return

    old_status = booking.status
    await db.update_booking_status(booking_id, CONFIRMED)
    logger.info(
        "Booking status changed: booking_id=%d %s → %s", booking_id, old_status, CONFIRMED
    )

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("✅ Запись подтверждена.")

    user = await db.get_user_by_id(booking.user_id)
    if user:
        try:
            await callback.bot.send_message(
                chat_id=user.telegram_id,
                text=f"Ваша запись на {booking.booking_date} в {booking.booking_time} подтверждена!",
            )
        except Exception:
            logger.error("Failed to notify client:\n%s", traceback.format_exc())


@router.callback_query(F.data.startswith("admin_complete:"))
async def admin_complete_booking(callback: CallbackQuery) -> None:
    if not _guard_callback(callback):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    booking_id = int(callback.data.split(":", 1)[1])
    logger.debug("admin action=complete booking_id=%d user_id=%s", booking_id, callback.from_user.id)

    booking = await db.get_booking_by_id(booking_id)
    if booking is None:
        await callback.answer("Запись не найдена.", show_alert=True)
        return

    old_status = booking.status
    await db.update_booking_status(booking_id, COMPLETED)
    logger.info(
        "Booking status changed: booking_id=%d %s → %s", booking_id, old_status, COMPLETED
    )

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("✔️ Запись завершена.")

    user = await db.get_user_by_id(booking.user_id)
    if user:
        try:
            await callback.bot.send_message(
                chat_id=user.telegram_id,
                text=f"Ваша запись на {booking.service} завершена. Спасибо, что выбрали АвтоПлюс!",
            )
        except Exception:
            logger.error("Failed to notify client:\n%s", traceback.format_exc())


@router.callback_query(F.data.startswith("admin_cancel:"))
async def admin_cancel_booking_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _guard_callback(callback):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    booking_id = int(callback.data.split(":", 1)[1])
    logger.debug(
        "admin action=cancel_start booking_id=%d user_id=%s", booking_id, callback.from_user.id
    )
    await state.set_state(AdminStates.waiting_cancel_reason)
    await state.update_data(cancel_booking_id=booking_id)
    await callback.message.answer(
        f"Укажите причину отмены записи #{booking_id}:"
    )
    await callback.answer()


@router.message(AdminStates.waiting_cancel_reason)
async def admin_cancel_booking_reason(message: Message, state: FSMContext) -> None:
    if not _guard_message(message):
        await state.clear()
        return
    data = await state.get_data()
    booking_id = data.get("cancel_booking_id")
    reason = message.text.strip() if message.text else ""
    logger.debug(
        "admin action=cancel booking_id=%s reason=%r user_id=%s",
        booking_id, reason, message.from_user.id,
    )
    await state.clear()

    if not booking_id:
        await message.answer("Ошибка: не найден ID записи.", reply_markup=admin_main_kb())
        return

    booking = await db.get_booking_by_id(booking_id)
    if booking is None:
        await message.answer("Запись не найдена.", reply_markup=admin_main_kb())
        return

    old_status = booking.status
    await db.update_booking_status(booking_id, CANCELLED, cancel_reason=reason)
    logger.info(
        "Booking status changed: booking_id=%d %s → %s reason=%r",
        booking_id, old_status, CANCELLED, reason,
    )
    await message.answer(f"Запись #{booking_id} отменена.", reply_markup=admin_main_kb())

    user = await db.get_user_by_id(booking.user_id)
    if user:
        try:
            reason_text = f" Причина: {reason}" if reason else ""
            await message.bot.send_message(
                chat_id=user.telegram_id,
                text=(
                    f"Ваша запись на {booking.service} "
                    f"({booking.booking_date} в {booking.booking_time}) отменена администратором."
                    f"{reason_text}"
                ),
            )
        except Exception:
            logger.error("Failed to notify client on admin cancel:\n%s", traceback.format_exc())
