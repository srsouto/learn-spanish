"""
One-time setup script. Parses book_index.md and loads sections into the database.
Run this once before starting the bot:
    python setup_db.py
"""
import re
import os
from dotenv import load_dotenv

load_dotenv()

from src.progress_db import init_db, get_connection

BOOK_INDEX_PATH = os.getenv("BOOK_INDEX_PATH", "book_index.md")


def parse_book_index(path: str) -> list[dict]:
    sections = []
    current = None

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") and not line.startswith("##"):
                continue

            chapter_match = re.match(r"^## (\d+): (.+)$", line)
            if chapter_match:
                if current:
                    sections.append(current)
                current = {
                    "chapter": int(chapter_match.group(1)),
                    "title": chapter_match.group(2).strip(),
                    "page_start": None,
                    "page_end": None,
                    "answer_page_start": None,
                    "answer_page_end": None,
                }
                continue

            if current:
                content_match = re.match(r"^- content: (\d+)-(\d+)$", line)
                if content_match:
                    current["page_start"] = int(content_match.group(1))
                    current["page_end"] = int(content_match.group(2))

                answer_match = re.match(r"^- answers: (\d+)-(\d+)$", line)
                if answer_match:
                    current["answer_page_start"] = int(answer_match.group(1))
                    current["answer_page_end"] = int(answer_match.group(2))

    if current:
        sections.append(current)
    return sections


def load_sections(sections: list[dict]):
    with get_connection() as conn:
        existing = conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
        if existing > 0:
            print(f"Database already has {existing} sections. Skipping load.")
            print("To reload, delete data/progress.db and run again.")
            return

        for s in sections:
            conn.execute("""
                INSERT INTO sections
                    (chapter, title, page_start, page_end, answer_page_start, answer_page_end, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                s["chapter"], s["title"],
                s["page_start"], s["page_end"],
                s["answer_page_start"], s["answer_page_end"],
                "not_started"
            ))
        print(f"Loaded {len(sections)} sections into the database.")

    # Set chapter 0 (intro) as the starting section
    from src.progress_db import set_state
    with get_connection() as conn:
        first = conn.execute("SELECT id FROM sections ORDER BY id LIMIT 1").fetchone()
        if first:
            conn.execute(
                "UPDATE sections SET status = 'in_progress' WHERE id = ?", (first["id"],)
            )
            first_id = first["id"]
        else:
            first_id = None

    if first_id:
        set_state("current_section_id", str(first_id))
        print(f"Starting section set to ID {first_id}.")


def main():
    print("Initializing database...")
    init_db()
    print(f"Parsing {BOOK_INDEX_PATH}...")
    sections = parse_book_index(BOOK_INDEX_PATH)
    print(f"Found {len(sections)} sections.")
    load_sections(sections)
    print("Done. Run 'python bot.py' to start.")


if __name__ == "__main__":
    main()
