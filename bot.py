"""
Main Telegram bot entry point.
Run this continuously — it polls Telegram for messages.

Usage:
    python bot.py
"""
import os
import asyncio
import logging
import urllib.request
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

load_dotenv()


def ensure_sections():
    """Load book index into DB on first boot if no sections exist."""
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from setup_db import parse_book_index, load_sections
    book_index_path = os.getenv("BOOK_INDEX_PATH", "book_index.md")
    sections = parse_book_index(book_index_path)
    load_sections(sections)  # no-ops if sections already exist


def ensure_pdf():
    """Download the textbook PDF from GitHub Releases if it's not on the volume."""
    pdf_path = os.getenv("PDF_PATH", "data/progress.db")
    asset_url = os.getenv("PDF_ASSET_URL")
    github_token = os.getenv("GITHUB_TOKEN")

    if os.path.exists(pdf_path):
        return

    if not asset_url or not github_token:
        log.warning("PDF not found at %s and PDF_ASSET_URL/GITHUB_TOKEN not set — PDF features will fail.", pdf_path)
        return

    log.info("PDF not found, downloading from GitHub Releases...")
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    req = urllib.request.Request(
        asset_url,
        headers={"Authorization": f"Bearer {github_token}", "Accept": "application/octet-stream"},
    )
    with urllib.request.urlopen(req) as resp, open(pdf_path, "wb") as f:
        f.write(resp.read())
    log.info("PDF downloaded to %s", pdf_path)

from src import progress_db as db
from src import lesson_manager as lm
from src import pdf_reader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))


def auth(update: Update) -> bool:
    """Only respond to your own chat."""
    return update.effective_chat.id == ALLOWED_CHAT_ID


# --- Command Handlers ---

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    section = db.get_current_section()
    if not section:
        await update.message.reply_text(
            "Welcome! No sections loaded yet. Ask me to set up the book index first."
        )
        return
    intro = lm.build_lesson_intro()
    await update.message.reply_text(intro, parse_mode=ParseMode.MARKDOWN)


async def cmd_next(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    section = db.advance_section()
    if section:
        db.clear_history()
        intro = lm.build_lesson_intro()
        await update.message.reply_text(f"Moving to Chapter {section['chapter']}: {section['title']}\n\n{intro}", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("You've finished all sections! Great work.")


async def cmd_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    question = lm.build_quiz_question()
    await update.message.reply_text(question, parse_mode=ParseMode.MARKDOWN)


async def cmd_progress(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    summary = lm.progress_summary()
    await update.message.reply_text(summary, parse_mode=ParseMode.MARKDOWN)


async def cmd_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Send a page image. Usage: /page 42"""
    if not auth(update):
        return
    args = ctx.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /page <number>  e.g. /page 42")
        return
    page_num = int(args[0])
    await update.message.reply_text(f"Fetching page {page_num}...")
    try:
        image_bytes = pdf_reader.render_page_as_image(page_num)
        await update.message.reply_photo(photo=image_bytes, caption=f"Page {page_num}")
    except Exception as e:
        await update.message.reply_text(f"Couldn't render page {page_num}: {e}")


async def cmd_goto(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Jump to a section by ID. Usage: /goto 3"""
    if not auth(update):
        return
    args = ctx.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /goto <section_id>  Use /progress to see section IDs.")
        return
    section = db.go_to_section(int(args[0]))
    if section:
        db.clear_history()
        intro = lm.build_lesson_intro()
        await update.message.reply_text(f"Jumped to Chapter {section['chapter']}: {section['title']}\n\n{intro}", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("Section not found.")


async def cmd_more(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Advance the page window within the current section."""
    if not auth(update):
        return
    section = db.get_current_section()
    if not section:
        await update.message.reply_text("No active section. Use /start to begin!")
        return
    offset = db.get_section_page_offset(section["id"])
    section_span = section["page_end"] - section["page_start"]
    if offset + lm.PAGES_PER_WINDOW > section_span:
        await update.message.reply_text(
            "You're at the end of this chapter. Use /next to move on!"
        )
        return
    new_offset = db.advance_section_page(section["id"], lm.PAGES_PER_WINDOW)
    page_start, page_end = lm.current_page_window(section)
    intro = lm.build_lesson_intro()
    await update.message.reply_text(
        f"Moving to pages {page_start}–{page_end} of this chapter.\n\n{intro}",
        parse_mode=ParseMode.MARKDOWN
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    await update.message.reply_text(
        "/start — intro to current section\n"
        "/next — move to next section\n"
        "/more — advance to the next pages within the current section\n"
        "/quiz — get a quiz question\n"
        "/progress — see your progress and strengths/weaknesses\n"
        "/page <n> — send a page image from the book\n"
        "/goto <id> — jump to a section\n\n"
        "Or just send me any message to ask a question or answer a quiz!"
    )


# --- Free-text Handler ---

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    user_text = update.message.text
    reply = lm.handle_user_message(user_text)
    await update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, lm.update_profile_from_history)


# --- Main ---

def main():
    ensure_pdf()
    db.init_db()
    ensure_sections()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("next", cmd_next))
    app.add_handler(CommandHandler("more", cmd_more))
    app.add_handler(CommandHandler("quiz", cmd_quiz))
    app.add_handler(CommandHandler("progress", cmd_progress))
    app.add_handler(CommandHandler("page", cmd_page))
    app.add_handler(CommandHandler("goto", cmd_goto))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    async def set_commands(app):
        await app.bot.set_my_commands([
            ("start",    "Intro to current section"),
            ("quiz",     "Get a quiz question"),
            ("next",     "Advance to the next section"),
            ("more",     "Move to the next pages within this section"),
            ("progress", "View your progress and weak areas"),
            ("page",     "Send a page image — /page 42"),
            ("goto",     "Jump to a section — /goto 3"),
            ("help",     "Show all commands"),
        ])

    app.post_init = set_commands
    log.info("Bot started. Polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
