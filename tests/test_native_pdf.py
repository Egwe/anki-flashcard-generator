"""Test verified native PDF generation without real uploads or credentials."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from anki_flashcards.ai import AISettings
from anki_flashcards.errors import FlashcardError
from anki_flashcards.models import CardBatch
from anki_flashcards.native_pdf import (
    OpenAINativePDFAdapter,
    generate_native_cards,
    native_openai_model,
)


class FakeOpenAIClient:
    """Record native PDF calls and provide controlled SDK-shaped responses."""

    def __init__(self, response: Any = None, failure: Exception | None = None) -> None:
        """Initialize file and response doubles for one test scenario.

        Args:
            response: Optional response returned by responses.parse.
            failure: Optional error raised by responses.parse.

        Returns:
            None. Recording structures are initialized without network access.
        """
        self.files = SimpleNamespace(
            create=self._create_file,
            delete=self._delete_file,
        )
        self.responses = SimpleNamespace(parse=self._parse_response)
        self.response = response
        self.failure = failure
        self.uploads: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    def _create_file(self, **kwargs: Any) -> SimpleNamespace:
        """Record a PDF upload and return a deterministic provider file ID.

        Args:
            **kwargs: File object and purpose supplied by the adapter.

        Returns:
            An uploaded-file namespace with a test identifier.
        """
        self.uploads.append(kwargs)
        return SimpleNamespace(id="file-test-123")

    def _parse_response(self, **kwargs: Any) -> Any:
        """Record a structured Responses request and return its configured result.

        Args:
            **kwargs: Responses API options supplied by the adapter.

        Returns:
            The configured response namespace.

        Raises:
            Exception: The configured request failure, when present.
        """
        self.requests.append(kwargs)
        if self.failure:
            raise self.failure
        return self.response

    def _delete_file(self, file_id: str) -> SimpleNamespace:
        """Record uploaded-file deletion for lifecycle assertions.

        Args:
            file_id: Provider identifier of the uploaded PDF.

        Returns:
            A deletion result namespace.
        """
        self.deleted.append(file_id)
        return SimpleNamespace(id=file_id, deleted=True)


def test_native_model_allowlist_is_conservative() -> None:
    """Verify only documented OpenAI vision models are selected for upload.

    Returns:
        None. Assertions reject other providers and unverified model names.
    """
    assert native_openai_model("openai/gpt-4o") == "gpt-4o"
    assert native_openai_model("openai/gpt-4o-2024-08-06") == "gpt-4o-2024-08-06"
    assert native_openai_model("openai/gpt-4o-mini") == "gpt-4o-mini"
    assert native_openai_model("openai/gpt-4.1") == "gpt-4.1"
    assert native_openai_model("openai/gpt-4o-mini-audio-preview") is None
    assert native_openai_model("anthropic/claude-sonnet-4-5") is None


def test_documented_gpt_4o_mini_snapshot_is_allowed() -> None:
    """Verify dated gpt-4o-mini snapshots match the documented base model.

    Returns:
        None. Assertions accept the dated snapshot but keep audio variants out.
    """
    assert native_openai_model("openai/gpt-4o-mini-2024-07-18") == "gpt-4o-mini-2024-07-18"
    assert native_openai_model("gpt-4o-mini-2024-07-18") == "gpt-4o-mini-2024-07-18"
    assert native_openai_model("openai/gpt-4o-mini-audio-preview-2024-12-17") is None
    assert native_openai_model("openai/gpt-4o-mini-tts") is None


class StrictParseClient(FakeOpenAIClient):
    """Expose an explicit responses.parse signature like the official SDK."""

    def __init__(self, response: Any = None) -> None:
        """Replace the permissive parse double with a keyword-checked one.

        Args:
            response: Response returned by the strict parse double.

        Returns:
            None. The inherited recording structures remain available.
        """
        super().__init__(response=response)
        self.responses = SimpleNamespace(parse=self._strict_parse)

    def _strict_parse(
        self,
        *,
        model: str,
        instructions: str,
        input: list[dict[str, Any]],
        text_format: type,
        store: bool,
        timeout: int,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
    ) -> Any:
        """Record accepted Responses options and return the configured result.

        Args:
            model: Bare OpenAI model identifier.
            instructions: System instructions.
            input: Uploaded-file and prompt content.
            text_format: Pydantic response schema.
            store: Provider-side response storage flag.
            timeout: Request timeout in seconds.
            temperature: Optional sampling temperature.
            max_output_tokens: Optional output-token limit.

        Returns:
            The configured response namespace.
        """
        request = {"model": model, "store": store, "max_output_tokens": max_output_tokens}
        self.requests.append(request)
        return self.response


def _native_pdf(tmp_path: Path) -> Path:
    """Create a small local PDF placeholder for adapter tests.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        Path to a file with a PDF suffix and minimal content.
    """
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF-test-content")
    return path


@pytest.mark.parametrize(
    ("options", "match"),
    [
        ({"max_tokens": 8192}, r"max_tokens.*max_output_tokens"),
        ({"max_completion_tokens": 100}, r"max_completion_tokens.*max_output_tokens"),
        ({"frequency_penalty": 0.5}, r"frequency_penalty"),
        ({"store": True}, r"store"),
    ],
)
def test_unsupported_native_options_are_rejected_before_upload(
    tmp_path: Path, monkeypatch, options: dict[str, Any], match: str
) -> None:
    """Verify invalid Responses options fail clearly before the PDF is uploaded.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing the SDK client factory.
        options: Profile options that the Responses request cannot accept.
        match: Expected error message pattern.

    Returns:
        None. Assertions inspect the error and the absence of uploads.
    """
    client = StrictParseClient()
    monkeypatch.setattr("anki_flashcards.native_pdf._openai_client", lambda settings: client)

    with pytest.raises(FlashcardError, match=match):
        generate_native_cards(
            _native_pdf(tmp_path),
            AISettings(model="openai/gpt-4o-mini", api_key="test", options=options),
        )

    assert client.uploads == []
    assert client.requests == []


def test_supported_native_options_reach_responses_request(tmp_path: Path, monkeypatch) -> None:
    """Verify documented Responses options are passed through unchanged.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing the SDK client factory.

    Returns:
        None. Assertions inspect the forwarded output-token limit and cleanup.
    """
    batch = CardBatch.model_validate({"cards": [{"front": "Frage?", "back": "Antwort"}]})
    client = StrictParseClient(response=SimpleNamespace(output_parsed=batch))
    monkeypatch.setattr("anki_flashcards.native_pdf._openai_client", lambda settings: client)

    cards = generate_native_cards(
        _native_pdf(tmp_path),
        AISettings(
            model="openai/gpt-4o-mini-2024-07-18",
            api_key="test",
            options={"temperature": 0.2, "max_output_tokens": 8192},
        ),
    )

    assert len(cards) == 1
    assert client.requests[0]["max_output_tokens"] == 8192
    assert client.deleted == ["file-test-123"]


def test_example_native_profile_options_match_official_sdk() -> None:
    """Verify the shipped native profile is accepted by the real SDK signature.

    Returns:
        None. The official OpenAI client is constructed without network access.
    """
    from openai import OpenAI

    from anki_flashcards.config import load_config
    from anki_flashcards.native_pdf import _validate_openai_options

    config = load_config(Path(__file__).parents[1] / "config.example.yaml")
    options = config.models["openai-native-pdf"].options

    _validate_openai_options(OpenAI(api_key="test"), options)


def test_openai_native_upload_parse_validate_and_delete(tmp_path: Path, monkeypatch) -> None:
    """Verify native PDF flow skips extraction and cleans up its upload.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing the SDK and local PDF reader.

    Returns:
        None. Assertions inspect upload, structured response, cards, and deletion.
    """
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF-test-content")
    batch = CardBatch.model_validate(
        {
            "cards": [
                {"front": "Frage?", "back": "Antwort", "tags": ["Test"]},
                {"front": " frage? ", "back": "Duplikat"},
            ]
        }
    )
    client = FakeOpenAIClient(response=SimpleNamespace(output_parsed=batch))
    monkeypatch.setattr("anki_flashcards.native_pdf._openai_client", lambda settings: client)

    def fail_pdf_read(path: Path) -> None:
        """Fail if native processing incorrectly attempts local PDF extraction.

        Args:
            path: PDF path that must not be parsed locally.

        Returns:
            Never returns normally.

        Raises:
            AssertionError: Always, because native mode must skip extraction.
        """
        raise AssertionError("Local PDF extraction must not run in native mode")

    monkeypatch.setattr("anki_flashcards.documents._read_pdf", fail_pdf_read)

    cards = generate_native_cards(
        path,
        AISettings(model="openai/gpt-4o", api_key="test-key"),
        limit=10,
        language="Deutsch",
        instructions="Kurze Antworten",
    )

    assert len(cards) == 1
    assert cards[0].front == "Frage?"
    assert client.uploads[0]["purpose"] == "user_data"
    assert client.requests[0]["model"] == "gpt-4o"
    assert client.requests[0]["text_format"] == CardBatch
    assert client.requests[0]["store"] is False
    assert client.requests[0]["input"][0]["content"][0]["file_id"] == "file-test-123"
    assert client.deleted == ["file-test-123"]


def test_unsupported_model_never_uploads(tmp_path: Path) -> None:
    """Verify unsupported models are rejected before a client can upload.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. The assertion requires a model-capability error.
    """
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF")

    with pytest.raises(FlashcardError, match="No verified native PDF adapter"):
        generate_native_cards(path, AISettings(model="ollama/llama3.2"))


def test_non_pdf_never_uploads(tmp_path: Path) -> None:
    """Verify native document mode currently rejects non-PDF input.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. The assertion requires a supported-format error.
    """
    path = tmp_path / "source.txt"
    path.write_text("Text", encoding="utf-8")

    with pytest.raises(FlashcardError, match="PDF files only"):
        generate_native_cards(path, AISettings(model="openai/gpt-4o"))


def test_file_at_openai_limit_is_rejected_before_upload(tmp_path: Path, monkeypatch) -> None:
    """Verify a 50 MiB file is rejected without any upload request.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture used to report the boundary file size.

    Returns:
        None. The assertion requires a size-limit error.
    """
    path = tmp_path / "large.pdf"
    path.write_bytes(b"%PDF")
    original_stat = Path.stat

    def boundary_stat(file_path: Path, *args: Any, **kwargs: Any) -> Any:
        """Report the exact 50 MiB boundary only for the test PDF.

        Args:
            file_path: Path being inspected.
            *args: Additional positional stat arguments.
            **kwargs: Additional stat keyword arguments.

        Returns:
            Actual stat data for other paths or a boundary-sized result for
            the test PDF.
        """
        result = original_stat(file_path, *args, **kwargs)
        if file_path != path:
            return result
        values = list(result)
        values[6] = 50 * 1024 * 1024
        return type(result)(values)

    monkeypatch.setattr(Path, "stat", boundary_stat)

    with pytest.raises(FlashcardError, match="smaller than 50 MiB"):
        generate_native_cards(path, AISettings(model="openai/gpt-4o"))


def test_request_failure_still_deletes_upload(tmp_path: Path, monkeypatch) -> None:
    """Verify cleanup runs even when the native generation request fails.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing the official SDK client.

    Returns:
        None. Assertions require a request error and upload deletion.
    """
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF")
    client = FakeOpenAIClient(failure=RuntimeError("simulated request failure"))
    monkeypatch.setattr("anki_flashcards.native_pdf._openai_client", lambda settings: client)

    with pytest.raises(FlashcardError, match="request failed"):
        OpenAINativePDFAdapter().generate(
            path,
            AISettings(model="openai/gpt-4o", api_key="test"),
            limit=5,
            language="Deutsch",
            instructions="",
        )

    assert client.deleted == ["file-test-123"]


def test_missing_parsed_batch_is_an_error(tmp_path: Path, monkeypatch) -> None:
    """Verify a missing parsed batch is not accepted as successful generation.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing the official SDK client.

    Returns:
        None. The assertion requires a parsed-response error.
    """
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF")
    client = FakeOpenAIClient(response=SimpleNamespace(output_parsed=None))
    monkeypatch.setattr("anki_flashcards.native_pdf._openai_client", lambda settings: client)

    with pytest.raises(FlashcardError, match="no valid card batch"):
        generate_native_cards(path, AISettings(model="openai/gpt-4o", api_key="test"))


def test_delete_failure_warns_with_file_id(tmp_path: Path, monkeypatch) -> None:
    """Verify deletion failures produce a visible manual-cleanup warning.

    Args:
        tmp_path: Pytest-provided isolated directory.
        monkeypatch: Pytest fixture replacing the official SDK client.

    Returns:
        None. Assertions inspect generated cards and deletion warning.
    """
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF")
    batch = CardBatch.model_validate({"cards": [{"front": "F?", "back": "A"}]})
    client = FakeOpenAIClient(response=SimpleNamespace(output_parsed=batch))

    def fail_delete(file_id: str) -> None:
        """Simulate a provider cleanup failure after successful generation.

        Args:
            file_id: Uploaded file identifier that could not be deleted.

        Returns:
            Never returns normally.

        Raises:
            RuntimeError: Deliberate cleanup failure.
        """
        raise RuntimeError("delete failed")

    client.files.delete = fail_delete
    monkeypatch.setattr("anki_flashcards.native_pdf._openai_client", lambda settings: client)

    with pytest.warns(RuntimeWarning, match="file-test-123"):
        cards = generate_native_cards(path, AISettings(model="openai/gpt-4o", api_key="test"))

    assert len(cards) == 1


def test_real_openai_sdk_against_local_native_server(tmp_path: Path) -> None:
    """Verify the official SDK uploads, parses, and deletes via a local server.

    Args:
        tmp_path: Pytest-provided isolated directory.

    Returns:
        None. Assertions inspect generated cards and all local HTTP calls.
    """
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    calls: list[tuple[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        """Serve a bounded local OpenAI-compatible native PDF test endpoint."""

        def do_POST(self) -> None:
            """Handle local file upload and structured Responses requests.

            Returns:
                None. A deterministic JSON HTTP response is written.
            """
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            calls.append(("POST", self.path))
            if self.path == "/v1/files":
                payload = {
                    "id": "file-local-test",
                    "object": "file",
                    "bytes": len(body),
                    "created_at": 1,
                    "filename": "source.pdf",
                    "purpose": "user_data",
                }
                self._send_json(payload)
                return
            if self.path == "/v1/responses":
                payload = {
                    "id": "resp-local-test",
                    "object": "response",
                    "created_at": 1,
                    "status": "completed",
                    "model": "gpt-4o",
                    "output": [
                        {
                            "id": "msg-local-test",
                            "type": "message",
                            "status": "completed",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(
                                        {"cards": [{"front": "SDK?", "back": "Funktioniert"}]}
                                    ),
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                }
                self._send_json(payload)
                return
            self.send_error(404)

        def do_DELETE(self) -> None:
            """Handle deletion of the local uploaded-file test resource.

            Returns:
                None. A successful deletion JSON response is written.
            """
            calls.append(("DELETE", self.path))
            self._send_json({"id": "file-local-test", "object": "file", "deleted": True})

        def _send_json(self, payload: dict[str, Any]) -> None:
            """Write one JSON response to the local test client.

            Args:
                payload: JSON-serializable provider response.

            Returns:
                None. HTTP status and content headers are set.
            """
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            """Suppress local HTTP server request logging.

            Args:
                *args: Unused logging arguments supplied by BaseHTTPRequestHandler.

            Returns:
                None. No output is written.
            """

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = tmp_path / "source.pdf"
    path.write_bytes(b"%PDF-local-sdk-test")
    try:
        cards = generate_native_cards(
            path,
            AISettings(
                model="openai/gpt-4o",
                api_key="local-test-only",
                api_base=f"http://127.0.0.1:{server.server_port}/v1",
                timeout=10,
            ),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert [(card.front, card.back) for card in cards] == [("SDK?", "Funktioniert")]
    assert ("POST", "/v1/files") in calls
    assert ("POST", "/v1/responses") in calls
    assert ("DELETE", "/v1/files/file-local-test") in calls
