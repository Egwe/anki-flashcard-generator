"""Test assembling structured PDF text from converter output without Docling."""

from pathlib import Path

import pytest

from anki_flashcards.errors import FlashcardError
from anki_flashcards.pictures import PictureContext
from anki_flashcards.structured_pdf import (
    ConversionOptions,
    ExtractedPage,
    ExtractedPdf,
    PictureInfo,
    figure_marker,
    is_decorative,
    render_document,
)

SOURCE = Path("vorlesung.pdf")


class FakeDescriber:
    """Return prepared descriptions and record every figure context.

    Attributes:
        answers: Descriptions returned in call order.
        contexts: Contexts received by ``describe``.
    """

    def __init__(self, *answers: str) -> None:
        """Store the descriptions to return.

        Args:
            *answers: Descriptions returned in call order.

        Returns:
            None.
        """
        self.answers = list(answers)
        self.contexts: list[PictureContext] = []

    def describe(self, image: object, context: PictureContext) -> str:
        """Record the context and return the next prepared description.

        Args:
            image: Picture crop; unused by the fake.
            context: Figure context passed by the renderer.

        Returns:
            The next prepared description.
        """
        self.contexts.append(context)
        return self.answers.pop(0)


def picture(token: str, page: int, **values: object) -> PictureInfo:
    """Create a content figure with a placeholder image.

    Args:
        token: Figure token used inside the page Markdown.
        page: One-based page number.
        **values: Field overrides such as ``kind`` or ``area_ratio``.

    Returns:
        A figure with a dummy image object.
    """
    return PictureInfo(token=token, page=page, image=object(), **values)


def test_render_marks_pages_figures_and_statistics() -> None:
    """Verify page markers, figure descriptions, decoration removal, and counts.

    Returns:
        None. Assertions inspect the text, statistics, and describer contexts.
    """
    extracted = ExtractedPdf(
        pages=(
            ExtractedPage(1, "## Halbleiter\n\n<P1>\n\n<LOGO>"),
            ExtractedPage(2, "| a | b |\n|---|---|\n| 1 | 2 |\n\n$$ U = R I $$\n\n<TINY>"),
        ),
        pictures=(
            picture("<P1>", 1, kind="line_chart", caption="Bild 3", text="W_L W_V"),
            picture("<LOGO>", 1, kind="logo"),
            picture("<TINY>", 2, kind="other", area_ratio=0.001),
        ),
        ocr_pages=(2,),
        tables=1,
        formulas=1,
    )
    describer = FakeDescriber("Bändermodell\nmit Leitungsband")
    progress: list[tuple[str, int, int]] = []

    result = render_document(
        SOURCE,
        extracted,
        ConversionOptions(language="Deutsch"),
        describer,
        lambda label, done, total: progress.append((label, done, total)),
    )

    text = result.document.text
    assert text.startswith("[Seite 1]\n## Halbleiter")
    assert (
        "[Abbildung S. 1 – Beschreibung: Bändermodell mit Leitungsband; "
        "Bildunterschrift: Bild 3; Text im Bild: W_L W_V]"
    ) in text
    assert "<LOGO>" not in text and "<TINY>" not in text
    assert "[Seite 2]\n| a | b |" in text
    assert describer.contexts == [PictureContext(1, "Bild 3", "W_L W_V", "Deutsch")]
    assert progress == [("Abbildungen beschreiben", 1, 1)]
    stats = result.stats
    assert (stats.pages, stats.ocr_pages, stats.tables, stats.formulas) == (2, 1, 1, 1)
    assert (stats.pictures_described, stats.pictures_decorative) == (1, 2)
    assert stats.unreadable == []


def test_every_page_keeps_its_marker() -> None:
    """Verify that an empty page is still represented by its page marker.

    Returns:
        None. The assertion checks the marker of the empty second page.
    """
    extracted = ExtractedPdf(pages=(ExtractedPage(1, "Text"), ExtractedPage(2, "")))

    result = render_document(SOURCE, extracted, ConversionOptions(), None)

    assert result.document.text == "[Seite 1]\nText\n\n[Seite 2]"


def test_unreadable_figure_aborts_by_default() -> None:
    """Verify that an empty description stops the run with a helpful message.

    Returns:
        None. The assertion expects the listed element and the option hint.
    """
    extracted = ExtractedPdf(
        pages=(ExtractedPage(1, "Text"), ExtractedPage(2, "<P>")),
        pictures=(picture("<P>", 2),),
    )

    with pytest.raises(FlashcardError, match=r"Abbildung S\. 2.*--allow-unreadable"):
        render_document(SOURCE, extracted, ConversionOptions(), FakeDescriber(""))


