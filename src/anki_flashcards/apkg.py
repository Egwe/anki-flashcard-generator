"""Create, extend, and inspect Anki package files without losing deck data."""

import hashlib
import html
import os
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import genanki
import zstandard

from anki_flashcards.errors import FlashcardError
from anki_flashcards.models import Card

MODEL_ID = 1_704_219_001
MODEL_NAME = "KI Karteikarte (Front/Back)"
COLLECTION_FILES = ("collection.anki21b", "collection.anki21", "collection.anki2")
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


@dataclass(frozen=True)
class ExportResult:
    """Summarize the outcome of creating or extending one APKG package.

    Attributes:
        path: APKG file that was written.
        deck: Target deck name.
        added: Number of newly written cards.
        skipped: Number of duplicate cards not written.
    """

    path: Path
    deck: str
    added: int
    skipped: int


def create_apkg(path: Path, deck_name: str, cards: list[Card]) -> ExportResult:
    """Create a new classic APKG with a stable deck ID and note GUIDs.

    Args:
        path: Destination package whose parent directories may be created.
        deck_name: Name of the single generated deck.
        cards: Non-empty validated cards to add to the deck.

    Returns:
        An export result containing the package path and added-card count.

    Raises:
        FlashcardError: If no cards are supplied or the package cannot be
            generated and atomically moved to its destination.
    """
    if not cards:
        raise FlashcardError("Cannot create an APKG without cards")
    model = _note_model()
    deck = genanki.Deck(deck_id=_stable_id(f"deck:{deck_name}"), name=deck_name)
    for card in cards:
        deck.add_note(
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
        genanki.Package(deck).write_to_file(temporary)
        os.replace(temporary, path)
    except Exception as error:
        raise FlashcardError(f"Could not create {path}: {error}") from error
    finally:
        temporary.unlink(missing_ok=True)
    return ExportResult(path=path, deck=deck_name, added=len(cards), skipped=0)


def append_apkg(path: Path, deck_name: str, cards: list[Card]) -> ExportResult:
    """Extend an APKG through the official Anki API and replace it atomically.

    Args:
        path: Existing classic or zstd-compressed APKG package.
        deck_name: Existing or new target deck inside the package.
        cards: Non-empty cards to add after duplicate filtering.

    Returns:
        The number of added and skipped cards for the target deck.

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
            return [
                {
                    "id": deck.id,
                    "name": deck.name,
                    "cards": collection.decks.card_count(deck.id, include_subdecks=False),
                }
                for deck in collection.decks.all_names_and_ids(include_filtered=False)
            ]
        finally:
            collection.close()


def _append_to_collection(
    collection: Any,
    path: Path,
    deck_name: str,
    cards: list[Card],
) -> ExportResult:
    """Add unique cards to one deck of an open Anki collection.

    Args:
        collection: Open official Anki collection object.
        path: Original package path used in the returned result.
        deck_name: Target deck name.
        cards: Candidate cards in their preferred insertion order.

    Returns:
        Added and duplicate counts for the target deck.

    Raises:
        FlashcardError: If an existing generated note type has incompatible
            fields.
    """
    model = collection.models.by_name(MODEL_NAME)
    if model is None:
        model = _new_anki_model(collection)
        collection.models.add(model)
    model = collection.models.by_name(MODEL_NAME)
    fields = [field["name"] for field in model["flds"]]
    if fields != ["Front", "Back"]:
        raise FlashcardError(f"Existing note type '{MODEL_NAME}' has incompatible fields")

    deck_id = collection.decks.id(deck_name)
    rows = collection.db.all(
        "SELECT n.id, n.flds FROM notes n JOIN cards c ON c.nid = n.id WHERE c.did = ?",
        deck_id,
    )
    existing = {_normalize_front(html.unescape(row[1].split("\x1f", 1)[0])) for row in rows}
    added = 0
    skipped = 0
    for card in cards:
        key = _normalize_front(card.front)
        if key in existing:
            skipped += 1
            continue
        _add_anki_note(collection, model, deck_id, deck_name, card)
        existing.add(key)
        added += 1
    return ExportResult(path=path, deck=deck_name, added=added, skipped=skipped)


def _add_anki_note(
    collection: Any,
    model: dict[str, Any],
    deck_id: int,
    deck_name: str,
    card: Card,
) -> None:
    """Write one escaped card with a stable GUID through the Anki API.

    Args:
        collection: Open Anki collection used for persistence.
        model: Compatible Front/Back note type.
        deck_id: Numeric target deck identifier.
        deck_name: Target deck name included in the stable GUID.
        card: Plain-text card to persist.

    Returns:
        None. One note and its generated card are added to the collection.
    """
    note = collection.new_note(model)
    note["Front"] = html.escape(card.front)
    note["Back"] = html.escape(card.back)
    note.tags = card.tags
    note.guid = _stable_guid(deck_name, card.front)
    collection.add_note(note, deck_id)


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
    for field in generated["flds"]:
        collection.models.add_field(model, collection.models.new_field(field["name"]))
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
