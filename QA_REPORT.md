# QA Bug Report — АвтоПлюс Telegram Bot

**Date:** 2026-03-20
**Reviewer:** QA Audit (static analysis of all Python source files)
**Scope:** `bot/` directory — all `.py` files

---

## Severity Legend

| Level | Meaning |
|---|---|
| CRITICAL | Data integrity loss, security breach, or booking system corruption |
| HIGH | Incorrect business logic, user-facing failures, exploitable misuse |
| MEDIUM | Degraded UX, stale data, edge-case crashes |
| LOW | Minor inconsistencies, code quality, non-blocking issues |

---

## CRITICAL

---

### BUG-001 · Race condition allows overbooking beyond `MAX_SLOTS_PER_HOUR`

**File:** `bot/services/booking_service.py:72–87`
**Also affected:** `bot/database/db.py:205–220`

**Description:**
`create_booking()` performs a check-then-insert in two separate `await` calls with no database transaction wrapping them. Between `get_slot_count` and `create_booking`, the Python event loop can yield to another coroutine running the identical path.

```python
# booking_service.py — NOT atomic
count = await db.get_slot_count(date_str, time_str)   # ← yields here
if count >= config.MAX_SLOTS_PER_HOUR:
    return None
booking = await db.create_booking(...)                 # ← another coroutine can run between these
```

**Scenario:** 5 users simultaneously confirm the last free slot in a 4-slot hour.
All 5 call `get_slot_count` → all see `count=3`. All pass the `>= 4` check. All call `create_booking`. Result: 5 bookings for a slot with a maximum of 4.

SQLite WAL mode does not protect against this because there is no `BEGIN EXCLUSIVE` or `INSERT ... WHERE (SELECT COUNT(*) ...) < max` guard. aiosqlite serializes individual SQL statements but the check and insert are two separate statements with an async gap between them.

**Fix required:** Wrap check + insert in a single SQL operation:
```sql
INSERT INTO bookings (...)
SELECT ?, ?, ?, ?, ?, ?
WHERE (SELECT COUNT(*) FROM bookings
       WHERE booking_date=? AND booking_time=?
       AND status != 'cancelled') < ?
```
Check `cursor.rowcount` to detect if the insert was blocked.

---

### BUG-002 · HTML injection via unescaped user-controlled input (ParseMode.HTML enabled globally)

**File:** `bot/main.py:64`, `bot/handlers/booking.py:154–159`, `bot/handlers/admin.py:78–86`, `bot/handlers/my_bookings.py:47–51`

**Description:**
`DefaultBotProperties(parse_mode=ParseMode.HTML)` is set globally. Every message sent by the bot is parsed as HTML. User-supplied data — `car_brand`, `car_model`, `first_name`, `username`, `cancel_reason` — is interpolated directly into f-strings without `html.escape()`.

```python
# booking.py — user-controlled car_brand and car_model go straight into HTML
summary = (
    f"🚗 Автомобиль: {data['car_brand']} {data['car_model']}\n"
    ...
)
await callback.message.edit_text(summary)
```

**Exploit scenarios:**
- Car brand `<b>HACKED</b>` → rendered as **HACKED** in all admin views.
- Car brand `<a href="https://phishing.example">Нажмите здесь</a>` → injects a hyperlink into admin messages.
- `first_name` or `cancel_reason` containing `</b><b>` can break message formatting.
- A carefully crafted string could trigger `TelegramBadRequest` (malformed HTML) and crash the handler, leaving the FSM in an uncleared state.

**All message sends that include user data are affected**, including admin booking notifications, confirmation messages, reminder texts, and cancellation notices.

**Fix required:** Wrap all user-supplied fields with `html.escape()` from the standard library before interpolating into any message string, or switch to `ParseMode.MARKDOWN_V2` with proper escaping.

---

## HIGH

---

### BUG-003 · `TIMEZONE` config is loaded but never used anywhere

**File:** `bot/config.py:32`, `bot/services/booking_service.py:18`, `bot/services/reminder_service.py:17`

**Description:**
`config.TIMEZONE = "Europe/Moscow"` is defined and logged at startup, but `date.today()` and `datetime.now()` are called without timezone awareness throughout the codebase. The server's local time zone is used instead.

- `booking_service.get_available_dates()` calls `date.today()` — server time.
- `reminder_service._send_reminders()` calls `date.today()` — server time.

