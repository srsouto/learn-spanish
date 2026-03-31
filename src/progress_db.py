"""
SQLite database for tracking progress, student profile, and conversation history.
"""
import sqlite3
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "data/progress.db")


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter INTEGER NOT NULL,
                title TEXT NOT NULL,
                page_start INTEGER NOT NULL,
                page_end INTEGER NOT NULL,
                answer_page_start INTEGER,
                answer_page_end INTEGER,
                status TEXT NOT NULL DEFAULT 'not_started'
            );

            CREATE TABLE IF NOT EXISTS student_profile (
                topic TEXT PRIMARY KEY,
                rating INTEGER NOT NULL DEFAULT 3,
                notes TEXT,
                last_updated TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversation_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)


# --- Sections ---

def get_current_section():
    with get_connection() as conn:
        section_id = get_state("current_section_id")
        if section_id:
            return conn.execute(
                "SELECT * FROM sections WHERE id = ?", (int(section_id),)
            ).fetchone()
        return conn.execute(
            "SELECT * FROM sections WHERE status = 'not_started' ORDER BY chapter, id LIMIT 1"
        ).fetchone()


def advance_section():
    current = get_current_section()
    if not current:
        return None
    with get_connection() as conn:
        conn.execute(
            "UPDATE sections SET status = 'completed' WHERE id = ?", (current["id"],)
        )
        next_section = conn.execute(
            "SELECT * FROM sections WHERE id > ? ORDER BY id LIMIT 1", (current["id"],)
        ).fetchone()
    if next_section:
        set_state("current_section_id", str(next_section["id"]))
        with get_connection() as conn:
            conn.execute(
                "UPDATE sections SET status = 'in_progress' WHERE id = ?", (next_section["id"],)
            )
    return next_section


def go_to_section(section_id: int):
    with get_connection() as conn:
        section = conn.execute("SELECT * FROM sections WHERE id = ?", (section_id,)).fetchone()
    if section:
        set_state("current_section_id", str(section_id))
        with get_connection() as conn:
            conn.execute(
                "UPDATE sections SET status = 'in_progress' WHERE id = ?", (section_id,)
            )
    return section


def get_all_sections():
    with get_connection() as conn:
        return conn.execute("SELECT * FROM sections ORDER BY chapter, id").fetchall()


# --- Student Profile ---

def update_topic(topic: str, rating: int, notes: str = ""):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO student_profile (topic, rating, notes, last_updated)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(topic) DO UPDATE SET
                rating = excluded.rating,
                notes = excluded.notes,
                last_updated = excluded.last_updated
        """, (topic, rating, notes, datetime.utcnow().isoformat()))


def get_profile():
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM student_profile ORDER BY rating ASC"
        ).fetchall()


# --- Conversation History ---

HISTORY_LIMIT = 10


def add_message(role: str, content: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO conversation_history (role, content, timestamp) VALUES (?, ?, ?)",
            (role, content, datetime.utcnow().isoformat())
        )
        # Trim to last HISTORY_LIMIT messages
        conn.execute("""
            DELETE FROM conversation_history
            WHERE id NOT IN (
                SELECT id FROM conversation_history ORDER BY id DESC LIMIT ?
            )
        """, (HISTORY_LIMIT,))


def get_history():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT role, content FROM conversation_history ORDER BY id ASC"
        ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def clear_history():
    with get_connection() as conn:
        conn.execute("DELETE FROM conversation_history")


# --- App State (key/value) ---

def get_state(key: str):
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_state(key: str, value: str):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO app_state (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
