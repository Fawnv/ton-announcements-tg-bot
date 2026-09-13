import html
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from database import db
from ton_api import TonApiClient

router = Router()

class WalletStates(StatesGroup):
    waiting_for_wallet = State()

def get_wallet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰 Проверить баланс", callback_data="check_balance")],
            [InlineKeyboardButton(text="🔄 Сменить адрес", callback_data="change_wallet")],
            [InlineKeyboardButton(text="❌ Отвязать кошелек", callback_data="delete_wallet")]
        ]
    )

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, ton_client: TonApiClient):
    await state.clear()
    user = await db.get_user(message.from_user.id)

    if not user:
        await state.set_state(WalletStates.waiting_for_wallet)
        await message.answer(
            "👋 <b>Добро пожаловать!</b>\n\n"
            "Для отслеживания транзакций укажите ваш <b>TON-адрес</b>\n"
            "(например, <code>EQ...</code>, <code>UQ...</code> или raw-адрес):",
            parse_mode="HTML"
        )
        return

    acc = await ton_client.get_account(user["raw_address"])
    balance = (acc.get("balance", 0) / 10**9) if acc else 0.0

    await message.answer(
        f"💎 <b>Ваш кошелек подключен:</b>\n"
        f"📍 Адрес: <code>{user['user_address']}</code>\n"
        f"💰 Баланс: <code>{balance:.4f} TON</code>\n\n"
        f"🔔 <i>Бот автоматически пришлет уведомление при новой транзакции.</i>",
        reply_markup=get_wallet_keyboard(),
        parse_mode="HTML"
    )

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.")

@router.message(WalletStates.waiting_for_wallet)
async def process_wallet_address(message: Message, state: FSMContext, ton_client: TonApiClient):
    address = message.text.strip()

    await message.answer("🔍 Проверяю адрес в сети TON...")
    acc_info = await ton_client.get_account(address)

    if not acc_info:
        await message.answer(
            "❌ <b>Некорректный адрес кошелька!</b>\n"
            "Не удалось найти аккаунт в сети TON. Проверьте правильность и отправьте адрес снова:",
            parse_mode="HTML"
        )
        return

    raw_address = acc_info["address"]
    balance = acc_info.get("balance", 0) / 10**9

    events = await ton_client.get_events(raw_address, limit=1)
    last_event_id = events[0]["event_id"] if events else ""

    await db.save_user(
        user_id=message.from_user.id,
        raw_address=raw_address,
        user_address=address,
        last_event_id=last_event_id
    )
    await state.clear()

    await message.answer(
        f"✅ <b>Кошелек успешно сохранен!</b>\n\n"
        f"📍 <b>Адрес:</b> <code>{address}</code>\n"
        f"💰 <b>Текущий баланс:</b> <code>{balance:.4f} TON</code>\n\n"
        f"🔔 Теперь бот будет присылать вам уведомления о входящих и исходящих транзакциях.",
        reply_markup=get_wallet_keyboard(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "check_balance")
async def cb_check_balance(callback: CallbackQuery, ton_client: TonApiClient):
    user = await db.get_user(callback.from_user.id)
    if not user:
        await callback.answer("Кошелек не найден.", show_alert=True)
        return

    acc = await ton_client.get_account(user["raw_address"])
    balance = (acc.get("balance", 0) / 10**9) if acc else 0.0

    await callback.message.edit_text(
        f"💎 <b>Информация о кошельке:</b>\n\n"
        f"📍 <b>Адрес:</b> <code>{user['user_address']}</code>\n"
        f"💰 <b>Текущий баланс:</b> <code>{balance:.4f} TON</code>\n\n"
        f"🔔 <i>Отслеживание активно.</i>",
        reply_markup=get_wallet_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "change_wallet")
async def cb_change_wallet(callback: CallbackQuery, state: FSMContext):
    await state.set_state(WalletStates.waiting_for_wallet)
    await callback.message.answer("✏️ Отправьте новый адрес TON-кошелька:")
    await callback.answer()

@router.callback_query(F.data == "delete_wallet")
async def cb_delete_wallet(callback: CallbackQuery):
    await db.delete_user(callback.from_user.id)
    await callback.message.edit_text(
        "❌ Кошелек отвязан. Для повторной настройки отправьте команду /start."
    )
    await callback.answer()
