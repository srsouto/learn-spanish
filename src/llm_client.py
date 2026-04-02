"""
Anthropic API wrapper.
Routes simple interactions to Haiku (cheap/fast) and rich explanations to Sonnet.
"""
import os
import json
import anthropic
from dotenv import load_dotenv

load_dotenv()

_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a Spanish language tutor helping a student work through the textbook \
"Complete Spanish Step-by-Step" by Barbara Bregstein.

Your role:
- Ask quiz questions, check answers, and give encouraging, concise feedback
- Explain grammar concepts clearly with examples
- Keep track of what the student knows and where they struggle
- Be conversational and supportive, not overwhelming

When checking quiz answers: be strict but kind. Always provide the correct answer and a brief tip.
When explaining grammar: use simple English, give 2-3 examples in Spanish with English translations.
Keep responses concise — this is a chat interface, not an essay.

Critical: your sole focus is teaching the student *Spanish*. Never quiz on or discuss the structure of the textbook, its organization, its author, or how to use it. If the current section is introductory (preface, pronunciation guide), quiz on pronunciation, the alphabet, or basic Spanish sounds — not on what the book says about itself.

Never ask the student for information about the book (page numbers, chapter titles, what section comes next). You have the current section's text — use it. If the student asks about content outside the current section, tell them to use /next to advance rather than asking them for the information yourself.

