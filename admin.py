import asyncio
import logging
import time

from aiogram import Router, F
from aiogram.filters import Command, BaseFilter
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_IDS
from database import db
import ota

logger = logging.getLogger(__name__)

router = Router()

BOT_STARTED_AT = time.time()


class AdminFilter(BaseFilter):
    async def __call__(self, event) -> bool:
        return event.from_user is not None and event.from_user.id in ADMIN_IDS


router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())


class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_price = State()


# --- КЛАВИАТУРЫ ---
def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="🔄 Проверить обновления", callback_data="admin_check_update")],
            [InlineKeyboardButton(text="⚙️ Цены подписок", callback_data="admin_prices")],
            [InlineKeyboardButton(text="🔁 Перезапустить бота", callback_data="admin_restart")],
            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_main")]
        ]
    )


def format_uptime() -> str:
    up = int(time.time() - BOT_STARTED_AT)
    days, rem = divmod(up, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} д")
    if hours:
        parts.append(f"{hours} ч")
    parts.append(f"{minutes} мин")
    return " ".join(parts)


async def show_admin_panel(event: Message | CallbackQuery):
    text = (
        "🛠 <b>Панель администратора</b>\n\n"
        "• <b>Статистика</b> — пользователи, вотч-лист, подписки\n"
        "• <b>Рассылка</b> — сообщение всем пользователям бота\n"
        "• <b>Проверить обновления</b> — OTA: новые коммиты с GitHub\n"
        "• <b>Цены подписок</b> — редактирование тарифов в звездах\n"
        "• <b>Перезапуск</b> — рестарт процесса бота"
    )
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    await show_admin_panel(message)


@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    await show_admin_panel(callback)


# --- СТАТИСТИКА ---
@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    stats = await db.get_stats()
    commit = await ota.get_current_commit()

    text = (
        f"📊 <b>Статистика бота</b>\n\n"
        f"👤 <b>Пользователей:</b> <code>{stats['users']}</code>\n"
        f"👀 <b>Кошельков в наблюдении:</b> <code>{stats['wallets']}</code>\n"
        f"⭐ <b>Активных подписок:</b> <code>{stats['active_subs']}</code>\n"
        f"🔑 <b>Своих TonAPI-ключей:</b> <code>{stats['custom_keys']}</code>\n\n"
        f"🧬 <b>Версия:</b> <code>{commit}</code>\n"
        f"🕒 <b>Аптайм:</b> <code>{format_uptime()}</code>"
    )
    await callback.message.edit_text(text, reply_markup=get_admin_keyboard(), parse_mode="HTML")
    await callback.answer()


