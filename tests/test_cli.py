"""Test CLI workflows and expected error handling without external AI calls."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from anki_flashcards.cli import app
from anki_flashcards.errors import FlashcardError

runner = CliRunner()


def test_export_command_creates_apkg_without_ai(tmp_path: Path) -> None:
    """Verify JSON export creates an APKG without invoking an AI provider.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions inspect exit status, output file, and success text.
    """
    cards_file = tmp_path / "cards.json"
    cards_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cards": [{"front": "Frage?", "back": "Antwort"}],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "deck.apkg"

    result = runner.invoke(
        app,
        ["export", str(cards_file), "--output", str(output), "--deck", "Test"],
    )

    assert result.exit_code == 0, result.output
    assert output.is_file()
    assert "1 Karten" in result.output


def test_generate_command_uses_document_and_writes_json(tmp_path: Path, monkeypatch) -> None:
    """Verify the generate command passes source and model and writes both outputs.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture used to replace card generation.

    Returns:
        None. Assertions inspect captured settings and generated files.
    """
    from anki_flashcards.models import Card

    source = tmp_path / "source.txt"
    source.write_text("Ein ausreichend langer Fakt für die KI.", encoding="utf-8")
    output = tmp_path / "deck.apkg"
    cards_file = tmp_path / "cards.json"
    captured = {}

    def fake_generate(document, settings, **kwargs):
        """Capture generation inputs and return one deterministic card.

        Args:
            document: Extracted source document supplied by the command.
            settings: Provider settings constructed from CLI options.
            **kwargs: Additional generation options not inspected by this test.

        Returns:
            A one-card list suitable for APKG and JSON export.
        """
        captured["text"] = document.text
        captured["settings"] = settings
        return [Card(front="Frage?", back="Antwort")]

    monkeypatch.setattr("anki_flashcards.cli.generate_cards", fake_generate)
    result = runner.invoke(
        app,
        [
            "generate",
            str(source),
            "--output",
            str(output),
            "--model",
            "ollama/test",
            "--json",
            str(cards_file),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["text"] == "Ein ausreichend langer Fakt für die KI."
    assert captured["settings"].model == "ollama/test"
    assert output.is_file()
    assert cards_file.is_file()


def test_extend_requires_existing_output(tmp_path: Path) -> None:
    """Verify extend mode rejects a missing APKG before writing cards.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions require a nonzero exit and FlashcardError.
    """
    cards_file = tmp_path / "cards.json"
    cards_file.write_text(
        '{"schema_version": 1, "cards": [{"front": "F?", "back": "A"}]}',
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "export",
            str(cards_file),
            "--output",
            str(tmp_path / "missing.apkg"),
            "--deck",
            "Test",
            "--extend",
        ],
    )

    assert result.exit_code == 1
    assert isinstance(result.exception, FlashcardError)


def test_run_prints_expected_errors_without_a_traceback(monkeypatch, capsys) -> None:
    """Verify expected failures are printed to stderr without a traceback.

    Args:
        monkeypatch: Pytest fixture used to replace CLI and environment loading.
        capsys: Pytest fixture capturing standard output and error streams.

    Returns:
        None. Assertions inspect the emitted error and Typer exit exception.
    """
    import typer

    from anki_flashcards.cli import run

    def fail() -> None:
        """Raise an expected application error instead of running the CLI.

        Returns:
            None. The function always raises before returning.

        Raises:
            FlashcardError: Deliberate failure used to test presentation.
        """
        raise FlashcardError("Ungültiges Paket")

    monkeypatch.setattr("anki_flashcards.cli.app", fail)
    monkeypatch.setattr("anki_flashcards.cli.load_dotenv", lambda: None)

    with pytest.raises(typer.Exit):
        run()

    captured = capsys.readouterr()
    assert "Ungültiges Paket" in captured.err
    assert "Traceback" not in captured.err
