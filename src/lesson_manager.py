"""
Orchestrates what to teach next and generates lesson/quiz content.
"""
import random
from . import progress_db as db
from . import pdf_reader
from . import llm_client as llm


def get_section_text(section) -> str:
    """Extract text for the current section (capped at 3 pages to control tokens)."""
    page_start = section["page_start"]
    page_end = min(section["page_end"], page_start + 2)  # max 3 pages at a time
    return pdf_reader.extract_text(page_start, page_end)


def get_weak_topics(limit: int = 3) -> list[str]:
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
    return llm.generate_quiz_question(text, weak)


def pick_proactive_action() -> dict:
    """
    Decide what to proactively send. Returns a dict:
      {"type": "text" | "image" | "quiz", "content": ..., "page": ...}
    """
    section = db.get_current_section()
    if not section:
        return {"type": "text", "content": "Ready to start? Send /start to begin your Spanish journey!"}

    last_action = db.get_state("last_proactive_action") or "quiz"

    # Rotate: intro → image → quiz → intro ...
    if last_action == "quiz":
        next_action = "intro"
    elif last_action == "intro":
        next_action = "image"
    else:
        next_action = "quiz"

    db.set_state("last_proactive_action", next_action)

    if next_action == "intro":
        return {"type": "text", "content": build_lesson_intro()}

    elif next_action == "image":
        # Pick a random page from the current section
        page = random.randint(section["page_start"], section["page_end"])
        return {"type": "image", "page": page}

    else:
        return {"type": "quiz", "content": build_quiz_question()}


def handle_user_message(user_text: str) -> str:
    """
    Process a free-text message from the user.
    Adds to history, calls Claude, saves reply, then assesses performance.
    """
    section = db.get_current_section()
    section_context = get_section_text(section) if section else ""
    profile_context = build_profile_context()

    db.add_message("user", user_text)
    history = db.get_history()

    # Use Sonnet if the user seems to want a detailed explanation
    keywords = ["explain", "why", "how does", "what is", "difference", "grammar"]
    use_sonnet = any(kw in user_text.lower() for kw in keywords)

    reply = llm.chat(history, section_context=section_context, profile_context=profile_context, use_sonnet=use_sonnet)
    db.add_message("assistant", reply)
    return reply


def update_profile_from_history():
    """Assess the latest exchange and update student profile. Designed to run in a background thread."""
    history = db.get_history()
    assessments = llm.assess_performance(history)
    for a in assessments:
        if isinstance(a, dict) and "topic" in a and "rating" in a:
            db.update_topic(a["topic"], int(a["rating"]), a.get("notes", ""))


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
