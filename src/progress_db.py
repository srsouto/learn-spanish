"""
SQLite database for tracking progress, student profile, and conversation history.
"""
import math
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

            CREATE TABLE IF NOT EXISTS profile_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                rating INTEGER NOT NULL,
                notes TEXT,
                section_id INTEGER,
                page_offset INTEGER,
                timestamp TEXT NOT NULL
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

            CREATE TABLE IF NOT EXISTS missed_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                student_answer TEXT NOT NULL,
                correct_answer TEXT NOT NULL,
                section_id INTEGER,
                timestamp TEXT NOT NULL,
                resolved INTEGER NOT NULL DEFAULT 0,
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_retried_at TEXT
            );
        """)
    _maybe_seed_profile_events()
    _maybe_add_srs_columns()
    _maybe_add_profile_event_columns()


def _maybe_seed_profile_events():
    """One-time migration: seed profile_events from existing student_profile rows."""
    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM profile_events").fetchone()[0]
        if count > 0:
            return
        existing = conn.execute(
            "SELECT topic, rating, notes, last_updated FROM student_profile"
        ).fetchall()
        for row in existing:
            conn.execute(
                "INSERT INTO profile_events (topic, rating, notes, section_id, timestamp) "
                "VALUES (?, ?, ?, NULL, ?)",
                (row["topic"], row["rating"], row["notes"] or "", row["last_updated"])
            )


def _maybe_add_profile_event_columns():
    """Migration: add page_offset to profile_events if it doesn't exist yet."""
    with get_connection() as conn:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(profile_events)").fetchall()}
        if "page_offset" not in existing:
            conn.execute("ALTER TABLE profile_events ADD COLUMN page_offset INTEGER")


def _maybe_add_srs_columns():
    """Migration: add SRS columns to student_profile if they don't exist yet."""
    with get_connection() as conn:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(student_profile)").fetchall()}
        for col, ddl in [
            ("ease_factor",    "ALTER TABLE student_profile ADD COLUMN ease_factor REAL DEFAULT 2.5"),
            ("interval_days",  "ALTER TABLE student_profile ADD COLUMN interval_days REAL DEFAULT 1.0"),
            ("next_review_at", "ALTER TABLE student_profile ADD COLUMN next_review_at TEXT"),
            ("review_count",   "ALTER TABLE student_profile ADD COLUMN review_count INTEGER DEFAULT 0"),
        ]:
            if col not in existing:
                conn.execute(ddl)


def _compute_srs(ease_factor: float, interval_days: float, review_count: int, rating: int) -> tuple:
    """SM-2 inspired SRS update. rating 1-5; returns (ease_factor, interval_days, next_review_at, review_count)."""
    from datetime import timedelta
    if rating <= 2:
        new_interval = 1.0
        new_ease = max(1.3, ease_factor - 0.2)
        new_count = 0
    else:
        if review_count == 0:
            new_interval = 1.0
        elif review_count == 1:
            new_interval = 6.0
        else:
            new_interval = round(interval_days * ease_factor, 1)
        new_ease = max(1.3, ease_factor + (0.1 - (5 - rating) * (0.08 + (5 - rating) * 0.02)))
        new_count = review_count + 1
    next_review = (datetime.utcnow() + timedelta(days=new_interval)).isoformat()
    return new_ease, new_interval, next_review, new_count


_RATING_HALF_LIFE_DAYS = 21.0


def _recompute_topic_rating(conn, topic: str) -> tuple[int, str]:
    """Recency-weighted average rating from event history. Half-life = 21 days."""
    events = conn.execute(
        "SELECT rating, notes, timestamp FROM profile_events "
        "WHERE topic = ? ORDER BY timestamp DESC",
        (topic,)
    ).fetchall()
    if not events:
        return 3, ""
    now = datetime.utcnow()
    total_weight = 0.0
    weighted_sum = 0.0
    for event in events:
        ts = datetime.fromisoformat(event["timestamp"])
        days_ago = (now - ts).total_seconds() / 86400
        weight = math.exp(-days_ago * math.log(2) / _RATING_HALF_LIFE_DAYS)
        weighted_sum += event["rating"] * weight
        total_weight += weight
    computed = round(weighted_sum / total_weight) if total_weight > 0 else 3
    latest_notes = events[0]["notes"] or ""
    return computed, latest_notes


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

def update_topic(topic: str, rating: int, notes: str = "", section_id: int = None, page_offset: int = None):
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO profile_events (topic, rating, notes, section_id, page_offset, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (topic, rating, notes or "", section_id, page_offset, now)
        )
        computed_rating, latest_notes = _recompute_topic_rating(conn, topic)

        # Fetch current SRS state (or defaults for new topics)
        row = conn.execute(
            "SELECT ease_factor, interval_days, review_count FROM student_profile WHERE topic = ?",
            (topic,)
        ).fetchone()
        if row:
            ef, iv, rc = row["ease_factor"] or 2.5, row["interval_days"] or 1.0, row["review_count"] or 0
        else:
            ef, iv, rc = 2.5, 1.0, 0
        new_ef, new_iv, next_review, new_rc = _compute_srs(ef, iv, rc, rating)

        conn.execute("""
            INSERT INTO student_profile (topic, rating, notes, last_updated, ease_factor, interval_days, next_review_at, review_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic) DO UPDATE SET
                rating = excluded.rating,
                notes = excluded.notes,
                last_updated = excluded.last_updated,
                ease_factor = excluded.ease_factor,
                interval_days = excluded.interval_days,
                next_review_at = excluded.next_review_at,
                review_count = excluded.review_count
        """, (topic, computed_rating, notes or latest_notes, now, new_ef, new_iv, next_review, new_rc))


