"""
Extract text and images from specific pages of the PDF textbook.
Never loads the full PDF into memory — always works with page ranges.
"""
import os
import io
from dotenv import load_dotenv

load_dotenv()

PDF_PATH = os.getenv("PDF_PATH", "Complete-Spanish-Step-By-Step-Book.pdf")


def extract_text(page_start: int, page_end: int) -> str:
    """Extract text from a range of pages (1-indexed)."""
    import pdfplumber

    text_parts = []
    with pdfplumber.open(PDF_PATH) as pdf:
        for page_num in range(page_start - 1, min(page_end, len(pdf.pages))):
            page = pdf.pages[page_num]
            text = page.extract_text()
            if text:
                text_parts.append(f"--- Page {page_num + 1} ---\n{text}")
    return "\n\n".join(text_parts)


def render_page_as_image(page_number: int, dpi: int = 150) -> bytes:
    """
    Render a single PDF page as a JPEG image (bytes).
    page_number is 1-indexed.
    """
    from pdf2image import convert_from_path

    images = convert_from_path(
        PDF_PATH,
        dpi=dpi,
        first_page=page_number,
        last_page=page_number,
        fmt="jpeg",
    )
    if not images:
        raise ValueError(f"Could not render page {page_number}")

    buf = io.BytesIO()
    images[0].save(buf, format="JPEG", quality=85)
    buf.seek(0)
    return buf.read()


def page_count() -> int:
    import pdfplumber
    with pdfplumber.open(PDF_PATH) as pdf:
        return len(pdf.pages)
