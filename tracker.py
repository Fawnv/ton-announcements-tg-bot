import asyncio
import html
import logging
from datetime import datetime, timezone
from aiogram import Bot

from database import Database
from ton_api import TonApiClient

logger = logging.getLogger(__name__)

# --- Премиум-эмодзи ---
E_COMMENT = '<tg-emoji emoji-id="5443038326535759644">💬</tg-emoji>'
E_IN      = '<tg-emoji emoji-id="5443127283898405358">📥</tg-emoji>'
E_OUT     = '<tg-emoji emoji-id="5445355530111437729">📤</tg-emoji>'
E_TON     = '<tg-emoji emoji-id="5427168083074628963">💎</tg-emoji>'
E_USER    = '<tg-emoji emoji-id="5258011929993026890">👤</tg-emoji>'
E_TIME    = '<tg-emoji emoji-id="5382194935057372936">🕒</tg-emoji>'
E_CHART   = '<tg-emoji emoji-id="5231200819986047254">📊</tg-emoji>'
E_GREEN   = '<tg-emoji emoji-id="5416081784641168838">🟢</tg-emoji>'
E_RED     = '<tg-emoji emoji-id="5411225014148014586">🔴</tg-emoji>'
E_LINK    = '<tg-emoji emoji-id="5271604874419647061">🔗</tg-emoji>'
E_LOC     = '<tg-emoji emoji-id="5391032818111363540">📍</tg-emoji>'

STATUS_WAITING = "⏳ <b>Статус:</b> <i>Отправлено, проверяем зачисление на адрес получателя...</i>"
STATUS_DELIVERED = "✅ <b>Статус:</b> <b>Средства успешно зачислены на кошелек получателя!</b>"

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

def format_fiat_amount(amount_ton: float, rates: dict[str, float], mode: str) -> str:
    """Форматирует строку с ценой в фиате по выбранному режиму."""
    if mode == "off" or not rates:
        return ""

    usd = rates.get("USD", 0.0)
    eur = rates.get("EUR", 0.0)
    rub = rates.get("RUB", 0.0)

    parts = []
    if mode == "usd" and usd:
        parts.append(f"{amount_ton * usd:.2f} USD")
    elif mode == "eur" and eur:
        parts.append(f"{amount_ton * eur:.2f} EUR")
    elif mode == "rub" and rub:
        parts.append(f"{amount_ton * rub:.2f} RUB")
    elif mode == "usd_rub":
        if usd: parts.append(f"{amount_ton * usd:.2f} USD")
        if rub: parts.append(f"{amount_ton * rub:.2f} RUB")
    elif mode == "all":
        if usd: parts.append(f"{amount_ton * usd:.2f} USD")
        if eur: parts.append(f"{amount_ton * eur:.2f} EUR")
        if rub: parts.append(f"{amount_ton * rub:.2f} RUB")

    return f"({ ' | '.join(parts) })" if parts else ""

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
            "ℹ️ <b>Статус:</b> <i>Отправлено (проверьте получение в Tonviewer)</i>"
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
    last_event_id = wallet.get("last_event_id")
    stored_balance = float(wallet.get("last_balance") or 0.0)
    user_key = wallet.get("custom_api_key")
    min_in = float(wallet.get("min_incoming") or 0.0)
    min_out = float(wallet.get("min_outgoing") or 0.0)
    

    events = await ton_client.get_events(raw_address, limit=10, api_key=user_key)
    if not events:
        return

    acc_info = await ton_client.get_account(raw_address, api_key=user_key)
    current_balance = (acc_info.get("balance", 0) / 10**9) if acc_info else stored_balance

    if not last_event_id:
        await db.update_watched_last_event_and_balance(wallet_id, events[0]["event_id"], current_balance)
        return

    if events[0]["event_id"] == last_event_id:
        if abs(stored_balance - current_balance) > 1e-6:
            await db.update_watched_last_event_and_balance(wallet_id, last_event_id, current_balance)
        return

    new_events = []
    for ev in events:
        if ev["event_id"] == last_event_id:
            break
        new_events.append(ev)

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

                if is_in and min_in > 0 and amount_ton < min_in:
                    continue #пропуск для входящего
                if not is_in and min_out > 0 and amount_ton < min_out:
                    continue #пропуск для исходящего



                icon = E_IN if is_in else E_OUT
                tx_title = "Входящий перевод TON" if is_in else "Исходящий перевод TON"
                party_label = "От кого" if is_in else "Кому"
                party_addr = sender if is_in else recipient

                fiat_mode = wallet.get("fiat_currency") or "usd_rub"
                rates = await ton_client.get_ton_rates(api_key=user_key)
                fiat_str = format_fiat_amount(amount_ton, rates, fiat_mode)
                fiat_display = f" <i>{fiat_str}</i>" if fiat_str else ""

                text = (
                    f"{icon} <b>{tx_title}</b>\n\n"
                    f"👀 <b>Вотч-лист:</b> <code>{short_addr(user_address)}</code>\n"
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
                icon = E_IN if is_in else E_OUT
                tx_title = f"Входящий перевод {symbol}" if is_in else f"Исходящий перевод {symbol}"
                party_label = "От кого" if is_in else "Кому"
                party_addr = sender if is_in else recipient

                text = (
                    f"{icon} <b>{tx_title}</b>\n\n"
                    f"👀 <b>Вотч-лист:</b> <code>{short_addr(user_address)}</code>\n"
                    f"🪙 <b>Сумма:</b> <code>{amount:.4f} {symbol}</code>\n"
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

    await db.update_watched_last_event_and_balance(wallet_id, events[0]["event_id"], current_balance)

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
