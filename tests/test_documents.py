"""Test local document extraction, failure handling, and text chunking."""

from pathlib import Path

import pytest
from docx import Document

from anki_flashcards.documents import chunk_text, read_document
from anki_flashcards.errors import FlashcardError


def test_reads_html_without_script_content(tmp_path: Path) -> None:
    """Verify visible HTML text is retained and script content is removed.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions compare the normalized extracted text.
    """
    source = tmp_path / "source.html"
    source.write_text(
        "<html><script>ignore this</script><main><h1>Titel</h1><p>Ein Fakt.</p></main></html>",
        encoding="utf-8",
    )

    document = read_document(source)

    assert document.text == "Titel\nEin Fakt."
    assert "ignore this" not in document.text


def test_reads_docx_paragraphs_and_tables(tmp_path: Path) -> None:
    """Verify DOCX extraction includes paragraphs and pipe-separated table cells.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. The assertion checks the complete extracted text.
    """
    source = tmp_path / "source.docx"
    document = Document()
    document.add_paragraph("Absatz")
    document.add_table(rows=1, cols=2)
    table = document.tables[0]
    table.cell(0, 0).text = "Links"
    table.cell(0, 1).text = "Rechts"
    document.save(source)

    assert read_document(source).text == "Absatz\nLinks | Rechts"


def test_rejects_empty_and_unsupported_documents(tmp_path: Path) -> None:
    """Verify empty content and unsupported extensions have clear failures.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions require FlashcardError for both invalid inputs.
    """
    empty = tmp_path / "empty.txt"
    empty.write_text(" \n", encoding="utf-8")
    with pytest.raises(FlashcardError, match="No extractable text"):
        read_document(empty)

    unsupported = tmp_path / "source.xyz"
    unsupported.write_text("text", encoding="utf-8")
    with pytest.raises(FlashcardError, match="Unsupported file type"):
        read_document(unsupported)


def test_corrupt_pdf_is_a_user_facing_error(tmp_path: Path) -> None:
    """Verify parser failures are translated into FlashcardError.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. The assertion requires a readable application error.
    """
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"not a PDF")

    with pytest.raises(FlashcardError, match="Could not read"):
        read_document(source)


def test_chunks_long_text_with_overlap() -> None:
    """Verify long text is split within limits without losing its ending.

    Returns:
        None. Assertions cover chunk count, maximum length, and final content.
    """
    text = "\n\n".join(f"Absatz {index} " + "x" * 100 for index in range(50))

    chunks = chunk_text(text, max_chars=1_000, overlap=100)

    assert len(chunks) > 1
    assert all(len(chunk) <= 1_000 for chunk in chunks)
    assert chunks[0].startswith("Absatz 0")
    assert chunks[-1].endswith("x" * 100)
    assert "Absatz 49" in chunks[-1]
