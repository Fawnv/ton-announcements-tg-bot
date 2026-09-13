import asyncio
import html
import logging
from datetime import datetime, timezone
from aiogram import Bot

from database import Database
from ton_api import TonApiClient

logger = logging.getLogger(__name__)

def short_addr(addr: str) -> str:
    if len(addr) > 16:
        return f"{addr[:6]}...{addr[-6:]}"
    return addr

async def check_user_events(user: dict, bot: Bot, db: Database, ton_client: TonApiClient):
    user_id = user["user_id"]
    raw_address = user["raw_address"]
    last_event_id = user.get("last_event_id")

    events = await ton_client.get_events(raw_address, limit=10)
    if not events:
        return

    if not last_event_id:
        await db.update_last_event_id(user_id, events[0]["event_id"])
        return

    if events[0]["event_id"] == last_event_id:
        return

    new_events = []
    for ev in events:
        if ev["event_id"] == last_event_id:
            break
        new_events.append(ev)

    new_events.reverse()

    acc_info = await ton_client.get_account(raw_address)
    current_balance = (acc_info.get("balance", 0) / 10**9) if acc_info else 0.0

    for ev in new_events:
        event_id = ev.get("event_id", "")
        actions = ev.get("actions", [])
        ts = ev.get("timestamp")
        dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y %H:%M:%S UTC") if ts else ""

        for act in actions:
            if act.get("status") != "ok":
                continue

            act_type = act.get("type")

            if act_type == "TonTransfer":
                transfer = act.get("TonTransfer", {})
                sender = transfer.get("sender", {}).get("address", "")
                recipient = transfer.get("recipient", {}).get("address", "")
                amount_ton = transfer.get("amount", 0) / 10**9
                comment = transfer.get("comment", "")

                is_in = recipient.lower() == raw_address.lower()
                icon = "📥" if is_in else "📤"
                tx_title = "Входящий перевод TON" if is_in else "Исходящий перевод TON"
                party_label = "От кого" if is_in else "Кому"
                party_addr = sender if is_in else recipient

                text = (
                    f"{icon} <b>{tx_title}</b>\n\n"
                    f"💎 <b>Сумма:</b> <code>{amount_ton:.4f} TON</code>\n"
                    f"👤 <b>{party_label}:</b> <code>{short_addr(party_addr)}</code>\n"
                )
                if comment:
                    text += f"💬 <b>Комментарий:</b> <i>{html.escape(comment)}</i>\n"
                if dt_str:
                    text += f"🕒 <b>Время:</b> {dt_str}\n"

                text += (
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💰 <b>Оставшийся баланс:</b> <code>{current_balance:.4f} TON</code>\n"
                    f"🔗 <a href=\"https://tonviewer.com/transaction/{event_id}\">Tonviewer</a>"
                )

                try:
                    await bot.send_message(user_id, text, parse_mode="HTML", disable_web_page_preview=True)
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление пользователю {user_id}: {e}")

            elif act_type == "JettonTransfer":
                transfer = act.get("JettonTransfer", {})
                jetton = transfer.get("jetton", {})
                symbol = jetton.get("symbol", "Токен")
                decimals = jetton.get("decimals", 9)
                amount = int(transfer.get("amount", 0)) / (10 ** decimals)

                sender = transfer.get("sender", {}).get("address", "")
                recipient = transfer.get("recipient", {}).get("address", "")
                comment = transfer.get("comment", "")

                is_in = recipient.lower() == raw_address.lower()
                icon = "📥" if is_in else "📤"
                tx_title = f"Входящий перевод {symbol}" if is_in else f"Исходящий перевод {symbol}"
                party_label = "От кого" if is_in else "Кому"
                party_addr = sender if is_in else recipient

                text = (
                    f"{icon} <b>{tx_title}</b>\n\n"
                    f"🪙 <b>Сумма:</b> <code>{amount:.4f} {symbol}</code>\n"
                    f"👤 <b>{party_label}:</b> <code>{short_addr(party_addr)}</code>\n"
                )
                if comment:
                    text += f"💬 <b>Комментарий:</b> <i>{html.escape(comment)}</i>\n"
                if dt_str:
                    text += f"🕒 <b>Время:</b> {dt_str}\n"

                text += (
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"💰 <b>Баланс TON:</b> <code>{current_balance:.4f} TON</code>\n"
                    f"🔗 <a href=\"https://tonviewer.com/transaction/{event_id}\">Tonviewer</a>"
                )

                try:
                    await bot.send_message(user_id, text, parse_mode="HTML", disable_web_page_preview=True)
                except Exception as e:
                    logger.error(f"Не удалось отправить Jetton-уведомление {user_id}: {e}")

    await db.update_last_event_id(user_id, events[0]["event_id"])

async def start_tx_tracker(bot: Bot, db: Database, ton_client: TonApiClient, interval: int = 20):
    logger.info("Фоновый трекер транзакций TON запущен.")
    while True:
        try:
            users = await db.get_all_users()
            for user in users:
                try:
                    await check_user_events(user, bot, db, ton_client)
                except Exception as e:
                    logger.error(f"Ошибка проверки кошелька юзера {user['user_id']}: {e}")
                await asyncio.sleep(1.0)
        except Exception as e:
            logger.error(f"Ошибка цикла трекера: {e}")

        await asyncio.sleep(interval)
