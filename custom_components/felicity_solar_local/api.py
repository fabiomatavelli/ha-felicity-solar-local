"""TCP/JSON client for the Felicity Solar battery local WiFi protocol.

Protocol reverse-engineered from https://github.com/mxbode/Felicitysolar-FLA48300-WiFi-Readout
(no license on that repo, so this is a fresh implementation from the observed protocol facts,
not a port of its code) and confirmed live against a Felicity Solar FLB48314TG1-H:

- Plain TCP on port 53970, no TLS, no Modbus framing.
- Write the ASCII command ``wifilocalMonitor:get dev real infor`` (no newline needed).
- The device replies with a single JSON object. The payload never nests ``{}``, only ``[]``,
  so reading up to and including the first ``}`` yields the complete, valid JSON document.
- After parsing, write a single ``.`` byte back to the device as an acknowledgement.
- The device's embedded TCP server tolerates multiple query/response round-trips on the same
  open connection (confirmed manually via telnet), so this client can keep the connection
  open across calls (``persistent=True``, the default) instead of reconnecting every time,
  transparently reconnecting if the cached connection turns out to be stale/dead. When
  persistent, OS-level TCP keepalive is also enabled on the socket so a half-dead connection
  (e.g. the WiFi module rebooting without a clean FIN) is more likely to be caught by the OS
  while idle, rather than only reactively on the next failed query.
- The embedded TCP stack's tolerance for *concurrent* connections is unknown and may well be
  just one, so every query (the main data query, the separate timezone query) goes through
  the same connect-or-reuse path and is serialized by one lock - never two connections open
  at once.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
from typing import Any

from .const import (
    ACK_BYTE,
    BASIC_INFO_QUERY_COMMAND,
    DATE_QUERY_COMMAND,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    QUERY_COMMAND,
    STRAY_BYTES_FLUSH_TIMEOUT,
    TCP_KEEPALIVE_COUNT,
    TCP_KEEPALIVE_IDLE,
    TCP_KEEPALIVE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# The firmware reports a zero pack voltage when a read happens mid-boot/mid-update.
# Treat that as an invalid snapshot rather than publishing a zeroed voltage.
_PACK_VOLTAGE_PATH = ("Batt", 0, 0)


class FelicityLocalError(Exception):
    """Base error for the Felicity Solar local client."""


class FelicityConnectionError(FelicityLocalError):
    """Raised when the TCP connection to the battery cannot be established."""


class FelicityTimeoutError(FelicityLocalError):
    """Raised when the battery does not respond within the configured timeout."""


class FelicityProtocolError(FelicityLocalError):
    """Raised when the battery's response is not valid/usable JSON."""


def _extract_path(data: dict[str, Any], path: tuple[str, int, int]) -> Any:
    key, row, col = path
    try:
        return data[key][row][col]
    except (KeyError, IndexError, TypeError):
        return None


