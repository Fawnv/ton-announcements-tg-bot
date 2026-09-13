import asyncio
import logging
import os
import time
from datetime import datetime

from dotenv import dotenv_values, set_key
from aiogram import Router, F
from aiogram.filters import Command, BaseFilter
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_IDS, IS_DOCKER
from database import db
from kb import btn
from emojis import E_CHART, E_TIME, E_OK, E_INFO, E_BULB, E_WARN, E_STAR, E_KEY, E_LOC
import ota

logger = logging.getLogger(__name__)

router = Router()

BOT_STARTED_AT = time.time()

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# Редактируемые из бота ключи .env (BOT_TOKEN намеренно исключен —
# его смена из работающего бота убьет текущую сессию).
ENV_KEYS = [
    ("TONAPI_KEY", "TonAPI мастер-ключ", True),
    ("CHECK_INTERVAL", "Интервал проверки (сек)", False),
    ("WHITELIST_USER_IDS", "Whitelist ID (через запятую)", False),
    ("ADMIN_IDS", "ID админов (через запятую)", False),
    ("PAY2328_PROJECT", "2328 Project UUID", True),
    ("PAY2328_API_KEY", "2328 API-ключ", True),
    ("PAY2328_CALLBACK_URL", "2328 Callback URL", False),
]


class AdminFilter(BaseFilter):
    async def __call__(self, event) -> bool:
        return event.from_user is not None and event.from_user.id in ADMIN_IDS


router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())


class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_price = State()
    waiting_env_value = State()


