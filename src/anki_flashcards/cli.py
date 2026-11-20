"""Expose document generation, JSON export, and deck inspection as a CLI."""

import json
from pathlib import Path

import typer
from dotenv import find_dotenv, load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TaskID, TextColumn
from rich.table import Table

from anki_flashcards.apkg import ExportResult, inspect_apkg
from anki_flashcards.config import PDFMode, PictureBackend
from anki_flashcards.errors import FlashcardError
from anki_flashcards.pipeline import (
    ConversionFinished,
    Notice,
    NoticeLevel,
    PipelineEvent,
    Stage,
    StageFinished,
    StageProgress,
    StageStarted,
    prepare_models,
    run_export,
    run_generate,
)
from anki_flashcards.settings import (
    configuration_diagnostics,
    load_selected_config,
    resolve_export_settings,
    resolve_generate_settings,
)
from anki_flashcards.structured_pdf import ConversionStats

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
run unless --allow-unreadable is given. structured needs a GPU accelerator
(CUDA, ROCm, MPS, or XPU); without one it stops unless --allow-cpu is given.
Without a GPU, use native (a verified provider model reads the original PDF)
or local (embedded text only). native uploads the original PDF.

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
    allow_cpu: bool | None = typer.Option(
        None,
        "--allow-cpu/--no-allow-cpu",
        help=(
            "Structured mode: run without a GPU accelerator. Default: off; without a "
            "GPU the run stops and suggests --pdf-mode native or --pdf-mode local."
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
        allow_cpu=allow_cpu,
        picture_backend=picture_backend,
        picture_profile=picture_profile,
        source_text=source_text,
    )
    config, config_path = load_selected_config(config_file)
    settings = resolve_generate_settings(
        {"input_file": input_file, **cli_values}, config, config_path
    )
    result = run_generate(settings, report=_ConsoleReporter(console))
    _print_result(result.export, result.json_output)


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
    _print_result(run_export(settings), None)


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
    allow_cpu: bool | None = typer.Option(None, "--allow-cpu/--no-allow-cpu"),
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
        allow_cpu: Optional structured-mode CPU override.
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
        allow_cpu=allow_cpu,
        picture_backend=picture_backend,
        picture_profile=picture_profile,
        source_text=source_text,
    )
    config, config_path = load_selected_config(config_file)
    settings = resolve_generate_settings(
        {"input_file": input_file, **cli_values}, config, config_path
    )
    console.print_json(json.dumps(configuration_diagnostics(settings, config_path)))


class _ConsoleReporter:
    """Render pipeline events on the terminal with Rich.

    Notices are printed as lines, warnings in yellow; each phase shows one
    spinner line that progress events update in place.

    Args:
        target: Console receiving all output.
    """

    def __init__(self, target: Console) -> None:
        """Prepare an idle reporter for one command.

        Args:
            target: Console receiving all output.
        """
        self._console = target
        self._progress: Progress | None = None
        self._task: TaskID | None = None

    def __call__(self, event: PipelineEvent) -> None:
        """Render one event.

        Args:
            event: Event emitted by the pipeline.

        Returns:
            None. Output is written to the console.
        """
        handlers = {
            Notice: self._notice,
            StageStarted: self._start,
            StageProgress: self._advance,
            StageFinished: self._finish,
            ConversionFinished: self._conversion,
        }
        handlers[type(event)](event)

    def _notice(self, event: Notice) -> None:
        """Print a notice; warnings are highlighted.

        Args:
            event: Notice to print.

        Returns:
            None.
        """
        if event.level == NoticeLevel.WARNING:
            self._console.print(f"[yellow]{event.text}[/yellow]")
            return
        self._console.print(event.text)

    def _start(self, event: StageStarted) -> None:
        """Start a spinner line for a phase.

        Args:
            event: Phase start with its initial description.

        Returns:
            None.
        """
        self._progress = Progress(
            SpinnerColumn(), TextColumn("{task.description}"), console=self._console
        )
        self._progress.start()
        self._task = self._progress.add_task(event.description, total=None)

    def _advance(self, event: StageProgress) -> None:
        """Update the spinner line of the running phase.

        Args:
            event: Progress of the running phase.

        Returns:
            None. Events without a running phase are ignored.
        """
        if self._progress is None or self._task is None:
            return
        if event.stage == Stage.GENERATION:
            self._progress.update(
                self._task,
                completed=event.completed,
                total=event.total,
                description=f"Chunk {event.completed}/{event.total}: {event.cards} unique cards",
            )
            return
        self._progress.update(
            self._task, description=f"{event.label}: {event.completed}/{event.total}"
        )

    def _finish(self, event: StageFinished) -> None:
        """Stop the spinner line of the finished phase.

        Args:
            event: Phase end.

        Returns:
            None.
        """
        if self._progress is not None:
            self._progress.stop()
        self._progress = None
        self._task = None

    def _conversion(self, event: ConversionFinished) -> None:
        """Print the statistics of a structured conversion.

        Args:
            event: Finished conversion with its statistics.

        Returns:
            None.
        """
        _print_conversion(event.stats)


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
    root = prepare_models(
        config,
        config_path,
        formulas=formulas,
        picture_backend=picture_backend,
        report=_ConsoleReporter(console),
    )
    console.print(f"[green]Modelle bereit:[/green] {root}")


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
