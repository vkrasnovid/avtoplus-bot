# Code Review — AutoPlus Telegram Bot

**Reviewer:** Claude Sonnet 4.6
**Date:** 2026-03-20
**Scope:** All Python files in `bot/`, `Dockerfile`, `docker-compose.yml`, `.env` handling
**Verdict:** ❌ **REJECT**

---

## Summary

The codebase is structurally sound — layering is clean, FSM flows are well-designed, SQL uses parameterized queries throughout, and async patterns are consistent. However there is one **critical security breach** (live credentials in git) and several meaningful bugs that prevent approval.

---

## CRITICAL — Must Fix Before Anything Else

### SEC-1 · Real bot token committed to git
**File:** `.env` (tracked)
**Severity:** CRITICAL

`git ls-files .env` confirms `.env` is committed. It contains a live bot token and admin Telegram ID:

```
BOT_TOKEN=8732056783:AAFVKhQl3WB6XJ3j8d4MoChE6rhx9p9AwCE
ADMIN_TELEGRAM_ID=210706056
```

**Action required immediately:**
1. Revoke the token at https://t.me/BotFather right now.
2. Remove `.env` from tracking: `git rm --cached .env`
3. Add `.env` to `.gitignore` (no `.gitignore` exists at all — see DOCKER-3).
4. Rotate any API keys or secrets exposed in git history.

There is no `.gitignore` in the repository. The `.dockerignore` correctly excludes `.env`, but that does not help with git.

---

## HIGH — Bugs / Security

### SEC-2 · Unvalidated service in callback data
**File:** `bot/handlers/booking.py:93`

```python
service = callback.data.split(":", 1)[1]
await state.update_data(service=service)
```

The service value comes from client-controlled callback data and is stored as-is in FSM state and later persisted to the database. Although aiogram does not sign inline keyboard callback data, a crafted Telegram client can send arbitrary `service:` payloads. The service should be validated against `config.SERVICES`:

```python
service = callback.data.split(":", 1)[1]
if service not in config.SERVICES:
    await callback.answer("Неверная услуга.", show_alert=True)
    return
```

### SEC-3 · Integer cast from callback data without guard
**Files:** `bot/handlers/admin.py:147,180,213`, `bot/handlers/my_bookings.py:61`

```python
booking_id = int(callback.data.split(":", 1)[1])
```

If the split produces a non-integer string, this raises an unhandled `ValueError` that propagates up and causes an unhandled exception (aiogram will silently drop the update after logging). Wrap in `try/except ValueError`.

### BUG-1 · Race condition in slot booking — claimed atomic, is not
**File:** `bot/services/booking_service.py:72-87`

```python
count = await db.get_slot_count(date_str, time_str)   # READ
if count >= config.MAX_SLOTS_PER_HOUR:
    return None
booking = await db.create_booking(...)                  # WRITE
```

The comment on the function says `"atomic"` but there is no transaction wrapping the check and the insert. Two concurrent coroutines can both pass the count check and both insert, causing a slot to exceed `MAX_SLOTS_PER_HOUR`. With a single-connection aiosqlite setup this race window is small but not zero (event loop yields between awaits).

Fix: wrap both operations in a single `BEGIN IMMEDIATE` transaction, or add a `CHECK` constraint at the database level, or use `INSERT ... WHERE (SELECT COUNT(*) ...) < max` as a single atomic statement.

### BUG-2 · Admin cancel does not validate booking state
**File:** `bot/handlers/admin.py:249`

`db.update_booking_status(booking_id, CANCELLED, cancel_reason=reason)` is called without checking whether the booking is already cancelled or completed. The client-facing `cancel_booking` in `booking_service.py:120` does this check, but the admin path bypasses the service layer and calls `db` directly. An admin can cancel an already-completed booking, corrupting stats.

### BUG-3 · Admin confirm/complete do not check current status
**File:** `bot/handlers/admin.py:150-162, 183-194`

A completed booking can be re-confirmed or re-completed. There is no guard like `if booking.status == COMPLETED: callback.answer("Уже завершена"); return`. This can cause duplicate client notifications and incorrect status history.

---

## MEDIUM — Code Quality / Architecture

### ARCH-1 · `_STATUS_RU` dict duplicated four times

Defined identically in:
- `bot/handlers/admin.py:20`
- `bot/handlers/my_bookings.py:18`
- `bot/services/stats_service.py:8`
- `bot/utils/helpers.py:5`

`utils/helpers.py` already exports `status_to_russian()`. The three other locations should import and use that function instead of maintaining their own copies.

### ARCH-2 · `LoggingMiddleware` defined inside `main.py`
**File:** `bot/main.py:37-47`

Middleware belongs in its own module (e.g. `bot/middleware.py`). Mixing class definitions with application startup logic in `main.py` violates single-responsibility.

