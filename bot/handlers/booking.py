import logging
import traceback
from datetime import date, time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot import config
from bot.database import db
from bot.keyboards.client import (
    confirm_kb,
    dates_kb,
    main_menu_kb,
    services_kb,
    slots_kb,
)
from bot.services import booking_service

logger = logging.getLogger(__name__)

router = Router()


class BookingStates(StatesGroup):
    waiting_car = State()
    waiting_service = State()
    waiting_date = State()
    waiting_slot = State()
    waiting_confirm = State()


# ── Step 1: "Записаться" button ────────────────────────────────────────────

@router.message(F.text == "Записаться")
async def start_booking(message: Message, state: FSMContext) -> None:
    logger.debug(
        "start_booking: user_id=%s state=None → waiting_car", message.from_user.id
    )
    await state.set_state(BookingStates.waiting_car)
    await message.answer(
        "Введите марку и модель автомобиля (например: Toyota Camry, BMW 3 Series)"
    )


# ── Cancel at any step ─────────────────────────────────────────────────────

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    logger.debug("cmd_cancel: user_id=%s current_state=%s", message.from_user.id, current)
    if current is None:
        await message.answer("Нет активной записи для отмены.", reply_markup=main_menu_kb())
        return
    await state.clear()
    logger.info("Booking flow cancelled by user: user_id=%s", message.from_user.id)
    await message.answer("Запись отменена.", reply_markup=main_menu_kb())


# ── Step 2: Car brand/model input ─────────────────────────────────────────

@router.message(BookingStates.waiting_car)
async def process_car(message: Message, state: FSMContext) -> None:
    text = message.text.strip() if message.text else ""
    logger.debug(
        "process_car: user_id=%s input=%r state=waiting_car → waiting_service",
        message.from_user.id, text,
    )
    parts = text.split(None, 1)
    if len(parts) < 2:
        await message.answer(
            "Пожалуйста, укажите и марку, и модель. Например: Toyota Camry"
        )
        return

    car_brand = parts[0]
    car_model = parts[1]
    await state.update_data(car_brand=car_brand, car_model=car_model)
    logger.debug(
        "process_car: user_id=%s car_brand=%s car_model=%s → waiting_service",
        message.from_user.id, car_brand, car_model,
    )
    await state.set_state(BookingStates.waiting_service)
    await message.answer("Выберите услугу:", reply_markup=services_kb())


# ── Step 3: Service selection ──────────────────────────────────────────────

@router.callback_query(BookingStates.waiting_service, F.data.startswith("service:"))
async def process_service(callback: CallbackQuery, state: FSMContext) -> None:
    service = callback.data.split(":", 1)[1]
    logger.debug(
        "process_service: user_id=%s service=%s state=waiting_service → waiting_date",
        callback.from_user.id, service,
    )
    await state.update_data(service=service)
    await state.set_state(BookingStates.waiting_date)

    dates = booking_service.get_available_dates()
    await callback.message.edit_text(
        f"Услуга: {service}\nВыберите дату:",
        reply_markup=dates_kb(dates),
    )
    await callback.answer()


# ── Step 4: Date selection ─────────────────────────────────────────────────

@router.callback_query(BookingStates.waiting_date, F.data.startswith("date:"))
async def process_date(callback: CallbackQuery, state: FSMContext) -> None:
    date_str = callback.data.split(":", 1)[1]
    booking_date = date.fromisoformat(date_str)
    logger.debug(
        "process_date: user_id=%s date=%s state=waiting_date → waiting_slot",
        callback.from_user.id, date_str,
    )
    await state.update_data(booking_date=date_str)
    await state.set_state(BookingStates.waiting_slot)

    slots = await booking_service.get_available_slots(booking_date)
    if not slots:
        logger.warning("process_date: no available slots for date=%s", date_str)
        await callback.message.edit_text(
            f"На {booking_date.strftime('%d.%m.%Y')} нет свободных слотов. Выберите другую дату:",
            reply_markup=dates_kb(booking_service.get_available_dates()),
        )
        await state.set_state(BookingStates.waiting_date)
        await callback.answer()
        return

    await callback.message.edit_text(
        f"Дата: {booking_date.strftime('%d.%m.%Y')}\nВыберите время:",
        reply_markup=slots_kb(slots),
    )
    await callback.answer()


# ── Step 5: Slot selection ─────────────────────────────────────────────────

