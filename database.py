import aiosqlite
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
                    raw_address TEXT NOT NULL,
                    user_address TEXT NOT NULL,
                    last_event_id TEXT
                )
            """)
            await db.commit()

    async def get_user(self, user_id: int) -> Optional[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def save_user(self, user_id: int, raw_address: str, user_address: str, last_event_id: str = "") -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO users (user_id, raw_address, user_address, last_event_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    raw_address = excluded.raw_address,
                    user_address = excluded.user_address,
                    last_event_id = excluded.last_event_id
            """, (user_id, raw_address, user_address, last_event_id))
            await db.commit()

    async def update_last_event_id(self, user_id: int, last_event_id: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET last_event_id = ? WHERE user_id = ?", (last_event_id, user_id))
            await db.commit()

    async def get_all_users(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users") as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def delete_user(self, user_id: int) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            await db.commit()

db = Database()
