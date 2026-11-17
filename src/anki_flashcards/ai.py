"""Generate validated flashcards from source text through LiteLLM providers."""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from anki_flashcards.documents import SourceDocument, chunk_text
from anki_flashcards.errors import FlashcardError
from anki_flashcards.models import Card, CardBatch, deduplicate_cards

SYSTEM_PROMPT = """You create high-quality Anki flashcards from a source document.
Return only valid JSON matching {"cards": [{"front": "...", "back": "...", "tags": []}]}.
Each card must test one self-contained, meaningful fact from the source. Do not invent facts.
Use plain text, concise answers, unambiguous questions, and tags without whitespace.
Do not create meta questions about the document or duplicate the same fact with different wording.
If the source does not contain enough material, return fewer cards rather than weak cards.
"""


@dataclass(frozen=True)
class AISettings:
    """Configure a provider request independently of a CLI or web interface.

    Attributes:
        model: LiteLLM model identifier in provider/model notation.
        api_key: Optional explicit credential overriding the generic environment
            credential; provider-specific environment variables remain supported.
        api_base: Optional provider endpoint override.
        timeout: Request timeout in seconds.
        options: Additional validated provider-specific completion options.
    """

    model: str
    api_key: str | None = None
    api_base: str | None = None
    timeout: int = 180
    options: dict[str, Any] = field(default_factory=dict)


def generate_cards(
    document: SourceDocument,
    settings: AISettings,
    *,
    limit: int = 50,
    language: str = "Deutsch",
    instructions: str = "",
    chunk_size: int = 24_000,
    progress: Callable[[int, int, int], None] | None = None,
) -> list[Card]:
    """Generate, validate, deduplicate, and limit cards for a source document.

    Args:
        document: Extracted source text and its path.
        settings: Provider model, optional connection overrides, and timeout.
        limit: Maximum cards across all chunks; zero enables unlimited mode.
        language: Natural language requested for the generated cards.
        instructions: Additional user guidance appended to each prompt.
        chunk_size: Maximum source characters per request.
        progress: Optional callback receiving completed chunks, total chunks,
            and the current unique-card count after each response.

    Returns:
        Validated unique cards in source-chunk order. An empty list is returned
        when every provider response contains an empty batch.

    Raises:
        ValueError: If the limit or chunking parameters are invalid.
        FlashcardError: If no model is configured or a provider request or
            response is invalid.
    """
    if limit < 0:
        raise ValueError("Card limit must be non-negative")
    if not settings.model.strip():
        raise FlashcardError("No AI model configured. Use --model or select a YAML profile.")

    chunks = chunk_text(document.text, max_chars=chunk_size)
    cards: list[Card] = []
    for index, chunk in enumerate(chunks):
        remaining = len(chunks) - index
        allocation = max(1, math.ceil((limit - len(cards)) / remaining)) if limit else None
        prompt = _build_prompt(
            chunk,
            allocation=allocation,
            language=language,
            instructions=instructions,
        )
        batch = _request_batch(prompt, settings, index + 1)
        cards.extend(batch.cards)
        cards = deduplicate_cards(cards, limit)
        if progress is not None:
            progress(index + 1, len(chunks), len(cards))
        if limit > 0 and len(cards) >= limit:
            break
    return cards


def _request_batch(prompt: str, settings: AISettings, chunk_number: int) -> CardBatch:
    """Request and validate one card batch at the external provider boundary.

    Args:
        prompt: Complete user prompt containing one source chunk.
        settings: Provider connection settings.
        chunk_number: One-based chunk number used in error messages.

    Returns:
        A validated card batch from the provider response.

    Raises:
        FlashcardError: If the request fails or the response is not a valid
            card batch.
    """
    try:
        response = _completion(
            model=settings.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format=CardBatch,
            timeout=settings.timeout,
            num_retries=2,
            drop_params=True,
            **settings.options,
            **_provider_options(settings),
        )
        return CardBatch.model_validate_json(_response_content(response))
    except (ValidationError, ValueError, TypeError) as error:
        raise FlashcardError(
            f"AI returned invalid card data for document chunk {chunk_number}: {error}"
        ) from error
    except Exception as error:
        raise FlashcardError(
            f"AI request failed for document chunk {chunk_number}: {error}"
        ) from error


def _build_prompt(text: str, *, allocation: int | None, language: str, instructions: str) -> str:
    """Build a prompt for one source chunk and requested card allocation.

    Args:
        text: Source text delimited as data rather than instructions.
        allocation: Maximum cards for this request; None requests all useful
            cards supported by the source.
        language: Natural language for question and answer text.
        instructions: Optional additional user guidance.

    Returns:
        The complete user prompt sent to the provider.
    """
    extra = f"\nAdditional user instructions: {instructions}" if instructions else ""
    target = (
        f"at most {allocation} cards"
        if allocation is not None
        else "as many useful cards as the source supports, without an arbitrary limit"
    )
    return (
        f"Create {target}. Write the cards in {language}.{extra}\n\n"
        f"<source_document>\n{text}\n</source_document>"
    )


def _provider_options(settings: AISettings) -> dict[str, Any]:
    """Collect optional LiteLLM connection overrides without empty values.

    Args:
        settings: Provider settings whose generic environment fallbacks are read.

    Returns:
        Optional ``api_key`` and ``api_base`` keyword arguments for LiteLLM.
    """
    options: dict[str, Any] = {}
    if settings.api_key:
        options["api_key"] = settings.api_key
    if settings.api_base:
        options["api_base"] = settings.api_base
    return options


def _completion(**kwargs: Any) -> Any:
    """Call LiteLLM lazily so tests can replace the external client boundary.

    Args:
        **kwargs: Complete LiteLLM completion request options.

    Returns:
        The provider response object in LiteLLM's normalized format.
    """
    from litellm import completion

    return completion(**kwargs)


def _response_content(response: Any) -> str:
    """Extract non-empty JSON text from a normalized provider response.

    Args:
        response: LiteLLM-style response containing a first message choice.

    Returns:
        Trimmed response text with one surrounding Markdown code fence removed
        when present.

    Raises:
        ValueError: If the message content is absent, empty, or not text.
    """
    content = response.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise ValueError("The model returned an empty response")
    content = content.strip()
    return _strip_code_fence(content)


def _strip_code_fence(content: str) -> str:
    """Remove one complete Markdown fence while preserving plain JSON text.

    Args:
        content: Trimmed model response.

    Returns:
        The response without its first and last fence line, or the unchanged
        content when no complete fence exists.
    """
    lines = content.splitlines()
    if not content.startswith("```") or lines[-1].strip() != "```":
        return content
    return "\n".join(lines[1:-1]).strip()
