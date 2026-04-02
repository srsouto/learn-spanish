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
from datetime import time
from zoneinfo import ZoneInfo
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
    github_token = os.getenv("GH_PAT") or os.getenv("GITHUB_TOKEN")

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
        lm.summarize_and_clear_history()
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
    """Send a page image. Usage: /page [number] — omit number for the current page."""
    if not auth(update):
        return
    args = ctx.args
    if args and args[0].isdigit():
        page_num = int(args[0])
    else:
        section = db.get_current_section()
        if not section:
            await update.message.reply_text("No active section. Use /start to begin!")
            return
        page_num, _ = lm.current_page_window(section)
        # Reset taught state so the proactive loop re-sends the lesson before the next quiz
        offset = db.get_section_page_offset(section["id"])
        db.mark_window_taught(section["id"], offset)
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
        lm.summarize_and_clear_history()
        intro = lm.build_lesson_intro()
        await update.message.reply_text(f"Jumped to Chapter {section['chapter']}: {section['title']}\n\n{intro}", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("Section not found.")


async def cmd_more(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Advance to the next page within the current section."""
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
    if lm.page_has_exercise(section, offset) and not db.is_window_quizzed(section["id"], offset):
        await update.message.reply_text(
            "This page has an exercise — work through it first, then use /more to continue.\n"
            "Use /skip if you want to move on without completing it."
        )
        return
    db.advance_section_page(section["id"], lm.PAGES_PER_WINDOW)
    page_start, _ = lm.current_page_window(section)
    image_bytes = pdf_reader.render_page_as_image(page_start)
    await update.message.reply_photo(photo=image_bytes, caption=f"Page {page_start}")


async def cmd_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Skip the current exercise and advance to the next page."""
    if not auth(update):
        return
    section = db.get_current_section()
    if not section:
        await update.message.reply_text("No active section. Use /start to begin!")
        return
    offset = db.get_section_page_offset(section["id"])
    section_span = section["page_end"] - section["page_start"]
    db.mark_window_quizzed(section["id"], offset)
    if offset + lm.PAGES_PER_WINDOW > section_span:
        await update.message.reply_text("You're at the end of this chapter. Use /next to move on!")
        return
    db.advance_section_page(section["id"], lm.PAGES_PER_WINDOW)
    page_start, _ = lm.current_page_window(section)
    image_bytes = pdf_reader.render_page_as_image(page_start)
    await update.message.reply_photo(photo=image_bytes, caption=f"Page {page_start} (exercise skipped)")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    await update.message.reply_text(
        "/page — show the current page (get back on track)\n"
        "/more — advance to the next page\n"
        "/skip — skip the current exercise and advance\n"
        "/quiz — get a quiz question on the current page\n"
        "/next — move to the next chapter\n"
        "/start — chapter intro\n"
        "/progress — see your progress and strengths/weaknesses\n"
        "/page <n> — send a specific page number\n"
        "/goto <id> — jump to a section\n\n"
        "Or just send me any message to ask a question or answer a quiz!"
    )


# --- Free-text Handler ---

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not auth(update):
        return
    user_text = update.message.text

    # If the page hasn't been shown yet, send it automatically before responding
    section = db.get_current_section()
    if section:
        offset = db.get_section_page_offset(section["id"])
        if not db.is_window_taught(section["id"], offset):
            page_num = section["page_start"] + offset
            try:
                image_bytes = pdf_reader.render_page_as_image(page_num)
                await update.message.reply_photo(photo=image_bytes, caption=f"Page {page_num} — read this, then I'll quiz you!")
                db.mark_window_taught(section["id"], offset)
            except Exception as e:
                log.warning("Couldn't send page image: %s", e)

    reply = lm.handle_user_message(user_text)
    await update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, lm.update_profile_from_history)


# --- Proactive Job ---

async def proactive_job(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled job: send a proactive lesson, quiz, or image if appropriate."""
    action = lm.pick_proactive_action()
    if action["type"] == "skip":
        log.info("Proactive job: skipping (snoozed or last message unacknowledged)")
        return
    if action["type"] == "image":
        page = action["page"]
        log.info(f"Proactive job: sending page image {page}")
        image_bytes = pdf_reader.render_page_as_image(page)
        await context.bot.send_photo(
            chat_id=ALLOWED_CHAT_ID,
            photo=image_bytes,
            caption=f"Here's page {page} from your textbook. Want to discuss it or get quizzed?",
        )
    else:
        log.info(f"Proactive job: sending {action['type']}")
        await context.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=action["content"])
    db.record_proactive_sent()


# --- Main ---

def main():
    ensure_pdf()
    db.init_db()
    ensure_sections()
    app = ApplicationBuilder().token(TOKEN).build()

    # Proactive scheduler: 9am and 6pm Pacific, DST-aware
    pacific = ZoneInfo("America/Los_Angeles")
    app.job_queue.run_daily(proactive_job, time(9, 0, tzinfo=pacific))
    app.job_queue.run_daily(proactive_job, time(16, 30, tzinfo=pacific))  # temp test slot — remove after verifying
    app.job_queue.run_daily(proactive_job, time(18, 0, tzinfo=pacific))

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("next", cmd_next))
    app.add_handler(CommandHandler("more", cmd_more))
    app.add_handler(CommandHandler("skip", cmd_skip))
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
            ("page",     "Show current page (or /page 42 for a specific one)"),
            ("skip",     "Skip the current exercise and advance"),
            ("goto",     "Jump to a section — /goto 3"),
            ("help",     "Show all commands"),
        ])

    app.post_init = set_commands
    log.info("Bot started. Polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
