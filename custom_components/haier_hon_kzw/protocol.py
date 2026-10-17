"""hOn protocol carried over TCP by Haier KZW-W002 Wi-Fi keys (e.g. 0011800292K).

Pure Python, no Home Assistant import, so it can be tested on its own.

Wire format (verified by capture, CRC/checksum checked on real frames):
  KZW header (80 bytes): [0:4] 00 00 27 14 (request) / 00 00 27 15 (reply),
      [40:52] key MAC as 12 ASCII hex chars, [72:76] sequence (big endian),
      [76:80] payload length (big endian). Unsolicited frames from the key use seq 0.
  hOn frame: ff ff | len | flags (0x40 = CRC present) | 00 x5 | frame type |
      data (subcommand + payload) | checksum | CRC-16/ARC (2 bytes, big endian)
      len = 8 + len(data); checksum = sum(len..data) & 0xff; CRC over len..data.

Control layout and rules mirror ESPHome's haier/hon_climate.cpp (HaierPacketControl).
"""
from __future__ import annotations

from dataclasses import dataclass

KZW_HEADER_LEN = 80
KZW_REQUEST = b"\x00\x00\x27\x14"
KZW_REPLY = b"\x00\x00\x27\x15"

FRAME_CONTROL = 0x01
FRAME_STATUS = 0x02
FRAME_INVALID = 0x03
FRAME_ALARM_STATUS = 0x04
FRAME_REPORT = 0x06

SUB_GET_USER_DATA = 0x4D01
SUB_GET_BIG_DATA = 0x4DFE
SUB_SET_POWER = 0x5D01  # SET_SINGLE_PARAMETER, parameter 1 = power
SUB_SET_GROUP = 0x6001  # SET_GROUP_PARAMETERS, group 1 = control packet
SUB_USER_DATA_REPLY = 0x6D01
SUB_BIG_DATA_REPLY = 0x7D01

# Proven status request (no CRC). Accepted by every key tested.
STATUS_QUERY = bytes.fromhex("ffff0a000000000000014d0159")
# Status + "big data" (power, compressor, coils); answered by the Nagano units tested.
BIG_DATA_QUERY = bytes.fromhex("ffff0a40000000000001 4dfe 96f3f4".replace(" ", ""))

CONTROL_LEN = 10
SENSORS_LEN = 22
BIG_DATA_LEN = 14

MODE_AUTO = 0
MODE_COOL = 1
MODE_DRY = 2
MODE_HEALTHY_DRY = 3
MODE_HEAT = 4
MODE_ENERGY_SAVING = 5
MODE_FAN = 6

FAN_HIGH = 1
FAN_MID = 2
FAN_LOW = 3
FAN_AUTO = 5

SWING_V_HEALTH_UP = 0x01
SWING_V_MAX_UP = 0x02
SWING_V_HEALTH_DOWN = 0x03
SWING_V_UP = 0x04
SWING_V_CENTER = 0x06
SWING_V_DOWN = 0x08
SWING_V_MAX_DOWN = 0x0A
SWING_V_AUTO = 0x0C
SWING_V_AUTO_SPECIAL = 0x0E

SWING_H_CENTER = 0x00
SWING_H_MAX_LEFT = 0x03
SWING_H_LEFT = 0x04
SWING_H_RIGHT = 0x05
SWING_H_MAX_RIGHT = 0x06
SWING_H_AUTO = 0x07

MIN_TEMP = 16
MAX_TEMP = 30


class ProtocolError(Exception):
    """Malformed or unexpected frame."""


