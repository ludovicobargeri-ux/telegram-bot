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

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
DB_PATH = os.environ.get("DB_PATH", "data/budget.db")

# ── Categories ────────────────────────────────────────────────────────────────
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

# ── Database ──────────────────────────────────────────────────────────────────
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

# ── Helpers ───────────────────────────────────────────────────────────────────
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

# ── /start ────────────────────────────────────────────────────────────────────
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

# ── /help ─────────────────────────────────────────────────────────────────────
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

# ── /summary ──────────────────────────────────────────────────────────────────
async def summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    start, end, month_name = month_range()
    con = get_con()

    rows = con.execute(
        "SELECT category, SUM(amount) FROM expenses "
        "WHERE user_id=? AND date BETWEEN ? AND ? GROUP BY category",
        (uid, start, end)
    ).fetchall()

    inv_total = con.execute(
        "SELECT SUM(value) FROM investments WHERE user_id=?", (uid,)
    ).fetchone()[0] or 0

    exp_count = con.execute(
        "SELECT COUNT(*) FROM expenses WHERE user_id=? AND date BETWEEN ? AND ?",
        (uid, start, end)
    ).fetchone()[0]
    con.close()

    total_spent = sum(r[1] for r in rows)
    total_budget = sum(get_budget(uid, c) for c in CATEGORIES)
    remaining = total_budget - total_spent
    remaining_emoji = "✅" if remaining >= 0 else "🔴"

    lines = [f"📊 *{month_name} — Summary*\n"]
    lines.append(f"💸 Total spent: *{fmt(total_spent)}*")
    lines.append(f"🎯 Total budget: *{fmt(total_budget)}*")
    lines.append(f"{remaining_emoji} Remaining: *{fmt(remaining)}*")
    lines.append(f"🧾 Transactions: *{exp_count}*")
    lines.append(f"📈 Portfolio: *{fmt(inv_total)}*")

    if rows:
        lines.append("\n📂 *By Category:*")
        for cat, amt in sorted(rows, key=lambda x: x[1], reverse=True):
            budget = get_budget(uid, cat)
            pct = int(amt / budget * 100) if budget else 0
            bar = "█" * min(10, pct // 10) + "░" * max(0, 10 - pct // 10)
            warn = " ⚠️" if pct > 90 else ""
            lines.append(f"`{bar}` {cat}\n    {fmt(amt)} / {fmt(budget)} ({pct}%){warn}")

    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard()
    )

