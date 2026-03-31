# Spanish Learning Telegram Bot — Plan

## Context

Build a personal Spanish learning assistant that works through "Complete Spanish Step-by-Step" (621 pages, PDF) via Telegram. The bot proactively sends lessons and quizzes on a schedule AND responds to on-demand messages. Runs locally first (Mac or Windows), architected to be trivially portable to the cloud.

---

## Architecture

```
learn-spanish-bot/
├── .env.example          # Template for secrets
├── .env                  # Gitignored — actual secrets
├── requirements.txt
├── Dockerfile            # For cloud migration
├── bot.py                # Entry point: runs Telegram polling loop
├── scheduler.py          # Entry point: cron calls this to send proactive lessons
└── src/
    ├── pdf_reader.py     # Page text extraction + page-as-image rendering
    ├── progress_db.py    # SQLite: progress, strengths/weaknesses, history
    ├── llm_client.py     # Anthropic API calls (Haiku vs Sonnet routing)
    └── lesson_manager.py # Logic: what to teach next, quiz generation
data/
    └── progress.db       # Gitignored — single-file database
```

**Portability principle:** All secrets in `.env`, all state in `data/progress.db`. To move to cloud: copy `.env` + `progress.db`, deploy container, point cron at cloud scheduler — no code changes.

---

## Key Libraries

| Library | Purpose |
|---|---|
| `python-telegram-bot` | Telegram bot (polling locally, webhook-ready for cloud) |
| `pdfplumber` | Extract text from specific page ranges (never full book) |
| `pdf2image` + `poppler` | Render PDF pages as images to send via Telegram |
| `anthropic` | Claude API (Haiku for quiz-checking, Sonnet for explanations) |
| `python-dotenv` | Load `.env` config |
| `sqlite3` | Built-in Python — no extra install needed |

---

## Database Schema (SQLite)

**`sections`** — maps the book structure
- `id`, `chapter`, `title`, `page_start`, `page_end`, `answer_page_start`, `answer_page_end`, `status` (not_started/in_progress/completed)

**`student_profile`** — strengths and weak areas
- `topic`, `rating` (1–5), `notes`, `last_updated`

**`conversation_history`** — rolling window for LLM context
- `id`, `role`, `content`, `timestamp` — keep last 10 turns only

---

## Two Entry Points

### 1. `bot.py` — Interactive (always running)
Telegram polling loop. Handles:
- `/start` — intro and current position in book
- `/next` — advance to next section
- `/quiz` — generate a quiz from current section
- `/explain <topic>` — ask for an explanation
- `/progress` — show strengths/weak areas summary
- `/goto <chapter>` — jump to a specific chapter
- Any free-text message → treated as a question or quiz answer

### 2. `scheduler.py` — Proactive (cron-triggered)
Run by cron/Task Scheduler. Sends one of:
- A text excerpt from the current section
- A page image from the textbook
- An unprompted quiz question
- A "you haven't practiced in X days" nudge

---

## LLM Cost Strategy

- **Haiku** for: checking quiz answers, short Q&A, nudge messages
- **Sonnet** for: generating rich lesson summaries, explaining grammar
- Context: current section text (1–3 pages) + last 10 conversation turns only
- Never pass the full PDF — extract pages on demand only

Estimated cost: < $1/month for daily use.

---

## Cron Setup

**Mac:** `crontab -e`
```
0 9  * * * /usr/bin/python3 /path/to/scheduler.py
0 18 * * * /usr/bin/python3 /path/to/scheduler.py
```

**Windows:** Task Scheduler pointing to `python scheduler.py`

**Cloud (later):** Cloud Run Job or ECS Scheduled Task on the same schedule — no code changes needed.

---

## Phase 1 Setup Task: Book Index

Before tracking progress, create `book_index.md` manually from the table of contents:
- Chapter name, page start/end, answer page range

The bot uses this to know what to teach and where the answers live.

---

## Implementation Order

1. Repo setup: `requirements.txt`, `.env.example`, install deps (poppler via brew/choco)
2. `progress_db.py` — SQLite setup and CRUD helpers
3. `pdf_reader.py` — extract page text + render page as image
4. `llm_client.py` — Anthropic wrapper with Haiku/Sonnet routing
5. `lesson_manager.py` — determine current section, generate quiz/lesson prompts
6. `bot.py` — wire up Telegram commands and free-text handler
7. `scheduler.py` — proactive message logic
8. `book_index.md` — populate chapter/page map from table of contents
9. `Dockerfile` — for cloud portability

---

## Status (as of 2026-03-31)

**Completed:**
- Full project scaffolded and committed to https://github.com/srsouto/learn-spanish (private)
- All dependencies installed in `.venv/` (anthropic, python-telegram-bot, pdfplumber, pdf2image, poppler)
- SQLite database initialized with all 31 sections from `book_index.md`
- Bot tested and working — `/start`, `/quiz`, `/page <n>`, free-text all confirmed working
- Telegram bot token and chat ID configured in `.env`

**Not yet done:**
- Cron job setup (for proactive scheduled messages via `scheduler.py`)
- Cloud deployment (Dockerfile is ready, just needs a host — Railway/Render recommended)
- Fine-tuning of answer key page ranges in `book_index.md` (rough estimates used, could be tightened)
- Student profile / weakness tracking not yet exercised (code is there, just needs use)

**To resume:**
1. `cd /Users/steven/Documents/learn-spanish`
2. `.venv/bin/python bot.py` — starts the bot
3. `.venv/bin/python scheduler.py` — test a proactive message manually

## Verification

- Run `bot.py` locally, message the bot, confirm it responds
- Run `scheduler.py` directly, confirm a message appears in Telegram
- Check `progress.db` reflects updated state after interactions
- Confirm a page image renders and sends correctly via Telegram
- Confirm `.env` swap is all that's needed to move environments
