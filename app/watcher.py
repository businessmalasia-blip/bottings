"""Слушает поток новых токенов pump.fun (через PumpPortal WebSocket)
и вызывает callback, если создатель токена есть в списке отслеживаемых."""

import asyncio
import json
import logging
from typing import Awaitable, Callable

import websockets

from .db import WalletStore

log = logging.getLogger(__name__)

PUMPPORTAL_WS = "wss://pumpportal.fun/api/data"

OnLaunch = Callable[[dict], Awaitable[None]]


async def watch_launches(store: WalletStore, on_launch: OnLaunch) -> None:
    backoff = 1
    while True:
        try:
            async with websockets.connect(
                PUMPPORTAL_WS, ping_interval=20, ping_timeout=20, max_size=2**22
            ) as ws:
                await ws.send(json.dumps({"method": "subscribeNewToken"}))
                log.info("Подключено к PumpPortal, слушаю новые токены")
                backoff = 1
                async for raw in ws:
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if event.get("txType") != "create":
                        continue
                    creator = event.get("traderPublicKey")
                    if creator and store.is_tracked(creator):
                        # не блокируем чтение потока отправкой сообщения
                        asyncio.create_task(_safe(on_launch, event))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # обрывы сети и т.п. — переподключаемся
            log.warning("WebSocket упал: %r, переподключение через %ss", e, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


async def _safe(fn: OnLaunch, event: dict) -> None:
    try:
        await fn(event)
    except Exception:
        log.exception("Ошибка при отправке алерта")
