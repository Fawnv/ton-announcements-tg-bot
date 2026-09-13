import aiosqlite
import time
from typing import Optional, Any

DB_PATH = "bot_users.db"

class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
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

            await db.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    raw_address TEXT NOT NULL,
                    user_address TEXT NOT NULL,
                    last_event_id TEXT,
                    last_balance REAL DEFAULT 0.0,
                    last_event_ts INTEGER DEFAULT 0,
                    created_at INTEGER,
                    UNIQUE(user_id, raw_address)
                )
            """)
            await db.commit()

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

            # 4. Миграция колонок вотч-листа
            async with db.execute("PRAGMA table_info(watchlist)") as cursor:
                existing_watch_cols = [row[1] for row in await cursor.fetchall()]

            needed_watch_cols = [
                ("last_event_ts", "INTEGER DEFAULT 0"),
                ("label", "TEXT DEFAULT ''")
            ]

            for col_name, col_type in needed_watch_cols:
                if col_name not in existing_watch_cols:
                    await db.execute(f"ALTER TABLE watchlist ADD COLUMN {col_name} {col_type}")
                    await db.commit()

            # 5. Таблица настроек бота (редактируются админами)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            await db.commit()

            # 6. Журнал транзакций по вотч-листу (для истории и оборотов)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tx_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    ts INTEGER NOT NULL,
                    is_in INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    kind TEXT DEFAULT 'ton',
                    symbol TEXT DEFAULT '',
                    event_id TEXT DEFAULT '',
                    FOREIGN KEY (wallet_id) REFERENCES watchlist(id) ON DELETE CASCADE
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_tx_log_wallet ON tx_log(wallet_id, ts)")
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
        self, user_id: int, raw_address: str, user_address: str, last_event_id: str, last_balance: float,
        last_event_ts: int = 0
    ) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute("""
                    INSERT INTO watchlist (user_id, raw_address, user_address, last_event_id, last_balance, last_event_ts, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (user_id, raw_address, user_address, last_event_id, last_balance, last_event_ts, int(time.time())))
                await db.commit()
                return True
            except Exception:
                return False

    async def remove_from_watchlist(self, user_id: int, wallet_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM tx_log WHERE wallet_id = ? AND user_id = ?", (wallet_id, user_id))
            await db.execute("DELETE FROM watchlist WHERE id = ? AND user_id = ?", (wallet_id, user_id))
            await db.commit()

    async def get_user_wallet(self, user_id: int, wallet_id: int) -> Optional[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM watchlist WHERE id = ? AND user_id = ?", (wallet_id, user_id)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def set_wallet_label(self, user_id: int, wallet_id: int, label: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE watchlist SET label = ? WHERE id = ? AND user_id = ?",
                (label, wallet_id, user_id)
            )
            await db.commit()

    # --- ЖУРНАЛ ТРАНЗАКЦИЙ ---

    async def add_tx_log(self, user_id: int, wallet_id: int, ts: int, is_in: bool, amount: float,
                         kind: str = "ton", symbol: str = "", event_id: str = "") -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO tx_log (wallet_id, user_id, ts, is_in, amount, kind, symbol, event_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (wallet_id, user_id, ts, 1 if is_in else 0, amount, kind, symbol, event_id)
            )
            await db.commit()

    async def get_tx_log(self, wallet_id: int, limit: int = 10) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tx_log WHERE wallet_id = ? ORDER BY ts DESC, id DESC LIMIT ?",
                (wallet_id, limit)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_turnover(self, wallet_id: int) -> dict[str, dict[str, float]]:
        """Оборот TON по периодам: today / yesterday / week / month / all.

        Возвращает {период: {"in": сумма входящих, "out": сумма исходящих}}.
        Учитываются только TON-переводы (kind='ton')."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT ts, is_in, amount FROM tx_log WHERE wallet_id = ? AND kind = 'ton'",
                (wallet_id,)
            ) as cursor:
                rows = await cursor.fetchall()

        now = int(time.time())
        today0 = now - (now % 86400)
        yesterday0 = today0 - 86400
        week0 = now - 7 * 86400
        month0 = now - 30 * 86400

        periods = ["today", "yesterday", "week", "month", "all"]
        result = {p: {"in": 0.0, "out": 0.0} for p in periods}

        for row in rows:
            ts, is_in, amount = row["ts"], bool(row["is_in"]), row["amount"]
            direction = "in" if is_in else "out"
            result["all"][direction] += amount
            if ts >= today0:
                result["today"][direction] += amount
            elif ts >= yesterday0:
                result["yesterday"][direction] += amount
            if ts >= week0:
                result["week"][direction] += amount
            if ts >= month0:
                result["month"][direction] += amount

        return result

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
                    w.label,
                    w.last_event_id,
                    w.last_balance,
                    w.last_event_ts,
                    u.custom_api_key,
                    u.fiat_currency,
                    u.min_incoming,
                    u.min_outgoing
                FROM watchlist w
                LEFT JOIN users u ON w.user_id = u.user_id
            """) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def update_watched_last_event_and_balance(self, wallet_id: int, last_event_id: str, last_balance: float, last_event_ts: int = 0) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE watchlist SET last_event_id = ?, last_balance = ?, last_event_ts = ? WHERE id = ?",
                (last_event_id, last_balance, last_event_ts, wallet_id)
            )
            await db.commit()

    # --- НАСТРОЙКИ БОТА (админские) ---

    async def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else default

    async def set_setting(self, key: str, value: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value)
            )
            await db.commit()

    async def get_all_user_ids(self) -> list[int]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT user_id FROM users") as cursor:
                rows = await cursor.fetchall()
                return [r[0] for r in rows]

    async def get_stats(self) -> dict[str, int]:
        async with aiosqlite.connect(self.db_path) as db:
            stats = {}
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                res = await cursor.fetchone()
                stats["users"] = res[0] if res else 0
            async with db.execute("SELECT COUNT(*) FROM watchlist") as cursor:
                res = await cursor.fetchone()
                stats["wallets"] = res[0] if res else 0
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE sub_type = 'lifetime' OR sub_until > ?",
                (int(time.time()),)
            ) as cursor:
                res = await cursor.fetchone()
                stats["active_subs"] = res[0] if res else 0
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE custom_api_key IS NOT NULL AND custom_api_key != ''"
            ) as cursor:
                res = await cursor.fetchone()
                stats["custom_keys"] = res[0] if res else 0
            return stats

db = Database()