**Impact:** If the server runs in UTC (common in Docker/cloud deployments) and the business is in Moscow (UTC+3):
- At 23:00 UTC (= 02:00 Moscow next day), `date.today()` returns the UTC date. The bot shows "bookings starting tomorrow" in UTC, which is already "day after tomorrow" in Moscow. Reminders fire at 00:00 UTC = 03:00 Moscow — in the middle of the night.
- A booking made by a Moscow user at "today" might actually land on the wrong date relative to the business calendar.

**Fix required:** Use `datetime.now(ZoneInfo(config.TIMEZONE)).date()` in place of all bare `date.today()` calls.

---

### BUG-004 · FSM state leak: `cancel_booking_flow` callback has no state guard

**File:** `bot/handlers/booking.py:167–173`

**Description:**
```python
@router.callback_query(F.data == "cancel_booking_flow")
async def cancel_booking_flow(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()   # clears ANY active state
```

This handler fires regardless of the user's current FSM state. If a user has an old booking confirmation message in their chat history (with the "❌ Отмена" button still active), clicking it at any future time — even while they are in the middle of a new booking flow — silently clears all their FSM state.

**Scenario:** User is at `waiting_slot` for a new booking and clicks "❌ Отмена" on an old message → their new booking state is wiped with no warning.

**Fix required:** Add `BookingStates.waiting_confirm` state filter, or check state before clearing:
```python
@router.callback_query(BookingStates.waiting_confirm, F.data == "cancel_booking_flow")
```

---

### BUG-005 · Admin stuck in `waiting_cancel_reason` — no escape path in the UI

**File:** `bot/handlers/admin.py:208–222`

**Description:**
When the admin clicks "Отменить" on a booking, the bot enters `AdminStates.waiting_cancel_reason`. The admin must now type a cancel reason. There is no inline "Abort" button and no admin-specific `/cancel` command handler. The only escape is the generic `/cancel` command from `booking.py`, which is not documented in the admin flow and may not be obvious.

While in `waiting_cancel_reason`, **any text the admin types** (including menu button presses like "Записи сегодня") is consumed as a cancellation reason and silently submitted. The admin will unknowingly cancel the booking with garbage reason text.

**Fix required:** Add an "Abort" inline button to the prompt message, or add an explicit `/cancel` handler for `AdminStates`.

---

### BUG-006 · Service name not validated against `config.SERVICES` whitelist

**File:** `bot/handlers/booking.py:91–98`

**Description:**
```python
@router.callback_query(BookingStates.waiting_service, F.data.startswith("service:"))
async def process_service(callback: CallbackQuery, state: FSMContext) -> None:
    service = callback.data.split(":", 1)[1]  # no validation
    await state.update_data(service=service)
```

A malicious user can craft a callback query with `service:ИнъекцияСервиса` (or any arbitrary string) and bypass the keyboard entirely. The unvalidated value is stored in FSM state and then written to the database.

Combined with BUG-002 (HTML injection), a crafted service name like `<b>anything</b>` would render in all admin views and admin notifications.

**Fix required:**
```python
if service not in config.SERVICES:
    await callback.answer("Неверный выбор.", show_alert=True)
    return
```

---

### BUG-007 · Date and time slot from callback data not validated

**File:** `bot/handlers/booking.py:113–114`, `bot/handlers/booking.py:144`

**Description:**
Both `process_date` and `process_slot` extract values from callback data and use them without validation:

```python
# process_date
date_str = callback.data.split(":", 1)[1]
booking_date = date.fromisoformat(date_str)   # ValueError if malformed

# process_slot
time_str = callback.data.split(":", 1)[1]
# time_str stored as-is; used later as:
booking_time = time.fromisoformat(data["booking_time"])  # ValueError if malformed
```

A replayed or crafted callback can supply:
- A past date (e.g., `date:2020-01-01`) — booking lands in the past, no check exists.
- A date far in the future (e.g., `date:2099-12-31`) — beyond `BOOKING_DAYS_AHEAD`.
- A time outside working hours (e.g., `slot:03:00`) — bypasses the slot availability display.
- Malformed values — uncaught `ValueError` crashes the handler, leaving FSM in `waiting_slot` or `waiting_date` indefinitely.

**Fix required:** Validate date is in `get_available_dates()` result; validate time is a valid working-hours slot; wrap `fromisoformat` calls in try/except.

---

### BUG-008 · No input length limit on car brand/model

**File:** `bot/handlers/booking.py:64–86`

