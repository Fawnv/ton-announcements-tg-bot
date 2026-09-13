import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Awaitable, Callable, Optional

import aiohttp

logger = logging.getLogger(__name__)

# Платежи старше этого возраста (сек) закрываются как expired
PAYMENT_MAX_AGE = 2 * 3600


class Pay2328Client:
    """Клиент платежного API 2328.io.

    Документация: https://2328.io/api
    Аутентификация: заголовки project (UUID проекта) + sign
    (HMAC-SHA256 от base64(compact JSON body), ключ — API-ключ проекта).
    """

    BASE_URL = "https://api.2328.io/api/v1"
    USER_AGENT = "ton-announcements-tg-bot/1.0 (+https://github.com/Fawnv/ton-announcements-tg-bot)"

    def __init__(self, project_id: Optional[str], api_key: Optional[str], callback_url: str = "https://2328.io/"):
        self.project_id = project_id
        self.api_key = api_key
        self.callback_url = callback_url
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def enabled(self) -> bool:
        return bool(self.project_id and self.api_key)

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _sign(self, payload: dict[str, Any]) -> str:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        b64 = base64.b64encode(body.encode("utf-8")).decode("ascii")
        return hmac.new(self.api_key.encode("utf-8"), b64.encode("ascii"), hashlib.sha256).hexdigest()

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not self.enabled:
            return None

        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.USER_AGENT,
            "project": self.project_id,
            "sign": self._sign(payload),
        }

        session = await self.get_session()
        try:
            async with session.post(f"{self.BASE_URL}/{endpoint}", data=body, headers=headers) as resp:
                data = await resp.json(content_type=None)
                if resp.status == 200 and isinstance(data, dict) and data.get("state") == 0:
                    return data.get("result")
                logger.error(f"2328 {endpoint}: HTTP {resp.status}, ответ: {data}")
                return None
        except Exception as e:
            logger.error(f"Ошибка запроса 2328 {endpoint}: {e}")
            return None

    async def create_payment(
        self, amount_usd: float, order_id: str, description: str = "", ttl_seconds: int = 3600
    ) -> Optional[dict[str, Any]]:
        """Создает счет в USD (hosted checkout): покупатель выбирает криптовалюту сам."""
        payload: dict[str, Any] = {
            "amount": f"{amount_usd:.2f}",
            "currency": "USD",
            "order_id": order_id,
            "url_callback": self.callback_url,
            "ttl_seconds": ttl_seconds,
        }
        if description:
            payload["description"] = description[:200]
        return await self._post("payment", payload)

    async def get_payment_info(self, order_id: str) -> Optional[dict[str, Any]]:
        return await self._post("payment/info", {"order_id": order_id})


async def start_payment_poller(
    bot,
    db,
    client: Pay2328Client,
    on_paid: Callable[[int, str], Awaitable[None]],
    interval: int = 30,
):
    """Фоновый поллер статусов крипто-платежей (вместо вебхуков)."""
    if not client.enabled:
        logger.info("2328.io не настроен (PAY2328_PROJECT/PAY2328_API_KEY) — поллер платежей не запущен.")
        return

    logger.info("Поллер крипто-платежей 2328.io запущен.")
    while True:
        try:
            pending = await db.get_pending_payments()
            for p in pending:
                try:
                    info = await client.get_payment_info(p["order_id"])
                    status = (info or {}).get("payment_status")

                    if status == "paid":
                        if await db.mark_payment_paid(p["order_id"]):
                            try:
                                await on_paid(p["user_id"], p["period"])
                            except Exception as e:
                                logger.error(f"Ошибка активации подписки после оплаты: {e}")
                    elif status in ("cancel",):
                        await db.set_payment_status(p["order_id"], "cancel")
                    elif int(time.time()) - int(p.get("created_at") or 0) > PAYMENT_MAX_AGE:
                        await db.set_payment_status(p["order_id"], "expired")
                except Exception as e:
                    logger.error(f"Ошибка проверки платежа {p['order_id']}: {e}")
                await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Ошибка цикла поллера платежей: {e}")

        await asyncio.sleep(interval)
