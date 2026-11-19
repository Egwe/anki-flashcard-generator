"""Test APKG creation, data-preserving extension, and package compatibility."""

import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import genanki
import zstandard

from anki_flashcards.apkg import append_apkg, create_apkg, inspect_apkg
from anki_flashcards.models import Card


def open_collection(package: Path) -> tuple[tempfile.TemporaryDirectory, Any]:
    """Open the classic collection of a generated test package.

    Args:
        package: APKG containing an uncompressed collection.anki2 member.

    Returns:
        The owning temporary directory and an open official Anki collection.
        The caller must close the collection and clean up the directory.
    """
    from anki.collection import Collection

    directory = tempfile.TemporaryDirectory(prefix="anki-test-")
    database = Path(directory.name) / "collection.anki2"
    with zipfile.ZipFile(package) as archive:
        content = archive.read("collection.anki2")
    database.write_bytes(content)
    return directory, Collection(str(database))


def test_create_append_and_inspect_preserves_existing_cards(tmp_path: Path) -> None:
    """Verify extension adds new cards and skips normalized duplicates.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions inspect counts and persisted front/back fields.
    """
    package = tmp_path / "biology.apkg"
    create_apkg(
        package,
        "Biologie",
        [Card(front="Was ist DNA?", back="Erbinformation", tags=["Genetik"])],
    )

    result = append_apkg(
        package,
        "Biologie",
        [
            Card(front=" was  ist DNA? ", back="Duplikat"),
            Card(front="Was ist RNA?", back="Ribonukleinsäure"),
        ],
    )

    assert result.added == 1
    assert result.skipped == 1
    decks = {deck["name"]: deck["cards"] for deck in inspect_apkg(package)}
    assert decks["Biologie"] == 2
    directory, collection = open_collection(package)
    try:
        rows = collection.db.all("SELECT flds FROM notes ORDER BY id")
        assert [row[0].split("\x1f") for row in rows] == [
            ["Was ist DNA?", "Erbinformation"],
            ["Was ist RNA?", "Ribonukleinsäure"],
        ]
    finally:
        collection.close()
        directory.cleanup()


def test_extend_unrelated_standard_deck_without_losing_review_history(
    tmp_path: Path,
) -> None:
    """Verify adding a deck preserves an existing card's review state.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions compare the original review fields before and after
        extension and verify the new note's fields and tags.
    """
    package = tmp_path / "existing.apkg"
    deck = genanki.Deck(123_456_789, "Bestehend")
    deck.add_note(
        genanki.Note(
            model=genanki.BASIC_MODEL,
            fields=["Alt?", "Bleibt erhalten"],
            guid="existing-guid",
        )
    )
    genanki.Package(deck).write_to_file(package)

    with tempfile.TemporaryDirectory(prefix="anki-review-setup-") as directory:
        database = Path(directory) / "collection.anki2"
        with zipfile.ZipFile(package) as archive:
            database.write_bytes(archive.read("collection.anki2"))
        with sqlite3.connect(database) as connection:
            original_ids = [row[0] for row in connection.execute("SELECT id FROM cards").fetchall()]
            connection.execute("UPDATE cards SET type = 2, queue = 2, reps = 7, ivl = 30")
        reviewed_package = tmp_path / "reviewed.apkg"
        with zipfile.ZipFile(package) as source, zipfile.ZipFile(reviewed_package, "w") as target:
            for item in source.infolist():
                if item.filename == "collection.anki2":
                    target.write(database, item.filename)
                else:
                    target.writestr(item, source.read(item.filename))
        reviewed_package.replace(package)

    result = append_apkg(package, "Neu", [Card(front="Neu?", back="Hinzugefügt", tags=["Test"])])

    assert result.added == 1
    directory, collection = open_collection(package)
    try:
        assert collection.db.list("SELECT id FROM cards WHERE id = ?", original_ids[0])
        reviewed = collection.db.first(
            "SELECT type, queue, reps, ivl FROM cards WHERE id = ?", original_ids[0]
        )
        assert list(reviewed) == [2, 2, 7, 30]
        new_note = collection.db.first("SELECT flds, tags FROM notes WHERE flds LIKE 'Neu?%'")
        assert new_note[0] == "Neu?\x1fHinzugefügt"
        assert "Test" in new_note[1]
    finally:
        collection.close()
        directory.cleanup()


