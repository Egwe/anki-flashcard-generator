"""Extract local document text and split it into model-sized chunks."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
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
    """Hold normalized text extracted from one local document.

    Attributes:
        path: Local source file path.
        text: Non-empty normalized text passed to the AI generator.
    """

    path: Path
    text: str


def read_document(path: Path) -> SourceDocument:
    """Read a supported local file and return normalized, non-empty text.

    Args:
        path: Local PDF, DOCX, HTML, Markdown, or text file of at most 100 MiB.

    Returns:
        A source document containing the extracted text and original path.

    Raises:
        FlashcardError: If the file is unsupported, too large, unreadable,
            damaged, encrypted without support, or contains no extractable text.
    """
    _validate_document_path(path)
    text = _extract_text(path)
    normalized_text = _normalize_text(text)
    if not normalized_text:
        raise FlashcardError(f"No extractable text found in {path}")
    return SourceDocument(path=path, text=normalized_text)


def _validate_document_path(path: Path) -> None:
    """Validate the local input's size and supported suffix before extraction.

    Args:
        path: Candidate local input file.

    Returns:
        None when the file is small enough and has a supported suffix.

    Raises:
        FlashcardError: If the path cannot be inspected, exceeds 100 MiB, or
            has an unsupported suffix.
    """
    try:
        file_size = path.stat().st_size
    except OSError as error:
        raise FlashcardError(f"Could not read {path}: {error}") from error
    if file_size > MAX_FILE_SIZE:
        raise FlashcardError(f"Input file exceeds the 100 MiB limit: {path}")
    suffix = path.suffix.casefold()
    if suffix in SUPPORTED_SUFFIXES:
        return
    supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
    raise FlashcardError(f"Unsupported file type '{suffix}'. Supported types: {supported}")


def _extract_text(path: Path) -> str:
    """Dispatch file extraction and normalize library failures at the boundary.

    Args:
        path: Previously validated local document path.

    Returns:
        Raw extracted text before whitespace normalization.

    Raises:
        FlashcardError: If file reading or a document parser fails.
    """
    try:
        return _extract_supported_text(path)
    except (
        OSError,
        UnicodeError,
        ValueError,
        PyPdfError,
        PackageNotFoundError,
        BadZipFile,
    ) as error:
        raise FlashcardError(f"Could not read {path}: {error}") from error


def _extract_supported_text(path: Path) -> str:
    """Select the extractor appropriate for a supported document suffix.

    Args:
        path: Local document with a suffix listed in SUPPORTED_SUFFIXES.

    Returns:
        Raw document text without normalized whitespace.
    """
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix == ".docx":
        return _read_docx(path)
    if suffix in {".html", ".htm"}:
        return _html_to_text(path.read_text(encoding="utf-8"))
    return path.read_text(encoding="utf-8-sig")


def _read_pdf(path: Path) -> str:
    """Extract text from PDF pages and retain page markers.

    Args:
        path: Local PDF file.

    Returns:
        Page text joined in document order; pages without text are omitted.

    Raises:
        FlashcardError: If encrypted content cannot be decrypted with an empty
            password or a PDF page cannot be extracted.
    """
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except NotImplementedError as error:
            raise FlashcardError(f"Encrypted PDF is not supported: {path}") from error
    pages = [_extract_pdf_page(number, page) for number, page in enumerate(reader.pages, 1)]
    return "\n\n".join(page for page in pages if page)


def _extract_pdf_page(number: int, page: Any) -> str:
    """Extract one PDF page and prefix non-empty content with its page number.

    Args:
        number: One-based page number used in the source marker.
        page: PDF page object supplied by pypdf.

    Returns:
        The marked page text or an empty string for a page without text.
    """
    page_text = page.extract_text() or ""
    if not page_text.strip():
        return ""
    return f"[Seite {number}]\n{page_text}"


def _read_docx(path: Path) -> str:
    """Extract DOCX paragraphs and table rows in a plain-text representation.

    Args:
        path: Local DOCX file.

    Returns:
        Paragraphs followed by table rows, with cells separated by pipes.
    """
    document = DocxDocument(path)
    blocks = [paragraph.text for paragraph in document.paragraphs]
    rows = (row for table in document.tables for row in table.rows)
    blocks.extend(" | ".join(cell.text for cell in row.cells) for row in rows)
    return "\n".join(blocks)


def _html_to_text(html: str) -> str:
    """Convert HTML to visible text and discard executable or styling content.

    Args:
        html: Raw HTML document.

    Returns:
        Text nodes separated by newlines without scripts, styles, or templates.
    """
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript", "template"]):
        element.decompose()
    return soup.get_text("\n")


def _normalize_text(text: str) -> str:
    """Normalize whitespace while preserving meaningful paragraph breaks.

    Args:
        text: Arbitrary extracted text.

    Returns:
        Trimmed text with aligned indentation and at most one blank line.
    """
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def chunk_text(text: str, max_chars: int = 24_000, overlap: int = 500) -> list[str]:
    """Split text into overlapping chunks for model requests.

    Args:
        text: Normalized source text to cover completely.
        max_chars: Maximum characters per chunk; at least 1,000.
        overlap: Repeated characters between adjacent chunks, less than half
            the chunk size.

    Returns:
        Non-empty chunks covering the source text, preferring paragraph and
        word boundaries.

    Raises:
        ValueError: If the chunk size or overlap is outside the supported range.
    """
    if max_chars < 1_000:
        raise ValueError("Chunk size must be at least 1000 characters")
    if overlap < 0 or overlap >= max_chars // 2:
        raise ValueError("Overlap must be non-negative and less than half the chunk size")
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = _chunk_end(text, start, max_chars)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _chunk_end(text: str, start: int, max_chars: int) -> int:
    """Choose a chunk boundary near a paragraph or word break.

    Args:
        text: Complete source text.
        start: Zero-based start of the current chunk.
        max_chars: Requested maximum chunk length.

    Returns:
        The exclusive end offset, never before the latter half of the requested
        chunk unless the source ends earlier.
    """
    end = min(start + max_chars, len(text))
    if end >= len(text):
        return end
    minimum_boundary = start + max_chars // 2
    paragraph_boundary = text.rfind("\n\n", minimum_boundary, end)
    if paragraph_boundary != -1:
        return paragraph_boundary
    word_boundary = text.rfind(" ", minimum_boundary, end)
    return word_boundary if word_boundary != -1 else end
