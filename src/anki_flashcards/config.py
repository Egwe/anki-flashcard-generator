"""Load, validate, merge, and persist UI-independent YAML configuration."""

import os
import re
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from anki_flashcards.errors import FlashcardError

CONFIG_SCHEMA_VERSION = 1
DEFAULT_CONFIG_PATH = Path("config.yaml")
DEFAULT_LIMIT = 50
DEFAULT_LANGUAGE = "Deutsch"
DEFAULT_CHUNK_SIZE = 24_000
DEFAULT_TIMEOUT = 180
DEFAULT_PDF_MODE = "local"
ENVIRONMENT_VARIABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PDFMode(StrEnum):
    """Select local text extraction or verified native provider processing."""

    LOCAL = "local"
    NATIVE = "native"


class StrictModel(BaseModel):
    """Reject unknown keys to catch configuration mistakes early."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GenerationConfig(StrictModel):
    """Define YAML defaults for generation and export behavior.

    Attributes:
        profile: Named model profile used when no direct model is supplied.
        deck: Fixed deck name; absent means derive it from the input filename.
        limit: Maximum generated cards; zero enables unlimited mode.
        language: Natural language requested from the model.
        instructions: Additional prompt guidance.
        chunk_size: Source characters per local-text model request.
        timeout: Default provider request timeout in seconds.
        json_output: Optional card JSON destination path.
        extend: Whether generation should extend an existing APKG by default.
        pdf_mode: Local extraction or native PDF provider processing.
    """

    profile: str | None = Field(default=None, min_length=1)
    deck: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=DEFAULT_LIMIT, ge=0)
    language: str = Field(default=DEFAULT_LANGUAGE, min_length=1)
    instructions: str = ""
    chunk_size: int = Field(default=DEFAULT_CHUNK_SIZE, ge=1_000, le=100_000)
    timeout: int = Field(default=DEFAULT_TIMEOUT, ge=1, le=3_600)
    json_output: Path | None = None
    extend: bool = False
    pdf_mode: PDFMode = PDFMode.LOCAL

    @field_validator("profile")
    @classmethod
    def reject_reserved_profile_name(cls, value: str | None) -> str | None:
        """Reserve ``cli`` for direct model settings outside named profiles.

        Args:
            value: Candidate profile name.

        Returns:
            The unchanged non-reserved name or None.

        Raises:
            ValueError: If the reserved name ``cli`` is used.
        """
        if value == "cli":
            raise ValueError("'cli' is reserved for direct --model settings")
        return value


class ModelProfile(StrictModel):
    """Describe one reusable provider connection without storing secrets.

    Attributes:
        model: LiteLLM identifier in provider/model notation.
        api_base: Optional provider endpoint override.
        api_key_env: Name of the environment variable holding the API key.
        timeout: Provider request timeout in seconds.
        pdf_mode: Local extraction or native PDF provider processing.
        options: Allowed provider-specific LiteLLM keyword arguments.
    """

    model: str = Field(min_length=3, pattern=r"^[^/\s]+/[^\s]+$")
    api_base: str | None = Field(default=None, min_length=1)
    api_key_env: str | None = None
    timeout: int = Field(default=DEFAULT_TIMEOUT, ge=1, le=3_600)
    pdf_mode: PDFMode = PDFMode.LOCAL
    options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("api_key_env")
    @classmethod
    def validate_environment_name(cls, value: str | None) -> str | None:
        """Validate that only an environment variable name references a secret.

        Args:
            value: Candidate environment variable name.

        Returns:
            The unchanged name or None when the provider needs no key.

        Raises:
            ValueError: If the value is not a valid environment variable name.
        """
        if value is None or ENVIRONMENT_VARIABLE.fullmatch(value):
            return value
        raise ValueError("api_key_env must be an environment variable name, not a key")

    @field_validator("options")
    @classmethod
    def validate_provider_options(cls, options: dict[str, Any]) -> dict[str, Any]:
        """Prevent credentials and duplicate connection settings in options.

        Args:
            options: Provider-specific keyword arguments.

        Returns:
            The unchanged options after safety validation.

        Raises:
            ValueError: If a key contains credentials or managed settings.
        """
        forbidden = {"api_key", "api_base", "model", "messages", "response_format"}
        sensitive_markers = ("secret", "password", "token", "credential", "apikey")
        for key, value in options.items():
            normalized = key.casefold().replace("-", "_")
            if normalized in forbidden or any(marker in normalized for marker in sensitive_markers):
                raise ValueError(f"Option '{key}' is reserved or may expose a secret")
            if _contains_sensitive_key(value):
                raise ValueError(f"Option '{key}' must not contain secret-like nested keys")
        return options


class AppConfig(StrictModel):
    """Represent the complete versioned YAML configuration.

    Attributes:
        schema_version: Supported configuration schema version.
        default_profile: Optional named model profile for generation.
        input_dir: Default directory for bare input filenames.
        output_dir: Default directory for generated files.
        generation: Generation defaults applied beneath environment and CLI values.
        models: Reusable model profiles keyed by unique names.
    """

    schema_version: Literal[1] = CONFIG_SCHEMA_VERSION
    default_profile: str | None = Field(default=None, min_length=1)
    input_dir: Path | None = None
    output_dir: Path | None = None
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    models: dict[str, ModelProfile] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_profile_references(self) -> "AppConfig":
        """Validate profile references and reject the reserved ``cli`` key.

        Returns:
            The validated application configuration.

        Raises:
            ValueError: If a profile reference is unknown or reserved.
        """
        if "cli" in self.models:
            raise ValueError("The model profile name 'cli' is reserved")
        references = (self.default_profile, self.generation.profile)
        for reference in references:
            if reference is not None and reference not in self.models:
                raise ValueError(f"Unknown model profile: {reference}")
        if self.default_profile and self.generation.profile:
            raise ValueError("Set only default_profile or generation.profile, not both")
        return self

    def selected_profile_name(self) -> str | None:
        """Return the configured default profile using one precedence location.

        Returns:
            The profile selected by default_profile or generation.profile, or
            None when direct model settings or built-in defaults are intended.
        """
        return self.default_profile or self.generation.profile

    def selected_profile(self) -> ModelProfile | None:
        """Resolve the selected model profile after reference validation.

        Returns:
            The selected typed profile, or None if no profile is configured.

        Raises:
            FlashcardError: If a profile reference cannot be resolved.
        """
        name = self.selected_profile_name()
        if name is None:
            return None
        profile = self.models.get(name)
        if profile is None:
            raise FlashcardError(f"Unknown model profile: {name}")
        return profile


def _contains_sensitive_key(value: Any) -> bool:
    """Detect secret-like keys recursively inside provider option structures.

    Args:
        value: Arbitrary provider option value to inspect.

    Returns:
        True when a nested mapping key suggests credential material.
    """
    if isinstance(value, dict):
        for key, nested_value in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if any(marker in normalized for marker in ("secret", "password", "token", "apikey")):
                return True
            if _contains_sensitive_key(nested_value):
                return True
    if isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def load_config(path: Path | None = None) -> AppConfig:
    """Load YAML configuration, falling back to defaults only when implicit.

    Args:
        path: Explicit YAML path, or None to load optional ``config.yaml`` in
            the current working directory.

    Returns:
        Validated configuration with built-in defaults for omitted values.

    Raises:
        FlashcardError: If an explicit file is missing, YAML is invalid, or
            schema validation fails.
    """
    selected_path = path or DEFAULT_CONFIG_PATH
    if path is None and not selected_path.exists():
        return AppConfig()
    try:
        raw = yaml.safe_load(selected_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise FlashcardError(f"Could not read configuration {selected_path}: {error}") from error
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise FlashcardError(f"Configuration {selected_path} must contain a YAML object")
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as error:
        raise FlashcardError(f"Invalid configuration {selected_path}:\n{error}") from error


def save_config(path: Path, config: AppConfig) -> None:
    """Validate and serialize configuration to YAML with atomic replacement.

    Args:
        path: Destination YAML file; parent directories are created as needed.
        config: Typed configuration without secret values.

    Returns:
        None. The YAML file is replaced only after serialization succeeds.

    Raises:
        FlashcardError: If serialization or the atomic write fails.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump(mode="json", exclude_none=True)
    try:
        content = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
        _atomic_write(path, content)
    except (OSError, UnicodeError, TypeError, ValueError, yaml.YAMLError) as error:
        raise FlashcardError(f"Could not save configuration {path}: {error}") from error


def _atomic_write(path: Path, content: str) -> None:
    """Write UTF-8 text beside its destination and atomically replace the file.

    Args:
        path: Final destination file.
        content: Complete serialized configuration.

    Returns:
        None. Temporary content is cleaned up if replacement fails.
    """
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(content)
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
