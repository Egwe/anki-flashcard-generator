"""Describe figure images through exchangeable local or profile-based picture models."""

import base64
import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from anki_flashcards.ai import AISettings, connection_options
from anki_flashcards.errors import FlashcardError

DESCRIPTION_PROMPT = (
    "Describe this figure from a lecture document factually, so that a reader who "
    "cannot see it learns its content. Name the kind of figure, all labels, axes, "
    "units, values, symbols, components, and how they relate. Transcribe visible "
    "formulas. Do not guess and do not add anything that is not visible. "
    "Answer with plain text in {language}, at most {max_words} words."
)
DEFAULT_MAX_WORDS = 120
LOCAL_DESCRIPTION_LANGUAGE = "English"
DEFAULT_MAX_NEW_TOKENS = 220


@dataclass(frozen=True)
class PictureContext:
    """Describe where a figure appears and what surrounds it.

    Attributes:
        page: One-based PDF page number of the figure.
        caption: Caption text found by the layout analysis, possibly empty.
        text: Text recognized inside the figure, possibly empty.
        language: Natural language requested for the description.
    """

    page: int
    caption: str = ""
    text: str = ""
    language: str = "Deutsch"


class PictureDescriber(Protocol):
    """Turn one figure image into a factual description text."""

    def describe(self, image: Any, context: PictureContext) -> str:
        """Describe one figure.

        Args:
            image: Picture crop, typically a ``PIL.Image.Image``.
            context: Page, caption, recognized text, and target language.

        Returns:
            The description; an empty string means the figure was unreadable.
        """


def description_prompt(context: PictureContext, language: str | None = None) -> str:
    """Build the shared description instruction for every backend.

    Args:
        context: Figure context; caption and recognized text are added as hints.
        language: Optional language overriding ``context.language``.

    Returns:
        The complete instruction sent together with the image.
    """
    prompt = DESCRIPTION_PROMPT.format(
        language=language or context.language, max_words=DEFAULT_MAX_WORDS
    )
    hints = [f"Caption: {context.caption}" if context.caption else ""]
    hints.append(f"Text found in the figure: {context.text}" if context.text else "")
    return "\n".join([prompt, *[hint for hint in hints if hint]])


Generator = Callable[[Any, str], str]


class LocalPictureDescriber:
    """Describe figures with a vision-language model running in this process.

    The model is loaded lazily from a local folder on the first figure, so
    selecting the backend costs nothing when a document has no figures. Small
    local models describe most reliably in English; the card model translates.

    Attributes:
        model_dir: Local folder containing a Hugging Face image-text model.
        max_new_tokens: Upper bound for generated description tokens.
    """

    def __init__(
        self,
        model_dir: Path,
        *,
        max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
        loader: Callable[[Path, int], Generator] | None = None,
    ) -> None:
        """Remember the model folder without loading the model yet.

        Args:
            model_dir: Local folder of the downloaded model.
            max_new_tokens: Upper bound for generated description tokens.
            loader: Optional factory returning ``generate(image, prompt)``;
                defaults to a Transformers implementation. Tests inject fakes.

        Returns:
            None.
        """
        self.model_dir = model_dir
        self.max_new_tokens = max_new_tokens
        self._loader = loader or _load_transformers_generator
        self._generate: Generator | None = None

    def describe(self, image: Any, context: PictureContext) -> str:
        """Describe one figure with the local model.

        Args:
            image: Picture crop as a PIL image.
            context: Figure context used for the shared prompt.

        Returns:
            The stripped description text.

        Raises:
            FlashcardError: If the model cannot be loaded or generation fails.
        """
        if self._generate is None:
            self._generate = self._loader(self.model_dir, self.max_new_tokens)
        prompt = description_prompt(context, LOCAL_DESCRIPTION_LANGUAGE)
        try:
            return self._generate(image, prompt).strip()
        except (RuntimeError, ValueError, TypeError) as error:
            raise FlashcardError(
                f"Local picture model failed on page {context.page}: {error}"
            ) from error


