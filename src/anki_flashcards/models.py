import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from anki_flashcards.errors import FlashcardError


class Card(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    front: str = Field(min_length=1, max_length=2_000)
    back: str = Field(min_length=1, max_length=20_000)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, tags: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))
        if any(any(character.isspace() for character in tag) for tag in normalized):
            raise ValueError("Anki tags must not contain whitespace")
        return normalized


class CardBatch(BaseModel):
    cards: list[Card]


def save_cards(
    path: Path,
    cards: list[Card],
    *,
    deck: str,
    source: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "deck": deck,
        "cards": [card.model_dump() for card in cards],
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
    unique: list[Card] = []
    seen: set[str] = set()
    for card in cards:
        key = " ".join(card.front.casefold().split())
        if key in seen:
            continue
        seen.add(key)
        unique.append(card)
        if limit > 0 and len(unique) == limit:
            break
    return unique
