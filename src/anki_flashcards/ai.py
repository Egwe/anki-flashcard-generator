import math
import os
from collections.abc import Callable
from dataclasses import dataclass
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
    model: str
    api_key: str | None = None
    api_base: str | None = None
    timeout: int = 180


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
    if limit < 0:
        raise ValueError("Card limit must be non-negative")
    if not settings.model.strip():
        raise FlashcardError("No AI model configured. Use --model or set ANKI_MODEL.")

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
                **_provider_options(settings),
            )
            batch = CardBatch.model_validate_json(_response_content(response))
        except (ValidationError, ValueError, TypeError) as error:
            raise FlashcardError(
                f"AI returned invalid card data for document chunk {index + 1}: {error}"
            ) from error
        except Exception as error:
            raise FlashcardError(
                f"AI request failed for document chunk {index + 1}: {error}"
            ) from error

        cards.extend(batch.cards)
        cards = deduplicate_cards(cards, limit)
        if progress is not None:
            progress(index + 1, len(chunks), len(cards))
        if limit > 0 and len(cards) >= limit:
            break
    return cards


def _build_prompt(text: str, *, allocation: int | None, language: str, instructions: str) -> str:
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
    options: dict[str, Any] = {}
    api_key = settings.api_key or os.getenv("LLM_API_KEY")
    api_base = settings.api_base or os.getenv("LLM_API_BASE")
    if api_key:
        options["api_key"] = api_key
    if api_base:
        options["api_base"] = api_base
    return options


def _completion(**kwargs: Any) -> Any:
    from litellm import completion

    return completion(**kwargs)


def _response_content(response: Any) -> str:
    content = response.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise ValueError("The model returned an empty response")
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines[-1].strip() == "```":
            content = "\n".join(lines[1:-1]).strip()
    return content
