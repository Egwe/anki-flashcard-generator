"""Convert PDFs locally with Docling into page Markdown, figures, and statistics.

This is the only module that imports Docling. Imports happen inside functions
so the base installation works without the optional ``pdf`` extra.
"""

import importlib.util
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from anki_flashcards.ai import AISettings
from anki_flashcards.config import PictureBackend
from anki_flashcards.errors import FlashcardError
from anki_flashcards.model_storage import (
    ModelStorage,
    downloaded_components,
    record_components,
)
from anki_flashcards.pictures import (
    LocalPictureDescriber,
    PictureDescriber,
    ProfilePictureDescriber,
)
from anki_flashcards.structured_pdf import (
    ConversionOptions,
    ExtractedPage,
    ExtractedPdf,
    PictureInfo,
    ProgressCallback,
    StructuredPdf,
    render_document,
)

INSTALL_HINT = (
    "The structured PDF mode needs the optional Docling extra. Install it into the "
    "project environment, for example:\n"
    "  .venv/bin/python -m pip install --no-cache-dir "
    "--index-url https://download.pytorch.org/whl/cpu torch torchvision\n"
    "  .venv/bin/python -m pip install --no-cache-dir -e '.[pdf]'"
)
PICTURE_TOKEN = "⟦picture:{index}⟧"
IMAGES_SCALE = 2.0
BASE_COMPONENTS = frozenset({"layout", "tableformer", "picture_classifier", "rapidocr"})
FORMULA_COMPONENT = "code_formula"
PICTURE_MODEL_IGNORE = ["onnx/*", "*.onnx", "*.gguf", "*.mlpackage/*", "mlx/*"]

Announce = Callable[[str], None]
Extractor = Callable[
    [Path, ConversionOptions, ModelStorage, str, ProgressCallback | None], ExtractedPdf
]
NO_GPU_HINT = (
    "The structured PDF mode needs a GPU accelerator usable by PyTorch (NVIDIA CUDA, "
    "AMD ROCm, Apple MPS, or Intel XPU); none was found. On a CPU it takes very long "
    "(measured: over 50 minutes for 15 lecture pages with formulas). Alternatives: "
    "--pdf-mode native lets a verified provider model read the original PDF, "
    "--pdf-mode local reads only the embedded text layer. Use --allow-cpu to run on "
    "the CPU anyway."
)


def convert_pdf(
    path: Path,
    options: ConversionOptions,
    storage: ModelStorage,
    *,
    describer: PictureDescriber | None,
    announce: Announce,
    progress: ProgressCallback | None = None,
    device: str | None = None,
    extractor: Extractor | None = None,
) -> StructuredPdf:
    """Convert a local PDF into marked Markdown text without uploading it.

    Args:
        path: Local ``.pdf`` file.
        options: OCR, formula, description language, and gap handling.
        storage: Project-local models folder for all downloads and caches.
        describer: Picture model backend, or None to keep figures undescribed.
        announce: Callback receiving download notices.
        progress: Optional callback receiving label, completed, and total.
        device: Accelerator from ``require_accelerator``; detected when None.
        extractor: Converter replacing Docling in tests; defaults to Docling.

    Returns:
        The marked document text and conversion statistics.

    Raises:
        FlashcardError: If the input is not a PDF, no GPU is available without
            ``allow_cpu``, Docling or its models are unavailable, conversion
            fails, or elements are unreadable without ``allow_unreadable``.
    """
    validate_pdf_input(path)
    if extractor is None:
        require_docling()
        device = device or require_accelerator(options.allow_cpu)
        ensure_conversion_models(storage, formulas=options.formulas, announce=announce)
        extractor = extract_pdf
    extracted = extractor(path, options, storage, device or "cpu", progress)
    return render_document(path, extracted, options, describer, progress)


