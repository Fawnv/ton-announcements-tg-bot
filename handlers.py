import html
import time
import hashlib
from datetime import datetime
from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    LabeledPrice,
    PreCheckoutQuery
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from config import WHITELIST_USER_IDS, ADMIN_IDS
from database import db
from ton_api import TonApiClient
from tracker import parse_fiat_currencies

router = Router()

# Премиум-эмодзи для текста сообщений (HTML)
E_TON     = '<tg-emoji emoji-id="5427168083074628963">💎</tg-emoji>'
E_CHART   = '<tg-emoji emoji-id="5231200819986047254">📊</tg-emoji>'
E_BELL    = '<tg-emoji emoji-id="5458603043203327669">🔔</tg-emoji>'
E_LOC     = '<tg-emoji emoji-id="5391032818111363540">📍</tg-emoji>'
E_REJECT  = '<tg-emoji emoji-id="5210952531676504517">❌</tg-emoji>'
E_PENCIL  = '<tg-emoji emoji-id="5395444784611480792">✏️</tg-emoji>'
E_SEARCH  = '<tg-emoji emoji-id="5231012545799666522">🔍</tg-emoji>'
E_TIME    = '<tg-emoji emoji-id="5382194935057372936">🕒</tg-emoji>'
E_LINK    = '<tg-emoji emoji-id="5271604874419647061">🔗</tg-emoji>'

# Цены подписки в звездах (значения по умолчанию; переопределяются админом через БД)
DEFAULT_STAR_PRICE_MONTH = 129
DEFAULT_STAR_PRICE_YEAR = 999
DEFAULT_STAR_PRICE_LIFETIME = 1499


async def get_star_prices() -> dict[str, int]:
    """Возвращает актуальные цены подписок (админ может менять их через панель)."""
    defaults = {
        "month": DEFAULT_STAR_PRICE_MONTH,
        "year": DEFAULT_STAR_PRICE_YEAR,
        "lifetime": DEFAULT_STAR_PRICE_LIFETIME,
    }
    prices = {}
    for key, default in defaults.items():
        raw = await db.get_setting(f"price_{key}", str(default))
        try:
            prices[key] = int(float(raw))
        except (TypeError, ValueError):
            prices[key] = default
    return prices


class FormStates(StatesGroup):
    waiting_for_api_key = State()
    waiting_for_watch_address = State()
    waiting_for_filter_in = State()
    waiting_for_filter_out = State()
    waiting_for_wallet_label = State()


def short_addr(addr: str) -> str:
    if len(addr) > 16:
        return f"{addr[:6]}...{addr[-6:]}"
    return addr


async def get_user_wallet_limit(user_id: int) -> int:
    """Лимит кошельков: 1 для фри-юзеров, 999999 для ВЛ и подписчиков."""
    if user_id in WHITELIST_USER_IDS:
        return 999999

    user = await db.get_user(user_id)
    if not user:
        return 1

    if user.get("sub_type") == "lifetime":
        return 999999

    if user.get("sub_until", 0) > int(time.time()):
        return 999999

    return 1


# --- КЛАВИАТУРЫ ---
def get_main_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="👀 Мой вотч-лист", callback_data="show_watchlist")],
        [InlineKeyboardButton(text="➕ Добавить кошелек", callback_data="add_wallet_btn")],
        [
            InlineKeyboardButton(text="⚙️ Валюта", callback_data="settings_fiat"),
            InlineKeyboardButton(text="🎯 Фильтры", callback_data="settings_filters")
        ],
        [InlineKeyboardButton(text="⭐ Подписка", callback_data="subscribe_menu")]
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="🛠 Админка", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_sub_keyboard(prices: dict[str, int]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"⭐ 1 месяц — {prices['month']} XTR", callback_data="buy_sub_month")],
            [InlineKeyboardButton(text=f"⭐ 1 год — {prices['year']} XTR", callback_data="buy_sub_year")],
            [InlineKeyboardButton(text=f"♾️ Навсегда — {prices['lifetime']} XTR", callback_data="buy_sub_lifetime")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
        ]
    )


FIAT_OPTIONS = [
    ("usd", "💵 USD"),
    ("eur", "💶 EUR"),
    ("rub", "🪙 RUB"),
]


