"""Загрузка картинки монеты: uri -> JSON метаданных -> поле image -> байты картинки."""

import asyncio
import logging
import re

from .http import session

log = logging.getLogger(__name__)

# ipfs.io и dweb.link больше не отдают файлы напрямую, поэтому подменяем шлюз
IPFS_GATEWAYS = (
    "https://pump.mypinata.cloud/ipfs/",
    "https://gateway.pinata.cloud/ipfs/",
    "https://4everland.io/ipfs/",
)
IPFS_RE = re.compile(r"(?:ipfs://|/ipfs/)(.+)$")
MAX_IMAGE = 10 * 1024 * 1024


def candidates(url: str) -> list[str]:
    m = IPFS_RE.search(url)
    if m:
        return [g + m.group(1) for g in IPFS_GATEWAYS]
    return [url]


async def _get(url: str, want_json: bool, timeout: float):
    async with session().get(url, timeout=timeout) as r:
        r.raise_for_status()
        if want_json:
            return await r.json(content_type=None)
        if int(r.headers.get("Content-Length") or 0) > MAX_IMAGE:
            raise ValueError("image too large")
        data = await r.content.read(MAX_IMAGE + 1)
        if len(data) > MAX_IMAGE or "svg" in r.headers.get("Content-Type", ""):
            raise ValueError("unsupported image")
        return data


async def _race(url: str, want_json: bool, timeout: float):
    """Запрашивает все шлюзы параллельно и берёт первый успешный ответ."""
    tasks = [asyncio.create_task(_get(u, want_json, timeout)) for u in candidates(url)]
    try:
        for fut in asyncio.as_completed(tasks):
            try:
                return await fut
            except Exception:
                continue
        return None
    finally:
        for t in tasks:
            t.cancel()


async def fetch_image(uri: str | None, budget: float = 6.0) -> bytes | None:
    if not uri:
        return None

    async def go():
        meta = await _race(uri, True, budget)
        image_url = meta.get("image") if isinstance(meta, dict) else None
        return await _race(image_url, False, budget) if image_url else None

    try:
        return await asyncio.wait_for(go(), budget)
    except Exception as e:
        log.info("Картинка не загрузилась (%s): %r", uri, e)
        return None
