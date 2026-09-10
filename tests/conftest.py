"""Shared pytest fixtures for the Felicity Solar Local test suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Make custom_components discoverable in every test."""


@pytest.fixture
def sample_response() -> dict[str, Any]:
    """Raw device JSON captured live from a Felicity Solar FLB48314TG1-H."""
    path = Path(__file__).parent / "fixtures" / "sample_response.json"
    return json.loads(path.read_text())


@pytest.fixture
def fla24100_response() -> dict[str, Any]:
    """Raw device JSON captured live from a Felicity Solar FLA24100."""
    path = Path(__file__).parent / "fixtures" / "fla24100_response.json"
    return json.loads(path.read_text())


@pytest.fixture
def fla48300_response() -> dict[str, Any]:
    """Raw device JSON reported by a Felicity Solar FLA48300 (see issue #42)."""
    path = Path(__file__).parent / "fixtures" / "fla48300_response.json"
    return json.loads(path.read_text())