# ── /quick ────────────────────────────────────────────────────────────────────
async def quick_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Usage: /quick 12.50 Groceries coffee at lidl"""
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/quick <amount> <category> [description]`\n"
            "Example: `/quick 12.50 Groceries coffee at lidl`",
            parse_mode="Markdown"
        )
        return

    try:
        amount = float(args[0].replace(",", ".").replace("€", ""))
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Use a number like `12.50`", parse_mode="Markdown")
        return

    # Match category (partial, case-insensitive)
    raw_cat = args[1].lower()
    matched = next((c for c in CATEGORIES if raw_cat in c.lower()), None)
    if not matched:
        cats = ", ".join(f"`{c}`" for c in CATEGORIES)
        await update.message.reply_text(
            f"❌ Category not found. Available:\n{cats}", parse_mode="Markdown"
        )
        return

    description = " ".join(args[2:]) if len(args) > 2 else matched
    today = date.today().isoformat()
    uid = update.effective_user.id

    con = get_con()
    cur = con.execute(
        "INSERT INTO expenses (user_id, amount, category, description, date) VALUES (?,?,?,?,?)",
        (uid, amount, matched, description, today)
    )
    expense_id = cur.lastrowid
    con.commit()
    con.close()

    budget = get_budget(uid, matched)
    start, end, _ = month_range()
    con = get_con()
    spent = con.execute(
        "SELECT SUM(amount) FROM expenses WHERE user_id=? AND category=? AND date BETWEEN ? AND ?",
        (uid, matched, start, end)
    ).fetchone()[0] or 0
    con.close()

    pct = int(spent / budget * 100) if budget else 0
    warn = "\n⚠️ *Budget alert!* You've exceeded 90% for this category." if pct > 90 else ""

    await update.message.reply_text(
        f"✅ *Expense added* (ID: {expense_id})\n\n"
        f"📂 {matched}\n"
        f"📝 {description}\n"
        f"💸 {fmt(amount)}\n"
        f"📅 {today}\n"
        f"📊 This month: {fmt(spent)} / {fmt(budget)} ({pct}%){warn}",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

# ── /add (conversation) ───────────────────────────────────────────────────────
async def add_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 *New Expense*\n\nWhat did you spend on?",
        parse_mode="Markdown"
    )
    return WAITING_EXPENSE_DESC

async def add_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["exp_desc"] = update.message.text
    await update.message.reply_text("💶 How much? (e.g. `12.50`)", parse_mode="Markdown")
    return WAITING_EXPENSE_AMOUNT

async def add_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.replace(",", ".").replace("€", ""))
        ctx.user_data["exp_amount"] = amount
        await update.message.reply_text("📂 Choose a category:", reply_markup=cat_keyboard())
        return WAITING_EXPENSE_CAT
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number (e.g. `12.50`)", parse_mode="Markdown")
        return WAITING_EXPENSE_AMOUNT

async def add_cat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cat = update.message.text
    if cat not in CATEGORIES:
        await update.message.reply_text("❌ Please choose from the keyboard.", reply_markup=cat_keyboard())
        return WAITING_EXPENSE_CAT

    uid = update.effective_user.id
    desc = ctx.user_data["exp_desc"]
    amount = ctx.user_data["exp_amount"]
    today = date.today().isoformat()

    con = get_con()
    cur = con.execute(
        "INSERT INTO expenses (user_id, amount, category, description, date) VALUES (?,?,?,?,?)",
        (uid, amount, cat, desc, today)
    )
    expense_id = cur.lastrowid
    con.commit()

    start, end, _ = month_range()
    spent = con.execute(
        "SELECT SUM(amount) FROM expenses WHERE user_id=? AND category=? AND date BETWEEN ? AND ?",
        (uid, cat, start, end)
    ).fetchone()[0] or 0
    con.close()

    budget = get_budget(uid, cat)
    pct = int(spent / budget * 100) if budget else 0
    warn = "\n⚠️ *Budget alert!* Over 90% used." if pct > 90 else ""

    await update.message.reply_text(
        f"✅ *Saved!* (ID: {expense_id})\n\n"
        f"📂 {cat} · 💸 {fmt(amount)}\n"
        f"📝 {desc} · 📅 {today}\n"
        f"📊 Monthly: {fmt(spent)} / {fmt(budget)} ({pct}%){warn}",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.", reply_markup=main_keyboard())
    return ConversationHandler.END

# ── /history ──────────────────────────────────────────────────────────────────
async def history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    con = get_con()
    rows = con.execute(
        "SELECT id, date, category, description, amount FROM expenses "
        "WHERE user_id=? ORDER BY date DESC, id DESC LIMIT 10",
        (uid,)
    ).fetchall()
    con.close()

    if not rows:
        await update.message.reply_text("📭 No expenses recorded yet.", reply_markup=main_keyboard())
        return

    lines = ["📅 *Last 10 Expenses*\n"]
    for row in rows:
        eid, d, cat, desc, amt = row
        lines.append(f"`#{eid}` {d} · {cat}\n    📝 {desc} · {fmt(amt)}")

    lines.append("\nTo delete: `/delete <id>`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())

# ── /delete ───────────────────────────────────────────────────────────────────
async def delete_expense(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ctx.args:
        await update.message.reply_text("Usage: `/delete <id>`", parse_mode="Markdown")
        return
    try:
        eid = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID.")
        return

    con = get_con()
    row = con.execute("SELECT id, description, amount FROM expenses WHERE id=? AND user_id=?", (eid, uid)).fetchone()
    if not row:
        await update.message.reply_text("❌ Expense not found or not yours.")
        con.close()
        return
    con.execute("DELETE FROM expenses WHERE id=?", (eid,))
    con.commit()
    con.close()
    await update.message.reply_text(
        f"🗑️ Deleted: *{row[1]}* — {fmt(row[2])}", parse_mode="Markdown", reply_markup=main_keyboard()
    )

# ── /budget ───────────────────────────────────────────────────────────────────
async def budget_view(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    start, end, month_name = month_range()
    con = get_con()
    spent_rows = con.execute(
        "SELECT category, SUM(amount) FROM expenses "
        "WHERE user_id=? AND date BETWEEN ? AND ? GROUP BY category",
        (uid, start, end)
    ).fetchall()
    con.close()

    spent_map = {r[0]: r[1] for r in spent_rows}
    lines = [f"💰 *Budget — {month_name}*\n"]

    for cat, default_budget in CATEGORIES.items():
        budget = get_budget(uid, cat)
        spent = spent_map.get(cat, 0)
        remaining = budget - spent
        pct = int(spent / budget * 100) if budget else 0
        filled = min(10, pct // 10)
        bar = "█" * filled + "░" * (10 - filled)
        status = "✅" if remaining >= 0 else "🔴"
        lines.append(
            f"{status} *{cat}*\n"
            f"`{bar}` {pct}%\n"
            f"    {fmt(spent)} spent · {fmt(remaining)} left\n"
        )

    lines.append("To change a budget: `/setbudget`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())

# ── /setbudget ────────────────────────────────────────────────────────────────
async def setbudget_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📂 Which category?", reply_markup=cat_keyboard())
    return WAITING_BUDGET_CAT

async def setbudget_cat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cat = update.message.text
    if cat not in CATEGORIES:
        await update.message.reply_text("❌ Choose from the keyboard.", reply_markup=cat_keyboard())
        return WAITING_BUDGET_CAT
    ctx.user_data["budget_cat"] = cat
    current = get_budget(update.effective_user.id, cat)
    await update.message.reply_text(
        f"Current budget for *{cat}*: {fmt(current)}\n\nEnter new monthly budget (€):",
        parse_mode="Markdown"
    )
    return WAITING_BUDGET_AMOUNT

async def setbudget_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.replace(",", ".").replace("€", ""))
    except ValueError:
        await update.message.reply_text("❌ Invalid number.")
        return WAITING_BUDGET_AMOUNT

    uid = update.effective_user.id
    cat = ctx.user_data["budget_cat"]
    con = get_con()
    con.execute(
        "INSERT OR REPLACE INTO budgets (user_id, category, amount) VALUES (?,?,?)",
        (uid, cat, amount)
    )
    con.commit()
    con.close()
    await update.message.reply_text(
        f"✅ Budget for *{cat}* set to *{fmt(amount)}*",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END

# ── /investments ──────────────────────────────────────────────────────────────
async def investments(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    con = get_con()
    rows = con.execute(
        "SELECT id, ticker, name, value, buy_price, current_price, added_date "
        "FROM investments WHERE user_id=? ORDER BY value DESC",
        (uid,)
    ).fetchall()
    total = con.execute("SELECT SUM(value) FROM investments WHERE user_id=?", (uid,)).fetchone()[0] or 0
    con.close()

    if not rows:
        await update.message.reply_text(
            "📭 No investments yet. Use `/addinv` to add one.", parse_mode="Markdown", reply_markup=main_keyboard()
        )
        return

    lines = [f"📈 *Portfolio* — Total: {fmt(total)}\n"]
    for row in rows:
        iid, ticker, name, value, buy, current, added = row
        pnl = (current - buy) / buy * 100 if buy else 0
        arrow = "▲" if pnl >= 0 else "▼"
        lines.append(
            f"`#{iid}` *{ticker}* — {name}\n"
            f"    💶 {fmt(value)} · {arrow} {abs(pnl):.1f}% P&L\n"
            f"    Cost: {fmt(buy)} · Now: {fmt(current)}\n"
        )

    lines.append("Delete: `/delinv <id>`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard())

# ── /addinv (conversation) ────────────────────────────────────────────────────
async def addinv_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📈 *New Investment*\n\nTicker symbol? (e.g. TAO, ENI, BTC)", parse_mode="Markdown")
    return WAITING_INV_TICKER

async def addinv_ticker(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["inv_ticker"] = update.message.text.upper()
    await update.message.reply_text("📛 Full name? (e.g. Bittensor, Eni SpA)")
    return WAITING_INV_NAME

async def addinv_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["inv_name"] = update.message.text
    await update.message.reply_text("💶 Total value invested (€)?")
    return WAITING_INV_VALUE

async def addinv_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["inv_value"] = float(update.message.text.replace(",", ".").replace("€", ""))
        await update.message.reply_text("📉 Buy price per unit? (e.g. 275.00)")
        return WAITING_INV_BUY
    except ValueError:
        await update.message.reply_text("❌ Invalid number.")
        return WAITING_INV_VALUE

async def addinv_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        ctx.user_data["inv_buy"] = float(update.message.text.replace(",", "."))
        await update.message.reply_text("📈 Current price per unit?")
        return WAITING_INV_CURRENT
    except ValueError:
        await update.message.reply_text("❌ Invalid number.")
        return WAITING_INV_BUY

async def addinv_current(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        current = float(update.message.text.replace(",", "."))
    except ValueError:
        await update.message.reply_text("❌ Invalid number.")
        return WAITING_INV_CURRENT

    uid = update.effective_user.id
    d = ctx.user_data
    buy = d["inv_buy"]
    pnl = (current - buy) / buy * 100 if buy else 0
    arrow = "▲" if pnl >= 0 else "▼"

    con = get_con()
    cur = con.execute(
        "INSERT INTO investments (user_id, ticker, name, value, buy_price, current_price, added_date) VALUES (?,?,?,?,?,?,?)",
        (uid, d["inv_ticker"], d["inv_name"], d["inv_value"], buy, current, date.today().isoformat())
    )
    iid = cur.lastrowid
    con.commit()
    con.close()

    await update.message.reply_text(
        f"✅ *Investment added!* (ID: {iid})\n\n"
        f"🏷 *{d['inv_ticker']}* — {d['inv_name']}\n"
        f"💶 Value: {fmt(d['inv_value'])}\n"
        f"📉 Cost basis: {fmt(buy)} · 📈 Current: {fmt(current)}\n"
        f"{arrow} P&L: {abs(pnl):.1f}%",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END

# ── /delinv ───────────────────────────────────────────────────────────────────
async def delinv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ctx.args:
        await update.message.reply_text("Usage: `/delinv <id>`", parse_mode="Markdown")
        return
    try:
        iid = int(ctx.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID.")
        return

    con = get_con()
    row = con.execute("SELECT ticker, value FROM investments WHERE id=? AND user_id=?", (iid, uid)).fetchone()
    if not row:
        await update.message.reply_text("❌ Investment not found or not yours.")
        con.close()
        return
    con.execute("DELETE FROM investments WHERE id=?", (iid,))
    con.commit()
    con.close()
    await update.message.reply_text(
        f"🗑️ Deleted: *{row[0]}* — {fmt(row[1])}", parse_mode="Markdown", reply_markup=main_keyboard()
    )

# ── /reset ────────────────────────────────────────────────────────────────────
async def reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    con = get_con()
    con.execute("DELETE FROM expenses WHERE user_id=?", (uid,))
    con.execute("DELETE FROM investments WHERE user_id=?", (uid,))
    con.execute("DELETE FROM budgets WHERE user_id=?", (uid,))
    con.commit()
    con.close()
    await update.message.reply_text("🗑️ All your data has been cleared.", reply_markup=main_keyboard())

# ── Menu button handler ───────────────────────────────────────────────────────
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
        await add_start(update, ctx)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    # Conversation: add expense
    exp_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            WAITING_EXPENSE_DESC:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_desc)],
            WAITING_EXPENSE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_amount)],
            WAITING_EXPENSE_CAT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_cat)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Conversation: add investment
    inv_conv = ConversationHandler(
        entry_points=[CommandHandler("addinv", addinv_start)],
        states={
            WAITING_INV_TICKER:  [MessageHandler(filters.TEXT & ~filters.COMMAND, addinv_ticker)],
            WAITING_INV_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, addinv_name)],
            WAITING_INV_VALUE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, addinv_value)],
            WAITING_INV_BUY:     [MessageHandler(filters.TEXT & ~filters.COMMAND, addinv_buy)],
            WAITING_INV_CURRENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, addinv_current)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Conversation: set budget
    budget_conv = ConversationHandler(
        entry_points=[CommandHandler("setbudget", setbudget_start)],
        states={
            WAITING_BUDGET_CAT:    [MessageHandler(filters.TEXT & ~filters.COMMAND, setbudget_cat)],
            WAITING_BUDGET_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbudget_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("quick", quick_add))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("delete", delete_expense))
    app.add_handler(CommandHandler("budget", budget_view))
    app.add_handler(CommandHandler("investments", investments))
    app.add_handler(CommandHandler("delinv", delinv))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(exp_conv)
    app.add_handler(inv_conv)
    app.add_handler(budget_conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_handler))

    logger.info("Bot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