def get_topic_history(topic: str) -> list[dict]:
    """Return all assessment events for a topic, newest first."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT rating, notes, section_id, timestamp FROM profile_events "
            "WHERE topic = ? ORDER BY timestamp DESC",
            (topic,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_window_comprehension(section_id: int, page_offset: int) -> dict:
    """
    Return assessment stats for topics assessed in the current page window.
    {"count": int, "avg_rating": float}  — count=0 means nothing assessed yet.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as count, AVG(rating) as avg_rating "
            "FROM profile_events "
            "WHERE section_id = ? AND page_offset = ?",
            (section_id, page_offset)
        ).fetchone()
    return {"count": row["count"] or 0, "avg_rating": row["avg_rating"] or 0.0}


def get_due_topics(limit: int = 5) -> list[dict]:
    """Topics where next_review_at is past or NULL (never reviewed), ordered by most overdue first."""
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT topic, rating, next_review_at, interval_days FROM student_profile "
            "WHERE next_review_at IS NULL OR next_review_at <= ? "
            "ORDER BY next_review_at ASC "
            "LIMIT ?",
            (now, limit)
        ).fetchall()
    return [dict(row) for row in rows]


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


# --- Missed Questions ---

def save_missed_question(question: str, student_answer: str, correct_answer: str, section_id: int = None):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO missed_questions (question, student_answer, correct_answer, section_id, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (question, student_answer, correct_answer, section_id, datetime.utcnow().isoformat())
        )


def get_due_missed_question() -> dict | None:
    """Return the oldest unresolved missed question, or None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM missed_questions WHERE resolved = 0 "
            "ORDER BY last_retried_at ASC NULLS FIRST, timestamp ASC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def resolve_missed_question(question_id: int):
    with get_connection() as conn:
        conn.execute(
            "UPDATE missed_questions SET resolved = 1 WHERE id = ?", (question_id,)
        )


def record_missed_question_retry(question_id: int):
    with get_connection() as conn:
        conn.execute(
            "UPDATE missed_questions SET retry_count = retry_count + 1, last_retried_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), question_id)
        )


def get_pending_missed_count() -> int:
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM missed_questions WHERE resolved = 0"
        ).fetchone()[0]


# --- Proactive Message Scheduling ---

def record_proactive_sent():
    """Mark that a proactive message was just sent and increment send counter."""
    set_state("last_proactive_sent_at", datetime.utcnow().isoformat())
    count = int(get_state("proactive_send_count") or "0") + 1
    set_state("proactive_send_count", str(count))


def record_user_interaction():
    """Mark that the user just sent a message."""
    set_state("last_user_interaction_at", datetime.utcnow().isoformat())


def proactive_was_acknowledged() -> bool:
    """True if the user responded after the last proactive message was sent."""
    sent = get_state("last_proactive_sent_at")
    interacted = get_state("last_user_interaction_at")
    if not sent:
        return True  # No proactive sent yet — nothing to acknowledge
    if not interacted:
        return False  # Never interacted
    return interacted >= sent


def set_snooze(hours: float = 2.0):
    """Snooze proactive messages for the given number of hours."""
    from datetime import timedelta
    until = (datetime.utcnow() + timedelta(hours=hours)).isoformat()
    set_state("snooze_until", until)


def is_snoozed() -> bool:
    """True if proactive messages are currently snoozed."""
    until = get_state("snooze_until")
    if not until:
        return False
    return datetime.utcnow().isoformat() < until


# --- Long-term Context ---

def get_long_term_context() -> str:
    return get_state("long_term_context") or ""


def set_long_term_context(summary: str):
    set_state("long_term_context", summary)


# --- Page Window (progressive section traversal) ---

def get_section_page_offset(section_id: int) -> int:
    val = get_state(f"section_{section_id}_page_offset")
    return int(val) if val else 0


def advance_section_page(section_id: int, window_size: int = 3) -> int:
    """Advance the page window by window_size. Resets interaction counter. Returns new offset."""
    new_offset = get_section_page_offset(section_id) + window_size
    set_state(f"section_{section_id}_page_offset", str(new_offset))
    set_state(f"section_{section_id}_window_interactions", "0")
    return new_offset


def increment_window_interactions(section_id: int) -> int:
    """Increment assessed-interaction count for the current page window. Returns new count."""
    key = f"section_{section_id}_window_interactions"
    count = int(get_state(key) or "0") + 1
    set_state(key, str(count))
    return count
