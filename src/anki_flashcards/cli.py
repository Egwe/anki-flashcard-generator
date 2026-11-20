"""Expose document generation, JSON export, and deck inspection as a CLI."""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import typer
from dotenv import find_dotenv, load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from anki_flashcards.ai import generate_cards
from anki_flashcards.apkg import (
    ExportResult,
    append_apkg,
    create_apkg,
    inspect_apkg,
    read_subdeck_context,
)
from anki_flashcards.config import PDFMode, PictureBackend
from anki_flashcards.docling_pdf import (
    convert_pdf,
    create_describer,
    ensure_conversion_models,
    ensure_picture_model,
    require_docling,
    validate_pdf_input,
)
from anki_flashcards.documents import SourceDocument, read_document
from anki_flashcards.errors import FlashcardError
from anki_flashcards.model_storage import configure_model_storage
from anki_flashcards.models import Card, deduplicate_cards, load_cards, save_cards
from anki_flashcards.native_pdf import generate_native_cards
from anki_flashcards.settings import (
    GenerateSettings,
    configuration_diagnostics,
    load_selected_config,
    resolve_export_settings,
    resolve_generate_settings,
    resolve_models_dir,
)
from anki_flashcards.structured_pdf import ConversionStats, save_source_text
from anki_flashcards.subdecks import SubdeckContext

MAIN_EPILOG = """
Examples:
  anki-flashcards generate skript.pdf -o output/biologie.apkg -m ollama/llama3.2
  anki-flashcards export output/biologie.cards.json -o output/biologie.apkg -d Biologie
  anki-flashcards decks output/biologie.apkg

New output files are created with missing parent directories. Existing APKG files
are never overwritten unless --extend is explicitly selected. Exit status is 0 on
success, 1 for an application/provider error, and 2 for invalid CLI usage.
"""
GENERATE_EPILOG = """
The input must be a readable local PDF, DOCX, HTML, Markdown, or UTF-8 text file
of at most 100 MiB. URLs are not supported. Without --deck, the input filename
without its suffix is used. The default limit is 50; --limit 0 processes every
chunk once and requests all useful cards without an arbitrary numeric cap.

Without --extend, --output must name a new .apkg file. With --extend, it must
already exist and is updated atomically. Existing cards and review states are
preserved. If the requested deck does not exist, it is created in the package.

PDF modes: local reads only the embedded text layer. structured converts the PDF
locally with Docling (optional extra "pdf"): OCR for text in images and scans,
tables as Markdown tables, formulas as LaTeX, and figures replaced by marked
descriptions from a picture model. Only text reaches the card model. Models and
caches are stored in the project models folder. Unreadable elements abort the
run unless --allow-unreadable is given. native uploads the original PDF.

With --subdecks, --deck is the parent deck (for example a lecture) and the AI
assigns every card to a chapter subdeck DECK::chapter, preferably named after the
source's own headings. With --extend, the names of existing subdecks and up to
five sample questions each are sent to the provider so matching subdecks are
reused; new ones are created only when needed. Duplicates are then checked across
the deck and all of its subdecks.

Examples:
  anki-flashcards generate skript.pdf -o output/biologie.apkg -m ollama/llama3.2
  anki-flashcards generate kapitel.docx -o output/deck.apkg -d Biologie --extend
  anki-flashcards generate notes.md -o output/notes.apkg -n 0 --json output/cards.json
  anki-flashcards generate vl-02.pdf -o output/el1.apkg -d EL1 --extend --subdecks
  anki-flashcards generate vl-03.pdf -o output/el1.apkg --pdf-mode structured \\
      --source-text output/vl-03.md
"""
EXPORT_EPILOG = """
The input must be a version-1 card JSON file previously written with --json or
created with the same schema. No AI request is made. Without --extend, --output
must be a new .apkg file; with --extend, it must already exist. The deck is a
required explicit target. Cards with a "subdeck" field are placed in
DECK::subdeck. New parent directories are created automatically.

Example:
  anki-flashcards export output/cards.json -o output/deck.apkg -d Biologie
"""
DECKS_EPILOG = """
The package must be a readable APKG with a classic or zstd-compressed Anki
collection. Normal decks are listed with direct card counts; filtered decks are
excluded. The package is only read, never modified.

Example:
  anki-flashcards decks output/deck.apkg
"""

