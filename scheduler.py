"""
Proactive lesson sender — run this via cron/Task Scheduler.
Sends one lesson snippet, page image, or quiz question to your Telegram chat.

Usage:
    python scheduler.py

Cron example (9am and 6pm daily):
    0 9,18 * * * /usr/bin/python3 /path/to/scheduler.py
"""
import os
import asyncio
import logging
from dotenv import load_dotenv
from telegram import Bot

load_dotenv()

from src import progress_db as db
from src import lesson_manager as lm
from src import pdf_reader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))


async def send_proactive():
    db.init_db()
    bot = Bot(token=TOKEN)
    action = lm.pick_proactive_action()

    if action["type"] == "image":
        page = action["page"]
        log.info(f"Sending page image: page {page}")
        image_bytes = pdf_reader.render_page_as_image(page)
        await bot.send_photo(
            chat_id=CHAT_ID,
            photo=image_bytes,
            caption=f"Here's page {page} from your textbook. Want to discuss it or get quizzed?"
        )
    else:
        log.info(f"Sending {action['type']} message")
        await bot.send_message(chat_id=CHAT_ID, text=action["content"])


if __name__ == "__main__":
    asyncio.run(send_proactive())
