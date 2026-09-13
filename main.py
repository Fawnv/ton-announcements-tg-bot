import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, WHITELIST_USER_IDS, TONAPI_KEY, CHECK_INTERVAL
from database import db
from ton_api import TonApiClient
from middlewares import WhitelistMiddleware
from handlers import router
from tracker import start_tx_tracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

async def main():
    await db.init()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    ton_client = TonApiClient(api_key=TONAPI_KEY)

    dp["ton_client"] = ton_client

    # Защита сообщений, кнопок и инлайн-запросов
    whitelist_mw = WhitelistMiddleware(whitelist=WHITELIST_USER_IDS)
    dp.message.outer_middleware(whitelist_mw)
    dp.callback_query.outer_middleware(whitelist_mw)
    dp.inline_query.outer_middleware(whitelist_mw)

    dp.include_router(router)

    tracker_task = asyncio.create_task(
        start_tx_tracker(bot, db, ton_client, interval=CHECK_INTERVAL)
    )

    try:
        logger.info(f"Бот запущен. Разрешенные ID: {WHITELIST_USER_IDS}")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        tracker_task.cancel()
        await ton_client.close()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
