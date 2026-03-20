import asyncio
import logging
import signal
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import aiogram

from bot import config
from bot.database.db import init_db
from bot.handlers import admin, booking, my_bookings, start
from bot.services.reminder_service import setup_scheduler

# ── Logging setup ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


# ── Middleware: log every update ───────────────────────────────────────────

from aiogram import BaseMiddleware
from aiogram.types import Update
from typing import Any, Awaitable, Callable


class LoggingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        update_id = getattr(event, "update_id", "?")
        update_type = event.event_type if hasattr(event, "event_type") else type(event).__name__
        logger.debug("Incoming update: update_id=%s type=%s", update_id, update_type)
        return await handler(event, data)


# ── Main ───────────────────────────────────────────────────────────────────

async def main() -> None:
    logger.info(
        "Starting АвтоПлюс bot | aiogram=%s | timezone=%s",
        aiogram.__version__,
        config.TIMEZONE,
    )

    await init_db()
    logger.info("Database initialized")

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Middleware
    dp.update.outer_middleware(LoggingMiddleware())

    # Routers
    dp.include_router(start.router)
    dp.include_router(booking.router)
    dp.include_router(my_bookings.router)
    dp.include_router(admin.router)
    logger.info("All routers registered")

    # Scheduler
    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Reminder scheduler started")

    # Graceful shutdown
    loop = asyncio.get_event_loop()

    def _shutdown(sig_name: str) -> None:
        logger.info("Received %s — initiating graceful shutdown", sig_name)
        scheduler.shutdown(wait=False)
        loop.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig.name: _shutdown(s))
        except NotImplementedError:
            pass  # Windows

    try:
        logger.info("Bot is polling...")
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query"],
        )
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
