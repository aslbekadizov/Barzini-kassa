import asyncio
import json
import os
import re
import sqlite3
from contextlib import closing
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup
from telegram.error import RetryAfter, TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# =========================================================
# SOZLAMALAR
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Kassirning Telegram ID raqami
CASHIER_ID = int(os.environ.get("CASHIER_ID", "0"))

# Kirim va xarajat xabarlari boradigan odamning Telegram ID raqami
REPORT_CHAT_ID = int(os.environ.get("REPORT_CHAT_ID", "0"))

DB_PATH = Path(__file__).with_name("kassa.db")

TZ = ZoneInfo("Asia/Tashkent")


# =========================================================
# HOLATLAR
# =========================================================

CHOOSE_CURRENCY, INCOME_AMOUNT, EXCHANGE_USD, EXCHANGE_UZS = range(4)
RESET_CONFIRM = 4
CARD_EXPENSE = 5
STATISTICS_PERIOD = 6
CLIENT_LIST, CLIENT_NAME, CLIENT_MENU, OTHER_MENU = range(7, 11)
CLIENT_SPLIT_USD, CLIENT_SPLIT_CARD = range(11, 13)
CLIENT_DELETE_CONFIRM = 18
CLIENT_EXPENSE_ACCOUNT = 19
UNDO_LIST, UNDO_CONFIRM, OTHER_USD = range(20, 23)
UNDO_BUTTON = "↩️ Tranzaksiyani qaytarish"
UNDO_CONFIRM_BUTTON = "✅ Qaytarish"
UNDO_PREV = "⬅️ Oldingi yozuvlar"
UNDO_NEXT = "➡️ Keyingi yozuvlar"
EMPLOYEE_LIST, EMPLOYEE_NAME, EMPLOYEE_MENU, EMPLOYEE_CURRENCY, EMPLOYEE_AMOUNT = range(13, 18)
EMPLOYEES_BUTTON = "👷 Xodimlar"
ADD_EMPLOYEE_BUTTON = "➕ Xodim qo'shish"
EMPLOYEE_PAY_BUTTON = "💸 Pul berish"
EMPLOYEE_REPORT_BUTTON = "📒 Xodim hisobi"
EMPLOYEE_PREV = "⬅️ Oldingi xodimlar"
EMPLOYEE_NEXT = "➡️ Keyingi xodimlar"

CARD_BUTTON = "💳 Karta"
BALANCE_BUTTON = "💰 Balans"
CARD_EXPENSE_BUTTON = "💳 Kartadan"
STATISTICS_BUTTON = "📊 Statistika"
BACK_BUTTON = "⬅️ Asosiy menyu"
CLIENTS_BUTTON = "👥 Mijozlar"
ADD_CLIENT_BUTTON = "➕ Mijoz qo'shish"
DELETE_CLIENT_BUTTON = "🗑 Mijozni o'chirish"
DELETE_CLIENT_CONFIRM = "✅ Ha, o'chirish"
CLIENT_INCOME_BUTTON = "💰 Mijozdan pul oldim"
CLIENT_SPLIT_BUTTON = "💵 Dollar + 💳 Karta"
CLIENT_CASH_BUTTON = "💸 Xarajat yozish"
CLIENT_CARD_BUTTON = "💳 Mijoz uchun kartadan"
CLIENT_REPORT_BUTTON = "📒 Mijoz hisobi"
OTHER_BUTTON = "🧾 Boshqa xarajatlar"
OTHER_CASH_BUTTON = "💸 Boshqa naqd xarajat"
OTHER_USD_BUTTON = "💵 Boshqa dollar xarajat"
OTHER_CARD_BUTTON = "💳 Boshqa xarajat kartadan"
OTHER_REPORT_BUTTON = "📒 Boshqa xarajatlar hisobi"
PREV_CLIENTS_BUTTON = "⬅️ Oldingi mijozlar"
NEXT_CLIENTS_BUTTON = "➡️ Keyingi mijozlar"
CLIENT_PAGE_SIZE = 10
STATISTICS_PERIODS = {
    "📅 Bugun": ("today", "Bugun"),
    "🗓 Shu oy": ("month", "Shu oy"),
    "📋 Barcha vaqt": ("all", "Barcha vaqt"),
}


# =========================================================
# TUGMALAR
# =========================================================

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["💰 Pul oldim", "💵 $ maydalash"],
        [CARD_EXPENSE_BUTTON, STATISTICS_BUTTON],
        [CLIENTS_BUTTON, OTHER_BUTTON],
        [EMPLOYEES_BUTTON, BALANCE_BUTTON],
        [UNDO_BUTTON],
    ],
    resize_keyboard=True
)

CURRENCY_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🇺🇿 So'm", "🇺🇸 Dollar"],
        [CARD_BUTTON],
        ["⬅️ Bekor qilish"],
    ],
    resize_keyboard=True
)

CLIENT_CURRENCY_KEYBOARD = ReplyKeyboardMarkup(
    [["🇺🇿 So'm", "🇺🇸 Dollar"], [CARD_BUTTON, CLIENT_SPLIT_BUTTON], ["⬅️ Bekor qilish"]],
    resize_keyboard=True
)

CANCEL_KEYBOARD = ReplyKeyboardMarkup(
    [["⬅️ Bekor qilish"]],
    resize_keyboard=True
)

RESET_CONFIRM_TEXT = "✅ Ha, nolga tushirish"
RESET_KEYBOARD = ReplyKeyboardMarkup(
    [[RESET_CONFIRM_TEXT], ["⬅️ Bekor qilish"]],
    resize_keyboard=True
)

STATISTICS_KEYBOARD = ReplyKeyboardMarkup(
    [["📅 Bugun", "🗓 Shu oy"], ["📋 Barcha vaqt"], [BACK_BUTTON]],
    resize_keyboard=True
)

CLIENT_KEYBOARD = ReplyKeyboardMarkup(
    [[CLIENT_INCOME_BUTTON], [CLIENT_CASH_BUTTON],
     [CLIENT_REPORT_BUTTON], [DELETE_CLIENT_BUTTON], [CLIENTS_BUTTON, BACK_BUTTON]],
    resize_keyboard=True
)

OTHER_KEYBOARD = ReplyKeyboardMarkup(
    [[OTHER_CASH_BUTTON, OTHER_CARD_BUTTON], [OTHER_USD_BUTTON], [OTHER_REPORT_BUTTON], [BACK_BUTTON]],
    resize_keyboard=True
)

CLIENT_EXPENSE_KEYBOARD = ReplyKeyboardMarkup(
    [["💵 Naqd so'm", CARD_BUTTON, "🇺🇸 Dollar"], ["⬅️ Bekor qilish"]], resize_keyboard=True
)

BOSS_KEYBOARD = ReplyKeyboardMarkup(
    [[CLIENTS_BUTTON, EMPLOYEES_BUTTON], [BALANCE_BUTTON, STATISTICS_BUTTON]], resize_keyboard=True
)
BOSS_CLIENT_KEYBOARD = ReplyKeyboardMarkup(
    [[CLIENT_REPORT_BUTTON], [CLIENTS_BUTTON, BACK_BUTTON]], resize_keyboard=True
)


# =========================================================
# DATABASE
# =========================================================

def init_db():
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                name_key TEXT NOT NULL UNIQUE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                currency TEXT NOT NULL,
                amount INTEGER NOT NULL,
                note TEXT,
                actor_id INTEGER,
                account TEXT NOT NULL DEFAULT 'cash',
                client_id INTEGER REFERENCES clients(id)
            )
        """)
        client_columns = {row[1] for row in conn.execute("PRAGMA table_info(clients)")}
        if "archived" not in client_columns:
            conn.execute("ALTER TABLE clients ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(transactions)")}
        if "account" not in columns:
            # Eski operatsiyalar va qoldiqlar naqd hisobda saqlanadi.
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN account TEXT NOT NULL DEFAULT 'cash'"
            )
        if "client_id" not in columns:
            conn.execute("ALTER TABLE transactions ADD COLUMN client_id INTEGER REFERENCES clients(id)")
        conn.execute("CREATE INDEX IF NOT EXISTS transactions_client ON transactions(client_id, created_at, id)")
        conn.execute("CREATE TABLE IF NOT EXISTS employees (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE)")
        conn.execute("""CREATE TABLE IF NOT EXISTS employee_payments (
            transaction_id INTEGER PRIMARY KEY REFERENCES transactions(id) ON DELETE CASCADE,
            employee_id INTEGER NOT NULL REFERENCES employees(id)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS payments_employee ON employee_payments(employee_id, transaction_id)")
        conn.execute("""CREATE TABLE IF NOT EXISTS transaction_undo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            undone_at TEXT NOT NULL, actor_id INTEGER, original_rows TEXT NOT NULL
        )""")


def add_employee(name):
    name = " ".join(name.split())
    if not name or len(name) > 80 or not any(c.isalnum() for c in name):
        raise ValueError("Xodim ismi 1–80 belgi bo'lsin")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("INSERT INTO employees(name, name_key) VALUES (?, ?) ON CONFLICT(name_key) DO NOTHING", (name, name.casefold()))
        return conn.execute("SELECT id, name FROM employees WHERE name_key = ?", (name.casefold(),)).fetchone()


def get_employee(employee_id):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute("SELECT id, name FROM employees WHERE id = ?", (employee_id,)).fetchone()


def get_employees(page=0):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute("SELECT id, name FROM employees ORDER BY name_key, id LIMIT 11 OFFSET ?", (page * 10,)).fetchall()


def get_employee_payments(employee_id):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute("SELECT t.created_at, t.currency, -t.amount, t.account, t.note FROM transactions t "
                            "JOIN employee_payments p ON p.transaction_id = t.id WHERE p.employee_id = ? "
                            "ORDER BY t.created_at, t.id", (employee_id,)).fetchall()


def add_employee_payment(employee_id, currency, amount, account="cash", note="", actor_id=None):
    if currency not in ("UZS", "USD") or account not in ("cash", "card") or (account == "card" and currency != "UZS"):
        raise ValueError("Noto'g'ri hisob")
    if not 0 < amount <= 9223372036854775807:
        raise ValueError("Summa musbat bo'lsin")
    if account == "card":
        amount = card_total(amount)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        require_funds(conn, currency, account, amount)
        cursor = conn.execute("INSERT INTO transactions(created_at, kind, currency, amount, note, actor_id, account) "
                              "VALUES (?, 'expense', ?, ?, ?, ?, ?)",
                              (now_text(), currency, -amount, note, actor_id, account))
        conn.execute("INSERT INTO employee_payments(transaction_id, employee_id) VALUES (?, ?)", (cursor.lastrowid, employee_id))
    return amount


def add_client(name):
    name = " ".join(name.split())
    if not name or len(name) > 80 or not any(char.isalnum() for char in name):
        raise ValueError("Mijoz nomi 1–80 belgidan iborat bo'lsin")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("INSERT INTO clients (name, name_key) VALUES (?, ?) ON CONFLICT(name_key) DO UPDATE SET archived = 0",
                     (name, name.casefold()))
        return conn.execute("SELECT id, name FROM clients WHERE name_key = ?", (name.casefold(),)).fetchone()


def get_client(client_id):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute("SELECT id, name FROM clients WHERE id = ? AND archived = 0", (client_id,)).fetchone()


def get_clients(page=0):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute("SELECT id, name FROM clients WHERE archived = 0 ORDER BY name_key, id LIMIT ? OFFSET ?",
                            (CLIENT_PAGE_SIZE + 1, page * CLIENT_PAGE_SIZE)).fetchall()



def archive_client(client_id):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("UPDATE clients SET archived = 1 WHERE id = ?", (client_id,))


def get_statement(client_id=None):
    condition = "client_id = ? AND kind IN ('income', 'expense')" if client_id is not None else "client_id IS NULL AND kind = 'expense'"
    params = (client_id,) if client_id is not None else ()
    if client_id is None:
        condition += " AND NOT EXISTS (SELECT 1 FROM employee_payments p WHERE p.transaction_id = transactions.id)"
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT created_at, kind, currency, amount, note, account FROM transactions "
            f"WHERE {condition} ORDER BY created_at, id", params
        ).fetchall()
    totals = {currency: {"income": 0, "expense": 0} for currency in ("UZS", "USD")}
    for _, kind, currency, amount, _, _ in rows:
        totals[currency][kind] += amount if kind == "income" else -amount
    return rows, totals