def validate_pdf_input(path: Path) -> None:
    """Reject inputs that the structured PDF mode cannot process.

    Args:
        path: Requested input file.

    Returns:
        None for a ``.pdf`` file.

    Raises:
        FlashcardError: For every other format, with a hint for Markdown or
            text files such as a previously saved converted text.
    """
    if path.suffix.casefold() == ".pdf":
        return
    raise FlashcardError(
        f"The structured PDF mode only accepts .pdf files: {path}. "
        "Use --pdf-mode local for other formats, including saved converted text."
    )


def available_accelerator() -> str | None:
    """Detect a GPU accelerator that PyTorch can use.

    Returns:
        ``cuda`` (also for AMD ROCm builds), ``xpu``, ``mps``, or None when
        only the CPU is available or PyTorch is missing.
    """
    try:
        import torch
    except ImportError:
        return None
    checks = (
        ("cuda", getattr(torch, "cuda", None)),
        ("xpu", getattr(torch, "xpu", None)),
        ("mps", getattr(getattr(torch, "backends", None), "mps", None)),
    )
    for name, backend in checks:
        if backend is not None and backend.is_available():
            return name
    return None


def require_accelerator(allow_cpu: bool) -> str:
    """Choose the conversion device or refuse CPU-only conversion.

    Args:
        allow_cpu: Whether the user explicitly accepted the slow CPU mode.

    Returns:
        The detected GPU device name, or ``cpu`` when explicitly allowed.

    Raises:
        FlashcardError: If no GPU is available and CPU use was not allowed;
            the message names ``--pdf-mode native`` and ``--pdf-mode local``.
    """
    device = available_accelerator()
    if device is not None:
        return device
    if allow_cpu:
        return "cpu"
    raise FlashcardError(NO_GPU_HINT)


def create_describer(
    backend: PictureBackend,
    storage: ModelStorage,
    *,
    picture_model: str,
    picture_ai: AISettings | None,
    announce: Announce,
    device: str = "cpu",
) -> PictureDescriber | None:
    """Create the configured picture-description backend.

    Args:
        backend: ``local``, ``profile``, or ``none``.
        storage: Models folder for the local picture model.
        picture_model: Hugging Face identifier used by the local backend.
        picture_ai: Provider settings used by the profile backend.
        announce: Callback receiving download and transfer notices.
        device: PyTorch device for the local picture model.

    Returns:
        A describer, or None for the ``none`` backend.

    Raises:
        FlashcardError: If the profile backend has no settings or the local
            model cannot be downloaded.
    """
    if backend == PictureBackend.NONE:
        return None
    if backend == PictureBackend.PROFILE:
        if picture_ai is None:
            raise FlashcardError("The picture backend 'profile' has no resolved model profile.")
        endpoint = picture_ai.api_base or "provider default endpoint"
        announce(
            f"Bildmodell über Profil: Bildausschnitte werden an {picture_ai.model} "
            f"({endpoint}) gesendet; die PDF selbst wird nicht übertragen."
        )
        return ProfilePictureDescriber(picture_ai)
    model_dir = ensure_picture_model(storage, picture_model, announce)
    return LocalPictureDescriber(model_dir, device=device)


def require_docling() -> None:
    """Fail early with installation instructions when Docling is missing.

    Returns:
        None when the ``docling`` package can be imported.

    Raises:
        FlashcardError: If the optional ``pdf`` extra is not installed.
    """
    if importlib.util.find_spec("docling") is None:
        raise FlashcardError(INSTALL_HINT)


