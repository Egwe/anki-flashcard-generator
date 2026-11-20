"""Application-specific exceptions suitable for concise CLI reporting."""


class FlashcardError(Exception):
    """An expected, user-facing application error."""


class GenerationCancelled(FlashcardError):
    """A caller asked a running generation to stop before anything was written."""
