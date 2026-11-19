"""Assign AI-generated cards to chapter subdecks consistently across requests."""

from dataclasses import dataclass

from anki_flashcards.models import Card, CardBatch, SubdeckCardBatch, normalize_key

SUBDECK_RULES = """
Also assign every card to exactly one chapter subdeck. Each card then has the form
{"front": "...", "back": "...", "tags": [], "subdeck": "..."}.
Derive subdecks from the structure of the source: chapter or section headings, their numbering,
or a table of contents. Prefer few, coarse chapters over many narrow ones.
Reuse a known subdeck whenever the card fits it and spell its name exactly as listed.
Create a new subdeck only for content that fits none of the known subdecks and name it after the
matching chapter of the source. Write only the subdeck name: no parent deck name and no "::".
"""


@dataclass(frozen=True)
class ExistingSubdeck:
    """Describe a subdeck that already exists below the target deck.

    Attributes:
        name: Single-level subdeck name without the parent deck prefix.
        examples: Short sample questions that show the subdeck's content.
    """

    name: str
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class SubdeckContext:
    """Provide the parent deck and its known subdecks for one generation run.

    Attributes:
        parent: Target deck that receives the generated subdecks.
        existing: Subdecks already present below the parent deck.
    """

    parent: str
    existing: tuple[ExistingSubdeck, ...] = ()


class SubdeckAssigner:
    """Apply subdeck mode consistently to prompts, schemas, and returned cards.

    Without a context the assigner represents normal mode: prompts and schema
    stay unchanged and any subdeck returned by a model is discarded. With a
    context it adds the subdeck rules, lists known subdecks, unifies spelling
    variants, and remembers new subdecks for later requests of the same run.

    Attributes:
        context: Parent deck and existing subdecks, or None for normal mode.
    """

    def __init__(self, context: SubdeckContext | None) -> None:
        """Initialize known subdeck names from the optional context.

        Args:
            context: Parent deck and existing subdecks, or None for normal mode.

        Returns:
            None. Existing names become the preferred spellings.
        """
        self.context = context
        self._names: dict[str, str] = {}
        self._created: list[str] = []
        for subdeck in context.existing if context else ():
            self._names.setdefault(normalize_key(subdeck.name), subdeck.name)

    @property
    def enabled(self) -> bool:
        """Return whether cards are assigned to subdecks in this run."""
        return self.context is not None

    @property
    def response_model(self) -> type[CardBatch]:
        """Return the Pydantic schema requested from and validated for the model."""
        return SubdeckCardBatch if self.enabled else CardBatch

    @property
    def created(self) -> tuple[str, ...]:
        """Return subdeck names first introduced during this run, in order."""
        return tuple(self._created)

    def system_prompt(self, base: str) -> str:
        """Extend the base system prompt with subdeck rules when enabled.

        Args:
            base: Shared card-quality system prompt.

        Returns:
            The base prompt, followed by the subdeck rules in subdeck mode.
        """
        return base + SUBDECK_RULES if self.enabled else base

    def prompt_section(self) -> str:
        """Describe the parent deck and all currently known subdecks.

        Returns:
            A delimited user-prompt section, or an empty string in normal mode.
        """
        if self.context is None:
            return ""
        lines = [f"- {subdeck.name}{_examples(subdeck)}" for subdeck in self.context.existing]
        lines.extend(f"- {name} (new in this run)" for name in self._created)
        known = "\n".join(lines) or "none yet"
        return (
            "Parent deck (do not repeat it in subdeck names):\n"
            f"<parent_deck>{self.context.parent}</parent_deck>\n"
            "Known subdecks; reuse them when the content fits:\n"
            f"<known_subdecks>\n{known}\n</known_subdecks>"
        )

    def assign(self, cards: list[Card]) -> list[Card]:
        """Return plain cards with unified subdecks, or without them in normal mode.

        Args:
            cards: Validated cards from one model response.

        Returns:
            New ``Card`` objects in the original order. Side effect: subdeck
            names seen for the first time are remembered for later prompts.
        """
        if not self.enabled:
            return [_with_subdeck(card, None) for card in cards]
        return [_with_subdeck(card, self._known_name(card.subdeck)) for card in cards]

    def _known_name(self, name: str | None) -> str | None:
        """Map a subdeck name to its first known spelling or register it.

        Args:
            name: Validated subdeck name from the model, or None.

        Returns:
            The preferred spelling, or None when the card has no subdeck.
        """
        if name is None:
            return None
        key = normalize_key(name)
        if key in self._names:
            return self._names[key]
        self._names[key] = name
        self._created.append(name)
        return name


def _examples(subdeck: ExistingSubdeck) -> str:
    """Format sample questions of an existing subdeck for the prompt.

    Args:
        subdeck: Existing subdeck with optional sample questions.

    Returns:
        An indented example line, or an empty string without samples.
    """
    if not subdeck.examples:
        return ""
    return "\n  Example questions: " + " | ".join(subdeck.examples)


def _with_subdeck(card: Card, subdeck: str | None) -> Card:
    """Copy a card into the plain ``Card`` type with the given subdeck.

    Args:
        card: Validated source card, possibly a ``SubdeckCard``.
        subdeck: Subdeck to assign, or None for the target deck itself.

    Returns:
        A newly validated ``Card``.
    """
    return Card(front=card.front, back=card.back, tags=list(card.tags), subdeck=subdeck)