def ensure_conversion_models(storage: ModelStorage, *, formulas: bool, announce: Announce) -> None:
    """Download missing Docling models into the project models folder once.

    Args:
        storage: Configured project-local models folder.
        formulas: Whether the formula model is required.
        announce: Callback receiving a message before a download starts.

    Returns:
        None. Afterwards the required components are listed in the manifest
        and later runs work offline.

    Raises:
        FlashcardError: If Docling is missing or the download fails.
    """
    required = set(BASE_COMPONENTS) | ({FORMULA_COMPONENT} if formulas else set())
    missing = required - downloaded_components(storage)
    if not missing:
        return
    require_docling()
    announce(f"Lade Docling-Modelle ({', '.join(sorted(missing))}) nach {storage.docling} ...")
    from docling.utils.model_downloader import download_models

    try:
        download_models(
            output_dir=storage.docling,
            with_layout="layout" in missing,
            with_tableformer="tableformer" in missing,
            with_code_formula=FORMULA_COMPONENT in missing,
            with_picture_classifier="picture_classifier" in missing,
            with_rapidocr="rapidocr" in missing,
            with_easyocr=False,
        )
    except (OSError, ValueError, RuntimeError) as error:
        raise FlashcardError(f"Could not download Docling models: {error}") from error
    record_components(storage, missing)


def ensure_picture_model(storage: ModelStorage, repo_id: str, announce: Announce) -> Path:
    """Download a local picture model from Hugging Face into the models folder once.

    Args:
        storage: Configured project-local models folder.
        repo_id: Hugging Face model identifier, for example
            ``HuggingFaceTB/SmolVLM-256M-Instruct``.
        announce: Callback receiving a message before a download starts.

    Returns:
        The local model folder.

    Raises:
        FlashcardError: If the download fails.
    """
    component = f"picture:{repo_id}"
    target = storage.picture_model(repo_id)
    if component in downloaded_components(storage):
        return target
    announce(f"Lade Bildmodell {repo_id} nach {target} ...")
    from huggingface_hub import snapshot_download

    try:
        snapshot_download(repo_id=repo_id, local_dir=target, ignore_patterns=PICTURE_MODEL_IGNORE)
    except (OSError, ValueError) as error:
        raise FlashcardError(f"Could not download picture model {repo_id}: {error}") from error
    record_components(storage, {component})
    return target


def extract_pdf(
    path: Path,
    options: ConversionOptions,
    storage: ModelStorage,
    device: str = "cpu",
    progress: ProgressCallback | None = None,
) -> ExtractedPdf:
    """Convert a PDF with Docling into page Markdown with figure tokens.

    Args:
        path: Local PDF file.
        options: OCR, formula, and language settings.
        storage: Models folder containing the downloaded Docling artifacts.
        device: Docling accelerator device such as ``cuda`` or ``cpu``.
        progress: Optional callback receiving label, completed, and total.

    Returns:
        Page Markdown, figures with crops and context, and statistics.

    Raises:
        FlashcardError: If Docling is missing or cannot convert the file.
    """
    require_docling()
    converter = _converter(options, storage, device)
    try:
        result = converter.convert(
            path, raises_on_error=False, progress_callback=_progress_adapter(progress)
        )
    except (OSError, ValueError, RuntimeError) as error:
        raise FlashcardError(f"Docling could not convert {path}: {error}") from error
    if result.document is None or not result.document.pages:
        raise FlashcardError(f"Docling could not convert {path}: {result.status}")
    return _extracted(result)


def _converter(options: ConversionOptions, storage: ModelStorage, device: str) -> Any:
    """Build a Docling converter that only uses local models from ``storage``.

    Args:
        options: OCR and formula settings.
        storage: Models folder used as Docling artifacts path.
        device: Accelerator device for Docling's models.

    Returns:
        A configured ``DocumentConverter`` for PDF input.
    """
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.datamodel.settings import settings
    from docling.document_converter import DocumentConverter, PdfFormatOption

    settings.cache_dir = storage.root / "docling-cache"
    ocr = RapidOcrOptions(
        lang=[f"iso:{language}" for language in options.ocr_languages[:1]],
        force_full_page_ocr=options.force_ocr,
        backend="torch",
    )
    pipeline = PdfPipelineOptions(
        artifacts_path=storage.docling,
        do_ocr=True,
        ocr_options=ocr,
        do_table_structure=True,
        do_formula_enrichment=options.formulas,
        do_picture_classification=True,
        generate_picture_images=True,
        images_scale=IMAGES_SCALE,
        enable_remote_services=False,
    )
    pipeline.accelerator_options = AcceleratorOptions(
        num_threads=os.cpu_count() or 4, device=device
    )
    pdf_option = PdfFormatOption(pipeline_options=pipeline)
    return DocumentConverter(format_options={InputFormat.PDF: pdf_option})


