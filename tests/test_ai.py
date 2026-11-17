import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from anki_flashcards.ai import AISettings, generate_cards
from anki_flashcards.documents import SourceDocument
from anki_flashcards.errors import FlashcardError


def response(payload: Any) -> SimpleNamespace:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    message = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def document() -> SourceDocument:
    return SourceDocument(path=Path("source.txt"), text="Die Erde dreht sich um die Sonne.")


def test_generates_valid_unique_cards_up_to_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict[str, Any]] = []

    def fake_completion(**kwargs: Any) -> SimpleNamespace:
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
    requests: list[dict[str, Any]] = []

    def fake_completion(**kwargs: Any) -> SimpleNamespace:
        requests.append(kwargs)
        return response({"cards": [{"front": "F?", "back": "A"}]})

    monkeypatch.setattr("anki_flashcards.ai._completion", fake_completion)
    cards = generate_cards(document(), AISettings(model="ollama/test"), limit=0)

    assert len(cards) == 1
    assert "without an arbitrary limit" in requests[0]["messages"][1]["content"]


def test_invalid_ai_json_is_a_user_facing_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("anki_flashcards.ai._completion", lambda **kwargs: response("not JSON"))

    with pytest.raises(FlashcardError, match="invalid card data"):
        generate_cards(document(), AISettings(model="openai/test"))