**Description:**
```python
text = message.text.strip() if message.text else ""
parts = text.split(None, 1)
car_brand = parts[0]
car_model = parts[1]
```

No maximum length is enforced. A user can enter a car brand/model of arbitrary length (Telegram messages can be up to 4096 characters). This value is:
1. Stored in the SQLite database (no column length constraint).
2. Included verbatim in admin notification messages — a 4096-character car brand would cause `TelegramBadRequest: message is too long` in `booking.py:259–260` when notifying the admin, crashing that code path.
3. Displayed in all booking list views.

**Fix required:** Enforce a reasonable maximum (e.g., 50 characters each):
```python
if len(car_brand) > 50 or len(car_model) > 80:
    await message.answer("Слишком длинное название. Попробуйте ещё раз.")
    return
```

---

### BUG-009 · `config.WORKING_HOURS_START/END` has no validation

**File:** `bot/config.py:33–34`, `bot/services/booking_service.py:36–38`

**Description:**
The configuration accepts any integer values from environment variables. No validation ensures:
- `WORKING_HOURS_START < WORKING_HOURS_END`
- Both values are in range 0–23

If misconfigured (e.g., `WORKING_HOURS_START=18`, `WORKING_HOURS_END=9`), `range(18, 9)` produces an empty sequence. `get_available_slots()` returns an empty list for every date, silently making all dates appear fully booked. The bot would display "Нет свободных слотов" for every date with no error, no log warning, and no indication of misconfiguration.

**Fix required:** Add validation in `config.py`:
```python
if not (0 <= WORKING_HOURS_START < WORKING_HOURS_END <= 23):
    raise ValueError("Invalid WORKING_HOURS configuration")
```

---

## MEDIUM

---

### BUG-010 · Double "Статус:" lines after user cancellation

**File:** `bot/handlers/my_bookings.py:91–93`

**Description:**
When the user cancels a booking, the message is updated by appending to the existing text:
```python
await callback.message.edit_text(
    callback.message.text + "\nСтатус: Отменена"
)
```
The original message already contains `Статус: Ожидает` or `Статус: Подтверждена`. The resulting message displays two status lines:
```
...
Статус: Ожидает
Статус: Отменена
```

**Fix required:** Replace the existing status line rather than appending.

---

### BUG-011 · Admin can confirm/complete an already-cancelled or completed booking

**File:** `bot/handlers/admin.py:143–172` (`admin_confirm_booking`), `bot/handlers/admin.py:175–205` (`admin_complete_booking`)

**Description:**
Neither `admin_confirm_booking` nor `admin_complete_booking` checks the current booking status before updating it. An admin can:
- Confirm a `cancelled` booking → status becomes `confirmed`, the slot is re-occupied but the user already received a "cancelled" notification.
- Mark a `cancelled` booking as `completed` → data integrity violation.
- Re-confirm an already `confirmed` booking → fires a duplicate notification to the user.

The user-facing `cancel_booking` in `booking_service.py` does correctly guard against invalid status transitions, but the admin direct path (`db.update_booking_status`) has no such guard.

**Fix required:** Add status transition checks in admin handlers before calling `update_booking_status`.

---

### BUG-012 · `get_or_create_user` returns stale user object after name update

**File:** `bot/database/db.py:107–117`

**Description:**
When an existing user is found, their `username` and `first_name` are updated in the DB, but the function returns the `user` object built from the pre-update SELECT row — containing the **old** username/first_name:

```python
if row:
    user = _row_to_user(row)          # ← built from old data
    await conn.execute("UPDATE users SET username=?, first_name=? ...", ...)
    await conn.commit()
    return user                        # ← returns old data
```

Any code relying on the returned `user.first_name` within the same request will use the stale value. For example, admin notifications that fetch user data via `get_user_by_id` in the same request cycle could display the old name.

---

### BUG-013 · No per-user booking limit enables slot flooding

**File:** `bot/handlers/booking.py` (missing validation), `bot/services/booking_service.py`

**Description:**
There is no limit on how many active (pending/confirmed) bookings a single user can hold. A malicious or bot-driven user can create `MAX_SLOTS_PER_HOUR × WORKING_HOURS × BOOKING_DAYS_AHEAD` bookings = 4 × 9 × 14 = 504 simultaneous bookings, completely filling the entire schedule for 14 days.

**Fix required:** Enforce a maximum of, e.g., 3–5 active bookings per user before allowing a new booking.

---

### BUG-014 · Unhandled `ValueError` on malformed `booking_date` in `my_bookings.py`

