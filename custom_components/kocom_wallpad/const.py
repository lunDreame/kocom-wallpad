"""Constants for Kocom Wallpad."""

from __future__ import annotations

import logging
from enum import IntEnum
from homeassistant.const import Platform

LOGGER = logging.getLogger(__package__)

DOMAIN = "kocom_wallpad"
PLATFORMS = [
    Platform.LIGHT,
    Platform.SWITCH,
    Platform.CLIMATE,
    Platform.FAN,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]

PACKET_PREFIX = bytes([0xAA, 0x55])
PACKET_SUFFIX = bytes([0x0D, 0x0D])
PACKET_LEN = 21

DEFAULT_TCP_PORT = 8899
RECV_POLL_SEC = 0.05  # 50ms polling
IDLE_GAP_SEC = 0.20   # 보내기 전 라인 유휴로 보고 싶은 최소 간격
SEND_RETRY_MAX = 3
SEND_RETRY_GAP = 0.15
CMD_CONFIRM_TIMEOUT = 1.0  # 보낸 뒤 상태 확인을 기다리는 최대 시간

class DeviceType(IntEnum):
    """Device types."""
    UNKNOWN = 0
    LIGHT = 1
    LIGHTCUTOFF = 2
    DIMMINGLIGHT = 3
    OUTLET = 4
    THERMOSTAT = 5
    AIRCONDITIONER = 6
    VENTILATION = 7
    GASVALVE = 8
    ELEVATOR = 9
    MOTION = 10
    AIRQUALITY = 11
    INTERPHONE = 12


class SubType(IntEnum):
    """Sub types."""
    NONE = 0
    DIRECTION = 1
    FLOOR = 2
    ERRCODE = 3
    HEATTEMP = 4
    HOTTEMP = 5
    CO2 = 6
    PM10 = 7
    PM25 = 8
    VOC = 9
    TEMP = 10
    HUMIDITY = 11
    EXIT = 12
    RING = 13
