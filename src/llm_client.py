"""
Anthropic API wrapper.
Routes simple interactions to Haiku (cheap/fast) and rich explanations to Sonnet.
"""
import os
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
    use_sonnet: bool = False,
) -> str:
    """
    Send a conversation to Claude and return the assistant's reply.

    messages: list of {"role": "user"/"assistant", "content": "..."}
    section_context: text extracted from the current textbook section
    use_sonnet: True for rich explanations, False (Haiku) for quiz checking / short replies
    """
    system = SYSTEM_PROMPT
    if section_context:
        system += (
            f"\n\nThe following is the actual extracted text from the student's current textbook section. "
            f"Use it as your primary source for teaching, quizzes, and answering questions. "
            f"Do not pretend you lack access to the material — you have it below.\n\n"
            f"{section_context}"
        )

    model = SONNET if use_sonnet else HAIKU

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


def generate_quiz_question(section_text: str, weak_topics: list[str] = None) -> str:
    """Generate a single quiz question from the current section."""
    focus = ""
    if weak_topics:
        focus = f"Focus on these areas where the student needs practice: {', '.join(weak_topics)}."

    prompt = (
        f"Generate one quiz question based on this textbook section. {focus} "
        f"Ask it naturally, as if in conversation. Do not include the answer.\n\n{section_text[:3000]}"
    )
    response = _client.messages.create(
        model=HAIKU,
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
