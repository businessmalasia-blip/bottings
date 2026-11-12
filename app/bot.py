import asyncio
import html
import logging
import re

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from . import http
from .config import load_config
from .media import fetch_image
from .price import SolPrice
from .db import WalletStore
from .watcher import watch_launches

log = logging.getLogger(__name__)

# Solana-адрес: base58, 32–44 символа
ADDR_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
PAGE_SIZE = 10

BTN_ADD = "➕ Добавить"
BTN_LIST = "📋 Список"
BTN_DEL = "🗑 Удалить"

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_LIST)], [KeyboardButton(text=BTN_DEL)]],
    resize_keyboard=True,
)

HELP = (
    "<b>Трекер запусков монет от дев-кошельков (pump.fun, Solana)</b>\n\n"
    "Просто пришли адрес кошелька — он добавится в отслеживание.\n"
    "Можно с меткой: <code>АДРЕС имя</code>\n"
    "Можно несколько сразу — каждый с новой строки.\n\n"
    "Команды:\n"
    "/add <code>АДРЕС [метка]</code> — добавить\n"
    "/remove <code>АДРЕС</code> — удалить\n"
    "/list — список (с кнопками удаления)\n"
    "/clear — удалить все\n"
    "/test — тестовый алерт в чат\n"
    "/chatid — показать id текущего чата"
)


def short(addr: str) -> str:
    return f"{addr[:4]}…{addr[-4:]}"


def list_view(store: WalletStore, page: int) -> tuple[str, InlineKeyboardMarkup | None]:
    items = store.all()
    if not items:
        return "Список пуст. Пришли адрес кошелька, чтобы добавить.", None
    pages = (len(items) - 1) // PAGE_SIZE + 1
    page = max(0, min(page, pages - 1))
    chunk = items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    lines = [f"<b>Отслеживаемые кошельки: {len(items)}</b> (стр. {page + 1}/{pages})\n"]
    rows = []
    for i, (addr, label) in enumerate(chunk, start=page * PAGE_SIZE + 1):
        name = f" — {html.escape(label)}" if label else ""
        lines.append(f"{i}. <code>{addr}</code>{name}")
        rows.append([InlineKeyboardButton(
            text=f"❌ {label or short(addr)}"[:60], callback_data=f"d:{page}:{addr}"
        )])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"p:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"p:{page + 1}"))
    if nav:
        rows.append(nav)
    lines.append("\nНажми ❌, чтобы удалить кошелёк.")
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def usd(v: float) -> str:
    if v >= 1_000_000:
        return f"${v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:,.0f}"


def format_alert(event: dict, label: str | None, sol_usd: float | None = None) -> str:
    mint = event.get("mint", "")
    dev = event.get("traderPublicKey", "")
    name = html.escape(str(event.get("name", "?"))[:64])
    symbol = html.escape(str(event.get("symbol", "?"))[:20])
    sig = event.get("signature", "")
    dev_name = f"{html.escape(label)} (<code>{dev}</code>)" if label else f"<code>{dev}</code>"
    parts = [
        "🚀 <b>НОВАЯ МОНЕТА ОТ ДЕВА</b>",
        "",
        f"<b>{name}</b> (${symbol})",
        f"CA: <code>{mint}</code>",
        f"Dev: {dev_name}",
    ]
    if event.get("solAmount") is not None:
        sol = float(event["solAmount"])
        extra = f" ({usd(sol * sol_usd)})" if sol_usd else ""
        parts.append(f"Dev buy: {sol:.3f} SOL{extra}" if sol > 0 else "Dev buy: нет")
    if event.get("marketCapSol") is not None:
        mc = float(event["marketCapSol"])
        parts.append(f"MC: <b>{usd(mc * sol_usd)}</b>" if sol_usd else f"MC: {mc:.1f} SOL")
    if event.get("pool"):
        parts.append(f"Платформа: {html.escape(str(event['pool']))}")
    parts += [
        "",
        f'<a href="https://pump.fun/coin/{mint}">pump.fun</a> | '
        f'<a href="https://axiom.trade/t/{mint}">Axiom</a> | '
        f'<a href="https://gmgn.ai/sol/token/{mint}">GMGN</a> | '
        f'<a href="https://dexscreener.com/solana/{mint}">DexS</a> | '
        f'<a href="https://solscan.io/tx/{sig}">TX</a>',
    ]
    return "\n".join(parts)


async def send_alert(bot: Bot, chat_id: int, event: dict, label: str | None, sol_usd: float | None) -> None:
    text = format_alert(event, label, sol_usd)
    image = await fetch_image(event.get("uri"))
    if image:
        try:
            await bot.send_photo(chat_id, BufferedInputFile(image, "coin.png"), caption=text)
            return
        except Exception as e:  # битая картинка, слишком длинная подпись и т.п.
            log.info("Не удалось отправить фото, шлю текстом: %r", e)
    await bot.send_message(chat_id, text, disable_web_page_preview=True)


