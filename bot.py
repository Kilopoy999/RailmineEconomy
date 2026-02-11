import asyncio
import random
import time
import secrets
import string
from dataclasses import dataclass

import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

import os

BOT_TOKEN = ("8421577436:AAE8bStcM2qVxtwrJUnH0Kw8bu0QN5agjDc")

ADMIN_IDS = (6339108316) 

DB_PATH = ("exchange.db")

ASSETS = ["USD", "BTC", "ETH", "SOL", "BNB", "XRP", "TON"]
CRYPTO = ["BTC", "ETH", "SOL", "BNB", "XRP", "TON"]

DEFAULT_PRICES = {
   "BTC": 65000.0,
   "ETH": 3500.0,
   "SOL": 150.0,
   "BNB": 600.0,
   "XRP": 0.55,
   "TON": 5.5,
}
VOL = {
   "BTC": 0.004,
   "ETH": 0.006,
   "SOL": 0.010,
   "BNB": 0.006,
   "XRP": 0.012,
   "TON": 0.010,
}
PRICE_TICK_SECONDS = 10

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


def is_admin(tg_id: int) -> bool:
   return tg_id in ADMIN_IDS


def now_ts() -> int:
   return int(time.time())


def gen_code(prefix="RP", n=10):
   alphabet = string.ascii_uppercase + string.digits
   core = "".join(secrets.choice(alphabet) for _ in range(n))
   return f"{prefix}-{core}"


# --- Simple per-user state machine (no FSM storage needed) ---
@dataclass
class Pending:
   action: str
   data: dict

PENDING: dict[int, Pending] = {}


# ---------------- DB ----------------
async def init_db():
   async with aiosqlite.connect(DB_PATH) as db:
     await db.execute("""
     CREATE TABLE IF NOT EXISTS users(
       tg_id INTEGER PRIMARY KEY,
       login TEXT NOT NULL,
       bank_id TEXT NOT NULL UNIQUE,
       created_at INTEGER NOT NULL
     )""")

     await db.execute("""
     CREATE TABLE IF NOT EXISTS balances(
       tg_id INTEGER NOT NULL,
       asset TEXT NOT NULL,
       amount REAL NOT NULL DEFAULT 0,
       PRIMARY KEY (tg_id, asset),
       FOREIGN KEY (tg_id) REFERENCES users(tg_id)
     )""")

     await db.execute("""
     CREATE TABLE IF NOT EXISTS prices(
       asset TEXT PRIMARY KEY,
       price_usd REAL NOT NULL,
       updated_at INTEGER NOT NULL
     )""")

     # One-time checks
     await db.execute("""
     CREATE TABLE IF NOT EXISTS promo_codes(
       code TEXT PRIMARY KEY,
       asset TEXT NOT NULL,
       amount REAL NOT NULL,
       used_by_tg_id INTEGER,
       used_at INTEGER,
       expires_at INTEGER,
       created_by INTEGER NOT NULL,
       created_at INTEGER NOT NULL,
       note TEXT
     )""")

     # Tickets
     await db.execute("""
     CREATE TABLE IF NOT EXISTS tickets(
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       tg_id INTEGER NOT NULL,
       bank_id TEXT NOT NULL,
       type TEXT NOT NULL,        -- deposit | withdraw
       amount REAL NOT NULL,
       status TEXT NOT NULL,       -- open | approved | rejected
       created_at INTEGER NOT NULL,
       handled_by INTEGER,
       handled_at INTEGER,
       admin_note TEXT,
       FOREIGN KEY (tg_id) REFERENCES users(tg_id)
     )""")

     for a, p in DEFAULT_PRICES.items():
       await db.execute(
         "INSERT OR IGNORE INTO prices(asset, price_usd, updated_at) VALUES (?, ?, ?)",
                  (a, float(p), now_ts())
       )

     await db.commit()


async def get_user_by_tg(db, tg_id: int):
   cur = await db.execute("SELECT tg_id, login, bank_id FROM users WHERE tg_id=?", (tg_id,))
   return await cur.fetchone()


async def get_user_by_bank_id(db, bank_id: str):
   cur = await db.execute("SELECT tg_id, login, bank_id FROM users WHERE bank_id=?", (bank_id,))
   return await cur.fetchone()