def test_allow_unreadable_inserts_reported_placeholders() -> None:
    """Verify placeholders and reporting for figures, formulas, and failed pages.

    Returns:
        None. Assertions inspect placeholders and the unreadable list.
    """
    extracted = ExtractedPdf(
        pages=(ExtractedPage(1, "<P>\n\n<!-- formula-not-decoded -->"), ExtractedPage(2, "")),
        pictures=(PictureInfo(token="<P>", page=1, image=None),),
        failed_pages=(2,),
    )

    result = render_document(
        SOURCE, extracted, ConversionOptions(allow_unreadable=True), FakeDescriber()
    )

    assert "[nicht lesbar: Abbildung S. 1]" in result.document.text
    assert "[nicht lesbar: Formel S. 1]" in result.document.text
    assert result.stats.unreadable == ["Abbildung S. 1", "Formel S. 1", "Seite 2"]


def test_disabled_formulas_are_marked_as_skipped() -> None:
    """Verify formulas are visibly skipped, not unreadable, when disabled.

    Returns:
        None. Assertions inspect the marker and the skipped count.
    """
    extracted = ExtractedPdf(pages=(ExtractedPage(3, "Sei <!-- formula-not-decoded -->"),))

    result = render_document(SOURCE, extracted, ConversionOptions(formulas=False), None)

    assert result.document.text == "[Seite 3]\nSei [Formel S. 3 – nicht ausgewertet]"
    assert result.stats.formulas_skipped == 1
    assert result.stats.unreadable == []


def test_figures_without_describer_stay_marked() -> None:
    """Verify the ``none`` backend keeps figures as marked placeholders.

    Returns:
        None. Assertions inspect the marker and the undescribed count.
    """
    extracted = ExtractedPdf(
        pages=(ExtractedPage(1, "<P>"),),
        pictures=(picture("<P>", 1, text="R1 R2"),),
    )

    result = render_document(SOURCE, extracted, ConversionOptions(), None)

    assert (
        result.document.text
        == "[Seite 1]\n[Abbildung S. 1 – nicht beschrieben; Text im Bild: R1 R2]"
    )
    assert result.stats.pictures_undescribed == 1


def test_document_without_content_is_rejected() -> None:
    """Verify a conversion without any page content is an error.

    Returns:
        None. The assertion expects a clear error.
    """
    extracted = ExtractedPdf(pages=(ExtractedPage(1, "  "),))

    with pytest.raises(FlashcardError, match="No extractable content"):
        render_document(SOURCE, extracted, ConversionOptions(), None)


@pytest.mark.parametrize(
    ("kind", "area", "expected"),
    [("logo", 0.5, True), ("icon", 0.5, True), ("line_chart", 0.005, True), ("other", 0.2, False)],
)
def test_decorative_figures(kind: str, area: float, expected: bool) -> None:
    """Verify logos, icons, and tiny images count as decoration.

    Args:
        kind: Predicted figure class.
        area: Share of the page covered by the figure.
        expected: Whether the figure should be left out.

    Returns:
        None. The assertion compares the decision.
    """
    assert is_decorative(PictureInfo(token="t", page=1, kind=kind, area_ratio=area)) is expected


def test_figure_marker_without_extras() -> None:
    """Verify the minimal marker format for a described figure.

    Returns:
        None. The assertion compares the exact marker.
    """
    marker = figure_marker(PictureInfo(token="t", page=12), "Ein Schaltplan.")

    assert marker == "[Abbildung S. 12 – Beschreibung: Ein Schaltplan.]"


def test_repeated_figures_lines_and_cjk_noise_are_removed() -> None:
    """Verify logos at a fixed position, footer lines, and CJK noise are removed.

    Returns:
        None. Assertions inspect the rendered pages and decorative count.
    """
    footer = "Hochschule für Angewandte Wissenschaften Hamburg"
    pages = tuple(
        ExtractedPage(
            number, f"## Folie {number}\n\nInhalt {number}\n\n{footer}\n\n<L{number}>\n\n三"
        )
        for number in range(1, 4)
    )
    pictures = tuple(
        picture(f"<L{number}>", number, kind="bar_chart", area_ratio=0.02, layout_key="1:2:3:4")
        for number in range(1, 4)
    )

    result = render_document(
        SOURCE, ExtractedPdf(pages=pages, pictures=pictures), ConversionOptions(), FakeDescriber()
    )

    assert result.document.text == (
        "[Seite 1]\n## Folie 1\n\nInhalt 1\n\n"
        "[Seite 2]\n## Folie 2\n\nInhalt 2\n\n"
        "[Seite 3]\n## Folie 3\n\nInhalt 3"
    )
    assert result.stats.pictures_decorative == 3


def test_cjk_lines_stay_for_cjk_ocr_languages() -> None:
    """Verify CJK lines are kept when a CJK OCR language is configured.

    Returns:
        None. The assertion finds the CJK line.
    """
    extracted = ExtractedPdf(pages=(ExtractedPage(1, "电路\n\nText"),))

    result = render_document(SOURCE, extracted, ConversionOptions(ocr_languages=("zh",)), None)

    assert "电路" in result.document.text
