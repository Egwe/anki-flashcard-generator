"""Test CLI workflows and expected error handling without external AI calls."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from anki_flashcards.cli import app
from anki_flashcards.errors import FlashcardError

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolate_cli_from_user_config(tmp_path: Path, monkeypatch) -> None:
    """Run CLI tests without the developer's local YAML or dotenv overrides.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture used to change directory and clear variables.

    Returns:
        None. Each test starts with empty configuration unless it writes its own.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANKI_CONFIG", raising=False)
    monkeypatch.delenv("ANKI_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_BASE", raising=False)


@pytest.mark.parametrize("command", [[], ["generate"], ["export"], ["decks"], ["config", "show"]])
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
        assert "--subdecks" in normalized and "--no-subdecks" in normalized
        assert "DECK::chapter" in normalized
    if command == ["export"]:
        assert "--deck" in normalized and "-d" in normalized
        assert "required unless generation.deck is configured" in normalized
        assert "No AI request is made" in normalized
        assert "must be a new .apkg file" in normalized
        assert "DECK::subdeck" in normalized
    if command == ["decks"]:
        assert "never modified" in normalized
        assert "zstd-compressed" in normalized
    if command == ["config", "show"]:
        assert "JSON output shows each value's source" in normalized
        assert "API key is set" in normalized


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


@pytest.mark.parametrize("chunk_size", ["1000", "1001"])
def test_generate_accepts_smallest_chunk_sizes(
    tmp_path: Path, monkeypatch, chunk_size: str
) -> None:
    """Verify the smallest allowed chunk sizes reach the model without a crash.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture used to replace the provider call.
        chunk_size: Allowed ``--chunk-size`` value at the lower range limit.

    Returns:
        None. Assertions inspect the exit code and the number of requests.
    """
    from types import SimpleNamespace

    source = tmp_path / "notes.md"
    source.write_text(
        "\n\n".join(f"Absatz {index}: " + "Fakt " * 40 for index in range(20)),
        encoding="utf-8",
    )
    prompts: list[str] = []

    def fake_completion(**kwargs):
        """Record one chunk request and return a single valid card.

        Args:
            **kwargs: LiteLLM options built by the application.

        Returns:
            A LiteLLM-shaped response with one card per chunk.
        """
        prompts.append(kwargs["messages"][-1]["content"])
        payload = {"cards": [{"front": f"Frage {len(prompts)}?", "back": "Antwort"}]}
        message = SimpleNamespace(content=json.dumps(payload))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr("anki_flashcards.ai._completion", fake_completion)
    result = runner.invoke(
        app,
        [
            "generate",
            str(source),
            "--output",
            str(tmp_path / "deck.apkg"),
            "--model",
            "ollama/test",
            "--chunk-size",
            chunk_size,
            "--limit",
            "0",
        ],
    )

    assert result.exit_code == 0, result.output
    assert result.exception is None
    assert len(prompts) > 1
    assert "Absatz 19" in prompts[-1]