async def ensure_balance(db, tg_id: int, asset: str):
   await db.execute(
     "INSERT OR IGNORE INTO balances(tg_id, asset, amount) VALUES(?, ?, 0)",
     (tg_id, asset)
   )


async def add_balance(db, tg_id: int, asset: str, delta: float):
   await ensure_balance(db, tg_id, asset)
   await db.execute(
     "UPDATE balances SET amount = amount + ? WHERE tg_id=? AND asset=?",
     (float(delta), tg_id, asset)
   )


async def get_balance(db, tg_id: int, asset: str) -> float:
   cur = await db.execute("SELECT amount FROM balances WHERE tg_id=? AND asset=?", (tg_id, asset))
   row = await cur.fetchone()
   return float(row[0]) if row else 0.0


async def get_balances(db, tg_id: int):
   cur = await db.execute("SELECT asset, amount FROM balances WHERE tg_id=? ORDER BY asset", (tg_id,))
   return await cur.fetchall()


async def get_price(db, asset: str) -> float | None:
   cur = await db.execute("SELECT price_usd FROM prices WHERE asset=?", (asset,))
   row = await cur.fetchone()
   return float(row[0]) if row else None


async def get_prices(db):
   cur = await db.execute("SELECT asset, price_usd FROM prices ORDER BY asset")
   return await cur.fetchall()


# ---------------- UI ----------------
def kb_main(is_admin_user: bool = False):
   kb = InlineKeyboardBuilder()
   kb.button(text="💰 Баланс", callback_data="m:balance")
   kb.button(text="📈 Курсы", callback_data="m:rates")
   kb.button(text="🟢 Купить", callback_data="m:buy")
   kb.button(text="🔴 Продать", callback_data="m:sell")
   kb.button(text="🤝 P2P перевод", callback_data="m:p2p")
   kb.button(text="🎟 Активировать чек", callback_data="m:redeem")
   kb.button(text="📝 Тикеты (депозит/вывод)", callback_data="m:tickets")
   if is_admin_user:
     kb.button(text="🛠 Админ: создать чек", callback_data="a:promo_create")
     kb.button(text="🧾 Админ: тикеты (очередь)", callback_data="a:tickets_list")
   kb.adjust(2, 2, 2, 1, 2)
   return kb.as_markup()


def kb_buy_assets():
   kb = InlineKeyboardBuilder()
   for a in CRYPTO:
     kb.button(text=a, callback_data=f"buy_asset:{a}")
   kb.button(text="⬅️ Назад", callback_data="back:main")
   kb.adjust(3, 3, 1)
   return kb.as_markup()


def kb_sell_assets():
   kb = InlineKeyboardBuilder()
   for a in CRYPTO:
     kb.button(text=a, callback_data=f"sell_asset:{a}")
   kb.button(text="⬅️ Назад", callback_data="back:main")
   kb.adjust(3, 3, 1)
   return kb.as_markup()


def kb_tickets():
   kb = InlineKeyboardBuilder()
   kb.button(text="➕ Создать депозит", callback_data="t:new:deposit")
   kb.button(text="➖ Создать вывод", callback_data="t:new:withdraw")
   kb.button(text="📋 Мои тикеты", callback_data="t:my")
   kb.button(text="⬅️ Назад", callback_data="back:main")
   kb.adjust(2, 1, 1)
   return kb.as_markup()


def kb_admin_ticket_actions(ticket_id: int):
   kb = InlineKeyboardBuilder()
   kb.button(text="✅ Одобрить", callback_data=f"at:approve:{ticket_id}")
   kb.button(text="❌ Отклонить", callback_data=f"at:reject:{ticket_id}")
   kb.button(text="⬅️ Назад к очереди", callback_data="a:tickets_list")
   kb.adjust(2, 1)
   return kb.as_markup()


# ---------------- Helpers ----------------
async def require_user(m: Message) -> bool:
   async with aiosqlite.connect(DB_PATH) as db:
     u = await get_user_by_tg(db, m.from_user.id)
   if not u:
     await m.answer("Сначала зарегистрируйся: /start")
     return False
   return True


async def show_main(chat_id: int, text="Меню:"):
   await bot.send_message(chat_id, text, reply_markup=kb_main(is_admin(chat_id)))