def now_text():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def add_transaction(kind, currency, amount, note="", actor_id=None, account="cash", client_id=None):
    if account not in ("cash", "card") or (account == "card" and currency != "UZS"):
        raise ValueError("Noto'g'ri hisob yoki valyuta")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON")
        if client_id is not None and kind not in ("income", "expense"):
            raise ValueError("Mijoz hisobiga faqat kirim yoki xarajat yoziladi")
        if amount < 0:
            conn.execute("BEGIN IMMEDIATE")
            require_funds(conn, currency, account, -amount)
        conn.execute(
            """
            INSERT INTO transactions
            (created_at, kind, currency, amount, note, actor_id, account, client_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_text(),
                kind,
                currency,
                amount,
                note,
                actor_id,
                account,
                client_id
            )
        )


def add_split_client_income(client_id, usd_cents, card_amount, actor_id=None):
    if client_id is None or not (0 < usd_cents <= 9223372036854775807 and 0 < card_amount <= 9223372036854775807):
        raise ValueError("Mijoz va ikkala musbat summa kerak")
    created_at = now_text()
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executemany(
            "INSERT INTO transactions (created_at, kind, currency, amount, note, actor_id, account, client_id) "
            "VALUES (?, 'income', ?, ?, ?, ?, ?, ?)",
            [
                (created_at, "USD", usd_cents, "Dollar olindi", actor_id, "cash", client_id),
                (created_at, "UZS", card_amount, "Kartaga pul olindi", actor_id, "card", client_id),
            ]
        )


class InsufficientFunds(Exception):
    def __init__(self, balance):
        self.balance = balance
        super().__init__("Balansda pul yetarli emas")


class InsufficientCardFunds(InsufficientFunds):
    pass


def require_funds(conn, currency, account, amount):
    balance = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE currency = ? AND account = ?",
        (currency, account)
    ).fetchone()[0]
    if amount > balance:
        error = InsufficientCardFunds if account == "card" else InsufficientFunds
        raise error(balance)


def card_total(amount):
    # So'm butun son: 1% komissiyani keyingi butun so'mga yaxlitlaymiz.
    return amount + (amount + 99) // 100


def add_card_expense(amount, note, actor_id=None, client_id=None):
    if amount <= 0:
        raise ValueError("Summa musbat bo'lishi kerak")
    amount = card_total(amount)
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        require_funds(conn, "UZS", "card", amount)
        conn.execute(
            "INSERT INTO transactions "
            "(created_at, kind, currency, amount, note, actor_id, account, client_id) "
            "VALUES (?, 'expense', 'UZS', ?, ?, ?, 'card', ?)",
            (now_text(), -amount, note, actor_id, client_id)
        )
    return amount


def add_exchange(usd_cents, uzs_amount, actor_id=None):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        require_funds(conn, "USD", "cash", usd_cents)
        conn.execute(
            """
            INSERT INTO transactions
            (created_at, kind, currency, amount, note, actor_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                now_text(),
                "exchange_out",
                "USD",
                -usd_cents,
                "Dollar maydalandi",
                actor_id
            )
        )

        conn.execute(
            """
            INSERT INTO transactions
            (created_at, kind, currency, amount, note, actor_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                now_text(),
                "exchange_in",
                "UZS",
                uzs_amount,
                "Dollar maydalashdan olindi",
                actor_id
            )
        )



def undo_rows(conn, transaction_id):
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
    if row is None:
        raise ValueError("Tranzaksiya topilmadi.")
    if row["kind"] == "exchange_in":
        transaction_id -= 1
        row = conn.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
    if row is None or row["kind"] not in ("income", "expense", "exchange_out"):
        raise ValueError("Tranzaksiyani qaytarib bo'lmaydi.")
    rows = [dict(row)]
    if row["kind"] == "exchange_out":
        pair = conn.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id + 1,)).fetchone()
        if (pair is None or pair["kind"] != "exchange_in" or pair["currency"] != "UZS"
                or row["currency"] != "USD" or pair["account"] != "cash" or row["account"] != "cash"
                or pair["actor_id"] != row["actor_id"]):
            raise ValueError("Dollar maydalash jufti topilmadi.")
        rows.append(dict(pair))
    for item in rows:
        employee = conn.execute("SELECT employee_id FROM employee_payments WHERE transaction_id = ?", (item["id"],)).fetchone()
        item["employee_id"] = employee[0] if employee else None
        client = conn.execute("SELECT name FROM clients WHERE id = ?", (item["client_id"],)).fetchone()
        employee = conn.execute("SELECT name FROM employees WHERE id = ?", (item["employee_id"],)).fetchone()
        item["owner"] = client[0] if client else employee[0] if employee else ""
    return rows


def get_undo_rows(transaction_id):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return undo_rows(conn, transaction_id)


def reverse_transaction(transaction_id, actor_id):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        rows = undo_rows(conn, transaction_id)
        reductions = {}
        for row in rows:
            key = (row["currency"], row["account"])
            reductions[key] = reductions.get(key, 0) + row["amount"]
        for (currency, account), amount in reductions.items():
            if amount > 0:
                require_funds(conn, currency, account, amount)
        conn.execute("INSERT INTO transaction_undo (undone_at, actor_id, original_rows) VALUES (?, ?, ?)",
                     (now_text(), actor_id, json.dumps(rows, ensure_ascii=False)))
        conn.executemany("DELETE FROM transactions WHERE id = ?", [(row["id"],) for row in rows])
        return rows


def undo_description(rows):
    lines = []
    for row in rows:
        kind = {"income": "Kirim", "expense": "Xarajat", "exchange_out": "Dollar maydalash",
                "exchange_in": "Olingan so'm"}[row["kind"]]
        account = "Karta" if row["account"] == "card" else "Naqd"
        lines.append(f"{kind}: {format_money(abs(row['amount']), row['currency'])} ({account})")
        if row["owner"]:
            lines.append(row["owner"])
        if row["note"]:
            lines.append(row["note"])
        lines.append(row["created_at"])
    return "\n".join(lines)


async def undo_start(update, context):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    context.chat_data.clear()
    return await show_undo_list(update, context)


async def show_undo_list(update, context, page=0):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT id, kind, currency, amount, note FROM transactions "
            "WHERE kind IN ('income', 'expense', 'exchange_out') ORDER BY id DESC LIMIT 11 OFFSET ?",
            (page * 10,)
        ).fetchall()
    if not rows and page:
        return await show_undo_list(update, context)
    choices = {}
    for tid, kind, currency, amount, note in rows[:10]:
        sign = "+" if amount > 0 else "−"
        choices[f"#{tid} {sign}{format_money(abs(amount), currency)} · {(note or kind)[:40]}"] = tid
    context.chat_data.clear()
    context.chat_data.update(undo_choices=choices, undo_page=page)
    keyboard = [[label] for label in choices]
    navigation = ([UNDO_PREV] if page else []) + ([UNDO_NEXT] if len(rows) > 10 else [])
    if navigation:
        keyboard.append(navigation)
    keyboard.append([BACK_BUTTON])
    await update.message.reply_text("Tranzaksiyani tanlang:" if rows else "Tranzaksiya yo'q.",
                                   reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return UNDO_LIST


async def undo_select(update, context):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    text = update.message.text
    if text in (UNDO_PREV, UNDO_NEXT):
        return await show_undo_list(update, context, max(0, context.chat_data.get("undo_page", 0) + (1 if text == UNDO_NEXT else -1)))
    tid = context.chat_data.get("undo_choices", {}).get(text)
    if tid is None:
        await update.message.reply_text("Tranzaksiyani ro'yxatdan tanlang.")
        return UNDO_LIST
    try:
        rows = get_undo_rows(tid)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return await show_undo_list(update, context)
    context.chat_data["undo_id"] = tid
    await reply_report(update, undo_description(rows), "Tranzaksiya qaytarilsinmi?",
                       ReplyKeyboardMarkup([[UNDO_CONFIRM_BUTTON], ["⬅️ Bekor qilish"]], resize_keyboard=True))
    return UNDO_CONFIRM


async def undo_confirm(update, context):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    if update.message.text != UNDO_CONFIRM_BUTTON:
        await update.message.reply_text("Tasdiqlang yoki bekor qiling.")
        return UNDO_CONFIRM
    try:
        reverse_transaction(context.chat_data.get("undo_id"), update.effective_user.id)
    except InsufficientFunds:
        await update.message.reply_text("❌ Balansda pul yetarli emas.")
        return UNDO_CONFIRM
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return await show_undo_list(update, context)
    except (sqlite3.Error, OSError):
        await update.message.reply_text("❌ Qaytarilmadi. Qayta urinib ko'ring.")
        return UNDO_CONFIRM
    await update.message.reply_text("✅ Tranzaksiya qaytarildi.")
    return await show_undo_list(update, context)


def get_balance(currency, account="cash"):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0)
            FROM transactions
            WHERE currency = ? AND account = ?
            """,
            (currency, account)
        ).fetchone()

        return row[0]


