import aiohttp
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

class TonApiClient:
    def __init__(self, api_key: Optional[str] = None):
        self.base_url = "https://tonapi.io/v2"
        self.api_key = api_key
        self._session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {"Accept": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._session = aiohttp.ClientSession(headers=headers)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_account(self, address: str) -> Optional[dict[str, Any]]:
        """Получить статус аккаунта и баланс."""
        session = await self.get_session()
        url = f"{self.base_url}/accounts/{address}"
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                return None
        except Exception as e:
            logger.error(f"Ошибка при запросе аккаунта {address}: {e}")
            return None

    async def get_events(self, address: str, limit: int = 10) -> list[dict[str, Any]]:
        """Получить последние события (транзакции) аккаунта."""
        session = await self.get_session()
        url = f"{self.base_url}/accounts/{address}/events"
        try:
            async with session.get(url, params={"limit": limit}) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("events", [])
                return []
        except Exception as e:
            logger.error(f"Ошибка при запросе событий {address}: {e}")
            return []