# ---------------- Commands ----------------
@dp.message(Command("start"))
async def cmd_start(m: Message):
   async with aiosqlite.connect(DB_PATH) as db:
     u = await get_user_by_tg(db, m.from_user.id)
   if u:
     await m.answer("Ты уже зарегистрирован.", reply_markup=kb_main(is_admin(m.from_user.id)))
     return

   PENDING[m.from_user.id] = Pending(action="register", data={})
   await m.answer(
     "Регистрация.\nОтправь одним сообщением: `login bank_id`\n"
     "Пример: `kilo 12345`\n\n"
     "bank_id ты задаёшь сам (должен быть уникальным).",
     parse_mode="Markdown"
   )


@dp.message(Command("menu"))
async def cmd_menu(m: Message):
   await m.answer("Меню:", reply_markup=kb_main(is_admin(m.from_user.id)))


# ---------------- Callbacks: main menu ----------------
@dp.callback_query(F.data == "back:main")
async def cb_back_main(c: CallbackQuery):
   await c.message.edit_text("Меню:", reply_markup=kb_main(is_admin(c.from_user.id)))
   await c.answer()


@dp.callback_query(F.data == "m:balance")
async def cb_balance(c: CallbackQuery):
   async with aiosqlite.connect(DB_PATH) as db:
     u = await get_user_by_tg(db, c.from_user.id)
     if not u:
       await c.answer("Сначала /start", show_alert=True)
       return
     rows = await get_balances(db, c.from_user.id)
   text = "Баланс:\n" + "\n".join([f"{a}: {amt:.8f}" for a, amt in rows])
   await c.message.edit_text(text, reply_markup=kb_main(is_admin(c.from_user.id)))
   await c.answer()


@dp.callback_query(F.data == "m:rates")
async def cb_rates(c: CallbackQuery):
   async with aiosqlite.connect(DB_PATH) as db:
     rows = await get_prices(db)
   text = "Курсы (USD):\n" + "\n".join([f"{a}: {p:.6f}" for a, p in rows])
   await c.message.edit_text(text, reply_markup=kb_main(is_admin(c.from_user.id)))
   await c.answer()


@dp.callback_query(F.data == "m:buy")
async def cb_buy(c: CallbackQuery):
   async with aiosqlite.connect(DB_PATH) as db:
     u = await get_user_by_tg(db, c.from_user.id)
     if not u:
       await c.answer("Сначала /start", show_alert=True)
       return
   await c.message.edit_text("Выбери актив для покупки:", reply_markup=kb_buy_assets())
   await c.answer()


@dp.callback_query(F.data == "m:sell")
async def cb_sell(c: CallbackQuery):
   async with aiosqlite.connect(DB_PATH) as db:
     u = await get_user_by_tg(db, c.from_user.id)
     if not u:
       await c.answer("Сначала /start", show_alert=True)
       return
   await c.message.edit_text("Выбери актив для продажи:", reply_markup=kb_sell_assets())
   await c.answer()


@dp.callback_query(F.data == "m:p2p")
async def cb_p2p(c: CallbackQuery):
   async with aiosqlite.connect(DB_PATH) as db:
     u = await get_user_by_tg(db, c.from_user.id)
     if not u:
       await c.answer("Сначала /start", show_alert=True)
       return
   PENDING[c.from_user.id] = Pending(action="p2p", data={})
   await c.message.edit_text(
     "P2P перевод.\nОтправь сообщением: `bank_id ASSET amount`\n"
     "Пример: `12345 USD 50`",
     parse_mode="Markdown",
     reply_markup=kb_main(is_admin(c.from_user.id))
   )
   await c.answer()


@dp.callback_query(F.data == "m:redeem")
async def cb_redeem(c: CallbackQuery):
   async with aiosqlite.connect(DB_PATH) as db:
     u = await get_user_by_tg(db, c.from_user.id)
     if not u:
       await c.answer("Сначала /start", show_alert=True)
       return
   PENDING[c.from_user.id] = Pending(action="redeem", data={})
   await c.message.edit_text(
     "Активация чека.\nОтправь код одним сообщением.\nПример: `RP-AB12CD34EF`",
     parse_mode="Markdown",
     reply_markup=kb_main(is_admin(c.from_user.id))
   )
   await c.answer()