def _progress_adapter(progress: ProgressCallback | None) -> Callable[[Any], None] | None:
    """Translate Docling page and enrichment events into the shared callback.

    Args:
        progress: Callback receiving label, completed, and total, or None.

    Returns:
        A Docling progress callback, or None when no progress is wanted.
    """
    if progress is None:
        return None

    def forward(event: Any) -> None:
        """Forward one Docling progress event with countable steps.

        Args:
            event: Docling progress event.

        Returns:
            None. Events without step counts are ignored.
        """
        kind = getattr(event.kind, "value", str(event.kind))
        if kind == "page_completed":
            progress("PDF-Seiten analysieren", event.completed_pages, event.total_pages)
        if kind == "enrichment_progress":
            progress(f"Docling: {event.label}", event.completed_items, event.total_items)

    return forward


def _extracted(result: Any) -> ExtractedPdf:
    """Map a Docling conversion result to the converter-neutral structure.

    Args:
        result: Docling ``ConversionResult`` with a document.

    Returns:
        Page Markdown with figure tokens, figures, and statistics.
    """
    document = result.document
    pictures = _pictures(document)
    tokens = {picture_ref: picture.token for picture_ref, picture in pictures.items()}
    page_count = max([result.input.page_count, *document.pages])
    pages = tuple(
        ExtractedPage(number, _page_markdown(document, number, tokens))
        for number in range(1, page_count + 1)
    )
    return ExtractedPdf(
        pages=pages,
        pictures=tuple(pictures.values()),
        ocr_pages=_ocr_pages(result.pages),
        tables=len(document.tables),
        formulas=_decoded_formulas(document),
        failed_pages=_failed_pages(result),
    )


def _pictures(document: Any) -> dict[str, PictureInfo]:
    """Collect every figure with its crop, class, size, caption, and inner text.

    Args:
        document: Docling document.

    Returns:
        Figures keyed by their Docling reference, in document order.
    """
    pictures: dict[str, PictureInfo] = {}
    for index, item in enumerate(document.pictures):
        page = item.prov[0].page_no if item.prov else 0
        pictures[item.self_ref] = PictureInfo(
            token=PICTURE_TOKEN.format(index=index),
            page=page,
            kind=_picture_kind(item),
            area_ratio=_area_ratio(document, item),
            caption=item.caption_text(document).strip(),
            text=_inner_text(document, item),
            image=item.get_image(document),
            layout_key=_layout_key(item),
        )
    return pictures


def _picture_kind(item: Any) -> str | None:
    """Return the most likely figure class predicted by Docling.

    Args:
        item: Docling picture item.

    Returns:
        A class name such as ``line_chart``, or None without classification.
    """
    meta = getattr(item, "meta", None)
    classification = getattr(meta, "classification", None)
    if classification is None:
        return None
    return classification.get_main_prediction().class_name


def _layout_key(item: Any) -> str:
    """Describe a figure's position and size rounded to 5 points.

    Args:
        item: Docling picture item with provenance.

    Returns:
        A key like ``"12:4:30:9"``; empty without provenance.
    """
    if not item.prov:
        return ""
    box = item.prov[0].bbox
    return ":".join(str(round(value / 5)) for value in (box.l, box.t, box.r, box.b))


def _area_ratio(document: Any, item: Any) -> float:
    """Compute the share of the page covered by a figure.

    Args:
        document: Docling document with page sizes.
        item: Docling picture item with provenance.

    Returns:
        A value between 0 and 1; 1.0 when the size cannot be determined.
    """
    if not item.prov:
        return 1.0
    provenance = item.prov[0]
    page = document.pages.get(provenance.page_no)
    if page is None or not page.size.width or not page.size.height:
        return 1.0
    page_area = page.size.width * page.size.height
    return min(1.0, provenance.bbox.area() / page_area)


