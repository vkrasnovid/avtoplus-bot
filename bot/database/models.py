from dataclasses import dataclass, field
from datetime import datetime

# Booking status constants
PENDING = "pending"
CONFIRMED = "confirmed"
COMPLETED = "completed"
CANCELLED = "cancelled"


@dataclass
class User:
    id: int
    telegram_id: int
    username: str | None
    first_name: str
    phone: str | None
    created_at: datetime


@dataclass
class Booking:
    id: int
    user_id: int
    car_brand: str
    car_model: str
    service: str
    booking_date: str   # stored as ISO date string "YYYY-MM-DD"
    booking_time: str   # stored as "HH:MM"
    status: str
    created_at: datetime
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    reminder_sent: bool = False