@dp.callback_query(F.data == "m:tickets")
async def cb_tickets(c: CallbackQuery):
   async with aiosqlite.connect(DB_PATH) as db:
     u = await get_user_by_tg(db, c.from_user.id)
     if not u:
       await c.answer("Сначала /start", show_alert=True)
       return
   await c.message.edit_text("Тикеты:", reply_markup=kb_tickets())
   await c.answer()
  async def cb_admin_ticket_view(c: CallbackQuery):
   if not is_admin(c.from_user.id):
     await c.answer("Нет доступа", show_alert=True)
     return
   tid = int(c.data.split(":")[-1])

   async with aiosqlite.connect(DB_PATH) as db:
     cur = await db.execute("""
       SELECT id, tg_id, bank_id, type, amount, status, created_at
       FROM tickets WHERE id=?
     """, (tid,))
     row = await cur.fetchone()

   if not row:
     await c.answer("Тикет не найден", show_alert=True)
     return

   id_, tg_id, bank_id, ttype, amt, st, ca = row
   text = (
     f"Тикет #{id_}\n"
     f"Пользователь tg_id: {tg_id}\n"
     f"bank_id: {bank_id}\n"
     f"type: {ttype}\n"
     f"amount: {amt:.2f} USD\n"
     f"status: {st}\n"
     f"created: {time.strftime('%Y-%m-%d %H:%M', time.localtime(ca))}"
   )
   await c.message.edit_text(text, reply_markup=kb_admin_ticket_actions(id_))
   await c.answer()


@dp.callback_query(F.data.startswith("at:approve:"))
async def cb_admin_ticket_approve(c: CallbackQuery):
   if not is_admin(c.from_user.id):
     await c.answer("Нет доступа", show_alert=True)
     return
   tid = int(c.data.split(":")[-1])

   async with aiosqlite.connect(DB_PATH) as db:
     # load
     cur = await db.execute("""
       SELECT id, tg_id, type, amount, status
       FROM tickets WHERE id=?
     """, (tid,))
     row = await cur.fetchone()
     if not row:
       await c.answer("Не найдено", show_alert=True)
       return
     _, tg_id, ttype, amt, st = row
     if st != "open":
       await c.answer("Уже обработан", show_alert=True)
       return

     # Apply RP logic INSIDE bot:
     # deposit approved => +USD
     # withdraw approved => -USD if достаточен баланс
     if ttype == "deposit":
       await add_balance(db, tg_id, "USD", float(amt))
     elif ttype == "withdraw":
       bal = await get_balance(db, tg_id, "USD")
       if bal < float(amt):
         await c.answer("Недостаточно USD у пользователя", show_alert=True)
         return
       await add_balance(db, tg_id, "USD", -float(amt))
     else:
       await c.answer("Неверный тип", show_alert=True)
       return

     await db.execute("""
       UPDATE tickets
       SET status='approved', handled_by=?, handled_at=?
       WHERE id=?
     """, (c.from_user.id, now_ts(), tid))
     await db.commit()

   # notify user
   try:
     await bot.send_message(tg_id, f"Тикет #{tid} одобрен. Изменение баланса применено.")
   except:
     pass

   await c.message.edit_text(f"Тикет #{tid} ✅ одобрен.", reply_markup=kb_main(True))
   await c.answer()


@dp.callback_query(F.data.startswith("at:reject:"))
async def cb_admin_ticket_reject(c: CallbackQuery):
   if not is_admin(c.from_user.id):
     await c.answer("Нет доступа", show_alert=True)
     return
   tid = int(c.data.split(":")[-1])

   PENDING[c.from_user.id] = Pending(action="admin_reject_note", data={"ticket_id": tid})
   await c.message.edit_text(
     f"Отклонение тикета #{tid}.\nОтправь причину (1 сообщением).",
     reply_markup=kb_main(True)
   )
   await c.answer()


