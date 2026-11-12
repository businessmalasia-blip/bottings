import os

import aiosqlite


class WalletStore:
    """Хранилище отслеживаемых кошельков (SQLite) + кэш в памяти для быстрой проверки."""

    def __init__(self, path: str):
        self.path = path
        self._cache: dict[str, str | None] = {}

    async def init(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS wallets (
                       address TEXT PRIMARY KEY,
                       label TEXT,
                       added_at TEXT DEFAULT CURRENT_TIMESTAMP
                   )"""
            )
            await db.commit()
            async with db.execute("SELECT address, label FROM wallets") as cur:
                self._cache = {a: l async for a, l in cur}

    def is_tracked(self, address: str) -> bool:
        return address in self._cache

    def label(self, address: str) -> str | None:
        return self._cache.get(address)

    def all(self) -> list[tuple[str, str | None]]:
        return sorted(self._cache.items())

    async def add(self, address: str, label: str | None) -> bool:
        """True — добавлен новый, False — уже был (метка обновлена)."""
        existed = address in self._cache
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO wallets(address, label) VALUES(?, ?) "
                "ON CONFLICT(address) DO UPDATE SET label=excluded.label",
                (address, label),
            )
            await db.commit()
        self._cache[address] = label
        return not existed

    async def remove(self, address: str) -> bool:
        if address not in self._cache:
            return False
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM wallets WHERE address=?", (address,))
            await db.commit()
        self._cache.pop(address, None)
        return True

    async def clear(self) -> int:
        n = len(self._cache)
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM wallets")
            await db.commit()
        self._cache.clear()
        return n
