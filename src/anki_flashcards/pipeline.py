"""Run generation, JSON export, and model downloads without a user interface.

The functions in this module contain the complete workflows behind the CLI
commands ``generate``, ``export``, and ``models download``. They never print;
progress and notices are reported as immutable events to a caller-supplied
callback, so a terminal, a web interface, or a test can present them.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from anki_flashcards.ai import generate_cards
from anki_flashcards.apkg import ExportResult, append_apkg, create_apkg, read_subdeck_context
from anki_flashcards.config import AppConfig, PDFMode, PictureBackend
from anki_flashcards.docling_pdf import (
    convert_pdf,
    create_describer,
    ensure_conversion_models,
    ensure_picture_model,
    require_accelerator,
    require_docling,
    validate_pdf_input,
)
from anki_flashcards.documents import SourceDocument, read_document
from anki_flashcards.errors import FlashcardError, GenerationCancelled
from anki_flashcards.model_storage import configure_model_storage
from anki_flashcards.models import Card, deduplicate_cards, load_cards, save_cards
from anki_flashcards.native_pdf import generate_native_cards
from anki_flashcards.settings import ExportSettings, GenerateSettings, resolve_models_dir
from anki_flashcards.structured_pdf import ConversionStats, save_source_text
from anki_flashcards.subdecks import SubdeckContext


class NoticeLevel(StrEnum):
    """Classify a notice for presentation.

    ``transfer`` marks every announcement that document content leaves the
    machine, so a user interface can highlight or require confirmation.
    """

    INFO = "info"
    WARNING = "warning"
    TRANSFER = "transfer"


class Stage(StrEnum):
    """Name a long-running phase of a generation run."""

    CONVERSION = "conversion"
    GENERATION = "generation"


@dataclass(frozen=True)
class Notice:
    """Report a human-readable message without terminal markup.

    Attributes:
        text: Message in the language of the existing CLI output.
        level: Presentation class of the message.
    """

    kind: ClassVar[str] = "notice"
    text: str
    level: NoticeLevel = NoticeLevel.INFO


@dataclass(frozen=True)
class StageStarted:
    """Report that a long-running phase begins.

    Attributes:
        stage: Phase that begins.
        description: Initial text shown until the first progress event.
    """

    kind: ClassVar[str] = "stage_started"
    stage: Stage
    description: str


@dataclass(frozen=True)
class StageProgress:
    """Report countable progress inside a phase.

    Attributes:
        stage: Phase the progress belongs to.
        label: Current step, for example ``Chunk`` or a conversion step.
        completed: Finished items of the step.
        total: All items of the step.
        cards: Unique cards so far during generation, otherwise None.
    """

    kind: ClassVar[str] = "stage_progress"
    stage: Stage
    label: str
    completed: int
    total: int
    cards: int | None = None


@dataclass(frozen=True)
class StageFinished:
    """Report that a phase ended, successfully or by an error or cancellation.

    Attributes:
        stage: Phase that ended.
    """

    kind: ClassVar[str] = "stage_finished"
    stage: Stage


@dataclass(frozen=True)
class ConversionFinished:
    """Report what the structured PDF conversion found and left out.

    Attributes:
        stats: Statistics of the finished conversion.
    """

    kind: ClassVar[str] = "conversion_finished"
    stats: ConversionStats


PipelineEvent = Notice | StageStarted | StageProgress | StageFinished | ConversionFinished
Reporter = Callable[[PipelineEvent], None]
CancelCheck = Callable[[], bool]

GENERATION_LABEL = "Chunk"


@dataclass(frozen=True)
class CardRun:
    """Hold the cards of one generation run before they are written.

    Attributes:
        cards: Validated, deduplicated, and limited cards; never empty.
        source_text: Saved Markdown of a structured conversion, or None.
        conversion: Statistics of a structured conversion, or None for the
            ``local`` and ``native`` modes.
    """

    cards: list[Card]
    source_text: Path | None = None
    conversion: ConversionStats | None = None


@dataclass(frozen=True)
class GenerateResult:
    """Summarize a complete generation run that wrote its outputs.

    Attributes:
        run: Generated cards and conversion details.
        export: Outcome of writing the APKG package.
        json_output: Card JSON file that was written, or None.
    """

    run: CardRun
    export: ExportResult
    json_output: Path | None = None


def event_to_dict(event: PipelineEvent) -> dict[str, Any]:
    """Convert an event into a JSON-serializable dictionary.

    Args:
        event: Any pipeline event.

    Returns:
        The event fields plus a ``type`` key naming the event class, for
        example ``{"type": "notice", "text": "...", "level": "info"}``.
        Enumerations are string values, so ``json.dumps`` works directly.
    """
    return {"type": event.kind, **asdict(event)}


def run_generate(
    settings: GenerateSettings,
    *,
    report: Reporter | None = None,
    cancel: CancelCheck | None = None,
) -> GenerateResult:
    """Generate cards for a document and write JSON and APKG outputs.

    This is the complete ``generate`` command without its terminal output.
    The output is validated before any conversion or AI request.

    Args:
        settings: Fully resolved generation settings.
        report: Callback receiving progress and notice events; optional.
        cancel: Callback returning True when the run should stop; optional.

    Returns:
        The generated cards, the APKG export result, and the written JSON path.

    Raises:
        GenerationCancelled: If ``cancel`` returned True; nothing is written.
        FlashcardError: If output validation, conversion, the provider, or
            writing fails, or no usable cards are returned.
    """
    validate_output(settings.output, settings.extend)
    subdeck_context = apkg_subdeck_context(settings, report=report)
    run = produce_cards(settings, subdeck_context, report=report, cancel=cancel)
    _check_cancel(cancel)
    if settings.json_output:
        save_cards(
            settings.json_output,
            run.cards,
            deck=settings.deck,
            source=str(settings.input_file),
        )
    export = write_apkg(settings.output, settings.deck, run.cards, settings.extend)
    return GenerateResult(run=run, export=export, json_output=settings.json_output)


def produce_cards(
    settings: GenerateSettings,
    subdeck_context: SubdeckContext | None,
    *,
    report: Reporter | None = None,
    cancel: CancelCheck | None = None,
) -> CardRun:
    """Generate cards in the configured PDF mode without writing a package.

    ``settings.output``, ``settings.extend``, and ``settings.json_output`` are
    ignored, so a caller can review the cards and choose a target afterwards.
    A structured conversion still saves ``conversion.source_text`` if set.

    Args:
        settings: Fully resolved generation settings.
        subdeck_context: Parent deck and known subdecks for the subdeck mode,
            or None for normal mode.
        report: Callback receiving progress and notice events; optional.
        cancel: Callback checked before an upload, between conversion steps,
            and after every chunk; optional.

    Returns:
        The non-empty validated cards and conversion details.

    Raises:
        GenerationCancelled: If ``cancel`` returned True.
        FlashcardError: If conversion or the provider fails, or the provider
            returns no usable cards.
    """
    emit = report or _ignore
    _check_cancel(cancel)
    if settings.pdf_mode == PDFMode.NATIVE:
        run = _native_cards(settings, subdeck_context, emit)
    elif settings.pdf_mode == PDFMode.STRUCTURED:
        run = _structured_cards(settings, subdeck_context, emit, cancel)
    else:
        document = read_document(settings.input_file)
        run = CardRun(_document_cards(settings, document, subdeck_context, emit, cancel))
    if not run.cards:
        raise FlashcardError("The AI did not return any usable cards")
    return run


def apkg_subdeck_context(
    settings: GenerateSettings, *, report: Reporter | None = None
) -> SubdeckContext | None:
    """Build the subdeck context for a run that writes an APKG package.

    Args:
        settings: Fully resolved generation settings.
        report: Callback receiving the notice about existing subdecks.

    Returns:
        None in normal mode, an empty context for a new package, or the
        existing subdecks read from the package to extend.

    Raises:
        FlashcardError: If the package to extend cannot be read.
    """
    if not settings.subdecks:
        return None
    if not settings.extend:
        return SubdeckContext(parent=settings.deck)
    context = read_subdeck_context(settings.output, settings.deck)
    (report or _ignore)(
        Notice(
            f"Unterdeck-Modus: {len(context.existing)} vorhandene Unterdecks von "
            f"'{settings.deck}' werden mit Beispielfragen als Kontext übergeben."
        )
    )
    return context


def validate_output(output: Path, extend: bool) -> None:
    """Validate APKG extension and create-versus-extend file semantics.

    Args:
        output: Requested destination package path.
        extend: Whether an existing package must be extended.

    Returns:
        None when the requested operation is valid.

    Raises:
        FlashcardError: If the suffix is wrong or the output existence does
            not match the requested operation.
    """
    if output.suffix.casefold() != ".apkg":
        raise FlashcardError("Output path must end in .apkg")
    if extend and not output.is_file():
        raise FlashcardError(f"Cannot extend missing APKG: {output}")
    if not extend and output.exists():
        raise FlashcardError(f"Output already exists: {output}. Use --extend or another path.")


def write_apkg(output: Path, deck: str, cards: list[Card], extend: bool) -> ExportResult:
    """Create a new APKG or extend an existing one with cards.

    Args:
        output: Destination APKG path, already checked by ``validate_output``.
        deck: Non-empty target deck name.
        cards: Validated cards to write.
        extend: Whether to preserve and extend an existing package.

    Returns:
        Added and skipped counts plus added cards per deck.

    Raises:
        FlashcardError: If the deck name is empty or package writing fails.
    """
    if not deck.strip():
        raise FlashcardError("Deck name must not be empty")
    if extend:
        return append_apkg(output, deck, cards)
    return create_apkg(output, deck, cards)


def run_export(settings: ExportSettings) -> ExportResult:
    """Write cards from a version-1 card JSON file into an APKG without AI.

    Args:
        settings: Fully resolved export settings.

    Returns:
        Added and skipped counts plus added cards per deck.

    Raises:
        FlashcardError: If the output is invalid, the JSON cannot be read, or
            writing fails.
    """
    validate_output(settings.output, settings.extend)
    cards = deduplicate_cards(load_cards(settings.cards_file))
    return write_apkg(settings.output, settings.deck, cards, settings.extend)


def prepare_models(
    config: AppConfig,
    config_path: Path | None,
    *,
    formulas: bool | None = None,
    picture_backend: PictureBackend | None = None,
    report: Reporter | None = None,
) -> Path:
    """Download every model the structured PDF mode needs ahead of time.

    Downloads use the network and write only into the configured models folder.

    Args:
        config: Validated application configuration.
        config_path: YAML location used to resolve the models folder.
        formulas: Whether the formula model is needed; None uses YAML.
        picture_backend: Picture backend; the local picture model is only
            downloaded for ``local``. None uses YAML.
        report: Callback receiving a notice before each download.

    Returns:
        The absolute models folder.

    Raises:
        FlashcardError: If Docling is missing or a download fails.
    """
    emit = report or _ignore
    conversion = config.pdf_conversion
    require_docling()
    storage = configure_model_storage(resolve_models_dir(config, config_path))
    with_formulas = conversion.formulas if formulas is None else formulas
    ensure_conversion_models(storage, formulas=with_formulas, announce=_announcer(emit))
    if (picture_backend or conversion.pictures.backend) == PictureBackend.LOCAL:
        ensure_picture_model(storage, conversion.pictures.model, _announcer(emit))
    return storage.root


def _native_cards(
    settings: GenerateSettings, subdeck_context: SubdeckContext | None, emit: Reporter
) -> CardRun:
    """Let a verified provider read the original PDF.

    Args:
        settings: Fully resolved generation settings using native mode.
        subdeck_context: Parent deck and known subdecks, or None.
        emit: Event callback; receives the upload announcement first.

    Returns:
        The provider's validated cards, possibly empty.
    """
    emit(
        Notice(
            "Native PDF mode: uploading the original document to the selected provider.",
            NoticeLevel.TRANSFER,
        )
    )
    cards = generate_native_cards(
        settings.input_file,
        settings.ai,
        limit=settings.limit,
        language=settings.language,
        instructions=settings.instructions,
        subdecks=subdeck_context,
    )
    return CardRun(cards)


def _structured_cards(
    settings: GenerateSettings,
    subdeck_context: SubdeckContext | None,
    emit: Reporter,
    cancel: CancelCheck | None,
) -> CardRun:
    """Convert a PDF locally with Docling and generate cards from the text.

    Args:
        settings: Fully resolved generation settings using structured mode.
        subdeck_context: Parent deck and known subdecks, or None.
        emit: Event callback for notices, progress, and statistics.
        cancel: Optional cancellation check between conversion steps.

    Returns:
        Cards, the saved source text path, and the conversion statistics.

    Raises:
        GenerationCancelled: If ``cancel`` returned True.
        FlashcardError: If the input is no PDF, the source text file exists,
            no GPU is available without ``allow_cpu``, Docling or a model is
            unavailable, or elements are unreadable.
    """
    conversion = settings.conversion
    validate_pdf_input(settings.input_file)
    if conversion.source_text is not None and conversion.source_text.exists():
        raise FlashcardError(f"Source text file already exists: {conversion.source_text}")
    require_docling()
    device = require_accelerator(conversion.options.allow_cpu)
    storage = configure_model_storage(conversion.models_dir)
    emit(
        Notice(
            f"Strukturierter PDF-Modus: {settings.input_file.name} wird lokal mit Docling "
            f"aufbereitet. GPU: {device}. Modelle und Caches: {storage.root}"
        )
    )
    if device == "cpu":
        emit(
            Notice(
                "Ohne GPU (--allow-cpu): Die Aufbereitung kann sehr lange dauern.",
                NoticeLevel.WARNING,
            )
        )
    picture_level = (
        NoticeLevel.TRANSFER
        if conversion.picture_backend == PictureBackend.PROFILE
        else NoticeLevel.INFO
    )
    describer = create_describer(
        conversion.picture_backend,
        storage,
        picture_model=conversion.picture_model,
        picture_ai=conversion.picture_ai,
        announce=_announcer(emit, picture_level),
        device=device,
    )
    with _stage(emit, Stage.CONVERSION, "PDF wird aufbereitet ..."):
        result = convert_pdf(
            settings.input_file,
            conversion.options,
            storage,
            describer=describer,
            announce=_announcer(emit),
            progress=_conversion_progress(emit, cancel),
            device=device,
        )
    _check_cancel(cancel)
    emit(ConversionFinished(result.stats))
    if conversion.source_text is not None:
        save_source_text(conversion.source_text, result.document.text)
        emit(Notice(f"Aufbereiteter Text: {conversion.source_text}"))
    cards = _document_cards(settings, result.document, subdeck_context, emit, cancel)
    return CardRun(cards, source_text=conversion.source_text, conversion=result.stats)


def _document_cards(
    settings: GenerateSettings,
    document: SourceDocument,
    subdeck_context: SubdeckContext | None,
    emit: Reporter,
    cancel: CancelCheck | None,
) -> list[Card]:
    """Generate cards from prepared document text with progress events.

    Args:
        settings: Fully resolved generation settings.
        document: Extracted or converted document text.
        subdeck_context: Parent deck and known subdecks, or None.
        emit: Event callback for generation progress.
        cancel: Optional cancellation check after every chunk.

    Returns:
        Validated cards from LiteLLM, possibly empty.

    Raises:
        GenerationCancelled: If ``cancel`` returned True after a chunk.
    """

    def update(completed: int, total: int, count: int) -> None:
        """Report one finished chunk and stop when cancellation was requested.

        Args:
            completed: Number of processed document chunks.
            total: Total document chunks in this generation run.
            count: Unique cards accumulated so far.

        Returns:
            None.

        Raises:
            GenerationCancelled: If ``cancel`` returned True.
        """
        emit(StageProgress(Stage.GENERATION, GENERATION_LABEL, completed, total, count))
        _check_cancel(cancel)

    with _stage(emit, Stage.GENERATION, "Generating cards with AI..."):
        return generate_cards(
            document,
            settings.ai,
            limit=settings.limit,
            language=settings.language,
            instructions=settings.instructions,
            chunk_size=settings.chunk_size,
            progress=update,
            subdecks=subdeck_context,
        )


def _conversion_progress(
    emit: Reporter, cancel: CancelCheck | None
) -> Callable[[str, int, int], None]:
    """Create the conversion progress callback with a cancellation check.

    Args:
        emit: Event callback receiving conversion progress.
        cancel: Optional cancellation check.

    Returns:
        A callback ``update(label, completed, total)`` for ``convert_pdf``.
    """

    def update(label: str, completed: int, total: int) -> None:
        """Report one conversion step and stop when cancellation was requested.

        Args:
            label: Name of the running step.
            completed: Finished items of the step.
            total: All items of the step.

        Returns:
            None.

        Raises:
            GenerationCancelled: If ``cancel`` returned True.
        """
        emit(StageProgress(Stage.CONVERSION, label, completed, total))
        _check_cancel(cancel)

    return update


def _announcer(emit: Reporter, level: NoticeLevel = NoticeLevel.INFO) -> Callable[[str], None]:
    """Adapt a plain-text announcement callback to notice events.

    Args:
        emit: Event callback.
        level: Level of every announcement passed through this adapter.

    Returns:
        A callback that wraps each message in a ``Notice``.
    """

    def announce(text: str) -> None:
        """Forward one announcement as a notice.

        Args:
            text: Announcement text.

        Returns:
            None.
        """
        emit(Notice(text, level))

    return announce


@contextmanager
def _stage(emit: Reporter, stage: Stage, description: str) -> Iterator[None]:
    """Bracket a phase with start and finish events, also on errors.

    Args:
        emit: Event callback.
        stage: Phase being run.
        description: Initial text of the phase.

    Returns:
        A context manager; ``StageFinished`` is emitted when it exits.
    """
    emit(StageStarted(stage, description))
    try:
        yield
    finally:
        emit(StageFinished(stage))


def _check_cancel(cancel: CancelCheck | None) -> None:
    """Stop the run when the caller requested cancellation.

    Args:
        cancel: Optional cancellation check.

    Returns:
        None when the run may continue.

    Raises:
        GenerationCancelled: If ``cancel`` returned True.
    """
    if cancel is not None and cancel():
        raise GenerationCancelled("Generation cancelled")


def _ignore(event: PipelineEvent) -> None:
    """Discard an event when the caller supplied no reporter.

    Args:
        event: Ignored event.

    Returns:
        None.
    """