# --- КЛАВИАТУРЫ ---
def get_admin_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [btn("📊 Статистика", cb="admin_stats", icon="chart")],
        [btn("👥 Пользователи", cb="admin_users", icon="user")],
        [btn("📢 Рассылка", cb="admin_broadcast", icon="comment")],
    ]
    # OTA и редактор .env не работают в Docker: код вшит в образ,
    # а переменные приходят через env_file при создании контейнера.
    if not IS_DOCKER:
        rows.append([btn("🔄 Проверить обновления", cb="admin_check_update", icon="date")])
    rows.append([
        btn("⚙️ Цены ⭐", cb="admin_prices", icon="star"),
        btn("🪙 Цены USD", cb="admin_prices_usd", icon="jetton")
    ])
    if not IS_DOCKER:
        rows.append([btn("🧩 Настройки (.env)", cb="admin_env", icon="gear")])
    rows.append([btn("🔁 Перезапустить бота", cb="admin_restart", style="danger", icon="red")])
    rows.append([btn("🔙 В главное меню", cb="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
    lines = [
        "• <b>Статистика</b> — пользователи, вотч-лист, подписки",
        "• <b>Пользователи</b> — список с подписками и лимитами",
        "• <b>Рассылка</b> — сообщение всем пользователям бота",
    ]
    if not IS_DOCKER:
        lines.append("• <b>Проверить обновления</b> — OTA: новые коммиты с GitHub")
    lines.append("• <b>Цены</b> — тарифы в звездах и USD")
    if not IS_DOCKER:
        lines.append("• <b>Настройки (.env)</b> — переменные окружения без SSH")
    lines.append("• <b>Перезапуск</b> — рестарт процесса бота")
    text = "🛠 <b>Панель администратора</b>\n\n" + "\n".join(lines)
    if IS_DOCKER:
        text += (
            "\n\n🐳 <i>Docker-режим: OTA-обновления и редактор .env отключены. "
            "Обновляйтесь пересборкой образа, переменные меняйте в docker-compose.</i>"
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
    commit = "docker" if IS_DOCKER else await ota.get_current_commit()

    text = (
        f"{E_CHART} <b>Статистика бота</b>\n\n"
        f"👤 <b>Пользователей:</b> <code>{stats['users']}</code>\n"
        f"👀 <b>Кошельков в наблюдении:</b> <code>{stats['wallets']}</code>\n"
        f"{E_STAR} <b>Активных подписок:</b> <code>{stats['active_subs']}</code>\n"
        f"{E_KEY} <b>Своих TonAPI-ключей:</b> <code>{stats['custom_keys']}</code>\n\n"
        f"🧬 <b>Версия:</b> <code>{commit}</code>\n"
        f"{E_TIME} <b>Аптайм:</b> <code>{format_uptime()}</code>"
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
            [btn("✅ Начать рассылку", cb="admin_broadcast_send", style="success", icon="ok")],
            [btn("✏️ Изменить текст", cb="admin_broadcast", icon="pencil")],
            [btn("❌ Отмена", cb="admin_broadcast_cancel", icon="reject")]
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
        await callback.message.edit_text(f"{E_INFO} Пользователей в базе нет.", reply_markup=get_admin_keyboard())
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
        f"{E_OK} <b>Рассылка завершена</b>\n\n"
        f"📬 Доставлено: <code>{ok}</code>\n"
        f"⛔ Ошибок: <code>{fail}</code>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


# --- OTA-ОБНОВЛЕНИЯ (только вне Docker) ---
@router.callback_query(F.data == "admin_check_update")
async def cb_check_update(callback: CallbackQuery):
    if IS_DOCKER:
        await callback.answer("🐳 OTA недоступен в Docker — обновите контейнер пересборкой образа", show_alert=True)
        return

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
            [btn("⬆️ Установить обновление", cb="admin_apply_update", style="success", icon="party")],
            [btn("🔙 В админку", cb="admin_panel")]
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
    if IS_DOCKER:
        await callback.answer("🐳 OTA недоступен в Docker — обновите контейнер пересборкой образа", show_alert=True)
        return

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
    "month": "1 месяц",
    "year": "1 год",
    "lifetime": "Навсегда",
}


@router.callback_query(F.data == "admin_prices")
async def cb_admin_prices(callback: CallbackQuery):
    from handlers import get_star_prices
    prices = await get_star_prices()
    text = (
        f"{E_STAR} <b>Цены подписок (в звездах)</b>\n\n"
        f"• <b>1 месяц:</b> <code>{prices['month']} XTR</code>\n"
        f"• <b>1 год:</b> <code>{prices['year']} XTR</code>\n"
        f"• <b>Навсегда:</b> <code>{prices['lifetime']} XTR</code>\n\n"
        f"{E_BULB} Нажмите на тариф, чтобы изменить его цену."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(f"💰 Месяц: {prices['month']} ⭐", cb="admin_price_month", icon="star")],
            [btn(f"💰 Год: {prices['year']} ⭐", cb="admin_price_year", icon="star")],
            [btn(f"💰 Навсегда: {prices['lifetime']} ⭐", cb="admin_price_lifetime", icon="star")],
            [btn("🔙 В админку", cb="admin_panel")]
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_prices_usd")
async def cb_admin_prices_usd(callback: CallbackQuery):
    from handlers import get_usd_prices
    prices = await get_usd_prices()
    text = (
        f"🪙 <b>Цены подписок в USD (оплата криптой через 2328.io)</b>\n\n"
        f"• <b>1 месяц:</b> <code>${prices['month']:.2f}</code>\n"
        f"• <b>1 год:</b> <code>${prices['year']:.2f}</code>\n"
        f"• <b>Навсегда:</b> <code>${prices['lifetime']:.2f}</code>\n\n"
        f"{E_BULB} Нажмите на тариф, чтобы изменить его цену."
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(f"💰 Месяц: ${prices['month']:.2f}", cb="admin_priceusd_month", icon="jetton")],
            [btn(f"💰 Год: ${prices['year']:.2f}", cb="admin_priceusd_year", icon="jetton")],
            [btn(f"💰 Навсегда: ${prices['lifetime']:.2f}", cb="admin_priceusd_lifetime", icon="jetton")],
            [btn("🔙 В админку", cb="admin_panel")]
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_priceusd_"))
async def cb_set_price_usd(callback: CallbackQuery, state: FSMContext):
    period = callback.data.replace("admin_priceusd_", "")
    if period not in PRICE_SETTINGS:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_price)
    await state.update_data(price_key=f"usd_{period}")

    await callback.message.answer(
        f"✏️ Введите новую цену тарифа <b>{PRICE_SETTINGS[period]}</b> в USD "
        f"(например: <code>2.50</code>):\n\n"
        "<i>Для отмены отправьте /cancel</i>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_price_"))
async def cb_set_price(callback: CallbackQuery, state: FSMContext):
    period = callback.data.replace("admin_price_", "")
    if period not in PRICE_SETTINGS:
        await callback.answer("Неизвестный тариф", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_price)
    await state.update_data(price_key=period)

    await callback.message.answer(
        f"✏️ Введите новую цену тарифа <b>{PRICE_SETTINGS[period]}</b> в звездах "
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
    if not message.text:
        await message.answer("❌ Цена должна быть числом. Отправьте текстом или /cancel.")
        return

    data = await state.get_data()
    price_key = data.get("price_key")
    if not price_key:
        await state.clear()
        await message.answer("❌ Ошибка состояния, попробуйте заново.", reply_markup=get_admin_keyboard())
        return

    is_usd = price_key.startswith("usd_")
    label = PRICE_SETTINGS.get(price_key.replace("usd_", "", 1) if is_usd else price_key, price_key)
    raw = message.text.strip().replace(",", ".")

    try:
        if is_usd:
            val = float(raw)
            if val <= 0:
                raise ValueError
        else:
            val = int(float(raw))
            if val <= 0:
                raise ValueError
    except (TypeError, ValueError):
        kind = "положительное число (например: 2.50)" if is_usd else "целое положительное число (например: 199)"
        await message.answer(f"❌ Введите {kind}:", parse_mode="HTML")
        return

    await db.set_setting(f"price_{price_key}", str(val))
    await state.clear()

    unit = "USD" if is_usd else "⭐"
    await message.answer(
        f"{E_OK} Цена тарифа <b>{label}</b> обновлена: <code>{val} {unit}</code>",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML"
    )


# --- ПОЛЬЗОВАТЕЛИ ---
@router.callback_query(F.data.startswith("admin_users"))
async def cb_admin_users(callback: CallbackQuery):
    raw = callback.data.replace("admin_users", "").replace("_", "")
    try:
        page = max(1, int(raw)) if raw else 1
    except ValueError:
        page = 1

    per_page = 10
    total = await db.count_users()
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)

    users = await db.get_users_page(page, per_page)
    now = int(time.time())

    text = f"👥 <b>Пользователи</b> <i>(стр. {page}/{pages}, всего {total})</i>\n\n"
    for u in users:
        if u.get("sub_type") == "lifetime":
            status = f"{E_STAR} навсегда"
        elif u.get("sub_until", 0) > now:
            dt = datetime.fromtimestamp(u["sub_until"]).strftime("%d.%m.%y")
            status = f"{E_STAR} до {dt}"
        else:
            status = "бесплатный"
        key_mark = f", {E_KEY} свой ключ" if u.get("custom_api_key") else ""
        text += (
            f"👤 <code>{u['user_id']}</code> — {status}{key_mark}\n"
            f"   👀 кошельков: <code>{u['wallets']}</code>\n"
        )

    rows = []
    if page > 1:
        rows.append(btn("⬅️ Назад", cb=f"admin_users_{page - 1}"))
    if page < pages:
        rows.append(btn("➡️ Вперед", cb=f"admin_users_{page + 1}"))
    kb_rows = [rows] if rows else []
    kb_rows.append([btn("🔙 В админку", cb="admin_panel")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# --- РЕДАКТОР .ENV ---
def _mask(value: str) -> str:
    if len(value) <= 4:
        return "••••"
    return value[:3] + "•••" + value[-2:]


def _read_env() -> dict[str, str]:
    if not os.path.isfile(ENV_PATH):
        return {}
    return {k: v for k, v in dotenv_values(ENV_PATH).items() if v is not None}


def _get_env_display(key: str, masked: bool) -> str:
    value = _read_env().get(key) or os.getenv(key, "")
    if not value:
        return "<i>(не задано)</i>"
    return f"<code>{_mask(value)}</code>" if masked else f"<code>{value}</code>"


@router.callback_query(F.data == "admin_env")
async def cb_admin_env(callback: CallbackQuery):
    if IS_DOCKER:
        await callback.answer("🐳 Редактор .env недоступен в Docker — переменные задаются в docker-compose", show_alert=True)
        return

    text = f"🧩 <b>Настройки бота (.env)</b>\n\n"
    rows = []
    for idx, (key, label, masked) in enumerate(ENV_KEYS):
        text += f"• <b>{label}</b>: {_get_env_display(key, masked)}\n"
        rows.append([btn(f"✏️ {label}", cb=f"admin_env_set_{idx}", icon="pencil")])
    text += (
        f"\n{E_WARN} <i>Изменения применяются после перезапуска бота.</i>\n"
        f"{E_LOC} Файл: <code>.env</code>"
    )
    rows.append([btn("🔁 Перезапустить", cb="admin_restart", style="danger", icon="red")])
    rows.append([btn("🔙 В админку", cb="admin_panel")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_env_set_"))
async def cb_admin_env_set(callback: CallbackQuery, state: FSMContext):
    if IS_DOCKER:
        await callback.answer("🐳 Редактор .env недоступен в Docker — переменные задаются в docker-compose", show_alert=True)
        return

    try:
        idx = int(callback.data.replace("admin_env_set_", ""))
        key, label, masked = ENV_KEYS[idx]
    except (ValueError, IndexError):
        await callback.answer("Неизвестная настройка", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_env_value)
    await state.update_data(env_key=key, env_masked=masked)

    await callback.message.answer(
        f"✏️ Введите новое значение для <b>{label}</b> (<code>{key}</code>):\n\n"
        f"{E_INFO} Текущее: {_get_env_display(key, masked)}\n"
        "<i>Для отмены отправьте /cancel. Пустое значение не сохранится.</i>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AdminStates.waiting_env_value, Command("cancel"))
async def cancel_env_value(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Изменение настройки отменено.", reply_markup=get_admin_keyboard())


@router.message(AdminStates.waiting_env_value)
async def process_env_value(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Значение должно быть текстом. Отправьте текстом или /cancel.")
        return

    data = await state.get_data()
    key = data.get("env_key")
    await state.clear()

    if not key or key not in [k for k, _, _ in ENV_KEYS]:
        await message.answer("❌ Ошибка состояния, попробуйте заново.", reply_markup=get_admin_keyboard())
        return

    value = message.text.strip()
    if not value:
        await message.answer("❌ Пустое значение не сохранено.", reply_markup=get_admin_keyboard())
        return

    if key == "CHECK_INTERVAL":
        try:
            if int(value) <= 0:
                raise ValueError
        except ValueError:
            await message.answer("❌ Интервал должен быть целым положительным числом (секунды).", parse_mode="HTML")
            return
    elif key in ("WHITELIST_USER_IDS", "ADMIN_IDS"):
        if not all(p.strip().isdigit() for p in value.split(",") if p.strip()):
            await message.answer("❌ Ожидается список числовых ID через запятую (например: 123, 456).", parse_mode="HTML")
            return

    try:
        set_key(ENV_PATH, key, value)
    except Exception as e:
        logger.error(f"Ошибка записи {key} в .env: {e}")
        await message.answer(f"❌ Не удалось записать <code>{key}</code> в .env: {e}", parse_mode="HTML")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("🔁 Перезапустить сейчас", cb="admin_restart", style="danger", icon="red")],
            [btn("🧩 К настройкам", cb="admin_env", icon="gear")]
        ]
    )
    await message.answer(
        f"{E_OK} <code>{key}</code> сохранен в .env.\n"
        f"{E_WARN} <i>Изменение вступит в силу после перезапуска бота.</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )
