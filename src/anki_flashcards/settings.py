"""Resolve YAML configuration, dotenv credentials, and CLI runtime settings."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from anki_flashcards.ai import AISettings
from anki_flashcards.config import (
    DEFAULT_TIMEOUT,
    AppConfig,
    ModelProfile,
    PDFMode,
    PictureBackend,
    load_config,
)
from anki_flashcards.errors import FlashcardError
from anki_flashcards.structured_pdf import ConversionOptions

CONVERSION_OPTIONS = (
    "force_ocr",
    "formulas",
    "allow_unreadable",
    "picture_backend",
    "picture_profile",
    "source_text",
)


class ValueSource(StrEnum):
    """Identify the precedence layer that supplied an effective value.

    Credentials are read from dotenv/environment but intentionally do not form
    a configuration precedence layer for models, endpoints, or generation.
    """

    BUILT_IN = "built-in"
    CONFIG = "config"
    CLI = "cli"


@dataclass(frozen=True)
class SourcedValue:
    """Hold one effective value and the layer from which it originated.

    Attributes:
        value: Resolved scalar, path, or provider options.
        source: Precedence layer that supplied the value.
    """

    value: Any
    source: ValueSource


@dataclass(frozen=True)
class ConversionSettings:
    """Contain resolved settings of the structured local PDF conversion.

    Attributes:
        options: OCR, formula, gap handling, and description language.
        models_dir: Absolute folder for every downloaded model and cache.
        picture_backend: Backend that describes figures.
        picture_model: Hugging Face identifier of the local picture model.
        picture_profile: Profile name used by the ``profile`` backend.
        picture_ai: Provider settings of that profile, or None for other backends.
        source_text: Optional new Markdown file receiving the converted text.
    """

    options: ConversionOptions
    models_dir: Path
    picture_backend: PictureBackend
    picture_model: str
    picture_profile: str | None = None
    picture_ai: AISettings | None = None
    source_text: Path | None = None


@dataclass(frozen=True)
class GenerateSettings:
    """Contain fully resolved values needed for a document generation run.

    Attributes:
        input_file: Existing local document path.
        output: Target APKG path.
        deck: Target Anki deck name.
        extend: Whether the output package must be extended.
        json_output: Optional card JSON destination.
        limit: Maximum cards; zero means unlimited.
        language: Requested card language.
        instructions: Additional prompt instructions.
        chunk_size: Maximum source characters per local-text request.
        ai: Provider model, credentials, endpoint, timeout, and options.
        pdf_mode: Effective local, structured, or native PDF processing mode.
        subdecks: Whether the AI assigns cards to subdecks below ``deck``.
        profile_name: Selected profile name or None for direct model settings.
        conversion: Settings of the structured local PDF conversion.
        origins: Precedence-layer label for every effective scalar setting.
    """

    input_file: Path
    output: Path
    deck: str
    extend: bool
    json_output: Path | None
    limit: int
    language: str
    instructions: str
    chunk_size: int
    ai: AISettings
    pdf_mode: PDFMode
    subdecks: bool
    profile_name: str | None
    conversion: ConversionSettings
    origins: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExportSettings:
    """Contain fully resolved values needed for JSON-to-APKG export.

    Attributes:
        cards_file: Versioned card JSON input path.
        output: Target APKG path.
        deck: Target deck name.
        extend: Whether an existing package must be extended.
        origins: Precedence-layer label for each effective setting.
    """

    cards_file: Path
    output: Path
    deck: str
    extend: bool
    origins: dict[str, str] = field(default_factory=dict)


def load_selected_config(path: Path | None) -> tuple[AppConfig, Path | None]:
    """Load an explicit or implicit YAML file and retain its resolved location.

    Args:
        path: Explicit YAML path, or None to search for optional config.yaml
            and honor ANKI_CONFIG when set.

    Returns:
        The validated configuration and its absolute base path, or None when
        no implicit file exists and defaults are used.

    Raises:
        FlashcardError: If an explicitly selected configuration is invalid.
    """
    environment_path = os.getenv("ANKI_CONFIG")
    selected_path = path or (Path(environment_path) if environment_path else None)
    config = load_config(selected_path)
    if selected_path is None:
        implicit_path = Path("config.yaml")
        if not implicit_path.exists():
            return config, None
        selected_path = implicit_path
    return config, selected_path.absolute()


def resolve_generate_settings(
    cli: Mapping[str, Any],
    config: AppConfig,
    config_path: Path | None,
) -> GenerateSettings:
    """Merge generation defaults, YAML, credentials, and explicit CLI values.

    Args:
        cli: Command options including only explicitly supplied values for
            options whose defaults are delegated to this resolver.
        config: Validated application configuration.
        config_path: Absolute YAML location used to resolve its relative paths.

    Returns:
        Effective generation settings with safe origin metadata.

    Raises:
        FlashcardError: If a selected profile is unknown or PDF mode is invalid.
    """
    profile_name = _resolve_profile_name(cli, config)
    profile = _select_profile(config, profile_name)
    input_file = _resolve_input_path(cli["input_file"], config, config_path)
    output = _resolve_output_path(cli.get("output"), input_file, config, config_path)
    deck = _resolve_deck(cli.get("deck"), config, input_file)
    json_output = _resolve_optional_path(
        cli.get("json_output"),
        config.generation.json_output,
        config.output_dir,
        config_path,
    )
    model = _resolve_model(cli.get("model"), profile)
    api_base = _resolve_api_base(cli.get("api_base"), profile)
    timeout = _resolve_timeout(cli.get("timeout"), config, profile)
    pdf_mode = _resolve_pdf_mode(cli.get("pdf_mode"), config, profile)
    origins = _generate_origins(cli, config, profile_name, config_path)
    language = cli.get("language", config.generation.language)
    conversion = _resolve_conversion(
        cli, config, config_path, input_file, profile_name, language, pdf_mode
    )
    ai = AISettings(
        model=model.value,
        api_key=_profile_api_key(profile),
        api_base=api_base.value,
        timeout=timeout.value,
        options=profile.options.copy() if profile else {},
    )
    return GenerateSettings(
        input_file=input_file,
        output=output,
        deck=deck,
        extend=cli.get("extend", config.generation.extend),
        json_output=json_output,
        limit=cli.get("limit", config.generation.limit),
        language=language,
        instructions=cli.get("instructions", config.generation.instructions),
        chunk_size=cli.get("chunk_size", config.generation.chunk_size),
        ai=ai,
        pdf_mode=pdf_mode,
        subdecks=cli.get("subdecks", config.generation.subdecks),
        profile_name=profile_name,
        conversion=conversion,
        origins=origins,
    )


def resolve_export_settings(
    cli: Mapping[str, Any],
    config: AppConfig,
    config_path: Path | None,
) -> ExportSettings:
    """Merge JSON export paths, deck, and extend defaults.

    Args:
        cli: Explicit export command options.
        config: Validated application configuration.
        config_path: Absolute YAML location used for relative configured paths.

    Returns:
        Effective JSON export settings and origin metadata.

    Raises:
        FlashcardError: If no target deck can be determined.
    """
    cards_file = _resolve_input_path(cli["cards_file"], config, config_path)
    output = _resolve_output_path(
        cli.get("output"), cards_file.with_suffix(".apkg"), config, config_path
    )
    deck = cli.get("deck") or config.generation.deck
    if not deck:
        raise FlashcardError("Deck name is required via --deck or generation.deck")
    origins = {
        "output": _source_for_option(cli, "output", config.output_dir is not None).value,
        "deck": _source_for_option(cli, "deck", config.generation.deck is not None).value,
        "extend": _source_for_option(cli, "extend", config_path is not None).value,
    }
    return ExportSettings(
        cards_file=cards_file,
        output=output,
        deck=deck,
        extend=cli.get("extend", config.generation.extend),
        origins=origins,
    )


def _resolve_conversion(
    cli: Mapping[str, Any],
    config: AppConfig,
    config_path: Path | None,
    input_file: Path,
    profile_name: str | None,
    language: str,
    pdf_mode: PDFMode,
) -> ConversionSettings:
    """Merge structured PDF conversion settings from CLI, YAML, and defaults.

    Args:
        cli: Explicit command options.
        config: Validated application configuration.
        config_path: YAML location for relative models and text folders.
        input_file: Resolved input used to name a saved source text.
        profile_name: Profile generating the cards, reused by default for
            the ``profile`` picture backend.
        language: Effective card language, also used for descriptions.
        pdf_mode: Effective PDF mode; the picture profile is only validated
            for the structured mode.

    Returns:
        Resolved conversion settings.

    Raises:
        FlashcardError: If the structured mode uses a picture profile that is
            missing or does not allow image input.
    """
    conversion = config.pdf_conversion
    options = ConversionOptions(
        ocr_languages=tuple(conversion.ocr_languages),
        force_ocr=cli.get("force_ocr", conversion.force_ocr),
        formulas=cli.get("formulas", conversion.formulas),
        allow_unreadable=cli.get("allow_unreadable", conversion.allow_unreadable),
        language=language,
    )
    backend = cli.get("picture_backend", conversion.pictures.backend)
    picture_profile = cli.get("picture_profile") or conversion.pictures.profile or profile_name
    picture_ai = None
    if pdf_mode == PDFMode.STRUCTURED and backend == PictureBackend.PROFILE:
        picture_ai = _picture_ai(config, picture_profile)
    return ConversionSettings(
        options=options,
        models_dir=resolve_models_dir(config, config_path),
        picture_backend=backend,
        picture_model=conversion.pictures.model,
        picture_profile=picture_profile if backend == PictureBackend.PROFILE else None,
        picture_ai=picture_ai,
        source_text=_resolve_source_text(cli, conversion.source_text_dir, input_file, config_path),
    )


def resolve_models_dir(config: AppConfig, config_path: Path | None) -> Path:
    """Resolve the project-local folder for downloaded models and caches.

    Args:
        config: Validated application configuration.
        config_path: YAML location; relative folders are resolved next to it,
            without YAML relative to the current working directory.

    Returns:
        The absolute models folder.
    """
    return _config_directory(config.pdf_conversion.models_dir, config_path)


def _picture_ai(config: AppConfig, name: str | None) -> AISettings:
    """Resolve provider settings of the profile that describes figures.

    Args:
        config: Validated application configuration.
        name: Picture profile name, or None when no profile is selected.

    Returns:
        Settings of the profile, with its credential read from the environment.

    Raises:
        FlashcardError: If no profile is selected, it is unknown, or it does
            not explicitly allow image input.
    """
    if name is None:
        raise FlashcardError(
            "The picture backend 'profile' needs a model profile: use --picture-profile "
            "or pdf_conversion.pictures.profile, or select a card profile."
        )
    profile = _select_profile(config, name)
    if profile is None or not profile.image_input:
        raise FlashcardError(
            f"Model profile '{name}' must set image_input: true to describe figures."
        )
    return AISettings(
        model=profile.model,
        api_key=_profile_api_key(profile),
        api_base=profile.api_base,
        timeout=profile.timeout,
        options=profile.options.copy(),
    )


def _resolve_source_text(
    cli: Mapping[str, Any],
    configured_dir: Path | None,
    input_file: Path,
    config_path: Path | None,
) -> Path | None:
    """Resolve where the converted Markdown is saved, if anywhere.

    Args:
        cli: Explicit command options; ``source_text`` is a file path.
        configured_dir: YAML folder for saved texts or None.
        input_file: Resolved input whose name is reused for the file.
        config_path: YAML location for a relative folder.

    Returns:
        Absolute Markdown path, or None when the text is not saved.
    """
    if "source_text" in cli:
        return Path(cli["source_text"]).absolute()
    if configured_dir is None:
        return None
    return _config_directory(configured_dir, config_path) / f"{input_file.stem}.md"


def _resolve_profile_name(cli: Mapping[str, Any], config: AppConfig) -> str | None:
    """Select a CLI profile or the configured default profile.

    Args:
        cli: Explicit generation command options.
        config: Validated application configuration.

    Returns:
        The selected name, or None for direct --model usage.
    """
    return cli.get("profile") or config.selected_profile_name()


def _select_profile(config: AppConfig, name: str | None) -> ModelProfile | None:
    """Resolve a profile by name without conflating direct model settings.

    Args:
        config: Validated application configuration.
        name: Selected profile name or None.

    Returns:
        The matching model profile or None.

    Raises:
        FlashcardError: If the selected profile does not exist.
    """
    if name is None:
        return None
    profile = config.models.get(name)
    if profile is None:
        raise FlashcardError(f"Unknown model profile: {name}")
    return profile


def _resolve_input_path(supplied: Path, config: AppConfig, config_path: Path | None) -> Path:
    """Resolve a CLI path directly or a configured bare input filename.

    Args:
        supplied: Command input argument, already validated by the CLI when
            given as a direct path.
        config: Application configuration containing input_dir.
        config_path: YAML file location used for relative directories.

    Returns:
        An absolute path to the local input file.
    """
    if supplied.parent != Path("."):
        return supplied.absolute()
    if config.input_dir is None:
        return supplied.absolute()
    base = _config_directory(config.input_dir, config_path)
    return base / supplied


def _resolve_output_path(
    supplied: Path | None,
    input_file: Path,
    config: AppConfig,
    config_path: Path | None,
) -> Path:
    """Resolve an explicit output or derive it from the output directory.

    Args:
        supplied: Explicit CLI output path, or None when configuration applies.
        input_file: Resolved input used for the default output filename.
        config: Application configuration containing output_dir.
        config_path: YAML file location used for relative directories.

    Returns:
        An absolute APKG destination path.

    Raises:
        FlashcardError: If neither CLI output nor output_dir is configured.
    """
    if supplied is not None:
        return supplied.absolute()
    if config.output_dir is None:
        raise FlashcardError("Output is required via --output or output_dir in YAML")
    directory = _config_directory(config.output_dir, config_path)
    return directory / f"{input_file.stem}.apkg"


def _resolve_optional_path(
    supplied: Path | None,
    configured: Path | None,
    output_dir: Path | None,
    config_path: Path | None,
) -> Path | None:
    """Resolve an optional JSON path with CLI precedence over YAML.

    Args:
        supplied: Explicit CLI JSON destination or None.
        configured: YAML generation.json_output destination or None.
        output_dir: Optional base for a bare configured filename.
        config_path: YAML file location for relative configured paths.

    Returns:
        Absolute JSON path or None when JSON output is disabled.
    """
    if supplied is not None:
        return supplied.absolute()
    if configured is None:
        return None
    if configured.parent != Path(".") or output_dir is None:
        return _config_directory(configured, config_path)
    return _config_directory(output_dir, config_path) / configured


def _config_directory(path: Path, config_path: Path | None) -> Path:
    """Resolve a YAML path relative to its file, not the caller's directory.

    Args:
        path: Absolute path or relative configured directory/file.
        config_path: Absolute YAML location, or None for built-in defaults.

    Returns:
        Absolute resolved path.
    """
    if path.is_absolute():
        return path
    base = config_path.parent if config_path else Path.cwd()
    return base / path


def _resolve_deck(cli_deck: str | None, config: AppConfig, input_file: Path) -> str:
    """Resolve the deck from CLI, YAML, or the input filename stem.

    Args:
        cli_deck: Explicit CLI deck name or None.
        config: Application generation defaults.
        input_file: Resolved source document used as fallback.

    Returns:
        The selected non-empty deck name.
    """
    return cli_deck or config.generation.deck or input_file.stem


def _resolve_model(supplied: str | None, profile: ModelProfile | None) -> SourcedValue:
    """Resolve direct model settings with YAML and explicit CLI precedence.

    Args:
        supplied: Explicit CLI model or None.
        profile: Optional selected model profile.

    Returns:
        Model identifier and its source, empty when no model is configured.
        Non-secret environment overrides are deliberately not consulted.
    """
    if supplied is not None:
        return SourcedValue(supplied, ValueSource.CLI)
    if profile is not None:
        return SourcedValue(profile.model, ValueSource.CONFIG)
    return SourcedValue("", ValueSource.BUILT_IN)


def _resolve_api_base(supplied: str | None, profile: ModelProfile | None) -> SourcedValue:
    """Resolve API endpoint with explicit CLI over the YAML profile.

    Args:
        supplied: Explicit CLI endpoint or None.
        profile: Optional selected model profile.

    Returns:
        Optional endpoint and its source. Non-secret environment overrides are
        deliberately not consulted; YAML owns provider connection settings.
    """
    if supplied is not None:
        return SourcedValue(supplied, ValueSource.CLI)
    if profile is not None and profile.api_base is not None:
        return SourcedValue(profile.api_base, ValueSource.CONFIG)
    return SourcedValue(None, ValueSource.BUILT_IN)


def _resolve_timeout(
    supplied: int | None, config: AppConfig, profile: ModelProfile | None
) -> SourcedValue:
    """Resolve timeout with generation overriding profile at the YAML layer.

    Args:
        supplied: Explicit CLI timeout or None.
        config: Generation defaults.
        profile: Optional selected model profile.

    Returns:
        Timeout in seconds and its source.
    """
    if supplied is not None:
        return SourcedValue(supplied, ValueSource.CLI)
    if config.generation.timeout is not None:
        return SourcedValue(config.generation.timeout, ValueSource.CONFIG)
    if profile is not None:
        return SourcedValue(profile.timeout, ValueSource.CONFIG)
    return SourcedValue(DEFAULT_TIMEOUT, ValueSource.BUILT_IN)


def _resolve_pdf_mode(
    supplied: PDFMode | None, config: AppConfig, profile: ModelProfile | None
) -> PDFMode:
    """Resolve PDF processing mode with CLI over generation over profile.

    Args:
        supplied: Explicit CLI PDF mode or None.
        config: Generation defaults.
        profile: Optional selected model profile.

    Returns:
        Effective local or native PDF processing mode.
    """
    if supplied is not None:
        return supplied
    if config.generation.pdf_mode is not None:
        return config.generation.pdf_mode
    if profile is not None:
        return profile.pdf_mode
    return PDFMode.LOCAL


def _profile_api_key(profile: ModelProfile | None) -> str | None:
    """Read a profile credential only from its named environment variable.

    Args:
        profile: Optional selected model profile.

    Returns:
        Secret value for the provider request or None; never a YAML value.
    """
    if profile is None or profile.api_key_env is None:
        return None
    return os.getenv(profile.api_key_env)


def _source_for_option(cli: Mapping[str, Any], name: str, has_config: bool) -> SourcedValue:
    """Determine origin metadata for a normal scalar command option.

    Args:
        cli: Explicit command option mapping.
        name: Option key to inspect.
        has_config: Whether YAML can supply the option.

    Returns:
        The option value and built-in, config, or CLI source label.
    """
    if name in cli:
        return SourcedValue(cli[name], ValueSource.CLI)
    if has_config:
        return SourcedValue(None, ValueSource.CONFIG)
    return SourcedValue(None, ValueSource.BUILT_IN)


def _pdf_mode_origin(
    cli: Mapping[str, Any], config: AppConfig, profile_name: str | None
) -> SourcedValue:
    """Identify the exact layer supplying the effective PDF processing mode.

    Args:
        cli: Explicit generation command options.
        config: Validated application configuration.
        profile_name: Selected profile name or None.

    Returns:
        The effective mode and CLI, config, or built-in origin.
    """
    if "pdf_mode" in cli:
        return SourcedValue(cli["pdf_mode"], ValueSource.CLI)
    if config.generation.pdf_mode is not None:
        return SourcedValue(config.generation.pdf_mode, ValueSource.CONFIG)
    profile = _select_profile(config, profile_name)
    if profile is not None:
        return SourcedValue(profile.pdf_mode, ValueSource.CONFIG)
    return SourcedValue(PDFMode.LOCAL, ValueSource.BUILT_IN)


def _generate_origins(
    cli: Mapping[str, Any],
    config: AppConfig,
    profile_name: str | None,
    config_path: Path | None,
) -> dict[str, str]:
    """Build safe source labels without exposing credentials or secret values.

    Args:
        cli: Explicit generation command options.
        config: Validated application configuration.
        profile_name: Selected profile name or None.
        config_path: Selected YAML location or None for built-in defaults.

    Returns:
        Mapping of effective setting names to their source-layer labels.
    """
    origins = {
        "input_file": (
            ValueSource.CONFIG.value if config.input_dir is not None else ValueSource.CLI.value
        ),
        "output": _source_for_option(cli, "output", config.output_dir is not None).source.value,
        "deck": _source_for_option(cli, "deck", config.generation.deck is not None).source.value,
        "profile": (
            ValueSource.CLI.value
            if "profile" in cli
            else (
                ValueSource.CONFIG.value
                if config.selected_profile_name()
                else ValueSource.BUILT_IN.value
            )
        ),
        "model": _resolve_model(
            cli.get("model"), _select_profile(config, profile_name)
        ).source.value,
        "api_base": _resolve_api_base(
            cli.get("api_base"), _select_profile(config, profile_name)
        ).source.value,
        "timeout": _resolve_timeout(
            cli.get("timeout"), config, _select_profile(config, profile_name)
        ).source.value,
        "extend": _source_for_option(cli, "extend", config_path is not None).source.value,
        "limit": _source_for_option(cli, "limit", config_path is not None).source.value,
        "language": _source_for_option(cli, "language", config_path is not None).source.value,
        "instructions": _source_for_option(
            cli, "instructions", config_path is not None
        ).source.value,
        "chunk_size": _source_for_option(cli, "chunk_size", config_path is not None).source.value,
        "pdf_mode": _pdf_mode_origin(cli, config, profile_name).source.value,
        "subdecks": _source_for_option(cli, "subdecks", config_path is not None).source.value,
        **{
            name: _source_for_option(cli, name, config_path is not None).source.value
            for name in CONVERSION_OPTIONS
        },
        "json_output": _source_for_option(
            cli, "json_output", config.generation.json_output is not None
        ).source.value,
    }
    return origins


def configuration_diagnostics(
    settings: GenerateSettings,
    config_path: Path | None,
) -> dict[str, Any]:
    """Create a JSON-safe configuration view without credential values.

    Args:
        settings: Fully resolved generation settings.
        config_path: Selected YAML location or None for built-in defaults.

    Returns:
        A serializable dictionary of effective settings and source labels.
    """
    return {
        "config_path": str(config_path) if config_path else None,
        "profile": settings.profile_name,
        "input_file": str(settings.input_file),
        "output": str(settings.output),
        "deck": settings.deck,
        "extend": settings.extend,
        "json_output": str(settings.json_output) if settings.json_output else None,
        "limit": settings.limit,
        "language": settings.language,
        "instructions": settings.instructions,
        "chunk_size": settings.chunk_size,
        "pdf_mode": settings.pdf_mode.value,
        "subdecks": settings.subdecks,
        "pdf_conversion": _conversion_diagnostics(settings.conversion),
        "model": settings.ai.model,
        "api_base": settings.ai.api_base,
        "timeout": settings.ai.timeout,
        "api_key": "set (hidden)" if settings.ai.api_key else "not set",
        "provider_options": sorted(settings.ai.options),
        "sources": settings.origins,
    }


def _conversion_diagnostics(conversion: ConversionSettings) -> dict[str, Any]:
    """Describe structured PDF settings without credential values.

    Args:
        conversion: Resolved conversion settings.

    Returns:
        A JSON-safe dictionary; the picture profile's key is only reported
        as set or not set.
    """
    options = conversion.options
    picture_key = conversion.picture_ai.api_key if conversion.picture_ai else None
    return {
        "models_dir": str(conversion.models_dir),
        "ocr_languages": list(options.ocr_languages),
        "force_ocr": options.force_ocr,
        "formulas": options.formulas,
        "allow_unreadable": options.allow_unreadable,
        "picture_backend": conversion.picture_backend.value,
        "picture_model": conversion.picture_model,
        "picture_profile": conversion.picture_profile,
        "picture_api_key": "set (hidden)" if picture_key else "not set",
        "source_text": str(conversion.source_text) if conversion.source_text else None,
    }
