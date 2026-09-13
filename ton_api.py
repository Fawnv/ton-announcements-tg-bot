import aiohttp
import logging
import time
from typing import Optional, Any

logger = logging.getLogger(__name__)

class TonApiClient:
    def __init__(self, api_key: Optional[str] = None, master_api_key: Optional[str] = None):
        self.base_url = "https://tonapi.io/v2"
        self.master_api_key = api_key or master_api_key
        self._session: Optional[aiohttp.ClientSession] = None
        self._rates_cache: dict[str, Any] = {"time": 0, "data": {}}

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _get_headers(self, custom_key: Optional[str] = None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        token = custom_key or self.master_api_key
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def verify_key(self, test_api_key: str) -> bool:
        """Проверяет валидность ключа тестовым запросом к TonAPI."""
        session = await self.get_session()
        url = f"{self.base_url}/rates?tokens=ton&currencies=usd"
        try:
            async with session.get(url, headers={"Authorization": f"Bearer {test_api_key}"}) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"Ошибка проверки ключа TonAPI: {e}")
            return False

    async def resolve_dns(self, domain_name: str, api_key: Optional[str] = None) -> Optional[str]:
        """Разрешает домен .ton или .t.me в реальный адрес кошелька."""
        session = await self.get_session()
        url = f"{self.base_url}/dns/{domain_name.lower()}/resolve"
        try:
            async with session.get(url, headers=self._get_headers(api_key)) as response:
                if response.status == 200:
                    data = await response.json()
                    wallet = data.get("wallet")
                    if wallet and "address" in wallet:
                        return wallet["address"]
        except Exception as e:
            logger.error(f"Ошибка резолва DNS {domain_name}: {e}")
        return None

    async def get_account(self, address_or_domain: str, api_key: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Получает информацию об аккаунте по адресу или домену (.ton / .t.me)."""
        target = address_or_domain.strip()
        domain_name = None

        if target.lower().endswith(".ton") or target.lower().endswith(".t.me"):
            domain_name = target.lower()
            resolved_address = await self.resolve_dns(domain_name, api_key)
            if not resolved_address:
                return None
            target = resolved_address

        session = await self.get_session()
        url = f"{self.base_url}/accounts/{target}"
        try:
            async with session.get(url, headers=self._get_headers(api_key)) as response:
                if response.status == 200:
                    data = await response.json()
                    if domain_name:
                        data["domain"] = domain_name
                    return data
                return None
        except Exception as e:
            logger.error(f"Ошибка получения аккаунта {target}: {e}")
            return None

    async def get_events(self, address: str, limit: int = 10, api_key: Optional[str] = None) -> list[dict[str, Any]]:
        """Получает последние события транзакций по адресу."""
        session = await self.get_session()
        url = f"{self.base_url}/accounts/{address}/events"
        try:
            async with session.get(url, params={"limit": limit}, headers=self._get_headers(api_key)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("events", [])
                return []
        except Exception as e:
            logger.error(f"Ошибка получения событий для {address}: {e}")
            return []

    async def get_ton_rates(self, api_key: Optional[str] = None) -> dict[str, float]:
        """Возвращает актуальный курс TON к USD, EUR, RUB (кэш на 60 секунд)."""
        now = time.time()
        if self._rates_cache and (now - self._rates_cache.get("time", 0) < 60):
            cached = self._rates_cache.get("data")
            if cached:
                return cached

        session = await self.get_session()
        url = f"{self.base_url}/rates?tokens=ton&currencies=usd,eur,rub"
        try:
            async with session.get(url, headers=self._get_headers(api_key)) as response:
                if response.status == 200:
                    data = await response.json()
                    prices = data.get("rates", {}).get("TON", {}).get("prices", {})
                    self._rates_cache = {
                        "time": now,
                        "data": {
                            "USD": float(prices.get("USD", 0.0)),
                            "EUR": float(prices.get("EUR", 0.0)),
                            "RUB": float(prices.get("RUB", 0.0)),
                        }
                    }
                    return self._rates_cache["data"]
        except Exception as e:
            logger.error(f"Ошибка получения курсов валют: {e}")

        return self._rates_cache.get("data", {})
