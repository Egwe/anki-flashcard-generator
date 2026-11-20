"""Test model storage and the Docling adapter boundary without Docling or downloads."""

import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from anki_flashcards import docling_pdf
from anki_flashcards.docling_pdf import (
    convert_pdf,
    ensure_conversion_models,
    ensure_picture_model,
    require_docling,
)
from anki_flashcards.errors import FlashcardError
from anki_flashcards.model_storage import (
    CACHE_VARIABLES,
    configure_model_storage,
    downloaded_components,
    record_components,
)
from anki_flashcards.structured_pdf import ConversionOptions, ExtractedPage, ExtractedPdf


@pytest.fixture
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Configure a temporary models folder and restore cache variables afterwards.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture restoring environment variables.

    Returns:
        The configured model storage below ``tmp_path``.
    """
    for variable in [*CACHE_VARIABLES, "HF_HUB_DISABLE_TELEMETRY"]:
        monkeypatch.setenv(variable, "unchanged")
    return configure_model_storage(tmp_path / "models")


def fake_module(monkeypatch: pytest.MonkeyPatch, name: str, **attributes: Any) -> None:
    """Install a fake module and its parent packages for one test.

    Args:
        monkeypatch: Pytest fixture restoring ``sys.modules``.
        name: Dotted module name.
        **attributes: Functions or values exposed by the module.

    Returns:
        None.
    """
    parts = name.split(".")
    for index in range(1, len(parts) + 1):
        module = ModuleType(".".join(parts[:index]))
        monkeypatch.setitem(sys.modules, module.__name__, module)
    for key, value in attributes.items():
        setattr(sys.modules[name], key, value)


def test_storage_points_every_cache_into_the_models_folder(storage) -> None:
    """Verify all library cache variables point below the models folder.

    Args:
        storage: Configured temporary model storage.

    Returns:
        None. Assertions inspect folder and environment.
    """
    assert storage.root.is_dir()
    for variable, folder in CACHE_VARIABLES.items():
        assert os.environ[variable] == str(storage.root / folder)
    assert storage.picture_model("owner/name") == storage.root / "pictures" / "owner--name"


def test_manifest_roundtrip_and_corrupt_file(storage) -> None:
    """Verify recorded components accumulate and a corrupt manifest is ignored.

    Args:
        storage: Configured temporary model storage.

    Returns:
        None. Assertions inspect the recorded component names.
    """
    record_components(storage, {"layout"})
    record_components(storage, {"rapidocr"})

    assert downloaded_components(storage) == {"layout", "rapidocr"}
    storage.manifest.write_text("{broken", encoding="utf-8")
    assert downloaded_components(storage) == set()


def test_require_docling_explains_installation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a missing extra produces the installation command.

    Args:
        monkeypatch: Pytest fixture hiding the Docling package.

    Returns:
        None. The assertion expects the install hint.
    """
    monkeypatch.setattr(docling_pdf.importlib.util, "find_spec", lambda name: None)

    with pytest.raises(FlashcardError, match=r"pip install --no-cache-dir -e '\.\[pdf\]'"):
        require_docling()


def test_conversion_models_download_once_into_storage(
    storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify missing components are downloaded into the models folder once.

    Args:
        storage: Configured temporary model storage.
        monkeypatch: Pytest fixture replacing Docling's downloader.

    Returns:
        None. Assertions inspect downloader calls, notices, and manifest.
    """
    calls: list[dict[str, Any]] = []
    fake_module(
        monkeypatch,
        "docling.utils.model_downloader",
        download_models=lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(docling_pdf, "require_docling", lambda: None)
    notices: list[str] = []

    ensure_conversion_models(storage, formulas=False, announce=notices.append)
    ensure_conversion_models(storage, formulas=False, announce=notices.append)

    assert len(calls) == 1
    assert calls[0]["output_dir"] == storage.docling
    assert calls[0]["with_code_formula"] is False
    assert calls[0]["with_easyocr"] is False
    assert len(notices) == 1 and str(storage.docling) in notices[0]
    ensure_conversion_models(storage, formulas=True, announce=notices.append)
    assert calls[1]["with_code_formula"] is True and calls[1]["with_layout"] is False


def test_picture_model_downloads_once_without_onnx(
    storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify the picture model lands in the models folder without ONNX copies.

    Args:
        storage: Configured temporary model storage.
        monkeypatch: Pytest fixture replacing the Hugging Face downloader.

    Returns:
        None. Assertions inspect downloader arguments and repeated calls.
    """
    calls: list[dict[str, Any]] = []
    fake_module(
        monkeypatch, "huggingface_hub", snapshot_download=lambda **kwargs: calls.append(kwargs)
    )

    first = ensure_picture_model(storage, "owner/vlm", announce=lambda message: None)
    second = ensure_picture_model(storage, "owner/vlm", announce=lambda message: None)

    assert first == second == storage.root / "pictures" / "owner--vlm"
    assert len(calls) == 1
    assert calls[0]["local_dir"] == first
    assert "onnx/*" in calls[0]["ignore_patterns"]


def test_convert_pdf_uses_extractor_without_docling(
    storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify an injected extractor replaces Docling and model downloads.

    Args:
        storage: Configured temporary model storage.
        monkeypatch: Pytest fixture making real Docling use fail.

    Returns:
        None. Assertions inspect the rendered text.
    """

    def forbidden() -> None:
        """Fail if the real Docling path is used.

        Returns:
            Never returns.

        Raises:
            AssertionError: Always.
        """
        raise AssertionError("Docling must not be used")

    monkeypatch.setattr(docling_pdf, "require_docling", forbidden)

    def extractor(path: Path, options: ConversionOptions, models, progress) -> ExtractedPdf:
        """Return one prepared page.

        Args:
            path: Requested PDF.
            options: Conversion options.
            models: Model storage.
            progress: Optional progress callback.

        Returns:
            A one-page extraction.
        """
        return ExtractedPdf(pages=(ExtractedPage(1, "Inhalt"),))

    result = convert_pdf(
        Path("skript.pdf"),
        ConversionOptions(),
        storage,
        describer=None,
        announce=lambda message: None,
        extractor=extractor,
    )

    assert result.document.text == "[Seite 1]\nInhalt"


def test_convert_pdf_rejects_other_formats(storage) -> None:
    """Verify the structured mode refuses non-PDF input before any work.

    Args:
        storage: Configured temporary model storage.

    Returns:
        None. The assertion expects a clear error.
    """
    with pytest.raises(FlashcardError, match="only accepts .pdf"):
        convert_pdf(
            Path("notes.docx"),
            ConversionOptions(),
            storage,
            describer=None,
            announce=lambda message: None,
        )
