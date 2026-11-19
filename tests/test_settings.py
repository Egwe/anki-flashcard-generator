"""Test configuration precedence, paths, profiles, and safe diagnostics."""

from pathlib import Path

import pytest

from anki_flashcards.config import AppConfig, GenerationConfig, ModelProfile, PDFMode
from anki_flashcards.documents import read_document
from anki_flashcards.errors import FlashcardError
from anki_flashcards.settings import (
    configuration_diagnostics,
    load_selected_config,
    resolve_export_settings,
    resolve_generate_settings,
)


def configured(tmp_path: Path) -> AppConfig:
    """Build a configuration with a profile, paths, and non-default values.

    Args:
        tmp_path: Isolated directory represented in relative YAML paths.

    Returns:
        Typed application configuration for precedence and path tests.
    """
    return AppConfig(
        default_profile="test",
        input_dir=Path("inputs"),
        output_dir=Path("outputs"),
        generation=GenerationConfig(
            deck="YAML Deck",
            limit=7,
            language="Englisch",
            instructions="YAML instructions",
            chunk_size=2_000,
            timeout=90,
            json_output=Path("cards.json"),
            extend=True,
            pdf_mode=PDFMode.LOCAL,
        ),
        models={
            "test": ModelProfile(
                model="openai/yaml-model",
                api_base="http://yaml.invalid/v1",
                api_key_env="TEST_PROVIDER_KEY",
                timeout=70,
                pdf_mode=PDFMode.NATIVE,
                options={"temperature": 0.2},
            )
        },
    )


def test_yaml_values_and_paths_apply(tmp_path: Path, monkeypatch) -> None:
    """Verify YAML defaults, profile fallback, and config-relative paths.

    Args:
        tmp_path: Isolated directory containing the hypothetical YAML file.
        monkeypatch: Pytest fixture used to supply a profile credential.

    Returns:
        None. Assertions inspect every major resolved setting and path.
    """
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-value")
    config = configured(tmp_path)
    config_path = tmp_path / "config.yaml"

    settings = resolve_generate_settings({"input_file": Path("source.pdf")}, config, config_path)

    assert settings.input_file == tmp_path / "inputs" / "source.pdf"
    assert settings.output == tmp_path / "outputs" / "source.apkg"
    assert settings.deck == "YAML Deck"
    assert settings.extend is True
    assert settings.limit == 7
    assert settings.language == "Englisch"
    assert settings.instructions == "YAML instructions"
    assert settings.chunk_size == 2_000
    assert settings.json_output == tmp_path / "outputs" / "cards.json"
    assert settings.ai.model == "openai/yaml-model"
    assert settings.ai.api_base == "http://yaml.invalid/v1"
    assert settings.ai.api_key == "secret-value"
    assert settings.ai.timeout == 90
    assert settings.ai.options == {"temperature": 0.2}
    assert settings.pdf_mode == PDFMode.LOCAL


def test_nonsecret_environment_values_do_not_override_yaml_and_cli_wins(
    tmp_path: Path, monkeypatch
) -> None:
    """Verify model/endpoint environment values cannot override YAML or CLI.

    Args:
        tmp_path: Isolated directory containing configuration paths.
        monkeypatch: Pytest fixture used to set legacy non-secret variables.

    Returns:
        None. Assertions prove YAML remains primary and explicit CLI values win.
    """
    monkeypatch.setenv("ANKI_MODEL", "ollama/llama3.2")
    monkeypatch.setenv("LLM_API_BASE", "http://environment.invalid/v1")
    config = configured(tmp_path)

    yaml_settings = resolve_generate_settings(
        {"input_file": Path("source.pdf")}, config, tmp_path / "config.yaml"
    )
    cli_settings = resolve_generate_settings(
        {
            "input_file": Path("cli/source.pdf"),
            "output": Path("cli-output.apkg"),
            "deck": "CLI Deck",
            "extend": False,
            "model": "ollama/cli-model",
            "limit": 0,
            "language": "Deutsch",
            "instructions": "",
            "chunk_size": 3_000,
            "api_base": "http://cli.invalid/v1",
            "timeout": 12,
            "json_output": Path("cli-cards.json"),
            "pdf_mode": PDFMode.NATIVE,
        },
        config,
        tmp_path / "config.yaml",
    )

    assert yaml_settings.ai.model == "openai/yaml-model"
    assert yaml_settings.ai.api_base == "http://yaml.invalid/v1"
    assert yaml_settings.origins["model"] == "config"
    assert yaml_settings.origins["api_base"] == "config"
    assert cli_settings.input_file == Path.cwd() / "cli/source.pdf"
    assert cli_settings.output == Path.cwd() / "cli-output.apkg"
    assert cli_settings.deck == "CLI Deck"
    assert cli_settings.extend is False
    assert cli_settings.ai.model == "ollama/cli-model"
    assert cli_settings.ai.api_base == "http://cli.invalid/v1"
    assert cli_settings.ai.timeout == 12
    assert cli_settings.limit == 0
    assert cli_settings.instructions == ""
    assert cli_settings.chunk_size == 3_000
    assert cli_settings.json_output == Path.cwd() / "cli-cards.json"
    assert cli_settings.pdf_mode == PDFMode.NATIVE


