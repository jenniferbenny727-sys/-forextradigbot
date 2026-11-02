import os
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
import aiohttp

# ---------- LOGGING ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
)
logger = logging.getLogger(__name__)

# ---------- CONFIG ----------
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
FOREX_API_KEY = os.environ.get("FOREX_API_KEY")
DB_PATH_ENV = os.environ.get("DB_PATH", "/var/data/bot.db")


# ---------- SAFE DB PATH RESOLUTION ----------
def resolve_db_path(preferred: str) -> str:
    """
    Return a writable path for the SQLite DB.

    Tries the preferred path first (e.g. /var/data/bot.db on Render with a
    persistent disk). If that directory does not exist or is not writable,
    falls back to /tmp/bot.db so the bot can still start.
    """
    target = Path(preferred)
    parent = target.parent

    try:
        parent.mkdir(parents=True, exist_ok=True)
        # Verify we can actually write inside the directory
        test_file = parent / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        logger.info(f"Using database path: {target}")
        return str(target)
    except (PermissionError, OSError) as e:
        fallback = Path("/tmp/bot.db")
        fallback.parent.mkdir(parents=True, exist_ok=True)
        logger.warning(
            f"Cannot use {preferred} ({e.__class__.__name__}: {e}). "
            f"Falling back to {fallback} — data will NOT persist across redeploys. "
            f"Attach a Render persistent disk mounted at {parent} to fix this."
        )
        return str(fallback)


DB_PATH = resolve_db_path(DB_PATH_ENV)