### ARCH-3 · Admin handlers bypass service layer
**Files:** `bot/handlers/admin.py:156, 189, 249`

`admin.py` calls `db.update_booking_status()` directly, skipping business-rule validation in `booking_service.cancel_booking()`. All status transitions should go through the service layer.

### ARCH-4 · `get_available_dates()` belongs in service, called without timezone
**File:** `bot/services/booking_service.py:18`

`date.today()` uses the system timezone, not `config.TIMEZONE`. If the server runs in UTC and the service is in `Europe/Moscow`, bookings near midnight will use the wrong date. Use `datetime.now(ZoneInfo(config.TIMEZONE)).date()` instead.

The same issue affects `stats_service.py:26,35,44` and `reminder_service.py:17`.

### QUAL-1 · Import ordering violation in `main.py`
**File:** `bot/main.py:32-34`

```python
# Line 20: logging.basicConfig(...)
# Line 32: from aiogram import BaseMiddleware  ← import after code
```

Imports must appear at the top of the module per PEP 8 E402. Move all imports before `logging.basicConfig`.

### QUAL-2 · Unused import in `models.py`
**File:** `bot/database/models.py:1`

```python
from dataclasses import dataclass, field  # `field` is never used
```

Remove `field`.

### QUAL-3 · Mixed typing style
**File:** `bot/database/db.py:4,14`

```python
from typing import Optional          # old style (line 4)
_connection: Optional[...] = None   # old style (line 14)
```

Elsewhere the codebase uses `X | None` (Python 3.10+ style). Pick one style. Given the `python:3.11-slim` base image, prefer `X | None` throughout and drop the `typing` import.

### QUAL-4 · Redundant `_from_db` suffix on db functions
**File:** `bot/database/db.py:324, 342`

`get_popular_services_from_db` and `get_cancellation_rate_from_db` are already inside the `db` module. The `_from_db` suffix is redundant and not consistent with the rest of the module's naming (`get_slot_count`, `get_booking_by_id`, etc.).

### QUAL-5 · Fragile `_was_existing()` heuristic
**File:** `bot/handlers/start.py:44-48`

```python
delta = datetime.now(timezone.utc).replace(tzinfo=None) - user.created_at.replace(tzinfo=None)
return abs(delta.total_seconds()) > 1
```

This strips timezone info and compares assuming both sides are UTC — valid today because SQLite stores UTC and the server returns UTC, but it is fragile. The 1-second threshold is also arbitrary and will misfire on slow DB inserts. This function is only used for a debug log (`logger.info("New user registered...")`) and should be removed or replaced with tracking a `just_created: bool` return value from `get_or_create_user`.

### QUAL-6 · Module-level `logger.debug()` before logging is configured
**File:** `bot/config.py:50-60`

