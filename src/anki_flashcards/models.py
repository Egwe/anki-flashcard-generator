"""Validated flashcard models and versioned JSON persistence."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from anki_flashcards.errors import FlashcardError

SUBDECK_MAX_LENGTH = 100


class Card(BaseModel):
    """Represent one plain-text question-answer flashcard.

    Attributes:
        front: Self-contained question shown on the front of the card.
        back: Concise answer shown on the back of the card.
        tags: Optional Anki tags; whitespace inside a tag is not allowed.
        subdeck: Optional single-level subdeck below the target deck, at most
            100 characters; None keeps the card in the target deck itself.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    front: str = Field(min_length=1, max_length=2_000)
    back: str = Field(min_length=1, max_length=20_000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    subdeck: str | None = Field(default=None, max_length=SUBDECK_MAX_LENGTH)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: list[str]) -> list[str]:
        """Normalize, deduplicate, and validate tags supplied by a model or user.

        Args:
            tags: Candidate Anki tags.

        Returns:
            Tags in their original order without empty or duplicate entries.

        Raises:
            ValueError: If a remaining tag contains whitespace.
        """
        normalized = list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))
        if any(any(character.isspace() for character in tag) for tag in normalized):
            raise ValueError("Anki tags must not contain whitespace")
        return normalized

    @field_validator("subdeck")
    @classmethod
    def validate_subdeck(cls, subdeck: str | None) -> str | None:
        """Normalize a subdeck name and enforce a single deck level.

        Args:
            subdeck: Candidate subdeck name supplied by a model or JSON file.

        Returns:
            The name with collapsed whitespace, or None for a missing or blank
            name.

        Raises:
            ValueError: If the name contains the Anki deck separator ``::``.
        """
        if subdeck is None:
            return None
        normalized = " ".join(subdeck.split())
        if not normalized:
            return None
        if "::" in normalized:
            raise ValueError("A subdeck name must be a single level without '::'")
        return normalized


class SubdeckCard(Card):
    """Represent a model-generated card that must name its chapter subdeck.

    Attributes:
        subdeck: Required single-level subdeck name of 1 to 100 characters.
    """

    subdeck: str = Field(min_length=1, max_length=SUBDECK_MAX_LENGTH)


class CardBatch(BaseModel):
    """Wrap the list of cards returned by an AI provider or stored in JSON.

    Multi-word tags are joined with underscores before the cards are
    validated, because Anki cannot store spaces in a tag and models often
    answer with tags like ``Ohmsches Gesetz`` (R-177).

    Attributes:
        cards: Validated flashcards; an empty batch is allowed at this boundary.
    """

    cards: list[Card]

    @model_validator(mode="before")
    @classmethod
    def join_tag_words(cls, data: Any) -> Any:
        """Turn every multi-word tag of the raw cards into a single tag.

        Args:
            data: Raw batch, usually ``{"cards": [...]}`` from JSON.

        Returns:
            The batch with tags such as ``"Ohmsches Gesetz"`` replaced by
            ``"Ohmsches_Gesetz"``; other input is returned unchanged for the
            regular validation to report.
        """
        if not isinstance(data, dict) or not isinstance(data.get("cards"), list):
            return data
        return {**data, "cards": [_join_card_tags(card) for card in data["cards"]]}


class SubdeckCardBatch(CardBatch):
    """Response schema for subdeck mode in which every card names a subdeck.

    Attributes:
        cards: Validated cards with a required subdeck name.
    """

    cards: list[SubdeckCard]


def _join_card_tags(card: Any) -> Any:
    """Join the words of each tag of one raw card with underscores.

    Args:
        card: Raw card data from a model answer or JSON file.

    Returns:
        The card with joined tags, or the input unchanged if it is no dict
        or has no list of tags.
    """
    if not isinstance(card, dict) or not isinstance(card.get("tags"), list):
        return card
    tags = ["_".join(str(tag).split()) for tag in card["tags"]]
    return {**card, "tags": tags}


def normalize_key(text: str) -> str:
    """Build a case- and whitespace-insensitive comparison key.

    Args:
        text: Question or subdeck name to compare.

    Returns:
        Case-folded text with each whitespace run reduced to one space.
    """
    return " ".join(text.casefold().split())


def save_cards(
    path: Path,
    cards: list[Card],
    *,
    deck: str,
    source: str | None = None,
) -> None:
    """Write cards and their versioned metadata to UTF-8 JSON atomically.

    Args:
        path: Destination JSON file; parent directories are created as needed.
        cards: Validated cards to serialize.
        deck: Target Anki deck name stored as metadata.
        source: Optional source document path stored as metadata.

    Returns:
        None. The destination file is replaced only after serialization succeeds.
        Cards without a subdeck are written without a ``subdeck`` key.
    """
    payload: dict[str, Any] = {
        "schema_version": 1,
        "deck": deck,
        "cards": [card.model_dump(exclude_none=True) for card in cards],
    }
    if source is not None:
        payload["source"] = source

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def load_cards(path: Path) -> list[Card]:
    """Read and validate a version-1 flashcard JSON document.

    Args:
        path: JSON file containing a card batch.

    Returns:
        The validated cards, including an empty list when the batch is empty.

    Raises:
        FlashcardError: If the file cannot be read, its schema is unsupported,
            or its card data is invalid.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise FlashcardError(f"Card JSON must contain an object: {path}")
        if payload.get("schema_version") != 1:
            raise FlashcardError(f"Unsupported card JSON schema in {path}")
        return CardBatch.model_validate(payload).cards
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, FlashcardError):
            raise
        raise FlashcardError(f"Could not read valid cards from {path}: {error}") from error


def deduplicate_cards(cards: list[Card], limit: int = 0) -> list[Card]:
    """Keep the first card for each normalized question and apply a limit.

    Args:
        cards: Candidate cards in their preferred order.
        limit: Maximum number of returned cards; zero disables the limit.

    Returns:
        Unique cards ordered by their first occurrence.
    """
    unique: list[Card] = []
    seen: set[str] = set()
    for card in cards:
        key = normalize_key(card.front)
        if key in seen:
            continue
        seen.add(key)
        unique.append(card)
        if limit > 0 and len(unique) == limit:
            break
    return unique
