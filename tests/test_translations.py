"""Every translation must mirror strings.json: same keys, same placeholders."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

COMPONENT_DIR = Path(__file__).parent.parent / "custom_components" / "felicity_solar_local"
STRINGS = json.loads((COMPONENT_DIR / "strings.json").read_text(encoding="utf-8"))
TRANSLATION_FILES = sorted((COMPONENT_DIR / "translations").glob("*.json"))
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, path))
        else:
            flat[path] = value
    return flat


SOURCE = _flatten(STRINGS)


def test_english_matches_strings() -> None:
    en = json.loads((COMPONENT_DIR / "translations" / "en.json").read_text(encoding="utf-8"))
    assert en == STRINGS


@pytest.mark.parametrize("path", TRANSLATION_FILES, ids=lambda p: p.stem)
def test_translation_has_same_keys(path: Path) -> None:
    translated = _flatten(json.loads(path.read_text(encoding="utf-8")))
    assert set(translated) == set(SOURCE)


@pytest.mark.parametrize("path", TRANSLATION_FILES, ids=lambda p: p.stem)
def test_translation_keeps_placeholders(path: Path) -> None:
    translated = _flatten(json.loads(path.read_text(encoding="utf-8")))
    for key, text in SOURCE.items():
        assert set(PLACEHOLDER.findall(translated.get(key, ""))) == set(
            PLACEHOLDER.findall(text)
        ), key
