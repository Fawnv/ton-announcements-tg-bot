import aiosqlite
import time
from typing import Optional, Any

DB_PATH = "bot_users.db"

class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            # 1. Создаем таблицу пользователей (если ее нет)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    custom_api_key TEXT,
                    sub_type TEXT DEFAULT 'free',
                    sub_until INTEGER DEFAULT 0,
                    fiat_currency TEXT DEFAULT 'usd_rub',
                    raw_address TEXT DEFAULT '',
                    user_address TEXT DEFAULT '',
                    min_incoming REAL DEFAULT 0.0,
                    min_outgoing REAL DEFAULT 0.0
                )
            """)

            # 2. Создаем таблицу вотч-листа (если ее нет)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    raw_address TEXT NOT NULL,
                    user_address TEXT NOT NULL,
                    last_event_id TEXT,
                    last_balance REAL DEFAULT 0.0,
                    created_at INTEGER,
                    UNIQUE(user_id, raw_address)
                )
            """)
            await db.commit()

            # 3. Гарантированная миграция существующих таблиц через PRAGMA
            async with db.execute("PRAGMA table_info(users)") as cursor:
                existing_cols = [row[1] for row in await cursor.fetchall()]

            needed_cols = [
                ("custom_api_key", "TEXT"),
                ("sub_type", "TEXT DEFAULT 'free'"),
                ("sub_until", "INTEGER DEFAULT 0"),
                ("fiat_currency", "TEXT DEFAULT 'usd_rub'"),
                ("raw_address", "TEXT DEFAULT ''"),
                ("user_address", "TEXT DEFAULT ''"),
                ("min_incoming", "REAL DEFAULT 0.0"),
                ("min_outgoing", "REAL DEFAULT 0.0")
            ]

            for col_name, col_type in needed_cols:
                if col_name not in existing_cols:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}")
                    await db.commit()

    async def get_user(self, user_id: int) -> Optional[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def set_user_subscription(self, user_id: int, sub_type: str, sub_until: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO users (user_id, sub_type, sub_until, raw_address, user_address)
                VALUES (?, ?, ?, '', '')
                ON CONFLICT(user_id) DO UPDATE SET
                    sub_type = excluded.sub_type,
                    sub_until = excluded.sub_until
            """, (user_id, sub_type, sub_until))
            await db.commit()

    async def set_user_api_key(self, user_id: int, api_key: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO users (user_id, custom_api_key, raw_address, user_address)
                VALUES (?, ?, '', '')
                ON CONFLICT(user_id) DO UPDATE SET
                    custom_api_key = excluded.custom_api_key
            """, (user_id, api_key))
            await db.commit()

    async def set_user_fiat(self, user_id: int, fiat_mode: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO users (user_id, fiat_currency, raw_address, user_address)
                VALUES (?, ?, '', '')
                ON CONFLICT(user_id) DO UPDATE SET
                    fiat_currency = excluded.fiat_currency
            """, (user_id, fiat_mode))
            await db.commit()

    async def get_user_fiat(self, user_id: int) -> str:
        user = await self.get_user(user_id)
        return (user.get("fiat_currency") if user else None) or "usd_rub"

    async def set_user_filter_in(self, user_id: int, min_in: float) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO users (user_id, min_incoming, raw_address, user_address)
                VALUES (?, ?, '', '')
                ON CONFLICT(user_id) DO UPDATE SET min_incoming = excluded.min_incoming
            """, (user_id, min_in))
            await db.commit()

    async def set_user_filter_out(self, user_id: int, min_out: float) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO users (user_id, min_outgoing, raw_address, user_address)
                VALUES (?, ?, '', '')
                ON CONFLICT(user_id) DO UPDATE SET min_outgoing = excluded.min_outgoing
            """, (user_id, min_out))
            await db.commit()

    async def get_user_filters(self, user_id: int) -> tuple[float, float]:
        user = await self.get_user(user_id)
        if not user:
            return 0.0, 0.0
        return float(user.get("min_incoming") or 0.0), float(user.get("min_outgoing") or 0.0)

    async def add_to_watchlist(
        self, user_id: int, raw_address: str, user_address: str, last_event_id: str, last_balance: float
    ) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute("""
                    INSERT INTO watchlist (user_id, raw_address, user_address, last_event_id, last_balance, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (user_id, raw_address, user_address, last_event_id, last_balance, int(time.time())))
                await db.commit()
                return True
            except Exception:
                return False

    async def remove_from_watchlist(self, user_id: int, wallet_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM watchlist WHERE id = ? AND user_id = ?", (wallet_id, user_id))
            await db.commit()

    async def get_user_watchlist(self, user_id: int) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM watchlist WHERE user_id = ? ORDER BY id DESC", (user_id,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def count_user_wallets(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM watchlist WHERE user_id = ?", (user_id,)) as cursor:
                res = await cursor.fetchone()
                return res[0] if res else 0

    async def get_all_watched_wallets(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT
                    w.id,
                    w.user_id,
                    w.raw_address,
                    w.user_address,
                    w.last_event_id,
                    w.last_balance,
                    u.custom_api_key,
                    u.fiat_currency,
                    u.min_incoming,
                    u.min_outgoing
                FROM watchlist w
                LEFT JOIN users u ON w.user_id = u.user_id
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def update_watched_last_event_and_balance(self, wallet_id: int, last_event_id: str, last_balance: float) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE watchlist SET last_event_id = ?, last_balance = ? WHERE id = ?",
                (last_event_id, last_balance, wallet_id)
            )
            await db.commit()

db = Database()
