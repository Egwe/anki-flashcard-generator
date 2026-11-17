"""Test card validation, JSON persistence, and question deduplication."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from anki_flashcards.errors import FlashcardError
from anki_flashcards.models import Card, deduplicate_cards, load_cards, save_cards


def test_card_json_round_trip(tmp_path: Path) -> None:
    """Verify cards survive versioned JSON serialization and validation.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. The assertion compares the loaded and original card lists.
    """
    path = tmp_path / "cards.json"
    expected = [Card(front="Frage?", back="Antwort", tags=["Biologie"])]
    save_cards(path, expected, deck="Test", source="source.pdf")

    assert load_cards(path) == expected


def test_invalid_card_json_is_rejected(tmp_path: Path) -> None:
    """Verify invalid card content becomes a user-facing JSON error.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. The assertion requires FlashcardError for an empty front field.
    """
    path = tmp_path / "cards.json"
    path.write_text('{"schema_version": 1, "cards": [{"front": ""}]}', encoding="utf-8")

    with pytest.raises(FlashcardError, match="valid cards"):
        load_cards(path)


def test_tags_cannot_contain_whitespace() -> None:
    """Verify tags with whitespace are rejected by the card schema.

    Returns:
        None. The assertion requires a Pydantic validation error.
    """
    with pytest.raises(ValidationError, match="whitespace"):
        Card(front="Frage?", back="Antwort", tags=["zwei Worte"])


def test_deduplicate_is_case_and_whitespace_insensitive() -> None:
    """Verify first-occurrence deduplication and optional limiting.

    Returns:
        None. Assertions compare the retained cards with the original objects.
    """
    cards = [
        Card(front="Eine Frage?", back="Alt"),
        Card(front=" eine   frage? ", back="Neu"),
        Card(front="Andere Frage?", back="Antwort"),
    ]

    assert deduplicate_cards(cards, limit=1) == [cards[0]]
    assert deduplicate_cards(cards) == [cards[0], cards[2]]