def _inner_text(document: Any, item: Any) -> str:
    """Join text recognized inside a figure.

    Args:
        document: Docling document.
        item: Docling picture item whose children hold inner text.

    Returns:
        Space-separated inner text, possibly empty.
    """
    texts = []
    for child, _level in document.iterate_items(root=item, traverse_pictures=True):
        text = getattr(child, "text", "")
        if child is not item and text:
            texts.append(text.strip())
    return " ".join(text for text in texts if text)


def _page_markdown(document: Any, page: int, tokens: dict[str, str]) -> str:
    """Serialize one page to Markdown with figure tokens instead of images.

    Args:
        document: Docling document.
        page: One-based page number.
        tokens: Figure token per Docling picture reference.

    Returns:
        Markdown of the page; empty when the page has no content.
    """
    from docling_core.transforms.serializer.markdown import (
        MarkdownDocSerializer,
        MarkdownParams,
    )

    params = MarkdownParams(
        pages={page},
        escape_html=False,
        escape_underscores=False,
        include_picture_classification=False,
    )
    serializer = MarkdownDocSerializer(
        doc=document, params=params, picture_serializer=_token_picture_serializer(tokens)
    )
    return serializer.serialize().text


def _token_picture_serializer(tokens: dict[str, str]) -> Any:
    """Create a picture serializer that writes figure tokens instead of images.

    Args:
        tokens: Figure token per Docling picture reference.

    Returns:
        A Docling ``MarkdownPictureSerializer`` subclass instance.
    """
    from docling_core.transforms.serializer.base import SerializationResult
    from docling_core.transforms.serializer.common import create_ser_result
    from docling_core.transforms.serializer.markdown import MarkdownPictureSerializer

    class TokenPictureSerializer(MarkdownPictureSerializer):
        """Replace the image part of a picture by its figure token."""

        def _serialize_image_part(
            self, item: Any, *args: Any, **kwargs: Any
        ) -> SerializationResult:
            """Return the figure token for a picture item.

            Args:
                item: Docling picture item.
                *args: Unused positional serializer arguments.
                **kwargs: Unused keyword serializer arguments.

            Returns:
                A serialization result containing only the token.
            """
            return create_ser_result(text=tokens.get(item.self_ref, ""), span_source=item)

    return TokenPictureSerializer()


def _ocr_pages(pages: list[Any]) -> tuple[int, ...]:
    """List pages containing text cells recognized by OCR.

    Docling discards ``parsed_page`` after the conversion, so the OCR flag is
    read from the cells of the assembled page elements.

    Args:
        pages: Docling page objects of the conversion result.

    Returns:
        Sorted one-based page numbers.
    """
    return tuple(sorted(page.page_no for page in pages if _has_ocr_cells(page)))


def _has_ocr_cells(page: Any) -> bool:
    """Tell whether any assembled element of a page contains OCR text cells.

    Args:
        page: Docling page object of the conversion result.

    Returns:
        True when at least one cell carries ``from_ocr``.
    """
    elements = page.assembled.elements if page.assembled else []
    clusters = [getattr(element, "cluster", None) for element in elements]
    cells = [cell for cluster in clusters if cluster for cell in cluster.cells]
    return any(getattr(cell, "from_ocr", False) for cell in cells)


def _decoded_formulas(document: Any) -> int:
    """Count formulas that Docling recognized as LaTeX.

    Args:
        document: Docling document.

    Returns:
        Number of formula items with non-empty text.
    """
    return sum(
        1
        for item in document.texts
        if getattr(item.label, "value", item.label) == "formula" and item.text.strip()
    )


def _failed_pages(result: Any) -> tuple[int, ...]:
    """List pages for which Docling reported a conversion error.

    Args:
        result: Docling conversion result.

    Returns:
        Sorted unique one-based page numbers.
    """
    return tuple(sorted({error.page_no for error in result.errors if error.page_no}))
