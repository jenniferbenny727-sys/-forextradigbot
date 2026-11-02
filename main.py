import os
import sqlite3
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
import aiohttp

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x]
FOREX_API_KEY = os.environ.get("FOREX_API_KEY")
DB_PATH = os.environ.get("DB_PATH", "/var/data/bot.db")

# ---------- DATABASE ----------
def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            registered_at TEXT,
            premium_until TEXT,
            subscribed INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()

def register_user(user_id: int, username: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username, registered_at) VALUES (?, ?, ?)",
        (user_id, username, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ---------- MENU ----------
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 Forex Signals", callback_data="signals")],
        [InlineKeyboardButton("📈 Market Analysis", callback_data="analysis")],
        [InlineKeyboardButton("💹 Live Prices", callback_data="prices")],
        [InlineKeyboardButton("🎯 Education", callback_data="education")],
        [InlineKeyboardButton("🛡 Risk Management", callback_data="risk")],
        [InlineKeyboardButton("📉 Economic Calendar", callback_data="calendar")],
        [InlineKeyboardButton("⭐ Premium", callback_data="premium")],
        [InlineKeyboardButton("📞 Contact Admin", callback_data="contact")],
        [InlineKeyboardButton("ℹ️ About", callback_data="about")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ---------- FOREX API (Finnhub example) ----------
async def fetch_forex_quote(symbol: str) -> dict | None:
    if not FOREX_API_KEY:
        return None
    url = "https://finnhub.io/api/v1/forex/rates"
    params = {"base": "USD", "token": FOREX_API_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning(f"Forex API returned {resp.status}")
    except Exception as e:
        logger.error(f"Forex API error: {e}")
    return None

# ---------- HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username or "")
    text = (
        f"👋 Welcome {user.first_name}!\n\n"
        "I'm your Forex Trading Assistant. Use the menu below to explore."
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Main Menu:", reply_markup=main_menu_keyboard()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "signals":
        await query.edit_message_text(
            "📊 *Forex Signals*\n\n"
            "No signals available right now.\n"
            "Signals require live market data via FOREX_API_KEY.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Main Menu", callback_data="main")]
            ]),
        )
    elif data == "prices":
        if not FOREX_API_KEY:
            await query.edit_message_text(
                "💹 *Live Prices*\n\n"
                "⚠️ Forex API key not configured.\n"
                "Set FOREX_API_KEY in your environment.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Main Menu", callback_data="main")]
                ]),
            )
            return
        rates = await fetch_forex_quote("USD")
        if rates is None:
            text = "⚠️ Could not fetch live prices. API may be unavailable."
        else:
            text = f"💹 *Live USD Rates*\n\n`{rates}`"
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Main Menu", callback_data="main")]
            ]),
        )
    elif data == "about":
        await query.edit_message_text(
            "ℹ️ *About*\n\n"
            "Forex Trading Assistant\n"
            "Built with python-telegram-bot.\n"
            "All trading decisions are your responsibility.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Main Menu", callback_data="main")]
            ]),
        )
    elif data == "main":
        await query.edit_message_text(
            "Main Menu:", reply_markup=main_menu_keyboard()
        )
    else:
        await query.edit_message_text(
            "This feature is being configured.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Main Menu", callback_data="main")]
            ]),
        )

# ---------- BACKGROUND JOB (safe pattern) ----------
async def signal_check_job(context: ContextTypes.DEFAULT_TYPE):
    """Runs periodically; guard against overlapping executions."""
    if context.bot_data.get("signal_job_running"):
        return
    context.bot_data["signal_job_running"] = True
    try:
        # Fetch data, generate signals, notify subscribed users
        logger.info("Signal check job ran")
    except Exception as e:
        logger.error(f"Signal job error: {e}")
    finally:
        context.bot_data["signal_job_running"] = False

# ---------- POST INIT ----------
async def post_init(application: Application):
    init_db()
    # Schedule job every 15 minutes, first run after 10 seconds
    application.job_queue.run_repeating(
        signal_check_job, interval=900, first=10
    )
    logger.info("Bot initialized, database ready, job scheduled")

# ---------- MAIN ----------
def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Starting polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
