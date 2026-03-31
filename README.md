# learn-spanish 
A personal Telegram bot for working through *Complete Spanish Step-by-Step* at a sustainable pace.                                                                          

## What it does

- Sends daily lesson excerpts and page images from the textbook
- Quizzes you on current material and checks your answers
- Tracks your progress, strengths, and weak areas in a local database
- Uses Claude Haiku for quick interactions and Claude Sonnet for deeper explanations

## Commands

| Command | Description |
|---|---|
| `/start` | Intro to current section |
| `/quiz` | Get a quiz question |
| `/next` | Advance to the next section |
| `/progress` | View progress and weak areas |
| `/page <n>` | Send a page image from the book |
| `/goto <id>` | Jump to a section |

## Stack

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot)
- [Anthropic API](https://docs.anthropic.com) (Claude)
- pdfplumber + pdf2image for on-demand PDF access
- SQLite for progress tracking
- Docker + GitHub Actions for builds

## Setup

See `.env.example` for required environment variables. Run locally:

```bash
python setup_db.py   # initialize database
python bot.py        # start the bot