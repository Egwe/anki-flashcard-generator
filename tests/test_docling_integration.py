"""Run the real Docling conversion on a generated scanned page (opt-in).

These tests need the optional ``pdf`` extra and download missing models into
the project ``models/`` folder. They are excluded from the standard run and
are started explicitly with ``pytest -m docling``.
"""

from pathlib import Path

import pytest

from anki_flashcards.config import PictureBackend
from anki_flashcards.docling_pdf import convert_pdf, create_describer
from anki_flashcards.model_storage import configure_model_storage
from anki_flashcards.structured_pdf import ConversionOptions

pytestmark = pytest.mark.docling
PROJECT_MODELS = Path(__file__).resolve().parents[1] / "models"
PICTURE_MODEL = "HuggingFaceTB/SmolVLM-256M-Instruct"


def scanned_pdf(path: Path) -> Path:
    """Write a one-page PDF that contains only an image of text and a sketch.

    Args:
        path: Destination PDF file.

    Returns:
        The written path. The page has no text layer, so text must come from OCR.
    """
    image_module = pytest.importorskip("PIL.Image")
    draw_module = pytest.importorskip("PIL.ImageDraw")
    font_module = pytest.importorskip("PIL.ImageFont")
    page = image_module.new("RGB", (1654, 2339), "white")
    draw = draw_module.Draw(page)
    title = font_module.load_default(size=72)
    body = font_module.load_default(size=48)
    draw.text((150, 200), "Ohmsches Gesetz", fill="black", font=title)
    draw.text((150, 380), "Die Spannung ist proportional zum Strom.", fill="black", font=body)
    draw.rectangle((400, 900, 1250, 1500), outline="black", width=8)
    draw.text((760, 1150), "R", fill="black", font=title)
    page.save(path, "PDF", resolution=200)
    return path


def test_real_docling_reads_a_scanned_page_locally(tmp_path: Path) -> None:
    """Verify OCR, page markers, and statistics with real Docling and local models.

    Args:
        tmp_path: Pytest-provided folder for the generated PDF.

    Returns:
        None. Assertions inspect the converted text and statistics.
    """
    pytest.importorskip("docling")
    storage = configure_model_storage(PROJECT_MODELS)
    describer = create_describer(
        PictureBackend.LOCAL,
        storage,
        picture_model=PICTURE_MODEL,
        picture_ai=None,
        announce=print,
    )

    result = convert_pdf(
        scanned_pdf(tmp_path / "scan.pdf"),
        ConversionOptions(formulas=False, allow_unreadable=True),
        storage,
        describer=describer,
        announce=print,
    )

    text = result.document.text
    assert text.startswith("[Seite 1]")
    assert "Ohmsches Gesetz" in text
    assert "proportional" in text
    assert result.stats.pages == 1
    assert result.stats.ocr_pages == 1