**File:** `bot/handlers/my_bookings.py:46`

**Description:**
```python
booking_date_obj = date.fromisoformat(booking.booking_date)
```
If `booking_date` in the database contains a malformed value (e.g., due to a data migration or manual DB edit), this raises `ValueError` and crashes the entire `show_my_bookings` handler mid-loop. The user receives no message for bookings processed after the corrupt one, and the FSM is not affected but the user sees a broken experience.

---

### BUG-015 · `time.fromisoformat` fails for `HH:MM` format in Python < 3.11

**File:** `bot/handlers/booking.py:191`

**Description:**
```python
booking_time = time.fromisoformat(data["booking_time"])
```
`data["booking_time"]` is a string like `"09:00"`. In Python 3.10 and earlier, `time.fromisoformat()` only accepts `HH:MM:SS` or `HH:MM:SS.ffffff`. It does NOT accept `HH:MM` alone, raising `ValueError: Invalid isoformat string: '09:00'`.

In Python 3.11+, `HH:MM` is accepted. If the deployment uses Python 3.10 (common in older Docker images), every booking confirmation crashes.

**Fix required:** Use `datetime.strptime(data["booking_time"], "%H:%M").time()` for guaranteed compatibility.

---

### BUG-016 · Reminder sent but `mark_reminder_sent` fails → duplicate reminders

**File:** `bot/services/reminder_service.py:38–39`

**Description:**
```python
await bot.send_message(chat_id=user.telegram_id, text=text)
await db.mark_reminder_sent(booking.id)
```
If `mark_reminder_sent` raises an exception after the message was sent successfully, the booking's `reminder_sent` flag remains `0`. The scheduler runs again the next hour and sends a second reminder. This will repeat every hour until the booking date passes.

**Fix required:** Move `mark_reminder_sent` inside the try/except block and log failures, or perform the DB update first and rollback if the Telegram send fails (though the latter is complex). At minimum, the scheduler should catch and log the failure so an operator is notified.

---

### BUG-017 · `_was_existing` heuristic in `start.py` is unreliable

**File:** `bot/handlers/start.py:27`, `bot/handlers/start.py:44–48`

**Description:**
```python
if user.telegram_id == telegram_id and not _was_existing(user):
    logger.info("New user registered: ...")
```
`user.telegram_id == telegram_id` is always `True` (the user was fetched by this exact `telegram_id`), making this condition redundant.

`_was_existing` compares `user.created_at` (from SQLite `datetime('now')` = UTC) with `datetime.now(timezone.utc).replace(tzinfo=None)`. If there is any clock skew between the SQLite process and Python, or if the commit+re-select adds latency, `abs(delta) > 1` may incorrectly classify a newly-created user as existing (log missed). This function also strips timezone info inconsistently.

The log is the only side effect, so this is not a data-integrity bug, but the misleading logic should be cleaned up.

---

## LOW

---

### BUG-018 · `MemoryStorage` loses all FSM state on bot restart

**File:** `bot/main.py:66`

**Description:**
`dp = Dispatcher(storage=MemoryStorage())` stores all FSM state in RAM. On bot restart (deploy, crash, OOM kill), every user currently in a booking flow loses their state silently. Clicking "Подтвердить" on an open confirmation message after restart will not match any FSM state filter and be silently ignored by the framework (unless a fallback handler exists).

**Impact:** Low in development, higher in production where users may be mid-booking during a deploy.

**Fix required (for production):** Use `RedisStorage` or `aiosqlite`-backed FSM storage.

---

### BUG-019 · `_STATUS_RU` dictionary defined in 3 separate files

**Files:** `bot/handlers/admin.py:20–25`, `bot/handlers/my_bookings.py:18–23`, `bot/services/stats_service.py:8–13`

**Description:**
Identical `_STATUS_RU` mapping is copy-pasted into three modules. If a new booking status is added (e.g., `"no_show"`), all three copies must be updated independently. `bot/utils/helpers.py` already contains `status_to_russian()` which performs the same lookup.

**Fix required:** Remove the local dictionaries and call `helpers.status_to_russian()` throughout.

---

### BUG-020 · Admin `choose_date` only shows future bookable dates, not past dates

**File:** `bot/handlers/admin.py:112–114`

**Description:**
`booking_service.get_available_dates()` returns only the next 14 working days. The admin date picker is built from this same list, so there is no UI path for an admin to view bookings from yesterday or last week. The "Записи сегодня / завтра" buttons exist, but anything older is inaccessible through the bot interface. This is a missing feature rather than a bug, but it means past data can only be recovered directly from the database.

