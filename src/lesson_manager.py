"""
Orchestrates what to teach next and generates lesson/quiz content.
"""
import random
from . import progress_db as db
from . import pdf_reader
from . import llm_client as llm


PAGES_PER_WINDOW = 1
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



def get_lesson_step() -> str:
    """
    Return the current step in the page→quiz→chat cycle:
      'show_page'    — page not yet shown to the student
      'quiz_pending' — page shown, no quiz given yet
      'free_chat'    — quiz done, student can chat freely about the material
    """
    section = db.get_current_section()
    if not section:
        return "free_chat"
    offset = db.get_section_page_offset(section["id"])
    if not db.is_window_taught(section["id"], offset):
        return "show_page"
    if not db.is_window_quizzed(section["id"], offset):
        return "quiz_pending"
    return "free_chat"


def build_quiz_question() -> str:
    """Generate a quiz question from the current section and mark the window as quizzed."""
    section = db.get_current_section()
    if not section:
        return "No active section. Use /start to begin!"
    text = get_section_text(section)
    weak = get_weak_topics()
    answer_key = get_answer_key_text(section)
    offset = db.get_section_page_offset(section["id"])
    db.mark_window_quizzed(section["id"], offset)
    return llm.generate_quiz_question(text, weak, answer_key=answer_key)


_SNOOZE_PHRASES = {
    "later", "not now", "busy", "snooze", "stop", "not today",
    "maybe later", "not right now", "leave me alone", "pause",
}


def pick_proactive_action() -> dict:
    """
    Decide what to proactively send. Returns a dict:
      {"type": "text" | "image" | "quiz", "content": ..., "page": ...}
      {"type": "skip"} if snoozed or last message unacknowledged.

    Priority:
      1. Snoozed or unacknowledged → skip
      2. Missed question retry (every 3rd send)
      3. Section intro (once per section)
      4. Window vocab/grammar lesson (once per page window, always before quiz)
      5. SRS review quiz if topics are overdue
      6. Quiz on current window material
    """
    if db.is_snoozed():
        return {"type": "skip"}
    if not db.proactive_was_acknowledged():
        return {"type": "skip"}

    section = db.get_current_section()
    if not section:
        return {"type": "text", "content": "Ready to start? Send /start to begin your Spanish journey!"}

    # Priority 1: retry a previously missed question (every 3rd proactive send)
    send_count = int(db.get_state("proactive_send_count") or "0")
    if send_count % 3 == 2:
        missed = db.get_due_missed_question()
        if missed:
            db.record_missed_question_retry(missed["id"])
            db.set_state("pending_retry_id", str(missed["id"]))
            return {
                "type": "retry",
                "content": f"Let's try this one again:\n\n{missed['question']}",
                "missed_id": missed["id"],
            }

    # Priority 2: send section intro if we haven't yet for this section
    last_intro_section = db.get_state("last_intro_section_id")
    if last_intro_section != str(section["id"]):
        db.set_state("last_intro_section_id", str(section["id"]))
        return {"type": "text", "content": build_lesson_intro()}

    # Priority 3: show the actual PDF page before quizzing on it
    offset = db.get_section_page_offset(section["id"])
    current_page = section["page_start"] + offset
    if not db.is_window_taught(section["id"], offset):
        db.mark_window_taught(section["id"], offset)
        return {"type": "image", "page": current_page}

    # Priority 4: SRS review quiz if topics are due
    due = db.get_due_topics(limit=1)
    if due:
        return {"type": "quiz", "content": build_quiz_question()}

    # Priority 5: quiz on current window material
    return {"type": "quiz", "content": build_quiz_question()}


def _check_retry_answer(question_id: int, user_text: str) -> str | None:
    """
    Check if user_text correctly answers a pending missed question.
    Resolves it if correct. Returns a response string, or None to fall through to normal chat.
    """
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT question, correct_answer FROM missed_questions WHERE id = ?", (question_id,)
        ).fetchone()
    if not row:
        return None

    verdict = llm.check_retry_answer(row["question"], row["correct_answer"], user_text)
    if verdict.get("correct"):
        db.resolve_missed_question(question_id)
        pending = db.get_pending_missed_count()
        praise = verdict.get("feedback", "Correct!")
        suffix = f" {pending} question{'s' if pending != 1 else ''} still to retry." if pending else " All caught up!"
        return f"{praise}{suffix}"
    else:
        feedback = verdict.get("feedback", f"Not quite — the correct answer is: {row['correct_answer']}")
        return feedback


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
    db.record_user_interaction()

    # Snooze proactive messages if the user signals they're busy
    if any(phrase in user_text.lower() for phrase in _SNOOZE_PHRASES):
        db.set_snooze(hours=2.0)
        return "No problem! I'll leave you alone for a couple of hours. Send me a message whenever you're ready."

    # If there's a pending retry question, check whether this message answers it correctly
    pending_retry_id = db.get_state("pending_retry_id")
    if pending_retry_id:
        db.set_state("pending_retry_id", "")
        missed = _check_retry_answer(int(pending_retry_id), user_text)
        if missed:
            return missed

    section = db.get_current_section()
    section_context = get_section_text(section) if section else ""
    profile_context = build_profile_context()
    long_term_context = db.get_long_term_context()
    answer_key_context = get_answer_key_text(section) if section else ""
    step = get_lesson_step()

    # If we're in quiz_pending during a chat, mark it quizzed — Claude will quiz them now
    if step == "quiz_pending" and section:
        offset = db.get_section_page_offset(section["id"])
        db.mark_window_quizzed(section["id"], offset)

    db.add_message("user", user_text)
    history = db.get_history()

    reply = llm.chat(
        history,
        section_context=section_context,
        profile_context=profile_context,
        long_term_context=long_term_context,
        answer_key_context=answer_key_context,
        lesson_step=step,
    )
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

    # Save any questions the student got wrong
    missed = llm.extract_missed_questions(history)
    for m in missed:
        if isinstance(m, dict) and "question" in m and "correct_answer" in m:
            db.save_missed_question(
                m["question"], m.get("student_answer", ""), m["correct_answer"],
                section_id=section_id
            )

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
