"""Test versioned YAML configuration, model profiles, and safe persistence."""

from pathlib import Path

import pytest
import yaml

from anki_flashcards.config import (
    AppConfig,
    GenerationConfig,
    ModelProfile,
    PDFMode,
    load_config,
    save_config,
)
from anki_flashcards.errors import FlashcardError


def write_yaml(path: Path, payload: object) -> None:
    """Serialize a test configuration to an isolated YAML file.

    Args:
        path: Destination file in a temporary test directory.
        payload: YAML-serializable test object.

    Returns:
        None. The file is written in UTF-8.
    """
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")


def test_missing_implicit_file_uses_defaults(tmp_path: Path, monkeypatch) -> None:
    """Verify absent implicit config.yaml preserves built-in defaults.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture used to change the working directory.

    Returns:
        None. Assertions compare default values and empty profile selection.
    """
    monkeypatch.chdir(tmp_path)

    config = load_config()

    assert config == AppConfig()
    assert config.generation.limit == 50
    assert config.generation.pdf_mode is None
    assert config.generation.timeout is None
    assert config.selected_profile() is None


def test_empty_file_uses_defaults(tmp_path: Path) -> None:
    """Verify an empty explicit YAML file is equivalent to an empty object.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. The assertion compares the parsed result with default config.
    """
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")

    assert load_config(path) == AppConfig()


def test_missing_explicit_file_is_an_error(tmp_path: Path) -> None:
    """Verify an explicitly requested missing configuration is not ignored.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. The assertion requires a readable FlashcardError.
    """
    with pytest.raises(FlashcardError, match="Could not read configuration"):
        load_config(tmp_path / "missing.yaml")


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"schema_version": 2}, "schema_version"),
        ({"unknown": True}, "unknown"),
        ({"generation": {"limit": -1}}, "limit"),
        ({"default_profile": "missing"}, "Unknown model profile"),
        (
            {
                "models": {
                    "test": {
                        "model": "openai/test",
                        "api_key_env": "actual-secret-value!",
                    }
                }
            },
            "api_key_env",
        ),
        (
            {"models": {"test": {"model": "openai/test", "options": {"api_key": "bad"}}}},
            "reserved or may expose a secret",
        ),
        (
            {"models": {"test": {"model": "openai/test", "options": {"access_token": "bad"}}}},
            "reserved or may expose a secret",
        ),
    ],
)
def test_invalid_schema_and_secrets_are_rejected(payload: object, match: str) -> None:
    """Verify malformed values, unknown keys, and inline secrets are rejected.

    Args:
        payload: Invalid application configuration candidate.
        match: Expected validation error fragment.

    Returns:
        None. Assertions require a Pydantic validation failure.
    """
    with pytest.raises(ValueError, match=match):
        AppConfig.model_validate(payload)


def test_non_object_yaml_is_a_user_facing_error(tmp_path: Path) -> None:
    """Verify a YAML list is rejected at the configuration-loading boundary.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. The assertion requires a descriptive object-type error.
    """
    path = tmp_path / "list.yaml"
    write_yaml(path, ["not", "an", "object"])

    with pytest.raises(FlashcardError, match="must contain a YAML object"):
        load_config(path)


def test_invalid_yaml_is_a_user_facing_error(tmp_path: Path) -> None:
    """Verify malformed YAML is translated to FlashcardError.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. The assertion requires the configuration path in the error.
    """
    path = tmp_path / "broken.yaml"
    path.write_text("models: [", encoding="utf-8")

    with pytest.raises(FlashcardError, match="Could not read configuration"):
        load_config(path)


def test_profile_resolution_and_round_trip(tmp_path: Path) -> None:
    """Verify a provider profile resolves and survives atomic YAML persistence.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions compare the selected profile and complete round trip.
    """
    profile = ModelProfile(
        model="openai/gpt-4o-mini",
        api_key_env="OPENAI_API_KEY",
        timeout=90,
        options={"temperature": 0.2},
    )
    config = AppConfig(
        default_profile="openai",
        input_dir=Path("input"),
        output_dir=Path("output"),
        generation=GenerationConfig(limit=12, pdf_mode=PDFMode.NATIVE),
        models={"openai": profile},
    )
    path = tmp_path / "nested" / "config.yaml"

    save_config(path, config)
    loaded = load_config(path)

    assert loaded == config
    assert loaded.selected_profile_name() == "openai"
    assert loaded.selected_profile() == profile
    assert "OPENAI_API_KEY" in path.read_text(encoding="utf-8")
    assert list(path.parent.iterdir()) == [path]


def test_failed_save_preserves_existing_file(tmp_path: Path, monkeypatch) -> None:
    """Verify a serialization failure cannot replace an existing configuration.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture used to force YAML serialization failure.

    Returns:
        None. Assertions check the error and unchanged original file.
    """
    path = tmp_path / "config.yaml"
    path.write_text("original", encoding="utf-8")

    def fail_dump(*args, **kwargs) -> str:
        """Raise a deterministic serializer error for atomic-write testing.

        Args:
            *args: Unused positional serializer arguments.
            **kwargs: Unused keyword serializer arguments.

        Returns:
            Never returns normally.

        Raises:
            TypeError: Deliberate serialization failure.
        """
        raise TypeError("unsupported value")

    monkeypatch.setattr("anki_flashcards.config.yaml.safe_dump", fail_dump)

    with pytest.raises(FlashcardError, match="Could not save configuration"):
        save_config(path, AppConfig())

    assert path.read_text(encoding="utf-8") == "original"
    assert list(tmp_path.iterdir()) == [path]


def test_example_configuration_is_valid_and_covers_required_providers() -> None:
    """Verify the committed example loads and includes all required providers.

    Returns:
        None. Assertions inspect profile names and provider prefixes.
    """
    config = load_config(Path("config.example.yaml"))

    assert config.default_profile == "ollama-local"
    providers = {profile.model.split("/", 1)[0] for profile in config.models.values()}
    assert {"ollama_chat", "openai", "anthropic", "gemini", "moonshot"} <= providers
    assert config.models["ollama-local"].pdf_mode == PDFMode.LOCAL
    assert config.models["openai-native-pdf"].pdf_mode == PDFMode.NATIVE
    assert config.generation.pdf_mode == PDFMode.LOCAL