def crc16_arc(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def _hon_frame(frame_type: int, data: bytes, use_crc: bool) -> bytes:
    body = bytes([8 + len(data), 0x40 if use_crc else 0x00, 0, 0, 0, 0, 0, frame_type]) + data
    frame = b"\xff\xff" + body + bytes([sum(body) & 0xFF])
    if use_crc:
        frame += crc16_arc(body).to_bytes(2, "big")
    return frame


def build_hon_frame(frame_type: int, data: bytes) -> bytes:
    """Build an hOn frame without any 0xff byte after the header.

    On the UART a 0xff inside a frame is escaped with 0x55; we do not know whether the
    key does that for us, so we never send such a frame. If the CRC variant contains
    0xff, the variant without CRC (also accepted by the unit) is used instead.
    """
    for use_crc in (True, False):
        frame = _hon_frame(frame_type, data, use_crc)
        if 0xFF not in frame[2:]:
            return frame
    raise ProtocolError("frame would contain an escaped 0xff byte")


def wrap_kzw(mac: str, seq: int, hon: bytes) -> bytes:
    header = bytearray(KZW_HEADER_LEN)
    header[0:4] = KZW_REQUEST
    header[40:52] = mac.encode("ascii")
    header[72:76] = seq.to_bytes(4, "big")
    header[76:80] = len(hon).to_bytes(4, "big")
    return bytes(header) + hon


def normalize_mac(mac: str) -> str:
    clean = "".join(c for c in mac.upper() if c in "0123456789ABCDEF")
    if len(clean) != 12:
        raise ValueError("MAC address must have 12 hexadecimal digits")
    return clean


class KzwStreamParser:
    """Reassembles KZW reply frames from a TCP byte stream."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, chunk: bytes) -> list[tuple[int, bytes]]:
        """Return a list of (seq, hon_payload)."""
        self._buf += chunk
        frames = []
        while True:
            start = self._buf.find(KZW_REPLY)
            if start < 0:
                self._buf = self._buf[-3:]
                return frames
            self._buf = self._buf[start:]
            if len(self._buf) < KZW_HEADER_LEN:
                return frames
            size = int.from_bytes(self._buf[76:80], "big")
            if size > 1024:
                self._buf = self._buf[4:]
                continue
            if len(self._buf) < KZW_HEADER_LEN + size:
                return frames
            seq = int.from_bytes(self._buf[72:76], "big")
            frames.append((seq, self._buf[KZW_HEADER_LEN:KZW_HEADER_LEN + size]))
            self._buf = self._buf[KZW_HEADER_LEN + size:]


@dataclass(frozen=True)
class HonMessage:
    frame_type: int
    subcommand: int | None
    payload: bytes  # data after the subcommand


def parse_hon(frame: bytes) -> HonMessage:
    """Decode an hOn frame. A 0xff inside a frame is followed by an escape byte 0x55
    (UART byte stuffing, relayed as is by the key): it is removed, but still counted
    in the checksum, while the CRC covers the unescaped bytes (as in HaierProtocol)."""
    if len(frame) < 11 or frame[0:2] != b"\xff\xff":
        raise ProtocolError("not an hOn frame")
    raw = bytearray()
    escapes = 0
    i = 2
    while i < len(frame):
        raw.append(frame[i])
        if frame[i] == 0xFF and i + 1 < len(frame) and frame[i + 1] == 0x55:
            escapes += 1
            i += 1
        i += 1
    length = raw[0]
    if length < 8 or len(raw) < length + 1:
        raise ProtocolError("truncated hOn frame")
    body = bytes(raw[:length])
    if ((sum(body) + 0x55 * escapes) & 0xFF) != raw[length]:
        raise ProtocolError("bad checksum")
    if body[1] & 0x40:
        if len(raw) < length + 3 or crc16_arc(body).to_bytes(2, "big") != bytes(raw[length + 1:length + 3]):
            raise ProtocolError("bad CRC")
    data = body[8:]
    if len(data) >= 2:
        return HonMessage(body[7], int.from_bytes(data[0:2], "big"), data[2:])
    return HonMessage(body[7], None, data)


@dataclass(frozen=True)
class HonStatus:
    control: bytes  # raw 10-byte control packet, reused to build commands
    power: bool
    mode: int
    fan: int
    target_temperature: float
    vertical_swing: int
    horizontal_swing: int
    display: bool
    health: bool
    quiet: bool
    fast: bool
    sleep: bool
    room_temperature: float
    room_humidity: int
    outdoor_temperature: int
    error: int
    big: HonBigData | None = None

    @property
    def vertical_swing_on(self) -> bool:
        return self.vertical_swing in (SWING_V_AUTO, SWING_V_AUTO_SPECIAL)

    @property
    def horizontal_swing_on(self) -> bool:
        return self.horizontal_swing == SWING_H_AUTO


@dataclass(frozen=True)
class HonBigData:
    power: int  # W
    indoor_coil_temperature: float
    outdoor_out_air_temperature: int
    outdoor_coil_temperature: int
    outdoor_in_air_temperature: int
    outdoor_defrost_temperature: int
    compressor_frequency: int  # Hz
    compressor_current: float | None  # A, None when not reported
    outdoor_fan: int  # 0 off, 1 on, 2 not available
    defrost: int
    compressor: int
    indoor_fan: int
    four_way_valve: int
    expansion_valve: int


def is_status(msg: HonMessage) -> bool:
    return (
        msg.frame_type in (FRAME_STATUS, FRAME_REPORT)
        and msg.subcommand in (SUB_USER_DATA_REPLY, SUB_BIG_DATA_REPLY)
        and len(msg.payload) >= CONTROL_LEN + SENSORS_LEN
    )


def decode_big_data(b: bytes) -> HonBigData:
    current = int.from_bytes(b[8:10], "big")
    return HonBigData(
        power=int.from_bytes(b[0:2], "big"),
        indoor_coil_temperature=b[2] / 2 - 20,
        outdoor_out_air_temperature=b[3] - 64,
        outdoor_coil_temperature=b[4] - 64,
        outdoor_in_air_temperature=b[5] - 64,
        outdoor_defrost_temperature=b[6] - 64,
        compressor_frequency=b[7],
        compressor_current=None if current >= 0x01FF else current / 10,
        outdoor_fan=b[10] & 0x03,
        defrost=(b[10] >> 2) & 0x03,
        compressor=b[11] & 0x03,
        indoor_fan=(b[11] >> 2) & 0x03,
        four_way_valve=(b[11] >> 4) & 0x03,
        expansion_valve=int.from_bytes(b[12:14], "big"),
    )


def decode_status(msg: HonMessage) -> HonStatus:
    if not is_status(msg):
        raise ProtocolError("not a status frame")
    c = msg.payload[:CONTROL_LEN]
    s = msg.payload[CONTROL_LEN:CONTROL_LEN + SENSORS_LEN]
    return HonStatus(
        control=bytes(c),
        power=bool(c[5] & 0x01),
        mode=c[2] >> 5,
        fan=c[2] & 0x07,
        target_temperature=c[0] + 16 + (0.5 if c[4] & 0x04 else 0.0),
        vertical_swing=c[1] & 0x0F,
        horizontal_swing=c[7] & 0x07,
        display=bool(c[4] & 0x02),
        health=bool(c[5] & 0x02),
        quiet=bool(c[5] & 0x10),
        fast=bool(c[5] & 0x08),
        sleep=bool(c[5] & 0x20),
        room_temperature=s[0] / 2,
        room_humidity=s[1],
        outdoor_temperature=s[2] - 64,
        error=s[4],
        big=decode_big_data(msg.payload[CONTROL_LEN + SENSORS_LEN:])
        if msg.subcommand == SUB_BIG_DATA_REPLY and len(msg.payload) >= CONTROL_LEN + SENSORS_LEN + BIG_DATA_LEN
        else None,
    )


def build_power(on: bool) -> bytes:
    return build_hon_frame(FRAME_CONTROL, SUB_SET_POWER.to_bytes(2, "big") + (b"\x00\x01" if on else b"\x00\x00"))


def build_control(
    status: HonStatus,
    *,
    power: bool | None = None,
    mode: int | None = None,
    fan: int | None = None,
    target_temperature: float | None = None,
    vertical_swing: bool | None = None,
    horizontal_swing: bool | None = None,
    vertical_position: int | None = None,
    horizontal_position: int | None = None,
    quiet: bool | None = None,
    turbo: bool | None = None,
    display: bool | None = None,
    fixed_vertical_position: int = SWING_V_CENTER,
    fixed_horizontal_position: int = SWING_H_CENTER,
    beeper: bool = True,
) -> bytes:
    """SET_GROUP_PARAMETERS frame built from the last status, like ESPHome does."""
    c = bytearray(status.control)
    cur_power = status.power if power is None else power
    cur_mode = status.mode if mode is None else mode
    cur_fan = status.fan if fan is None else fan
    if cur_mode == MODE_FAN and cur_fan == FAN_AUTO:
        cur_fan = FAN_MID  # auto fan is refused in fan-only mode
    c[2] = (c[2] & 0x18) | (cur_mode << 5) | cur_fan
    half = 0
    if target_temperature is not None:
        target = min(max(target_temperature, MIN_TEMP), MAX_TEMP)
        c[0] = int(target) - 16
        half = 1 if target - int(target) >= 0.49 else 0
    else:
        half = (c[4] >> 2) & 1
    if vertical_swing is not None:
        position = SWING_V_AUTO if vertical_swing else fixed_vertical_position
        c[1] = (c[1] & 0xF0) | position
    if horizontal_swing is not None:
        position = SWING_H_AUTO if horizontal_swing else fixed_horizontal_position
        c[7] = (c[7] & 0xF8) | position
    # an explicit louver position wins (and stops the swing on that axis)
    if vertical_position is not None:
        c[1] = (c[1] & 0xF0) | (vertical_position & 0x0F)
    if horizontal_position is not None:
        c[7] = (c[7] & 0xF8) | (horizontal_position & 0x07)
    # byte 4 must be cleared, then only display and half degree are set
    cur_display = status.display if display is None else display
    c[4] = (0x02 if cur_display else 0) | (half << 2)
    flags = c[5] & ~0x01 & ~0x80
    if quiet is not None:
        flags = (flags | 0x10) if quiet else (flags & ~0x10)
    if turbo is not None:
        flags = (flags | 0x08) if turbo else (flags & ~0x08)
    if cur_power:
        flags |= 0x01
    else:
        flags &= ~(0x08 | 0x20)  # no boost / sleep when off
    if not cur_power or cur_mode == MODE_FAN:
        flags &= ~(0x10 | 0x08)  # no quiet / boost when off or fan only
    if not beeper:
        flags |= 0x80
    c[5] = flags
    return build_hon_frame(FRAME_CONTROL, SUB_SET_GROUP.to_bytes(2, "big") + bytes(c))