class FelicityLocalClient:
    """Async client for a single Felicity Solar battery's local WiFi endpoint."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
        persistent: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.persistent = persistent
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def async_get_data(self) -> dict[str, Any]:
        """Query the battery and return the parsed JSON payload.

        In persistent mode, reuses the cached connection when possible and retries once
        with a guaranteed-fresh connection if that fails. In one-shot mode (default),
        behaves exactly as a single connect/query/close round-trip.
        """
        async with self._lock:
            attempts = 2 if self.persistent else 1
            last_err: FelicityLocalError | None = None
            for _ in range(attempts):
                try:
                    await self._ensure_connected()
                    data = await self._query(QUERY_COMMAND)
                    self._validate(data)
                except FelicityLocalError as err:
                    last_err = err
                    await self._disconnect()
                    continue

                if not self.persistent:
                    await self._disconnect()
                return data

            assert last_err is not None
            raise last_err

    async def async_close(self) -> None:
        """Close the connection, if any. Safe to call whether or not one is open."""
        async with self._lock:
            await self._disconnect()

    async def async_get_timezone_offset_minutes(self) -> int | None:
        """Query the device's self-reported UTC offset (``wifilocalMonitor:get Date``).

        Shares the same connect/reuse logic as async_get_data - including reusing an
        already-open persistent connection - rather than opening a second, concurrent
        connection: the device's embedded TCP stack may only support one client at a
        time, so a second connection risks failing outright or evicting the primary
        polling connection. Best-effort: any failure returns None (treat as "unknown")
        rather than raising, since this is supplementary info, not the main poll data.
        """
        data = await self._async_best_effort_query(DATE_QUERY_COMMAND)
        offset = data.get("timeZMin") if data is not None else None
        return offset if isinstance(offset, int) else None

    async def async_get_basic_info(self) -> dict[str, Any] | None:
        """Query the device's model codes and firmware versions (``get dev basice infor``).

        Same connection handling and best-effort semantics as
        async_get_timezone_offset_minutes: any failure returns None.
        """
        return await self._async_best_effort_query(BASIC_INFO_QUERY_COMMAND)

    async def _async_best_effort_query(self, command: bytes) -> dict[str, Any] | None:
        """Run a supplementary query over the shared connection; None on any failure."""
        async with self._lock:
            try:
                await self._ensure_connected()
                data = await self._query(command)
            except FelicityLocalError:
                await self._disconnect()
                return None

            if not self.persistent:
                await self._disconnect()

        return data

    async def _ensure_connected(self) -> None:
        """Reuse the cached connection if it's still usable, else open a fresh one."""
        if self._writer is None or self._writer.is_closing():
            await self._connect()
        elif self.persistent:
            await self._flush_stray_bytes()

    async def _connect(self) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
        except TimeoutError as err:
            raise FelicityTimeoutError(
                f"Timed out connecting to {self.host}:{self.port}"
            ) from err
        except OSError as err:
            raise FelicityConnectionError(
                f"Could not connect to {self.host}:{self.port}: {err}"
            ) from err

        if self.persistent:
            self._enable_keepalive()

    def _enable_keepalive(self) -> None:
        """Best-effort: ask the OS to probe the persistent connection while it's idle.

        Without this, a peer that vanishes without a clean FIN (e.g. the battery's WiFi
        module rebooting) can leave a cached connection looking alive between polls, only
        discovered reactively on the next failed query. Tuning knobs (TCP_KEEPIDLE/
        TCP_KEEPINTVL/TCP_KEEPCNT on Linux, TCP_KEEPALIVE as the idle-time equivalent on
        macOS) aren't available on every platform, so each is applied independently via
        hasattr guards - a platform that only supports bare SO_KEEPALIVE still gets that
        much.
        """
        assert self._writer is not None
        sock = self._writer.get_extra_info("socket")
        if sock is None:
            return
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            if hasattr(socket, "TCP_KEEPIDLE"):  # Linux
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, TCP_KEEPALIVE_IDLE)
            elif hasattr(socket, "TCP_KEEPALIVE"):  # macOS equivalent of TCP_KEEPIDLE
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, TCP_KEEPALIVE_IDLE)
            if hasattr(socket, "TCP_KEEPINTVL"):
                sock.setsockopt(
                    socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, TCP_KEEPALIVE_INTERVAL
                )
            if hasattr(socket, "TCP_KEEPCNT"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, TCP_KEEPALIVE_COUNT)
        except OSError:
            _LOGGER.debug(
                "Could not tune TCP keepalive for %s:%s (non-fatal)", self.host, self.port
            )

    async def _disconnect(self) -> None:
        writer, self._writer = self._writer, None
        self._reader = None
        if writer is None:
            return
        writer.close()
        with contextlib.suppress(TimeoutError, OSError):
            await asyncio.wait_for(writer.wait_closed(), timeout=self.timeout)

    async def _flush_stray_bytes(self) -> None:
        """Best-effort: discard bytes left over from a previous response.

        The device isn't guaranteed to stop sending exactly at the closing '}' (see the
        trailing-bytes handling in _query()), so on a reused connection there may be stray
        bytes still sitting in the read buffer from the prior round-trip. A short-timeout
        read drains them before the next query; timing out here just means there was
        nothing pending, which is the common case.
        """
        assert self._reader is not None
        try:
            leftover = await asyncio.wait_for(
                self._reader.read(65536), timeout=STRAY_BYTES_FLUSH_TIMEOUT
            )
        except (TimeoutError, OSError):
            return
        if leftover:
            _LOGGER.debug(
                "Flushed %d stray byte(s) from %s:%s before next query",
                len(leftover),
                self.host,
                self.port,
            )

    async def _query(self, command: bytes) -> dict[str, Any]:
        writer = self._writer
        reader = self._reader
        assert writer is not None
        assert reader is not None

        writer.write(command)
        try:
            await asyncio.wait_for(writer.drain(), timeout=self.timeout)
        except OSError as err:
            raise FelicityConnectionError(f"Failed to send query: {err}") from err

        buffer = b""
        try:
            while b"}" not in buffer:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=self.timeout)
                if not chunk:
                    break
                buffer += chunk
        except TimeoutError as err:
            raise FelicityTimeoutError(
                f"Timed out waiting for response from {self.host}:{self.port}"
            ) from err
        except OSError as err:
            raise FelicityConnectionError(f"Connection error while reading: {err}") from err

        if b"}" not in buffer:
            raise FelicityProtocolError(
                f"Response from {self.host}:{self.port} was never terminated with '}}'"
            )

        payload = buffer[: buffer.index(b"}") + 1]

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as err:
            raise FelicityProtocolError(f"Could not parse response as JSON: {err}") from err

        if not isinstance(data, dict):
            raise FelicityProtocolError("Response JSON was not an object")

        # Best-effort ack; the battery doesn't require it for us to have already gotten
        # a valid reading, so a failure here shouldn't fail the whole update.
        try:
            writer.write(ACK_BYTE)
            await asyncio.wait_for(writer.drain(), timeout=self.timeout)
        except (TimeoutError, OSError):
            _LOGGER.debug(
                "Failed to send ack byte to %s:%s (non-fatal)", self.host, self.port
            )

        return data

    def _validate(self, data: dict[str, Any]) -> None:
        voltage = _extract_path(data, _PACK_VOLTAGE_PATH)
        if not voltage:
            raise FelicityProtocolError(
                f"Battery at {self.host}:{self.port} returned an invalid/empty snapshot "
                f"(pack voltage missing or zero)"
            )