def get_fiat_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    """Тогл-меню: 3 кнопки-валюты. Нажал — включил, нажал выбранное — выключил."""
    rows = []
    for code, label in FIAT_OPTIONS:
        mark = "✅ " if code in selected else "▫️ "
        rows.append([InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"toggle_fiat_{code}")])
    state = " + ".join(c.upper() for c in selected) if selected else "выключено"
    rows.append([InlineKeyboardButton(text=f"🔴 Выключить цены", callback_data="toggle_fiat_off")])
    rows.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- ОТМЕНА ДЕЙСТВИЯ ---
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=get_main_keyboard())


# --- АКТИВАЦИЯ ПО КЛЮЧУ TONAPI ДЛЯ ФРИ-ЮЗЕРОВ ---
@router.callback_query(F.data == "activate_by_key")
async def cb_activate_by_key(callback: CallbackQuery, state: FSMContext):
    await state.set_state(FormStates.waiting_for_api_key)
    await callback.message.answer(
        "🔑 <b>Подключение персонального TonAPI ключа:</b>\n\n"
        "1. Зарегистрируйтесь на сайте <a href=\"https://tonapi.io\">tonapi.io</a>\n"
        "2. Перейдите во вкладку <b>TON API > API Keys</b> и создайте бесплатный ключ.\n"
        "3. Скопируйте созданный ключ и отправьте его сюда сообщением.\n\n"
        "<i>Для отмены отправьте /cancel</i>",
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()


@router.message(FormStates.waiting_for_api_key)
async def process_user_api_key(message: Message, state: FSMContext, ton_client: TonApiClient):
    if not message.text:
        await message.answer("❌ Ключ должен быть текстом. Отправьте ключ сообщением или /cancel.")
        return

    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Ввод ключа отменен.")
        return

    key = message.text.strip()
    wait_m = await message.answer("🔍 Проверяю валидность ключа на tonapi.io...")

    is_valid = await ton_client.verify_key(key)
    if not is_valid:
        await wait_m.edit_text(
            "❌ <b>Неверный API-ключ!</b>\n"
            "Сервер tonapi.io отклонил этот ключ. Убедитесь, что скопировали его полностью из вкладки <b>TON API > API Keys</b>, и попробуйте снова:",
            parse_mode="HTML"
        )
        return

    await db.set_user_api_key(message.from_user.id, key)
    await state.clear()

    await wait_m.edit_text(
        "✅ <b>Ключ успешно подтвержден! Доступ разблокирован.</b>\n\n"
        "Вам доступно бесплатное наблюдение за <b>1 кошельком</b>.\n"
        "Используйте команду <code>/watch UQ...</code> или кнопки меню ниже:",
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )


# --- ГЛАВНОЕ МЕНЮ (ИСПРАВЛЕН БАГ СО СТАТУСОМ ВЛ) ---
async def show_main_menu(event: Message | CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = event.from_user.id
    is_admin = user_id in ADMIN_IDS

    limit = await get_user_wallet_limit(user_id)
    count = await db.count_user_wallets(user_id)
    user = await db.get_user(user_id)

    if user_id in WHITELIST_USER_IDS:
        status_str = "⭐ Безлимитный (ВЛ)"
    elif user and user.get("sub_type") == "lifetime":
        status_str = "⭐ Подписка Навсегда"
    elif user and user.get("sub_until", 0) > int(time.time()):
        until_dt = datetime.fromtimestamp(user.get("sub_until", 0)).strftime("%d.%m.%Y")
        status_str = f"⭐ Подписка до {until_dt}"
    else:
        status_str = "Бесплатный (1 кошелек)"

    limit_str = "∞" if limit > 10 else str(limit)

    text = (
        f"{E_TON} <b>Главное меню трекера TON</b>\n\n"
        f"👤 <b>Ваш статус:</b> {status_str}\n"
        f"👀 <b>В наблюдении:</b> {count} из {limit_str}\n\n"
        f"💡 <i>Отправьте команду /watch <code>адрес</code> чтобы начать отслеживание.</i>"
    )

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=get_main_keyboard(is_admin), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=get_main_keyboard(is_admin), parse_mode="HTML")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await show_main_menu(message, state)


@router.callback_query(F.data == "back_to_main")
async def cb_back_to_main(callback: CallbackQuery, state: FSMContext):
    await show_main_menu(callback, state)


# --- НАСТРОЙКИ ВАЛЮТЫ ---
@router.callback_query(F.data == "settings_fiat")
async def cb_settings_fiat(callback: CallbackQuery):
    selected = parse_fiat_currencies(await db.get_user_fiat(callback.from_user.id))
    state = " + ".join(c.upper() for c in selected) if selected else "выключено"
    await callback.message.edit_text(
        "⚙️ <b>Настройки отображения цен:</b>\n\n"
        f"Выбрано: <b>{state}</b>\n\n"
        "Нажмите на валюту, чтобы включить её. Нажмите ещё раз — выключить.\n"
        "<i>Пример: 15.0000 TON (20.70 USD | 1742.40 RUB)</i>",
        reply_markup=get_fiat_keyboard(selected),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_fiat_"))
async def cb_toggle_fiat(callback: CallbackQuery):
    code = callback.data.replace("toggle_fiat_", "")
    selected = parse_fiat_currencies(await db.get_user_fiat(callback.from_user.id))

    if code == "off":
        selected = []
        await callback.answer("🔴 Цены выключены")
    elif code in selected:
        selected.remove(code)
        await callback.answer(f"▫️ {code.upper()} выключена")
    else:
        selected.append(code)
        await callback.answer(f"✅ {code.upper()} включена")

    # Пустой набор храним как "off", иначе get_user_fiat вернет дефолт
    await db.set_user_fiat(callback.from_user.id, ",".join(selected) if selected else "off")

    state = " + ".join(c.upper() for c in selected) if selected else "выключено"
    try:
        await callback.message.edit_text(
            "⚙️ <b>Настройки отображения цен:</b>\n\n"
            f"Выбрано: <b>{state}</b>\n\n"
            "Нажмите на валюту, чтобы включить её. Нажмите ещё раз — выключить.\n"
            "<i>Пример: 15.0000 TON (20.70 USD | 1742.40 RUB)</i>",
            reply_markup=get_fiat_keyboard(selected),
            parse_mode="HTML"
        )
    except Exception:
        pass

# --- МЕНЮ ФИЛЬТРОВ СУММ ---
def get_filters_keyboard(min_in: float, min_out: float) -> InlineKeyboardMarkup:
    in_text = f"{min_in:.2f} TON" if min_in > 0 else "Все (0 TON)"
    out_text = f"{min_out:.2f} TON" if min_out > 0 else "Все (0 TON)"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"📥 Мин. входящий: {in_text}", callback_data="set_filter_in_btn")],
            [InlineKeyboardButton(text=f"📤 Мин. исходящий: {out_text}", callback_data="set_filter_out_btn")],
            [InlineKeyboardButton(text="🔄 Сбросить фильтры", callback_data="reset_filters_btn")],
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main")]
        ]
    )

@router.callback_query(F.data == "settings_filters")
async def cb_settings_filters(callback: CallbackQuery):
    min_in, min_out = await db.get_user_filters(callback.from_user.id)
    text = (
        "🎯 <b>Настройки фильтрации сумм:</b>\n\n"
        "Вы можете скрыть мелкие переводы, чтобы бот не спамил уведомлениями.\n\n"
        f"📥 <b>Порог входящих:</b> <code>{min_in:.2f} TON</code>\n"
        f"📤 <b>Порог исходящих:</b> <code>{min_out:.2f} TON</code>\n\n"
        "<i>Транзакции меньше выбранной суммы будут игнорироваться.</i>"
    )
    await callback.message.edit_text(text, reply_markup=get_filters_keyboard(min_in, min_out), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "set_filter_in_btn")
async def cb_set_filter_in(callback: CallbackQuery, state: FSMContext):
    await state.set_state(FormStates.waiting_for_filter_in)
    await callback.message.answer(
        "📥 Введите минимальную сумму для <b>входящих</b> транзакций в TON (например: <code>5</code> или <code>0.5</code>):\n\n"
        "<i>Для отключения фильтра отправьте 0. Для отмены: /cancel</i>",
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(FormStates.waiting_for_filter_in)
async def process_filter_in(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Сумма должна быть числом. Отправьте текстом или /cancel.")
        return

    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Действие отменено.", reply_markup=get_main_keyboard())
        return

    try:
        val = float(message.text.strip().replace(",", "."))
        if val < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректное положительное число (например: <code>5</code> или <code>2.5</code>):", parse_mode="HTML")
        return

    await db.set_user_filter_in(message.from_user.id, val)
    await state.clear()
    
    status_text = f"от <b>{val:.2f} TON</b>" if val > 0 else "<b>выключен (все суммы)</b>"
    await message.answer(f"✅ Фильтр входящих установлен: {status_text}!", reply_markup=get_main_keyboard(), parse_mode="HTML")

@router.callback_query(F.data == "set_filter_out_btn")
async def cb_set_filter_out(callback: CallbackQuery, state: FSMContext):
    await state.set_state(FormStates.waiting_for_filter_out)
    await callback.message.answer(
        "📤 Введите минимальную сумму для <b>исходящих</b> транзакций в TON (например: <code>2</code> или <code>10</code>):\n\n"
        "<i>Для отключения фильтра отправьте 0. Для отмены: /cancel</i>",
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(FormStates.waiting_for_filter_out)
async def process_filter_out(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Сумма должна быть числом. Отправьте текстом или /cancel.")
        return

    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Действие отменено.", reply_markup=get_main_keyboard())
        return

    try:
        val = float(message.text.strip().replace(",", "."))
        if val < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите корректное положительное число (например: <code>10</code> или <code>1.5</code>):", parse_mode="HTML")
        return

    await db.set_user_filter_out(message.from_user.id, val)
    await state.clear()
    
    status_text = f"от <b>{val:.2f} TON</b>" if val > 0 else "<b>выключен (все суммы)</b>"
    await message.answer(f"✅ Фильтр исходящих установлен: {status_text}!", reply_markup=get_main_keyboard(), parse_mode="HTML")

@router.callback_query(F.data == "reset_filters_btn")
async def cb_reset_filters(callback: CallbackQuery):
    await db.set_user_filter_in(callback.from_user.id, 0.0)
    await db.set_user_filter_out(callback.from_user.id, 0.0)
    await callback.answer("✅ Фильтры сброшены!")
    await callback.message.edit_reply_markup(reply_markup=get_filters_keyboard(0.0, 0.0))


# --- ДОБАВЛЕНИЕ КОШЕЛЬКА В ВОТЧ-ЛИСТ (/watch) ---
@router.message(Command("watch"))
async def cmd_watch(message: Message, ton_client: TonApiClient):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "ℹ️ <b>Формат команды:</b>\n<code>/watch UQ...</code>\n\nОтправьте команду вместе с TON-адресом.",
            parse_mode="HTML"
        )
        return

    address = args[1].strip()
    await process_add_wallet(message.from_user.id, address, message, ton_client)


@router.callback_query(F.data == "add_wallet_btn")
async def cb_add_wallet_btn(callback: CallbackQuery, state: FSMContext):
    limit = await get_user_wallet_limit(callback.from_user.id)
    count = await db.count_user_wallets(callback.from_user.id)

    if count >= limit:
        await callback.message.answer(
            f"{E_REJECT} <b>Лимит исчерпан!</b>\n"
            f"Вам доступен максимум <b>{limit}</b> кошелек в наблюдении.\n\n"
            f"Для безлимитного вотч-листа оформите подписку за звезды ⭐",
            reply_markup=get_sub_keyboard(await get_star_prices()),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    await state.set_state(FormStates.waiting_for_watch_address)
    await callback.message.answer(f"{E_PENCIL} Отправьте TON-адрес для наблюдения:", parse_mode="HTML")
    await callback.answer()


@router.message(FormStates.waiting_for_watch_address)
async def form_watch_address(message: Message, state: FSMContext, ton_client: TonApiClient):
    if not message.text:
        await message.answer("❌ Адрес должен быть текстом. Отправьте адрес сообщением или /cancel.")
        return

    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Действие отменено.", reply_markup=get_main_keyboard())
        return

    await state.clear()
    await process_add_wallet(message.from_user.id, message.text.strip(), message, ton_client)


async def process_add_wallet(user_id: int, address: str, message: Message, ton_client: TonApiClient):
    limit = await get_user_wallet_limit(user_id)
    count = await db.count_user_wallets(user_id)

    if count >= limit:
        await message.answer(
            f"{E_REJECT} <b>Лимит исчерпан!</b>\n"
            f"Вам доступен максимум <b>{limit}</b> кошелек.\n\n"
            f"Оформите подписку ⭐ для добавления любого числа кошельков!",
            reply_markup=get_sub_keyboard(await get_star_prices()),
            parse_mode="HTML"
        )
        return

    wait_msg = await message.answer(f"{E_SEARCH} Проверяю адрес в сети TON...", parse_mode="HTML")
    user = await db.get_user(user_id)
    user_key = user.get("custom_api_key") if user else None

    acc_info = await ton_client.get_account(address, api_key=user_key)
    if not acc_info:
        await wait_msg.edit_text(
            f"{E_REJECT} <b>Некорректный адрес!</b> Кошелек не найден в сети TON.", parse_mode="HTML"
        )
        return

    raw_address = acc_info["address"]
    balance = acc_info.get("balance", 0) / 10**9

    events = await ton_client.get_events(raw_address, limit=1, api_key=user_key)
    last_event_id = events[0]["event_id"] if events else ""
    last_event_ts = int(events[0].get("timestamp") or 0) if events else 0

    success = await db.add_to_watchlist(user_id, raw_address, address, last_event_id, balance, last_event_ts)
    if not success:
        await wait_msg.edit_text("ℹ️ Этот кошелек уже находится в вашем списке наблюдения!", parse_mode="HTML")
        return

    await wait_msg.edit_text(
        f"✅ Кошелек <code>{address}</code> отправлен в наблюдение\n"
        f"{E_CHART} <b>Текущий баланс:</b> <code>{balance:.4f} TON</code>\n\n"
        f"{E_BELL} Бот уведомит о любых транзакциях по этому адресу!",
        parse_mode="HTML"
    )


# --- ПРОСМОТР ВОТЧ-ЛИСТА (/list) ---
@router.message(Command("list"))
@router.callback_query(F.data == "show_watchlist")
async def show_watchlist(event: Message | CallbackQuery):
    user_id = event.from_user.id
    wallets = await db.get_user_watchlist(user_id)

    if not wallets:
        text = "👀 <b>Ваш вотч-лист пуст.</b>\nДобавьте кошелек командой: <code>/watch UQ...</code>"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="add_wallet_btn")]])
    else:
        text = f"{E_TON} <b>Ваш вотч-лист ({len(wallets)}):</b>\n\n"
        kb_rows = []
        for idx, w in enumerate(wallets, start=1):
            label = (w.get("label") or "").strip()
            name = label if label else short_addr(w['user_address'])
            text += f"<b>{idx}.</b> <code>{name}</code>\n"
            text += f"    {E_CHART} Баланс: <code>{w['last_balance']:.4f} TON</code>\n\n"
            kb_rows.append([
                InlineKeyboardButton(text=f"ℹ️ Инфо #{idx}", callback_data=f"info_w_{w['id']}"),
                InlineKeyboardButton(text=f"❌ Удалить #{idx}", callback_data=f"del_w_{w['id']}")
            ])
        kb_rows.append([InlineKeyboardButton(text="➕ Добавить еще", callback_data="add_wallet_btn")])
        kb_rows.append([InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_main")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb, parse_mode="HTML")


def _parse_wallet_callback(data: str, prefix: str) -> int | None:
    """Безопасно достает wallet_id из callback_data вида prefix_<id>."""
    try:
        return int(data.replace(prefix, ""))
    except ValueError:
        return None


# --- УДАЛЕНИЕ С ПОДТВЕРЖДЕНИЕМ ---
@router.callback_query(F.data.startswith("del_w_"))
async def cb_delete_watched_wallet(callback: CallbackQuery):
    wallet_id = _parse_wallet_callback(callback.data, "del_w_")
    if wallet_id is None:
        await callback.answer("Ошибка запроса", show_alert=True)
        return

    wallet = await db.get_user_wallet(callback.from_user.id, wallet_id)
    if not wallet:
        await callback.answer("Кошелек не найден", show_alert=True)
        return

    label = (wallet.get("label") or "").strip()
    name = label if label else short_addr(wallet["user_address"])

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"dely_w_{wallet_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="show_watchlist")]
        ]
    )
    await callback.message.edit_text(
        f"⚠️ Точно удалить кошелек <code>{name}</code> из наблюдения?\n\n"
        "<i>История транзакций и обороты по нему также будут удалены.</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dely_w_"))
async def cb_delete_watched_wallet_confirm(callback: CallbackQuery):
    wallet_id = _parse_wallet_callback(callback.data, "dely_w_")
    if wallet_id is None:
        await callback.answer("Ошибка запроса", show_alert=True)
        return

    await db.remove_from_watchlist(callback.from_user.id, wallet_id)
    await callback.answer("Кошелек удален из наблюдения")
    await show_watchlist(callback)


# --- ИНФОРМАЦИЯ О КОШЕЛЬКЕ (обороты, история, имя) ---
def _fmt_turnover_row(label: str, stats: dict[str, float]) -> str:
    return (
        f"  • <b>{label}:</b> "
        f"<code>+{stats['in']:.4f} / -{stats['out']:.4f} TON</code>\n"
    )


@router.callback_query(F.data.startswith("info_w_"))
async def cb_wallet_info(callback: CallbackQuery):
    wallet_id = _parse_wallet_callback(callback.data, "info_w_")
    if wallet_id is None:
        await callback.answer("Ошибка запроса", show_alert=True)
        return

    wallet = await db.get_user_wallet(callback.from_user.id, wallet_id)
    if not wallet:
        await callback.answer("Кошелек не найден", show_alert=True)
        return

    label = (wallet.get("label") or "").strip()
    name = label if label else short_addr(wallet["user_address"])
    turnover = await db.get_turnover(wallet_id)
    added = wallet.get("created_at")
    added_str = datetime.fromtimestamp(added).strftime("%d.%m.%Y") if added else "—"

    text = (
        f"ℹ️ <b>Информация о кошельке</b>\n\n"
        f"👀 <b>Имя:</b> <code>{name}</code>\n"
        f"📍 <b>Адрес:</b> <code>{wallet['user_address']}</code>\n"
        f"{E_CHART} <b>Баланс:</b> <code>{wallet['last_balance']:.4f} TON</code>\n"
        f"📅 <b>В наблюдении с:</b> {added_str}\n\n"
        f"📊 <b>Оборот TON</b> <i>(приход / расход)</i>:\n"
        + _fmt_turnover_row("Сегодня", turnover["today"])
        + _fmt_turnover_row("Вчера", turnover["yesterday"])
        + _fmt_turnover_row("Неделя", turnover["week"])
        + _fmt_turnover_row("Месяц", turnover["month"])
        + _fmt_turnover_row("За все время", turnover["all"])
        + "\n<i>Оборот считается с момента добавления кошелька в наблюдение.</i>"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Название", callback_data=f"ren_w_{wallet_id}")],
            [InlineKeyboardButton(text="📜 История", callback_data=f"hist_w_{wallet_id}")],
            [InlineKeyboardButton(text="❌ Удалить", callback_data=f"del_w_{wallet_id}")],
            [InlineKeyboardButton(text="🔙 К списку", callback_data="show_watchlist")]
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# --- КАСТОМНОЕ ИМЯ КОШЕЛЬКА ---
@router.callback_query(F.data.startswith("ren_w_"))
async def cb_rename_wallet(callback: CallbackQuery, state: FSMContext):
    wallet_id = _parse_wallet_callback(callback.data, "ren_w_")
    if wallet_id is None:
        await callback.answer("Ошибка запроса", show_alert=True)
        return

    wallet = await db.get_user_wallet(callback.from_user.id, wallet_id)
    if not wallet:
        await callback.answer("Кошелек не найден", show_alert=True)
        return

    await state.set_state(FormStates.waiting_for_wallet_label)
    await state.update_data(wallet_id=wallet_id)
    await callback.message.answer(
        "✏️ Отправьте новое имя для кошелька (до 32 символов):\n\n"
        "<i>Для отмены отправьте /cancel. Чтобы убрать имя — отправьте 0</i>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(FormStates.waiting_for_wallet_label)
async def process_wallet_label(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Имя должно быть текстом. Попробуйте еще раз или /cancel.")
        return

    if message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Переименование отменено.")
        return

    data = await state.get_data()
    wallet_id = data.get("wallet_id")
    await state.clear()

    if not wallet_id:
        await message.answer("❌ Ошибка состояния, попробуйте заново.", reply_markup=get_main_keyboard())
        return

    label = "" if message.text.strip() == "0" else message.text.strip()[:32]
    await db.set_wallet_label(message.from_user.id, wallet_id, label)

    status = f"<code>{label}</code>" if label else "имя убрано (показывается адрес)"
    await message.answer(f"✅ Готово: {status}", reply_markup=get_main_keyboard(), parse_mode="HTML")


# --- ИСТОРИЯ ТРАНЗАКЦИЙ КОШЕЛЬКА ---
@router.callback_query(F.data.startswith("hist_w_"))
async def cb_wallet_history(callback: CallbackQuery):
    wallet_id = _parse_wallet_callback(callback.data, "hist_w_")
    if wallet_id is None:
        await callback.answer("Ошибка запроса", show_alert=True)
        return

    wallet = await db.get_user_wallet(callback.from_user.id, wallet_id)
    if not wallet:
        await callback.answer("Кошелек не найден", show_alert=True)
        return

    txs = await db.get_tx_log(wallet_id, limit=10)
    label = (wallet.get("label") or "").strip()
    name = label if label else short_addr(wallet["user_address"])

    if not txs:
        text = (
            f"📜 <b>История: {name}</b>\n\n"
            "Транзакций пока не было (или бот их еще не зафиксировал)."
        )
    else:
        text = f"📜 <b>История: {name}</b> <i>(последние {len(txs)})</i>\n\n"
        for tx in txs:
            icon = "📥" if tx["is_in"] else "📤"
            sign = "+" if tx["is_in"] else "-"
            dt = datetime.fromtimestamp(tx["ts"]).strftime("%d.%m %H:%M")
            kind = {"ton": "TON", "jetton": tx.get("symbol") or "token", "stake": "stake"}.get(tx["kind"], tx["kind"])
            text += f"{icon} {sign}{tx['amount']:.4f} {kind} — {dt}\n"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К инфо", callback_data=f"info_w_{wallet_id}")]
        ]
    )
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# --- ОПЛАТА ЗВЕЗДАМИ (TELEGRAM STARS) ---
@router.callback_query(F.data == "subscribe_menu")
async def cb_subscribe_menu(callback: CallbackQuery):
    prices = await get_star_prices()
    await callback.message.edit_text(
        "⭐ <b>Тарифы подписки на вотч-лист:</b>\n\n"
        f"• <b>1 месяц</b> — <code>{prices['month']} ⭐</code>\n"
        f"• <b>1 год</b> — <code>{prices['year']} ⭐</code>\n"
        f"• <b>Навсегда</b> — <code>{prices['lifetime']} ⭐</code>\n\n"
        "<i>С подпиской снимается лимит на 1 кошелек: можно добавлять неограниченное количество адресов.</i>",
        reply_markup=get_sub_keyboard(prices),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "buy_sub_month")
async def cb_buy_sub_month(callback: CallbackQuery):
    prices = await get_star_prices()
    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Подписка на 1 месяц",
        description="Безлимитный вотч-лист кошельков TON на 30 дней",
        payload="sub_month",
        currency="XTR",
        prices=[LabeledPrice(label="1 месяц", amount=prices["month"])],
        provider_token=""
    )
    await callback.answer()


@router.callback_query(F.data == "buy_sub_year")
async def cb_buy_sub_year(callback: CallbackQuery):
    prices = await get_star_prices()
    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Подписка на 1 год",
        description="Безлимитный вотч-лист кошельков TON на 365 дней",
        payload="sub_year",
        currency="XTR",
        prices=[LabeledPrice(label="1 год", amount=prices["year"])],
        provider_token=""
    )
    await callback.answer()


@router.callback_query(F.data == "buy_sub_lifetime")
async def cb_buy_sub_lifetime(callback: CallbackQuery):
    prices = await get_star_prices()
    await callback.bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Подписка Навсегда",
        description="Пожизненный безлимитный вотч-лист кошельков TON",
        payload="sub_lifetime",
        currency="XTR",
        prices=[LabeledPrice(label="Навсегда", amount=prices["lifetime"])],
        provider_token=""
    )
    await callback.answer()


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload

    if payload == "sub_month":
        sub_until = int(time.time()) + 30 * 86400
        await db.set_user_subscription(message.from_user.id, "month", sub_until)
        dt_str = datetime.fromtimestamp(sub_until).strftime("%d.%m.%Y")
        await message.answer(
            f"🎉 <b>Спасибо за оплату!</b>\nВам открыт безлимитный вотч-лист до <b>{dt_str}</b>.\n"
            f"Добавляйте любые кошельки через <code>/watch адрес</code>!",
            parse_mode="HTML"
        )
    elif payload == "sub_year":
        sub_until = int(time.time()) + 365 * 86400
        await db.set_user_subscription(message.from_user.id, "year", sub_until)
        dt_str = datetime.fromtimestamp(sub_until).strftime("%d.%m.%Y")
        await message.answer(
            f"🎉 <b>Спасибо за оплату!</b>\nВам открыт <b>годовой</b> безлимитный вотч-лист до <b>{dt_str}</b>.\n"
            f"Добавляйте любые кошельки через <code>/watch адрес</code>!",
            parse_mode="HTML"
        )
    elif payload == "sub_lifetime":
        await db.set_user_subscription(message.from_user.id, "lifetime", 0)
        await message.answer(
            "🎉 <b>Спасибо за оплату!</b>\nВам навсегда открыт <b>пожизненный безлимитный вотч-лист</b>!",
            parse_mode="HTML"
        )


