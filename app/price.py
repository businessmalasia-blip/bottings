"""Цена SOL в USD с кэшем: фоновое обновление раз в 30 секунд из нескольких источников."""

import asyncio
import logging

from .http import session

log = logging.getLogger(__name__)


async def _coingecko() -> float:
    async with session().get(
        "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd", timeout=5
    ) as r:
        return float((await r.json())["solana"]["usd"])


async def _kraken() -> float:
    async with session().get("https://api.kraken.com/0/public/Ticker?pair=SOLUSD", timeout=5) as r:
        data = await r.json()
        return float(next(iter(data["result"].values()))["c"][0])


async def _binance() -> float:
    async with session().get(
        "https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT", timeout=5
    ) as r:
        return float((await r.json())["price"])


SOURCES = (_coingecko, _kraken, _binance)


class SolPrice:
    def __init__(self) -> None:
        self.usd: float | None = None

    async def refresh(self) -> None:
        for src in SOURCES:
            try:
                price = await src()
                if price > 0:
                    self.usd = price
                    return
            except Exception as e:
                log.debug("Источник цены %s не ответил: %r", src.__name__, e)
        log.warning("Не удалось обновить цену SOL, использую последнюю: %s", self.usd)

    async def run(self, interval: float = 30) -> None:
        while True:
            await self.refresh()
            await asyncio.sleep(interval)