def get_history(limit=10):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute(
            """
            SELECT t.created_at, t.kind, t.currency, t.amount,
                   CASE WHEN e.id IS NOT NULL THEN 'Xodim: ' || e.name || char(10) || COALESCE(t.note, '')
                        WHEN c.id IS NULL THEN t.note
                        ELSE 'Mijoz: ' || c.name || char(10) || COALESCE(t.note, '') END,
                   t.account
            FROM transactions t LEFT JOIN clients c ON c.id = t.client_id
            LEFT JOIN employee_payments p ON p.transaction_id = t.id
            LEFT JOIN employees e ON e.id = p.employee_id
            ORDER BY t.id DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()


def get_statistics(period="all", now=None):
    now = (now or datetime.now(TZ)).astimezone(TZ)
    conditions = "kind = 'expense'"
    params = []
    if period in ("today", "month"):
        begin = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if period == "today":
            end = begin + timedelta(days=1)
        else:
            begin = begin.replace(day=1)
            end = (begin + timedelta(days=32)).replace(day=1)
        conditions += " AND created_at >= ? AND created_at < ?"
        params = [begin.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")]
    elif period != "all":
        raise ValueError("Noto'g'ri davr")

    totals = {"UZS": 0, "USD": 0}
    balances = {
        ("cash", "UZS"): 0,
        ("cash", "USD"): 0,
        ("card", "UZS"): 0,
    }
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        conn.execute("BEGIN")
        expenses = conn.execute(
            "SELECT t.created_at, CASE WHEN e.id IS NOT NULL THEN 'Xodim: ' || e.name || char(10) || COALESCE(t.note, '') "
            "WHEN c.id IS NULL THEN t.note "
            "ELSE 'Mijoz: ' || c.name || char(10) || COALESCE(t.note, '') END, "
            "t.currency, -t.amount, t.account FROM transactions t LEFT JOIN clients c ON c.id = t.client_id "
            "LEFT JOIN employee_payments p ON p.transaction_id = t.id LEFT JOIN employees e ON e.id = p.employee_id "
            f"WHERE {conditions} ORDER BY t.created_at ASC, t.id ASC", params
        ).fetchall()
        for _, _, currency, amount, _ in expenses:
            totals[currency] += amount
        for account, currency, amount in conn.execute(
            "SELECT account, currency, SUM(amount) FROM transactions GROUP BY account, currency"
        ):
            balances[(account, currency)] = amount
    return expenses, totals, balances


# =========================================================
# BAZANI NOLGA TUSHIRISH
# =========================================================

def reset_database():
    backup_dir = DB_PATH.parent / "backups"
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    backup_path = backup_dir / f"kassa-{datetime.now(TZ):%Y%m%d-%H%M%S-%f}.db"
    backup_path.touch(mode=0o600, exist_ok=False)

    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        # Zaxira olish va tozalash davomida boshqa yozuvlarni bloklaymiz.
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        with closing(sqlite3.connect(DB_PATH)) as source:
            with closing(sqlite3.connect(backup_path)) as backup:
                source.backup(backup)
        conn.execute("DELETE FROM transactions")

    return backup_path


# =========================================================
# FORMATLASH
# =========================================================

def format_uzs(amount):
    return f"{amount:,}".replace(",", " ")


def format_usd(cents):
    value = Decimal(cents) / Decimal(100)

    if value == value.to_integral():
        return f"${int(value):,}"

    return f"${value:,.2f}"


def parse_uzs(text):
    cleaned = (
        text.lower()
        .replace("so'm", "")
        .replace("soʻm", "")
        .replace("som", "")
        .replace("uzs", "")
        .replace(" ", "")
        .replace(",", "")
        .replace(".", "")
        .replace("_", "")
        .replace("'", "")
    )

    value = int(cleaned)

    if value <= 0 or value > 9223372036854775807:
        raise ValueError

    return value


def parse_usd(text):
    cleaned = (
        text.lower()
        .replace("usd", "")
        .replace("$", "")
        .replace(" ", "")
        .replace(",", ".")
    )

    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", cleaned):
        raise ValueError

    value = Decimal(cleaned)
    if value <= 0 or value > Decimal("92233720368547758.07"):
        raise ValueError

    return int(value * 100)


def parse_income_text(text, currency):
    text = " ".join(text.split())
    parse_amount = parse_usd if currency == "USD" else parse_uzs
    amount_pattern = r"\$?\s*[+-]?[0-9][0-9.,_' ]*(?:\s*(?:\$|usd|uzs|so'm|soʻm|som))?"
    if re.fullmatch(amount_pattern, text, flags=re.IGNORECASE):
        return "", parse_amount(text)

    match = re.fullmatch(rf"(.+?)\s+({amount_pattern})", text, flags=re.IGNORECASE)
    if match is None:
        raise ValueError
    name, amount_text = match.groups()
    if len(name) > 200 or not any(char.isalpha() for char in name):
        raise ValueError
    return name, parse_amount(amount_text)


# =========================================================
# HUQUQ TEKSHIRISH
# =========================================================

def is_cashier(update: Update):
    return (
        update.effective_user
        and update.effective_user.id == CASHIER_ID
    )


async def reject_if_not_cashier(update: Update):
    if not is_cashier(update):
        await update.message.reply_text(
            "⛔ Bu bot faqat kassir uchun."
        )
        return True

    return False


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Boshqa odam ham /start bosishi mumkin,
    # shunda bot unga keyinchalik xabar yubora oladi.

    if is_boss(update) and not is_cashier(update):
        await update.message.reply_text("Kerakli bo‘limni tanlang.", reply_markup=BOSS_KEYBOARD)
        return ConversationHandler.END
    if not is_cashier(update):
        await update.message.reply_text(
            f"Telegram ID: {update.effective_user.id}"
        )
        return ConversationHandler.END

    context.chat_data.clear()

    await update.message.reply_text(
        "💼 Kassa bot\n\n"
        "Kerakli amalni tanlang.",
        reply_markup=MAIN_KEYBOARD
    )
    return ConversationHandler.END


async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Sizning Telegram ID'ingiz:\n"
        f"{update.effective_user.id}"
    )


# =========================================================
# XODIMLAR
# =========================================================

def is_boss(update):
    return bool(REPORT_CHAT_ID and update.effective_user and update.effective_user.id == REPORT_CHAT_ID)


async def employee_access(update):
    if is_cashier(update) or is_boss(update):
        return True
    await update.message.reply_text("⛔ Xodimlar hisobi faqat kassir va boshliq uchun.")
    return False


async def report_access(update):
    if is_cashier(update) or is_boss(update):
        return True
    await update.message.reply_text("⛔ Hisobotlar faqat kassir va boshliq uchun.")
    return False


def client_view_session(update, context):
    if is_cashier(update):
        return context.chat_data
    return context.user_data.setdefault("client_views", {}).setdefault(update.effective_chat.id, {})


def employee_session(update, context):
    # Boshliq va kassir bir guruhda ham bir-birining tanlovini almashtirmaydi.
    return context.user_data.setdefault("employee_views", {}).setdefault(update.effective_chat.id, {})


def employee_keyboard(update):
    rows = [[EMPLOYEE_PAY_BUTTON]] if is_cashier(update) else []
    return ReplyKeyboardMarkup(rows + [[EMPLOYEE_REPORT_BUTTON], [EMPLOYEES_BUTTON, BACK_BUTTON]], resize_keyboard=True)


async def employees_start(update, context):
    if not await employee_access(update):
        return ConversationHandler.END
    if is_cashier(update):
        context.chat_data.clear()
    return await show_employees(update, context)


async def show_employees(update, context, page=0):
    rows = get_employees(page)
    if not rows and page:
        page, rows = 0, get_employees()
    choices = {name: eid for eid, name in rows[:10]}
    session = employee_session(update, context)
    session.clear()
    session.update(page=page, choices=choices)
    keyboard = [[label] for label in choices]
    navigation = ([EMPLOYEE_PREV] if page else []) + ([EMPLOYEE_NEXT] if len(rows) > 10 else [])
    if navigation:
        keyboard.append(navigation)
    if is_cashier(update):
        keyboard.append([ADD_EMPLOYEE_BUTTON])
    keyboard.append([BACK_BUTTON])
    await update.message.reply_text("Xodimni tanlang:" if rows else "Hozircha xodim yo'q.",
                                    reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return EMPLOYEE_LIST


async def employee_select(update, context):
    if not await employee_access(update):
        return ConversationHandler.END
    text = update.message.text
    session = employee_session(update, context)
    if text == ADD_EMPLOYEE_BUTTON:
        if await reject_if_not_cashier(update):
            return EMPLOYEE_LIST
        await update.message.reply_text("Xodimning ismini yozing:", reply_markup=CANCEL_KEYBOARD)
        return EMPLOYEE_NAME
    if text in (EMPLOYEE_PREV, EMPLOYEE_NEXT):
        return await show_employees(update, context, max(0, session.get("page", 0) + (1 if text == EMPLOYEE_NEXT else -1)))
    employee = get_employee(session.get("choices", {}).get(text))
    if employee is None:
        await update.message.reply_text("Xodimni ro'yxatdagi tugmadan tanlang.")
        return EMPLOYEE_LIST
    session.clear()
    session["employee_id"] = employee[0]
    return await show_employee(update, context, employee)


async def employee_create(update, context):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    try:
        employee = add_employee(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ Xodim ismini 1–80 belgi bilan yozing.", reply_markup=CANCEL_KEYBOARD)
        return EMPLOYEE_NAME
    except (sqlite3.Error, OSError):
        await update.message.reply_text("❌ Xodim saqlanmadi. Qayta urinib ko'ring.", reply_markup=CANCEL_KEYBOARD)
        return EMPLOYEE_NAME
    session = employee_session(update, context)
    session.clear()
    session["employee_id"] = employee[0]
    return await show_employee(update, context, employee)


async def show_employee(update, context, employee):
    rows = get_employee_payments(employee[0])
    totals = {("cash", "UZS"): 0, ("cash", "USD"): 0, ("card", "UZS"): 0}
    lines = [f"👷 XODIM: {employee[1]}", ""]
    for index, (created_at, currency, amount, account, note) in enumerate(rows, 1):
        totals[(account, currency)] += amount
        source = "karta" if account == "card" else "naqd"
        detail = f" — {note}" if note else ""
        lines.append(f"{index}. {format_money(amount, currency)} ({source}){detail}\n{created_at[:16]}")
    if not rows:
        lines.append("Hozircha pul berilmagan.")
    summary = (
        "JAMI BERILGAN PUL\n"
        f"Naqd so'm: {format_money(totals[('cash', 'UZS')], 'UZS')}\n"
        f"Kartadan: {format_money(totals[('card', 'UZS')], 'UZS')}\n"
        f"Jami so'm: {format_money(totals[('cash', 'UZS')] + totals[('card', 'UZS')], 'UZS')}\n"
        f"Dollar: {format_usd(totals[('cash', 'USD')])}"
    )
    await reply_report(update, "\n".join(lines), summary, employee_keyboard(update))
    return EMPLOYEE_MENU


async def employee_menu(update, context):
    if not await employee_access(update):
        return ConversationHandler.END
    session = employee_session(update, context)
    employee = get_employee(session.get("employee_id"))
    if employee is None:
        return await employees_start(update, context)
    if update.message.text == EMPLOYEE_REPORT_BUTTON:
        return await show_employee(update, context, employee)
    if await reject_if_not_cashier(update):
        return EMPLOYEE_MENU
    if update.message.text == EMPLOYEE_PAY_BUTTON:
        await update.message.reply_text(f"{employee[1]} xodimga qaysi hisobdan pul berdingiz?", reply_markup=CURRENCY_KEYBOARD)
        return EMPLOYEE_CURRENCY
    if update.message.text.startswith(("👤 #", "👷 #")):
        return await employees_start(update, context)
    session["currency"] = "USD" if update.message.text.rstrip().endswith("$") else "UZS"
    session["account"] = "cash"
    return await employee_amount(update, context, retry_state=EMPLOYEE_MENU)


async def employee_currency(update, context):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    choices = {"🇺🇿 So'm": ("UZS", "cash"), "🇺🇸 Dollar": ("USD", "cash"), CARD_BUTTON: ("UZS", "card")}
    choice = choices.get(update.message.text)
    if choice is None:
        await update.message.reply_text("So'm, dollar yoki kartani tugmadan tanlang.", reply_markup=CURRENCY_KEYBOARD)
        return EMPLOYEE_CURRENCY
    session = employee_session(update, context)
    session["currency"], session["account"] = choice
    unit = "dollar" if choice[0] == "USD" else "so'm"
    await update.message.reply_text(f"Necha {unit} berdingiz?", reply_markup=CANCEL_KEYBOARD)
    return EMPLOYEE_AMOUNT


async def employee_amount(update, context, retry_state=EMPLOYEE_AMOUNT):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    session = employee_session(update, context)
    employee = get_employee(session.get("employee_id"))
    if employee is None:
        return await employees_start(update, context)
    currency, account = session.get("currency"), session.get("account")
    if currency not in ("UZS", "USD") or account not in ("cash", "card"):
        return await show_employee(update, context, employee)
    try:
        note, amount = parse_income_text(update.message.text, currency)
    except (ValueError, InvalidOperation):
        await update.message.reply_text("❌ Summani to'g'ri yozing.", reply_markup=CANCEL_KEYBOARD)
        return retry_state
    try:
        amount = add_employee_payment(employee[0], currency, amount, account, note, update.effective_user.id)
    except InsufficientFunds:
        await update.message.reply_text("❌ Balansda pul yetarli emas.", reply_markup=CANCEL_KEYBOARD)
        return retry_state
    except (sqlite3.Error, OSError):
        await update.message.reply_text("❌ To'lov saqlanmadi. Qayta urinib ko'ring.", reply_markup=CANCEL_KEYBOARD)
        return retry_state
    session.clear()
    session["employee_id"] = employee[0]
    await update.message.reply_text(f"{employee[1]}ga {format_money(amount, currency)} berildi.", reply_markup=employee_keyboard(update))
    await send_transaction_report(update, context, "expense", currency, amount, account=account, note=note,
                                  employee_name=employee[1], reply_markup=employee_keyboard(update))
    return EMPLOYEE_MENU


async def employee_cancel(update, context):
    if not await employee_access(update):
        return ConversationHandler.END
    session = employee_session(update, context)
    employee = get_employee(session.get("employee_id"))
    session.clear()
    if employee:
        session["employee_id"] = employee[0]
        return await show_employee(update, context, employee)
    return await employees_start(update, context)


# =========================================================
# MIJOZLAR VA BOSHQA XARAJATLAR
# =========================================================

def active_client(context):
    if context.chat_data.get("expense_scope") == "client":
        return get_client(context.chat_data.get("client_id"))
    return None


def scope_keyboard(context):
    scope = context.chat_data.get("expense_scope")
    return CLIENT_KEYBOARD if scope == "client" else OTHER_KEYBOARD if scope == "other" else MAIN_KEYBOARD


def format_money(amount, currency):
    return format_usd(amount) if currency == "USD" else f"{format_uzs(amount)} so'm"


def client_totals_text(totals):
    lines = []
    for currency, label in (("UZS", "SO'M (naqd va karta)"), ("USD", "DOLLAR")):
        income = totals[currency]["income"]
        expense = totals[currency]["expense"]
        lines.append(
            f"{label}\nOlingan: {format_money(income, currency)}\n"
            f"Ishlatilgan: {format_money(expense, currency)}"
        )
    return "\n\n".join(lines)


async def clients_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await report_access(update):
        return ConversationHandler.END
    return await show_clients(update, context)


async def show_clients(update, context, page=0):
    rows = get_clients(page)
    if not rows and page:
        page = 0
        rows = get_clients(page)
    choices = {name: client_id for client_id, name in rows[:CLIENT_PAGE_SIZE]}
    session = client_view_session(update, context)
    session.clear()
    session.update(client_page=page, client_choices=choices)
    keyboard = [[label] for label in choices]
    navigation = []
    if page:
        navigation.append(PREV_CLIENTS_BUTTON)
    if len(rows) > CLIENT_PAGE_SIZE:
        navigation.append(NEXT_CLIENTS_BUTTON)
    if navigation:
        keyboard.append(navigation)
    if is_cashier(update):
        keyboard.append([ADD_CLIENT_BUTTON])
    keyboard.append([BACK_BUTTON])
    text = "👥 Mijozni tanlang:" if rows else "Hozircha mijoz yo'q."
    await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    return CLIENT_LIST


async def clients_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await report_access(update):
        return ConversationHandler.END
    text = update.message.text
    if text == ADD_CLIENT_BUTTON:
        if await reject_if_not_cashier(update):
            return CLIENT_LIST
        await update.message.reply_text("Mijozning ismini yozing:", reply_markup=CANCEL_KEYBOARD)
        return CLIENT_NAME
    page = client_view_session(update, context).get("client_page", 0)
    if text in (PREV_CLIENTS_BUTTON, NEXT_CLIENTS_BUTTON):
        return await show_clients(update, context, max(0, page + (1 if text == NEXT_CLIENTS_BUTTON else -1)))
    client_id = client_view_session(update, context).get("client_choices", {}).get(text)
    client = get_client(client_id) if client_id is not None else None
    if client is None:
        await update.message.reply_text("Mijozni ro'yxatdagi tugmadan tanlang.")
        return CLIENT_LIST
    return await show_client(update, context, client)


async def client_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    try:
        client = add_client(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ Mijozning ismini 1–80 belgi bilan yozing.", reply_markup=CANCEL_KEYBOARD)
        return CLIENT_NAME
    except (sqlite3.Error, OSError):
        await update.message.reply_text("❌ Mijoz saqlanmadi. Qayta urinib ko'ring.", reply_markup=CANCEL_KEYBOARD)
        return CLIENT_NAME
    return await client_income_prompt(update, context, client)


async def client_income_prompt(update, context, client):
    context.chat_data.clear()
    context.chat_data.update(expense_scope="client", client_id=client[0])
    await update.message.reply_text(
        f"👤 Mijoz: {client[1]}\n\nPulni qaysi hisobga oldingiz?",
        reply_markup=CLIENT_CURRENCY_KEYBOARD
    )
    return CHOOSE_CURRENCY


async def show_client(update, context, client):
    session = client_view_session(update, context)
    session.clear()
    session.update(expense_scope="client", client_id=client[0])
    _, totals = get_statement(client[0])
    await update.message.reply_text(
        f"👤 MIJOZ: {client[1]}\n\n{client_totals_text(totals)}",
        reply_markup=CLIENT_KEYBOARD if is_cashier(update) else BOSS_CLIENT_KEYBOARD
    )
    return CLIENT_MENU


async def client_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await report_access(update):
        return ConversationHandler.END
    session = client_view_session(update, context)
    client = active_client(context) if is_cashier(update) else get_client(session.get("client_id"))
    if client is None:
        return await clients_start(update, context)
    text = update.message.text
    if not is_cashier(update):
        if text == CLIENT_REPORT_BUTTON:
            return await show_statement(update, context, client)
        await reject_if_not_cashier(update)
        return CLIENT_MENU
    if text == DELETE_CLIENT_BUTTON:
        await update.message.reply_text(
            f"{client[1]} ro'yxatdan o'chirilsinmi?\nKirim-xarajatlar va balans saqlanadi.",
            reply_markup=ReplyKeyboardMarkup(
                [[DELETE_CLIENT_CONFIRM], ["⬅️ Bekor qilish"]], resize_keyboard=True
            )
        )
        return CLIENT_DELETE_CONFIRM
    if text == CLIENT_INCOME_BUTTON:
        return await client_income_prompt(update, context, client)
    if text == CLIENT_REPORT_BUTTON:
        return await show_statement(update, context, client)
    if text in (CLIENT_CASH_BUTTON, CLIENT_CARD_BUTTON):
        return await scoped_expense_prompt(update, context, text == CLIENT_CARD_BUTTON)
    return await record_expense(update, context, account="cash")


async def client_expense_account(update, context):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    client = active_client(context)
    if client is None:
        return await clients_start(update, context)
    pending = context.chat_data.get("pending_client_expense")
    if not pending or pending[0] != client[0]:
        return await show_client(update, context, client)
    choices = {"💵 Naqd so'm": ("UZS", "cash"), CARD_BUTTON: ("UZS", "card"),
               "🇺🇸 Dollar": ("USD", "cash")}
    choice = choices.get(update.message.text)
    if choice is None:
        await update.message.reply_text("Hisobni tanlang.", reply_markup=CLIENT_EXPENSE_KEYBOARD)
        return CLIENT_EXPENSE_ACCOUNT
    currency, account = choice
    try:
        if currency == "UZS" and re.fullmatch(r"[0-9]+[.,][0-9]{1,2}", pending[2]):
            raise ValueError
        amount = parse_usd(pending[2]) if currency == "USD" else parse_uzs(pending[2])
    except (ValueError, InvalidOperation):
        await update.message.reply_text("❌ Summa bu hisobga mos emas.", reply_markup=CLIENT_EXPENSE_KEYBOARD)
        return CLIENT_EXPENSE_ACCOUNT
    return await record_expense(update, context, account, (pending[1], amount, currency))


async def client_delete_confirm(update, context):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    client = active_client(context)
    if client is None:
        return await clients_start(update, context)
    if update.message.text != DELETE_CLIENT_CONFIRM:
        await update.message.reply_text("Tasdiqlang yoki bekor qiling.")
        return CLIENT_DELETE_CONFIRM
    try:
        archive_client(client[0])
    except (sqlite3.Error, OSError):
        await update.message.reply_text("❌ Mijoz o'chirilmadi. Qayta urinib ko'ring.")
        return CLIENT_DELETE_CONFIRM
    await update.message.reply_text(f"{client[1]} ro'yxatdan o'chirildi.")
    return await clients_start(update, context)


async def other_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    context.chat_data.clear()
    context.chat_data["expense_scope"] = "other"
    await update.message.reply_text(
        "🧾 BOSHQA XARAJATLAR\n\nXarajat nomi va summani yozing.",
        reply_markup=OTHER_KEYBOARD
    )
    return OTHER_MENU


async def other_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    text = update.message.text
    if text == OTHER_REPORT_BUTTON:
        return await show_statement(update, context)
    if text == OTHER_USD_BUTTON:
        await update.message.reply_text("Dollar xarajati nomi va summani yozing.", reply_markup=CANCEL_KEYBOARD)
        return OTHER_USD
    if text in (OTHER_CASH_BUTTON, OTHER_CARD_BUTTON):
        return await scoped_expense_prompt(update, context, text == OTHER_CARD_BUTTON)
    return await record_expense(update, context, account="cash")


async def other_usd_expense(update, context):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    text = update.message.text.strip()
    try:
        name, amount, currency = parse_expense_text(text if text.endswith("$") else text + "$")
    except (ValueError, InvalidOperation):
        await update.message.reply_text("❌ Xarajat nomi va summani to'g'ri yozing.")
        return OTHER_USD
    return await record_expense(update, context, "cash", (name, amount, currency), selected_retry=OTHER_USD)



async def scoped_expense_prompt(update, context, card=False):
    client = active_client(context)
    title = f"👤 Mijoz: {client[1]}" if client else "🧾 Boshqa xarajatlar"
    source = "kartadan" if card else "naqd"
    prompt = "Xarajat nomi va summani yozing." if client else f"{source.capitalize()} xarajat: nima uchun va qancha ishlatdingiz?"
    await update.message.reply_text(
        f"{title}\n\n{prompt}", reply_markup=CANCEL_KEYBOARD if card else scope_keyboard(context)
    )
    return CARD_EXPENSE if card else CLIENT_MENU if client else OTHER_MENU


async def show_statement(update, context, client=None):
    rows, totals = get_statement(client[0] if client else None)
    title = f"👤 MIJOZ HISOBI — {client[1]}" if client else "🧾 BOSHQA XARAJATLAR"
    lines = [title, ""]
    for index, (created_at, kind, currency, amount, note, account) in enumerate(rows, 1):
        sign = "+" if kind == "income" else "−"
        source = "karta" if account == "card" else "naqd"
        lines.append(f"{index}. {note or 'Nomsiz'} — {sign}{format_money(abs(amount), currency)} ({source})\n{created_at[:16]}")
    if not rows:
        lines.append("Hozircha yozuv yo'q.")
    summary = client_totals_text(totals) if client else (
        "JAMI XARAJAT\n"
        f"So'm: {format_money(totals['UZS']['expense'], 'UZS')}\n"
        f"Dollar: {format_money(totals['USD']['expense'], 'USD')}"
    )
    await reply_report(update, "\n".join(lines), summary, scope_keyboard(context) if is_cashier(update) else BOSS_CLIENT_KEYBOARD)
    return CLIENT_MENU if client else OTHER_MENU


# =========================================================
# KIRIM VA XARAJAT XABARLARI
# =========================================================

async def send_transaction_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    kind,
    currency,
    amount,
    account="cash",
    note="",
    client_name=None,
    reply_markup=None,
    employee_name=None,
):
    if kind not in ("income", "expense"):
        return

    title = "🟢 YANGI KIRIM" if kind == "income" else "🔴 YANGI XARAJAT"
    sign = "➕" if kind == "income" else "➖"
    account_label = "💳 Karta" if account == "card" else "💵 Naqd dollar" if currency == "USD" else "💰 Naqd so'm"
    amount_text = format_usd(amount) if currency == "USD" else f"{format_uzs(amount)} so'm"
    lines = [title, "", f"Hisob: {account_label}"]
    if client_name is not None:
        lines.append(f"👤 Mijoz: {client_name}")
    if note:
        lines.append(f"📝 {note}")
    lines.extend([f"{sign} {amount_text}", f"🕐 {now_text()}"])
    text = f"{employee_name}ga {amount_text} berildi." if employee_name is not None else "\n".join(lines)

    try:
        await context.bot.send_message(chat_id=REPORT_CHAT_ID, text=text)
    except TelegramError as exc:
        operation = "Kirim" if kind == "income" else "Xarajat"
        await update.message.reply_text(
            f"⚠️ {operation} saqlandi, lekin hisobot boshqa odamga yuborilmadi.",
            reply_markup=reply_markup or MAIN_KEYBOARD
        )
        print("Hisobotni yuborishda xato:", type(exc).__name__)


# =========================================================
# PUL OLDIM
# =========================================================

async def income_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END

    context.chat_data.clear()
    await update.message.reply_text(
        "Pulni qaysi hisobga oldingiz?",
        reply_markup=CURRENCY_KEYBOARD
    )

    return CHOOSE_CURRENCY


async def choose_currency(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    text = update.message.text
    client = active_client(context)
    if context.chat_data.get("expense_scope") == "client" and client is None:
        return await clients_start(update, context)
    if text == CLIENT_SPLIT_BUTTON:
        if client is None:
            return await currency_invalid(update, context)
        await update.message.reply_text(
            f"👤 Mijoz: {client[1]}\n\nAvval necha dollar oldingiz?",
            reply_markup=CANCEL_KEYBOARD
        )
        return CLIENT_SPLIT_USD
    if client is not None:
        choices = {"🇺🇿 So'm": ("UZS", "cash"), "🇺🇸 Dollar": ("USD", "cash"), CARD_BUTTON: ("UZS", "card")}
        currency, account = choices[text]
        context.chat_data["income_currency"] = currency
        context.chat_data["income_account"] = account
        unit = "dollar" if currency == "USD" else "so'm"
        question = "Kartaga necha so'm oldingiz?" if account == "card" else f"Necha {unit} oldingiz?"
        await update.message.reply_text(
            f"👤 Mijoz: {client[1]}\n\n{question}",
            reply_markup=CANCEL_KEYBOARD
        )
        return INCOME_AMOUNT

    if text == "🇺🇿 So'm":
        context.chat_data["income_currency"] = "UZS"
        context.chat_data["income_account"] = "cash"

        await update.message.reply_text(
            "Kimdan oldingiz?",
            reply_markup=CANCEL_KEYBOARD
        )

        return INCOME_AMOUNT

    elif text == "🇺🇸 Dollar":
        context.chat_data["income_currency"] = "USD"
        context.chat_data["income_account"] = "cash"

        await update.message.reply_text(
            "Kimdan oldingiz?",
            reply_markup=CANCEL_KEYBOARD
        )

        return INCOME_AMOUNT

    elif text == CARD_BUTTON:
        context.chat_data["income_currency"] = "UZS"
        context.chat_data["income_account"] = "card"
        await update.message.reply_text(
            "Kimdan oldingiz?",
            reply_markup=CANCEL_KEYBOARD
        )
        return INCOME_AMOUNT


async def income_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    currency = context.chat_data.get("income_currency")
    account = context.chat_data.get("income_account", "cash")
    client = active_client(context)
    if context.chat_data.get("expense_scope") == "client" and client is None:
        return await clients_start(update, context)
    keyboard = CLIENT_KEYBOARD if client else MAIN_KEYBOARD
    source = context.chat_data.get("income_source")
    text = " ".join(update.message.text.split())
    if not client and source is None and text.casefold().split()[-1:] not in (["nan"], ["infinity"]) and 0 < len(text) <= 200 and any(c.isalpha() for c in text) and all(
        c.isalpha() or c in " '-’ʻ‘." for c in text
    ):
        context.chat_data["income_source"] = text
        unit = "dollar" if currency == "USD" else "so'm"
        await update.message.reply_text(f"Necha {unit} oldingiz?", reply_markup=CANCEL_KEYBOARD)
        return INCOME_AMOUNT
    try:
        if source is not None:
            name = source
            amount = parse_usd(text) if currency == "USD" else parse_uzs(text)
        else:
            name, amount = parse_income_text(text, currency)
    except (ValueError, InvalidOperation):
        guidance = "Kimdan olganingizni va summani to'g'ri yozing."
        if source is not None or account == "card" or client:
            guidance = "Summani to'g'ri kiriting."
        await update.message.reply_text(
            f"❌ {guidance}", reply_markup=CANCEL_KEYBOARD
        )
        return INCOME_AMOUNT

    source_note = f"Kimdan: {name}" if name else ""
    default_note = "Kartaga pul olindi" if account == "card" else "Dollar olindi" if currency == "USD" else "Pul olindi"
    try:
        add_transaction("income", currency, amount, source_note or default_note,
                        update.effective_user.id, account=account, client_id=client[0] if client else None)
    except (sqlite3.Error, OSError) as exc:
        print("Kirimni saqlashda xato:", type(exc).__name__)
        await update.message.reply_text("❌ Kirim saqlanmadi. Qayta urinib ko'ring.", reply_markup=CANCEL_KEYBOARD)
        return INCOME_AMOUNT

    balance = get_balance(currency, account)
    label = "💳 Karta qoldiq" if account == "card" else "💵 Dollar qoldiq" if currency == "USD" else "💰 Naqd so'm qoldiq"
    if client:
        label = "Umumiy kassa — " + label
    title = "✅ Dollar qabul qilindi" if currency == "USD" else "✅ Pul qabul qilindi"
    lines = [title, ""]
    if client:
        lines.append(f"👤 Mijoz: {client[1]}")
    if source_note:
        lines.append(f"👤 {source_note}")
    lines.extend([f"➕ {format_money(amount, currency)}", f"{label}: {format_money(balance, currency)}"])
    if client:
        context.chat_data.pop("income_currency", None)
        context.chat_data.pop("income_account", None)
    else:
        context.chat_data.clear()
    await update.message.reply_text("\n".join(lines), reply_markup=keyboard)
    await send_transaction_report(
        update, context, "income", currency, amount, account=account, note=source_note,
        client_name=client[1] if client else None, reply_markup=keyboard
    )
    return CLIENT_MENU if client else ConversationHandler.END


async def currency_invalid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    client = active_client(context)
    choices = "so'm, dollar, karta yoki dollar + karta" if client else "so'm, dollar yoki karta"
    await update.message.reply_text(f"Hisobni tugmadan tanlang: {choices}.",
                                    reply_markup=CLIENT_CURRENCY_KEYBOARD if client else CURRENCY_KEYBOARD)
    return CHOOSE_CURRENCY


async def client_split_usd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    client = active_client(context)
    if client is None:
        return await clients_start(update, context)
    try:
        usd_cents = parse_usd(update.message.text)
    except (ValueError, InvalidOperation):
        await update.message.reply_text("❌ Dollar miqdorini to'g'ri kiriting.",
                                        reply_markup=CANCEL_KEYBOARD)
        return CLIENT_SPLIT_USD
    context.chat_data["split_usd_cents"] = usd_cents
    await update.message.reply_text(
        f"👤 Mijoz: {client[1]}\nDollar: {format_usd(usd_cents)}\n\n"
        "Endi kartaga necha so'm oldingiz?",
        reply_markup=CANCEL_KEYBOARD
    )
    return CLIENT_SPLIT_CARD


async def client_split_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    client = active_client(context)
    if client is None:
        return await clients_start(update, context)
    usd_cents = context.chat_data.get("split_usd_cents")
    if usd_cents is None:
        return await client_income_prompt(update, context, client)
    try:
        card_amount = parse_uzs(update.message.text)
    except (ValueError, InvalidOperation):
        await update.message.reply_text("❌ Kartaga tushgan so'mni to'g'ri kiriting.",
                                        reply_markup=CANCEL_KEYBOARD)
        return CLIENT_SPLIT_CARD
    try:
        add_split_client_income(client[0], usd_cents, card_amount, update.effective_user.id)
    except (sqlite3.Error, OSError) as exc:
        print("Dollar va karta kirimini saqlashda xato:", type(exc).__name__)
        await update.message.reply_text("❌ Kirimlar saqlanmadi. Karta summasini qayta yuboring yoki bekor qiling.",
                                        reply_markup=CANCEL_KEYBOARD)
        return CLIENT_SPLIT_CARD
    context.chat_data.clear()
    context.chat_data.update(expense_scope="client", client_id=client[0])
    _, totals = get_statement(client[0])
    await update.message.reply_text(
        f"✅ Kirimlar qabul qilindi\n👤 Mijoz: {client[1]}\n\n"
        f"Dollar: +{format_usd(usd_cents)}\nKarta: +{format_uzs(card_amount)} so'm\n\n"
        f"{client_totals_text(totals)}",
        reply_markup=CLIENT_KEYBOARD
    )
    await send_transaction_report(update, context, "income", "USD", usd_cents,
                                  client_name=client[1], reply_markup=CLIENT_KEYBOARD)
    await send_transaction_report(update, context, "income", "UZS", card_amount, account="card",
                                  client_name=client[1], reply_markup=CLIENT_KEYBOARD)
    return CLIENT_MENU


# =========================================================
# DOLLAR MAYDALASH
# =========================================================

async def exchange_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END

    context.chat_data.clear()
    usd_balance = get_balance("USD")

    await update.message.reply_text(
        "💵 Necha dollar maydalayapsiz?\n\n"
        f"Hozirgi dollar qoldiq: "
        f"{format_usd(usd_balance)}",
        reply_markup=CANCEL_KEYBOARD
    )

    return EXCHANGE_USD


async def exchange_usd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:

        amount = parse_usd(update.message.text)

        current_balance = get_balance("USD")

        if amount > current_balance:
            await update.message.reply_text(
                "❌ Dollar yetarli emas.\n\n"
                f"Qoldiq: {format_usd(current_balance)}"
            )

            return EXCHANGE_USD

        context.chat_data["exchange_usd"] = amount

        await update.message.reply_text(
            f"💵 Maydalanmoqda: "
            f"{format_usd(amount)}\n\n"
            "🇺🇿 Necha so'm oldingiz?"
        )

        return EXCHANGE_UZS

    except (ValueError, InvalidOperation):

        await update.message.reply_text(
            "❌ Dollar miqdorini to'g'ri kiriting."
        )

        return EXCHANGE_USD


async def exchange_uzs(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:

        uzs_amount = parse_uzs(update.message.text)

        usd_amount = context.chat_data["exchange_usd"]

        add_exchange(
            usd_amount,
            uzs_amount,
            update.effective_user.id
        )

        usd_balance = get_balance("USD")
        uzs_balance = get_balance("UZS")

        dollar_value = Decimal(usd_amount) / Decimal(100)

        rate = Decimal(uzs_amount) / dollar_value

        await update.message.reply_text(
            "✅ Dollar maydalandi\n\n"
            f"💵 -{format_usd(usd_amount)}\n"
            f"🇺🇿 +{format_uzs(uzs_amount)} so'm\n\n"
            f"📊 Kurs: "
            f"{format_uzs(int(rate))} so'm\n\n"
            "QOLDIQ:\n"
            f"🇺🇿 {format_uzs(uzs_balance)} so'm\n"
            f"💵 {format_usd(usd_balance)}",
            reply_markup=MAIN_KEYBOARD
        )

        context.chat_data.clear()

        return ConversationHandler.END

    except InsufficientFunds:
        await update.message.reply_text("❌ Balansda pul yetarli emas.", reply_markup=CANCEL_KEYBOARD)
        return EXCHANGE_UZS

    except (ValueError, InvalidOperation):

        await update.message.reply_text(
            "❌ So'm miqdorini to'g'ri kiriting."
        )

        return EXCHANGE_UZS


# =========================================================
# XARAJAT
# =========================================================

def parse_expense_text(text):
    text = text.strip()
    currency = "USD" if text.endswith("$") else "UZS"
    if currency == "USD":
        text = text[:-1].rstrip()
    parts = text.rsplit(maxsplit=1)
    if len(parts) != 2:
        raise ValueError
    name = " ".join(parts[0].split())
    if not name or len(name) > 200:
        raise ValueError
    amount = parse_usd(parts[1]) if currency == "USD" else parse_uzs(parts[1])
    return name, amount, currency


async def card_expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    context.chat_data.clear()
    await update.message.reply_text(
        "💳 Kartadan xarajat\n\n"
        f"Karta qoldiq: {format_uzs(get_balance('UZS', 'card'))} so'm\n\n"
        "Xarajat nomi va summani yozing.",
        reply_markup=CANCEL_KEYBOARD
    )
    return CARD_EXPENSE


async def card_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await record_expense(update, context, account="card")


async def expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    if update.message.text.strip() in {
        "💰 Pul oldim", "💵 $ maydalash", "⬅️ Bekor qilish",
        "🇺🇿 So'm", "🇺🇸 Dollar", CARD_BUTTON, CARD_EXPENSE_BUTTON,
        STATISTICS_BUTTON, BACK_BUTTON, RESET_CONFIRM_TEXT, *STATISTICS_PERIODS,
        CLIENTS_BUTTON, ADD_CLIENT_BUTTON, CLIENT_INCOME_BUTTON, CLIENT_CASH_BUTTON,
        CLIENT_SPLIT_BUTTON, EMPLOYEES_BUTTON, ADD_EMPLOYEE_BUTTON, EMPLOYEE_PAY_BUTTON,
        EMPLOYEE_REPORT_BUTTON, EMPLOYEE_PREV, EMPLOYEE_NEXT,
        CLIENT_CARD_BUTTON, CLIENT_REPORT_BUTTON, OTHER_BUTTON, OTHER_CASH_BUTTON,
        OTHER_CARD_BUTTON, OTHER_REPORT_BUTTON, PREV_CLIENTS_BUTTON, NEXT_CLIENTS_BUTTON,
    }:
        return
    if update.message.text.startswith(("👤 #", "👷 #")):
        section = "Xodimlar" if update.message.text.startswith("👷 #") else "Mijozlar"
        await update.message.reply_text(f"Avval «{section}» tugmasini bosib ro'yxatdan tanlang.", reply_markup=MAIN_KEYBOARD)
        return
    return await record_expense(update, context, account="cash")


async def record_expense(update: Update, context: ContextTypes.DEFAULT_TYPE, account, selected_expense=None, selected_retry=CLIENT_EXPENSE_ACCOUNT):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    scope = context.chat_data.get("expense_scope")
    client = active_client(context)
    if scope == "client" and client is None:
        return await clients_start(update, context)
    success_state = CLIENT_MENU if client else OTHER_MENU if scope == "other" else ConversationHandler.END
    retry_state = CARD_EXPENSE if account == "card" else success_state
    keyboard = scope_keyboard(context)
    retry_keyboard = CANCEL_KEYBOARD if account == "card" else keyboard
    if update.message.text.startswith("👷 #"):
        return await employees_start(update, context)
    if update.message.text.startswith("👤 #"):
        return await clients_start(update, context)
    if client and selected_expense is None:
        text = update.message.text.strip()
        try:
            # Hisob tanlanguncha summani birlikda saqlaymiz; dollar sentlari keyin hisoblanadi.
            raw = text[:-1].rstrip() if text.endswith("$") else text
            name, amount_text = raw.rsplit(maxsplit=1)
            if not name.strip() or len(name) > 200:
                raise ValueError
            try:
                parse_usd(amount_text)
            except (ValueError, InvalidOperation):
                if text.endswith("$"):
                    raise
                parse_uzs(amount_text)
        except (ValueError, InvalidOperation):
            await update.message.reply_text("❌ Xarajat nomi va summani to'g'ri yozing.", reply_markup=retry_keyboard)
            return retry_state
        context.chat_data["pending_client_expense"] = (client[0], name, amount_text)
        await update.message.reply_text("Qaysi hisobdan?", reply_markup=CLIENT_EXPENSE_KEYBOARD)
        return CLIENT_EXPENSE_ACCOUNT
    if selected_expense is not None:
        retry_state = selected_retry
        retry_keyboard = CLIENT_EXPENSE_KEYBOARD if selected_retry == CLIENT_EXPENSE_ACCOUNT else CANCEL_KEYBOARD
    try:
        name, amount, currency = selected_expense or parse_expense_text(update.message.text)
    except (ValueError, InvalidOperation):
        await update.message.reply_text(
            "❌ Xarajat nomi va summani to'g'ri yozing.",
            reply_markup=retry_keyboard
        )
        return retry_state

    if account == "card" and currency == "USD":
        await update.message.reply_text(
            "💳 Karta hisobi so'mda yuritiladi.",
            reply_markup=CANCEL_KEYBOARD
        )
        return CARD_EXPENSE

    try:
        if account == "card":
            amount = add_card_expense(amount, name, update.effective_user.id, client_id=client[0] if client else None)
        else:
            add_transaction("expense", currency, -amount, name, update.effective_user.id,
                            client_id=client[0] if client else None)
    except InsufficientFunds:
        await update.message.reply_text(
            "❌ Balansda pul yetarli emas.",
            reply_markup=retry_keyboard
        )
        return retry_state
    except (sqlite3.Error, OSError) as exc:
        print("Xarajatni saqlashda xato:", exc)
        await update.message.reply_text(
            "❌ Xarajat saqlanmadi. Qayta urinib ko'ring.",
            reply_markup=retry_keyboard
        )
        return retry_state

    context.chat_data.pop("pending_client_expense", None)
    if not scope:
        context.chat_data.clear()
    account_label = "💳 Karta" if account == "card" else "💵 Naqd dollar" if currency == "USD" else "💰 Naqd so'm"
    account_balance = get_balance(currency, account)
    amount_text = format_usd(amount) if currency == "USD" else f"{format_uzs(amount)} so'm"
    balance_text = format_usd(account_balance) if currency == "USD" else f"{format_uzs(account_balance)} so'm"
    client_line = f"👤 Mijoz: {client[1]}\n" if client else ""
    balance_label = f"Umumiy kassa — {account_label}" if client else account_label
    await update.message.reply_text(
        "🔴 Xarajat yozildi\n\n"
        f"{client_line}"
        f"📝 {name}\n"
        f"Manba: {account_label}\n"
        f"➖ {amount_text}\n\n"
        f"{balance_label} qoldiq: {balance_text}",
        reply_markup=keyboard
    )

    await send_transaction_report(
        update, context, "expense", currency, amount, account=account, note=name,
        client_name=client[1] if client else None, reply_markup=keyboard
    )
    return success_state


# =========================================================
# HISOB
# =========================================================

async def balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not await report_access(update):
        return ConversationHandler.END

    if is_cashier(update):
        context.chat_data.clear()
    uzs = get_balance("UZS")
    usd = get_balance("USD")
    card = get_balance("UZS", "card")

    await update.message.reply_text(
        f"Karta: {format_uzs(card)} so'm\n"
        f"So'm: {format_uzs(uzs)} so'm\n"
        f"Dollar: {format_usd(usd)}",
        reply_markup=MAIN_KEYBOARD if is_cashier(update) else BOSS_KEYBOARD
    )
    return ConversationHandler.END


# =========================================================
# STATISTIKA
# =========================================================

async def statistics_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await report_access(update):
        return ConversationHandler.END
    if is_cashier(update):
        context.chat_data.clear()
    await update.message.reply_text("Davrni tanlang:", reply_markup=STATISTICS_KEYBOARD)
    return STATISTICS_PERIOD


async def statistics_period(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await report_access(update):
        return ConversationHandler.END
    selection = STATISTICS_PERIODS.get(update.message.text)
    if selection is None:
        await update.message.reply_text(
            "Statistika davrini tanlang yoki asosiy menyuga qayting.",
            reply_markup=STATISTICS_KEYBOARD
        )
        return STATISTICS_PERIOD
    return await show_statistics(update, *selection)


def split_statistics_text(text, limit=4000):
    while text:
        size = 0
        end = 0
        last_newline = 0
        for char in text:
            width = 2 if ord(char) > 0xFFFF else 1
            if size + width > limit:
                break
            size += width
            end += 1
            if char == "\n":
                last_newline = end
        else:
            yield text
            return
        cut = last_newline or end
        chunk = text[:cut].rstrip("\n")
        if chunk:
            yield chunk
        text = text[cut:]


async def reply_report(update, text, summary, keyboard):
    chunks = list(split_statistics_text(text))
    if summary:
        combined = chunks[-1] + "\n\n" + summary
        if len(combined.encode("utf-16-le")) // 2 <= 4000:
            chunks[-1] = combined
        else:
            chunks.append(summary)
    for chunk in chunks:
        while True:
            try:
                await update.message.reply_text(chunk, reply_markup=keyboard)
                break
            except RetryAfter as exc:
                delay = exc.retry_after
                if isinstance(delay, timedelta):
                    delay = delay.total_seconds()
                await asyncio.sleep(delay + 0.1)


async def show_statistics(update: Update, period, label):
    expenses, totals, balances = get_statistics(period)
    lines = [f"📊 STATISTIKA — {label}", ""]
    if not expenses:
        lines.append("Bu davrda xarajat yo'q.")
    for index, (created_at, note, currency, amount, account) in enumerate(expenses, 1):
        amount_text = format_usd(amount) if currency == "USD" else f"{format_uzs(amount)} so'm"
        source = "karta" if account == "card" else "naqd"
        lines.append(f"{index}. {note or 'Nomsiz'} — {amount_text} ({source})\n{created_at[:16]}")

    summary = (
        "JAMI XARAJAT\n"
        f"So'm: {format_uzs(totals['UZS'])} so'm\n"
        f"Dollar: {format_usd(totals['USD'])}\n\n"
        "HOZIRGI QOLDIQ\n"
        f"Naqd so'm: {format_uzs(balances[('cash', 'UZS')])} so'm\n"
        f"Karta: {format_uzs(balances[('card', 'UZS')])} so'm\n"
        f"Dollar: {format_usd(balances[('cash', 'USD')])}"
    )
    await reply_report(update, "\n".join(lines), summary, STATISTICS_KEYBOARD)
    return STATISTICS_PERIOD


# =========================================================
# TARIX
# =========================================================

async def history(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END

    context.chat_data.clear()
    rows = get_history(10)

    if not rows:
        await update.message.reply_text(
            "Hozircha operatsiyalar yo'q.",
            reply_markup=MAIN_KEYBOARD
        )
        return ConversationHandler.END

    lines = ["📋 OXIRGI 10 TA OPERATSIYA\n"]

    for created_at, kind, currency, amount, note, account in rows:

        if kind == "income":
            icon = "🟢"

        elif kind == "expense":
            icon = "🔴"

        elif kind.startswith("exchange"):
            icon = "🔄"

        else:
            icon = "•"

        if currency == "UZS":
            amount_text = (
                f"{format_uzs(abs(amount))} so'm"
            )
        else:
            amount_text = format_usd(abs(amount))

        sign = "+" if amount > 0 else "-"

        lines.append(
            f"{icon} {note}\n"
            f"{'💳 Karta' if account == 'card' else '💵 Naqd'}\n"
            f"{sign}{amount_text}\n"
            f"{created_at}\n"
        )

    await reply_report(update, "\n".join(lines), "", MAIN_KEYBOARD)
    return ConversationHandler.END


# =========================================================
# NOLGA TUSHIRISH
# =========================================================

async def reset_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END

    context.chat_data.clear()
    await update.message.reply_text(
        "⚠️ Kassani nolga tushirish\n\n"
        "Naqd so'm, dollar va karta qoldiqlari 0 bo'ladi. "
        "Barcha kirim, xarajat va dollar maydalash tarixi tozalanadi.\n\n"
        "Mijozlarning kirim va xarajatlari ham tozalanadi, mijoz nomlari saqlanadi.\n"
        "Xodimlarga berilgan pullar tarixi ham tozalanadi, xodim nomlari saqlanadi.\n\n"
        "Tozalashdan oldin zaxira nusxasi saqlanadi.\n\n"
        "Tasdiqlaysizmi?",
        reply_markup=RESET_KEYBOARD
    )
    return RESET_CONFIRM


async def reset_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await reject_if_not_cashier(update):
        return ConversationHandler.END

    if update.message.text != RESET_CONFIRM_TEXT:
        await update.message.reply_text(
            "Nolga tushirish uchun tasdiqlash tugmasini bosing "
            "yoki amalni bekor qiling.",
            reply_markup=RESET_KEYBOARD
        )
        return RESET_CONFIRM

    try:
        reset_database()
    except (sqlite3.Error, OSError) as exc:
        print("Kassani nolga tushirishda xato:", exc)
        await update.message.reply_text(
            "❌ Kassani nolga tushirib bo'lmadi. Ma'lumotlar saqlandi.\n"
            "Qayta urinib ko'ring yoki amalni bekor qiling.",
            reply_markup=RESET_KEYBOARD
        )
        return RESET_CONFIRM

    context.chat_data.clear()
    await update.message.reply_text(
        "✅ Kassa nolga tushirildi.\n\n"
        "🇺🇿 So'm: 0 so'm\n"
        "💵 Dollar: $0\n"
        "💳 Karta: 0 so'm\n"
        "📋 Operatsiyalar tarixi tozalandi.\n\n"
        "Mijozlarning yozuvlari tozalandi, mijoz nomlari saqlandi.\n\n"
        "Zaxira nusxasi saqlandi. Endi yangidan boshlashingiz mumkin.",
        reply_markup=MAIN_KEYBOARD
    )
    return ConversationHandler.END


# =========================================================
# BEKOR QILISH
# =========================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if is_boss(update) and not is_cashier(update):
        return await start(update, context)
    if await reject_if_not_cashier(update):
        return ConversationHandler.END
    client = active_client(context)
    if client:
        return await show_client(update, context, client)
    if "client_choices" in context.chat_data:
        return await clients_start(update, context)
    if context.chat_data.get("expense_scope") == "other":
        return await other_start(update, context)
    context.chat_data.clear()

    await update.message.reply_text(
        "❌ Amal bekor qilindi.",
        reply_markup=MAIN_KEYBOARD
    )

    return ConversationHandler.END


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN sozlanmagan. .env faylini to'ldirib, sh run.sh buyrug'ini bajaring."
        )

    init_db()

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(False)
        .build()
    )

    conversation = ConversationHandler(

        entry_points=[
            CommandHandler("qaytarish", undo_start),
            MessageHandler(filters.Regex(f"^{re.escape(UNDO_BUTTON)}$"), undo_start),
            CommandHandler("start", start),
            CommandHandler("hisob", balance),
            MessageHandler(filters.Regex(f"^{re.escape(BALANCE_BUTTON)}$"), balance),
            CommandHandler("tarix", history),
            CommandHandler(["statistika", "stats"], statistics_start),
            CommandHandler("kartadan", card_expense_start),
            CommandHandler("reset", reset_start),
            CommandHandler("xodimlar", employees_start),
            MessageHandler(filters.Regex(f"^{re.escape(EMPLOYEES_BUTTON)}$"), employees_start),
            CommandHandler("mijozlar", clients_start),
            CommandHandler("boshqa", other_start),
            MessageHandler(filters.Regex(f"^{re.escape(CLIENTS_BUTTON)}$"), clients_start),
            MessageHandler(filters.Regex(f"^{re.escape(OTHER_BUTTON)}$"), other_start),
            MessageHandler(filters.Regex("^💳 Kartadan$"), card_expense_start),
            MessageHandler(filters.Regex("^📊 Statistika$"), statistics_start),
            MessageHandler(filters.Regex("^⬅️ Asosiy menyu$"), start),
            MessageHandler(
                filters.Regex("^💰 Pul oldim$"),
                income_start
            ),

            MessageHandler(
                filters.Regex(r"^💵 \$ maydalash$"),
                exchange_start
            ),
        ],

        states={
            UNDO_LIST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, undo_select),
            ],
            UNDO_CONFIRM: [
                MessageHandler(filters.Regex("^⬅️ Bekor qilish$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, undo_confirm),
            ],
            OTHER_USD: [
                MessageHandler(filters.Regex("^⬅️ Bekor qilish$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, other_usd_expense),
            ],
            **{state: [CommandHandler("cancel", employee_cancel),
                       MessageHandler(filters.Regex("^⬅️ Bekor qilish$"), employee_cancel),
                       MessageHandler(filters.TEXT & ~filters.COMMAND, callback)]
               for state, callback in ((EMPLOYEE_LIST, employee_select), (EMPLOYEE_NAME, employee_create),
                                       (EMPLOYEE_MENU, employee_menu), (EMPLOYEE_CURRENCY, employee_currency),
                                       (EMPLOYEE_AMOUNT, employee_amount))},

            CLIENT_LIST: [
                MessageHandler(filters.Regex("^⬅️ Bekor qilish$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, clients_select),
            ],
            CLIENT_NAME: [
                MessageHandler(filters.Regex("^⬅️ Bekor qilish$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, client_create),
            ],
            CLIENT_SPLIT_USD: [
                MessageHandler(filters.Regex("^⬅️ Bekor qilish$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, client_split_usd),
            ],
            CLIENT_SPLIT_CARD: [
                MessageHandler(filters.Regex("^⬅️ Bekor qilish$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, client_split_card),
            ],
            CLIENT_EXPENSE_ACCOUNT: [
                MessageHandler(filters.Regex("^⬅️ Bekor qilish$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, client_expense_account),
            ],
            CLIENT_DELETE_CONFIRM: [
                MessageHandler(filters.Regex("^⬅️ Bekor qilish$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, client_delete_confirm),
            ],
            CLIENT_MENU: [
                MessageHandler(filters.Regex("^⬅️ Bekor qilish$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, client_menu),
            ],
            OTHER_MENU: [
                MessageHandler(filters.Regex("^⬅️ Bekor qilish$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, other_menu),
            ],

            CARD_EXPENSE: [
                MessageHandler(filters.Regex("^⬅️ Bekor qilish$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, card_expense),
            ],

            STATISTICS_PERIOD: [
                MessageHandler(filters.Regex("^⬅️ Bekor qilish$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, statistics_period),
            ],

            RESET_CONFIRM: [
                MessageHandler(
                    filters.Regex("^⬅️ Bekor qilish$"),
                    cancel
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    reset_confirm
                ),
            ],

            CHOOSE_CURRENCY: [
                MessageHandler(
                    filters.Regex("^⬅️ Bekor qilish$"),
                    cancel
                ),
                MessageHandler(
                    filters.Regex(
                        rf"^(🇺🇿 So'm|🇺🇸 Dollar|💳 Karta|{re.escape(CLIENT_SPLIT_BUTTON)})$"
                    ),
                    choose_currency
                ),
                MessageHandler(filters.TEXT & ~filters.COMMAND, currency_invalid),
            ],

            INCOME_AMOUNT: [
                MessageHandler(
                    filters.Regex("^⬅️ Bekor qilish$"),
                    cancel
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    income_amount
                ),
            ],

            EXCHANGE_USD: [
                MessageHandler(
                    filters.Regex("^⬅️ Bekor qilish$"),
                    cancel
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    exchange_usd
                ),
            ],

            EXCHANGE_UZS: [
                MessageHandler(
                    filters.Regex("^⬅️ Bekor qilish$"),
                    cancel
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    exchange_uzs
                ),
            ],
        },

        fallbacks=[
            CommandHandler("reset", reset_start),
            CommandHandler("cancel", cancel)
        ],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("id", get_id))

    app.add_handler(conversation)

    # Oddiy yozilgan xabarlar = xarajat
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            expense
        )
    )

    print("BOT ISHLADI...")

    app.run_polling(
        drop_pending_updates=False
    )


if __name__ == "__main__":
    main()
