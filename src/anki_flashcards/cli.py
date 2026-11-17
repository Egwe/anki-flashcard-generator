"""Expose document generation, JSON export, and deck inspection as a CLI."""

import os
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from anki_flashcards.ai import AISettings, generate_cards
from anki_flashcards.apkg import ExportResult, append_apkg, create_apkg, inspect_apkg
from anki_flashcards.documents import read_document
from anki_flashcards.errors import FlashcardError
from anki_flashcards.models import Card, deduplicate_cards, load_cards, save_cards

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

Examples:
  anki-flashcards generate skript.pdf -o output/biologie.apkg -m ollama/llama3.2
  anki-flashcards generate kapitel.docx -o output/deck.apkg -d Biologie --extend
  anki-flashcards generate notes.md -o output/notes.apkg -n 0 --json output/cards.json
"""
EXPORT_EPILOG = """
The input must be a version-1 card JSON file previously written with --json or
created with the same schema. No AI request is made. Without --extend, --output
must be a new .apkg file; with --extend, it must already exist. The deck is a
required explicit target. New parent directories are created automatically.

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
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="Local PDF, DOCX, HTML, Markdown, or UTF-8 text file; required.",
    ),
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help=(
            "Required destination .apkg. Must be new, or an existing package "
            "with --extend. Missing parent directories are created."
        ),
    ),
    deck: str | None = typer.Option(
        None,
        "--deck",
        "-d",
        help="Target deck name; use '::' for subdecks. Default: input filename stem.",
    ),
    extend: bool = typer.Option(
        False,
        "--extend",
        help=(
            "Append to an existing --output instead of creating one; preserves "
            "cards/review states, skips duplicates, creates the deck if absent."
        ),
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        envvar="ANKI_MODEL",
        help=(
            "LiteLLM provider/model, for example ollama/llama3.2 or "
            "openai/gpt-4o-mini. May also be set with ANKI_MODEL."
        ),
    ),
    limit: int = typer.Option(
        50,
        "--limit",
        "-n",
        min=0,
        help="Maximum cards across all chunks, >= 0. Default: 50; 0 = unlimited.",
        show_default=False,
    ),
    language: str = typer.Option(
        "Deutsch",
        "--language",
        "-l",
        help="Natural language for generated questions and answers. Default: Deutsch.",
        show_default=False,
    ),
    instructions: str = typer.Option(
        "",
        "--instructions",
        help="Optional additional card guidance; default: no extra instructions.",
        show_default=False,
    ),
    chunk_size: int = typer.Option(
        24_000,
        "--chunk-size",
        min=1_000,
        max=100_000,
        help=(
            "Maximum source characters per AI request, 1000..100000. "
            "Default: 24000; adjacent chunks overlap by 500 characters."
        ),
        show_default=False,
    ),
    api_base: str | None = typer.Option(
        None,
        "--api-base",
        help=(
            "Optional provider endpoint override. May also be set with "
            "LLM_API_BASE; provider defaults are used otherwise."
        ),
    ),
    timeout: int = typer.Option(
        180,
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
) -> None:
    """Generate cards from PDF, DOCX, HTML, Markdown, or text."""
    deck_name = deck or input_file.stem
    _validate_output(output, extend)
    document = read_document(input_file)
    settings = AISettings(
        model=model or os.getenv("ANKI_MODEL", ""),
        api_base=api_base,
        timeout=timeout,
    )
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

        cards = generate_cards(
            document,
            settings,
            limit=limit,
            language=language,
            instructions=instructions,
            chunk_size=chunk_size,
            progress=update,
        )
    if not cards:
        raise FlashcardError("The AI did not return any usable cards")

    if json_output:
        save_cards(json_output, cards, deck=deck_name, source=str(input_file))
    result = _write_deck(output, deck_name, cards, extend)
    _print_result(result, json_output)


@app.command("export", epilog=EXPORT_EPILOG)
def export_cards(
    cards_file: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="Required version-1 card JSON file; no AI provider is called.",
    ),
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help=(
            "Required destination .apkg. Must be new, or an existing package "
            "with --extend. Missing parent directories are created."
        ),
    ),
    deck: str = typer.Option(
        ...,
        "--deck",
        "-d",
        help="Required target deck name; use '::' for subdecks.",
    ),
    extend: bool = typer.Option(
        False,
        "--extend",
        help=(
            "Append to an existing --output instead of creating one; preserves "
            "existing data and skips duplicate questions."
        ),
    ),
) -> None:
    """Export previously saved JSON without another AI request."""
    _validate_output(output, extend)
    cards = deduplicate_cards(load_cards(cards_file))
    result = _write_deck(output, deck, cards, extend)
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
    """Print export counts, package path, and optional JSON path.

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
    if json_output:
        console.print(f"JSON-Zwischendatei: {json_output}")


def run() -> None:
    """Run the CLI and present expected application failures without tracebacks.

    Returns:
        None on successful command completion.

    Raises:
        typer.Exit: With status 1 after printing an expected FlashcardError to
            standard error.
    """
    load_dotenv()
    try:
        app()
    except FlashcardError as error:
        error_console.print(f"[red]Fehler:[/red] {error}")
        raise typer.Exit(1) from error