app = typer.Typer(
    name="anki-flashcards",
    help="Generate Anki decks from local documents using AI.",
    epilog=MAIN_EPILOG,
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console()
error_console = Console(stderr=True)


@app.command(epilog=GENERATE_EPILOG)
def generate(
    input_file: Path = typer.Argument(
        ...,
        file_okay=True,
        dir_okay=False,
        help=(
            "Local PDF, DOCX, HTML, Markdown, or UTF-8 text file. Bare names "
            "may resolve through input_dir; direct paths are checked by the CLI."
        ),
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help=(
            "Destination .apkg; required unless output_dir is configured. Must "
            "be new, or existing with --extend. Parent directories are created."
        ),
    ),
    deck: str | None = typer.Option(
        None,
        "--deck",
        "-d",
        help="Target deck name; use '::' for subdecks. Default: input filename stem.",
    ),
    extend: bool | None = typer.Option(
        None,
        "--extend/--no-extend",
        help=(
            "Append to an existing output (--extend) or require a new one "
            "(--no-extend). Overrides YAML extend in both directions."
        ),
    ),
    config_file: Path | None = typer.Option(
        None,
        "--config",
        envvar="ANKI_CONFIG",
        help="YAML configuration path. Default: optional ./config.yaml; may use ANKI_CONFIG.",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Named YAML model profile. Overrides default_profile; direct --model still wins.",
    ),
    pdf_mode: PDFMode | None = typer.Option(
        None,
        "--pdf-mode",
        help=(
            "PDF handling: local (text layer only), structured (local Docling "
            "conversion with OCR, tables, formulas, and figure descriptions; needs "
            "the pdf extra), or native (uploads the original file to a verified "
            "provider). Overrides YAML."
        ),
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help=(
            "LiteLLM provider/model, for example ollama/llama3.2 or "
            "openai/gpt-4o-mini. Overrides the model from the YAML profile."
        ),
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        "-n",
        min=0,
        help="Maximum cards across all chunks, >= 0. Default: 50; 0 = unlimited.",
        show_default=False,
    ),
    language: str | None = typer.Option(
        None,
        "--language",
        "-l",
        help="Natural language for generated questions and answers. Default: Deutsch.",
        show_default=False,
    ),
    instructions: str | None = typer.Option(
        None,
        "--instructions",
        help="Optional additional card guidance; default: no extra instructions.",
        show_default=False,
    ),
    chunk_size: int | None = typer.Option(
        None,
        "--chunk-size",
        min=1_000,
        max=100_000,
        help=(
            "Maximum source characters per AI request, 1000..100000. "
            "Default: 24000; adjacent chunks overlap by 500 characters, "
            "at most a quarter of the chunk size."
        ),
        show_default=False,
    ),
    api_base: str | None = typer.Option(
        None,
        "--api-base",
        help=(
            "Optional provider endpoint override. Overrides YAML api_base; "
            "provider defaults are used when neither is configured."
        ),
    ),
    timeout: int | None = typer.Option(
        None,
        "--timeout",
        min=1,
        max=3_600,
        help="Provider request timeout in seconds, 1..3600. Default: 180.",
        show_default=False,
    ),
    json_output: Path | None = typer.Option(
        None,
        "--json",
        help=(
            "Optional UTF-8 card JSON for review/re-export without AI. "
            "Parent directories are created; an existing JSON file is replaced."
        ),
    ),
    subdecks: bool | None = typer.Option(
        None,
        "--subdecks/--no-subdecks",
        help=(
            "Let the AI sort cards into chapter subdecks DECK::chapter below --deck. "
            "With --extend, existing subdecks and sample questions are sent as "
            "context. Default: off; overrides YAML subdecks in both directions."
        ),
        show_default=False,
    ),
    formulas: bool | None = typer.Option(
        None,
        "--formulas/--no-formulas",
        help=(
            "Structured mode: recognize formulas as LaTeX. Default: on; slow on a "
            "CPU. With --no-formulas, formulas are marked as not evaluated."
        ),
        show_default=False,
    ),
    force_ocr: bool | None = typer.Option(
        None,
        "--force-ocr/--no-force-ocr",
        help="Structured mode: read every page by OCR instead of its text layer. Default: off.",
        show_default=False,
    ),
    allow_unreadable: bool | None = typer.Option(
        None,
        "--allow-unreadable/--no-allow-unreadable",
        help=(
            "Structured mode: continue with reported placeholders when an element "
            "cannot be read. Default: off, the run aborts before any AI request."
        ),
        show_default=False,
    ),
    picture_backend: PictureBackend | None = typer.Option(
        None,
        "--picture-backend",
        help=(
            "Structured mode: describe figures with the local model (default), a "
            "model profile (sends figure crops to its provider), or none."
        ),
    ),
    picture_profile: str | None = typer.Option(
        None,
        "--picture-profile",
        help=(
            "Profile for --picture-backend profile; it must set image_input: true. "
            "Default: pdf_conversion.pictures.profile, else the card profile."
        ),
    ),
    source_text: Path | None = typer.Option(
        None,
        "--source-text",
        help=(
            "Structured mode: save the converted Markdown to this new file for "
            "review and reuse. An existing file is never overwritten."
        ),
    ),
) -> None:
    """Generate cards from PDF, DOCX, HTML, Markdown, or text."""
    cli_values = _explicit_values(
        output=output,
        deck=deck,
        extend=extend,
        profile=profile,
        pdf_mode=pdf_mode,
        model=model,
        limit=limit,
        language=language,
        instructions=instructions,
        chunk_size=chunk_size,
        api_base=api_base,
        timeout=timeout,
        json_output=json_output,
        subdecks=subdecks,
        formulas=formulas,
        force_ocr=force_ocr,
        allow_unreadable=allow_unreadable,
        picture_backend=picture_backend,
        picture_profile=picture_profile,
        source_text=source_text,
    )
    config, config_path = load_selected_config(config_file)
    settings = resolve_generate_settings(
        {"input_file": input_file, **cli_values}, config, config_path
    )
    _validate_output(settings.output, settings.extend)
    subdeck_context = _subdeck_context(settings)
    if settings.pdf_mode == PDFMode.NATIVE:
        console.print("Native PDF mode: uploading the original document to the selected provider.")
        cards = generate_native_cards(
            settings.input_file,
            settings.ai,
            limit=settings.limit,
            language=settings.language,
            instructions=settings.instructions,
            subdecks=subdeck_context,
        )
    elif settings.pdf_mode == PDFMode.STRUCTURED:
        cards = _generate_structured_cards(settings, subdeck_context)
    else:
        cards = _generate_local_cards(settings, subdeck_context)
    if not cards:
        raise FlashcardError("The AI did not return any usable cards")

    if settings.json_output:
        save_cards(
            settings.json_output,
            cards,
            deck=settings.deck,
            source=str(settings.input_file),
        )
    result = _write_deck(settings.output, settings.deck, cards, settings.extend)
    _print_result(result, settings.json_output)


def _subdeck_context(settings: GenerateSettings) -> SubdeckContext | None:
    """Build the subdeck context for a generation run and announce it.

    Args:
        settings: Fully resolved generation settings.

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
    console.print(
        f"Unterdeck-Modus: {len(context.existing)} vorhandene Unterdecks von "
        f"'{settings.deck}' werden mit Beispielfragen als Kontext übergeben."
    )
    return context


def _generate_local_cards(
    settings: GenerateSettings, subdeck_context: SubdeckContext | None
) -> list[Card]:
    """Extract document text and generate cards with progress reporting.

    Args:
        settings: Fully resolved generation settings using local PDF mode.
        subdeck_context: Parent deck and known subdecks, or None for normal
            mode.

    Returns:
        Validated cards from LiteLLM, possibly empty when the provider returns
        no usable cards.
    """
    return _generate_from_document(settings, read_document(settings.input_file), subdeck_context)


def _generate_structured_cards(
    settings: GenerateSettings, subdeck_context: SubdeckContext | None
) -> list[Card]:
    """Convert a PDF locally with Docling and generate cards from the text.

    Args:
        settings: Fully resolved generation settings using structured mode.
        subdeck_context: Parent deck and known subdecks, or None.

    Returns:
        Validated cards from LiteLLM.

    Raises:
        FlashcardError: If the input is no PDF, the source text file exists,
            Docling or a model is unavailable, or elements are unreadable.
    """
    conversion = settings.conversion
    validate_pdf_input(settings.input_file)
    if conversion.source_text is not None and conversion.source_text.exists():
        raise FlashcardError(f"Source text file already exists: {conversion.source_text}")
    require_docling()
    storage = configure_model_storage(conversion.models_dir)
    console.print(
        f"Strukturierter PDF-Modus: {settings.input_file.name} wird lokal mit Docling "
        f"aufbereitet. Modelle und Caches: {storage.root}"
    )
    describer = create_describer(
        conversion.picture_backend,
        storage,
        picture_model=conversion.picture_model,
        picture_ai=conversion.picture_ai,
        announce=console.print,
    )
    with _progress("PDF wird aufbereitet ...") as update:
        result = convert_pdf(
            settings.input_file,
            conversion.options,
            storage,
            describer=describer,
            announce=console.print,
            progress=update,
        )
    _print_conversion(result.stats)
    if conversion.source_text is not None:
        save_source_text(conversion.source_text, result.document.text)
        console.print(f"Aufbereiteter Text: {conversion.source_text}")
    return _generate_from_document(settings, result.document, subdeck_context)


def _generate_from_document(
    settings: GenerateSettings,
    document: SourceDocument,
    subdeck_context: SubdeckContext | None,
) -> list[Card]:
    """Generate cards from prepared document text with progress reporting.

    Args:
        settings: Fully resolved generation settings.
        document: Extracted or converted document text.
        subdeck_context: Parent deck and known subdecks, or None.

    Returns:
        Validated cards from LiteLLM, possibly empty.
    """
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
        task = progress.add_task("Generating cards with AI...", total=None)

        def update(completed: int, total: int, count: int) -> None:
            """Render the latest chunk and unique-card count in the progress UI.

            Args:
                completed: Number of processed document chunks.
                total: Total document chunks in this generation run.
                count: Unique cards accumulated so far.

            Returns:
                None. The Rich progress task is updated in place.
            """
            progress.update(
                task,
                completed=completed,
                total=total,
                description=f"Chunk {completed}/{total}: {count} unique cards",
            )

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


@app.command("export", epilog=EXPORT_EPILOG)
def export_cards(
    cards_file: Path = typer.Argument(
        ...,
        file_okay=True,
        dir_okay=False,
        help="Version-1 card JSON file; bare names may resolve through input_dir.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help=(
            "Destination .apkg; required unless output_dir is configured. Must "
            "be new, or existing with --extend. Parent directories are created."
        ),
    ),
    deck: str | None = typer.Option(
        None,
        "--deck",
        "-d",
        help="Target deck; required unless generation.deck is configured.",
    ),
    extend: bool | None = typer.Option(
        None,
        "--extend/--no-extend",
        help="Extend an existing output or require a new one; overrides YAML.",
    ),
    config_file: Path | None = typer.Option(
        None,
        "--config",
        envvar="ANKI_CONFIG",
        help="YAML configuration path. Default: optional ./config.yaml; may use ANKI_CONFIG.",
    ),
) -> None:
    """Export previously saved JSON without another AI request."""
    config, config_path = load_selected_config(config_file)
    cli_values = _explicit_values(output=output, deck=deck, extend=extend)
    settings = resolve_export_settings(
        {"cards_file": cards_file, **cli_values}, config, config_path
    )
    _validate_output(settings.output, settings.extend)
    cards = deduplicate_cards(load_cards(settings.cards_file))
    result = _write_deck(settings.output, settings.deck, cards, settings.extend)
    _print_result(result, None)


@app.command("decks", epilog=DECKS_EPILOG)
def list_decks(
    package: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="Required readable classic or zstd-compressed .apkg file.",
    ),
) -> None:
    """List normal decks and card counts inside an APKG."""
    rows = inspect_apkg(package)
    table = Table(title=f"Decks in {package.name}")
    table.add_column("Deck")
    table.add_column("Karten", justify="right")
    table.add_column("ID", justify="right")
    for row in rows:
        table.add_row(row["name"], str(row["cards"]), str(row["id"]))
    console.print(table)


def _explicit_values(**values: object) -> dict[str, object]:
    """Discard unset CLI options so YAML and environment defaults can apply.

    Args:
        **values: Option names and values, with None meaning not supplied.

    Returns:
        Only explicitly supplied options; false, zero, and empty strings remain.
    """
    return {name: value for name, value in values.items() if value is not None}


config_app = typer.Typer(
    name="config",
    help="Inspect effective YAML, environment, and CLI configuration.",
    no_args_is_help=True,
)
app.add_typer(config_app)


@config_app.command(
    "show",
    help="Show effective settings and origins without exposing credentials.",
    epilog=(
        "Example: anki-flashcards config show source.pdf --config config.yaml "
        "--output output/deck.apkg\n"
        "The JSON output shows each value's source and only whether an API key is set."
    ),
)
def show_config(
    input_file: Path = typer.Argument(
        ...,
        help="Input filename used to resolve configured directories and defaults.",
    ),
    output: Path | None = typer.Option(None, "--output", "-o"),
    deck: str | None = typer.Option(None, "--deck", "-d"),
    extend: bool | None = typer.Option(None, "--extend/--no-extend"),
    config_file: Path | None = typer.Option(None, "--config", envvar="ANKI_CONFIG"),
    profile: str | None = typer.Option(None, "--profile"),
    pdf_mode: PDFMode | None = typer.Option(None, "--pdf-mode"),
    model: str | None = typer.Option(None, "--model", "-m"),
    limit: int | None = typer.Option(None, "--limit", "-n", min=0),
    language: str | None = typer.Option(None, "--language", "-l"),
    instructions: str | None = typer.Option(None, "--instructions"),
    chunk_size: int | None = typer.Option(None, "--chunk-size", min=1_000, max=100_000),
    api_base: str | None = typer.Option(None, "--api-base"),
    timeout: int | None = typer.Option(None, "--timeout", min=1, max=3_600),
    json_output: Path | None = typer.Option(None, "--json"),
    subdecks: bool | None = typer.Option(None, "--subdecks/--no-subdecks"),
    formulas: bool | None = typer.Option(None, "--formulas/--no-formulas"),
    force_ocr: bool | None = typer.Option(None, "--force-ocr/--no-force-ocr"),
    allow_unreadable: bool | None = typer.Option(None, "--allow-unreadable/--no-allow-unreadable"),
    picture_backend: PictureBackend | None = typer.Option(None, "--picture-backend"),
    picture_profile: str | None = typer.Option(None, "--picture-profile"),
    source_text: Path | None = typer.Option(None, "--source-text"),
) -> None:
    """Resolve and display non-secret effective settings as JSON.

    Args:
        input_file: Source path used for directory and deck resolution.
        output: Optional explicit APKG output override.
        deck: Optional explicit deck override.
        extend: Optional extend/no-extend override.
        config_file: Optional YAML path; ANKI_CONFIG is also supported.
        profile: Optional named YAML profile.
        pdf_mode: Optional local, structured, or native PDF override.
        model: Optional direct provider/model override.
        limit: Optional non-negative card limit.
        language: Optional card language override.
        instructions: Optional additional prompt instructions.
        chunk_size: Optional local-text chunk size.
        api_base: Optional provider endpoint override.
        timeout: Optional request timeout in seconds.
        json_output: Optional JSON destination override.
        subdecks: Optional subdeck-mode override.
        formulas: Optional structured-mode formula recognition override.
        force_ocr: Optional structured-mode full-page OCR override.
        allow_unreadable: Optional structured-mode placeholder override.
        picture_backend: Optional figure-description backend override.
        picture_profile: Optional profile for the profile picture backend.
        source_text: Optional file for the converted Markdown.

    Returns:
        None. A JSON-safe diagnostic view is printed to standard output.
    """
    cli_values = _explicit_values(
        output=output,
        deck=deck,
        extend=extend,
        profile=profile,
        pdf_mode=pdf_mode,
        model=model,
        limit=limit,
        language=language,
        instructions=instructions,
        chunk_size=chunk_size,
        api_base=api_base,
        timeout=timeout,
        json_output=json_output,
        subdecks=subdecks,
        formulas=formulas,
        force_ocr=force_ocr,
        allow_unreadable=allow_unreadable,
        picture_backend=picture_backend,
        picture_profile=picture_profile,
        source_text=source_text,
    )
    config, config_path = load_selected_config(config_file)
    settings = resolve_generate_settings(
        {"input_file": input_file, **cli_values}, config, config_path
    )
    console.print_json(json.dumps(configuration_diagnostics(settings, config_path)))


@contextmanager
def _progress(description: str) -> Iterator[Callable[[str, int, int], None]]:
    """Show a Rich progress line that conversion steps can update.

    Args:
        description: Initial text before the first step reports.

    Returns:
        A context manager yielding ``update(label, completed, total)``.
    """
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
        task = progress.add_task(description, total=None)

        def update(label: str, completed: int, total: int) -> None:
            """Show the current step with its count.

            Args:
                label: Name of the running step.
                completed: Finished items of the step.
                total: All items of the step.

            Returns:
                None. The progress line is updated in place.
            """
            progress.update(task, description=f"{label}: {completed}/{total}")

        yield update


def _print_conversion(stats: ConversionStats) -> None:
    """Report what the structured conversion found and left out.

    Args:
        stats: Statistics of the finished conversion.

    Returns:
        None. A summary and any placeholders are printed.
    """
    console.print(
        f"Aufbereitung: {stats.pages} Seiten, {stats.ocr_pages} mit OCR, "
        f"{stats.tables} Tabellen, {stats.formulas} Formeln, "
        f"{stats.pictures_described} Abbildungen beschrieben, "
        f"{stats.pictures_decorative} dekorative ausgelassen."
    )
    if stats.formulas_skipped:
        console.print(f"Formeln nicht ausgewertet (--no-formulas): {stats.formulas_skipped}")
    if stats.pictures_undescribed:
        console.print(f"Abbildungen ohne Beschreibung: {stats.pictures_undescribed}")
    if stats.unreadable:
        console.print(
            f"[yellow]Nicht lesbar, als Platzhalter markiert:[/yellow] {stats.unreadable}"
        )


models_app = typer.Typer(
    name="models",
    help="Prepare local models for the structured PDF mode.",
    no_args_is_help=True,
)
app.add_typer(models_app)


@models_app.command(
    "download",
    help="Download Docling and picture models into the project models folder.",
    epilog=(
        "Downloads only what the configuration needs: Docling layout, table, OCR, and "
        "classification models, the formula model unless --no-formulas, and the local "
        "picture model for the local picture backend. Everything is stored in "
        "pdf_conversion.models_dir (default: models/ next to the YAML file); nothing is "
        "written to user-wide caches. Afterwards the structured mode works offline.\n"
        "Example: anki-flashcards models download --config config.yaml"
    ),
)
def download_models(
    config_file: Path | None = typer.Option(
        None,
        "--config",
        envvar="ANKI_CONFIG",
        help="YAML configuration path. Default: optional ./config.yaml; may use ANKI_CONFIG.",
    ),
    formulas: bool | None = typer.Option(
        None,
        "--formulas/--no-formulas",
        help="Include the formula model. Default: pdf_conversion.formulas (on).",
        show_default=False,
    ),
    picture_backend: PictureBackend | None = typer.Option(
        None,
        "--picture-backend",
        help="Include the local picture model only for the local backend. Default: YAML.",
    ),
) -> None:
    """Download every model the structured PDF mode needs ahead of time.

    Args:
        config_file: Optional YAML path; ANKI_CONFIG is also supported.
        formulas: Optional override whether the formula model is needed.
        picture_backend: Optional override of the picture backend.

    Returns:
        None. Models are stored in the configured models folder.
    """
    config, config_path = load_selected_config(config_file)
    conversion = config.pdf_conversion
    require_docling()
    storage = configure_model_storage(resolve_models_dir(config, config_path))
    with_formulas = conversion.formulas if formulas is None else formulas
    ensure_conversion_models(storage, formulas=with_formulas, announce=console.print)
    if (picture_backend or conversion.pictures.backend) == PictureBackend.LOCAL:
        ensure_picture_model(storage, conversion.pictures.model, console.print)
    console.print(f"[green]Modelle bereit:[/green] {storage.root}")


def _validate_output(output: Path, extend: bool) -> None:
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


def _write_deck(output: Path, deck: str, cards: list[Card], extend: bool) -> ExportResult:
    """Dispatch a validated write request to APKG creation or extension.

    Args:
        output: Destination APKG path.
        deck: Non-empty target deck name.
        cards: Validated cards to write.
        extend: Whether to preserve and extend an existing package.

    Returns:
        The export result reported to the user.

    Raises:
        FlashcardError: If the deck name is empty or package writing fails.
    """
    if not deck.strip():
        raise FlashcardError("Deck name must not be empty")
    if extend:
        return append_apkg(output, deck, cards)
    return create_apkg(output, deck, cards)


def _print_result(result: ExportResult, json_output: Path | None) -> None:
    """Print export counts, cards per subdeck, package path, and JSON path.

    Args:
        result: Completed APKG export summary.
        json_output: Optional intermediate JSON file that was written.

    Returns:
        None. Human-readable output is written to standard output.
    """
    console.print(
        f"[green]Fertig:[/green] {result.added} Karten in '{result.deck}' "
        f"→ {result.path} ({result.skipped} Duplikate übersprungen)"
    )
    subdecks = {name: count for name, count in result.added_by_deck.items() if name != result.deck}
    if subdecks:
        console.print("Neue Karten je Unterdeck:")
    for name, count in subdecks.items():
        console.print(f"  {name}: {count}")
    if json_output:
        console.print(f"JSON-Zwischendatei: {json_output}")


def run() -> None:
    """Run the CLI and present expected application failures without tracebacks.

    Returns:
        None on successful command completion.

    Raises:
        SystemExit: With status 1 after printing an expected FlashcardError to
            standard error. Exception chaining is suppressed at the CLI boundary
            so users do not see an implementation traceback.
    """
    load_dotenv(find_dotenv(usecwd=True))
    try:
        app()
    except FlashcardError as error:
        error_console.print(f"[red]Fehler:[/red] {error}")
        raise SystemExit(1) from None