def test_generate_uses_yaml_profile_paths_and_cli_overrides(tmp_path: Path, monkeypatch) -> None:
    """Verify the command resolves YAML defaults and explicit CLI precedence.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture used to replace AI generation.

    Returns:
        None. Assertions inspect effective settings and generated output paths.
    """
    import yaml

    from anki_flashcards.models import Card

    source = tmp_path / "input" / "source.txt"
    source.parent.mkdir()
    source.write_text("Ein Fakt aus YAML.", encoding="utf-8")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "default_profile": "local",
                "input_dir": "input",
                "output_dir": "output",
                "generation": {
                    "deck": "YAML Deck",
                    "limit": 1,
                    "extend": True,
                },
                "models": {"local": {"model": "ollama/yaml-model"}},
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_generate(document, settings, **kwargs):
        """Capture resolved generation values and return one card.

        Args:
            document: Resolved local document.
            settings: Resolved provider settings.
            **kwargs: Effective generation options.

        Returns:
            A deterministic one-card list.
        """
        captured["document"] = document
        captured["settings"] = settings
        captured["options"] = kwargs
        return [Card(front="Frage?", back="Antwort")]

    monkeypatch.setattr("anki_flashcards.cli.generate_cards", fake_generate)
    result = runner.invoke(
        app,
        [
            "generate",
            "source.txt",
            "--config",
            str(config_file),
            "--model",
            "ollama/cli-model",
            "--limit",
            "0",
            "--no-extend",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["document"].path == source
    assert captured["settings"].model == "ollama/cli-model"
    assert captured["options"]["limit"] == 0
    assert (tmp_path / "output" / "source.apkg").is_file()


def test_config_show_is_json_and_hides_credentials(tmp_path: Path, monkeypatch) -> None:
    """Verify config show emits non-secret effective settings and origins.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture used to supply a test credential.

    Returns:
        None. Assertions parse JSON and reject any exposed secret value.
    """
    import yaml

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "default_profile": "test",
                "generation": {"limit": 7},
                "models": {
                    "test": {
                        "model": "openai/test",
                        "api_key_env": "CLI_TEST_SECRET",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLI_TEST_SECRET", "do-not-print-this")

    result = runner.invoke(
        app,
        [
            "config",
            "show",
            "source.pdf",
            "--config",
            str(config_file),
            "--output",
            str(tmp_path / "out.apkg"),
        ],
    )

    assert result.exit_code == 0, result.output
    diagnostics = json.loads(result.output)
    assert diagnostics["model"] == "openai/test"
    assert diagnostics["limit"] == 7
    assert diagnostics["sources"]["limit"] == "config"
    assert diagnostics["sources"]["output"] == "cli"
    assert diagnostics["api_key"] == "set (hidden)"
    assert "do-not-print-this" not in result.output


def test_generate_native_pdf_skips_local_extraction_and_exports(
    tmp_path: Path, monkeypatch
) -> None:
    """Verify CLI native mode uploads directly and still creates a normal APKG.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing native and local processing.

    Returns:
        None. Assertions verify native invocation, no local read, and APKG output.
    """
    from anki_flashcards.models import Card

    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-test")
    output = tmp_path / "native.apkg"
    captured = {}

    def fail_read_document(path):
        """Fail when native mode incorrectly reads local PDF text.

        Args:
            path: PDF path that must be uploaded rather than extracted.

        Returns:
            Never returns normally.

        Raises:
            AssertionError: Always, to expose the wrong processing branch.
        """
        raise AssertionError("Native CLI mode must not call read_document")

    def fake_native(path, settings, **kwargs):
        """Capture native settings and return one validated card.

        Args:
            path: Original PDF path.
            settings: Resolved OpenAI settings.
            **kwargs: Effective generation parameters.

        Returns:
            A deterministic one-card list.
        """
        captured["path"] = path
        captured["settings"] = settings
        captured["options"] = kwargs
        return [Card(front="Native?", back="Antwort")]

    monkeypatch.setattr("anki_flashcards.cli.read_document", fail_read_document)
    monkeypatch.setattr("anki_flashcards.cli.generate_native_cards", fake_native)

    result = runner.invoke(
        app,
        [
            "generate",
            str(source),
            "--output",
            str(output),
            "--model",
            "openai/gpt-4o",
            "--pdf-mode",
            "native",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["path"] == source
    assert captured["settings"].model == "openai/gpt-4o"
    assert captured["options"]["limit"] == 50
    assert output.is_file()
    assert "uploading the original document" in result.output


def test_generate_local_mode_never_calls_native_adapter(tmp_path: Path, monkeypatch) -> None:
    """Verify default local PDF processing never invokes native upload.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing native and local processing.

    Returns:
        None. Assertions verify the local branch and generated APKG.
    """
    from anki_flashcards.documents import SourceDocument
    from anki_flashcards.models import Card

    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-test")
    output = tmp_path / "local.apkg"

    def fake_read(path):
        """Return extracted local text for the local-mode command.

        Args:
            path: Local PDF path.

        Returns:
            A source document containing one fact.
        """
        return SourceDocument(path=path, text="Lokaler Fakt")

    def fake_generate(document, settings, **kwargs):
        """Return one card for local generation without a real provider.

        Args:
            document: Locally extracted source document.
            settings: Resolved provider settings.
            **kwargs: Effective generation options.

        Returns:
            A deterministic one-card list.
        """
        return [Card(front="Lokal?", back="Antwort")]

    def fail_native(*args, **kwargs):
        """Fail if local mode invokes the native upload path.

        Args:
            *args: Unused positional arguments.
            **kwargs: Unused keyword arguments.

        Returns:
            Never returns normally.

        Raises:
            AssertionError: Always, to expose unintended upload behavior.
        """
        raise AssertionError("Local mode must not call native adapter")

    monkeypatch.setattr("anki_flashcards.cli.read_document", fake_read)
    monkeypatch.setattr("anki_flashcards.cli.generate_cards", fake_generate)
    monkeypatch.setattr("anki_flashcards.cli.generate_native_cards", fail_native)

    result = runner.invoke(
        app,
        ["generate", str(source), "--output", str(output), "--model", "openai/gpt-4o"],
    )

    assert result.exit_code == 0, result.output
    assert output.is_file()


def test_dotenv_loads_credentials_but_not_legacy_model_override(
    tmp_path: Path, monkeypatch
) -> None:
    """Verify dotenv credentials work while YAML owns the selected model.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture used to change directory and set legacy env.

    Returns:
        None. Assertions check the credential, YAML model, and endpoint.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "TEST_PROVIDER_KEY=credential-from-dotenv\nANKI_MODEL=ollama/llama3.2\n",
        encoding="utf-8",
    )
    (tmp_path / "config.yaml").write_text(
        "default_profile: test\n"
        "models:\n"
        "  test:\n"
        "    model: ollama_chat/qwen3.6:27b\n"
        "    api_base: http://localhost:11434\n"
        "    api_key_env: TEST_PROVIDER_KEY\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("TEST_PROVIDER_KEY", raising=False)

    from anki_flashcards.cli import find_dotenv, load_dotenv
    from anki_flashcards.settings import load_selected_config, resolve_generate_settings

    load_dotenv(find_dotenv(usecwd=True))
    config, config_path = load_selected_config(None)
    settings = resolve_generate_settings(
        {"input_file": Path("source.txt"), "output": Path("out.apkg")},
        config,
        config_path,
    )

    assert settings.ai.api_key == "credential-from-dotenv"
    assert settings.ai.model == "ollama_chat/qwen3.6:27b"
    assert settings.ai.api_base == "http://localhost:11434"


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


def test_installed_cli_error_has_no_traceback(tmp_path: Path) -> None:
    """Verify the real console entry point suppresses implementation tracebacks.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions inspect exit status and standard streams from a
        subprocess using the installed anki-flashcards executable.
    """
    import os
    import subprocess
    import sys

    source = tmp_path / "source.txt"
    source.write_text("Ein Fakt", encoding="utf-8")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "anki_flashcards",
            "generate",
            str(source),
            "--output",
            str(tmp_path / "missing.apkg"),
            "--model",
            "ollama/test",
            "--extend",
        ],
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 1
    assert "Cannot extend missing APKG" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_run_prints_expected_errors_without_a_traceback(monkeypatch, capsys) -> None:
    """Verify expected failures are printed to stderr without a traceback.

    Args:
        monkeypatch: Pytest fixture used to replace CLI and environment loading.
        capsys: Pytest fixture capturing standard output and error streams.

    Returns:
        None. Assertions inspect the emitted error and Typer exit exception.
    """
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
    monkeypatch.setattr("anki_flashcards.cli.load_dotenv", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit):
        run()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Ungültiges Paket" in captured.err
    assert "Traceback" not in captured.err


def test_generate_subdecks_extend_sends_existing_context(tmp_path: Path, monkeypatch) -> None:
    """Verify subdeck mode reads existing subdecks and writes chapter subdecks.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture used to replace card generation.

    Returns:
        None. Assertions inspect the passed context, output, and package decks.
    """
    from anki_flashcards.apkg import create_apkg, inspect_apkg
    from anki_flashcards.models import Card

    source = tmp_path / "kapitel-2.txt"
    source.write_text("Netzwerke bestehen aus Knoten.", encoding="utf-8")
    output = tmp_path / "el1.apkg"
    create_apkg(output, "EL1", [Card(front="Was ist Strom?", back="Fluss", subdeck="Grundlagen")])
    captured = {}

    def fake_generate(document, settings, **kwargs):
        """Capture the subdeck context and return a card for a new subdeck.

        Args:
            document: Extracted source document supplied by the command.
            settings: Provider settings constructed from CLI options.
            **kwargs: Effective generation options including subdecks.

        Returns:
            One card assigned to a new chapter subdeck.
        """
        captured["subdecks"] = kwargs["subdecks"]
        return [Card(front="Was ist ein Knoten?", back="Verbindung", subdeck="Netzwerke")]

    monkeypatch.setattr("anki_flashcards.cli.generate_cards", fake_generate)
    result = runner.invoke(
        app,
        [
            "generate",
            str(source),
            "--output",
            str(output),
            "--deck",
            "EL1",
            "--model",
            "ollama/test",
            "--extend",
            "--subdecks",
        ],
        env={"COLUMNS": "200"},
    )

    assert result.exit_code == 0, result.output
    context = captured["subdecks"]
    assert context.parent == "EL1"
    assert [subdeck.name for subdeck in context.existing] == ["Grundlagen"]
    assert context.existing[0].examples == ("Was ist Strom?",)
    assert "1 vorhandene Unterdecks" in result.output
    assert "EL1::Netzwerke: 1" in result.output
    names = {row["name"] for row in inspect_apkg(output)}
    assert {"EL1::Grundlagen", "EL1::Netzwerke"} <= names


@pytest.mark.parametrize(("flag", "expected"), [(["--subdecks"], "EL1"), ([], None)])
def test_generate_passes_subdeck_context_only_when_enabled(
    tmp_path: Path, monkeypatch, flag: list[str], expected: str | None
) -> None:
    """Verify a new package gets an empty context and normal mode gets none.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture used to replace card generation.
        flag: Optional subdeck CLI flag.
        expected: Expected parent deck of the context, or None.

    Returns:
        None. Assertions inspect the context passed to generation.
    """
    from anki_flashcards.models import Card

    source = tmp_path / "vl.txt"
    source.write_text("Ein Fakt.", encoding="utf-8")
    captured = {}

    def fake_generate(document, settings, **kwargs):
        """Capture the subdeck context and return one card.

        Args:
            document: Extracted source document supplied by the command.
            settings: Provider settings constructed from CLI options.
            **kwargs: Effective generation options including subdecks.

        Returns:
            One deterministic card.
        """
        captured["subdecks"] = kwargs["subdecks"]
        return [Card(front="F?", back="A")]

    monkeypatch.setattr("anki_flashcards.cli.generate_cards", fake_generate)
    result = runner.invoke(
        app,
        [
            "generate",
            str(source),
            "-o",
            str(tmp_path / "new.apkg"),
            "-d",
            "EL1",
            "-m",
            "ollama/test",
            *flag,
        ],
    )

    assert result.exit_code == 0, result.output
    context = captured["subdecks"]
    assert (context.parent if context else None) == expected
    assert context is None or context.existing == ()


def test_export_places_json_subdecks_below_deck(tmp_path: Path) -> None:
    """Verify export writes cards with a JSON subdeck into Deck::subdeck.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions inspect the exported deck names.
    """
    from anki_flashcards.apkg import inspect_apkg
    from anki_flashcards.models import Card, save_cards

    cards_file = tmp_path / "cards.json"
    save_cards(
        cards_file,
        [Card(front="A?", back="1", subdeck="Grundlagen"), Card(front="B?", back="2")],
        deck="EL1",
    )
    output = tmp_path / "el1.apkg"

    result = runner.invoke(app, ["export", str(cards_file), "-o", str(output), "-d", "EL1"])

    assert result.exit_code == 0, result.output
    counts = {row["name"]: row["cards"] for row in inspect_apkg(output)}
    assert counts["EL1::Grundlagen"] == 1
    assert counts["EL1"] == 1


def test_config_show_reports_subdeck_mode(tmp_path: Path) -> None:
    """Verify diagnostics show the effective subdeck mode and its source.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions inspect the JSON diagnostic output.
    """
    result = runner.invoke(
        app, ["config", "show", "source.txt", "-o", str(tmp_path / "x.apkg"), "--subdecks"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["subdecks"] is True
    assert payload["sources"]["subdecks"] == "cli"