def test_latest_official_package_is_extended_and_remains_readable(tmp_path: Path) -> None:
    """Verify a real current Anki export remains readable after extension.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions cover duplicate filtering, zstd framing, and SQLite
        card counts.
    """
    from anki.collection import Collection, ExportAnkiPackageOptions

    package = tmp_path / "latest.apkg"
    collection = Collection(str(tmp_path / "latest-source.anki2"))
    try:
        deck_id = collection.decks.id("Test")
        model = collection.models.all()[0]
        note = collection.new_note(model)
        note.fields[0] = "Alt?"
        note.fields[1] = "Antwort"
        collection.add_note(note, deck_id)
        collection.export_anki_package(
            out_path=str(package),
            options=ExportAnkiPackageOptions(legacy=False),
            limit=None,
        )
    finally:
        collection.close()

    result = append_apkg(
        package,
        "Test",
        [
            Card(front=" alt? ", back="Duplikat mit anderem Notiztyp"),
            Card(front="Neu?", back="Antwort"),
        ],
    )

    assert result.added == 1
    assert result.skipped == 1
    with zipfile.ZipFile(package) as archive:
        content = archive.read("collection.anki21b")
        assert content.startswith(b"\x28\xb5\x2f\xfd")
        database = zstandard.ZstdDecompressor().decompress(content)
        assert database.startswith(b"SQLite format 3\x00")
    with tempfile.NamedTemporaryFile(suffix=".anki2") as temporary:
        temporary.write(database)
        temporary.flush()
        with sqlite3.connect(temporary.name) as connection:
            assert connection.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 2


def test_card_text_is_html_escaped_and_duplicate_check_still_works(
    tmp_path: Path,
) -> None:
    """Verify HTML-sensitive text is escaped without defeating deduplication.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions inspect duplicate count and stored escaped fields.
    """
    package = tmp_path / "escaping.apkg"
    create_apkg(
        package,
        "Test",
        [Card(front="Ist 1 < 2 & 3 > 2?", back="Ja & nein <unbekannt>")],
    )

    result = append_apkg(
        package,
        "Test",
        [Card(front="Ist 1 < 2 & 3 > 2?", back="Duplikat")],
    )

    assert result.skipped == 1
    directory, collection = open_collection(package)
    try:
        fields = collection.db.scalar("SELECT flds FROM notes")
        assert fields == "Ist 1 &lt; 2 &amp; 3 &gt; 2?\x1fJa &amp; nein &lt;unbekannt&gt;"
    finally:
        collection.close()
        directory.cleanup()


def test_extension_preserves_other_package_entries(tmp_path: Path) -> None:
    """Verify extension retains an unrelated media archive entry byte for byte.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. The assertion compares the media payload after package rewriting.
    """
    package = tmp_path / "media.apkg"
    create_apkg(package, "Test", [Card(front="Alt?", back="Antwort")])
    with zipfile.ZipFile(package, "a") as archive:
        archive.writestr("0", b"image-data")

    append_apkg(package, "Test", [Card(front="Neu?", back="Antwort")])

    with zipfile.ZipFile(package) as archive:
        assert archive.read("0") == b"image-data"


def deck_card_counts(package: Path) -> dict[str, int]:
    """Read direct card counts of all normal decks in a classic test package.

    Args:
        package: APKG containing an uncompressed collection.anki2 member.

    Returns:
        Mapping of full deck names to their direct card counts.
    """
    directory, collection = open_collection(package)
    try:
        return {
            deck.name: collection.decks.card_count(deck.id, include_subdecks=False)
            for deck in collection.decks.all_names_and_ids(include_filtered=False)
        }
    finally:
        collection.close()
        directory.cleanup()


def test_create_apkg_places_cards_in_subdecks(tmp_path: Path) -> None:
    """Verify new packages contain the parent deck and every used subdeck.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions inspect deck counts and the per-deck result.
    """
    package = tmp_path / "el1.apkg"
    result = create_apkg(
        package,
        "EL1",
        [
            Card(front="A?", back="1", subdeck="Grundlagen"),
            Card(front="B?", back="2", subdeck="Grundlagen"),
            Card(front="C?", back="3", subdeck="Netzwerke"),
            Card(front="D?", back="4"),
        ],
    )

    counts = deck_card_counts(package)
    assert counts["EL1"] == 1
    assert counts["EL1::Grundlagen"] == 2
    assert counts["EL1::Netzwerke"] == 1
    assert result.added == 4
    assert result.added_by_deck == {"EL1::Grundlagen": 2, "EL1::Netzwerke": 1, "EL1": 1}


def test_append_with_subdecks_reuses_creates_and_skips_tree_duplicates(tmp_path: Path) -> None:
    """Verify extension reuses subdecks, creates new ones, and checks the deck tree.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions inspect counts, skipped duplicates, and kept cards.
    """
    package = tmp_path / "el1.apkg"
    create_apkg(package, "EL1", [Card(front="Was ist Strom?", back="Fluss", subdeck="Grundlagen")])

    result = append_apkg(
        package,
        "EL1",
        [
            Card(front=" was ist  STROM? ", back="Duplikat", subdeck="Netzwerke"),
            Card(front="Was ist Spannung?", back="Potenzial", subdeck="Grundlagen"),
            Card(front="Was ist ein Knoten?", back="Verbindung", subdeck="Netzwerke"),
        ],
    )

    counts = deck_card_counts(package)
    assert result.added == 2
    assert result.skipped == 1
    assert result.added_by_deck == {"EL1::Grundlagen": 1, "EL1::Netzwerke": 1}
    assert counts["EL1::Grundlagen"] == 2
    assert counts["EL1::Netzwerke"] == 1


def test_normal_extension_keeps_direct_deck_duplicate_scope(tmp_path: Path) -> None:
    """Verify cards without subdecks still compare only with the target deck.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. A question that exists only in a subdeck is added to the parent.
    """
    package = tmp_path / "el1.apkg"
    create_apkg(package, "EL1", [Card(front="Was ist Strom?", back="Fluss", subdeck="Grundlagen")])

    result = append_apkg(package, "EL1", [Card(front="Was ist Strom?", back="Direkt")])

    assert result.added == 1
    assert deck_card_counts(package)["EL1"] == 1


def test_read_subdeck_context_lists_direct_children_without_changes(tmp_path: Path) -> None:
    """Verify context reading returns first-level subdecks and bounded examples.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions inspect names, examples, other decks, and file bytes.
    """
    from anki_flashcards.apkg import read_subdeck_context

    package = tmp_path / "el1.apkg"
    grundlagen = [Card(front=f"Frage {n}?", back="A", subdeck="Grundlagen") for n in range(6)]
    create_apkg(
        package,
        "EL1",
        [
            *grundlagen,
            Card(front="Ist a < b & c?", back="Ja", subdeck="Netzwerke"),
            Card(front="Direkt im Elterndeck?", back="Ja"),
        ],
    )
    append_apkg(package, "EL1::Netzwerke::Vertiefung", [Card(front="Tief?", back="Ja")])
    append_apkg(package, "Andere", [Card(front="Fremd?", back="Ja", subdeck="Kapitel")])
    before = package.read_bytes()

    context = read_subdeck_context(package, "el1")
    missing = read_subdeck_context(package, "Unbekannt")

    assert context.parent == "el1"
    assert [subdeck.name for subdeck in context.existing] == ["Grundlagen", "Netzwerke"]
    assert len(context.existing[0].examples) == 5
    assert set(context.existing[1].examples) == {"Ist a < b & c?", "Tief?"}
    assert missing.existing == ()
    assert package.read_bytes() == before
