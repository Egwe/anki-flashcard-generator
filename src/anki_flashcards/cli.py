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

app = typer.Typer(
    name="anki-flashcards",
    help="Generate Anki decks from local documents using AI.",
    no_args_is_help=True,
)
console = Console()
error_console = Console(stderr=True)


@app.command()
def generate(
    input_file: Path = typer.Argument(
        ..., exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True
    ),
    output: Path = typer.Option(..., "--output", "-o", help="Target .apkg file"),
    deck: str | None = typer.Option(None, "--deck", "-d", help="Anki deck name"),
    extend: bool = typer.Option(False, "--extend", help="Extend an existing APKG"),
    model: str | None = typer.Option(
        None, "--model", "-m", envvar="ANKI_MODEL", help="LiteLLM provider/model"
    ),
    limit: int = typer.Option(50, "--limit", "-n", min=0, help="Card limit; 0 is unlimited"),
    language: str = typer.Option("Deutsch", "--language", "-l", help="Card language"),
    instructions: str = typer.Option("", "--instructions", help="Additional card guidance"),
    chunk_size: int = typer.Option(24_000, "--chunk-size", min=1_000, max=100_000),
    api_base: str | None = typer.Option(None, "--api-base", help="Custom provider endpoint"),
    timeout: int = typer.Option(180, "--timeout", min=1, max=3_600),
    json_output: Path | None = typer.Option(None, "--json", help="Also save reviewable card JSON"),
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


@app.command("export")
def export_cards(
    cards_file: Path = typer.Argument(
        ..., exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True
    ),
    output: Path = typer.Option(..., "--output", "-o", help="Target .apkg file"),
    deck: str = typer.Option(..., "--deck", "-d", help="Anki deck name"),
    extend: bool = typer.Option(False, "--extend", help="Extend an existing APKG"),
) -> None:
    """Export previously saved JSON without another AI request."""
    _validate_output(output, extend)
    cards = deduplicate_cards(load_cards(cards_file))
    result = _write_deck(output, deck, cards, extend)
    _print_result(result, None)


@app.command("decks")
def list_decks(
    package: Path = typer.Argument(
        ..., exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True
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
    if output.suffix.casefold() != ".apkg":
        raise FlashcardError("Output path must end in .apkg")
    if extend and not output.is_file():
        raise FlashcardError(f"Cannot extend missing APKG: {output}")
    if not extend and output.exists():
        raise FlashcardError(f"Output already exists: {output}. Use --extend or another path.")


def _write_deck(output: Path, deck: str, cards: list[Card], extend: bool) -> ExportResult:
    if not deck.strip():
        raise FlashcardError("Deck name must not be empty")
    if extend:
        return append_apkg(output, deck, cards)
    return create_apkg(output, deck, cards)


def _print_result(result: ExportResult, json_output: Path | None) -> None:
    console.print(
        f"[green]Fertig:[/green] {result.added} Karten in '{result.deck}' "
        f"→ {result.path} ({result.skipped} Duplikate übersprungen)"
    )
    if json_output:
        console.print(f"JSON-Zwischendatei: {json_output}")


def run() -> None:
    load_dotenv()
    try:
        app()
    except FlashcardError as error:
        error_console.print(f"[red]Fehler:[/red] {error}")
        raise typer.Exit(1) from error