# ---------- DATABASE ----------
def init_db() -> None:
    """Create tables if they don't exist. Safe to call multiple times."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    registered_at TEXT NOT NULL,
                    premium_until TEXT,
                    subscribed INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stats (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            conn.commit()
        logger.info(f"Database initialized at {DB_PATH}")
    except sqlite3.Error as e:
        logger.error(f"Database initialization failed: {e}")
        raise


def register_user(user_id: int, username: str, first_name: str) -> None:
    """Insert user if not already registered. Update username if changed."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, username, first_name, registered_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name
                """,
                (user_id, username or "", first_name or "", datetime.utcnow().isoformat()),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Failed to register user {user_id}: {e}")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ---------- MENU ----------
def main_menu_keyboard() -> InlineKeyboardMarkup:
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


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Main Menu", callback_data="main")]]
    )


# ---------- FOREX API ----------
async def fetch_forex_rates(base: str = "USD") -> dict | None:
    """Fetch USD-based Forex rates. Returns None if unavailable."""
    if not FOREX_API_KEY:
        return None
    url = "https://finnhub.io/api/v1/forex/rates"
    params = {"base": base, "token": FOREX_API_KEY}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning(f"Forex API returned {resp.status}")
    except (aiohttp.ClientError, TimeoutError) as e:
        logger.error(f"Forex API error: {e}")
    return None


# ---------- HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    register_user(user.id, user.username or "", user.first_name or "")
    text = (
        f"👋 Welcome {user.first_name}!\n\n"
        "I'm your Forex Trading Assistant.\n"
        "Use the menu below to explore signals, analysis, prices, risk tools and more."
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Main Menu:", reply_markup=main_menu_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Available commands:\n"
        "/start - Register and open main menu\n"
        "/menu - Open main menu\n"
        "/help - This help message\n"
        "/about - About the bot",
        reply_markup=back_to_menu_keyboard(),
    )


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "ℹ️ Forex Trading Assistant\n\n"
        "Built with python-telegram-bot.\n"
        "All trading decisions are your responsibility.",
        reply_markup=back_to_menu_keyboard(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    try:
        if data == "signals":
            await query.edit_message_text(
                "📊 *Forex Signals*\n\n"
                "No signals available right now.\n"
                "Signals require live market data via FOREX_API_KEY.",
                parse_mode="Markdown",
                reply_markup=back_to_menu_keyboard(),
            )

        elif data == "analysis":
            await query.edit_message_text(
                "📈 *Market Analysis*\n\n"
                "Technical analysis requires live candle data.\n"
                "Configure FOREX_API_KEY to enable.",
                parse_mode="Markdown",
                reply_markup=back_to_menu_keyboard(),
            )

        elif data == "prices":
            if not FOREX_API_KEY:
                await query.edit_message_text(
                    "💹 *Live Prices*\n\n"
                    "⚠️ Forex API key not configured.\n"
                    "Set FOREX_API_KEY in your environment.",
                    parse_mode="Markdown",
                    reply_markup=back_to_menu_keyboard(),
                )
                return
            await query.edit_message_text("Fetching live prices…")
            rates = await fetch_forex_rates("USD")
            if rates is None:
                text = "⚠️ Could not fetch live prices. API unavailable or rate limited."
            else:
                text = f"💹 *Live USD Rates*\n\n`{rates}`"
            await query.edit_message_text(
                text, parse_mode="Markdown", reply_markup=back_to_menu_keyboard()
            )

        elif data == "education":
            await query.edit_message_text(
                "🎯 *Trading Education*\n\n"
                "• Risk no more than 1–2% per trade.\n"
                "• Always use a stop loss.\n"
                "• Trade with the higher-timeframe trend.\n"
                "• Keep a trading journal.",
                parse_mode="Markdown",
                reply_markup=back_to_menu_keyboard(),
            )

        elif data == "risk":
            await query.edit_message_text(
                "🛡 *Risk Management*\n\n"
                "Position size = (Balance × Risk%) ÷ (Entry − Stop Loss)\n\n"
                "Example: $1000 balance, 1% risk, 20-pip SL → risk $10 per trade.",
                parse_mode="Markdown",
                reply_markup=back_to_menu_keyboard(),
            )

        elif data == "calendar":
            await query.edit_message_text(
                "📉 *Economic Calendar*\n\n"
                "⚠️ Economic calendar API not configured.\n"
                "Set ECONOMIC_CALENDAR_API_KEY to enable.",
                parse_mode="Markdown",
                reply_markup=back_to_menu_keyboard(),
            )

        elif data == "premium":
            await query.edit_message_text(
                "⭐ *Premium Membership*\n\n"
                "Free: basic menu and education.\n"
                "Premium: signals, analysis, priority support.\n\n"
                "Contact the admin to activate premium after verified payment.",
                parse_mode="Markdown",
                reply_markup=back_to_menu_keyboard(),
            )

        elif data == "contact":
            await query.edit_message_text(
                "📞 *Contact Admin*\n\n"
                "Reach out to the bot administrator for support,\n"
                "premium activation, or partnership inquiries.",
                parse_mode="Markdown",
                reply_markup=back_to_menu_keyboard(),
            )

        elif data == "about":
            await query.edit_message_text(
                "ℹ️ *About*\n\n"
                "Forex Trading Assistant\n"
                "Built with python-telegram-bot.\n"
                "All trading decisions are your responsibility.",
                parse_mode="Markdown",
                reply_markup=back_to_menu_keyboard(),
            )

        elif data == "main":
            await query.edit_message_text(
                "Main Menu:", reply_markup=main_menu_keyboard()
            )

        else:
            await query.edit_message_text(
                "Unknown option.", reply_markup=back_to_menu_keyboard()
            )

    except Exception as e:
        logger.error(f"Button handler error for '{data}': {e}")
        try:
            await query.edit_message_text(
                "⚠️ Something went wrong. Please try again.",
                reply_markup=back_to_menu_keyboard(),
            )
        except Exception:
            pass


# ---------- BACKGROUND JOB ----------
async def signal_check_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodic job. Guard against overlapping runs."""
    if context.bot_data.get("signal_job_running"):
        logger.debug("Signal job already running — skipping this tick.")
        return
    context.bot_data["signal_job_running"] = True
    try:
        logger.info("Signal check job ran")
    except Exception as e:
        logger.error(f"Signal job error: {e}")
    finally:
        context.bot_data["signal_job_running"] = False


# ---------- POST INIT ----------
async def post_init(application: Application) -> None:
    init_db()
    application.job_queue.run_repeating(
        signal_check_job, interval=900, first=10
    )
    logger.info("Bot initialized, database ready, job scheduled")


# ---------- MAIN ----------
def main() -> None:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Starting polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
