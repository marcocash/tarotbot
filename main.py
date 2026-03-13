import asyncio
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import ai_client
import config
import database
import handlers
import payments
from services.mailing import send_daily_mailing
from services.antispam import (
    CallbackSpamGuardMiddleware,
    MessageSpamGuardMiddleware,
    UniversalSpamGuardMiddleware,
)
from services.payment_watcher import run_payment_autocheck
from services.retention import run_abandoned_payment_reminders, run_vip_renewal_reminders
from services.subscription import CheckSubscriptionMiddleware


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))

    handler = logging.StreamHandler()
    if config.LOG_JSON:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )

    root_logger.addHandler(handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _mask_database_url(database_url: str) -> str:
    try:
        parsed = urlsplit(database_url)
        if parsed.password is None:
            return database_url

        host = parsed.hostname or ""
        netloc = host
        if parsed.port is not None:
            netloc = f"{host}:{parsed.port}"

        if parsed.username:
            netloc = f"{parsed.username}:***@{netloc}"

        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        logging.exception("Failed to mask DATABASE_URL")
        return "<hidden>"


def create_fsm_storage():
    if not config.REDIS_FSM_URL:
        logging.info("FSM storage: MemoryStorage")
        return MemoryStorage()

    try:
        from aiogram.fsm.storage.redis import RedisStorage
        from redis.asyncio import Redis

        redis_client = Redis.from_url(config.REDIS_FSM_URL)
        logging.info("FSM storage: RedisStorage")
        return RedisStorage(redis_client)
    except Exception:
        logging.exception("Failed to initialize RedisStorage, falling back to MemoryStorage")
        return MemoryStorage()


setup_logging()

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(storage=create_fsm_storage())
scheduler = AsyncIOScheduler()
_dispatcher_configured = False


def _configure_dispatcher_once() -> None:
    global _dispatcher_configured
    if _dispatcher_configured:
        return

    middleware = CheckSubscriptionMiddleware()
    dp.update.middleware(UniversalSpamGuardMiddleware())
    dp.message.middleware(middleware)
    dp.callback_query.middleware(middleware)
    dp.message.middleware(MessageSpamGuardMiddleware())
    dp.callback_query.middleware(CallbackSpamGuardMiddleware())

    for router in handlers.get_routers():
        dp.include_router(router)

    _dispatcher_configured = True


def _start_scheduler_once() -> None:
    if scheduler.running:
        return

    scheduler.add_job(
        send_daily_mailing,
        "cron",
        hour=8,
        minute=0,
        args=[bot],
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        send_daily_mailing,
        "cron",
        hour=18,
        minute=0,
        args=[bot],
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_payment_autocheck,
        "interval",
        seconds=30,
        args=[bot],
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_abandoned_payment_reminders,
        "interval",
        minutes=10,
        args=[bot],
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_vip_renewal_reminders,
        "interval",
        minutes=30,
        args=[bot],
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(_log_runtime_metrics, "interval", minutes=1, max_instances=1, coalesce=True)
    scheduler.start()


def _log_runtime_metrics() -> None:
    metrics = ai_client.get_ai_runtime_metrics()
    logging.info(
        "Runtime metrics | ai_requests=%s ai_retries=%s ai_rejected=%s ai_errors=%s ai_pending=%s",
        metrics["requests"],
        metrics["retries"],
        metrics["queue_rejected"],
        metrics["errors"],
        metrics["pending"],
    )


async def _run_polling() -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


async def _run_webhook() -> None:
    if not config.WEBHOOK_BASE_URL:
        raise ValueError("WEBHOOK_BASE_URL must be set when WEBHOOK_ENABLED=true")

    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    app = web.Application()
    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=config.WEBHOOK_SECRET_TOKEN or None,
    )
    webhook_handler.register(app, path=config.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    webhook_url = f"{config.WEBHOOK_BASE_URL.rstrip('/')}{config.WEBHOOK_PATH}"
    await bot.set_webhook(
        webhook_url,
        secret_token=config.WEBHOOK_SECRET_TOKEN or None,
        drop_pending_updates=True,
    )
    logging.info("Webhook set: %s", webhook_url)
    await web._run_app(app, host=config.WEBHOOK_HOST, port=config.WEBHOOK_PORT)


async def main() -> None:
    await database.create_table()
    _configure_dispatcher_once()
    _start_scheduler_once()

    logging.info(
        "Bot started | mode=%s db=%s ai_concurrency=%s ai_queue=%s",
        "webhook" if config.WEBHOOK_ENABLED else "polling",
        _mask_database_url(config.DATABASE_URL),
        config.AI_MAX_CONCURRENCY,
        config.AI_QUEUE_LIMIT,
    )
    try:
        if config.WEBHOOK_ENABLED:
            await _run_webhook()
        else:
            await _run_polling()
    finally:
        scheduler.shutdown(wait=False)
        if config.WEBHOOK_ENABLED:
            try:
                await bot.delete_webhook()
            except Exception:
                logging.exception("Failed to delete webhook on shutdown")
        await payments.close()
        await database.close()
        await dp.storage.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