def test_profile_timeout_and_pdf_mode_fallback(tmp_path: Path) -> None:
    """Verify omitted generation overrides inherit profile settings.

    Args:
        tmp_path: Isolated directory containing configuration paths.

    Returns:
        None. Assertions inspect profile timeout and native PDF mode.
    """
    config = AppConfig(
        default_profile="test",
        models={"test": ModelProfile(model="openai/test", timeout=75, pdf_mode="native")},
    )

    settings = resolve_generate_settings(
        {"input_file": Path("source.pdf"), "output": Path("out.apkg")},
        config,
        tmp_path / "config.yaml",
    )

    assert settings.ai.timeout == 75
    assert settings.pdf_mode == PDFMode.NATIVE


def test_export_uses_yaml_defaults_and_cli_negative_extend(tmp_path: Path) -> None:
    """Verify export derives paths and honors --no-extend over YAML true.

    Args:
        tmp_path: Isolated directory containing configuration paths.

    Returns:
        None. Assertions inspect output, deck, and effective extend flag.
    """
    settings = resolve_export_settings(
        {"cards_file": Path("cards.json"), "extend": False},
        configured(tmp_path),
        tmp_path / "config.yaml",
    )

    assert settings.cards_file == tmp_path / "inputs" / "cards.json"
    assert settings.output == tmp_path / "outputs" / "cards.apkg"
    assert settings.deck == "YAML Deck"
    assert settings.extend is False


def test_explicit_config_environment_path_is_loaded(tmp_path: Path, monkeypatch) -> None:
    """Verify ANKI_CONFIG selects a YAML file when --config is absent.

    Args:
        tmp_path: Isolated directory containing the YAML file.
        monkeypatch: Pytest fixture used to set ANKI_CONFIG and change directory.

    Returns:
        None. Assertions inspect selected path and loaded profile.
    """
    path = tmp_path / "custom.yaml"
    path.write_text("default_profile: null\n", encoding="utf-8")
    monkeypatch.setenv("ANKI_CONFIG", str(path))
    monkeypatch.chdir(tmp_path)

    config, config_path = load_selected_config(None)

    assert config == AppConfig()
    assert config_path == path.absolute()


def test_missing_configured_input_reports_resolved_path(tmp_path: Path) -> None:
    """Verify a missing YAML-resolved input reports the effective full path.

    Args:
        tmp_path: Isolated directory containing configuration paths.

    Returns:
        None. The assertion requires FlashcardError naming the resolved input.
    """
    settings = resolve_generate_settings(
        {"input_file": Path("missing.pdf")}, configured(tmp_path), tmp_path / "config.yaml"
    )

    with pytest.raises(FlashcardError, match=str(settings.input_file)):
        read_document(settings.input_file)


def test_builtin_defaults_are_reported_without_yaml() -> None:
    """Verify absent YAML marks scalar defaults as built-in rather than config.

    Returns:
        None. Assertions inspect source labels for default scalar settings.
    """
    settings = resolve_generate_settings(
        {"input_file": Path("source.txt"), "output": Path("out.apkg")},
        AppConfig(),
        None,
    )

    diagnostics = configuration_diagnostics(settings, None)

    assert diagnostics["sources"]["limit"] == "built-in"
    assert diagnostics["sources"]["extend"] == "built-in"
    assert diagnostics["sources"]["pdf_mode"] == "built-in"
    assert diagnostics["sources"]["timeout"] == "built-in"


def test_diagnostics_hide_secret_values_and_include_sources(tmp_path: Path, monkeypatch) -> None:
    """Verify diagnostics expose origins but never actual credential values.

    Args:
        tmp_path: Isolated directory containing configuration paths.
        monkeypatch: Pytest fixture used to set a distinctive secret value.

    Returns:
        None. Assertions inspect redaction and origin metadata.
    """
    monkeypatch.setenv("TEST_PROVIDER_KEY", "never-print-this-key")
    settings = resolve_generate_settings(
        {"input_file": Path("source.pdf"), "model": "openai/cli-model"},
        configured(tmp_path),
        tmp_path / "config.yaml",
    )

    diagnostics = configuration_diagnostics(settings, tmp_path / "config.yaml")
    serialized = str(diagnostics)

    assert diagnostics["api_key"] == "set (hidden)"
    assert diagnostics["sources"]["model"] == "cli"
    assert diagnostics["sources"]["limit"] == "config"
    assert diagnostics["sources"]["api_base"] == "config"
    assert diagnostics["sources"]["output"] == "config"
    assert diagnostics["sources"]["pdf_mode"] == "config"
    assert diagnostics["provider_options"] == ["temperature"]
    assert "never-print-this-key" not in serialized


def test_subdeck_mode_follows_default_yaml_and_cli_precedence(tmp_path: Path) -> None:
    """Verify subdeck mode is off by default and CLI overrides YAML both ways.

    Args:
        tmp_path: Isolated directory used as YAML location.

    Returns:
        None. Assertions inspect effective values, sources, and diagnostics.
    """
    base = {"input_file": Path("source.txt"), "output": Path("out.apkg")}
    yaml_on = AppConfig(generation=GenerationConfig(subdecks=True))
    config_path = tmp_path / "config.yaml"

    default = resolve_generate_settings(base, AppConfig(), None)
    from_yaml = resolve_generate_settings(base, yaml_on, config_path)
    cli_off = resolve_generate_settings({**base, "subdecks": False}, yaml_on, config_path)
    cli_on = resolve_generate_settings({**base, "subdecks": True}, AppConfig(), None)

    assert default.subdecks is False
    assert default.origins["subdecks"] == "built-in"
    assert from_yaml.subdecks is True
    assert from_yaml.origins["subdecks"] == "config"
    assert cli_off.subdecks is False
    assert cli_off.origins["subdecks"] == "cli"
    assert configuration_diagnostics(cli_on, None)["subdecks"] is True
