#!/usr/bin/env python3
"""Probe a Felicity Solar battery's local WiFi endpoint and dump its raw snapshot.

Standalone (stdlib-only) - does not require Home Assistant or the integration installed.
Useful for confirming the protocol works against a given battery before setting up the
integration, and for capturing a fixture to build/verify a battery-model profile.

Usage: python3 scripts/probe.py <host> [port] [--report] [--output FILE]

The default mode prints the payload untouched, serial numbers included - it's a local
debugging tool. ``--report`` instead prints a Markdown "battery profile request" issue body
with the serial numbers redacted, ready to paste into (or pass as ``--body-file`` to) a new
GitHub issue.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_PORT = 53970
QUERY_COMMAND = b"wifilocalMonitor:get dev real infor"
ACK_BYTE = b"."
TIMEOUT = 5.0

# Keep in sync with diagnostics.TO_REDACT (which can't be imported here without pulling in
# Home Assistant). These are the raw payload keys that carry the device/WiFi serials.
REDACT_KEYS = ("DevSN", "wifiSN")
REDACTED = "**REDACTED**"

REPORT_TITLE_PREFIX = "[Battery profile]"


async def probe(host: str, port: int) -> dict[str, Any]:
    """Query the battery once and return its parsed JSON snapshot."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port), timeout=TIMEOUT
    )

    try:
        writer.write(QUERY_COMMAND)
        await asyncio.wait_for(writer.drain(), timeout=TIMEOUT)

        buffer = b""
        while b"}" not in buffer:
            chunk = await asyncio.wait_for(reader.read(4096), timeout=TIMEOUT)
            if not chunk:
                break
            buffer += chunk

        if b"}" not in buffer:
            raise OSError(f"No closing brace received. Raw buffer: {buffer!r}")

        payload = buffer[: buffer.index(b"}") + 1]
        data = json.loads(payload)

        writer.write(ACK_BYTE)
        await asyncio.wait_for(writer.drain(), timeout=TIMEOUT)
        return data
    finally:
        writer.close()
        with contextlib.suppress(TimeoutError, OSError):
            await asyncio.wait_for(writer.wait_closed(), timeout=TIMEOUT)


def redact(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``data`` with the serial-number fields replaced."""
    return {key: REDACTED if key in REDACT_KEYS else value for key, value in data.items()}


def report_title(data: dict[str, Any]) -> str:
    """Suggested GitHub issue title for a profile request."""
    return (
        f"{REPORT_TITLE_PREFIX} <model> (Type={data.get('Type')}, "
        f"SubType={data.get('SubType')})"
    )


def render_report(data: dict[str, Any]) -> str:
    """Render a Markdown issue body requesting a profile for this battery.

    Section headings mirror .github/ISSUE_TEMPLATE/battery_profile.yml so issues opened
    from this output look the same as ones opened through the web form.
    """
    payload = json.dumps(redact(data), indent=2)
    return f"""\
<!-- Suggested title: {report_title(data)} -->

### Battery model

<!-- Exact model from the battery's label, e.g. FLA48300 -->

### Type / SubType

Type={data.get("Type")}, SubType={data.get("SubType")}

### Raw device payload

```json
{payload}
```

### Vendor app readings (for cross-checking)

<!-- Optional, but it's what lets the profile be marked verified. Read these from the
Felicity app/cloud at roughly the same moment as the payload above. -->

- SOC (%):
- Pack voltage (V):
- Current (A):
- Temperature(s) (°C):
- Capacity (Ah):

### Notes

<!-- Anything else: firmware version, readings that look wrong, how many packs, etc. -->
"""


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Probe a Felicity Solar battery over its local WiFi protocol."
    )
    parser.add_argument("host", help="battery IP address or hostname")
    parser.add_argument("port", nargs="?", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--report",
        action="store_true",
        help="print a redacted Markdown issue body for requesting a new battery profile",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="with --report, also write the issue body to this file",
    )
    args = parser.parse_args(argv)

    if not args.report:
        print(f"Connecting to {args.host}:{args.port} ...")

    try:
        data = asyncio.run(probe(args.host, args.port))
    except (TimeoutError, OSError, ValueError) as err:
        print(f"Failed to probe {args.host}:{args.port}: {err}", file=sys.stderr)
        sys.exit(1)

    if args.report:
        body = render_report(data)
        if args.output:
            args.output.write_text(body)
        print(body)
        return

    print(f"\nType={data.get('Type')} SubType={data.get('SubType')} "
          f"DevSN={data.get('DevSN')}\n")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
