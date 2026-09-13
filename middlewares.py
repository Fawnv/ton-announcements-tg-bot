from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

class WhitelistMiddleware(BaseMiddleware):
    def __init__(self, whitelist: set[int]):
        self.whitelist = whitelist

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        if user.id not in self.whitelist:
            if isinstance(event, Message):
                await event.answer(
                    "⛔ <b>Доступ запрещен</b>\n"
                    f"Ваш Telegram ID: <code>{user.id}</code> не найден в списке разрешенных.",
                    parse_mode="HTML"
                )
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ запрещен.", show_alert=True)
            return

        return await handler(event, data)
