"""Assemble locally converted PDF pages, figures, and formulas into marked text."""

import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from anki_flashcards.ai import FIGURE_MARKER
from anki_flashcards.documents import SourceDocument
from anki_flashcards.errors import FlashcardError
from anki_flashcards.pictures import PictureContext, PictureDescriber

FORMULA_NOT_DECODED = "<!-- formula-not-decoded -->"
DECORATIVE_KINDS = frozenset(
    {"logo", "icon", "signature", "stamp", "qr_code", "bar_code", "page_thumbnail"}
)
MIN_PICTURE_AREA = 0.01
MIN_REPEATED_PAGES = 3
REPEATED_LINE_SHARE = 0.4
MAX_LISTED_UNREADABLE = 10
PROTECTED_LINE_STARTS = ("#", "[", "|", "$$")
CJK_LANGUAGES = frozenset({"zh", "ja", "ko"})
CJK_ONLY = re.compile(r"^[\s\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+$")

ProgressCallback = Callable[[str, int, int], None]


@dataclass(frozen=True)
class ConversionOptions:
    """Configure the local structured PDF conversion.

    Attributes:
        ocr_languages: ISO language codes for text recognition, first is primary.
        force_ocr: Recognize all page text by OCR instead of the text layer.
        formulas: Recognize formulas as LaTeX; slow on a CPU.
        allow_unreadable: Insert reported placeholders instead of aborting.
        allow_cpu: Accept CPU-only conversion although it is very slow.
        language: Language requested for figure descriptions.
    """

    ocr_languages: tuple[str, ...] = ("de", "en")
    force_ocr: bool = False
    formulas: bool = True
    allow_unreadable: bool = False
    allow_cpu: bool = False
    language: str = "Deutsch"


@dataclass(frozen=True)
class PictureInfo:
    """Describe one figure found by the converter.

    Attributes:
        token: Unique placeholder for the figure inside its page text.
        page: One-based page number.
        kind: Predicted figure class such as ``line_chart`` or ``logo``.
        area_ratio: Share of the page area covered by the figure, 0..1.
        caption: Caption text, possibly empty.
        text: Text recognized inside the figure, possibly empty.
        image: Picture crop for the describer, or None if unavailable.
        layout_key: Rounded position and size on the page; equal keys on
            several pages identify repeated decoration such as logos.
    """

    token: str
    page: int
    kind: str | None = None
    area_ratio: float = 1.0
    caption: str = ""
    text: str = ""
    image: Any = None
    layout_key: str = ""


@dataclass(frozen=True)
class ExtractedPage:
    """Hold the Markdown of one page with figure tokens and formula placeholders.

    Attributes:
        number: One-based page number.
        markdown: Page Markdown; figures appear as their tokens.
    """

    number: int
    markdown: str


@dataclass(frozen=True)
class ExtractedPdf:
    """Collect the converter output before figures are described.

    Attributes:
        pages: Every page of the document in order, including empty ones.
        pictures: All figures referenced by page tokens.
        ocr_pages: Page numbers whose text was recognized by OCR.
        tables: Number of tables rendered as Markdown tables.
        formulas: Number of formulas recognized as LaTeX.
        failed_pages: Page numbers the converter could not process.
    """

    pages: tuple[ExtractedPage, ...]
    pictures: tuple[PictureInfo, ...] = ()
    ocr_pages: tuple[int, ...] = ()
    tables: int = 0
    formulas: int = 0
    failed_pages: tuple[int, ...] = ()


@dataclass
class ConversionStats:
    """Count what the structured conversion found and how it was handled.

    Attributes:
        pages: Number of pages in the result.
        ocr_pages: Pages whose text came from OCR.
        tables: Tables rendered as Markdown tables.
        formulas: Formulas recognized as LaTeX.
        formulas_skipped: Formulas left out because recognition was disabled.
        pictures_described: Figures replaced by a description.
        pictures_undescribed: Figures kept only as placeholder with their text.
        pictures_decorative: Logos, icons, and tiny images left out.
        unreadable: Human-readable labels of elements that could not be read.
    """

    pages: int = 0
    ocr_pages: int = 0
    tables: int = 0
    formulas: int = 0
    formulas_skipped: int = 0
    pictures_described: int = 0
    pictures_undescribed: int = 0
    pictures_decorative: int = 0
    unreadable: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StructuredPdf:
    """Return the marked document text together with its statistics.

    Attributes:
        document: Source document whose text is passed to card generation.
        stats: Counts of pages, OCR, tables, formulas, figures, and gaps.
    """

    document: SourceDocument
    stats: ConversionStats


