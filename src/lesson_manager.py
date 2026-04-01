"""
Orchestrates what to teach next and generates lesson/quiz content.
"""
import random
from . import progress_db as db
from . import pdf_reader
from . import llm_client as llm


PAGES_PER_WINDOW = 3
MIN_COMPREHENSION_RATING = 3  # avg rating threshold to advance
FALLBACK_EXCHANGE_LIMIT = 10  # advance anyway after this many exchanges if nothing assessed


def get_section_text(section) -> str:
    """Extract the current page window for this section (3 pages, advances as student progresses)."""
    offset = db.get_section_page_offset(section["id"])
    page_start = section["page_start"] + offset
    page_end = min(section["page_end"], page_start + PAGES_PER_WINDOW - 1)
    return pdf_reader.extract_text(page_start, page_end)


def get_answer_key_text(section) -> str:
    """Extract answer key text for the current section, if available."""
    start = section["answer_page_start"]
    end = section["answer_page_end"]
    if not start or not end:
        return ""
    return pdf_reader.extract_text(start, end)


def current_page_window(section) -> tuple[int, int]:
    """Return (page_start, page_end) of the current window."""
    offset = db.get_section_page_offset(section["id"])
    page_start = section["page_start"] + offset
    page_end = min(section["page_end"], page_start + PAGES_PER_WINDOW - 1)
    return page_start, page_end


def get_weak_topics(limit: int = 3) -> list[str]:
    # Prefer topics that are due for SRS review
    due = db.get_due_topics(limit)
    if due:
        return [row["topic"] for row in due]
    # Fall back to low-rated topics with no review schedule yet
    profile = db.get_profile()
    weak = [row["topic"] for row in profile if row["rating"] <= 2]
    return weak[:limit]


def build_profile_context() -> str:
    """Format student profile as a concise summary for the system prompt."""
    profile = db.get_profile()
    if not profile:
        return ""
    lines = []
    strong = [r for r in profile if r["rating"] >= 4]
    weak = [r for r in profile if r["rating"] <= 2]
    mid = [r for r in profile if r["rating"] == 3]
    if strong:
        lines.append("Strong: " + ", ".join(f"{r['topic']}" for r in strong))
    if mid:
        lines.append("Developing: " + ", ".join(f"{r['topic']}" for r in mid))
    if weak:
        lines.append("Needs work: " + ", ".join(f"{r['topic']} ({r['notes']})" for r in weak if r["notes"]))
    return "\n".join(lines)


def build_lesson_intro() -> str:
    """Text message: intro to the current section."""
    section = db.get_current_section()
    if not section:
        return "You've completed all sections! Ask me to go back to any chapter you'd like to review."
    text = get_section_text(section)
    return llm.generate_lesson_intro(section["title"], text)


def build_quiz_question() -> str:
    """Generate a quiz question from the current section."""
    section = db.get_current_section()
    if not section:
        return "No active section. Use /start to begin!"
    text = get_section_text(section)
    weak = get_weak_topics()
    answer_key = get_answer_key_text(section)
    return llm.generate_quiz_question(text, weak, answer_key=answer_key)


def pick_proactive_action() -> dict:
    """
    Decide what to proactively send. Returns a dict:
      {"type": "text" | "image" | "quiz", "content": ..., "page": ...}

    Priority:
      1. SRS topics due for review → quiz targeting the most overdue topic
      2. Section intro not yet sent → lesson intro
      3. Otherwise → page image for passive reinforcement
    """
    section = db.get_current_section()
    if not section:
        return {"type": "text", "content": "Ready to start? Send /start to begin your Spanish journey!"}

    # Priority 1: send a quiz if any topics are due for review
    due = db.get_due_topics(limit=1)
    if due:
        return {"type": "quiz", "content": build_quiz_question()}

    # Priority 2: send section intro if we haven't yet for this section
    last_intro_section = db.get_state("last_intro_section_id")
    if last_intro_section != str(section["id"]):
        db.set_state("last_intro_section_id", str(section["id"]))
        return {"type": "text", "content": build_lesson_intro()}

    # Priority 3: page image for passive reinforcement
    page = random.randint(section["page_start"], section["page_end"])
    return {"type": "image", "page": page}


def summarize_and_clear_history():
    """Compress current history into the long-term summary, then clear it. Call before section changes."""
    section = db.get_current_section()
    history = db.get_history()
    if history and section:
        existing = db.get_long_term_context()
        updated = llm.summarize_section_learning(section["title"], history, existing)
        db.set_long_term_context(updated)
    db.clear_history()


def handle_user_message(user_text: str) -> str:
    """
    Process a free-text message from the user.
    Adds to history, calls Claude, saves reply, then assesses performance.
    """
    section = db.get_current_section()
    section_context = get_section_text(section) if section else ""
    profile_context = build_profile_context()
    long_term_context = db.get_long_term_context()
    answer_key_context = get_answer_key_text(section) if section else ""

    db.add_message("user", user_text)
    history = db.get_history()

    # Use Sonnet if the user seems to want a detailed explanation
    keywords = ["explain", "why", "how does", "what is", "difference", "grammar"]
    use_sonnet = any(kw in user_text.lower() for kw in keywords)

    reply = llm.chat(history, section_context=section_context, profile_context=profile_context, long_term_context=long_term_context, answer_key_context=answer_key_context, use_sonnet=use_sonnet)
    db.add_message("assistant", reply)
    return reply


def update_profile_from_history():
    """Assess the latest exchange and update student profile. Designed to run in a background thread."""
    history = db.get_history()
    section = db.get_current_section()
    section_id = section["id"] if section else None
    page_offset = db.get_section_page_offset(section_id) if section_id else None
    assessments = llm.assess_performance(history)
    for a in assessments:
        if isinstance(a, dict) and "topic" in a and "rating" in a:
            db.update_topic(a["topic"], int(a["rating"]), a.get("notes", ""), section_id=section_id, page_offset=page_offset)

    # Decide whether to advance the page window
    if section_id:
        offset = db.get_section_page_offset(section_id)
        section_span = section["page_end"] - section["page_start"]
        if offset + PAGES_PER_WINDOW <= section_span:
            comp = db.get_window_comprehension(section_id, offset)
            exchange_count = db.increment_window_interactions(section_id)
            understood = comp["count"] > 0 and comp["avg_rating"] >= MIN_COMPREHENSION_RATING
            fallback = exchange_count >= FALLBACK_EXCHANGE_LIMIT
            if understood or fallback:
                db.advance_section_page(section_id, PAGES_PER_WINDOW)


def progress_summary() -> str:
    """Return a readable summary of the student's progress."""
    sections = db.get_all_sections()
    profile = db.get_profile()
    current = db.get_current_section()

    completed = sum(1 for s in sections if s["status"] == "completed")
    total = len(sections)

    lines = [f"*Progress: {completed}/{total} sections completed*"]

    if current:
        lines.append(f"Currently on: Chapter {current['chapter']} — {current['title']} (p.{current['page_start']}–{current['page_end']})")

    if profile:
        weak = [r for r in profile if r["rating"] <= 2]
        strong = [r for r in profile if r["rating"] >= 4]
        if weak:
            lines.append("\nNeeds work: " + ", ".join(r["topic"] for r in weak))
        if strong:
            lines.append("Strong areas: " + ", ".join(r["topic"] for r in strong))

    return "\n".join(lines)
