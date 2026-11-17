import re
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile

from bs4 import BeautifulSoup
from docx import Document as DocxDocument
from docx.opc.exceptions import PackageNotFoundError
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from anki_flashcards.errors import FlashcardError

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".html", ".htm", ".md", ".markdown", ".txt"}
MAX_FILE_SIZE = 100 * 1024 * 1024


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    text: str


def read_document(path: Path) -> SourceDocument:
    try:
        if path.stat().st_size > MAX_FILE_SIZE:
            raise FlashcardError(f"Input file exceeds the 100 MiB limit: {path}")
        suffix = path.suffix.casefold()
        if suffix not in SUPPORTED_SUFFIXES:
            supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
            raise FlashcardError(f"Unsupported file type '{suffix}'. Supported types: {supported}")

        if suffix == ".pdf":
            text = _read_pdf(path)
        elif suffix == ".docx":
            text = _read_docx(path)
        elif suffix in {".html", ".htm"}:
            text = _html_to_text(path.read_text(encoding="utf-8"))
        else:
            text = path.read_text(encoding="utf-8-sig")
    except FlashcardError:
        raise
    except (
        OSError,
        UnicodeError,
        ValueError,
        PyPdfError,
        PackageNotFoundError,
        BadZipFile,
    ) as error:
        raise FlashcardError(f"Could not read {path}: {error}") from error

    text = _normalize_text(text)
    if not text:
        raise FlashcardError(f"No extractable text found in {path}")
    return SourceDocument(path=path, text=text)


def _read_pdf(path: Path) -> str:
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except NotImplementedError as error:
            raise FlashcardError(f"Encrypted PDF is not supported: {path}") from error
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        if page_text.strip():
            pages.append(f"[Seite {number}]\n{page_text}")
    return "\n\n".join(pages)


def _read_docx(path: Path) -> str:
    document = DocxDocument(path)
    blocks = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            blocks.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(blocks)


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript", "template"]):
        element.decompose()
    return soup.get_text("\n")


def _normalize_text(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def chunk_text(text: str, max_chars: int = 24_000, overlap: int = 500) -> list[str]:
    if max_chars < 1_000:
        raise ValueError("Chunk size must be at least 1000 characters")
    if overlap < 0 or overlap >= max_chars // 2:
        raise ValueError("Overlap must be non-negative and less than half the chunk size")
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            boundary = text.rfind("\n\n", start + max_chars // 2, end)
            if boundary == -1:
                boundary = text.rfind(" ", start + max_chars // 2, end)
            if boundary != -1:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks
