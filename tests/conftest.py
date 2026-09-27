"""Shared pytest fixtures for the Felicity Solar Local test suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Make custom_components discoverable in every test."""


BASIC_INFO_PATH = (
    "custom_components.felicity_solar_local.coordinator.FelicityLocalClient"
    ".async_get_basic_info"
)


@pytest.fixture
def basic_info_response() -> dict[str, Any]:
    """Raw ``get dev basice infor`` JSON captured live from a Felicity Solar FLB48314TG1-H."""
    path = Path(__file__).parent / "fixtures" / "basic_info_response.json"
    return json.loads(path.read_text())


@pytest.fixture(autouse=True)
def mock_basic_info(
    request: pytest.FixtureRequest, basic_info_response: dict[str, Any]
) -> Any:
    """Answer the coordinator's one-off firmware query so no test hits the network.

    test_api.py exercises the real client against a fake server, so it's left alone there.
    """
    if request.module.__name__.endswith("test_api"):
        yield None
        return
    with patch(BASIC_INFO_PATH, AsyncMock(return_value=basic_info_response)) as mock:
        yield mock


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


@pytest.fixture
def fla48460tg2_response() -> dict[str, Any]:
    """Raw device JSON reported by a Felicity Solar FLA48460TG2/GT2 (see issue #50)."""
    path = Path(__file__).parent / "fixtures" / "fla48460tg2_response.json"
    return json.loads(path.read_text())


@pytest.fixture
def lux_e_48100lg03_response() -> dict[str, Any]:
    """Raw device JSON reported by a Lux-e 48100LG03 (see issue #59)."""
    path = Path(__file__).parent / "fixtures" / "lux_e_48100lg03_response.json"
    return json.loads(path.read_text())
