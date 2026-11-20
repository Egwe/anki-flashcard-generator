"""Test picture-description backends without models or network access."""

import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from anki_flashcards.ai import AISettings
from anki_flashcards.errors import FlashcardError
from anki_flashcards.pictures import (
    LocalPictureDescriber,
    PictureContext,
    ProfilePictureDescriber,
    description_prompt,
)

CONTEXT = PictureContext(page=4, caption="Bild 2", text="U_in U_out", language="Deutsch")


class FakeImage:
    """Imitate the PIL ``save`` method with fixed PNG bytes."""

    def save(self, buffer: Any, format: str) -> None:
        """Write fixed bytes into a buffer.

        Args:
            buffer: Binary buffer receiving the image data.
            format: Requested format; must be PNG.

        Returns:
            None.
        """
        assert format == "PNG"
        buffer.write(b"png-bytes")


def test_prompt_contains_language_caption_and_text() -> None:
    """Verify the shared prompt carries the target language and context hints.

    Returns:
        None. Assertions inspect the prompt text.
    """
    prompt = description_prompt(CONTEXT)

    assert "in Deutsch" in prompt
    assert "Caption: Bild 2" in prompt
    assert "Text found in the figure: U_in U_out" in prompt
    assert "Do not guess" in prompt


def test_local_describer_loads_once_and_uses_english(tmp_path: Path) -> None:
    """Verify lazy loading, the English prompt, and stripped output.

    Args:
        tmp_path: Pytest-provided folder standing in for the model folder.

    Returns:
        None. Assertions inspect loader calls and prompts.
    """
    loads: list[tuple[Path, int, str]] = []
    prompts: list[str] = []

    def loader(model_dir: Path, max_new_tokens: int, device: str):
        """Record the load and return a fake generator.

        Args:
            model_dir: Requested model folder.
            max_new_tokens: Requested generation limit.
            device: Requested accelerator.

        Returns:
            A generator returning a padded description.
        """
        loads.append((model_dir, max_new_tokens, device))

        def generate(image: object, prompt: str) -> str:
            """Record the prompt and return a padded description.

            Args:
                image: Picture crop; unused.
                prompt: Prompt built by the describer.

            Returns:
                A description with surrounding whitespace.
            """
            prompts.append(prompt)
            return "  A band diagram.  "

        return generate

    describer = LocalPictureDescriber(tmp_path, max_new_tokens=50, device="cuda", loader=loader)

    assert describer.describe(object(), CONTEXT) == "A band diagram."
    assert describer.describe(object(), CONTEXT) == "A band diagram."
    assert loads == [(tmp_path, 50, "cuda")]
    assert "in English" in prompts[0]


def test_local_describer_reports_generation_errors(tmp_path: Path) -> None:
    """Verify model failures become a user-facing error with the page.

    Args:
        tmp_path: Pytest-provided folder standing in for the model folder.

    Returns:
        None. The assertion expects a FlashcardError.
    """

    def loader(model_dir: Path, max_new_tokens: int, device: str):
        """Return a generator that always fails.

        Args:
            model_dir: Requested model folder.
            max_new_tokens: Requested generation limit.
            device: Requested accelerator.

        Returns:
            A failing generator.
        """

        def generate(image: object, prompt: str) -> str:
            """Raise a runtime error like a broken model.

            Args:
                image: Picture crop; unused.
                prompt: Prompt; unused.

            Returns:
                Never returns.

            Raises:
                RuntimeError: Always.
            """
            raise RuntimeError("out of memory")

        return generate

    describer = LocalPictureDescriber(tmp_path, loader=loader)

    with pytest.raises(FlashcardError, match="page 4.*out of memory"):
        describer.describe(object(), CONTEXT)


def test_profile_describer_sends_image_and_profile_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the LiteLLM request carries image, prompt, and connection data.

    Args:
        monkeypatch: Pytest fixture replacing the provider call.

    Returns:
        None. Assertions inspect the captured request.
    """
    requests: list[dict[str, Any]] = []

    def fake_completion(**kwargs: Any) -> SimpleNamespace:
        """Capture the request and return a padded description.

        Args:
            **kwargs: LiteLLM options built by the describer.

        Returns:
            A LiteLLM-shaped response.
        """
        requests.append(kwargs)
        message = SimpleNamespace(content="  Ein Tiefpass.  ")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr("anki_flashcards.pictures._completion", fake_completion)
    settings = AISettings(
        model="ollama/qwen2.5vl",
        api_key="secret",
        api_base="http://server:11434",
        timeout=60,
        options={"temperature": 0},
    )

    description = ProfilePictureDescriber(settings).describe(FakeImage(), CONTEXT)

    assert description == "Ein Tiefpass."
    request = requests[0]
    assert request["model"] == "ollama/qwen2.5vl"
    assert request["api_base"] == "http://server:11434"
    assert request["api_key"] == "secret"
    assert request["temperature"] == 0
    text, image = request["messages"][0]["content"]
    assert "in Deutsch" in text["text"]
    encoded = base64.b64encode(b"png-bytes").decode()
    assert image["image_url"]["url"] == f"data:image/png;base64,{encoded}"


def test_profile_describer_reports_provider_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify provider failures become a user-facing error with the page.

    Args:
        monkeypatch: Pytest fixture replacing the provider call.

    Returns:
        None. The assertion expects a FlashcardError.
    """

    def failing_completion(**kwargs: Any) -> None:
        """Raise like an unreachable provider.

        Args:
            **kwargs: LiteLLM options; unused.

        Returns:
            Never returns.

        Raises:
            ConnectionError: Always.
        """
        raise ConnectionError("refused")

    monkeypatch.setattr("anki_flashcards.pictures._completion", failing_completion)
    describer = ProfilePictureDescriber(AISettings(model="ollama/x"))

    with pytest.raises(FlashcardError, match="page 4.*refused"):
        describer.describe(FakeImage(), CONTEXT)
