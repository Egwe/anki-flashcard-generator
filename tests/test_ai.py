"""Test provider request construction and validated card generation."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from anki_flashcards.ai import AISettings, generate_cards
from anki_flashcards.documents import SourceDocument
from anki_flashcards.errors import FlashcardError


def response(payload: Any) -> SimpleNamespace:
    """Build a minimal LiteLLM-shaped response for provider-boundary tests.

    Args:
        payload: Response text or a JSON-serializable object.

    Returns:
        A response namespace whose first message contains the payload text.
    """
    content = payload if isinstance(payload, str) else json.dumps(payload)
    message = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def document() -> SourceDocument:
    """Create a small deterministic source document for generation tests.

    Returns:
        A source document containing one astronomical fact.
    """
    return SourceDocument(path=Path("source.txt"), text="Die Erde dreht sich um die Sonne.")


def test_generates_valid_unique_cards_up_to_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify provider options, prompt allocation, deduplication, and limit.

    Args:
        monkeypatch: Pytest fixture used to replace the external AI client.

    Returns:
        None. Assertions inspect generated cards and the captured request.
    """
    requests: list[dict[str, Any]] = []

    def fake_completion(**kwargs: Any) -> SimpleNamespace:
        """Capture a completion request and return three candidate cards.

        Args:
            **kwargs: LiteLLM options supplied by the application.

        Returns:
            A valid response containing one duplicate question.
        """
        requests.append(kwargs)
        return response(
            {
                "cards": [
                    {"front": "Frage 1?", "back": "Antwort 1", "tags": ["Physik"]},
                    {"front": "Frage 2?", "back": "Antwort 2"},
                    {"front": " frage 1? ", "back": "Duplikat"},
                ]
            }
        )

    monkeypatch.setattr("anki_flashcards.ai._completion", fake_completion)
    cards = generate_cards(
        document(),
        AISettings(model="openai/test", api_key="secret", api_base="http://localhost"),
        limit=2,
    )

    assert [(card.front, card.back) for card in cards] == [
        ("Frage 1?", "Antwort 1"),
        ("Frage 2?", "Antwort 2"),
    ]
    assert requests[0]["model"] == "openai/test"
    assert requests[0]["api_key"] == "secret"
    assert requests[0]["api_base"] == "http://localhost"
    assert "at most 2 cards" in requests[0]["messages"][1]["content"]


def test_unlimited_mode_does_not_invent_a_card_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify unlimited mode omits an arbitrary numeric card target.

    Args:
        monkeypatch: Pytest fixture used to replace the external AI client.

    Returns:
        None. Assertions check the returned batch and unlimited prompt text.
    """
    requests: list[dict[str, Any]] = []

    def fake_completion(**kwargs: Any) -> SimpleNamespace:
        """Capture a request and return one valid card.

        Args:
            **kwargs: LiteLLM options supplied by the application.

        Returns:
            A response containing one question-answer pair.
        """
        requests.append(kwargs)
        return response({"cards": [{"front": "F?", "back": "A"}]})

    monkeypatch.setattr("anki_flashcards.ai._completion", fake_completion)
    cards = generate_cards(document(), AISettings(model="ollama/test"), limit=0)

    assert len(cards) == 1
    assert "without an arbitrary limit" in requests[0]["messages"][1]["content"]


def test_invalid_ai_json_is_a_user_facing_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify malformed provider JSON becomes a concise application error.

    Args:
        monkeypatch: Pytest fixture used to replace the external AI client.

    Returns:
        None. The assertion requires FlashcardError for invalid response data.
    """

    def invalid_completion(**kwargs: Any) -> SimpleNamespace:
        """Return deliberately malformed JSON regardless of request options.

        Args:
            **kwargs: Unused LiteLLM request options.

        Returns:
            A provider-shaped response containing non-JSON text.
        """
        return response("not JSON")

    monkeypatch.setattr("anki_flashcards.ai._completion", invalid_completion)

    with pytest.raises(FlashcardError, match="invalid card data"):
        generate_cards(document(), AISettings(model="openai/test"))