class ProfilePictureDescriber:
    """Describe figures with a model profile through LiteLLM.

    Picture crops are sent to the profile's provider; the caller must have
    announced this transfer and verified that the profile allows image input.

    Attributes:
        settings: Model, endpoint, credential, timeout, and options of the profile.
    """

    def __init__(self, settings: AISettings) -> None:
        """Store the provider settings of the picture profile.

        Args:
            settings: Resolved settings of a profile with ``image_input: true``.

        Returns:
            None.
        """
        self.settings = settings

    def describe(self, image: Any, context: PictureContext) -> str:
        """Send one figure and the shared prompt to the profile model.

        Args:
            image: Picture crop offering ``save(buffer, format="PNG")``.
            context: Figure context used for the shared prompt.

        Returns:
            The stripped description text, empty if the model returned none.

        Raises:
            FlashcardError: If the provider request fails.
        """
        content = [
            {"type": "text", "text": description_prompt(context)},
            {"type": "image_url", "image_url": {"url": _png_data_url(image)}},
        ]
        try:
            response = _completion(
                model=self.settings.model,
                messages=[{"role": "user", "content": content}],
                timeout=self.settings.timeout,
                num_retries=2,
                drop_params=True,
                **self.settings.options,
                **connection_options(self.settings),
            )
        except Exception as error:
            raise FlashcardError(
                f"Picture model request failed for page {context.page}: {error}"
            ) from error
        return _message_text(response)


def _completion(**kwargs: Any) -> Any:
    """Call LiteLLM lazily so tests can replace the picture provider boundary.

    Args:
        **kwargs: Complete LiteLLM completion request options.

    Returns:
        The provider response object in LiteLLM's normalized format.
    """
    from litellm import completion

    return completion(**kwargs)


def _png_data_url(image: Any) -> str:
    """Encode a picture crop as a base64 PNG data URL.

    Args:
        image: Object offering ``save(buffer, format="PNG")`` like a PIL image.

    Returns:
        A ``data:image/png;base64,...`` URL accepted by vision chat APIs.
    """
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _message_text(response: Any) -> str:
    """Extract the first message text from a LiteLLM-style response.

    Args:
        response: Normalized chat completion response.

    Returns:
        The stripped text, or an empty string when the message has no text.
    """
    content = response.choices[0].message.content
    return content.strip() if isinstance(content, str) else ""


def _load_transformers_generator(model_dir: Path, max_new_tokens: int) -> Generator:
    """Load a local Transformers image-text model and return a generator function.

    Args:
        model_dir: Local model folder; nothing is downloaded here.
        max_new_tokens: Upper bound for generated tokens per figure.

    Returns:
        A function ``generate(image, prompt)`` returning decoded new text.

    Raises:
        FlashcardError: If Transformers is missing or the model cannot be loaded.
    """
    try:
        from transformers import AutoModelForImageTextToText, AutoProcessor
    except ImportError as error:
        raise FlashcardError(
            "The local picture model needs the optional PDF extra: pip install -e '.[pdf]'"
        ) from error
    try:
        processor = AutoProcessor.from_pretrained(model_dir, local_files_only=True)
        model = AutoModelForImageTextToText.from_pretrained(model_dir, local_files_only=True)
    except (OSError, ValueError) as error:
        raise FlashcardError(f"Could not load picture model from {model_dir}: {error}") from error
    _disable_image_splitting(processor)

    def generate(image: Any, prompt: str) -> str:
        """Generate a description for one image with the loaded model.

        Args:
            image: PIL image of the figure.
            prompt: Shared description instruction.

        Returns:
            Decoded text generated after the prompt.
        """
        messages = [
            {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}
        ]
        chat = processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = processor(text=chat, images=[image.convert("RGB")], return_tensors="pt")
        output = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        new_tokens = output[:, inputs["input_ids"].shape[1] :]
        return processor.batch_decode(new_tokens, skip_special_tokens=True)[0]

    return generate


def _disable_image_splitting(processor: Any) -> None:
    """Process each figure as one tile instead of many sub-images.

    Some processors (for example SmolVLM) split large images into up to 17
    tiles, which multiplies image tokens and makes CPU inference about ten
    times slower without helping figure descriptions much.

    Args:
        processor: Loaded Transformers processor.

    Returns:
        None. The processor is changed in place when it supports splitting.
    """
    image_processor = getattr(processor, "image_processor", None)
    if hasattr(image_processor, "do_image_splitting"):
        image_processor.do_image_splitting = False
