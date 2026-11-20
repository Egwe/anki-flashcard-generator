"""Keep downloaded conversion models and library caches inside one project folder."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from anki_flashcards.errors import FlashcardError

DEFAULT_MODELS_DIR = Path("models")
MANIFEST_NAME = "downloaded.json"
CACHE_VARIABLES = {
    "HF_HOME": "huggingface",
    "TORCH_HOME": "torch",
    "XDG_CACHE_HOME": "cache",
    "DOCLING_CACHE_DIR": "docling-cache",
}


@dataclass(frozen=True)
class ModelStorage:
    """Describe the single folder that holds every downloaded model and cache.

    Attributes:
        root: Absolute models folder, for example ``<project>/models``.
    """

    root: Path

    @property
    def docling(self) -> Path:
        """Return the Docling artifacts folder for layout, table, OCR, and formula models."""
        return self.root / "docling"

    @property
    def pictures(self) -> Path:
        """Return the folder for locally embedded picture-description models."""
        return self.root / "pictures"

    @property
    def manifest(self) -> Path:
        """Return the JSON file listing components that were downloaded completely."""
        return self.root / MANIFEST_NAME

    def picture_model(self, repo_id: str) -> Path:
        """Return the local folder of one Hugging Face picture model.

        Args:
            repo_id: Hugging Face model identifier such as ``owner/name``.

        Returns:
            A folder below ``pictures`` whose name is the identifier with
            ``/`` replaced by ``--``.
        """
        return self.pictures / repo_id.replace("/", "--")


def configure_model_storage(root: Path) -> ModelStorage:
    """Create the models folder and point library caches of this process into it.

    Libraries such as Hugging Face Hub, PyTorch, and Docling otherwise write
    to user-wide folders like ``~/.cache``. The variables are set for the
    current process only, before those libraries are imported.

    Args:
        root: Absolute or relative models folder; relative paths are taken
            from the current working directory.

    Returns:
        The storage description with an absolute root.

    Raises:
        FlashcardError: If the folder cannot be created.
    """
    storage = ModelStorage(root=root.absolute())
    try:
        storage.root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise FlashcardError(f"Could not create models folder {storage.root}: {error}") from error
    for variable, folder in CACHE_VARIABLES.items():
        os.environ[variable] = str(storage.root / folder)
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    return storage


def downloaded_components(storage: ModelStorage) -> set[str]:
    """Read which model components were downloaded completely.

    Args:
        storage: Configured models folder.

    Returns:
        Component names from the manifest; empty when none was written yet or
        the manifest is unreadable.
    """
    try:
        data = json.loads(storage.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    components = data.get("components") if isinstance(data, dict) else None
    if not isinstance(components, list):
        return set()
    return {str(component) for component in components}


def record_components(storage: ModelStorage, components: set[str]) -> None:
    """Add completely downloaded components to the manifest.

    Args:
        storage: Configured models folder.
        components: Component names whose files are now present.

    Returns:
        None. The manifest is rewritten with the union of old and new names.
    """
    merged = sorted(downloaded_components(storage) | components)
    payload = json.dumps({"components": merged}, indent=2) + "\n"
    storage.manifest.write_text(payload, encoding="utf-8")