def build_router(store: WalletStore, admin_ids: frozenset[int], alert_chat_id: int,
                 price: SolPrice) -> Router:
    r = Router()
    # /chatid работает везде и для всех — чтобы узнать id группы для алертов
    @r.message(Command("chatid"))
    async def chatid(m: Message):
        await m.answer(f"chat_id: <code>{m.chat.id}</code>\nuser_id: <code>{m.from_user.id}</code>")

    # всё остальное — только админам и только в личке
    admin = Router()
    admin.message.filter(F.chat.type == ChatType.PRIVATE, F.from_user.id.in_(admin_ids))
    admin.callback_query.filter(F.from_user.id.in_(admin_ids))
    r.include_router(admin)

    async def add_from_text(m: Message, text: str):
        added, updated = [], []
        for line in text.splitlines():
            match = ADDR_RE.search(line)
            if not match:
                continue
            addr = match.group(0)
            rest = (line[:match.start()] + line[match.end():]).strip(" -—:|\t") or None
            (added if await store.add(addr, rest) else updated).append((addr, rest))
        if not added and not updated:
            await m.answer("Не нашёл Solana-адрес в сообщении 🤔", reply_markup=MAIN_KB)
            return
        out = []
        for addr, lbl in added:
            out.append(f"✅ Добавлен: <code>{addr}</code>" + (f" — {html.escape(lbl)}" if lbl else ""))
        for addr, lbl in updated:
            out.append(f"♻️ Уже был, метка обновлена: <code>{addr}</code>" + (f" — {html.escape(lbl)}" if lbl else ""))
        out.append(f"\nВсего отслеживается: {len(store.all())}")
        await m.answer("\n".join(out), reply_markup=MAIN_KB)

    @admin.message(CommandStart())
    @admin.message(Command("help"))
    async def start(m: Message):
        await m.answer(HELP, reply_markup=MAIN_KB)

    @admin.message(Command("add"))
    async def add_cmd(m: Message, command: CommandObject):
        if not command.args:
            await m.answer("Формат: /add <code>АДРЕС [метка]</code>")
            return
        await add_from_text(m, command.args)

    @admin.message(F.text == BTN_ADD)
    async def add_btn(m: Message):
        await m.answer("Пришли адрес кошелька (можно с меткой через пробел, можно несколько строк).")

    @admin.message(Command("remove", "del", "delete"))
    async def remove_cmd(m: Message, command: CommandObject):
        addrs = ADDR_RE.findall(command.args or "")
        if not addrs:
            await m.answer("Формат: /remove <code>АДРЕС</code>\nИли открой /list и нажми ❌.")
            return
        out = []
        for a in addrs:
            ok = await store.remove(a)
            out.append(f"{'🗑 Удалён' if ok else '⚠️ Не найден'}: <code>{a}</code>")
        await m.answer("\n".join(out))

    @admin.message(Command("list"))
    @admin.message(F.text.in_({BTN_LIST, BTN_DEL}))
    async def list_cmd(m: Message):
        text, kb = list_view(store, 0)
        await m.answer(text, reply_markup=kb)

    @admin.callback_query(F.data.startswith("p:"))
    async def page_cb(c: CallbackQuery):
        text, kb = list_view(store, int(c.data.split(":")[1]))
        await c.message.edit_text(text, reply_markup=kb)
        await c.answer()

    @admin.callback_query(F.data.startswith("d:"))
    async def del_cb(c: CallbackQuery):
        _, page, addr = c.data.split(":", 2)
        ok = await store.remove(addr)
        await c.answer("Удалён" if ok else "Уже удалён")
        text, kb = list_view(store, int(page))
        await c.message.edit_text(text, reply_markup=kb)

    @admin.message(Command("clear"))
    async def clear_cmd(m: Message):
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Да, удалить все", callback_data="clear:yes"),
            InlineKeyboardButton(text="Отмена", callback_data="clear:no"),
        ]])
        await m.answer(f"Удалить все кошельки ({len(store.all())})?", reply_markup=kb)

    @admin.callback_query(F.data.startswith("clear:"))
    async def clear_cb(c: CallbackQuery):
        if c.data == "clear:yes":
            n = await store.clear()
            await c.message.edit_text(f"🗑 Удалено кошельков: {n}")
        else:
            await c.message.edit_text("Отменено.")
        await c.answer()

    @admin.message(Command("test"))
    async def test_cmd(m: Message, bot: Bot):
        fake = {
            "mint": "So11111111111111111111111111111111111111112",
            "uri": "https://ipfs.io/ipfs/bafkreicavsn2tsgh2nr5bsf4uhuu4nnhhtkl4476icf6a6kkpi3ihz4zhq",
            "traderPublicKey": "11111111111111111111111111111111",
            "name": "TEST", "symbol": "TEST", "solAmount": 1.0, "marketCapSol": 30.0,
            "signature": "", "pool": "pump",
        }
        try:
            fake["name"] = "🧪 TEST"
            await send_alert(bot, alert_chat_id, fake, "test", price.usd)
            await m.answer(f"Тестовый алерт отправлен в <code>{alert_chat_id}</code> ✅")
        except Exception as e:
            await m.answer(f"Не смог отправить в <code>{alert_chat_id}</code>: {html.escape(str(e))}\n"
                           "Проверь, что бот добавлен в чат и может писать.")

    @admin.message(F.text)
    async def any_text(m: Message):
        await add_from_text(m, m.text)

    return r


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    store = WalletStore(cfg.db_path)
    await store.init()
    log.info("Загружено кошельков: %d", len(store.all()))

    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    price = SolPrice()
    await price.refresh()
    log.info("Цена SOL: %s USD", price.usd)
    dp.include_router(build_router(store, cfg.admin_ids, cfg.alert_chat_id, price))

    async def on_launch(event: dict) -> None:
        label = store.label(event["traderPublicKey"])
        log.info("Запуск от %s: %s", event["traderPublicKey"], event.get("mint"))
        await send_alert(bot, cfg.alert_chat_id, event, label, price.usd)

    watcher = asyncio.create_task(watch_launches(store, on_launch))
    price_task = asyncio.create_task(price.run())
    try:
        await dp.start_polling(bot)
    finally:
        watcher.cancel()
        price_task.cancel()
        await bot.session.close()
        await http.close()