`config` is imported at the top of `main.py`, which means `logger.debug(...)` at module scope in `config.py` executes before `logging.basicConfig()` is called. At that point the root logger has no handlers, so the message is silently dropped (Python's `lastResort` handler only fires for WARNING+). Move the config debug log into a function or after `basicConfig`.

---

## LOW — Minor Issues

### LOW-1 · `asyncio.get_event_loop()` deprecated
**File:** `bot/main.py:84`

```python
loop = asyncio.get_event_loop()
```

`get_event_loop()` is deprecated inside a running async context in Python 3.10+. Use `asyncio.get_running_loop()` inside `async def main()`.

### LOW-2 · APScheduler has no timezone configured
**File:** `bot/services/reminder_service.py:62`

```python
scheduler = AsyncIOScheduler()
```

Without a `timezone` argument, APScheduler defaults to UTC. The cron job fires at `minute=0` (every hour) which is timezone-independent, but if the job logic ever references local time it will use UTC. For correctness and explicitness, pass `timezone=config.TIMEZONE`.

### LOW-3 · No `.gitignore`

There is a `.dockerignore` that excludes `.env`, but no `.gitignore`. At minimum, `.env`, `data/`, and `**/__pycache__/` should be listed.

### LOW-4 · Dockerfile stage name is misleading
**File:** `Dockerfile:1`

```dockerfile
FROM python:3.11-slim AS base
```

The `AS base` alias implies a multi-stage build but there is only one stage. Either add a proper second production stage or remove the alias.

### LOW-5 · Dockerfile runs as root
**File:** `Dockerfile`

No `USER` instruction is present; the container runs as root. Add a non-root user:

```dockerfile
RUN adduser --disabled-password --gecos "" appuser
USER appuser
```

### LOW-6 · No Docker health check
**File:** `docker-compose.yml`

No `healthcheck` is defined. A simple poll to check if the bot is alive (e.g. check the PID or call getMe) would allow `restart: unless-stopped` to actually detect a hung process.

### LOW-7 · DB path is relative
**File:** `bot/database/db.py:12`

```python
DB_PATH = "data/avtoplus.db"
```

This path is relative to the current working directory at runtime. It works because Docker sets `WORKDIR /app` and the volume mounts at `/app/data`. If the bot is ever run locally from a different directory, it will create a database in the wrong place or fail silently. Use an absolute path or derive it from `__file__` or an env var.

### LOW-8 · No input length validation on car brand/model
**File:** `bot/handlers/booking.py:71-80`

The only validation is that the input has 2+ words. A user can send a 50,000-character string. Add a max-length check (e.g. 100 characters total) and a non-empty check after stripping.

### LOW-9 · Admin receives no response when guard silently rejects
**File:** `bot/handlers/admin.py:93-94, 99-103, 109-110, 132-134`

When `_guard_message()` returns `False`, the handler returns without sending any message to the user. From the user's perspective nothing happens. This is intentional (security through silence) but inconsistent — callback guards do send `"Нет доступа."`. Consider at least logging a warning (already done) and deciding on a consistent policy.

### LOW-10 · `my_bookings.py:91-92` — appending to existing text is fragile
**File:** `bot/handlers/my_bookings.py:91-92`

```python
await callback.message.edit_text(
    callback.message.text + "\nСтатус: Отменена"
)
```

If the message contains formatting or the status line is already present (e.g. after a previous cancellation attempt), this will double-append. Build the new text from the booking data instead.

---

## Positive Observations

- Parameterized queries everywhere — no SQL injection risk.
- Ownership check in `booking_service.cancel_booking()` prevents IDOR for client cancellations.
- `TelegramForbiddenError` caught explicitly in reminder service.
- WAL mode and foreign keys enabled at connection setup.
- FSM state validation (handlers fire only in the correct state) prevents step-skipping attacks.
- Consistent structured logging with contextual fields throughout.
- Clean separation: handlers → services → db, with models as plain dataclasses.

---

## Issue Summary Table

| ID | Severity | File | Description |
|----|----------|------|-------------|
| SEC-1 | CRITICAL | `.env` | Live credentials committed to git |
| SEC-2 | HIGH | `handlers/booking.py:93` | Unvalidated service from callback data |
| SEC-3 | HIGH | `handlers/admin.py:147,180,213`, `handlers/my_bookings.py:61` | Integer cast from callback data without try/except |
| BUG-1 | HIGH | `services/booking_service.py:72-87` | Non-atomic slot availability check |
| BUG-2 | HIGH | `handlers/admin.py:249` | Admin cancel skips status validation |
| BUG-3 | HIGH | `handlers/admin.py:156,189` | Admin confirm/complete allow invalid state transitions |
| ARCH-1 | MEDIUM | multiple | `_STATUS_RU` duplicated in 4 files |
| ARCH-2 | MEDIUM | `main.py:37` | Middleware class in main.py |
| ARCH-3 | MEDIUM | `handlers/admin.py` | Admin bypasses service layer for status updates |
| ARCH-4 | MEDIUM | `services/booking_service.py:18` | `date.today()` ignores configured timezone |
| QUAL-1 | MEDIUM | `main.py:32-34` | PEP 8 import ordering |
| QUAL-2 | LOW | `database/models.py:1` | Unused `field` import |
| QUAL-3 | LOW | `database/db.py` | Mixed `Optional` vs `X \| None` typing style |
| QUAL-4 | LOW | `database/db.py:324,342` | Redundant `_from_db` suffix |
| QUAL-5 | LOW | `handlers/start.py:44` | Fragile `_was_existing()` heuristic |
| QUAL-6 | LOW | `config.py:50` | Module-level debug log before logging is configured |
| LOW-1 | LOW | `main.py:84` | `get_event_loop()` deprecated in 3.10+ |
| LOW-2 | LOW | `services/reminder_service.py:62` | APScheduler missing timezone |
| LOW-3 | LOW | repo root | No `.gitignore` file |
| LOW-4 | LOW | `Dockerfile:1` | Unused `AS base` stage name |
| LOW-5 | LOW | `Dockerfile` | Container runs as root |
| LOW-6 | LOW | `docker-compose.yml` | No health check |
| LOW-7 | LOW | `database/db.py:12` | Relative DB path |
| LOW-8 | LOW | `handlers/booking.py:71` | No input length validation |
| LOW-9 | LOW | `handlers/admin.py` | Silent rejection on guard failure |
| LOW-10 | LOW | `handlers/my_bookings.py:91` | Fragile text append on cancel |

---

## Required Changes for Approval

1. **Immediately revoke** the committed bot token and rotate it.
2. Add `.gitignore` with `.env` included.
3. Remove `.env` from git history (`git filter-repo` or `BFG`).
4. Fix SEC-2 (service validation), SEC-3 (integer cast guard).
5. Fix BUG-1 (atomic slot booking), BUG-2 and BUG-3 (status transition guards).
6. Fix ARCH-4 (timezone-aware `date.today()`).

All other issues are recommended improvements but not blockers.
