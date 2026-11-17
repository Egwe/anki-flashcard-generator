"""Test CLI workflows and expected error handling without external AI calls."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from anki_flashcards.cli import app
from anki_flashcards.errors import FlashcardError

runner = CliRunner()


@pytest.mark.parametrize("command", [[], ["generate"], ["export"], ["decks"]])
def test_help_documents_usage_defaults_files_and_examples(command: list[str]) -> None:
    """Verify every CLI help page includes its operational contract.

    Args:
        command: Command path supplied by pytest, without ``--help``.

    Returns:
        None. Assertions inspect exit status and rendered Rich help text.
    """
    result = runner.invoke(app, [*command, "--help"], env={"COLUMNS": "200"})

    assert result.exit_code == 0, result.output
    normalized = " ".join(result.output.split())
    assert "Example" in normalized
    assert "Usage:" in normalized
    if not command:
        assert "generate" in normalized
        assert "export" in normalized
        assert "decks" in normalized
        assert "0 on success" in normalized
        assert "2 for invalid CLI usage" in normalized
    if command == ["generate"]:
        assert "--output" in normalized and "-o" in normalized
        assert "--model" in normalized and "-m" in normalized
        assert "--limit" in normalized and "-n" in normalized
        assert "Default: 50" in normalized
        assert "0 = unlimited" in normalized
        assert "1000..100000" in normalized
        assert "Default: 180" in normalized
        assert "PDF, DOCX, HTML, Markdown, or UTF-8" in normalized
        assert "With --extend, it must already exist" in normalized
    if command == ["export"]:
        assert "--deck" in normalized and "-d" in normalized
        assert "Required target deck name" in normalized
        assert "No AI request is made" in normalized
        assert "must be a new .apkg file" in normalized
    if command == ["decks"]:
        assert "never modified" in normalized
        assert "zstd-compressed" in normalized


def test_short_help_and_invalid_usage_exit_codes() -> None:
    """Verify -h succeeds and missing required input uses usage exit code 2.

    Returns:
        None. Assertions inspect both exit codes and the usage error stream.
    """
    help_result = runner.invoke(app, ["-h"])
    invalid_result = runner.invoke(app, ["generate"])

    assert help_result.exit_code == 0
    assert "Usage:" in help_result.output
    assert invalid_result.exit_code == 2
    assert "Usage" in invalid_result.stderr
    assert "Missing argument" in invalid_result.stderr


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
    assert captured.out == ""
    assert "Ungültiges Paket" in captured.err
    assert "Traceback" not in captured.err
