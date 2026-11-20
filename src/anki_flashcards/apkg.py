"""Create, extend, and inspect Anki package files without losing deck data."""

import hashlib
import html
import os
import re
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import genanki
import zstandard

from anki_flashcards.errors import FlashcardError
from anki_flashcards.models import Card
from anki_flashcards.subdecks import ExistingSubdeck, SubdeckContext

MODEL_ID = 1_704_219_001
MODEL_NAME = "KI Karteikarte (Front/Back)"
COLLECTION_FILES = ("collection.anki21b", "collection.anki21", "collection.anki2")
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
SUBDECK_EXAMPLES = 5
EXAMPLE_MAX_CHARS = 200


@dataclass(frozen=True)
class ExportResult:
    """Summarize the outcome of creating or extending one APKG package.

    Attributes:
        path: APKG file that was written.
        deck: Target deck name.
        added: Number of newly written cards.
        skipped: Number of duplicate cards not written.
        added_by_deck: Newly written cards per full deck name, including
            subdecks such as ``Deck::Kapitel``.
    """

    path: Path
    deck: str
    added: int
    skipped: int
    added_by_deck: dict[str, int] = field(default_factory=dict)


def create_apkg(path: Path, deck_name: str, cards: list[Card]) -> ExportResult:
    """Create a new classic APKG with stable deck IDs and note GUIDs.

    Args:
        path: Destination package whose parent directories may be created.
        deck_name: Name of the target deck; cards with a subdeck are placed
            in ``deck_name::subdeck`` and the parent deck is always included.
        cards: Non-empty validated cards to add.

    Returns:
        An export result containing the package path and added-card count.

    Raises:
        FlashcardError: If no cards are supplied or the package cannot be
            generated and atomically moved to its destination.
    """
    if not cards:
        raise FlashcardError("Cannot create an APKG without cards")
    model = _note_model()
    decks = {deck_name: _genanki_deck(deck_name)}
    for card in cards:
        target = _target_deck(deck_name, card)
        if target not in decks:
            decks[target] = _genanki_deck(target)
        decks[target].add_note(
            genanki.Note(
                model=model,
                fields=[html.escape(card.front), html.escape(card.back)],
                tags=card.tags,
                guid=_stable_guid(deck_name, card.front),
            )
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        genanki.Package(list(decks.values())).write_to_file(temporary)
        os.replace(temporary, path)
    except Exception as error:
        raise FlashcardError(f"Could not create {path}: {error}") from error
    finally:
        temporary.unlink(missing_ok=True)
    return ExportResult(
        path=path,
        deck=deck_name,
        added=len(cards),
        skipped=0,
        added_by_deck=_count_by_deck(deck_name, cards),
    )


def append_apkg(path: Path, deck_name: str, cards: list[Card]) -> ExportResult:
    """Extend an APKG through the official Anki API and replace it atomically.

    Args:
        path: Existing classic or zstd-compressed APKG package.
        deck_name: Existing or new target deck inside the package; cards with
            a subdeck are placed in ``deck_name::subdeck``.
        cards: Non-empty cards to add after duplicate filtering.

    Returns:
        Added and skipped counts plus added cards per deck.

    Raises:
        FlashcardError: If the package is unreadable, incompatible, or cannot
            be safely written back in its original collection format.
    """
    if not cards:
        raise FlashcardError("Cannot extend an APKG without cards")
    with tempfile.TemporaryDirectory(prefix="anki-flashcards-") as directory:
        database = Path(directory) / "collection.anki2"
        collection_name = _extract_collection(path, database)
        collection = _open_collection(database)
        try:
            result = _append_to_collection(collection, path, deck_name, cards)
        except FlashcardError:
            raise
        except Exception as error:
            raise FlashcardError(f"Could not extend {path}: {error}") from error
        finally:
            collection.close()
        _checkpoint_collection(database)
        _replace_collection(path, database, collection_name)
        return result


def inspect_apkg(path: Path) -> list[dict[str, Any]]:
    """List normal decks and their direct card counts in an APKG package.

    Args:
        path: Existing classic or zstd-compressed APKG package.

    Returns:
        One dictionary per normal deck with ``id``, ``name``, and ``cards`` keys.

    Raises:
        FlashcardError: If the package or its collection cannot be opened.
    """
    with tempfile.TemporaryDirectory(prefix="anki-flashcards-") as directory:
        database = Path(directory) / "collection.anki2"
        _extract_collection(path, database)
        collection = _open_collection(database)
        try:
            return collection_decks(collection)
        finally:
            collection.close()


def collection_decks(collection: Any) -> list[dict[str, Any]]:
    """List normal decks and their direct card counts in an open collection.

    Args:
        collection: Open official Anki collection; it is only read.

    Returns:
        One dictionary per normal deck with ``id``, ``name``, and ``cards``
        keys; filtered decks are excluded and subdeck cards are not counted
        for their parents.
    """
    return [
        {
            "id": deck.id,
            "name": deck.name,
            "cards": collection.decks.card_count(deck.id, include_subdecks=False),
        }
        for deck in collection.decks.all_names_and_ids(include_filtered=False)
    ]


def read_subdeck_context(
    path: Path, deck_name: str, *, examples: int = SUBDECK_EXAMPLES
) -> SubdeckContext:
    """Read the first-level subdecks of a deck as context for the AI model.

    Args:
        path: Existing classic or zstd-compressed APKG package.
        deck_name: Parent deck; matched case-insensitively like Anki does.
        examples: Maximum sample questions per subdeck, taken from the
            subdeck and its descendants.

    Returns:
        The parent deck name and its subdecks sorted by name, each with plain
        sample questions of at most 200 characters. A missing parent deck
        yields no subdecks. The package file is never modified.

    Raises:
        FlashcardError: If the package or its collection cannot be opened.
    """
    with tempfile.TemporaryDirectory(prefix="anki-flashcards-") as directory:
        database = Path(directory) / "collection.anki2"
        _extract_collection(path, database)
        collection = _open_collection(database)
        try:
            return collection_subdeck_context(collection, deck_name, examples=examples)
        finally:
            collection.close()


def collection_subdeck_context(
    collection: Any, deck_name: str, *, examples: int = SUBDECK_EXAMPLES
) -> SubdeckContext:
    """Read the first-level subdecks of a deck in an open collection.

    Args:
        collection: Open official Anki collection; it is only read.
        deck_name: Parent deck; matched case-insensitively like Anki does.
        examples: Maximum sample questions per subdeck, taken from the
            subdeck and its descendants.

    Returns:
        The parent deck name and its subdecks sorted by name, each with plain
        sample questions of at most 200 characters. A missing parent deck
        yields no subdecks.
    """
    existing = _existing_subdecks(collection, deck_name, examples)
    return SubdeckContext(parent=deck_name, existing=existing)


def add_cards_to_collection(collection: Any, deck_name: str, cards: list[Card]) -> ExportResult:
    """Add unique cards to a deck of an open collection in one Anki operation.

    The rules equal those of ``append_apkg``: same note type, duplicate check
    against the deck (and all its subdecks when a card has a subdeck), stable
    GUIDs, HTML-escaped fields, and ``deck_name::subdeck`` targets. Missing
    decks and the note type are created first; all notes are then added by a
    single undoable ``add_notes`` call. Opening, locking, syncing, and closing
    the collection remain the caller's responsibility.

    Args:
        collection: Open official ``anki.collection.Collection``; modified.
        deck_name: Non-empty target or parent deck name.
        cards: Non-empty validated cards in their preferred insertion order.

    Returns:
        Added and skipped counts plus added cards per deck; ``path`` is the
        collection file.

    Raises:
        FlashcardError: If no cards or no deck name are given, the generated
            note type is incompatible, or Anki rejects the change.
    """
    if not cards:
        raise FlashcardError("Cannot add an empty card list to the collection")
    if not deck_name.strip():
        raise FlashcardError("Deck name must not be empty")
    path = Path(collection.path)
    try:
        return _append_to_collection(collection, path, deck_name, cards)
    except FlashcardError:
        raise
    except Exception as error:
        raise FlashcardError(f"Could not add cards to the collection {path}: {error}") from error


def _existing_subdecks(
    collection: Any, deck_name: str, examples: int
) -> tuple[ExistingSubdeck, ...]:
    """Collect first-level subdecks below a parent deck with sample questions.

    Args:
        collection: Open Anki collection.
        deck_name: Parent deck name.
        examples: Maximum sample questions per subdeck.

    Returns:
        Existing subdecks sorted case-insensitively by name.
    """
    children = _child_deck_names(collection, deck_name)
    subdecks = []
    for name in sorted(children, key=str.casefold):
        deck_id = collection.decks.id_for_name(children[name])
        deck_ids = collection.decks.deck_and_child_ids(deck_id) if deck_id else []
        subdecks.append(ExistingSubdeck(name, _sample_questions(collection, deck_ids, examples)))
    return tuple(subdecks)


def _child_deck_names(collection: Any, deck_name: str) -> dict[str, str]:
    """Map first-level child names of a deck to their full deck names.

    Args:
        collection: Open Anki collection.
        deck_name: Parent deck name, compared case-insensitively.

    Returns:
        Child name without parent prefix mapped to the full Anki deck name.
        Deeper descendants contribute only their first-level ancestor.
    """
    prefix = f"{deck_name}::".casefold()
    children: dict[str, str] = {}
    for deck in collection.decks.all_names_and_ids(include_filtered=False):
        if not deck.name.casefold().startswith(prefix):
            continue
        child = deck.name[len(prefix) :].split("::", 1)[0]
        children.setdefault(child, deck.name[: len(prefix) + len(child)])
    return children


def _sample_questions(collection: Any, deck_ids: list[int], limit: int) -> tuple[str, ...]:
    """Read the first fields of a few notes in the given decks as plain text.

    Args:
        collection: Open Anki collection.
        deck_ids: Deck identifiers whose cards are searched.
        limit: Maximum number of returned questions.

    Returns:
        Up to ``limit`` non-empty plain-text questions in note creation order.
    """
    if not deck_ids or limit <= 0:
        return ()
    placeholders = ",".join("?" * len(deck_ids))
    rows = collection.db.all(
        "SELECT DISTINCT n.id, n.flds FROM notes n JOIN cards c ON c.nid = n.id "
        f"WHERE c.did IN ({placeholders}) ORDER BY n.id LIMIT ?",
        *deck_ids,
        limit,
    )
    questions = (_plain_text(row[1].split("\x1f", 1)[0]) for row in rows)
    return tuple(question for question in questions if question)


def _plain_text(field_content: str) -> str:
    """Convert a stored note field to short plain text for prompts.

    Args:
        field_content: HTML field content from an Anki note.

    Returns:
        Text without tags and entities, with collapsed whitespace, shortened
        to at most 200 characters.
    """
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", field_content)).split())
    if len(text) <= EXAMPLE_MAX_CHARS:
        return text
    return text[: EXAMPLE_MAX_CHARS - 1].rstrip() + "…"


def _append_to_collection(
    collection: Any,
    path: Path,
    deck_name: str,
    cards: list[Card],
) -> ExportResult:
    """Add unique cards to a deck and its subdecks in an open Anki collection.

    Args:
        collection: Open official Anki collection object.
        path: Original package path used in the returned result.
        deck_name: Target deck name; missing decks and subdecks are created.
        cards: Candidate cards in their preferred insertion order.

    Returns:
        Added and duplicate counts plus added cards per deck. Duplicates are
        searched in the target deck, and additionally in all of its subdecks
        when any card carries a subdeck. All new notes are added in one
        ``add_notes`` operation.

    Raises:
        FlashcardError: If an existing generated note type has incompatible
            fields.
    """
    from anki.collection import AddNoteRequest

    model = _compatible_note_type(collection)
    deck_id = collection.decks.id(deck_name)
    existing = _existing_fronts(collection, _duplicate_scope(collection, deck_id, cards))
    added_by_deck: dict[str, int] = {}
    requests = []
    skipped = 0
    for card in cards:
        key = _normalize_front(card.front)
        if key in existing:
            skipped += 1
            continue
        target = _target_deck(deck_name, card)
        note = _new_anki_note(collection, model, deck_name, card)
        requests.append(AddNoteRequest(note=note, deck_id=collection.decks.id(target)))
        existing.add(key)
        added_by_deck[target] = added_by_deck.get(target, 0) + 1
    if requests:
        collection.add_notes(requests)
    return ExportResult(
        path=path,
        deck=deck_name,
        added=sum(added_by_deck.values()),
        skipped=skipped,
        added_by_deck=added_by_deck,
    )


def _compatible_note_type(collection: Any) -> dict[str, Any]:
    """Return the application's note type, creating it when missing.

    Args:
        collection: Open Anki collection.

    Returns:
        The persisted Front/Back note type.

    Raises:
        FlashcardError: If a note type with the same name has other fields.
    """
    if collection.models.by_name(MODEL_NAME) is None:
        collection.models.add(_new_anki_model(collection))
    model = collection.models.by_name(MODEL_NAME)
    fields = [entry["name"] for entry in model["flds"]]
    if fields != ["Front", "Back"]:
        raise FlashcardError(f"Existing note type '{MODEL_NAME}' has incompatible fields")
    return model


def _duplicate_scope(collection: Any, deck_id: int, cards: list[Card]) -> list[int]:
    """Choose the decks whose questions count as duplicates.

    Args:
        collection: Open Anki collection.
        deck_id: Target deck identifier.
        cards: Candidate cards.

    Returns:
        The target deck and all of its subdecks when any card has a subdeck;
        otherwise only the target deck, as before subdeck support.
    """
    if any(card.subdeck for card in cards):
        return list(collection.decks.deck_and_child_ids(deck_id))
    return [deck_id]


def _existing_fronts(collection: Any, deck_ids: list[int]) -> set[str]:
    """Read normalized questions of all notes with cards in the given decks.

    Args:
        collection: Open Anki collection.
        deck_ids: Deck identifiers to search.

    Returns:
        Normalized, HTML-unescaped first fields regardless of note type.
    """
    placeholders = ",".join("?" * len(deck_ids))
    rows = collection.db.all(
        "SELECT n.id, n.flds FROM notes n JOIN cards c ON c.nid = n.id "
        f"WHERE c.did IN ({placeholders})",
        *deck_ids,
    )
    return {_normalize_front(html.unescape(row[1].split("\x1f", 1)[0])) for row in rows}


def _new_anki_note(collection: Any, model: dict[str, Any], deck_name: str, card: Card) -> Any:
    """Build one escaped, not yet persisted note with a stable GUID.

    Args:
        collection: Open Anki collection that creates the note object.
        model: Compatible Front/Back note type.
        deck_name: Target deck name included in the stable GUID.
        card: Plain-text card to convert.

    Returns:
        A new ``anki.notes.Note`` ready for ``add_notes``.
    """
    note = collection.new_note(model)
    note["Front"] = html.escape(card.front)
    note["Back"] = html.escape(card.back)
    note.tags = card.tags
    note.guid = _stable_guid(deck_name, card.front)
    return note


def _new_anki_model(collection: Any) -> dict[str, Any]:
    """Build the application's Front/Back note type in an open collection.

    Args:
        collection: Open Anki collection whose model manager supplies defaults.

    Returns:
        A not-yet-persisted note type with the standard fields, template, and CSS.
    """
    generated = _note_model().to_json(0, 0)
    model = collection.models.new(MODEL_NAME)
    model["css"] = generated["css"]
    for field_spec in generated["flds"]:
        collection.models.add_field(model, collection.models.new_field(field_spec["name"]))
    for template in generated["tmpls"]:
        new_template = collection.models.new_template(template["name"])
        new_template["qfmt"] = template["qfmt"]
        new_template["afmt"] = template["afmt"]
        collection.models.add_template(model, new_template)
    return model


def _open_collection(database: Path) -> Any:
    """Open an extracted SQLite collection using Anki's official Python API.

    Args:
        database: Temporary SQLite collection path.

    Returns:
        An open collection that the caller must close.

    Raises:
        FlashcardError: If Anki cannot read or migrate the collection.
    """
    try:
        from anki.collection import Collection

        return Collection(str(database))
    except Exception as error:
        raise FlashcardError(f"Anki could not open the collection: {error}") from error


def _extract_collection(path: Path, database: Path) -> str:
    """Extract and, when needed, decompress an APKG collection to SQLite.

    Args:
        path: Existing APKG package.
        database: Destination for the uncompressed SQLite collection.

    Returns:
        The collection member name used inside the original package.

    Raises:
        FlashcardError: If the package is missing, invalid, lacks a supported
            collection, or contains invalid zstd data.
    """
    if not path.is_file():
        raise FlashcardError(f"APKG file not found: {path}")
    try:
        with zipfile.ZipFile(path) as package:
            for name in COLLECTION_FILES:
                try:
                    content = package.read(name)
                except KeyError:
                    continue
                if name == "collection.anki21b" and content.startswith(ZSTD_MAGIC):
                    content = zstandard.ZstdDecompressor().decompress(
                        content, max_output_size=2 * 1024 * 1024 * 1024
                    )
                database.write_bytes(content)
                return name
            raise FlashcardError(f"No supported Anki collection found in {path}")
    except FlashcardError:
        raise
    except (OSError, zipfile.BadZipFile, zstandard.ZstdError) as error:
        raise FlashcardError(f"Could not read APKG {path}: {error}") from error


def _checkpoint_collection(database: Path) -> None:
    """Flush SQLite WAL content into the main collection before packaging.

    Args:
        database: Closed SQLite collection file to checkpoint.

    Returns:
        None. The database main file contains all committed changes.
    """
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def _replace_collection(path: Path, database: Path, collection_name: str) -> None:
    """Replace an APKG collection while preserving all other archive entries.

    Args:
        path: Original package to replace atomically.
        database: Updated uncompressed SQLite collection.
        collection_name: Original collection member name and format.

    Returns:
        None. A compressed collection remains zstd-compressed.

    Raises:
        FlashcardError: If reading, compressing, writing, or replacing the
            package fails.
    """
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w") as target:
            for item in source.infolist():
                if item.filename not in COLLECTION_FILES:
                    target.writestr(item, source.read(item.filename))
            content = database.read_bytes()
            if collection_name == "collection.anki21b":
                content = zstandard.ZstdCompressor().compress(content)
            target.writestr(collection_name, content, compress_type=zipfile.ZIP_DEFLATED)
        os.replace(temporary, path)
    except (OSError, zipfile.BadZipFile, zstandard.ZstdError) as error:
        raise FlashcardError(f"Could not save extended APKG {path}: {error}") from error
    finally:
        temporary.unlink(missing_ok=True)


def _note_model() -> genanki.Model:
    """Create the shared plain-text Front/Back genanki note model.

    Returns:
        A model with two fields, one card template, and whitespace-preserving CSS.
    """
    return genanki.Model(
        model_id=MODEL_ID,
        name=MODEL_NAME,
        fields=[{"name": "Front"}, {"name": "Back"}],
        templates=[
            {
                "name": "Karte 1",
                "qfmt": '<div class="front">{{Front}}</div>',
                "afmt": '{{FrontSide}}<hr id="answer"><div class="back">{{Back}}</div>',
            }
        ],
        css=(
            ".card { font-family: sans-serif; font-size: 20px; text-align: left; "
            "color: #222; background-color: #fff; padding: 20px; }\n"
            ".front { white-space: pre-wrap; }\n.back { white-space: pre-wrap; }"
        ),
    )


def _genanki_deck(name: str) -> genanki.Deck:
    """Create a genanki deck whose ID is derived from its full name.

    Args:
        name: Full deck name, possibly with ``::`` subdeck levels.

    Returns:
        An empty genanki deck with a stable identifier.
    """
    return genanki.Deck(deck_id=_stable_id(f"deck:{name}"), name=name)


def _target_deck(deck_name: str, card: Card) -> str:
    """Return the full deck name that receives a card.

    Args:
        deck_name: Target or parent deck name.
        card: Card with an optional single-level subdeck.

    Returns:
        ``deck_name::subdeck`` for cards with a subdeck, otherwise ``deck_name``.
    """
    return f"{deck_name}::{card.subdeck}" if card.subdeck else deck_name


def _count_by_deck(deck_name: str, cards: list[Card]) -> dict[str, int]:
    """Count cards per full target deck name.

    Args:
        deck_name: Target or parent deck name.
        cards: Cards with optional subdecks.

    Returns:
        Number of cards per full deck name in first-occurrence order.
    """
    counts: dict[str, int] = {}
    for card in cards:
        target = _target_deck(deck_name, card)
        counts[target] = counts.get(target, 0) + 1
    return counts


def _stable_id(value: str) -> int:
    """Derive a repeatable positive Anki deck identifier from a string.

    Args:
        value: Stable input such as a qualified deck name.

    Returns:
        An integer between 1 and 2,000,000,000 inclusive.
    """
    digest = hashlib.sha256(value.encode()).digest()
    return int.from_bytes(digest[:4], "big") % 2_000_000_000 + 1


def _normalize_front(front: str) -> str:
    """Normalize question text for case- and whitespace-insensitive comparison.

    Args:
        front: Plain-text question from a new or existing note.

    Returns:
        Case-folded text with each whitespace run reduced to one space.
    """
    return " ".join(front.casefold().split())


def _stable_guid(deck_name: str, front: str) -> str:
    """Derive a stable Anki note GUID from deck and normalized question.

    Args:
        deck_name: Target deck name.
        front: Plain-text question.

    Returns:
        A deterministic GUID accepted by genanki and Anki.
    """
    return genanki.guid_for(deck_name, _normalize_front(front))