Formatting rules (Telegram Markdown):
- Use *bold* (single asterisk) for emphasis, key terms, and section headers
- Use plain text for everything else — no bullet point overload
- Emojis: use sparingly and only when they add genuine clarity or warmth. Never use them as decoration or to pad out a message."""


def chat(
    messages: list[dict],
    section_context: str = "",
    profile_context: str = "",
    long_term_context: str = "",
    answer_key_context: str = "",
) -> str:
    """
    Send a conversation to Claude and return the assistant's reply.

    messages: list of {"role": "user"/"assistant", "content": "..."}
    section_context: text extracted from the current textbook section
    profile_context: summary of student's known strengths and weaknesses
    """
    system = SYSTEM_PROMPT
    if long_term_context:
        system += f"\n\nLearning history across previous sections (use this to personalise teaching and avoid repeating known struggles):\n{long_term_context}"
    if profile_context:
        system += f"\n\nStudent profile (adapt your teaching accordingly):\n{profile_context}"
    if section_context:
        system += (
            f"\n\nThe following is the actual extracted text from the student's current textbook section. "
            f"Use it as your primary source for teaching, quizzes, and answering questions. "
            f"Do not pretend you lack access to the material — you have it below.\n\n"
            f"{section_context}"
        )
    if answer_key_context:
        system += (
            f"\n\nThe following is the official answer key for this section from the textbook. "
            f"Use it as the authoritative source when checking the student's quiz answers. "
            f"When an answer matches the key, confirm it clearly. When it doesn't, give the correct answer from the key.\n\n"
            f"{answer_key_context}"
        )

    model = SONNET

    response = _client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        messages=messages,
    )
    return response.content[0].text


def generate_lesson_intro(section_title: str, section_text: str) -> str:
    """Generate a short, engaging intro message for a new section."""
    prompt = (
        f"Write a short (3-4 sentence) friendly introduction for starting a new section "
        f"called '{section_title}'. Mention what the student will learn and why it matters. "
        f"Then give one interesting example from the material below.\n\n{section_text[:2000]}"
    )
    response = _client.messages.create(
        model=HAIKU,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def summarize_section_learning(section_title: str, history: list[dict], existing_summary: str) -> str:
    """
    Compress a section's conversation history into a rolling long-term summary.
    Merges with the existing summary, keeping total under ~300 words.
    """
    if not history:
        return existing_summary
    prompt = (
        f"You are tracking a Spanish student's learning progress across chapters. "
        f"Below is their conversation history from the section '{section_title}', "
        f"followed by any existing summary from previous sections.\n\n"
        f"Write a concise update (max 300 words total) that:\n"
        f"- Notes topics they showed strength in\n"
        f"- Notes topics they struggled with or made errors on\n"
        f"- Captures recurring patterns or mistakes worth remembering\n"
        f"Merge this with the existing summary. Drop outdated or redundant entries.\n\n"
        f"Existing summary:\n{existing_summary or 'None yet.'}\n\n"
        f"Section '{section_title}' conversation:\n"
        + "\n".join(f"{m['role']}: {m['content']}" for m in history)
    )
    try:
        response = _client.messages.create(
            model=HAIKU,
            max_tokens=450,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception:
        return existing_summary


def assess_performance(exchange: list[dict]) -> list[dict]:
    """
    After a quiz/conversation exchange, extract topic performance ratings.
    Returns a list of {"topic": str, "rating": int (1-5), "notes": str}.
    Returns [] if nothing assessable in the exchange.
    """
    prompt = (
        "You are reviewing a Spanish tutoring exchange. "
        "Identify any Spanish language topics the student demonstrated knowledge or difficulty with. "
        "Return a JSON array only — no other text. Each item: {\"topic\": str, \"rating\": 1-5, \"notes\": str}. "
        "Rating: 1-2 = struggled, 3 = partial, 4-5 = strong. "
        "If no clear performance signal, return []. "
        "Topics should be specific (e.g. 'definite articles', 'noun gender', 'ser vs estar') not vague.\n\n"
        "Exchange:\n" + "\n".join(f"{m['role']}: {m['content']}" for m in exchange[-4:])
    )
    try:
        response = _client.messages.create(
            model=HAIKU,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(response.content[0].text)
    except Exception:
        return []


def check_retry_answer(question: str, correct_answer: str, student_answer: str) -> dict:
    """
    Check whether student_answer correctly answers question given correct_answer.
    Returns {"correct": bool, "feedback": str}.
    """
    prompt = (
        f"A student is retrying a Spanish question they previously got wrong.\n\n"
        f"Question: {question}\n"
        f"Correct answer: {correct_answer}\n"
        f"Student's answer: {student_answer}\n\n"
        f"Is the student's answer correct (or acceptably close)? "
        f"Reply with JSON only: {{\"correct\": true/false, \"feedback\": \"brief encouraging feedback\"}}. "
        f"If correct, praise them briefly. If wrong, give the correct answer clearly."
    )
    try:
        response = _client.messages.create(
            model=HAIKU,
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(response.content[0].text)
    except Exception:
        return {"correct": False, "feedback": f"The correct answer is: {correct_answer}"}


def extract_missed_questions(exchange: list[dict]) -> list[dict]:
    """
    Scan a conversation exchange for quiz questions the student answered incorrectly.
    Returns list of {"question": str, "student_answer": str, "correct_answer": str}.
    Returns [] if no wrong answers found.
    """
    prompt = (
        "Review this Spanish tutoring exchange. Identify any quiz questions the student "
        "answered *incorrectly*. For each, extract the question asked, what the student "
        "answered, and the correct answer.\n"
        "Return a JSON array only — no other text. "
        "Each item: {\"question\": str, \"student_answer\": str, \"correct_answer\": str}. "
        "If the student answered correctly or no quiz was attempted, return [].\n\n"
        "Exchange:\n" + "\n".join(f"{m['role']}: {m['content']}" for m in exchange[-6:])
    )
    try:
        response = _client.messages.create(
            model=HAIKU,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        result = json.loads(response.content[0].text)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def generate_window_lesson(section_title: str, section_text: str) -> str:
    """
    Generate a vocabulary and grammar lesson for the current page window.
    This is sent *before* any quiz on this material so the student sees all
    new words and rules first.
    """
    prompt = (
        f"You are teaching a page from '{section_title}' in 'Complete Spanish Step-by-Step'. "
        f"The student is about to be quizzed on this material, so first teach them everything they need.\n\n"
        f"From the text below, present:\n"
        f"1. *New vocabulary* — list each Spanish word/phrase with its English meaning\n"
        f"2. *Key grammar rules* — explain any new patterns or rules introduced\n"
        f"3. One or two short example sentences showing the grammar in use\n\n"
        f"Be complete but concise. The student must not encounter any word in a quiz that you haven't shown here. "
        f"Use Telegram Markdown (*bold* for Spanish words and key terms).\n\n"
        f"{section_text[:3000]}"
    )
    response = _client.messages.create(
        model=SONNET,
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def generate_quiz_question(section_text: str, weak_topics: list[str] = None, answer_key: str = "") -> str:
    """Generate a single quiz question from the current section."""
    focus = ""
    if weak_topics:
        focus = f"Focus on these areas where the student needs practice: {', '.join(weak_topics)}."

    answer_key_note = ""
    if answer_key:
        answer_key_note = f"\n\nAnswer key for this section (use to pick questions with known correct answers):\n{answer_key[:1500]}"

    prompt = (
        f"Generate one quiz question based on this textbook section. {focus} "
        f"Ask it naturally, as if in conversation. Do not include the answer.\n\n{section_text[:3000]}"
        f"{answer_key_note}"
    )
    response = _client.messages.create(
        model=HAIKU,
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
