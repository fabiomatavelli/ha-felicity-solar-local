"""Tests for the standalone scripts/probe.py helper."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_PROBE_PATH = Path(__file__).parent.parent / "scripts" / "probe.py"


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    # scripts/ isn't a package - load the file directly, the same way a user runs it.
    spec = importlib.util.spec_from_file_location("probe", _PROBE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report_payload(body: str) -> dict[str, Any]:
    match = re.search(r"```json\n(.*?)\n```", body, re.DOTALL)
    assert match is not None
    return json.loads(match.group(1))


def test_redact_replaces_serials_only(
    probe: ModuleType, sample_response: dict[str, Any]
) -> None:
    original = dict(sample_response)
    redacted = probe.redact(sample_response)

    assert redacted["DevSN"] == probe.REDACTED
    assert redacted["wifiSN"] == probe.REDACTED
    assert {k: v for k, v in redacted.items() if k not in probe.REDACT_KEYS} == {
        k: v for k, v in sample_response.items() if k not in probe.REDACT_KEYS
    }
    assert sample_response == original


def test_render_report_embeds_full_redacted_payload(
    probe: ModuleType, sample_response: dict[str, Any]
) -> None:
    body = probe.render_report(sample_response)

    payload = _report_payload(body)
    assert payload.keys() == sample_response.keys()
    assert payload == probe.redact(sample_response)
    assert sample_response["DevSN"] not in body
    assert sample_response["wifiSN"] not in body
    assert (
        f"Type={sample_response['Type']}, SubType={sample_response['SubType']}" in body
    )


def test_render_report_headings_match_issue_form(probe: ModuleType) -> None:
    form = (
        Path(__file__).parent.parent / ".github" / "ISSUE_TEMPLATE" / "battery_profile.yml"
    ).read_text()
    form_labels = re.findall(r"^\s+label: (.+)$", form, re.MULTILINE)
    body_headings = re.findall(r"^### (.+)$", probe.render_report({}), re.MULTILINE)

    assert body_headings == form_labels


def test_main_report_writes_output_file(
    probe: ModuleType,
    sample_response: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fake_probe(host: str, port: int) -> dict[str, Any]:
        return sample_response

    monkeypatch.setattr(probe, "probe", fake_probe)
    output = tmp_path / "report.md"

    probe.main(["192.168.1.50", "--report", "--output", str(output)])

    stdout = capsys.readouterr().out
    assert output.read_text() in stdout
    assert "192.168.1.50" not in stdout
    assert _report_payload(output.read_text()) == probe.redact(sample_response)
