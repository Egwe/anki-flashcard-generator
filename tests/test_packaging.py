"""Tests for the declared runtime dependencies of the package."""

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def declared_dependencies() -> list[str]:
    """Read the runtime dependencies from ``pyproject.toml``.

    Returns:
        Requirement strings of ``project.dependencies``.
    """
    with PYPROJECT.open("rb") as file:
        return tomllib.load(file)["project"]["dependencies"]


def test_tenacity_is_declared() -> None:
    """Verify tenacity is a declared dependency.

    ``ai.py`` asks LiteLLM for ``num_retries=2``; LiteLLM then imports
    tenacity but does not declare it. In a fresh environment every AI
    request failed with "tenacity import failed" (found by Anki Studio).

    Returns:
        None. The assertion checks the requirement list.
    """
    assert any(requirement.startswith("tenacity") for requirement in declared_dependencies())
