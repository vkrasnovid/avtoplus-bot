import logging
import traceback
from datetime import date, datetime
from typing import Optional

import aiosqlite

from bot.database.models import Booking, PENDING, CONFIRMED, User

logger = logging.getLogger(__name__)

DB_PATH = "data/avtoplus.db"

_connection: Optional[aiosqlite.Connection] = None


async def get_connection() -> aiosqlite.Connection:
    global _connection
    if _connection is None:
        logger.debug("Opening database connection: path=%s", DB_PATH)
        _connection = await aiosqlite.connect(DB_PATH)
        _connection.row_factory = aiosqlite.Row
        await _connection.execute("PRAGMA journal_mode=WAL")
        await _connection.execute("PRAGMA foreign_keys=ON")
        logger.debug("Database connection opened, WAL mode enabled")
    return _connection


async def init_db() -> None:
    logger.debug("Initializing database schema")
    conn = await get_connection()
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username    TEXT,
                first_name  TEXT NOT NULL,
                phone       TEXT,
                created_at  DATETIME NOT NULL DEFAULT (datetime('now'))
            )
        """)
        logger.debug("SQL: CREATE TABLE IF NOT EXISTS users")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL REFERENCES users(id),
                car_brand     TEXT NOT NULL,
                car_model     TEXT NOT NULL,
                service       TEXT NOT NULL,
                booking_date  DATE NOT NULL,
                booking_time  TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'pending',
                created_at    DATETIME NOT NULL DEFAULT (datetime('now')),
                cancelled_at  DATETIME,
                cancel_reason TEXT,
                reminder_sent INTEGER NOT NULL DEFAULT 0
            )
        """)
        logger.debug("SQL: CREATE TABLE IF NOT EXISTS bookings")

        await conn.commit()
        logger.info("Database schema initialized successfully")
    except Exception:
        logger.error("Failed to initialize database schema:\n%s", traceback.format_exc())
        raise