# --- РАССЫЛКА ---
@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_broadcast)
    await callback.message.answer(
        "📢 <b>Рассылка</b>\n\n"
        "Отправьте сообщение, которое нужно разослать всем пользователям бота "
        "(поддерживается форматирование).\n\n"
        "<i>Для отмены отправьте /cancel</i>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AdminStates.waiting_broadcast, Command("cancel"))
async def cancel_broadcast(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Рассылка отменена.", reply_markup=get_admin_keyboard())


@router.message(AdminStates.waiting_broadcast)
async def process_broadcast_message(message: Message, state: FSMContext):
    text = message.html_text or message.text
    if not text:
        await message.answer("❌ Поддерживается только текстовое сообщение. Попробуйте еще раз или /cancel.")
        return

    await state.update_data(broadcast_text=text)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Начать рассылку", callback_data="admin_broadcast_send")],
            [InlineKeyboardButton(text="✏️ Изменить текст", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_broadcast_cancel")]
        ]
    )
    await message.answer(
        f"📋 <b>Превью рассылки:</b>\n\n{text}\n\n"
        "Подтвердите отправку всем пользователям:",
        reply_markup=kb,
        parse_mode="HTML",
        disable_web_page_preview=True
    )


@router.callback_query(F.data == "admin_broadcast_cancel")
async def cb_broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_admin_panel(callback)


@router.callback_query(F.data == "admin_broadcast_send")
async def cb_broadcast_send(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = data.get("broadcast_text")
    await state.clear()

    if not text:
        await callback.answer("Текст не найден, начните заново", show_alert=True)
        return

    user_ids = await db.get_all_user_ids()
    if not user_ids:
        await callback.message.edit_text("ℹ️ Пользователей в базе нет.", reply_markup=get_admin_keyboard())
        await callback.answer()
        return

    await callback.message.edit_text(f"📢 Рассылка запущена для <code>{len(user_ids)}</code> пользователей...")
    await callback.answer()

    ok = fail = 0
    for uid in user_ids:
        try:
            await callback.bot.send_message(
                uid, text, parse_mode="HTML", disable_web_page_preview=True
            )
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)

    await callback.message.edit_text(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"📬 Доставлено: <code>{ok}</code>\n"
        f"⛔ Ошибок: <code>{fail}</code>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


# --- OTA-ОБНОВЛЕНИЯ ---
@router.callback_query(F.data == "admin_check_update")
async def cb_check_update(callback: CallbackQuery):
    await callback.answer("⏳ Проверяю обновления...")

    info = await ota.check_for_updates()
    if info.get("error"):
        await callback.message.edit_text(
            f"❌ <b>Ошибка проверки:</b>\n{info['error']}",
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
        return

    if not info.get("available"):
        await callback.message.edit_text(
            f"✅ <b>Установлена последняя версия</b> (<code>{info['current']}</code>)",
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
        return

    changes = info.get("changes", "")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬆️ Установить обновление", callback_data="admin_apply_update")],
            [InlineKeyboardButton(text="🔙 В админку", callback_data="admin_panel")]
        ]
    )
    await callback.message.edit_text(
        f"🔄 <b>Доступно обновление!</b>\n\n"
        f"🧬 Текущая версия: <code>{info['current']}</code>\n"
        f"🆕 Новая версия: <code>{info['remote']}</code>\n\n"
        f"<b>Изменения:</b>\n<code>{changes}</code>",
        reply_markup=kb,
        parse_mode="HTML"
    )


async def _delayed_restart(delay: float = 3.0):
    await asyncio.sleep(delay)
    ota.restart_bot()


@router.callback_query(F.data == "admin_apply_update")
async def cb_apply_update(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("⬆️ Загружаю и устанавливаю обновление...")

    ok, msg = await ota.apply_update()
    if not ok:
        await callback.message.edit_text(
            f"❌ <b>Обновление не удалось:</b>\n{msg}",
            reply_markup=get_admin_keyboard(),
            parse_mode="HTML"
        )
        return

    await callback.message.edit_text(
        f"✅ <b>Обновление установлено</b> (версия <code>{msg}</code>).\n"
        f"🔁 Перезапускаюсь через пару секунд...",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )
    asyncio.create_task(_delayed_restart())


@router.callback_query(F.data == "admin_restart")
async def cb_restart(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("🔁 Перезапускаюсь через пару секунд...")
    asyncio.create_task(_delayed_restart())


# --- ЦЕНЫ ПОДПИСОК ---
PRICE_SETTINGS = {
    "month": ("price_month", "1 месяц"),
    "year": ("price_year", "1 год"),
    "lifetime": ("price_lifetime", "Навсегда"),
}

DEFAULT_PRICES = {"month": 129, "year": 999, "lifetime": 1499}


async def get_admin_prices() -> dict[str, int]:
    prices = {}
    for key, default in DEFAULT_PRICES.items():
        raw = await db.get_setting(f"price_{key}", str(default))
        try:
            prices[key] = int(float(raw))
        except (TypeError, ValueError):
            prices[key] = default
    return prices


@router.callback_query(F.data == "admin_prices")
async def cb_admin_prices(callback: CallbackQuery):
    prices = await get_admin_prices()
    text = (
        "⚙️ <b>Цены подписок (в звездах ⭐)</b>\n\n"
        f"• <b>1 месяц:</b> <code>{prices['month']} XTR</code>\n"
        f"• <b>1 год:</b> <code>{prices['year']} XTR</code>\n"
        f"• <b>Навсегда:</b> <code>{prices['lifetime']} XTR</code>\n\n"
        "Нажмите на тариф, чтобы изменить его цену."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"💰 Месяц: {prices['month']} ⭐", callback_data="admin_price_month")],
            [InlineKeyboardButton(text=f"💰 Год: {prices['year']} ⭐", callback_data="admin_price_year")],
            [InlineKeyboardButton(text=f"💰 Навсегда: {prices['lifetime']} ⭐", callback_data="admin_price_lifetime")],
            [InlineKeyboardButton(text="🔙 В админку", callback_data="admin_panel")]
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_price_"))
async def cb_set_price(callback: CallbackQuery, state: FSMContext):
    period = callback.data.replace("admin_price_", "")
    if period not in PRICE_SETTINGS:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return

    _, label = PRICE_SETTINGS[period]
    await state.set_state(AdminStates.waiting_price)
    await state.update_data(price_period=period)

    await callback.message.answer(
        f"✏️ Введите новую цену тарифа <b>{label}</b> в звездах "
        f"(целое число, например: <code>199</code>):\n\n"
        "<i>Для отмены отправьте /cancel</i>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AdminStates.waiting_price, Command("cancel"))
async def cancel_price(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Изменение цены отменено.", reply_markup=get_admin_keyboard())


@router.message(AdminStates.waiting_price)
async def process_price(message: Message, state: FSMContext):
    data = await state.get_data()
    period = data.get("price_period")
    if period not in PRICE_SETTINGS:
        await state.clear()
        await message.answer("❌ Ошибка состояния, попробуйте заново.", reply_markup=get_admin_keyboard())
        return

    try:
        val = int(message.text.strip())
        if val <= 0:
            raise ValueError
    except (TypeError, ValueError):
        await message.answer("❌ Введите целое положительное число (например: <code>199</code>):", parse_mode="HTML")
        return

    await db.set_setting(f"price_{period}", str(val))
    await state.clear()

    _, label = PRICE_SETTINGS[period]
    await message.answer(
        f"✅ Цена тарифа <b>{label}</b> обновлена: <code>{val} ⭐</code>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )
