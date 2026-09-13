import asyncio
import html
import logging
import time
from datetime import datetime, timezone
from aiogram import Bot

from database import Database
from ton_api import TonApiClient
from emojis import (
    E_COMMENT, E_IN, E_OUT, E_TON, E_USER, E_TIME, E_CHART, E_GREEN, E_RED,
    E_LINK, E_NFT, E_STAKE, E_GEAR, E_SCALE, E_WATCH, E_JETTON, E_OK, E_INFO, E_WAIT
)

logger = logging.getLogger(__name__)

STATUS_WAITING = f"{E_WAIT} <b>Статус:</b> <i>Отправлено, проверяем зачисление на адрес получателя...</i>"
STATUS_DELIVERED = f"{E_OK} <b>Статус:</b> <b>Средства успешно зачислены на кошелек получателя!</b>"

# Легаси-значения fiat_currency, сохраненные до перехода на набор валют
_LEGACY_FIAT = {
    "usd": "usd",
    "eur": "eur",
    "rub": "rub",
    "usd_rub": "usd,rub",
    "all": "usd,eur,rub",
    "off": "",
}
_VALID_FIAT = ("usd", "eur", "rub")


def parse_fiat_currencies(raw: str | None) -> list[str]:
    """Нормализует настройку валют: 'usd,rub' -> ['usd','rub'].

    Понимает старые режимы (usd_rub, all, off) и дефолт usd_rub."""
    if not raw:
        return ["usd", "rub"]
    raw = raw.strip().lower()
    if raw in _LEGACY_FIAT:
        raw = _LEGACY_FIAT[raw]
    return [c for c in raw.split(",") if c in _VALID_FIAT]


def short_addr(addr: str) -> str:
    if len(addr) > 16:
        return f"{addr[:6]}...{addr[-6:]}"
    return addr

def format_ton_diff(delta: float) -> str:
    if abs(delta) < 1e-6:
        return "без изменений"
    if delta > 0:
        return f"{E_GREEN} +{delta:.4f} TON"
    return f"{E_RED} {delta:.4f} TON"

def format_fiat_amount(amount_ton: float, rates: dict[str, float], currencies: list[str]) -> str:
    """Форматирует строку с ценой в выбранных пользователем валютах."""
    if not currencies or not rates:
        return ""

    parts = []
    for cur in ("usd", "eur", "rub"):
        if cur not in currencies:
            continue
        rate = rates.get(cur.upper(), 0.0)
        if rate:
            parts.append(f"{amount_ton * rate:.2f} {cur.upper()}")

    return f"({' | '.join(parts)})" if parts else ""

