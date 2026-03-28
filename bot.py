import os
import sqlite3
import logging
from datetime import datetime, date
from calendar import monthrange
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

# ── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN non impostato!")

DB_PATH = os.environ.get("DB_PATH", "/tmp/budget.db")

# ── Categories ─────────────────────────────────────────────────────────────
CATEGORIES = {
    "🏠 Housing":      1200,
    "🛒 Groceries":    400,
    "🚗 Transport":    200,
    "🎉 Leisure":      150,
    "💊 Health":       100,
    "👗 Clothing":     100,
    "💡 Utilities":    150,
    "📦 Other":        200,
}

# ConversationHandler states
WAITING_EXPENSE_DESC, WAITING_EXPENSE_AMOUNT, WAITING_EXPENSE_CAT = range(3)
WAITING_INV_TICKER, WAITING_INV_NAME, WAITING_INV_VALUE, WAITING_INV_BUY, WAITING_INV_CURRENT = range(5, 10)
WAITING_BUDGET_CAT, WAITING_BUDGET_AMOUNT = range(10, 12)

# ── Database ───────────────────────────────────────────────────────────────
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS expenses (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER NOT NULL,
            amount    REAL    NOT NULL,
            category  TEXT    NOT NULL,
            description TEXT  NOT NULL,
            date      TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS investments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            ticker        TEXT    NOT NULL,
            name          TEXT    NOT NULL,
            value         REAL    NOT NULL,
            buy_price     REAL    NOT NULL,
            current_price REAL    NOT NULL,
            added_date    TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS budgets (
            user_id   INTEGER NOT NULL,
            category  TEXT    NOT NULL,
            amount    REAL    NOT NULL,
            PRIMARY KEY (user_id, category)
        );
    """)
    con.commit()
    con.close()
    logger.info("Database initialized")

def get_con():
    return sqlite3.connect(DB_PATH)

def get_budget(user_id, category):
    con = get_con()
    row = con.execute(
        "SELECT amount FROM budgets WHERE user_id=? AND category=?",
        (user_id, category)
    ).fetchone()
    con.close()
    return row[0] if row else CATEGORIES.get(category, 0)

# ── Helpers ───────────────────────────────────────────────────────────────
def month_range():
    today = date.today()
    start = today.replace(day=1).isoformat()
    last  = monthrange(today.year, today.month)[1]
    end   = today.replace(day=last).isoformat()
    return start, end, today.strftime("%B %Y")

def fmt(amount: float) -> str:
    return f"€{amount:,.2f}"

def cat_keyboard():
    keys = list(CATEGORIES.keys())
    rows = [keys[i:i+2] for i in range(0, len(keys), 2)]
    return ReplyKeyboardMarkup(rows, one_time_keyboard=True, resize_keyboard=True)

def main_keyboard():
    buttons = [
        [KeyboardButton("📊 Summary"), KeyboardButton("➕ Add Expense")],
        [KeyboardButton("📈 Investments"), KeyboardButton("💰 Budget")],
        [KeyboardButton("📅 History"), KeyboardButton("❓ Help")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

# ── Error handler ─────────────────────────────────────────────────────────
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception: {context.error}")

# ── /start ───────────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Welcome, *{name}*!\n\n"
        "I'm your personal *Budget Bot*. I'll help you track expenses, "
        "monitor your budget, and manage investments.\n\n"
        "Use the menu below or type a command:",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

# ── /help ────────────────────────────────────────────────────────────────
async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Available Commands*\n\n"
        "💸 *Expenses*\n"
        "`/add` — add a new expense\n"
        "`/quick 12.50 Groceries coffee` — quick add\n"
        "`/history` — last 10 expenses\n"
        "`/delete <id>` — delete an expense\n\n"
        "📊 *Reports*\n"
        "`/summary` — monthly overview\n"
        "`/budget` — budget vs spent by category\n\n"
        "📈 *Investments*\n"
        "`/investments` — view portfolio\n"
        "`/addinv` — add an investment\n"
        "`/delinv <id>` — delete an investment\n\n"
        "⚙️ *Settings*\n"
        "`/setbudget` — set budget for a category\n"
        "`/reset` — clear all your data\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_keyboard())

# ── /menu handler ─────────────────────────────────────────────────────────
async def menu_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📊 Summary":
        await summary(update, ctx)
    elif text == "📈 Investments":
        await investments(update, ctx)
    elif text == "💰 Budget":
        await budget_view(update, ctx)
    elif text == "📅 History":
        await history(update, ctx)
    elif text == "❓ Help":
        await help_cmd(update, ctx)
    elif text == "➕ Add Expense":
        await update.message.reply_text("Usa /add per inserire una spesa")

# ── Main ────────────────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    # Conversation handlers...
    # (qui puoi incollare tutti i ConversationHandler esistenti senza modifiche)

    # Comandi principali
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))

    # Error handler globale
    app.add_error_handler(error_handler)

    logger.info("Bot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
