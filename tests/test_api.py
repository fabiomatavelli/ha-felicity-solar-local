"""Tests for the Felicity Solar local TCP/JSON client."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from typing import Any

import pytest

from custom_components.felicity_solar_local.api import (
    FelicityConnectionError,
    FelicityLocalClient,
    FelicityProtocolError,
    FelicityTimeoutError,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.enable_socket]


@pytest.fixture(autouse=True)
def _ensure_socket_enabled(socket_enabled: None) -> None:
    """Belt-and-suspenders alongside the `enable_socket` marker above.

    On some CI environments (observed: Python 3.14 on Linux, not reproduced locally on
    macOS with byte-for-byte identical package versions) the marker alone wasn't
    sufficient to unblock sockets before the test body ran - the very first
    asyncio.start_server() call in _FakeServer.start() was still hitting
    pytest-socket's guard. Explicitly depending on the socket_enabled fixture goes
    through pytest's core fixture resolution instead of marker lookup, which has
    proven more reliable.
    """


class _FakeServer:
    """A minimal TCP server that replays a canned response.

    By default it closes the connection after one query/response/ack round-trip
    (mirroring the client's one-shot mode). ``stay_open=True`` instead loops, accepting
    further queries on the same connection (mirroring what the real device tolerates and
    what the client's persistent mode relies on).
    """

    def __init__(self) -> None:
        self.received_command: bytes | None = None
        self.received_ack: bytes | None = None
        self.port: int | None = None
        self.handled = asyncio.Event()
        self.connection_count = 0
        self._server: asyncio.AbstractServer | None = None
        self._response: bytes = b""
        self._hold_open = False
        self._stay_open = False
        self._stray_bytes: bytes = b""
        self._command_responses: dict[bytes, bytes] = {}

    async def start(
        self,
        response: bytes,
        hold_open: bool = False,
        stay_open: bool = False,
        stray_bytes: bytes = b"",
        command_responses: dict[bytes, bytes] | None = None,
    ) -> int:
        self._response = response
        self._hold_open = hold_open
        self._stay_open = stay_open
        self._stray_bytes = stray_bytes
        self._command_responses = command_responses or {}
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.connection_count += 1
        if self._hold_open:
            # Simulate a device that never replies, to exercise the read timeout.
            await reader.read(1024)
            await asyncio.sleep(10)
            return

        first_round_trip = True
        while True:
            command = await reader.read(1024)
            if not command:
                break
            self.received_command = command
            writer.write(self._command_responses.get(command, self._response))
            await writer.drain()
            self.received_ack = await reader.read(1)
            self.handled.set()

            if first_round_trip and self._stray_bytes:
                # Simulate late-arriving trailing bytes sent as a separate write, not
                # part of the response itself.
                writer.write(self._stray_bytes)
                await writer.drain()
            first_round_trip = False

            if not self._stay_open:
                writer.close()
                break

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()


@pytest.fixture
async def fake_server() -> AsyncIterator[_FakeServer]:
    server = _FakeServer()
    yield server
    await server.stop()


async def test_async_get_data_parses_response_and_sends_ack(
    fake_server: _FakeServer, sample_response: dict[str, Any]
) -> None:
    port = await fake_server.start(json.dumps(sample_response).encode())

    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0)
    result = await client.async_get_data()
    await asyncio.wait_for(fake_server.handled.wait(), timeout=2.0)

    assert result["DevSN"] == sample_response["DevSN"]
    assert fake_server.received_command == b"wifilocalMonitor:get dev real infor"
    assert fake_server.received_ack == b"."


async def test_async_get_data_ignores_trailing_bytes_after_first_brace(
    fake_server: _FakeServer, sample_response: dict[str, Any]
) -> None:
    # The device is not guaranteed to close cleanly right after the closing brace;
    # the client must stop reading at the first '}' regardless of what follows.
    payload = json.dumps(sample_response).encode() + b"garbage-after-close"
    port = await fake_server.start(payload)

    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0)
    result = await client.async_get_data()

    assert result["DevSN"] == sample_response["DevSN"]


async def test_async_get_data_raises_on_malformed_json(fake_server: _FakeServer) -> None:
    port = await fake_server.start(b'{"Batt": [[54000]], "not valid json"}')

    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0)
    with pytest.raises(FelicityProtocolError):
        await client.async_get_data()


async def test_async_get_data_raises_on_zero_pack_voltage(
    fake_server: _FakeServer, sample_response: dict[str, Any]
) -> None:
    invalid = {**sample_response, "Batt": [[0], [0], [None]]}
    port = await fake_server.start(json.dumps(invalid).encode())

    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0)
    with pytest.raises(FelicityProtocolError):
        await client.async_get_data()


async def test_async_get_data_raises_on_read_timeout(fake_server: _FakeServer) -> None:
    port = await fake_server.start(b"", hold_open=True)

    client = FelicityLocalClient("127.0.0.1", port, timeout=0.2)
    with pytest.raises(FelicityTimeoutError):
        await client.async_get_data()


async def test_async_get_data_raises_on_connection_refused() -> None:
    # Bind a real socket and close it immediately: connecting to the just-freed port
    # deterministically yields a fast connection-refused everywhere. An arbitrary
    # unbound port number (e.g. a low privileged one) isn't reliable for this across
    # platforms/Python versions - some environments don't refuse it promptly.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0)
    with pytest.raises(FelicityConnectionError):
        await client.async_get_data()


async def test_one_shot_mode_reconnects_every_call(
    fake_server: _FakeServer, sample_response: dict[str, Any]
) -> None:
    # Even against a server willing to stay open, one-shot (persistent=False, the
    # default) must still open a fresh connection every call.
    port = await fake_server.start(json.dumps(sample_response).encode(), stay_open=True)
    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0)

    await client.async_get_data()
    await client.async_get_data()

    assert fake_server.connection_count == 2


async def test_persistent_mode_reuses_open_connection(
    fake_server: _FakeServer, sample_response: dict[str, Any]
) -> None:
    port = await fake_server.start(json.dumps(sample_response).encode(), stay_open=True)
    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0, persistent=True)

    for _ in range(3):
        result = await client.async_get_data()
        assert result["DevSN"] == sample_response["DevSN"]

    assert fake_server.connection_count == 1


async def test_persistent_mode_reconnects_after_stale_connection(
    fake_server: _FakeServer, sample_response: dict[str, Any]
) -> None:
    # Server closes after every round-trip (stay_open defaults to False) - the client's
    # cached connection from the first call is stale by the second call, and it must
    # detect that and transparently reconnect rather than fail.
    port = await fake_server.start(json.dumps(sample_response).encode())
    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0, persistent=True)

    await client.async_get_data()
    await client.async_get_data()

    assert fake_server.connection_count == 2


async def test_persistent_mode_flushes_stray_bytes_before_next_query(
    fake_server: _FakeServer, sample_response: dict[str, Any]
) -> None:
    port = await fake_server.start(
        json.dumps(sample_response).encode(),
        stay_open=True,
        stray_bytes=b"stray-garbage-not-json",
    )
    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0, persistent=True)

    first = await client.async_get_data()
    second = await client.async_get_data()

    assert first["DevSN"] == sample_response["DevSN"]
    assert second["DevSN"] == sample_response["DevSN"]
    assert fake_server.connection_count == 1


async def test_async_close_disconnects_persistent_connection(
    fake_server: _FakeServer, sample_response: dict[str, Any]
) -> None:
    port = await fake_server.start(json.dumps(sample_response).encode(), stay_open=True)
    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0, persistent=True)

    await client.async_get_data()
    assert fake_server.connection_count == 1

    await client.async_close()

    await client.async_get_data()
    assert fake_server.connection_count == 2


async def test_persistent_mode_enables_tcp_keepalive(
    fake_server: _FakeServer, sample_response: dict[str, Any]
) -> None:
    port = await fake_server.start(json.dumps(sample_response).encode(), stay_open=True)
    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0, persistent=True)

    await client.async_get_data()

    assert client._writer is not None
    sock = client._writer.get_extra_info("socket")
    assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) != 0


async def test_one_shot_mode_does_not_enable_tcp_keepalive(fake_server: _FakeServer) -> None:
    port = await fake_server.start(b"")  # never reached; connecting is enough
    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0, persistent=False)

    await client._connect()
    try:
        assert client._writer is not None
        sock = client._writer.get_extra_info("socket")
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) == 0
    finally:
        await client._disconnect()


async def test_async_get_timezone_offset_minutes_parses_response(
    fake_server: _FakeServer,
) -> None:
    port = await fake_server.start(
        b"",
        command_responses={
            b"wifilocalMonitor:get Date": b'{"CommVer":1,"timeZMin":60,"rssi":-79}'
        },
    )
    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0)

    offset = await client.async_get_timezone_offset_minutes()

    assert offset == 60
    assert fake_server.received_command == b"wifilocalMonitor:get Date"


async def test_async_get_timezone_offset_minutes_returns_none_on_failure(
    fake_server: _FakeServer,
) -> None:
    port = await fake_server.start(
        b"",
        command_responses={b"wifilocalMonitor:get Date": b'{"no timeZMin here"}'},
    )
    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0)

    assert await client.async_get_timezone_offset_minutes() is None


async def test_async_get_timezone_offset_minutes_reuses_open_persistent_connection(
    fake_server: _FakeServer, sample_response: dict[str, Any]
) -> None:
    # The device's embedded TCP stack may only support one connection at a time, so the
    # timezone query must never open a second, concurrent connection - it should reuse
    # whatever connection async_get_data already has open in persistent mode.
    port = await fake_server.start(
        json.dumps(sample_response).encode(),
        stay_open=True,
        command_responses={
            b"wifilocalMonitor:get Date": b'{"CommVer":1,"timeZMin":60,"rssi":-79}'
        },
    )
    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0, persistent=True)

    await client.async_get_data()
    offset = await client.async_get_timezone_offset_minutes()

    assert offset == 60
    assert fake_server.connection_count == 1


async def test_async_get_timezone_offset_minutes_does_not_leave_one_shot_connection_open(
    fake_server: _FakeServer,
) -> None:
    port = await fake_server.start(
        b"",
        command_responses={
            b"wifilocalMonitor:get Date": b'{"CommVer":1,"timeZMin":60,"rssi":-79}'
        },
    )
    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0)  # persistent=False

    await client.async_get_timezone_offset_minutes()

    assert client._writer is None


async def test_async_get_basic_info_returns_payload(fake_server: _FakeServer) -> None:
    port = await fake_server.start(
        b"",
        command_responses={
            b"wifilocalMonitor:get dev basice infor": b'{"version":"2.10","M1SwVer":203}'
        },
    )
    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0)

    info = await client.async_get_basic_info()

    assert info == {"version": "2.10", "M1SwVer": 203}
    assert fake_server.received_command == b"wifilocalMonitor:get dev basice infor"
    assert client._writer is None


async def test_async_get_basic_info_returns_none_on_failure(fake_server: _FakeServer) -> None:
    port = await fake_server.start(
        b"",
        command_responses={b"wifilocalMonitor:get dev basice infor": b'{"broken"}'},
    )
    client = FelicityLocalClient("127.0.0.1", port, timeout=2.0)

    assert await client.async_get_basic_info() is None