@router.callback_query(BookingStates.waiting_slot, F.data.startswith("slot:"))
async def process_slot(callback: CallbackQuery, state: FSMContext) -> None:
    time_str = callback.data.split(":", 1)[1]
    logger.debug(
        "process_slot: user_id=%s time=%s state=waiting_slot → waiting_confirm",
        callback.from_user.id, time_str,
    )
    await state.update_data(booking_time=time_str)
    await state.set_state(BookingStates.waiting_confirm)

    data = await state.get_data()
    booking_date = date.fromisoformat(data["booking_date"])
    summary = (
        f"Проверьте данные записи:\n\n"
        f"🚗 Автомобиль: {data['car_brand']} {data['car_model']}\n"
        f"🔧 Услуга: {data['service']}\n"
        f"📅 Дата: {booking_date.strftime('%d.%m.%Y')}\n"
        f"⏰ Время: {time_str}"
    )
    await callback.message.edit_text(summary, reply_markup=confirm_kb())
    await callback.answer()


# ── Cancel button in confirm step ─────────────────────────────────────────

@router.callback_query(F.data == "cancel_booking_flow")
async def cancel_booking_flow(callback: CallbackQuery, state: FSMContext) -> None:
    logger.debug("cancel_booking_flow: user_id=%s", callback.from_user.id)
    await state.clear()
    await callback.message.edit_text("Запись отменена.")
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await callback.answer()


# ── Confirmation ───────────────────────────────────────────────────────────

@router.callback_query(BookingStates.waiting_confirm, F.data == "confirm_booking")
async def process_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    logger.debug("process_confirm: user_id=%s", callback.from_user.id)
    data = await state.get_data()

    telegram_id = callback.from_user.id
    user = await db.get_or_create_user(
        telegram_id,
        callback.from_user.username,
        callback.from_user.first_name or "Клиент",
    )

    booking_date = date.fromisoformat(data["booking_date"])
    booking_time = time.fromisoformat(data["booking_time"])

    try:
        booking = await booking_service.create_booking(
            user_id=user.id,
            car_brand=data["car_brand"],
            car_model=data["car_model"],
            service=data["service"],
            booking_date=booking_date,
            booking_time=booking_time,
        )
    except Exception:
        logger.error("process_confirm: booking creation failed:\n%s", traceback.format_exc())
        await callback.message.edit_text(
            "Произошла ошибка при создании записи. Попробуйте позже."
        )
        await state.clear()
        await callback.answer()
        return

    if booking is None:
        logger.warning(
            "process_confirm: slot taken for user_id=%s date=%s time=%s",
            user.id, data["booking_date"], data["booking_time"],
        )
        # Slot was taken — offer to pick another slot
        slots = await booking_service.get_available_slots(booking_date)
        if slots:
            await callback.message.edit_text(
                "Этот слот уже занят. Выберите другое время:",
                reply_markup=slots_kb(slots),
            )
            await state.set_state(BookingStates.waiting_slot)
        else:
            await callback.message.edit_text(
                "К сожалению, все слоты на эту дату заняты. Выберите другую дату:",
                reply_markup=dates_kb(booking_service.get_available_dates()),
            )
            await state.set_state(BookingStates.waiting_date)
        await callback.answer()
        return

    await state.clear()
    logger.info(
        "Booking confirmed: booking_id=%s user_id=%s service=%s date=%s time=%s",
        booking.id, user.id, booking.service, booking.booking_date, booking.booking_time,
    )

    confirm_text = (
        f"Запись подтверждена!\n\n"
        f"🚗 {booking.car_brand} {booking.car_model}\n"
        f"🔧 {booking.service}\n"
        f"📅 {date.fromisoformat(booking.booking_date).strftime('%d.%m.%Y')}\n"
        f"⏰ {booking.booking_time}\n\n"
        f"Ждём вас!"
    )
    await callback.message.edit_text(confirm_text)
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())

    # Notify admin
    try:
        admin_text = (
            f"Новая запись! {callback.from_user.first_name} "
            f"(@{callback.from_user.username or 'нет'}) — "
            f"{booking.car_brand} {booking.car_model} — "
            f"{booking.service} — "
            f"{date.fromisoformat(booking.booking_date).strftime('%d.%m')} "
            f"в {booking.booking_time}"
        )
        await callback.bot.send_message(chat_id=config.ADMIN_TELEGRAM_ID, text=admin_text)
    except Exception:
        logger.error("Failed to notify admin:\n%s", traceback.format_exc())

    await callback.answer()
