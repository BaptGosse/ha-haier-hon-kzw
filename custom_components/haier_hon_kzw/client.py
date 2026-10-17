"""Asyncio client for one KZW-W002 key (no Home Assistant import)."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from .protocol import (
    BIG_DATA_QUERY,
    FRAME_INVALID,
    STATUS_QUERY,
    SUB_BIG_DATA_REPLY,
    SWING_H_AUTO,
    SWING_H_CENTER,
    SWING_V_AUTO,
    SWING_V_AUTO_SPECIAL,
    SWING_V_CENTER,
    HonBigData,
    HonMessage,
    HonStatus,
    KzwStreamParser,
    ProtocolError,
    build_control,
    build_power,
    decode_status,
    is_status,
    normalize_mac,
    parse_hon,
    wrap_kzw,
)

_LOGGER = logging.getLogger(__name__)

PORT = 56800
CONNECT_TIMEOUT = 10.0
REQUEST_TIMEOUT = 4.0
COMMAND_GAP = 0.15  # the key is fragile: one command at a time, small gap
POLL_INTERVAL = 10.0  # the key drops a connection after ~17 s without a request (measured)
SILENCE_TIMEOUT = POLL_INTERVAL * 3
MAX_BACKOFF = 60.0


class CommandError(Exception):
    """The unit refused or did not answer a command."""


class HonKzwClient:
    def __init__(self, host: str, mac: str, port: int = PORT) -> None:
        self.host = host
        self.mac = normalize_mac(mac)
        self.port = port
        self.status: HonStatus | None = None
        self.available = False
        self.last_vertical_position = SWING_V_CENTER
        self.last_horizontal_position = SWING_H_CENTER
        self.beeper = True  # sent with every command, the unit does not store it
        self.big: HonBigData | None = None  # power, compressor... (if the unit answers)
        self._big_supported = True
        self._big_failures = 0
        self._listeners: list[Callable[[], None]] = []
        self._writer: asyncio.StreamWriter | None = None
        self._pending: dict[int, asyncio.Future[HonMessage]] = {}
        self._lock = asyncio.Lock()
        self._seq = 0
        self._ready = asyncio.Event()
        self._closing = False

    # -- listeners -----------------------------------------------------------------
    def add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback)

    def _notify(self) -> None:
        for callback in list(self._listeners):
            callback()

    def _set_available(self, value: bool) -> None:
        if self.available != value:
            self.available = value
            _LOGGER.info("%s (%s) %s", self.host, self.mac, "available" if value else "unavailable")
            self._notify()

    # -- connection loop -----------------------------------------------------------
    async def wait_ready(self, timeout: float) -> None:
        await asyncio.wait_for(self._ready.wait(), timeout)

    async def run(self) -> None:
        """Keep a connection open forever, reconnecting with backoff."""
        backoff = 5.0
        while not self._closing:
            try:
                await self._session()
                backoff = 5.0
            except (OSError, asyncio.TimeoutError, ConnectionError) as err:
                _LOGGER.debug("%s: connection lost: %r", self.host, err)
            finally:
                self._teardown()
            if self._closing:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)

    async def stop(self) -> None:
        self._closing = True
        self._teardown()

    def _teardown(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ConnectionError("connection closed"))
        self._pending.clear()
        self._set_available(False)

    async def _session(self) -> None:
        reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), CONNECT_TIMEOUT
        )
        _LOGGER.debug("%s: connected", self.host)
        poller = asyncio.create_task(self._poll())
        try:
            parser = KzwStreamParser()
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), SILENCE_TIMEOUT)
                if not chunk:
                    raise ConnectionError("closed by the key")
                for seq, frame in parser.feed(chunk):
                    self._handle(seq, frame)
        finally:
            poller.cancel()

    async def _poll(self) -> None:
        count = 0
        while True:
            big = self._big_supported and count % 3 == 0
            try:
                msg = await self._request(BIG_DATA_QUERY if big else STATUS_QUERY)
                if big:
                    self._big_failures = 0 if msg.subcommand == SUB_BIG_DATA_REPLY else self._big_failures + 1
            except CommandError as err:
                _LOGGER.debug("%s: poll refused: %r", self.host, err)
                if big:
                    self._big_failures += 1
            except (ConnectionError, asyncio.TimeoutError) as err:
                _LOGGER.debug("%s: poll failed: %r", self.host, err)
            except Exception:  # never let the keep-alive die: the key drops idle clients
                _LOGGER.exception("%s: unexpected error while polling", self.host)
            if self._big_supported and self._big_failures >= 3:
                _LOGGER.info("%s: unit does not answer big data requests, disabled", self.host)
                self._big_supported = False
            count += 1
            await asyncio.sleep(POLL_INTERVAL)

    def _handle(self, seq: int, frame: bytes) -> None:
        try:
            msg = parse_hon(frame)
        except ProtocolError as err:
            _LOGGER.debug("%s: ignored frame (%s): %s", self.host, err, frame.hex())
            return
        if is_status(msg):
            status = decode_status(msg)
            if status.vertical_swing not in (0, SWING_V_AUTO, SWING_V_AUTO_SPECIAL):
                self.last_vertical_position = status.vertical_swing
            if status.horizontal_swing != SWING_H_AUTO:
                self.last_horizontal_position = status.horizontal_swing
            if self.status is None or status.control != self.status.control:
                _LOGGER.debug("%s: control %s", self.host, status.control.hex(" "))
            self.status = status
            if status.big is not None:
                self.big = status.big
            self._ready.set()
            self._set_available(True)
            self._notify()
        elif msg.frame_type == FRAME_INVALID:
            _LOGGER.warning("%s: unit rejected a frame: %s", self.host, frame.hex())
        future = self._pending.pop(seq, None) if seq else None
        if future is not None and not future.done():
            future.set_result(msg)

    async def _request(self, hon: bytes) -> HonMessage:
        async with self._lock:
            if self._writer is None:
                raise ConnectionError("not connected")
            self._seq = self._seq % 250 + 1
            seq = self._seq
            future: asyncio.Future[HonMessage] = asyncio.get_running_loop().create_future()
            self._pending[seq] = future
            try:
                self._writer.write(wrap_kzw(self.mac, seq, hon))
                await self._writer.drain()
                msg = await asyncio.wait_for(future, REQUEST_TIMEOUT)
            finally:
                self._pending.pop(seq, None)
            await asyncio.sleep(COMMAND_GAP)
        if msg.frame_type == FRAME_INVALID:
            raise CommandError("frame rejected by the unit")
        return msg

    # -- commands ------------------------------------------------------------------
    async def _command(self, hon: bytes) -> None:
        try:
            msg = await self._request(hon)
        except (ConnectionError, asyncio.TimeoutError) as err:
            raise CommandError(str(err) or "no answer") from err
        if not is_status(msg):
            # the reply should be the full status; ask for it if it was not
            await self._request(STATUS_QUERY)

    async def async_set_power(self, on: bool) -> None:
        if self.beeper or self.status is None:
            await self._command(build_power(on))
        else:
            # the single-parameter power command has no beeper flag
            await self.async_control(power=on)

    async def async_control(self, **changes: Any) -> None:
        if self.status is None:
            raise CommandError("state not known yet")
        await self._command(
            build_control(
                self.status,
                fixed_vertical_position=self.last_vertical_position,
                fixed_horizontal_position=self.last_horizontal_position,
                beeper=self.beeper,
                **changes,
            )
        )


async def async_probe(host: str, mac: str, timeout: float = 8.0) -> HonStatus:
    """Connect once, read the status, disconnect. Used by the config flow."""
    mac = normalize_mac(mac)
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, PORT), timeout)
    try:
        writer.write(wrap_kzw(mac, 1, STATUS_QUERY))
        await writer.drain()
        parser = KzwStreamParser()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while (remaining := deadline - loop.time()) > 0:
            chunk = await asyncio.wait_for(reader.read(4096), remaining)
            if not chunk:
                break
            for _seq, frame in parser.feed(chunk):
                try:
                    msg = parse_hon(frame)
                except ProtocolError:
                    continue
                if is_status(msg):
                    return decode_status(msg)
        raise ProtocolError("no hOn status received")
    finally:
        writer.close()