# ---------------- Text handler for pending actions ----------------
@dp.message(F.text)
async def on_text(m: Message):
   pend = PENDING.get(m.from_user.id)
   if not pend:
     # если человек просто пишет — покажем меню
     await m.answer("Открой меню: /menu", reply_markup=kb_main(is_admin(m.from_user.id)))
     return

   try:
     if pend.action == "register":
       if len(m.text.split()) < 2:
         await m.answer("Нужно: `login bank_id`", parse_mode="Markdown")
         return
       login, bank_id = m.text.split(maxsplit=1)
       bank_id = bank_id.strip()

       async with aiosqlite.connect(DB_PATH) as db:
         if await get_user_by_tg(db, m.from_user.id):
           PENDING.pop(m.from_user.id, None)
           await m.answer("Ты уже зарегистрирован.", reply_markup=kb_main(is_admin(m.from_user.id)))
           return
         if await get_user_by_bank_id(db, bank_id):
                      await m.answer("Этот bank_id уже занят. Выбери другой.")
           return

         await db.execute(
           "INSERT INTO users(tg_id, login, bank_id, created_at) VALUES (?, ?, ?, ?)",
           (m.from_user.id, login, bank_id, now_ts())
         )
         # Баланс 0, только через чеки/тикеты
         await add_balance(db, m.from_user.id, "USD", 0.0)
         for a in CRYPTO:
           await ensure_balance(db, m.from_user.id, a)
         await db.commit()

       PENDING.pop(m.from_user.id, None)
       await m.answer("Регистрация завершена. Открой меню:", reply_markup=kb_main(is_admin(m.from_user.id)))
       return

     if pend.action == "redeem":
       code = m.text.strip().upper()
       async with aiosqlite.connect(DB_PATH) as db:
         u = await get_user_by_tg(db, m.from_user.id)
         if not u:
           await m.answer("Сначала /start")
           return

         cur = await db.execute("""
           SELECT code, asset, amount, used_by_tg_id, expires_at
           FROM promo_codes WHERE code=?
         """, (code,))
         row = await cur.fetchone()
         if not row:
           await m.answer("Чек не найден.")
           return
         _, asset, amount, used_by, expires_at = row

         if expires_at is not None and now_ts() > expires_at:
           await m.answer("Срок чека истёк.")
           return
         if used_by is not None:
           await m.answer("Чек уже использован.")
           return

         # атомарно занять чек: UPDATE ... WHERE used_by IS NULL
         res = await db.execute("""
           UPDATE promo_codes
           SET used_by_tg_id=?, used_at=?
           WHERE code=? AND used_by_tg_id IS NULL
            AND (expires_at IS NULL OR expires_at >= ?)
         """, (m.from_user.id, now_ts(), code, now_ts()))
         if res.rowcount != 1:
           await db.rollback()
           await m.answer("Не удалось активировать (возможно, уже заняли).")
           return

         await add_balance(db, m.from_user.id, asset, float(amount))
         await db.commit()

       PENDING.pop(m.from_user.id, None)
       await m.answer(f"Готово: +{amount:.2f} {asset}", reply_markup=kb_main(is_admin(m.from_user.id)))
       return

     if pend.action == "buy_amount":
       asset = pend.data["asset"]
       try:
         usd_amount = float(m.text.strip())
       except:
         await m.answer("Нужно число (USD).")
         return
       if usd_amount <= 0:
         await m.answer("Сумма должна быть > 0")
         return

       async with aiosqlite.connect(DB_PATH) as db:
         if not await get_user_by_tg(db, m.from_user.id):
           await m.answer("Сначала /start")
           return
         price = await get_price(db, asset)
         usd_bal = await get_balance(db, m.from_user.id, "USD")
         if usd_bal < usd_amount:
           await m.answer("Недостаточно USD.")
           return
         qty = usd_amount / price
         await add_balance(db, m.from_user.id, "USD", -usd_amount)
         await add_balance(db, m.from_user.id, asset, qty)
         await db.commit()

       PENDING.pop(m.from_user.id, None)
       await m.answer(f"Куплено {qty:.8f} {asset} за {usd_amount:.2f} USD", reply_markup=kb_main(is_admin(m.from_user.id)))
       return

     if pend.action == "sell_amount":
       asset = pend.data["asset"]
       try:
         qty = float(m.text.strip())
       except:
         await m.answer("Нужно число (кол-во).")
         return
       if qty <= 0:
         await m.answer("Количество должно быть > 0")
         return

       async with aiosqlite.connect(DB_PATH) as db:
         if not await get_user_by_tg(db, m.from_user.id):
           await m.answer("Сначала /start")
           return
         price = await get_price(db, asset)
         bal = await get_balance(db, m.from_user.id, asset)
         if bal < qty:
           await m.answer(f"Недостаточно {asset}.")
           return
         usd_amount = qty * price
                  await add_balance(db, m.from_user.id, asset, -qty)
         await add_balance(db, m.from_user.id, "USD", usd_amount)
         await db.commit()

       PENDING.pop(m.from_user.id, None)
       await m.answer(f"Продано {qty:.8f} {asset} за {usd_amount:.2f} USD", reply_markup=kb_main(is_admin(m.from_user.id)))
       return

     if pend.action == "p2p":
       # bank_id ASSET amount
       parts = m.text.split()
       if len(parts) != 3:
         await m.answer("Нужно: `bank_id ASSET amount`", parse_mode="Markdown")
         return
       to_bank_id = parts[0].strip()
       asset = parts[1].upper()
       try:
         amount = float(parts[2])
       except:
         await m.answer("amount должно быть числом.")
         return
       if asset not in ASSETS or amount <= 0:
         await m.answer("Неверная валюта или сумма.")
         return

       async with aiosqlite.connect(DB_PATH) as db:
         u = await get_user_by_tg(db, m.from_user.id)
         if not u:
           await m.answer("Сначала /start")
           return
         to_u = await get_user_by_bank_id(db, to_bank_id)
         if not to_u:
           await m.answer("Получатель не найден.")
           return
         to_tg = int(to_u[0])
         if to_tg == m.from_user.id:
           await m.answer("Нельзя отправить себе.")
           return
         bal = await get_balance(db, m.from_user.id, asset)
         if bal < amount:
           await m.answer("Недостаточно средств.")
           return
         await add_balance(db, m.from_user.id, asset, -amount)
         await add_balance(db, to_tg, asset, amount)
         await db.commit()

       PENDING.pop(m.from_user.id, None)
       await m.answer(f"Отправлено {amount:.8f} {asset} пользователю {to_bank_id}", reply_markup=kb_main(is_admin(m.from_user.id)))
       return

     if pend.action == "ticket_amount":
       ttype = pend.data["type"]
       try:
         amount = float(m.text.strip())
       except:
         await m.answer("Сумма должна быть числом.")
         return
       if amount <= 0:
         await m.answer("Сумма должна быть > 0")
         return

       async with aiosqlite.connect(DB_PATH) as db:
         u = await get_user_by_tg(db, m.from_user.id)
         if not u:
           await m.answer("Сначала /start")
           return
         _, login, bank_id = u
         await db.execute("""
           INSERT INTO tickets(tg_id, bank_id, type, amount, status, created_at)
           VALUES (?, ?, ?, ?, 'open', ?)
         """, (m.from_user.id, bank_id, ttype, float(amount), now_ts()))
         await db.commit()

       PENDING.pop(m.from_user.id, None)
       await m.answer(f"Тикет создан: {ttype} на {amount:.2f} USD.\nОжидай решения админа.", reply_markup=kb_main(is_admin(m.from_user.id)))
       return

     if pend.action == "admin_promo_amount":
       if not is_admin(m.from_user.id):
         PENDING.pop(m.from_user.id, None)
         return
       parts = m.text.split()
       try:
         amount = float(parts[0])
       except:
         await m.answer("Нужно число, например: 500 или `500 7`", parse_mode="Markdown")
         return
       days = None
       if len(parts) >= 2:
         try:
           days = int(parts[1])
         except:
           await m.answer("Второй параметр (days) должен быть целым числом.")
           return
       if amount <= 0:
         await m.answer("amount должен быть > 0")
         return

       code = gen_code("RP", 10)
       expires_at = None if days is None else now_ts() + days * 86400

       async with aiosqlite.connect(DB_PATH) as db:
         await db.execute("""
           INSERT INTO promo_codes(code, asset, amount, used_by_tg_id, used_at, expires_at, created_by, created_at)
           VALUES (?, 'USD', ?, NULL, NULL, ?, ?, ?)
         """, (code, float(amount), expires_at, m.from_user.id, now_ts()))
         await db.commit()

       PENDING.pop(m.from_user.id, None)
