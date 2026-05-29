"""
Bus Bot Telegram - EMT Madrid
==============================
Commands:
  /morning       → Stop 784, Line 12 (morning)
  /afternoon     → Stop 793, Line 12 (afternoon)
  /time 793 12   → Custom stop and line
  /start         → Welcome message
  /help          → List commands
"""

import os
import re
import logging
from datetime import datetime
from dotenv import load_dotenv

import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "il_tuo_token_qui")
COMMANDS = {
    "morning":   {"parada": 784, "linea": 12, "label": "🌅 Morning  |  Stop 793"},
    "afternoon": {"parada": 793, "linea": 12, "label": "🌆 Afternoon  |  Stop 784"},
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
}

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s  %(levelname)s  %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── SCRAPING ─────────────────────────────────────────────────────────────────

def get_bus_times(parada: int, linea: int) -> dict:
    url = f"https://cuantoqueda.com/parada/{parada}/linea/{linea}/"
    result = {
        "parada": parada,
        "linea": linea,
        "timestamp": datetime.now().strftime("%H:%M"),
        "stop_name": None,
        "buses": [],
        "error": None,
    }

    try:
        response = requests.get(url, headers=HEADERS, timeout=12)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        result["error"] = "Timeout: the site is not responding. Please try again later."
        return result
    except requests.exceptions.RequestException as e:
        result["error"] = f"Network error: {e}"
        return result

    soup = BeautifulSoup(response.text, "html.parser")

    h1 = soup.find("h1")
    if h1:
        result["stop_name"] = h1.get_text(strip=True)

    for h3 in soup.find_all("h3"):
        text = h3.get_text(strip=True)
        match_min = re.match(r"^(\d+)\s+minuto", text, re.IGNORECASE)
        match_arr = re.match(r"^(llegando|en parada)", text, re.IGNORECASE)

        if match_min or match_arr:
            minutes = int(match_min.group(1)) if match_min else 0
            detail = ""
            next_el = h3.find_next_sibling()
            if next_el and next_el.name == "p":
                detail = next_el.get_text(strip=True)

            bus_num  = re.search(r"#(\d+)", detail)
            distance = re.search(r"([\d,.]+)\s*km", detail)

            result["buses"].append({
                "minutes":     minutes,
                "bus_number":  bus_num.group(1)  if bus_num  else "?",
                "distance_km": distance.group(1) if distance else "?",
            })

    if not result["buses"]:
        result["error"] = "No buses found. The service may be out of hours (06:25–23:58)."

    return result


def format_message(data: dict, label: str) -> str:
    stop = data["stop_name"] or f"Stop {data['parada']}"
    lines = [
        f"*{label}*",
        f"🚌 Line {data['linea']}  •  _{stop}_",
        f"🕐 Updated at {data['timestamp']}",
        "",
    ]

    if data["error"]:
        lines.append(f"⚠️ {data['error']}")
    else:
        for bus in data["buses"]:
            if bus["minutes"] == 0:
                emoji = "🟢"
                time_str = "Arriving / At stop"
            elif bus["minutes"] <= 5:
                emoji = "🟢"
                time_str = f"{bus['minutes']} min"
            elif bus["minutes"] <= 15:
                emoji = "🟡"
                time_str = f"{bus['minutes']} min"
            else:
                emoji = "🔴"
                time_str = f"{bus['minutes']} min"

            lines.append(f"{emoji}  *{time_str}*  —  bus #{bus['bus_number']}  ({bus['distance_km']} km)")

    return "\n".join(lines)


# ─── TELEGRAM HANDLERS ────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Bus Bot EMT Madrid*\n\n"
        "Use these commands to check when your bus arrives:\n\n"
        "🌅 /morning       → Stop 784, Line 12\n"
        "🌆 /afternoon     → Stop 793, Line 12\n"
        "🔍 /time 793 12   → Custom stop and line\n"
        "❓ /help          → Show this message"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


async def cmd_bus(update: Update, context: ContextTypes.DEFAULT_TYPE, command: str):
    cfg = COMMANDS[command]
    msg = await update.message.reply_text("⏳ Fetching real-time data...")
    data = get_bus_times(cfg["parada"], cfg["linea"])
    text = format_message(data, cfg["label"])
    await msg.edit_text(text, parse_mode="Markdown")
    logger.info(f"/{command} → stop {cfg['parada']} | {len(data['buses'])} buses found")


async def cmd_morning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_bus(update, context, "morning")


async def cmd_afternoon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_bus(update, context, "afternoon")


async def cmd_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args

    if len(args) != 2:
        await update.message.reply_text(
            "⚠️ Usage: `/time <stop> <line>`\n"
            "Example: `/time 793 12`",
            parse_mode="Markdown",
        )
        return

    try:
        parada = int(args[0])
        linea  = int(args[1])
    except ValueError:
        await update.message.reply_text(
            "⚠️ Stop and line must be numbers.\n"
            "Example: `/time 793 12`",
            parse_mode="Markdown",
        )
        return

    msg = await update.message.reply_text("⏳ Fetching real-time data...")
    data = get_bus_times(parada, linea)
    label = f"🔍 Stop {parada}  |  Line {linea}"
    text = format_message(data, label)
    await msg.edit_text(text, parse_mode="Markdown")
    logger.info(f"/time → stop {parada} line {linea} | {len(data['buses'])} buses found")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    if BOT_TOKEN == "INSERISCI_QUI_IL_TUO_TOKEN":
        print("❌ Bot token not set!")
        print("   Option 1: edit BOT_TOKEN in this file")
        print("   Option 2: export TELEGRAM_BOT_TOKEN='your_token'")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("morning",   cmd_morning))
    app.add_handler(CommandHandler("afternoon", cmd_afternoon))
    app.add_handler(CommandHandler("time",      cmd_time))

    logger.info("Bot started. Listening...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()