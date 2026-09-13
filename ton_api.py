import asyncio
import aiohttp
import logging
import time
from typing import Optional, Any

logger = logging.getLogger(__name__)


class TonApiClient:
    DNS_CACHE_TTL = 15 * 60
    ACCOUNT_CACHE_TTL = 5
    STALE_ACCOUNT_TTL = 60
    FAST_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=2.2, connect=1.0, sock_read=1.8)
    TRANSIENT_STATUSES = {429, 500, 502, 503, 504}

    def __init__(self, api_key: Optional[str] = None, master_api_key: Optional[str] = None):
        self.base_url = "https://tonapi.io/v2"
        self.master_api_key = api_key or master_api_key
        self._session: Optional[aiohttp.ClientSession] = None
        self._rates_cache: dict[tuple[str, str], tuple[float, dict[str, dict[str, float]]]] = {}
        self._dns_cache: dict[str, tuple[float, str]] = {}
        self._account_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=5, connect=2, sock_read=4)
            self._session = aiohttp.ClientSession(timeout=timeout)
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

    async def _get_json_fast(
        self,
        url: str,
        api_key: Optional[str] = None,
        *,
        attempts: int = 2,
    ) -> tuple[Optional[dict[str, Any]], str]:
        """Быстрый GET для inline-критичных запросов.

        Возвращает (json, status), где status: ok / not_found / temporary / error.
        На 429 и 5xx делает короткий retry, чтобы не отдавать пользователю ложный
        "не найден" из-за краткого rate limit или сбоя TonAPI.
        """
        session = await self.get_session()
        last_status: Optional[int] = None

        for attempt in range(max(1, attempts)):
            try:
                async with session.get(
                    url,
                    headers=self._get_headers(api_key),
                    timeout=self.FAST_REQUEST_TIMEOUT,
                ) as response:
                    last_status = response.status

                    if response.status == 200:
                        try:
                            return await response.json(), "ok"
                        except (aiohttp.ContentTypeError, ValueError) as e:
                            logger.warning(f"TonAPI вернул некорректный JSON для {url}: {e}")
                            return None, "temporary"

                    if response.status == 404:
                        return None, "not_found"

                    if response.status in self.TRANSIENT_STATUSES:
                        if attempt + 1 < attempts:
                            retry_after_raw = response.headers.get("Retry-After", "")
                            try:
                                retry_after = float(retry_after_raw)
                            except (TypeError, ValueError):
                                retry_after = 0.0
                            delay = min(max(retry_after, 0.15), 0.45)
                            await asyncio.sleep(delay)
                            continue

                        logger.warning(f"TonAPI временно недоступен для {url}: HTTP {response.status}")
                        return None, "temporary"

                    logger.warning(f"TonAPI запрос {url}: HTTP {response.status}")
                    return None, "error"

            except asyncio.TimeoutError:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.15)
                    continue
                logger.warning(f"Таймаут TonAPI для {url}")
                return None, "temporary"
            except aiohttp.ClientError as e:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.15)
                    continue
                logger.warning(f"Сетевая ошибка TonAPI для {url}: {e}")
                return None, "temporary"
            except Exception as e:
                logger.error(f"Неожиданная ошибка TonAPI для {url}: {e}")
                return None, "temporary"

        logger.warning(f"TonAPI запрос {url} завершился без результата, последний HTTP: {last_status}")
        return None, "temporary"

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
        """Разрешает домен .ton или .t.me в адрес кошелька с кэшем и retry."""
        domain = domain_name.strip().lower()
        now = time.time()
        cached = self._dns_cache.get(domain)

        if cached and now - cached[0] < self.DNS_CACHE_TTL:
            return cached[1]

        url = f"{self.base_url}/dns/{domain}/resolve"
        data, status = await self._get_json_fast(url, api_key=api_key, attempts=2)

        if data:
            wallet = data.get("wallet") or {}
            address = wallet.get("address")
            if address:
                self._dns_cache[domain] = (now, str(address))
                return str(address)

        # При кратком сбое лучше использовать ранее успешно разрешенный адрес,
        # даже если основной TTL уже истек: TON DNS меняется редко, а inline не
        # должен мигать "домен не найден" из-за 429/5xx.
        if status == "temporary" and cached:
            logger.info(f"Используем stale DNS-кэш для {domain} после временной ошибки TonAPI")
            return cached[1]

        return None

    async def get_account(self, address_or_domain: str, api_key: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Получает аккаунт по адресу или домену, устойчиво к кратким сбоям TonAPI."""
        target = address_or_domain.strip()
        domain_name = None

        if target.lower().endswith(".ton") or target.lower().endswith(".t.me"):
            domain_name = target.lower()
            resolved_address = await self.resolve_dns(domain_name, api_key)
            if not resolved_address:
                return None
            target = resolved_address

        now = time.time()
        cache_key = target.lower()
        cached = self._account_cache.get(cache_key)

        if cached and now - cached[0] < self.ACCOUNT_CACHE_TTL:
            data = dict(cached[1])
            if domain_name:
                data["domain"] = domain_name
            return data

        url = f"{self.base_url}/accounts/{target}"
        data, status = await self._get_json_fast(url, api_key=api_key, attempts=2)

        if data:
            self._account_cache[cache_key] = (now, dict(data))
            if domain_name:
                data = dict(data)
                data["domain"] = domain_name
            return data

        # Если аккаунт только что успешно читался, transient-сбой не должен
        # превращаться в "кошелек/домен не найден" и затем кэшироваться Telegram.
        if status == "temporary" and cached and now - cached[0] < self.STALE_ACCOUNT_TTL:
            logger.info(f"Используем stale account-кэш для {target} после временной ошибки TonAPI")
            stale = dict(cached[1])
            if domain_name:
                stale["domain"] = domain_name
            return stale

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

    async def get_rates(
        self, tokens: list[str], currencies: list[str], api_key: Optional[str] = None
    ) -> dict[str, dict[str, float]]:
        """Курсы токенов TonAPI к валютам: {ton: {usd: 1.3, rub: 110}}.

        Неподдерживаемые токены либо отсутствуют в ответе, либо идут с нулевым
        курсом — вызывающий код обязан это проверять. Кэш на 60 секунд.
        """
        tkey = ",".join(sorted({t.lower() for t in tokens if t}))
        ckey = ",".join(sorted({c.lower() for c in currencies if c}))
        if not tkey or not ckey:
            return {}

        now = time.time()
        cached = self._rates_cache.get((tkey, ckey))
        if cached and now - cached[0] < 60:
            return cached[1]

        session = await self.get_session()
        try:
            async with session.get(
                f"{self.base_url}/rates",
                params={"tokens": tkey, "currencies": ckey},
                headers=self._get_headers(api_key),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    out: dict[str, dict[str, float]] = {}
                    for sym, info in (data.get("rates") or {}).items():
                        prices = info.get("prices") or {}
                        out[str(sym).lower()] = {
                            str(cur).lower(): float(v)
                            for cur, v in prices.items()
                            if v is not None
                        }
                    self._rates_cache[(tkey, ckey)] = (now, out)
                    return out
                logger.error(f"TonAPI rates {tkey} -> {ckey}: HTTP {response.status}")
        except Exception as e:
            logger.error(f"Ошибка получения курсов {tkey}: {e}")
        return {}

    async def get_ton_rates(self, api_key: Optional[str] = None) -> dict[str, float]:
        """Возвращает актуальный курс TON к USD, EUR, RUB (кэш на 60 секунд)."""
        rates = await self.get_rates(["ton"], ["usd", "eur", "rub"], api_key=api_key)
        ton = rates.get("ton", {})
        return {
            "USD": ton.get("usd", 0.0),
            "EUR": ton.get("eur", 0.0),
            "RUB": ton.get("rub", 0.0),
        }

