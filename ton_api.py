import asyncio
import aiohttp
import logging
import random
import time
from typing import Optional, Any

logger = logging.getLogger(__name__)


class TonApiClient:
    DNS_CACHE_TTL = 15 * 60
    ACCOUNT_CACHE_TTL = 5
    STALE_ACCOUNT_TTL = 60
    FAST_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=2.2, connect=1.0, sock_read=1.8)
    TRANSIENT_STATUSES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        api_key: Optional[str] = None,
        master_api_key: Optional[str] = None,
        api_keys: Optional[list[str]] = None,
    ):
        self.base_url = "https://tonapi.io/v2"

        keys: list[str] = []

        for key in api_keys or []:
            key = (key or "").strip()
            if key and key not in keys:
                keys.append(key)

        for key in (api_key, master_api_key):
            key = (key or "").strip()
            if key and key not in keys:
                keys.append(key)

        self._api_keys = keys
        self.master_api_key = keys[0] if keys else None

        # key -> monotonic timestamp, до которого ключ отдыхает после 429
        self._key_cooldowns: dict[str, float] = {}

        self._session: Optional[aiohttp.ClientSession] = None
        self._rates_cache: dict[
            tuple[str, str],
            tuple[float, dict[str, dict[str, float]]]
        ] = {}
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

    def _pick_master_key(
        self,
        exclude: Optional[set[str]] = None,
    ) -> Optional[str]:
        """Случайный доступный master key.

        Ключи, недавно получившие 429, временно исключаются.
        """
        if not self._api_keys:
            return None

        exclude = exclude or set()
        now = time.monotonic()

        available = [
            key
            for key in self._api_keys
            if key not in exclude
            and self._key_cooldowns.get(key, 0.0) <= now
        ]

        if not available:
            return None

        return random.choice(available)


    def _cooldown_master_key(
        self,
        key: Optional[str],
        retry_after: float = 1.0,
    ) -> None:
        if not key or key not in self._api_keys:
            return

        cooldown = min(max(retry_after, 1.0), 30.0)

        self._key_cooldowns[key] = (
            time.monotonic() + cooldown
        )

        logger.warning(
            "TonAPI key ...%s получил 429, cooldown %.1fs",
            key[-6:],
            cooldown,
        )


    def _headers_for_token(
        self,
        token: Optional[str],
    ) -> dict[str, str]:
        headers = {"Accept": "application/json"}

        if token:
            headers["Authorization"] = f"Bearer {token}"

        return headers

    def _get_headers(
        self,
        custom_key: Optional[str] = None,
    ) -> dict[str, str]:
        # Персональный пользовательский ключ всегда имеет приоритет
        # и никогда не смешивается с master pool.
        token = custom_key

        if not token:
            token = self._pick_master_key()

        return self._headers_for_token(token)    

    async def _get_json_fast(
        self,
        url: str,
        api_key: Optional[str] = None,
        *,
        attempts: int = 3,
        params: Optional[dict[str, Any]] = None,
    ) -> tuple[Optional[dict[str, Any]], str]:
        """GET с failover master-ключей после HTTP 429.

        custom api_key пользователя никогда не ротируется по master pool.
        """

        session = await self.get_session()

        used_keys: set[str] = set()

        # Пользовательский ключ закрепляем за запросом.
        current_token = api_key

        for attempt in range(max(1, attempts)):
            if api_key is None:
                if current_token is None:
                    current_token = self._pick_master_key(
                        exclude=used_keys
                    )

                # Master keys есть, но все находятся в cooldown.
                if self._api_keys and current_token is None:
                    logger.warning(
                        "Все TonAPI master keys сейчас в cooldown"
                    )
                    return None, "temporary"

            try:
                async with session.get(
                    url,
                    params=params,
                    headers=self._headers_for_token(current_token),
                    timeout=self.FAST_REQUEST_TIMEOUT,
                ) as response:

                    if response.status == 200:
                        try:
                            return await response.json(), "ok"
                        except (
                            aiohttp.ContentTypeError,
                            ValueError,
                        ) as e:
                            logger.warning(
                                "TonAPI invalid JSON %s: %s",
                                url,
                                e,
                            )
                            return None, "temporary"

                    if response.status == 404:
                        return None, "not_found"

                    if response.status == 429:
                        retry_after_raw = response.headers.get(
                            "Retry-After",
                            "",
                        )

                        try:
                            retry_after = float(retry_after_raw)
                        except (TypeError, ValueError):
                            retry_after = 1.0

                        # Master pool:
                        # исключаем получивший 429 ключ и пробуем другой.
                        if api_key is None and current_token:
                            self._cooldown_master_key(
                                current_token,
                                retry_after,
                            )

                            used_keys.add(current_token)
                            current_token = None

                            if attempt + 1 < attempts:
                                continue

                        # Пользовательский custom key не заменяем
                        # ключом владельца бота.
                        if attempt + 1 < attempts:
                            await asyncio.sleep(
                                min(max(retry_after, 0.25), 2.0)
                            )
                            continue

                        return None, "temporary"

                    if response.status in {
                        500,
                        502,
                        503,
                        504,
                    }:
                        if attempt + 1 < attempts:
                            await asyncio.sleep(0.2)
                            continue

                        return None, "temporary"

                    logger.warning(
                        "TonAPI %s: HTTP %s",
                        url,
                        response.status,
                    )
                    return None, "error"

            except asyncio.TimeoutError:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.15)
                    continue

                return None, "temporary"

            except aiohttp.ClientError as e:
                logger.warning(
                    "TonAPI network error %s: %s",
                    url,
                    e,
                )

                if attempt + 1 < attempts:
                    await asyncio.sleep(0.15)
                    continue

                return None, "temporary"

            except Exception as e:
                logger.exception(
                    "Unexpected TonAPI error %s: %s",
                    url,
                    e,
                )
                return None, "temporary"

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

    async def get_events(
        self,
        address: str,
        limit: int = 10,
        api_key: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        url = f"{self.base_url}/accounts/{address}/events"

        data, status = await self._get_json_fast(
            url,
            api_key=api_key,
            attempts=3,
            params={"limit": limit},
        )

        if data:
            return data.get("events", [])

        return []


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
        self,
        tokens: list[str],
        currencies: list[str],
        api_key: Optional[str] = None,
    ) -> dict[str, dict[str, float]]:
        """Курсы токенов TonAPI к валютам.

        Пример результата:
        {
            "ton": {
                "usd": 1.3,
                "rub": 110.0,
            }
        }

        Кэш на 60 секунд.
        """

        tkey = ",".join(
            sorted({
                token.lower()
                for token in tokens
                if token
            })
        )

        ckey = ",".join(
            sorted({
                currency.lower()
                for currency in currencies
                if currency
            })
        )

        if not tkey or not ckey:
            return {}

        now = time.time()

        cached = self._rates_cache.get((tkey, ckey))
        if cached and now - cached[0] < 60:
            return cached[1]

        data, status = await self._get_json_fast(
            f"{self.base_url}/rates",
            api_key=api_key,
            attempts=3,
            params={
                "tokens": tkey,
                "currencies": ckey,
            },
        )

        if not data:
            logger.warning(
                "Не удалось получить TonAPI rates %s -> %s, status=%s",
                tkey,
                ckey,
                status,
            )
            return {}

        out: dict[str, dict[str, float]] = {}

        for symbol, info in (data.get("rates") or {}).items():
            prices = info.get("prices") or {}

            parsed_prices: dict[str, float] = {}

            for currency, value in prices.items():
                if value is None:
                    continue

                try:
                    parsed_prices[str(currency).lower()] = float(value)
                except (TypeError, ValueError):
                    continue

            out[str(symbol).lower()] = parsed_prices

        self._rates_cache[(tkey, ckey)] = (
            time.time(),
            out,
        )

        return out

    async def get_ton_rates(self, api_key: Optional[str] = None) -> dict[str, float]:
        """Возвращает актуальный курс TON к USD, EUR, RUB (кэш на 60 секунд)."""
        rates = await self.get_rates(["ton"], ["usd", "eur", "rub"], api_key=api_key)
        ton = rates.get("ton", {})
        return {
            "USD": ton.get("usd", 0.0),
            "EUR": ton.get("eur", 0.0),
            "RUB": ton.get("rub", 0.0),
        }