# --- ИНЛАЙН-РЕЖИМ (@tonancbot адрес) ---
def is_potential_ton_target(query: str) -> bool:
    """Проверяет, похож ли ввод на готовый адрес или домен."""
    q = query.strip().lower()
    # Домен .ton или .t.me
    if q.endswith(".ton") or q.endswith(".t.me"):
        return len(q) >= 5
    # Адрес в friendly формате (EQ... / UQ...) или raw (0:...)
    if (q.startswith("eq") or q.startswith("uq") or q.startswith("ef") or q.startswith("uf")) and len(q) >= 48:
        return True
    if q.startswith("0:") and len(q) == 66:
        return True
    return False


@router.inline_query()
async def inline_query_handler(inline_query: InlineQuery, ton_client: TonApiClient):
    query = inline_query.query.strip()
    results = []

    user = await db.get_user(inline_query.from_user.id)
    user_key = user.get("custom_api_key") if user else None

    # 1. Если поле ввода пустое — предлагаем свой кошелек из вотч-листа
    if not query:
        wallets = await db.get_user_watchlist(inline_query.from_user.id)
        if wallets:
            w = wallets[0]
            acc = await ton_client.get_account(w["raw_address"], api_key=user_key)
            bal = (acc.get("balance", 0) / 10**9) if acc else w["last_balance"]
            text = (
                f"{E_TON} <b>Кошелек из вотч-листа</b>\n\n"
                f"{E_LOC} <b>Адрес:</b> <code>{w['user_address']}</code>\n"
                f"{E_CHART} <b>Баланс:</b> <code>{bal:.4f} TON</code>\n"
                f"{E_LINK} <a href=\"https://tonviewer.com/{w['user_address']}\">Tonviewer</a>"
            )
            results.append(
                InlineQueryResultArticle(
                    id="my_w",
                    title=f"💎 {short_addr(w['user_address'])}",
                    description=f"Баланс: {bal:.4f} TON",
                    input_message_content=InputTextMessageContent(message_text=text, parse_mode="HTML", disable_web_page_preview=True)
                )
            )
        await inline_query.answer(results, cache_time=60, is_personal=True)
        return

    if not is_potential_ton_target(query):
        results.append(
            InlineQueryResultArticle(
                id="typing_hint",
                title="⏳ Введите адрес или домен .ton",
                description="Поддерживаются: UQ..., EQ..., а также домены (например, wallet.ton)",
                input_message_content=InputTextMessageContent(
                    message_text="💡 Введите полный адрес (UQ... / EQ...) или домен (например, <code>wallet.ton</code>).",
                    parse_mode="HTML"
                )
            )
        )
        await inline_query.answer(results, cache_time=30, is_personal=True)
        return

    acc_info = await ton_client.get_account(query, api_key=user_key)
    q_hash = hashlib.md5(query.encode()).hexdigest()

    if not acc_info:
        results.append(
            InlineQueryResultArticle(
                id=q_hash,
                title="❌ Кошелек или домен не найден",
                description=f"Не удалось найти: {query}",
                input_message_content=InputTextMessageContent(
                    message_text=f"❌ Кошелек или домен <code>{query}</code> не найден в сети TON.",
                    parse_mode="HTML"
                )
            )
        )
        await inline_query.answer(results, cache_time=30, is_personal=True)
        return

    bal = acc_info.get("balance", 0) / 10**9
    raw_addr = acc_info.get("address", query)
    domain_label = f" ({acc_info['domain']})" if "domain" in acc_info else ""

    text = (
        f"{E_TON} <b>Информация о кошельке TON</b>\n\n"
        f"{E_LOC} <b>Адрес:</b> <code>{raw_addr}</code>{domain_label}\n"
        f"{E_CHART} <b>Баланс:</b> <code>{bal:.4f} TON</code>\n"
        f"{E_LINK} <a href=\"https://tonviewer.com/{raw_addr}\">Смотреть в Tonviewer</a>"
    )
    btn = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Открыть в Tonviewer", url=f"https://tonviewer.com/{raw_addr}")]
        ]
    )
    results.append(
        InlineQueryResultArticle(
            id=q_hash,
            title=f"💎 Баланс: {bal:.4f} TON{domain_label}",
            description=f"Адрес: {short_addr(raw_addr)}",
            input_message_content=InputTextMessageContent(message_text=text, parse_mode="HTML", disable_web_page_preview=True),
            reply_markup=btn
        )
    )
    await inline_query.answer(results, cache_time=60, is_personal=True)
