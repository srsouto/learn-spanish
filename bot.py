"""
Main Telegram bot entry point.
Run this continuously — it polls Telegram for messages.

Usage:
    python bot.py
"""
import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

load_dotenv()

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
    await update.message.reply_text(intro)


async def cmd_next(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    section = db.advance_section()
    if section:
        db.clear_history()
        intro = lm.build_lesson_intro()
        await update.message.reply_text(f"Moving to Chapter {section['chapter']}: {section['title']}\n\n{intro}")
    else:
        await update.message.reply_text("You've finished all sections! Great work.")


async def cmd_quiz(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    question = lm.build_quiz_question()
    await update.message.reply_text(question)


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
        await update.message.reply_text(f"Jumped to Chapter {section['chapter']}: {section['title']}\n\n{intro}")
    else:
        await update.message.reply_text("Section not found.")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    await update.message.reply_text(
        "/start — intro to current section\n"
        "/next — move to next section\n"
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
    await update.message.reply_text(reply)


# --- Main ---

def main():
    db.init_db()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("next", cmd_next))
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
