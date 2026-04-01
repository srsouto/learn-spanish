# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->


## Running the Bot

```bash
# Activate virtualenv
source .venv/bin/activate   # Mac/Linux
# or
.venv/bin/python bot.py     # run directly

# Start the interactive bot (runs continuously)
python bot.py

# Send one proactive lesson/quiz to Telegram (cron target)
python scheduler.py

# Initialize DB from book_index.md (first time only)
python setup_db.py
```

## Architecture Overview

Telegram bot that teaches Spanish via "Complete Spanish Step-by-Step" (PDF, 621 pages).

- `bot.py` — interactive Telegram bot (polling loop)
- `scheduler.py` — cron-triggered proactive sender (lessons, page images, quizzes)
- `src/progress_db.py` — SQLite progress tracking (sections, student profile, conversation history)
- `src/pdf_reader.py` — extracts text and renders page images from PDF on demand
- `src/llm_client.py` — Anthropic API wrapper (Haiku for quizzes, Sonnet for explanations)
- `src/lesson_manager.py` — quiz/lesson orchestration + async student profile assessment
- `book_index.md` — 31 sections mapped with PDF page ranges and answer key page ranges
- `setup_db.py` — parses book_index.md and loads sections into SQLite

## Deployment

- **Cloud:** Railway (https://railway.app), pulls from GitHub repo
- **Volume:** mounted at `/data/` — holds `progress.db` and the PDF
- **PDF:** auto-downloads from GitHub Release asset on startup (env vars: `PDF_ASSET_URL`, `GITHUB_TOKEN`)
- **CI:** GitHub Actions builds versioned Docker image to ghcr.io on every push to main
- **Cron:** Separate Railway service using the same Docker image. Start command: `python scheduler.py`. Type: Cron. Schedule: `0 9,18 * * *` (9am + 6pm UTC). Must share the same `/data` volume and env vars as the bot service. See `railway.toml` for full setup notes.

## Key Environment Variables

```
TELEGRAM_BOT_TOKEN      — from BotFather
TELEGRAM_CHAT_ID        — your Telegram chat ID (run get_chat_id.py to find it)
ANTHROPIC_API_KEY       — from console.anthropic.com
PDF_PATH                — /data/Complete-Spanish-Step-By-Step-Book.pdf (Railway) or local path
DB_PATH                 — /data/progress.db (Railway) or local path
BOOK_INDEX_PATH         — /app/book_index.md (Railway) or local path
PDF_ASSET_URL           — GitHub Release asset API URL for PDF auto-download
GITHUB_TOKEN            — fine-grained PAT with Contents:Read on this repo
```
