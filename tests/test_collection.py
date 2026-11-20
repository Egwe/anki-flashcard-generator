"""Tests for writing cards into and reading decks from an open Anki collection."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import genanki
import pytest
from anki.collection import Collection

from anki_flashcards.apkg import (
    MODEL_NAME,
    add_cards_to_collection,
    collection_decks,
    collection_subdeck_context,
)
from anki_flashcards.config import AppConfig
from anki_flashcards.errors import FlashcardError
from anki_flashcards.models import Card
from anki_flashcards.pipeline import (
    PipelineEvent,
    subdeck_context_from_collection,
    write_collection,
)
from anki_flashcards.settings import resolve_generate_settings


@pytest.fixture
def collection(tmp_path: Path) -> Iterator[Any]:
    """Open a fresh official Anki collection in a temporary folder.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        An iterator yielding the open collection; it is closed afterwards.
    """
    opened = Collection(str(tmp_path / "collection.anki2"))
    yield opened
    opened.close()


def _fronts(collection: Any, deck: str) -> list[str]:
    """Read the stored question fields of all notes in one deck.

    Args:
        collection: Open Anki collection.
        deck: Exact deck name, without its subdecks.

    Returns:
        Stored first fields in note creation order.
    """
    ids = collection.find_notes(f'"deck:{deck}" -"deck:{deck}::*"')
    return [collection.get_note(note_id).fields[0] for note_id in sorted(ids)]


def test_cards_land_in_deck_and_subdecks_with_escaping_and_stable_guids(collection: Any) -> None:
    """Verify target decks, escaped fields, tags, and GUIDs in a collection.

    Args:
        collection: Open temporary Anki collection.

    Returns:
        None. Assertions inspect the result and the stored notes.
    """
    cards = [
        Card(front="Was ist <b>fett</b>?", back="Text & mehr", tags=["html"]),
        Card(front="Was ist ein Tiefpass?", back="Ein Filter.", subdeck="Filter"),
    ]

    result = add_cards_to_collection(collection, "EL1", cards)

    assert result.path == Path(collection.path)
    assert (result.added, result.skipped) == (2, 0)
    assert result.added_by_deck == {"EL1": 1, "EL1::Filter": 1}
    assert _fronts(collection, "EL1") == ["Was ist &lt;b&gt;fett&lt;/b&gt;?"]
    assert _fronts(collection, "EL1::Filter") == ["Was ist ein Tiefpass?"]
    note = collection.get_note(collection.find_notes('"deck:EL1::Filter"')[0])
    assert note.note_type()["name"] == MODEL_NAME
    assert note.guid == genanki.guid_for("EL1", "was ist ein tiefpass?")


def test_all_new_notes_are_added_in_one_undoable_operation(collection: Any) -> None:
    """Verify one undo step removes every note added by one call.

    Args:
        collection: Open temporary Anki collection.

    Returns:
        None. Assertions inspect the note count before and after undo.
    """
    cards = [Card(front=f"Frage {index}?", back="Antwort") for index in range(5)]

    add_cards_to_collection(collection, "Stapel", cards)
    assert collection.note_count() == 5
    collection.undo()

    assert collection.note_count() == 0


def test_duplicates_in_deck_tree_are_skipped(collection: Any) -> None:
    """Verify questions already in the deck or its subdecks are not added again.

    Args:
        collection: Open temporary Anki collection.

    Returns:
        None. Assertions inspect counts of a second call.
    """
    add_cards_to_collection(
        collection, "EL1", [Card(front="Was ist ein Filter?", back="A", subdeck="Filter")]
    )

    result = add_cards_to_collection(
        collection,
        "EL1",
        [
            Card(front="  was IST ein filter? ", back="B", subdeck="Andere"),
            Card(front="Neue Frage?", back="C", subdeck="Andere"),
        ],
    )

    assert (result.added, result.skipped) == (1, 1)
    assert collection.note_count() == 2


def test_reading_decks_and_subdeck_context_does_not_modify(collection: Any) -> None:
    """Verify deck listing and subdeck context are read-only.

    Args:
        collection: Open temporary Anki collection.

    Returns:
        None. Assertions inspect the returned data and modification time.
    """
    add_cards_to_collection(
        collection,
        "EL1",
        [
            Card(front="Was ist ein Tiefpass?", back="A", subdeck="Filter"),
            Card(front="Was ist Strom?", back="B", subdeck="Grundlagen"),
        ],
    )
    modified = collection.mod

    rows = {row["name"]: row["cards"] for row in collection_decks(collection)}
    context = collection_subdeck_context(collection, "el1")

    assert rows["EL1::Filter"] == 1 and rows["EL1"] == 0
    assert [subdeck.name for subdeck in context.existing] == ["Filter", "Grundlagen"]
    assert context.existing[0].examples == ("Was ist ein Tiefpass?",)
    assert collection.mod == modified


@pytest.mark.parametrize(
    ("deck", "cards", "message"),
    [
        ("EL1", [], "empty card list"),
        ("   ", [Card(front="F?", back="A")], "Deck name"),
    ],
)
def test_invalid_requests_are_rejected(
    collection: Any, deck: str, cards: list[Card], message: str
) -> None:
    """Verify empty card lists and blank deck names fail before any change.

    Args:
        collection: Open temporary Anki collection.
        deck: Requested deck name.
        cards: Requested cards.
        message: Expected part of the error message.

    Returns:
        None. The error and the unchanged note count are asserted.
    """
    with pytest.raises(FlashcardError, match=message):
        write_collection(collection, deck, cards)

    assert collection.note_count() == 0


def test_subdeck_context_from_collection_follows_subdeck_mode(
    collection: Any, tmp_path: Path
) -> None:
    """Verify the collection context is only read and announced in subdeck mode.

    Args:
        collection: Open temporary Anki collection.
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions inspect both modes and the notice.
    """
    add_cards_to_collection(collection, "EL1", [Card(front="F?", back="A", subdeck="Filter")])
    source = tmp_path / "vl.md"
    source.write_text("Inhalt", encoding="utf-8")
    base = {"input_file": source, "output": tmp_path / "unused.apkg", "deck": "EL1"}
    normal = resolve_generate_settings(base, AppConfig(), None)
    with_subdecks = resolve_generate_settings({**base, "subdecks": True}, AppConfig(), None)
    events: list[PipelineEvent] = []

    assert subdeck_context_from_collection(normal, collection, report=events.append) is None
    context = subdeck_context_from_collection(with_subdecks, collection, report=events.append)

    assert context is not None and [s.name for s in context.existing] == ["Filter"]
    assert len(events) == 1 and "1 vorhandene Unterdecks" in events[0].text
