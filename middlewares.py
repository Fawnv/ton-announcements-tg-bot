from typing import Callable, Dict, Any, Awaitable, Optional
from aiogram import BaseMiddleware
from aiogram.types import (
    TelegramObject,
    Message,
    CallbackQuery,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from database import db
from emojis import E_LOCK, E_KEY, E_BULB

class WhitelistMiddleware(BaseMiddleware):
    def __init__(
        self,
        whitelist: Optional[set[int]] = None,
        admin_whitelist: Optional[set[int]] = None,
        admins: Optional[set[int]] = None
    ):
        self.whitelist = whitelist or set()
        self.admins = admins or admin_whitelist or set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if not user:
            return await handler(event, data)

        if user.id in self.whitelist or user.id in self.admins:
            return await handler(event, data)

        user_db = await db.get_user(user.id)
        has_custom_key = bool(user_db and user_db.get("custom_api_key"))
        if has_custom_key:
            return await handler(event, data)

        state = data.get("state")
        current_state = await state.get_state() if state else None

        if current_state == "FormStates:waiting_for_api_key":
            return await handler(event, data)

        if isinstance(event, CallbackQuery) and event.data == "activate_by_key":
            return await handler(event, data)

        unlock_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔑 Ввести свой TonAPI ключ", callback_data="activate_by_key")],
                [InlineKeyboardButton(text="ℹ️ Как получить ключ (бесплатно)", url="https://tonapi.io")]
            ]
        )

        lock_text = (
            f"{E_LOCK} <b>Требуется активация по API-ключу</b>\n\n"
            "Для бесплатных пользователей отслеживание работает через ваш <b>персональный ключ TonAPI</b>, "
            "чтобы не перегружать общий лимит бота.\n\n"
            "1. Зайдите на tonapi.io, зарегистрируйтесь и во вкладке TON API > API Keys бесплатно создайте и скопируйте ключ.\n"
            "2. Нажмите кнопку ниже и отправьте ключ боту.\n\n"
            f"{E_BULB} <i>После этого вам сразу откроется возможность добавить 1 кошелек в наблюдение!</i>"
        )

        if isinstance(event, Message):
            await event.answer(lock_text, reply_markup=unlock_kb, parse_mode="HTML")
        elif isinstance(event, CallbackQuery):
            await event.answer("🔒 Сначала введите свой TonAPI ключ!", show_alert=True)
        elif isinstance(event, InlineQuery):
            await event.answer(
                results=[
                    InlineQueryResultArticle(
                        id="key_required",
                        title="🔒 Требуется TonAPI ключ",
                        description="Нажмите /start в боте, чтобы привязать бесплатный ключ.",
                        input_message_content=InputTextMessageContent(
                            message_text="🔒 Для использования бота введите свой TonAPI ключ через команду /start."
                        )
                    )
                ],
                cache_time=5,
                is_personal=True
            )
        return