def render_document(
    path: Path,
    extracted: ExtractedPdf,
    options: ConversionOptions,
    describer: PictureDescriber | None,
    progress: ProgressCallback | None = None,
) -> StructuredPdf:
    """Describe figures, mark gaps, and join all pages into one text.

    Args:
        path: Source PDF path stored in the resulting document.
        extracted: Converter output with page Markdown and figures.
        options: Formula and unreadable-element handling.
        describer: Picture model backend, or None to keep figures undescribed.
        progress: Optional callback receiving label, completed, and total.

    Returns:
        The marked Markdown document and its statistics.

    Raises:
        FlashcardError: If elements are unreadable and placeholders are not
            allowed, or if no page contains any text.
    """
    stats = ConversionStats(
        pages=len(extracted.pages),
        ocr_pages=len(extracted.ocr_pages),
        tables=extracted.tables,
        formulas=extracted.formulas,
    )
    markers = _picture_markers(extracted.pictures, options, describer, stats, progress)
    bodies = [_render_body(page, markers, options, stats) for page in extracted.pages]
    bodies = _remove_repeated_lines(bodies)
    pages = [
        f"[Seite {page.number}]\n{body}".strip()
        for page, body in zip(extracted.pages, bodies, strict=True)
    ]
    stats.unreadable.extend(f"Seite {number}" for number in extracted.failed_pages)
    _check_unreadable(stats.unreadable, options.allow_unreadable)
    text = "\n\n".join(pages).strip()
    if not any(_page_body(page) for page in pages):
        raise FlashcardError(f"No extractable content found in {path}")
    return StructuredPdf(document=SourceDocument(path=path, text=text), stats=stats)


def save_source_text(path: Path, text: str) -> None:
    """Save the converted Markdown to a new file atomically.

    Args:
        path: Destination that must not exist yet; parent folders are created.
        text: Converted document text.

    Returns:
        None. The file appears only after it was written completely.

    Raises:
        FlashcardError: If the file exists or cannot be written.
    """
    if path.exists():
        raise FlashcardError(f"Source text file already exists: {path}")
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text + "\n")
        os.replace(temporary, path)
    except OSError as error:
        raise FlashcardError(f"Could not save source text {path}: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def is_decorative(picture: PictureInfo) -> bool:
    """Decide whether a figure is decoration that should not be described.

    Args:
        picture: Figure with predicted class and relative page area.

    Returns:
        True for logos, icons, signatures, codes, and tiny images.
    """
    return picture.kind in DECORATIVE_KINDS or picture.area_ratio < MIN_PICTURE_AREA


def figure_marker(picture: PictureInfo, description: str | None) -> str:
    """Format the marked text that replaces a figure in the document.

    Args:
        picture: Figure with page, caption, and recognized text.
        description: Machine description, or None when no model described it.

    Returns:
        One line starting with ``[Abbildung S. N``; caption and recognized
        text are appended when present.
    """
    head = f"{FIGURE_MARKER}{picture.page}"
    parts = [f"Beschreibung: {_one_line(description)}" if description else "nicht beschrieben"]
    if picture.caption:
        parts.append(f"Bildunterschrift: {_one_line(picture.caption)}")
    if picture.text:
        parts.append(f"Text im Bild: {_one_line(picture.text)}")
    return f"{head} – " + "; ".join(parts) + "]"


def _picture_markers(
    pictures: tuple[PictureInfo, ...],
    options: ConversionOptions,
    describer: PictureDescriber | None,
    stats: ConversionStats,
    progress: ProgressCallback | None,
) -> dict[str, str]:
    """Create the replacement text for every figure token.

    Args:
        pictures: All figures of the document.
        options: Requested description language and gap handling.
        describer: Picture backend, or None to keep figures undescribed.
        stats: Statistics updated in place.
        progress: Optional callback for description progress.

    Returns:
        Mapping from figure token to its marked replacement text.
    """
    repeated = _repeated_layout_keys(pictures)
    decorative = [p for p in pictures if is_decorative(p) or p.layout_key in repeated]
    content = [picture for picture in pictures if picture not in decorative]
    stats.pictures_decorative = len(decorative)
    markers = {picture.token: "" for picture in decorative}
    for index, picture in enumerate(content, 1):
        markers[picture.token] = _describe(picture, options, describer, stats)
        if progress is not None:
            progress("Abbildungen beschreiben", index, len(content))
    return markers


def _repeated_layout_keys(pictures: tuple[PictureInfo, ...]) -> set[str]:
    """Find figure positions that repeat on several pages, like logos.

    Args:
        pictures: All figures of the document.

    Returns:
        Layout keys present on at least three different pages.
    """
    pages_by_key: dict[str, set[int]] = {}
    for picture in pictures:
        if picture.layout_key:
            pages_by_key.setdefault(picture.layout_key, set()).add(picture.page)
    return {key for key, pages in pages_by_key.items() if len(pages) >= MIN_REPEATED_PAGES}


def _describe(
    picture: PictureInfo,
    options: ConversionOptions,
    describer: PictureDescriber | None,
    stats: ConversionStats,
) -> str:
    """Describe one content figure or mark it as undescribed or unreadable.

    Args:
        picture: Non-decorative figure.
        options: Requested description language.
        describer: Picture backend, or None when descriptions are disabled.
        stats: Statistics updated in place.

    Returns:
        The figure marker or an unreadable placeholder.
    """
    if describer is None:
        stats.pictures_undescribed += 1
        return figure_marker(picture, None)
    description = ""
    if picture.image is not None:
        context = PictureContext(picture.page, picture.caption, picture.text, options.language)
        description = describer.describe(picture.image, context)
    if not description:
        label = f"Abbildung S. {picture.page}"
        stats.unreadable.append(label)
        return f"[nicht lesbar: {label}]"
    stats.pictures_described += 1
    return figure_marker(picture, description)


def _render_body(
    page: ExtractedPage,
    markers: dict[str, str],
    options: ConversionOptions,
    stats: ConversionStats,
) -> str:
    """Replace figure tokens and formula placeholders and drop OCR noise on one page.

    Args:
        page: Converter Markdown of the page.
        markers: Replacement text per figure token.
        options: Formula setting and OCR languages.
        stats: Statistics updated in place.

    Returns:
        The page body without its page marker.
    """
    text = page.markdown
    for token, marker in markers.items():
        text = text.replace(token, marker)
    text = _replace_formulas(text, page.number, options, stats)
    if not CJK_LANGUAGES.intersection(options.ocr_languages):
        text = "\n".join(line for line in text.split("\n") if not CJK_ONLY.match(line))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _remove_repeated_lines(bodies: list[str]) -> list[str]:
    """Remove header and footer lines that repeat on many pages.

    Headings, markers, table rows, and formulas are never removed.

    Args:
        bodies: Page bodies in page order.

    Returns:
        Page bodies without lines found on at least three pages and on at
        least 40 percent of all pages.
    """
    counts: dict[str, int] = {}
    for body in bodies:
        for line in {line.strip() for line in body.split("\n")}:
            counts[line] = counts.get(line, 0) + 1
    limit = max(MIN_REPEATED_PAGES, REPEATED_LINE_SHARE * len(bodies))
    repeated = {
        line
        for line, count in counts.items()
        if line and count >= limit and not line.startswith(PROTECTED_LINE_STARTS)
    }
    if not repeated:
        return bodies
    cleaned = []
    for body in bodies:
        lines = [line for line in body.split("\n") if line.strip() not in repeated]
        cleaned.append(re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip())
    return cleaned


def _replace_formulas(
    text: str, page: int, options: ConversionOptions, stats: ConversionStats
) -> str:
    """Replace undecoded formula placeholders by visible markers.

    Args:
        text: Page Markdown.
        page: One-based page number for the marker.
        options: Whether formula recognition was enabled.
        stats: Statistics updated in place.

    Returns:
        Page text in which every placeholder is a skipped or unreadable marker.
    """
    count = text.count(FORMULA_NOT_DECODED)
    if not count:
        return text
    if not options.formulas:
        stats.formulas_skipped += count
        return text.replace(FORMULA_NOT_DECODED, f"[Formel S. {page} – nicht ausgewertet]")
    stats.unreadable.extend([f"Formel S. {page}"] * count)
    return text.replace(FORMULA_NOT_DECODED, f"[nicht lesbar: Formel S. {page}]")


def _check_unreadable(unreadable: list[str], allowed: bool) -> None:
    """Abort on unreadable elements unless placeholders were allowed.

    Args:
        unreadable: Labels of elements that could not be read.
        allowed: Whether reported placeholders are acceptable.

    Returns:
        None when nothing is unreadable or placeholders are allowed.

    Raises:
        FlashcardError: If unreadable elements exist and are not allowed.
    """
    if not unreadable or allowed:
        return
    listed = ", ".join(unreadable[:MAX_LISTED_UNREADABLE])
    more = len(unreadable) - MAX_LISTED_UNREADABLE
    suffix = f" and {more} more" if more > 0 else ""
    raise FlashcardError(
        f"{len(unreadable)} PDF elements could not be read: {listed}{suffix}. "
        "Use --allow-unreadable to continue with marked placeholders."
    )


def _page_body(page: str) -> str:
    """Return a rendered page without its leading page marker.

    Args:
        page: Rendered page text starting with ``[Seite N]``.

    Returns:
        The remaining page content, stripped.
    """
    return page.partition("\n")[2].strip()


def _one_line(text: str) -> str:
    """Collapse whitespace so a marker never contains blank lines.

    Args:
        text: Arbitrary multi-line text.

    Returns:
        Text with every whitespace run replaced by one space.
    """
    return " ".join(text.split())
