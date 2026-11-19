"""Test AI subdeck prompts, response schemas, and consistent name assignment."""

from anki_flashcards.models import Card, CardBatch, SubdeckCard, SubdeckCardBatch
from anki_flashcards.subdecks import (
    SUBDECK_RULES,
    ExistingSubdeck,
    SubdeckAssigner,
    SubdeckContext,
)


def context() -> SubdeckContext:
    """Create a lecture context with one existing chapter subdeck.

    Returns:
        A context for parent deck ``EL1`` with sample questions.
    """
    return SubdeckContext(
        parent="EL1",
        existing=(
            ExistingSubdeck("Kapitel 1 – Grundlagen", ("Was ist Strom?", "Was ist Spannung?")),
        ),
    )


def test_disabled_assigner_keeps_normal_mode_unchanged() -> None:
    """Verify normal mode keeps the base prompt and discards model subdecks.

    Returns:
        None. Assertions inspect prompts, schema, and returned cards.
    """
    assigner = SubdeckAssigner(None)

    cards = assigner.assign([Card(front="F?", back="A", subdeck="Unerwünscht")])

    assert not assigner.enabled
    assert assigner.response_model is CardBatch
    assert assigner.system_prompt("BASE") == "BASE"
    assert assigner.prompt_section() == ""
    assert cards == [Card(front="F?", back="A")]


def test_enabled_assigner_describes_context_and_schema() -> None:
    """Verify subdeck mode adds rules, parent deck, known names, and examples.

    Returns:
        None. Assertions inspect the generated prompt text and response model.
    """
    assigner = SubdeckAssigner(context())
    section = assigner.prompt_section()

    assert assigner.enabled
    assert assigner.response_model is SubdeckCardBatch
    assert assigner.system_prompt("BASE") == "BASE" + SUBDECK_RULES
    assert "<parent_deck>EL1</parent_deck>" in section
    assert "- Kapitel 1 – Grundlagen" in section
    assert "Was ist Strom? | Was ist Spannung?" in section


def test_names_are_unified_and_new_subdecks_are_remembered() -> None:
    """Verify spelling variants map to known names and new names persist.

    Returns:
        None. Assertions inspect assigned names, created names, and prompts.
    """
    assigner = SubdeckAssigner(context())

    first = assigner.assign(
        [
            SubdeckCard(front="A?", back="1", subdeck=" kapitel 1 –  grundlagen "),
            SubdeckCard(front="B?", back="2", subdeck="Kapitel 2 – Netzwerke"),
        ]
    )
    second = assigner.assign([SubdeckCard(front="C?", back="3", subdeck="KAPITEL 2 – NETZWERKE")])

    assert [card.subdeck for card in first + second] == [
        "Kapitel 1 – Grundlagen",
        "Kapitel 2 – Netzwerke",
        "Kapitel 2 – Netzwerke",
    ]
    assert all(type(card) is Card for card in first + second)
    assert assigner.created == ("Kapitel 2 – Netzwerke",)
    assert "- Kapitel 2 – Netzwerke (new in this run)" in assigner.prompt_section()


def test_context_without_existing_subdecks_says_so() -> None:
    """Verify a new parent deck tells the model that no subdecks exist yet.

    Returns:
        None. The assertion inspects the empty known-subdeck block.
    """
    section = SubdeckAssigner(SubdeckContext(parent="Neu")).prompt_section()

    assert "<known_subdecks>\nnone yet\n</known_subdecks>" in section
