import aiohttp

_session: aiohttp.ClientSession | None = None


def session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            trust_env=True,  # учитывает HTTP(S)_PROXY, если задан
            headers={"User-Agent": "Mozilla/5.0 (dev-launch-tracker)"},
        )
    return _session


async def close() -> None:
    if _session and not _session.closed:
        await _session.close()
