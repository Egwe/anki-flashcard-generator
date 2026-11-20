"""Test model storage and the Docling adapter boundary without Docling or downloads."""

import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from anki_flashcards import docling_pdf
from anki_flashcards.docling_pdf import (
    available_accelerator,
    convert_pdf,
    ensure_conversion_models,
    ensure_picture_model,
    limit_formula_batch,
    require_accelerator,
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

    def extractor(path: Path, options: ConversionOptions, models, device, progress) -> ExtractedPdf:
        """Return one prepared page.

        Args:
            path: Requested PDF.
            options: Conversion options.
            models: Model storage.
            device: Accelerator selected for Docling.
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


def fake_torch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cuda: bool,
    mps: bool = False,
    capability: tuple[int, int] = (8, 6),
    arch_list: tuple[str, ...] = ("sm_80", "sm_86", "sm_90"),
) -> None:
    """Install a fake ``torch`` module reporting the given accelerators.

    Args:
        monkeypatch: Pytest fixture restoring ``sys.modules``.
        cuda: Whether CUDA (or ROCm through the CUDA API) is available.
        mps: Whether Apple's Metal backend is available.
        capability: Compute capability of CUDA device 0.
        arch_list: Architectures the fake PyTorch build contains.

    Returns:
        None.
    """
    torch = ModuleType("torch")
    torch.__version__ = "2.99.0+fake"
    torch.cuda = ModuleType("torch.cuda")
    torch.cuda.is_available = lambda: cuda
    torch.cuda.get_device_capability = lambda device=0: capability
    torch.cuda.get_arch_list = lambda: list(arch_list)
    torch.cuda.get_device_name = lambda device=0: "Quadro K1200"
    torch.backends = ModuleType("torch.backends")
    torch.backends.mps = ModuleType("torch.backends.mps")
    torch.backends.mps.is_available = lambda: mps
    monkeypatch.setitem(sys.modules, "torch", torch)


@pytest.mark.parametrize(("cuda", "mps", "expected"), [(True, False, "cuda"), (False, True, "mps")])
def test_require_accelerator_returns_detected_gpu(
    monkeypatch: pytest.MonkeyPatch, cuda: bool, mps: bool, expected: str
) -> None:
    """Verify a detected GPU backend is selected for the conversion.

    Args:
        monkeypatch: Pytest fixture replacing ``torch``.
        cuda: Fake CUDA availability.
        mps: Fake MPS availability.
        expected: Expected Docling device name.

    Returns:
        None. The assertion compares the device.
    """
    fake_torch(monkeypatch, cuda=cuda, mps=mps)

    assert require_accelerator(allow_cpu=False) == expected


@pytest.mark.parametrize(
    ("capability", "arch_list", "supported"),
    [
        ((5, 0), ("sm_50", "sm_60", "sm_90"), True),
        ((5, 2), ("sm_50", "sm_60"), True),
        ((5, 0), ("sm_75", "sm_80", "sm_90"), False),
        ((5, 0), ("sm_52",), False),
        ((9, 0), ("sm_80", "compute_80"), True),
        ((7, 5), ("sm_80", "compute_80"), False),
        ((12, 0), ("sm_100", "sm_120"), True),
    ],
)
def test_cuda_architecture_check(
    monkeypatch: pytest.MonkeyPatch,
    capability: tuple[int, int],
    arch_list: tuple[str, ...],
    supported: bool,
) -> None:
    """Verify a CUDA GPU only counts when the PyTorch build has kernels for it (R-160).

    Binary kernels run on the same major architecture with an equal or
    higher minor version; PTX (``compute_XY``) also serves newer GPUs.

    Args:
        monkeypatch: Pytest fixture replacing ``torch``.
        capability: Compute capability of the fake GPU.
        arch_list: Architectures of the fake PyTorch build.
        supported: Whether the GPU is expected to be usable.

    Returns:
        None. The assertion checks the detected device.
    """
    fake_torch(monkeypatch, cuda=True, capability=capability, arch_list=arch_list)

    assert available_accelerator() == ("cuda" if supported else None)


def test_unsupported_gpu_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a GPU without kernels in the PyTorch build gets a precise message.

    Args:
        monkeypatch: Pytest fixture replacing ``torch``.

    Returns:
        None. Assertions inspect the error message.
    """
    fake_torch(monkeypatch, cuda=True, capability=(5, 0), arch_list=("sm_75", "sm_80"))

    with pytest.raises(FlashcardError) as error:
        require_accelerator(allow_cpu=False)

    message = str(error.value)
    assert "Quadro K1200" in message
    assert "sm_50" in message
    assert "sm_75, sm_80" in message
    assert "--pdf-mode local" in message


def test_require_accelerator_without_gpu_points_to_alternatives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify a missing GPU aborts with native/local alternatives unless CPU is allowed.

    Args:
        monkeypatch: Pytest fixture replacing ``torch``.

    Returns:
        None. Assertions inspect the error and the explicit CPU override.
    """
    fake_torch(monkeypatch, cuda=False)

    with pytest.raises(FlashcardError) as error:
        require_accelerator(allow_cpu=False)

    message = str(error.value)
    assert "--pdf-mode native" in message
    assert "--pdf-mode local" in message
    assert "--allow-cpu" in message
    assert require_accelerator(allow_cpu=True) == "cpu"


def test_convert_pdf_checks_the_gpu_before_any_download(
    storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify the core refuses CPU-only conversion before models are loaded.

    Args:
        storage: Configured temporary model storage.
        monkeypatch: Pytest fixture replacing ``torch`` and the downloader.

    Returns:
        None. The assertion expects the GPU error and no download.
    """
    fake_torch(monkeypatch, cuda=False)
    monkeypatch.setattr(docling_pdf, "require_docling", lambda: None)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        """Fail if models would be downloaded.

        Args:
            *args: Ignored positional arguments.
            **kwargs: Ignored keyword arguments.

        Returns:
            Never returns.

        Raises:
            AssertionError: Always.
        """
        raise AssertionError("no download without GPU")

    monkeypatch.setattr(docling_pdf, "ensure_conversion_models", forbidden)

    with pytest.raises(FlashcardError, match="GPU"):
        convert_pdf(
            Path("skript.pdf"),
            ConversionOptions(),
            storage,
            describer=None,
            announce=lambda message: None,
        )


class FakeEnrichment:
    """Stand in for a Docling enrichment model.

    Attributes:
        progress_step: Docling's stable step identifier.
        elements_batch_size: Number of elements per model call.
    """

    def __init__(self, step: str) -> None:
        """Create a fake model with Docling's default batch size.

        Args:
            step: Value of ``progress_step``, e.g. ``code_formula``.
        """
        self.progress_step = step
        self.elements_batch_size = 5


class FakeConverter:
    """Stand in for Docling's ``DocumentConverter`` with one PDF pipeline.

    Attributes:
        models: Enrichment models of the pipeline.
        initialized: Formats passed to ``initialize_pipeline``.
        initialized_pipelines: Pipelines keyed like Docling's cache.
    """

    def __init__(self, *steps: str) -> None:
        """Create the converter with enrichment models for the given steps.

        Args:
            *steps: ``progress_step`` values of the pipeline's models.
        """
        self.models = [FakeEnrichment(step) for step in steps]
        self.initialized: list[object] = []
        self.initialized_pipelines = {"pdf": SimpleNamespace(enrichment_pipe=self.models)}

    def initialize_pipeline(self, input_format: object) -> None:
        """Record the request to build the pipeline.

        Args:
            input_format: Docling input format.
        """
        self.initialized.append(input_format)


def test_formula_batch_size_is_applied_to_the_formula_model() -> None:
    """Verify only the formula model gets the configured batch size (R-159).

    Returns:
        None. Assertions compare batch sizes of both fake models.
    """
    converter = FakeConverter("picture_classification", "code_formula")

    limit_formula_batch(converter, ConversionOptions(formula_batch_size=1), "pdf")

    assert [model.elements_batch_size for model in converter.models] == [5, 1]
    assert converter.initialized == ["pdf"]


def test_formula_batch_size_is_ignored_without_formulas() -> None:
    """Verify nothing is built when formulas are off or no size is set.

    Returns:
        None. The assertion checks that no pipeline was initialized.
    """
    converter = FakeConverter("code_formula")

    limit_formula_batch(converter, ConversionOptions(formulas=False, formula_batch_size=1), "pdf")
    limit_formula_batch(converter, ConversionOptions(), "pdf")

    assert converter.initialized == []
    assert converter.models[0].elements_batch_size == 5


def test_missing_formula_model_is_reported() -> None:
    """Verify a Docling version without the expected model fails loudly.

    Returns:
        None. The assertion checks the error message.
    """
    with pytest.raises(FlashcardError, match="formula_batch_size"):
        limit_formula_batch(
            FakeConverter("picture_classification"), ConversionOptions(formula_batch_size=2), "pdf"
        )
