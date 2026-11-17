"""Generate cards from PDFs through verified native provider adapters."""

import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from anki_flashcards.ai import SYSTEM_PROMPT, AISettings
from anki_flashcards.errors import FlashcardError
from anki_flashcards.models import Card, CardBatch, deduplicate_cards

OPENAI_FILE_SIZE_LIMIT = 50 * 1024 * 1024
OPENAI_MODEL_DOCUMENTATION = {
    "gpt-4o": "https://developers.openai.com/api/docs/models/gpt-4o",
    "gpt-4o-mini": "https://developers.openai.com/api/docs/models/gpt-4o-mini",
    "gpt-4.1": "https://developers.openai.com/api/docs/models/gpt-4.1",
}
NATIVE_OPENAI_SNAPSHOT_PREFIXES = {
    "gpt-4o-": "gpt-4o",
    "gpt-4.1-": "gpt-4.1",
}


@dataclass(frozen=True)
class NativePDFResult:
    """Report generated cards and whether temporary upload deletion succeeded.

    Attributes:
        cards: Validated unique cards from the native provider response.
        deleted: True when the uploaded file was deleted, False when no file
            was uploaded or deletion failed and a warning was emitted.
    """

    cards: list[Card]
    deleted: bool


class NativePDFAdapter(Protocol):
    """Define the provider-independent boundary for native PDF generation."""

    def generate(
        self,
        path: Path,
        settings: AISettings,
        *,
        limit: int,
        language: str,
        instructions: str,
    ) -> NativePDFResult:
        """Upload one PDF and return validated cards from a native provider.

        Args:
            path: Local PDF to process.
            settings: Provider connection and model settings.
            limit: Maximum cards; zero requests all useful source facts.
            language: Natural language for card content.
            instructions: Additional user guidance.

        Returns:
            Validated cards and upload-deletion status.
        """
        ...


def native_openai_model(model: str) -> str | None:
    """Resolve a conservatively verified OpenAI model or snapshot.

    Args:
        model: Full LiteLLM model identifier or bare OpenAI model name.

    Returns:
        The bare OpenAI model identifier when officially documented for PDF
        input and structured outputs, otherwise None.
    """
    provider, separator, bare_model = model.partition("/")
    if separator and provider != "openai":
        return None
    if not separator:
        bare_model = provider
    if bare_model in OPENAI_MODEL_DOCUMENTATION:
        return bare_model
    for prefix in NATIVE_OPENAI_SNAPSHOT_PREFIXES:
        suffix = bare_model.removeprefix(prefix)
        if bare_model.startswith(prefix) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", suffix):
            return bare_model
    return None


def generate_native_cards(
    path: Path,
    settings: AISettings,
    *,
    limit: int = 50,
    language: str = "Deutsch",
    instructions: str = "",
    adapter: NativePDFAdapter | None = None,
) -> list[Card]:
    """Generate cards with a verified native adapter without local extraction.

    Args:
        path: Local PDF file to upload explicitly.
        settings: Provider model, credentials, endpoint, and timeout.
        limit: Maximum cards; zero enables unlimited source-driven generation.
        language: Natural language for generated questions and answers.
        instructions: Additional prompt guidance.
        adapter: Optional test adapter; production uses OpenAINativePDFAdapter.

    Returns:
        Validated unique cards, subject to the requested positive limit.

    Raises:
        FlashcardError: If the input is not a supported PDF, the model lacks a
            verified adapter, or the provider request/response fails.
    """
    if path.suffix.casefold() != ".pdf":
        raise FlashcardError("Native document processing currently supports PDF files only")
    selected_adapter = adapter or OpenAINativePDFAdapter()
    result = selected_adapter.generate(
        path,
        settings,
        limit=limit,
        language=language,
        instructions=instructions,
    )
    return deduplicate_cards(result.cards, limit)


class OpenAINativePDFAdapter:
    """Process PDFs with OpenAI Files and Responses structured-output APIs."""

    def generate(
        self,
        path: Path,
        settings: AISettings,
        *,
        limit: int,
        language: str,
        instructions: str,
    ) -> NativePDFResult:
        """Upload a PDF, request a card batch, and delete the uploaded file.

        Args:
            path: Local PDF below OpenAI's 50 MiB request limit.
            settings: OpenAI model and API connection settings.
            limit: Maximum cards; zero means no arbitrary numeric cap.
            language: Natural language for generated cards.
            instructions: Additional prompt guidance.

        Returns:
            Validated cards and whether uploaded-file deletion succeeded.

        Raises:
            FlashcardError: If the file, model, upload, response, or schema is
                unsupported or invalid. No silent local fallback is performed.
        """
        model = native_openai_model(settings.model)
        if model is None:
            raise FlashcardError(
                f"No verified native PDF adapter for model '{settings.model}'. "
                "Use a documented OpenAI vision model or pdf_mode=local."
            )
        _validate_openai_pdf(path)
        client = _openai_client(settings)
        uploaded_id = _upload_pdf(client, path, settings.timeout)
        try:
            batch = _request_openai_batch(
                client,
                uploaded_id,
                model,
                settings,
                limit=limit,
                language=language,
                instructions=instructions,
            )
        finally:
            deleted = _delete_uploaded_file(client, uploaded_id)
        return NativePDFResult(cards=batch.cards, deleted=deleted)


