"""Tests for the UI-independent generation, export, and model workflows."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from anki_flashcards.apkg import inspect_apkg
from anki_flashcards.config import AppConfig, PictureBackend
from anki_flashcards.documents import SourceDocument
from anki_flashcards.errors import FlashcardError, GenerationCancelled
from anki_flashcards.model_storage import ModelStorage
from anki_flashcards.models import Card, save_cards
from anki_flashcards.pipeline import (
    ConversionFinished,
    Notice,
    NoticeLevel,
    PipelineEvent,
    Stage,
    StageFinished,
    StageProgress,
    StageStarted,
    event_to_dict,
    prepare_models,
    produce_cards,
    run_export,
    run_generate,
)
from anki_flashcards.settings import ExportSettings, GenerateSettings, resolve_generate_settings
from anki_flashcards.structured_pdf import ConversionStats, StructuredPdf

CARDS = [
    Card(front="Was ist ein Tiefpass?", back="Ein Filter für tiefe Frequenzen."),
    Card(front="Was ist ein Hochpass?", back="Ein Filter für hohe Frequenzen."),
]


def _settings(tmp_path: Path, name: str = "notes.md", **values: object) -> GenerateSettings:
    """Resolve generation settings for a temporary source without YAML.

    Args:
        tmp_path: Pytest-provided isolated directory.
        name: Source filename; ``.pdf`` files get placeholder PDF bytes.
        **values: Explicit option values overriding the defaults.

    Returns:
        Settings writing ``deck.apkg`` next to the source with model ``ollama/test``.
    """
    source = tmp_path / name
    if source.suffix == ".pdf":
        source.write_bytes(b"%PDF-1.4 placeholder")
    else:
        source.write_text("# Filter\n\nTiefpass und Hochpass.", encoding="utf-8")
    explicit = {"input_file": source, "output": tmp_path / "deck.apkg", "model": "ollama/test"}
    return resolve_generate_settings({**explicit, **values}, AppConfig(), None)


def _forbidden(*args: object, **kwargs: object) -> None:
    """Fail when a code path runs that the test excludes.

    Args:
        *args: Ignored positional arguments.
        **kwargs: Ignored keyword arguments.

    Returns:
        Never returns.

    Raises:
        AssertionError: Always.
    """
    raise AssertionError("this path must not run")


def _two_chunk_generator(calls: list[int]):
    """Create a fake ``generate_cards`` reporting two chunks.

    Args:
        calls: List receiving the number of each reported chunk.

    Returns:
        A replacement for ``generate_cards`` that returns ``CARDS``.
    """

    def fake_generate(document: SourceDocument, settings: object, **kwargs: object) -> list[Card]:
        """Report two chunks with one new card each.

        Args:
            document: Source document.
            settings: Provider settings.
            **kwargs: Generation options including ``progress``.

        Returns:
            The two test cards.
        """
        for completed in (1, 2):
            calls.append(completed)
            kwargs["progress"](completed, 2, completed)
        return list(CARDS)

    return fake_generate


def test_event_to_dict_produces_json_for_every_event() -> None:
    """Verify all event types convert to JSON with a type key and plain values.

    Returns:
        None. Assertions inspect the serialized dictionaries.
    """
    stats = ConversionStats(pages=2, tables=1, unreadable=["Tabelle S. 2"])
    events: list[PipelineEvent] = [
        Notice("Upload", NoticeLevel.TRANSFER),
        StageStarted(Stage.CONVERSION, "PDF wird aufbereitet ..."),
        StageProgress(Stage.GENERATION, "Chunk", 1, 3, 4),
        StageFinished(Stage.GENERATION),
        ConversionFinished(stats),
    ]

    serialized = json.loads(json.dumps([event_to_dict(event) for event in events]))

    assert [entry["type"] for entry in serialized] == [
        "notice",
        "stage_started",
        "stage_progress",
        "stage_finished",
        "conversion_finished",
    ]
    assert serialized[0] == {"type": "notice", "text": "Upload", "level": "transfer"}
    assert serialized[2]["stage"] == "generation" and serialized[2]["cards"] == 4
    assert serialized[4]["stats"]["pages"] == 2
    assert serialized[4]["stats"]["unreadable"] == ["Tabelle S. 2"]


def test_produce_cards_reports_progress_and_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    """Verify card production reports each chunk but leaves the target untouched.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing the AI client.

    Returns:
        None. Assertions inspect events, cards, and the file system.
    """
    monkeypatch.setattr("anki_flashcards.pipeline.generate_cards", _two_chunk_generator([]))
    settings = _settings(tmp_path, json_output=tmp_path / "cards.json")
    events: list[PipelineEvent] = []

    run = produce_cards(settings, None, report=events.append)

    assert run.cards == CARDS
    assert run.conversion is None and run.source_text is None
    assert events == [
        StageStarted(Stage.GENERATION, "Generating cards with AI..."),
        StageProgress(Stage.GENERATION, "Chunk", 1, 2, 1),
        StageProgress(Stage.GENERATION, "Chunk", 2, 2, 2),
        StageFinished(Stage.GENERATION),
    ]
    assert not settings.output.exists()
    assert not (tmp_path / "cards.json").exists()


def test_produce_cards_without_usable_cards_fails(tmp_path: Path, monkeypatch) -> None:
    """Verify an empty provider result is an application error.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing the AI client.

    Returns:
        None. The expected error is asserted.
    """
    monkeypatch.setattr("anki_flashcards.pipeline.generate_cards", lambda *a, **k: [])

    with pytest.raises(FlashcardError, match="usable cards"):
        produce_cards(_settings(tmp_path), None)


def test_run_generate_writes_json_and_package(tmp_path: Path, monkeypatch) -> None:
    """Verify the complete run writes both outputs and returns their summary.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing the AI client.

    Returns:
        None. Assertions inspect the result and the written files.
    """
    monkeypatch.setattr("anki_flashcards.pipeline.generate_cards", _two_chunk_generator([]))
    settings = _settings(tmp_path, deck="Filter", json_output=tmp_path / "cards.json")

    result = run_generate(settings)

    assert result.export.added == 2
    assert result.json_output == tmp_path / "cards.json"
    assert json.loads((tmp_path / "cards.json").read_text(encoding="utf-8"))["deck"] == "Filter"
    assert inspect_apkg(settings.output)[-1]["cards"] == 2


def test_cancel_after_chunk_stops_without_writing(tmp_path: Path, monkeypatch) -> None:
    """Verify a cancellation after the first chunk stops before any file is written.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing the AI client.

    Returns:
        None. Assertions inspect chunks, events, and the file system.
    """
    chunks: list[int] = []
    monkeypatch.setattr("anki_flashcards.pipeline.generate_cards", _two_chunk_generator(chunks))
    settings = _settings(tmp_path, json_output=tmp_path / "cards.json")
    events: list[PipelineEvent] = []

    def cancel() -> bool:
        """Request cancellation as soon as one chunk was reported.

        Returns:
            True after the first progress event.
        """
        return any(isinstance(event, StageProgress) for event in events)

    with pytest.raises(GenerationCancelled):
        run_generate(settings, report=events.append, cancel=cancel)

    assert chunks == [1]
    assert events[-1] == StageFinished(Stage.GENERATION)
    assert not settings.output.exists()
    assert not (tmp_path / "cards.json").exists()


def test_native_upload_is_announced_as_transfer(tmp_path: Path, monkeypatch) -> None:
    """Verify the native mode marks its upload notice as a data transfer.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing the native adapter.

    Returns:
        None. Assertions inspect the first event and the cards.
    """
    monkeypatch.setattr("anki_flashcards.pipeline.generate_native_cards", lambda *a, **k: CARDS)
    monkeypatch.setattr("anki_flashcards.pipeline.read_document", _forbidden)
    settings = _settings(tmp_path, "skript.pdf", pdf_mode="native", model="openai/gpt-4o-mini")
    events: list[PipelineEvent] = []

    run = produce_cards(settings, None, report=events.append)

    assert run.cards == CARDS
    assert events[0].level == NoticeLevel.TRANSFER


def test_cancel_before_native_upload_uploads_nothing(tmp_path: Path, monkeypatch) -> None:
    """Verify a cancellation requested before the run prevents the upload.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture forbidding the native adapter.

    Returns:
        None. The expected cancellation and missing events are asserted.
    """
    monkeypatch.setattr("anki_flashcards.pipeline.generate_native_cards", _forbidden)
    settings = _settings(tmp_path, "skript.pdf", pdf_mode="native", model="openai/gpt-4o-mini")
    events: list[PipelineEvent] = []

    with pytest.raises(GenerationCancelled):
        produce_cards(settings, None, report=events.append, cancel=lambda: True)

    assert events == []


def _structured(tmp_path: Path, monkeypatch, convert) -> GenerateSettings:
    """Prepare structured-mode settings with fake Docling and picture backends.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing Docling and model storage.
        convert: Replacement for ``convert_pdf``.

    Returns:
        Settings for ``skript.pdf`` in structured mode with the profile
        picture backend.
    """

    def fake_describer(backend: PictureBackend, storage: ModelStorage, **kwargs: object) -> None:
        """Announce the figure transfer like the profile backend does.

        Args:
            backend: Requested picture backend.
            storage: Models folder.
            **kwargs: Picture settings including ``announce``.

        Returns:
            None instead of a describer.
        """
        kwargs["announce"]("Bildmodell über Profil: Bildausschnitte werden gesendet.")

    monkeypatch.setattr("anki_flashcards.pipeline.require_docling", lambda: None)
    monkeypatch.setattr("anki_flashcards.pipeline.require_accelerator", lambda allow_cpu: "cuda")
    monkeypatch.setattr(
        "anki_flashcards.pipeline.configure_model_storage", lambda root: ModelStorage(root)
    )
    monkeypatch.setattr("anki_flashcards.pipeline.create_describer", fake_describer)
    monkeypatch.setattr("anki_flashcards.pipeline.convert_pdf", convert)
    monkeypatch.setattr("anki_flashcards.pipeline.read_document", _forbidden)
    settings = _settings(tmp_path, "skript.pdf", pdf_mode="structured")
    conversion = replace(settings.conversion, picture_backend=PictureBackend.PROFILE)
    return replace(settings, conversion=conversion)


def test_structured_mode_reports_levels_and_statistics(tmp_path: Path, monkeypatch) -> None:
    """Verify transfer notices, conversion progress, and statistics events.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing Docling, models, and the AI.

    Returns:
        None. Assertions inspect notices, stages, and the card run.
    """
    stats = ConversionStats(pages=1)

    def fake_convert(path: Path, options: object, storage: object, **kwargs) -> StructuredPdf:
        """Report a download notice and one step, then return a result.

        Args:
            path: Requested PDF.
            options: Conversion options.
            storage: Models folder.
            **kwargs: Callbacks ``announce`` and ``progress``.

        Returns:
            A one-page structured result.
        """
        kwargs["announce"]("Lade Docling-Modelle ...")
        kwargs["progress"]("PDF-Seiten analysieren", 1, 1)
        return StructuredPdf(SourceDocument(path, "[Seite 1]\nFilter"), stats)

    settings = _structured(tmp_path, monkeypatch, fake_convert)
    monkeypatch.setattr("anki_flashcards.pipeline.generate_cards", _two_chunk_generator([]))
    events: list[PipelineEvent] = []

    run = produce_cards(settings, None, report=events.append)

    notices = {event.text: event.level for event in events if isinstance(event, Notice)}
    assert notices["Bildmodell über Profil: Bildausschnitte werden gesendet."] == "transfer"
    assert notices["Lade Docling-Modelle ..."] == "info"
    assert StageProgress(Stage.CONVERSION, "PDF-Seiten analysieren", 1, 1) in events
    assert ConversionFinished(stats) in events
    assert run.conversion is stats


def test_cancel_during_conversion_skips_generation(tmp_path: Path, monkeypatch) -> None:
    """Verify a cancellation in a conversion step stops before any AI request.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing Docling and forbidding the AI.

    Returns:
        None. Assertions inspect the cancellation and the closing event.
    """

    def fake_convert(path: Path, options: object, storage: object, **kwargs) -> StructuredPdf:
        """Report a step; the cancellation check raises inside the callback.

        Args:
            path: Requested PDF.
            options: Conversion options.
            storage: Models folder.
            **kwargs: Callbacks ``announce`` and ``progress``.

        Returns:
            Never returns in this test.
        """
        kwargs["progress"]("PDF-Seiten analysieren", 1, 3)
        raise AssertionError("cancellation must stop the conversion")

    settings = _structured(tmp_path, monkeypatch, fake_convert)
    monkeypatch.setattr("anki_flashcards.pipeline.generate_cards", _forbidden)
    events: list[PipelineEvent] = []

    def cancel() -> bool:
        """Request cancellation after the first conversion step.

        Returns:
            True once a conversion progress event was reported.
        """
        return any(isinstance(event, StageProgress) for event in events)

    with pytest.raises(GenerationCancelled):
        produce_cards(settings, None, report=events.append, cancel=cancel)

    assert events[-1] == StageFinished(Stage.CONVERSION)


def test_run_export_writes_saved_cards(tmp_path: Path) -> None:
    """Verify JSON export writes deduplicated cards without AI.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions inspect the export result and package.
    """
    cards_file = tmp_path / "cards.json"
    save_cards(cards_file, [*CARDS, CARDS[0]], deck="Filter")
    output = tmp_path / "deck.apkg"

    result = run_export(ExportSettings(cards_file, output, "Filter", extend=False))

    assert result.added == 2
    assert inspect_apkg(output)[-1]["cards"] == 2


def test_prepare_models_reports_downloads(tmp_path: Path, monkeypatch) -> None:
    """Verify model downloads are announced as notices and return the folder.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing Docling and the downloads.

    Returns:
        None. Assertions inspect notices and the returned folder.
    """

    def fake_conversion_models(storage: ModelStorage, *, formulas: bool, announce) -> None:
        """Announce the Docling download.

        Args:
            storage: Models folder.
            formulas: Whether the formula model is requested.
            announce: Notice callback.

        Returns:
            None.
        """
        announce(f"Docling formulas={formulas}")

    def fake_picture_model(storage: ModelStorage, repo_id: str, announce) -> Path:
        """Announce the picture model download.

        Args:
            storage: Models folder.
            repo_id: Picture model identifier.
            announce: Notice callback.

        Returns:
            The picture model folder.
        """
        announce("Bildmodell")
        return storage.root / "pictures"

    monkeypatch.setattr("anki_flashcards.pipeline.require_docling", lambda: None)
    monkeypatch.setattr("anki_flashcards.pipeline.ensure_conversion_models", fake_conversion_models)
    monkeypatch.setattr("anki_flashcards.pipeline.ensure_picture_model", fake_picture_model)
    events: list[PipelineEvent] = []

    root = prepare_models(
        AppConfig(),
        tmp_path / "config.yaml",
        formulas=False,
        picture_backend=PictureBackend.LOCAL,
        report=events.append,
    )

    assert root == tmp_path / "models"
    assert events == [Notice("Docling formulas=False"), Notice("Bildmodell")]