async def watch_outgoing_delivery(
    bot: Bot,
    ton_client: TonApiClient,
    user_id: int,
    message_id: int,
    recipient_addr: str,
    sender_addr: str,
    amount_nano: int,
    event_id: str,
    base_text: str,
    custom_key: str | None = None
):
    """Фоново проверяет кошелек получателя до зачисления."""
    for _ in range(45):
        await asyncio.sleep(4)
        try:
            rec_events = await ton_client.get_events(recipient_addr, limit=10, api_key=custom_key)
            delivered = False

            for r_ev in rec_events:
                if r_ev.get("event_id") == event_id:
                    delivered = True
                    break

                for act in r_ev.get("actions", []):
                    if act.get("status") != "ok":
                        continue
                    tt = act.get("TonTransfer") or act.get("JettonTransfer")
                    if tt:
                        s = tt.get("sender", {}).get("address", "").lower()
                        r = tt.get("recipient", {}).get("address", "").lower()
                        amt = int(tt.get("amount", 0))
                        if s == sender_addr.lower() and r == recipient_addr.lower() and amt == amount_nano:
                            delivered = True
                            break
                if delivered:
                    break

            if delivered:
                updated_text = base_text.replace(STATUS_WAITING, STATUS_DELIVERED)
                await bot.edit_message_text(
                    text=updated_text,
                    chat_id=user_id,
                    message_id=message_id,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                return
        except Exception as e:
            logger.error(f"Ошибка проверки доставки: {e}")

    try:
        timeout_text = base_text.replace(
            STATUS_WAITING,
            f"{E_INFO} <b>Статус:</b> <i>Отправлено (проверьте получение в Tonviewer)</i>"
        )
        await bot.edit_message_text(
            text=timeout_text,
            chat_id=user_id,
            message_id=message_id,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except Exception:
        pass

async def check_wallet_events(wallet: dict, bot: Bot, db: Database, ton_client: TonApiClient):
    wallet_id = wallet["id"]
    user_id = wallet["user_id"]
    raw_address = wallet["raw_address"]
    user_address = wallet["user_address"]
    wallet_label = (wallet.get("label") or "").strip()
    # Имя задает пользователь — экранируем, иначе битый HTML сломает отправку уведомлений
    display_name = html.escape(wallet_label) if wallet_label else short_addr(user_address)
    last_event_id = wallet.get("last_event_id")
    last_event_ts = int(wallet.get("last_event_ts") or 0)
    stored_balance = float(wallet.get("last_balance") or 0.0)
    user_key = wallet.get("custom_api_key")
    min_in = float(wallet.get("min_incoming") or 0.0)
    min_out = float(wallet.get("min_outgoing") or 0.0)
    fiat_currencies = parse_fiat_currencies(wallet.get("fiat_currency"))

    events = await ton_client.get_events(raw_address, limit=10, api_key=user_key)
    if not events:
        return

    acc_info = await ton_client.get_account(raw_address, api_key=user_key)
    current_balance = (acc_info.get("balance", 0) / 10**9) if acc_info else stored_balance

    newest_ts = int(events[0].get("timestamp") or 0)

    if not last_event_id:
        await db.update_watched_last_event_and_balance(wallet_id, events[0]["event_id"], current_balance, newest_ts)
        return

    if events[0]["event_id"] == last_event_id:
        diff = current_balance - stored_balance
        if abs(diff) > 0.01:
            # Баланс изменился, но новых событий нет: стейкинг, nominator pools,
            # награды за валидацию и т.п.
            diff_text = format_ton_diff(diff)
            text = (
                f"{E_SCALE} <b>Изменение баланса без транзакций</b>\n\n"
                f"{E_WATCH} <b>Вотч-лист:</b> <code>{display_name}</code>\n"
                f"{E_CHART} <b>Баланс:</b>\n"
                f"  • <b>Было:</b> <code>{stored_balance:.4f} TON</code>\n"
                f"  • <b>Стало:</b> <code>{current_balance:.4f} TON</code> ({diff_text})\n\n"
                f"<i>Обычно это начисление стейкинга или награда пула номинаторов.</i>\n"
                f"{E_LINK} <a href=\"https://tonviewer.com/{raw_address}\">Tonviewer</a>"
            )
            try:
                await bot.send_message(user_id, text, parse_mode="HTML", disable_web_page_preview=True)
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления о дрифте баланса: {e}")
            await db.update_watched_last_event_and_balance(wallet_id, last_event_id, current_balance, newest_ts)
        elif abs(diff) > 1e-6:
            await db.update_watched_last_event_and_balance(wallet_id, last_event_id, current_balance, newest_ts)
        return

    new_events = []
    last_id_found = False
    for ev in events:
        if ev["event_id"] == last_event_id:
            last_id_found = True
            break
        new_events.append(ev)

    if not last_id_found:
        # last_event_id выпал из окна последних событий (даунтайм бота, всплеск
        # транзакций, переиндексация события в TonAPI). Чтобы не заспамить
        # пользователя старой историей, берем только события новее времени
        # последней обработки.
        if last_event_ts > 0:
            new_events = [ev for ev in events if ev.get("timestamp", 0) > last_event_ts]
        else:
            new_events = []

    new_events.reverse()

    event_deltas = []
    for ev in new_events:
        d = 0.0
        for act in ev.get("actions", []):
            if act.get("status") != "ok":
                continue
            if act.get("type") == "TonTransfer":
                tt = act.get("TonTransfer", {})
                amt = tt.get("amount", 0) / 10**9
                r = tt.get("recipient", {}).get("address", "").lower()
                s = tt.get("sender", {}).get("address", "").lower()
                if r == raw_address.lower():
                    d += amt
                elif s == raw_address.lower():
                    d -= amt
        event_deltas.append(d)

    total_delta = sum(event_deltas)
    start_bal = stored_balance if stored_balance > 0 else max(0.0, current_balance - total_delta)
    running_balance = start_bal

    # Курс запрашиваем один раз на проход, а не для каждой транзакции
    rates = await ton_client.get_ton_rates(api_key=user_key) if fiat_currencies else {}

    for i, (ev, delta) in enumerate(zip(new_events, event_deltas)):
        b_before = running_balance
        if i == len(new_events) - 1 and current_balance > 0:
            if delta < 0 and current_balance < b_before:
                b_after = current_balance
            elif delta > 0 and current_balance >= b_before:
                b_after = current_balance
            else:
                b_after = max(0.0, b_before + delta)
        else:
            b_after = max(0.0, b_before + delta)

        eff_delta = b_after - b_before
        running_balance = b_after

        event_id = ev.get("event_id", "")
        actions = ev.get("actions", [])
        ts = ev.get("timestamp")
        ts_int = int(ts) if ts else int(time.time())
        dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC") if ts else ""
        diff_text = format_ton_diff(eff_delta)

        for act in actions:
            if act.get("status") != "ok":
                continue

            act_type = act.get("type")

            if act_type == "TonTransfer":
                transfer = act.get("TonTransfer", {})
                sender = transfer.get("sender", {}).get("address", "")
                recipient = transfer.get("recipient", {}).get("address", "")
                amount_nano = int(transfer.get("amount", 0))
                amount_ton = amount_nano / 10**9
                comment = transfer.get("comment", "")

                is_in = recipient.lower() == raw_address.lower()

                # Пишем в журнал до фильтров, чтобы обороты считались честно
                await db.add_tx_log(user_id, wallet_id, ts_int, is_in, amount_ton, "ton", "TON", event_id)

                if is_in and min_in > 0 and amount_ton < min_in:
                    continue #пропуск для входящего
                if not is_in and min_out > 0 and amount_ton < min_out:
                    continue #пропуск для исходящего

                icon = E_IN if is_in else E_OUT
                tx_title = "Входящий перевод TON" if is_in else "Исходящий перевод TON"
                party_label = "От кого" if is_in else "Кому"
                party_addr = sender if is_in else recipient

                fiat_str = format_fiat_amount(amount_ton, rates, fiat_currencies)
                fiat_display = f" <i>{fiat_str}</i>" if fiat_str else ""

                text = (
                    f"{icon} <b>{tx_title}</b>\n\n"
                    f"{E_WATCH} <b>Вотч-лист:</b> <code>{display_name}</code>\n"
                    f"{E_TON} <b>Сумма:</b> <code>{amount_ton:.4f} TON</code>{fiat_display}\n"
                    f"{E_USER} <b>{party_label}:</b> <code>{short_addr(party_addr)}</code>\n"
                )

                if comment:
                    text += f"{E_COMMENT} <b>Комментарий:</b> <i>{html.escape(comment)}</i>\n"
                if dt_str:
                    text += f"{E_TIME} <b>Время:</b> {dt_str}\n"

                text += (
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E_CHART} <b>Баланс TON:</b>\n"
                    f"  • <b>До:</b> <code>{b_before:.4f} TON</code>\n"
                    f"  • <b>После:</b> <code>{b_after:.4f} TON</code> ({diff_text})\n"
                )

                if not is_in:
                    text += f"━━━━━━━━━━━━━━━━━━\n{STATUS_WAITING}\n"

                text += f"{E_LINK} <a href=\"https://tonviewer.com/transaction/{event_id}\">Tonviewer</a>"

                try:
                    sent_msg = await bot.send_message(user_id, text, parse_mode="HTML", disable_web_page_preview=True)
                    if not is_in and recipient:
                        asyncio.create_task(
                            watch_outgoing_delivery(
                                bot=bot,
                                ton_client=ton_client,
                                user_id=user_id,
                                message_id=sent_msg.message_id,
                                recipient_addr=recipient,
                                sender_addr=raw_address,
                                amount_nano=amount_nano,
                                event_id=event_id,
                                base_text=text,
                                custom_key=user_key
                            )
                        )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления: {e}")

            elif act_type == "JettonTransfer":
                transfer = act.get("JettonTransfer", {})
                jetton = transfer.get("jetton", {})
                symbol = jetton.get("symbol", "Токен")
                decimals = jetton.get("decimals", 9)
                amount = int(transfer.get("amount", 0)) / (10 ** decimals)
                amount_nano = int(transfer.get("amount", 0))

                sender = transfer.get("sender", {}).get("address", "")
                recipient = transfer.get("recipient", {}).get("address", "")
                comment = transfer.get("comment", "")

                is_in = recipient.lower() == raw_address.lower()

                await db.add_tx_log(user_id, wallet_id, ts_int, is_in, amount, "jetton", symbol, event_id)

                icon = E_IN if is_in else E_OUT
                tx_title = f"Входящий перевод {symbol}" if is_in else f"Исходящий перевод {symbol}"
                party_label = "От кого" if is_in else "Кому"
                party_addr = sender if is_in else recipient

                text = (
                    f"{icon} <b>{tx_title}</b>\n\n"
                    f"{E_WATCH} <b>Вотч-лист:</b> <code>{display_name}</code>\n"
                    f"{E_JETTON} <b>Сумма:</b> <code>{amount:.4f} {symbol}</code>\n"
                    f"{E_USER} <b>{party_label}:</b> <code>{short_addr(party_addr)}</code>\n"
                )
                if comment:
                    text += f"{E_COMMENT} <b>Комментарий:</b> <i>{html.escape(comment)}</i>\n"
                if dt_str:
                    text += f"{E_TIME} <b>Время:</b> {dt_str}\n"

                text += (
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E_CHART} <b>Баланс TON:</b>\n"
                    f"  • <b>До:</b> <code>{b_before:.4f} TON</code>\n"
                    f"  • <b>После:</b> <code>{b_after:.4f} TON</code> ({diff_text})\n"
                )

                if not is_in:
                    text += f"━━━━━━━━━━━━━━━━━━\n{STATUS_WAITING}\n"

                text += f"{E_LINK} <a href=\"https://tonviewer.com/transaction/{event_id}\">Tonviewer</a>"

                try:
                    sent_msg = await bot.send_message(user_id, text, parse_mode="HTML", disable_web_page_preview=True)
                    if not is_in and recipient:
                        asyncio.create_task(
                            watch_outgoing_delivery(
                                bot=bot,
                                ton_client=ton_client,
                                user_id=user_id,
                                message_id=sent_msg.message_id,
                                recipient_addr=recipient,
                                sender_addr=raw_address,
                                amount_nano=amount_nano,
                                event_id=event_id,
                                base_text=text,
                                custom_key=user_key
                            )
                        )
                except Exception as e:
                    logger.error(f"Ошибка отправки Jetton уведомления: {e}")

            elif act_type == "NftItemTransfer":
                nft_data = act.get("NftItemTransfer", {})
                nft_item = nft_data.get("nft", {}) or {}
                nft_name = nft_item.get("name") or ""
                nft_addr = nft_item.get("address", "")
                sender = nft_data.get("sender", {}).get("address", "")
                recipient = nft_data.get("recipient", {}).get("address", "")

                is_in = recipient.lower() == raw_address.lower()
                icon = E_IN if is_in else E_OUT
                tx_title = "Входящий NFT-перевод" if is_in else "Исходящий NFT-перевод"
                party_label = "От кого" if is_in else "Кому"
                party_addr = sender if is_in else recipient
                nft_display = html.escape(nft_name) if nft_name else short_addr(nft_addr)

                text = (
                    f"{E_NFT} <b>{tx_title}</b>\n\n"
                    f"{E_WATCH} <b>Вотч-лист:</b> <code>{display_name}</code>\n"
                    f"{E_NFT} <b>NFT:</b> <code>{nft_display}</code>\n"
                    f"{E_USER} <b>{party_label}:</b> <code>{short_addr(party_addr)}</code>\n"
                )
                if dt_str:
                    text += f"{E_TIME} <b>Время:</b> {dt_str}\n"
                text += f"{E_LINK} <a href=\"https://tonviewer.com/transaction/{event_id}\">Tonviewer</a>"

                try:
                    await bot.send_message(user_id, text, parse_mode="HTML", disable_web_page_preview=True)
                except Exception as e:
                    logger.error(f"Ошибка отправки NFT уведомления: {e}")

            elif act_type in ("DepositStake", "WithdrawStake"):
                stake_data = act.get(act_type, {})
                amount_ton = int(stake_data.get("amount", 0)) / 10**9
                staker = stake_data.get("staker", {}).get("address", "")

                if amount_ton <= 0:
                    continue

                is_in = act_type == "WithdrawStake"
                tx_title = "Вывод из стейкинга" if is_in else "Пополнение стейкинга"
                icon = E_IN if is_in else E_OUT

                await db.add_tx_log(user_id, wallet_id, ts_int, is_in, amount_ton, "stake", "TON", event_id)

                text = (
                    f"{E_STAKE} <b>{tx_title}</b>\n\n"
                    f"{E_WATCH} <b>Вотч-лист:</b> <code>{display_name}</code>\n"
                    f"{E_TON} <b>Сумма:</b> <code>{amount_ton:.4f} TON</code>\n"
                )
                if staker:
                    text += f"{E_USER} <b>Стейкер:</b> <code>{short_addr(staker)}</code>\n"
                if dt_str:
                    text += f"{E_TIME} <b>Время:</b> {dt_str}\n"
                text += f"{E_LINK} <a href=\"https://tonviewer.com/transaction/{event_id}\">Tonviewer</a>"

                try:
                    await bot.send_message(user_id, text, parse_mode="HTML", disable_web_page_preview=True)
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления о стейкинге: {e}")

            elif act_type == "SmartContractExec":
                sce = act.get("SmartContractExec", {})
                ton_attached = int(sce.get("ton_attached", 0)) / 10**9
                executor = sce.get("executor", {}).get("address", "")
                contract = sce.get("contract", {}).get("address", "")
                operation = sce.get("operation", "")

                # Уведомляем, только если вотч-кошелек — инициатор или контракт
                if executor.lower() != raw_address.lower() and contract.lower() != raw_address.lower():
                    continue

                text = (
                    f"{E_GEAR} <b>Вызов смарт-контракта</b>\n\n"
                    f"{E_WATCH} <b>Вотч-лист:</b> <code>{display_name}</code>\n"
                    f"{E_USER} <b>Инициатор:</b> <code>{short_addr(executor)}</code>\n"
                    f"{E_GEAR} <b>Контракт:</b> <code>{short_addr(contract)}</code>\n"
                )
                if operation:
                    text += f"{E_GEAR} <b>Операция:</b> <code>{html.escape(str(operation))}</code>\n"
                if ton_attached > 0:
                    text += f"{E_TON} <b>Приложено:</b> <code>{ton_attached:.4f} TON</code>\n"
                if dt_str:
                    text += f"{E_TIME} <b>Время:</b> {dt_str}\n"
                text += f"{E_LINK} <a href=\"https://tonviewer.com/transaction/{event_id}\">Tonviewer</a>"

                try:
                    await bot.send_message(user_id, text, parse_mode="HTML", disable_web_page_preview=True)
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления о вызове контракта: {e}")

    await db.update_watched_last_event_and_balance(wallet_id, events[0]["event_id"], current_balance, newest_ts)

async def start_tx_tracker(bot: Bot, db: Database, ton_client: TonApiClient, interval: int = 20):
    logger.info("Фоновый трекер вотч-листа запущен.")
    while True:
        try:
            wallets = await db.get_all_watched_wallets()
            for w in wallets:
                try:
                    await check_wallet_events(w, bot, db, ton_client)
                except Exception as e:
                    logger.error(f"Ошибка проверки кошелька #{w['id']}: {e}")
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка цикла трекера: {e}")

        await asyncio.sleep(interval)