def _row_to_user(row: aiosqlite.Row) -> User:
    return User(
        id=row["id"],
        telegram_id=row["telegram_id"],
        username=row["username"],
        first_name=row["first_name"],
        phone=row["phone"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _row_to_booking(row: aiosqlite.Row) -> Booking:
    return Booking(
        id=row["id"],
        user_id=row["user_id"],
        car_brand=row["car_brand"],
        car_model=row["car_model"],
        service=row["service"],
        booking_date=row["booking_date"],
        booking_time=row["booking_time"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        cancelled_at=datetime.fromisoformat(row["cancelled_at"]) if row["cancelled_at"] else None,
        cancel_reason=row["cancel_reason"],
        reminder_sent=bool(row["reminder_sent"]),
    )


async def get_or_create_user(telegram_id: int, username: str | None, first_name: str) -> User:
    logger.debug("SQL: get_or_create_user telegram_id=%s username=%s", telegram_id, username)
    conn = await get_connection()
    try:
        async with conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            user = _row_to_user(row)
            logger.debug("User found: id=%s telegram_id=%s", user.id, telegram_id)
            # Update username/first_name in case they changed
            await conn.execute(
                "UPDATE users SET username=?, first_name=? WHERE telegram_id=?",
                (username, first_name, telegram_id),
            )
            logger.debug("SQL: UPDATE users telegram_id=%s", telegram_id)
            await conn.commit()
            return user

        logger.debug("SQL: INSERT INTO users telegram_id=%s", telegram_id)
        async with conn.execute(
            "INSERT INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)",
            (telegram_id, username, first_name),
        ) as cursor:
            user_id = cursor.lastrowid

        await conn.commit()
        logger.info("New user created: id=%s telegram_id=%s", user_id, telegram_id)

        async with conn.execute("SELECT * FROM users WHERE id=?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        return _row_to_user(row)
    except Exception:
        logger.error("get_or_create_user failed:\n%s", traceback.format_exc())
        raise


async def create_booking(
    user_id: int,
    car_brand: str,
    car_model: str,
    service: str,
    booking_date: str,
    booking_time: str,
) -> Booking:
    logger.debug(
        "SQL: create_booking user_id=%s car=%s %s service=%s date=%s time=%s",
        user_id, car_brand, car_model, service, booking_date, booking_time,
    )
    conn = await get_connection()
    try:
        async with conn.execute(
            "INSERT INTO bookings (user_id, car_brand, car_model, service, booking_date, booking_time) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, car_brand, car_model, service, booking_date, booking_time),
        ) as cursor:
            booking_id = cursor.lastrowid

        await conn.commit()
        logger.info("Booking created: booking_id=%s user_id=%s service=%s date=%s time=%s",
                    booking_id, user_id, service, booking_date, booking_time)

        async with conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)) as cursor:
            row = await cursor.fetchone()
        return _row_to_booking(row)
    except Exception:
        logger.error("create_booking failed:\n%s", traceback.format_exc())
        raise


async def get_user_bookings(user_id: int) -> list[Booking]:
    logger.debug("SQL: get_user_bookings user_id=%s", user_id)
    conn = await get_connection()
    try:
        async with conn.execute(
            "SELECT * FROM bookings WHERE user_id=? ORDER BY booking_date DESC, booking_time DESC",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        bookings = [_row_to_booking(r) for r in rows]
        logger.debug("get_user_bookings user_id=%s count=%d", user_id, len(bookings))
        return bookings
    except Exception:
        logger.error("get_user_bookings failed:\n%s", traceback.format_exc())
        raise


async def get_bookings_by_date(booking_date: date) -> list[Booking]:
    date_str = booking_date.isoformat()
    logger.debug("SQL: get_bookings_by_date date=%s", date_str)
    conn = await get_connection()
    try:
        async with conn.execute(
            "SELECT * FROM bookings WHERE booking_date=? ORDER BY booking_time",
            (date_str,),
        ) as cursor:
            rows = await cursor.fetchall()
        bookings = [_row_to_booking(r) for r in rows]
        logger.debug("get_bookings_by_date date=%s count=%d", date_str, len(bookings))
        return bookings
    except Exception:
        logger.error("get_bookings_by_date failed:\n%s", traceback.format_exc())
        raise


async def get_slot_count(booking_date: str, booking_time: str) -> int:
    logger.debug("SQL: get_slot_count date=%s time=%s", booking_date, booking_time)
    conn = await get_connection()
    try:
        async with conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE booking_date=? AND booking_time=? "
            "AND status NOT IN ('cancelled')",
            (booking_date, booking_time),
        ) as cursor:
            row = await cursor.fetchone()
        count = row[0] if row else 0
        logger.debug("get_slot_count date=%s time=%s count=%d", booking_date, booking_time, count)
        return count
    except Exception:
        logger.error("get_slot_count failed:\n%s", traceback.format_exc())
        raise


async def update_booking_status(
    booking_id: int,
    status: str,
    cancel_reason: str | None = None,
) -> bool:
    logger.debug("SQL: update_booking_status booking_id=%s status=%s", booking_id, status)
    conn = await get_connection()
    try:
        if status == "cancelled":
            async with conn.execute(
                "UPDATE bookings SET status=?, cancelled_at=datetime('now'), cancel_reason=? WHERE id=?",
                (status, cancel_reason, booking_id),
            ) as cursor:
                updated = cursor.rowcount
        else:
            async with conn.execute(
                "UPDATE bookings SET status=? WHERE id=?",
                (status, booking_id),
            ) as cursor:
                updated = cursor.rowcount

        await conn.commit()
        success = updated > 0
        if success:
            logger.info("Booking status updated: booking_id=%s new_status=%s", booking_id, status)
        else:
            logger.warning("update_booking_status: booking_id=%s not found", booking_id)
        return success
    except Exception:
        logger.error("update_booking_status failed:\n%s", traceback.format_exc())
        raise


async def get_booking_by_id(booking_id: int) -> Booking | None:
    logger.debug("SQL: get_booking_by_id booking_id=%s", booking_id)
    conn = await get_connection()
    try:
        async with conn.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            logger.debug("get_booking_by_id: not found booking_id=%s", booking_id)
            return None
        return _row_to_booking(row)
    except Exception:
        logger.error("get_booking_by_id failed:\n%s", traceback.format_exc())
        raise


async def get_pending_reminders(target_date: date) -> list[Booking]:
    date_str = target_date.isoformat()
    logger.debug("SQL: get_pending_reminders target_date=%s", date_str)
    conn = await get_connection()
    try:
        async with conn.execute(
            "SELECT * FROM bookings WHERE booking_date=? AND status IN (?, ?) AND reminder_sent=0",
            (date_str, PENDING, CONFIRMED),
        ) as cursor:
            rows = await cursor.fetchall()
        bookings = [_row_to_booking(r) for r in rows]
        logger.debug("get_pending_reminders date=%s count=%d", date_str, len(bookings))
        return bookings
    except Exception:
        logger.error("get_pending_reminders failed:\n%s", traceback.format_exc())
        raise


async def mark_reminder_sent(booking_id: int) -> None:
    logger.debug("SQL: mark_reminder_sent booking_id=%s", booking_id)
    conn = await get_connection()
    try:
        await conn.execute(
            "UPDATE bookings SET reminder_sent=1 WHERE id=?", (booking_id,)
        )
        await conn.commit()
        logger.debug("mark_reminder_sent: booking_id=%s done", booking_id)
    except Exception:
        logger.error("mark_reminder_sent failed:\n%s", traceback.format_exc())
        raise


async def get_stats_by_period(start_date: date, end_date: date) -> dict:
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()
    logger.debug("SQL: get_stats_by_period start=%s end=%s", start_str, end_str)
    conn = await get_connection()
    try:
        async with conn.execute(
            "SELECT status, COUNT(*) as cnt FROM bookings "
            "WHERE booking_date >= ? AND booking_date <= ? "
            "GROUP BY status",
            (start_str, end_str),
        ) as cursor:
            rows = await cursor.fetchall()
        result = {row["status"]: row["cnt"] for row in rows}
        logger.debug("get_stats_by_period start=%s end=%s result=%s", start_str, end_str, result)
        return result
    except Exception:
        logger.error("get_stats_by_period failed:\n%s", traceback.format_exc())
        raise


async def get_popular_services_from_db(limit: int = 5) -> list[tuple[str, int]]:
    logger.debug("SQL: get_popular_services_from_db limit=%d", limit)
    conn = await get_connection()
    try:
        async with conn.execute(
            "SELECT service, COUNT(*) as cnt FROM bookings "
            "GROUP BY service ORDER BY cnt DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        result = [(row["service"], row["cnt"]) for row in rows]
        logger.debug("get_popular_services_from_db result=%s", result)
        return result
    except Exception:
        logger.error("get_popular_services_from_db failed:\n%s", traceback.format_exc())
        raise


async def get_cancellation_rate_from_db() -> float:
    logger.debug("SQL: get_cancellation_rate_from_db")
    conn = await get_connection()
    try:
        async with conn.execute("SELECT COUNT(*) as total FROM bookings") as cursor:
            total_row = await cursor.fetchone()
        total = total_row["total"] if total_row else 0

        if total == 0:
            logger.debug("get_cancellation_rate_from_db: no bookings, rate=0.0")
            return 0.0

        async with conn.execute(
            "SELECT COUNT(*) as cnt FROM bookings WHERE status='cancelled'"
        ) as cursor:
            cancelled_row = await cursor.fetchone()
        cancelled = cancelled_row["cnt"] if cancelled_row else 0

        rate = cancelled / total * 100
        logger.debug("get_cancellation_rate_from_db: total=%d cancelled=%d rate=%.2f%%",
                     total, cancelled, rate)
        return rate
    except Exception:
        logger.error("get_cancellation_rate_from_db failed:\n%s", traceback.format_exc())
        raise


async def get_user_by_id(user_id: int) -> User | None:
    """Helper to fetch user by internal id (needed for admin notifications)."""
    logger.debug("SQL: get_user_by_id user_id=%s", user_id)
    conn = await get_connection()
    try:
        async with conn.execute("SELECT * FROM users WHERE id=?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_user(row)
    except Exception:
        logger.error("get_user_by_id failed:\n%s", traceback.format_exc())
        raise