---

### BUG-021 · `loop.stop()` in signal handler may interrupt active DB commits

**File:** `bot/main.py:89`

**Description:**
```python
def _shutdown(sig_name: str) -> None:
    scheduler.shutdown(wait=False)
    loop.stop()
```
`loop.stop()` halts the event loop immediately on the next iteration. Any pending `await conn.commit()` calls in flight (e.g., mid-transaction on an active booking) may not complete. SQLite WAL mode provides crash recovery, so data will not be corrupted, but in-flight operations will silently fail without notifying the user.

The `finally` block in `main()` calls `scheduler.shutdown(wait=False)` again (harmless) and `await bot.session.close()` (which would not run after `loop.stop()` since the loop is stopped). This means the HTTP session to Telegram API is not closed cleanly.

---

### BUG-022 · Logging level set to DEBUG globally in production

**File:** `bot/main.py:21`

**Description:**
```python
logging.basicConfig(level=logging.DEBUG, ...)
```
All `logger.debug(...)` calls — including those that log `booking_date`, `booking_time`, `telegram_id`, `first_name`, `username`, and `cancel_reason` — are emitted to stdout in production. This exposes personally identifiable information (PII) in logs. There is no log rotation or filtering.

**Fix required:** Use `logging.INFO` as the default level and make it configurable via environment variable (e.g., `LOG_LEVEL=DEBUG`).

---

## Summary Table

| ID | Severity | File | Description |
|---|---|---|---|
| BUG-001 | CRITICAL | `services/booking_service.py:72` | TOCTOU race condition allows overbooking |
| BUG-002 | CRITICAL | `handlers/booking.py`, `admin.py`, `my_bookings.py` | HTML injection via unescaped user input |
| BUG-003 | HIGH | `services/booking_service.py`, `services/reminder_service.py` | `TIMEZONE` config ignored; uses server local time |
| BUG-004 | HIGH | `handlers/booking.py:167` | `cancel_booking_flow` clears any FSM state, no state guard |
| BUG-005 | HIGH | `handlers/admin.py:208` | Admin stuck in `waiting_cancel_reason` with no abort UI |
| BUG-006 | HIGH | `handlers/booking.py:92` | Service name not validated against whitelist |
| BUG-007 | HIGH | `handlers/booking.py:113,144` | Date/time from callback unvalidated; past dates accepted; ValueError on malformed |
| BUG-008 | HIGH | `handlers/booking.py:66` | No car brand/model length limit; crashes admin notification |
| BUG-009 | HIGH | `config.py:33` | Working hours not validated; silent zero-slot configuration |
| BUG-010 | MEDIUM | `handlers/my_bookings.py:91` | Double `Статус:` line after cancellation |
| BUG-011 | MEDIUM | `handlers/admin.py:143,175` | Admin can confirm/complete cancelled bookings |
| BUG-012 | MEDIUM | `database/db.py:107` | `get_or_create_user` returns stale name after update |
| BUG-013 | MEDIUM | `services/booking_service.py` | No per-user booking limit; entire schedule can be flooded |
| BUG-014 | MEDIUM | `handlers/my_bookings.py:46` | Unhandled `ValueError` on malformed DB date |
| BUG-015 | MEDIUM | `handlers/booking.py:191` | `time.fromisoformat("HH:MM")` fails on Python ≤ 3.10 |
| BUG-016 | MEDIUM | `services/reminder_service.py:38` | `mark_reminder_sent` failure causes duplicate reminders |
| BUG-017 | MEDIUM | `handlers/start.py:27,44` | `_was_existing` heuristic always true; fragile UTC comparison |
| BUG-018 | LOW | `main.py:66` | `MemoryStorage` loses FSM state on restart |
| BUG-019 | LOW | `admin.py`, `my_bookings.py`, `stats_service.py` | `_STATUS_RU` duplicated in 3 files |
| BUG-020 | LOW | `handlers/admin.py:112` | Admin cannot view past dates in date picker |
| BUG-021 | LOW | `main.py:89` | `loop.stop()` may interrupt in-flight DB commits |
| BUG-022 | LOW | `main.py:21` | DEBUG logging exposes PII in production |

---

**Total:** 2 CRITICAL · 7 HIGH · 8 MEDIUM · 5 LOW = **22 issues**
