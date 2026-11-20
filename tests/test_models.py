"""Test card validation, JSON persistence, and question deduplication."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from anki_flashcards.errors import FlashcardError
from anki_flashcards.models import (
    Card,
    CardBatch,
    SubdeckCard,
    SubdeckCardBatch,
    deduplicate_cards,
    load_cards,
    save_cards,
)


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


def test_subdeck_names_are_normalized_and_validated() -> None:
    """Verify subdeck names are single-level, bounded, and whitespace-normalized.

    Returns:
        None. Assertions cover optional, required, valid, and invalid names.
    """
    assert Card(front="F?", back="A").subdeck is None
    assert Card(front="F?", back="A", subdeck="   ").subdeck is None
    assert SubdeckCard(front="F?", back="A", subdeck="  Kapitel   1 ").subdeck == "Kapitel 1"
    for invalid in ("", "   ", "EL1::Kapitel 1", "x" * 101):
        with pytest.raises(ValidationError):
            SubdeckCard(front="F?", back="A", subdeck=invalid)


def test_subdeck_json_round_trip_omits_missing_subdecks(tmp_path: Path) -> None:
    """Verify JSON keeps subdecks and leaves cards without subdeck unchanged.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions inspect the raw JSON and the loaded cards.
    """
    import json

    path = tmp_path / "cards.json"
    expected = [
        Card(front="A?", back="1", subdeck="Kapitel 1"),
        Card(front="B?", back="2"),
    ]
    save_cards(path, expected, deck="EL1")
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert raw["schema_version"] == 1
    assert raw["cards"][0]["subdeck"] == "Kapitel 1"
    assert "subdeck" not in raw["cards"][1]
    assert load_cards(path) == expected


def test_batch_joins_multi_word_tags() -> None:
    """Verify model answers and card JSON turn multi-word tags into one tag.

    Small models often answer with tags such as "Ohmsches Gesetz"; Anki
    cannot store spaces in a tag, so the words are joined with underscores
    instead of rejecting the whole answer (R-177).

    Returns:
        None. The assertions check the normalized tags.
    """
    batch = CardBatch.model_validate(
        {"cards": [{"front": "Frage?", "back": "Antwort", "tags": ["Ohmsches  Gesetz", "Strom"]}]}
    )

    assert batch.cards[0].tags == ["Ohmsches_Gesetz", "Strom"]


def test_subdeck_batch_joins_multi_word_tags() -> None:
    """Verify the subdeck response schema normalizes tags the same way.

    Returns:
        None. The assertion checks the normalized tag.
    """
    batch = SubdeckCardBatch.model_validate(
        {"cards": [{"front": "F?", "back": "A", "tags": ["zwei Worte"], "subdeck": "Kapitel"}]}
    )

    assert batch.cards[0].tags == ["zwei_Worte"]
