import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    alert_chat_id: int
    admin_ids: frozenset[int]
    db_path: str


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    chat = os.getenv("ALERT_CHAT_ID", "").strip()
    admins = os.getenv("ADMIN_IDS", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не задан в .env")
    if not chat:
        raise SystemExit("ALERT_CHAT_ID не задан в .env")
    if not admins:
        raise SystemExit("ADMIN_IDS не задан в .env (твой Telegram user id)")
    return Config(
        bot_token=token,
        alert_chat_id=int(chat),
        admin_ids=frozenset(int(x) for x in admins.replace(" ", "").split(",") if x),
        db_path=os.getenv("DB_PATH", "data/wallets.db"),
    )
