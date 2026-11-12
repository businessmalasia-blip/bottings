# Dev Wallet Launch Tracker (Telegram)

Бот следит за кошельками девов и сразу присылает алерт в указанный чат, когда один из них создаёт монету на pump.fun (Solana).
В алерте: картинка монеты, капитализация и покупка дева в долларах (цена SOL — CoinGecko / Kraken / Binance).
Источник — WebSocket PumpPortal (`subscribeNewToken`): событие приходит в момент транзакции создания токена.

## Установка

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполни BOT_TOKEN, ALERT_CHAT_ID, ADMIN_IDS
python main.py
```

- `ADMIN_IDS` — твой Telegram user id (только эти люди могут управлять ботом в личке).
- `ALERT_CHAT_ID` — чат для алертов. Добавь бота в группу/канал и напиши там `/chatid` — бот ответит id.

## Управление (в личке с ботом)

- Просто пришли адрес — добавится. С меткой: `АДРЕС имя`. Несколько — по одному на строку.
- `/list` или кнопка «📋 Список» / «🗑 Удалить» — список с кнопками ❌ для удаления.
- `/add АДРЕС [метка]`, `/remove АДРЕС`, `/clear` — удалить все (с подтверждением).
- `/test` — отправить тестовый алерт в чат.

Кошельки хранятся в SQLite (`data/wallets.db`), env для них не нужен.