def _validate_openai_pdf(path: Path) -> None:
    """Validate native PDF size and extension before any network transfer.

    Args:
        path: Candidate local PDF file.

    Returns:
        None when the original file is eligible for upload.

    Raises:
        FlashcardError: If the file cannot be inspected or reaches the 50 MiB
            request limit.
    """
    try:
        size = path.stat().st_size
    except OSError as error:
        raise FlashcardError(f"Could not read native PDF {path}: {error}") from error
    if size >= OPENAI_FILE_SIZE_LIMIT:
        raise FlashcardError("Native OpenAI PDF input must be smaller than 50 MiB")


def _openai_client(settings: AISettings) -> Any:
    """Construct the official OpenAI client from resolved provider settings.

    Args:
        settings: Provider credentials, optional endpoint, and timeout.

    Returns:
        An initialized OpenAI client.

    Raises:
        FlashcardError: If no credential is available in settings or the
            OPENAI_API_KEY environment fallback used by the SDK.
    """
    import os

    from openai import OpenAI

    api_key = settings.api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise FlashcardError("Native OpenAI PDF processing requires OPENAI_API_KEY")
    options: dict[str, Any] = {"api_key": api_key, "timeout": settings.timeout}
    if settings.api_base:
        options["base_url"] = settings.api_base
    return OpenAI(**options)


def _upload_pdf(client: Any, path: Path, timeout: int) -> str:
    """Upload the original PDF for user data and return its provider file ID.

    Args:
        client: Initialized official OpenAI client.
        path: Validated local PDF file.
        timeout: Upload request timeout in seconds.

    Returns:
        Provider file identifier used by the Responses request.

    Raises:
        FlashcardError: If reading or uploading the original file fails.
    """
    try:
        with path.open("rb") as source:
            uploaded = client.files.create(file=source, purpose="user_data", timeout=timeout)
    except Exception as error:
        raise FlashcardError(f"Native PDF upload failed for {path}: {error}") from error
    return uploaded.id


def _request_openai_batch(
    client: Any,
    file_id: str,
    model: str,
    settings: AISettings,
    *,
    limit: int,
    language: str,
    instructions: str,
) -> CardBatch:
    """Request and validate structured cards for an uploaded PDF.

    Args:
        client: Initialized official OpenAI client.
        file_id: Uploaded PDF identifier.
        model: Verified bare OpenAI model identifier.
        settings: Provider timeout and safe custom options.
        limit: Maximum cards; zero requests all useful facts.
        language: Natural language for card content.
        instructions: Additional prompt guidance.

    Returns:
        Validated card batch parsed by the official SDK.

    Raises:
        FlashcardError: If the response is missing, refused, or invalid.
    """
    target = f"at most {limit} cards" if limit else "all useful cards supported by the PDF"
    prompt = f"Create {target} in {language}. {instructions}"
    try:
        response = client.responses.parse(
            model=model,
            instructions=SYSTEM_PROMPT,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_file", "file_id": file_id},
                        {"type": "input_text", "text": prompt},
                    ],
                }
            ],
            text_format=CardBatch,
            store=False,
            timeout=settings.timeout,
            **settings.options,
        )
        batch = response.output_parsed
    except (ValidationError, ValueError, TypeError) as error:
        raise FlashcardError(f"Native OpenAI response contained invalid cards: {error}") from error
    except Exception as error:
        raise FlashcardError(f"Native OpenAI PDF request failed: {error}") from error
    if not isinstance(batch, CardBatch):
        raise FlashcardError("Native OpenAI returned no valid card batch or refused the request")
    return batch


def _delete_uploaded_file(client: Any, file_id: str) -> bool:
    """Best-effort delete an uploaded PDF and warn when cleanup fails.

    Args:
        client: Initialized official OpenAI client.
        file_id: Uploaded file identifier to remove.

    Returns:
        True when deletion succeeds; otherwise emits a warning and returns False.
        The warning includes the file ID so manual cleanup remains possible.
    """
    try:
        client.files.delete(file_id)
    except Exception as error:
        warnings.warn(
            f"Native PDF upload {file_id} could not be deleted; remove it manually: {error}",
            RuntimeWarning,
            stacklevel=2,
        )
        return False
    return True
