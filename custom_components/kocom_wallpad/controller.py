"""코콤 월패드 컨트롤러 (Controller).

패킷을 파싱하여 기기 상태(DeviceState)를 생성하거나, 기기 제어 명령을 패킷으로 변환합니다.
"""

from __future__ import annotations

from typing import List, Callable, Any, Tuple
from dataclasses import dataclass, replace

from homeassistant.const import Platform, UnitOfTemperature
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.switch import SwitchDeviceClass
from homeassistant.components.climate.const import (
    PRESET_NONE,
    PRESET_AWAY,
    FAN_LOW,
    HVACMode,
)

from .const import (
    LOGGER,
    PACKET_PREFIX,
    PACKET_SUFFIX,
    CMD_CONFIRM_TIMEOUT,
    DeviceType,
    SubType,
)
from .models import (
    DEVICE_TYPE_MAP,
    AIRCONDITIONER_HVAC_MAP,
    AIRCONDITIONER_FAN_MAP,
    VENTILATION_PRESET_MAP,
    ELEVATOR_DIRECTION_MAP,
    DeviceKey,
    DeviceState
)

Predicate = Callable[[DeviceState], bool]

REV_DT_MAP = {v: k for k, v in DEVICE_TYPE_MAP.items()}
REV_AC_HVAC_MAP = {v: k for k, v in AIRCONDITIONER_HVAC_MAP.items()}
REV_AC_FAN_MAP = {v: k for k, v in AIRCONDITIONER_FAN_MAP.items()}
REV_VENT_PRESET_MAP = {v: k for k, v in VENTILATION_PRESET_MAP.items()}


@dataclass(slots=True, frozen=True)
class PacketFrame:
    """패킷 프레임 구조체."""
    raw: bytes

    @property
    def packet_type(self) -> int:
        """패킷 타입 반환."""
        return (self.raw[3] >> 4) & 0x0F

    @property
    def dest(self) -> bytes:
        """수신자 주소 반환."""
        return self.raw[5:7]

    @property
    def src(self) -> bytes:
        """송신자 주소 반환."""
        return self.raw[7:9]

    @property
    def command(self) -> int:
        """명령 코드 반환."""
        return self.raw[9]

    @property
    def payload(self) -> bytes:
        """데이터 페이로드 반환."""
        return self.raw[10:18]

    @property
    def checksum(self) -> int:
        """체크섬 값 반환."""
        return self.raw[18]

    @property
    def peer(self) -> tuple[int, int]:
        """상대방 기기 식별자 (타입, 룸 인덱스) 반환."""
        if self.dest[0] == 0x01:
            return (self.src[0], self.src[1])
        elif self.src[0] == 0x01:
            return (self.dest[0], self.dest[1])
        else:
            LOGGER.warning("Peer 해독 실패: dest=%s, src=%s", self.dest.hex(), self.src.hex())
            return (0, 0)

    @property
    def dev_type(self) -> DeviceType:
        """기기 타입 반환."""
        dev_type = DEVICE_TYPE_MAP.get(self.peer[0], None)
        if dev_type is None:
            LOGGER.debug("알 수 없는 기기 타입 code=%s, raw=%s", hex(self.peer[0]), self.raw.hex())
            dev_type = DeviceType.UNKNOWN
        return dev_type

    @property
    def dev_room(self) -> int:
        """기기 룸 인덱스 반환."""
        return self.peer[1]


class KocomController:
    """코콤 월패드 컨트롤러 클래스."""

    def __init__(self, gateway) -> None:
        """컨트롤러 초기화.

        Args:
            gateway: 게이트웨이 인스턴스
        """
        self.gateway = gateway
        self._device_storage: dict[str, Any] = {}

    @staticmethod
    def _checksum(buf: bytes) -> int:
        """체크섬 계산."""
        return sum(buf) % 256

    def process_packet(self, packet: bytes) -> None:
        """수신된 패킷 처리.

        Args:
            packet: 검증된 패킷 데이터
        """
        LOGGER.debug("패킷 수신: raw=%s", packet.hex())
        self._dispatch_packet(packet)

    def _dispatch_packet(self, packet: bytes) -> None:
        """패킷 분석 및 기기 상태 핸들러 분배."""
        frame = PacketFrame(packet)
        if self._checksum(packet[2:18]) != frame.checksum:
            LOGGER.debug("패킷 체크섬 오류. raw=%s", frame.raw.hex())
            return

        dev_state = None
        if frame.dev_type == DeviceType.LIGHT:
            if frame.dev_room == 0xFF:
                dev_state = self._handle_cutoff_switch(frame)
            else:
                dev_state = self._handle_switch(frame)
        elif frame.dev_type == DeviceType.OUTLET:
            dev_state = self._handle_switch(frame)
        elif frame.dev_type == DeviceType.THERMOSTAT:
            dev_state = self._handle_thermostat(frame)
        elif frame.dev_type == DeviceType.AIRCONDITIONER:
            dev_state = self._handle_airconditioner(frame)
        elif frame.dev_type == DeviceType.VENTILATION:
            dev_state = self._handle_ventilation(frame)
        elif frame.dev_type == DeviceType.GASVALVE:
            dev_state = self._handle_gasvalve(frame)
        elif frame.dev_type == DeviceType.ELEVATOR:
            dev_state = self._handle_elevator(frame)
        elif frame.dev_type == DeviceType.MOTION:
            dev_state = self._handle_motion(frame)
        elif frame.dev_type == DeviceType.AIRQUALITY:
            dev_state = self._handle_airquality(frame)
        else:
            LOGGER.debug("처리되지 않은 기기 타입: %s (raw=%s)", frame.dev_type.name, frame.raw.hex())
            return

        if not dev_state:
            return

        if isinstance(dev_state, list):
            for state in dev_state:
                state._packet = packet
                self.gateway.on_device_state(state)
        else:
            dev_state._packet = packet
            self.gateway.on_device_state(dev_state)
            
    def _handle_cutoff_switch(self, frame: PacketFrame) -> DeviceState:
        """일괄 소등 스위치 핸들러."""
        if frame.command in (0x65, 0x66):
            key = DeviceKey(
                device_type=frame.dev_type,
                room_index=0,
                device_index=0,
                sub_type=SubType.NONE,
            )
            state = frame.command == 0x65
            dev = DeviceState(key=key, platform=Platform.LIGHT, attribute={}, state=state)
            return dev

    def _handle_switch(self, frame: PacketFrame) -> List[DeviceState]:
        """조명 및 콘센트 핸들러."""
        states: List[DeviceState] = []
        if frame.command == 0x00:
            for idx in range(8):
                key = DeviceKey(
                    device_type=frame.dev_type,
                    room_index=frame.dev_room,
                    device_index=idx,
                    sub_type=SubType.NONE,
                )
                platform = Platform.LIGHT if frame.dev_type == DeviceType.LIGHT else Platform.SWITCH      
                attribute = {}
                if platform == Platform.SWITCH:
                    attribute = {"device_class": SwitchDeviceClass.OUTLET}
                state = frame.payload[idx] == 0xFF        
                dev = DeviceState(key=key, platform=platform, attribute=attribute, state=state)
                if state:
                    dev._is_register = True
                else:
                    dev._is_register = False
                states.append(dev)
            return states

    def _handle_thermostat(self, frame: PacketFrame) -> List[DeviceState]:
        """난방기 핸들러 (데이터 타당성 검사 포함)."""
        states: List[DeviceState] = []
        if frame.command == 0x00:
            key = DeviceKey(
                device_type=frame.dev_type,
                room_index=frame.dev_room,
                device_index=0,
                sub_type=SubType.NONE,
            )
            havc_mode = HVACMode.HEAT if frame.payload[0] >> 4 == 0x01 else HVACMode.OFF
            preset_mode = PRESET_AWAY if frame.payload[1] & 0x0F == 0x01 else PRESET_NONE

            # 데이터 타당성 검사 (Sanity Check)
            raw_target = frame.payload[2]
            raw_current = frame.payload[4]

            target_temp = float(raw_target)
            current_temp = float(raw_current)

            # 유효 범위 확인 (0도 ~ 50도), 0xFF 등 잘못된 값 필터링
            if raw_target == 0xFF or not (0 <= target_temp <= 50):
                 target_temp = 0.0
            if raw_current == 0xFF or not (0 <= current_temp <= 50):
                 current_temp = 0.0

            hot_temp = frame.payload[3]
            heat_temp = frame.payload[5]
            error_code = frame.payload[6]

            attribute = {
                "hvac_modes": [HVACMode.HEAT, HVACMode.OFF],
                "feature_preset": True,
                "preset_modes": [PRESET_AWAY, PRESET_NONE],
                "temp_step": self._device_storage.get(f"{key.unique_id}_thermo_step", 1.0),
            }
            state = {
                "hvac_mode": havc_mode,
                "preset_mode": preset_mode,
                "target_temp": self._device_storage.get(f"{key.unique_id}_thermo_target", target_temp),
                "current_temp": self._device_storage.get(f"{key.unique_id}_thermo_current", current_temp),
            }

            # 0.5도 단위 감지 로직
            if target_temp % 1 == 0.5 and self._device_storage.get(f"{key.unique_id}_thermo_step") != 0.5:
                LOGGER.debug("0.5도 단위 난방 제어 감지.")
                self._device_storage[f"{key.unique_id}_thermo_step"] = 0.5

            if target_temp != 0 and current_temp != 0:
                if havc_mode == HVACMode.HEAT and self._device_storage.get(f"{key.unique_id}_thermo_target") != target_temp:
                    LOGGER.debug(f"사용자 설정 온도 업데이트: {target_temp}")
                    self._device_storage[f"{key.unique_id}_thermo_target"] = target_temp
                self._device_storage[f"{key.unique_id}_thermo_current"] = current_temp

            dev = DeviceState(key=key, platform=Platform.CLIMATE, attribute=attribute, state=state)
            states.append(dev)
            
            # 온수 온도 센서
            key = DeviceKey(
                device_type=frame.dev_type,
                room_index=frame.dev_room,
                device_index=0,
                sub_type=SubType.HOTTEMP,
            )
            attribute = {
                "device_class": SensorDeviceClass.TEMPERATURE,
                "unit_of_measurement": UnitOfTemperature.CELSIUS
            }
            if 0 < hot_temp <= 80: # 온수 유효 범위 체크 (대략 80도 이하)
                dev = DeviceState(key=key, platform=Platform.SENSOR, attribute=attribute, state=hot_temp)
                states.append(dev)
            
            # 난방수 온도 센서
            key = DeviceKey(
                device_type=frame.dev_type,
                room_index=frame.dev_room,
                device_index=0,
                sub_type=SubType.HEATTEMP,
            )
            attribute = {
                "device_class": SensorDeviceClass.TEMPERATURE,
                "unit_of_measurement": UnitOfTemperature.CELSIUS
            }
            if 0 < heat_temp <= 80:
                dev = DeviceState(key=key, platform=Platform.SENSOR, attribute=attribute, state=heat_temp)
                states.append(dev)
            
            # 에러 코드 센서
            key = DeviceKey(
                device_type=frame.dev_type,
                room_index=frame.dev_room,
                device_index=0,
                sub_type=SubType.ERRCODE,
            )
            attribute = {
                "extra_state": {
                    "error_code": f"{error_code:02}"
                },
                "device_class": BinarySensorDeviceClass.PROBLEM
            }
            state = error_code != 0x00
            dev = DeviceState(key=key, platform=Platform.BINARY_SENSOR, attribute=attribute, state=state)
            states.append(dev)
            return states
        
    def _handle_airconditioner(self, frame: PacketFrame) -> DeviceState:
        """에어컨 핸들러 (데이터 타당성 검사 포함)."""
        if frame.command == 0x00:
            key = DeviceKey(
                device_type=frame.dev_type,
                room_index=frame.dev_room,
                device_index=0,
                sub_type=SubType.NONE,
            )
            if frame.payload[0] == 0x10:
                havc_mode = AIRCONDITIONER_HVAC_MAP.get(frame.payload[1], HVACMode.OFF) 
            else:
                havc_mode = HVACMode.OFF
            fan_mode = AIRCONDITIONER_FAN_MAP.get(frame.payload[2], FAN_LOW)

            # 데이터 타당성 검사
            raw_current = frame.payload[4]
            raw_target = frame.payload[5]

            current_temp = float(raw_current)
            target_temp = float(raw_target)

            if raw_current == 0xFF or not (0 <= current_temp <= 50):
                current_temp = 0.0
            if raw_target == 0xFF or not (0 <= target_temp <= 50):
                target_temp = 0.0

            attribute = {
                "hvac_modes": [*AIRCONDITIONER_HVAC_MAP.values(), HVACMode.OFF],
                "fan_modes": [*AIRCONDITIONER_FAN_MAP.values()],
                "feature_fan": True,
                "temp_step": 1.0,
            }
            state = {
                "hvac_mode": havc_mode,
                "fan_mode": fan_mode,
                "current_temp": current_temp,
                "target_temp": target_temp,
            }
            dev = DeviceState(key=key, platform=Platform.CLIMATE, attribute=attribute, state=state)
            return dev
    
    def _handle_ventilation(self, frame: PacketFrame) -> List[DeviceState]:
        """환기 장치 핸들러."""
        states: List[DeviceState] = []
        if frame.command == 0x00:
            key = DeviceKey(
                device_type=frame.dev_type,
                room_index=frame.dev_room,
                device_index=0,
                sub_type=SubType.NONE,
            )
            state = frame.payload[0] >> 4 == 0x01
            preset_mode = VENTILATION_PRESET_MAP.get(frame.payload[1], "unknown")
            speed = frame.payload[2]
            co2_value = (frame.payload[4] * 100) + frame.payload[5]
            error_code = frame.payload[6]

            attribute = {
                "feature_preset": self._device_storage.get("ventil_feature", False),
                "preset_modes": self._device_storage.get("ventil_modes", []),
                "speed_list": [0x40, 0x80, 0xC0]
            }
            state = {
                "state": state,
                "preset_mode": preset_mode,
                "speed": speed,
            }
            if preset_mode != "unknown" and preset_mode != "ventilation":
                if self._device_storage.get("ventil_modes") is None:
                    LOGGER.debug("새로운 환기 프리셋 감지 (기본값 제외).")
                    self._device_storage["ventil_feature"] = True
                    self._device_storage["ventil_modes"] = ["ventilation"]
                if preset_mode not in self._device_storage["ventil_modes"]:
                    LOGGER.debug(f"프리셋 추가됨: {preset_mode}")
                    self._device_storage["ventil_modes"].append(preset_mode)
            dev = DeviceState(key=key, platform=Platform.FAN, attribute=attribute, state=state)
            states.append(dev)
            
            key = DeviceKey(
                device_type=frame.dev_type,
                room_index=frame.dev_room,
                device_index=0,
                sub_type=SubType.CO2,
            )
            attribute = {
                "device_class": SensorDeviceClass.CO2,
                "unit_of_measurement": "ppm"
            }
            if co2_value > 0 and co2_value < 5000: # CO2 유효 범위 체크 (일반적으로 0-5000ppm)
                dev = DeviceState(key=key, platform=Platform.SENSOR, attribute=attribute, state=co2_value)
                states.append(dev)
            
            key = DeviceKey(
                device_type=frame.dev_type,
                room_index=frame.dev_room,
                device_index=0,
                sub_type=SubType.ERRCODE,
            )
            attribute = {
                "extra_state": {
                    "error_code": f"{error_code:02}"
                },
                "device_class": BinarySensorDeviceClass.PROBLEM
            }
            state = error_code != 0x00
            dev = DeviceState(key=key, platform=Platform.BINARY_SENSOR, attribute=attribute, state=state)
            states.append(dev)
            return states

    def _handle_gasvalve(self, frame: PacketFrame) -> DeviceState:
        """가스 밸브 핸들러."""
        if frame.command in (0x01, 0x02):
            key = DeviceKey(
                device_type=frame.dev_type,
                room_index=frame.dev_room,
                device_index=0,
                sub_type=SubType.NONE,
            )
            state = frame.command == 0x01
            dev = DeviceState(key=key, platform=Platform.SWITCH, attribute={}, state=state)
            return dev

    def _handle_elevator(self, frame: PacketFrame) -> List[DeviceState]:    
        """엘리베이터 핸들러."""
        states: List[DeviceState] = []
        key = DeviceKey(
            device_type=frame.dev_type,
            room_index=frame.dev_room,
            device_index=0,
            sub_type=SubType.NONE,
        )
        state = False
        if frame.payload[0] == 0x03:
            state = False
        elif frame.payload[0] in (0x01, 0x02) or frame.packet_type == 0x0D:
            state = True
        dev = DeviceState(key=key, platform=Platform.SWITCH, attribute={}, state=state)
        states.append(dev)

        key = DeviceKey(
            device_type=frame.dev_type,
            room_index=frame.dev_room,
            device_index=0,
            sub_type=SubType.DIRECTION,
        )
        state = ""
        if frame.payload[0] == 0x00 and frame.packet_type == 0x0D:
            state = "called"
        else:
            state = ELEVATOR_DIRECTION_MAP.get(frame.payload[0], "unknown")
        dev = DeviceState(key=key, platform=Platform.SENSOR, attribute={}, state=state)
        states.append(dev)
        
        key = DeviceKey(
            device_type=frame.dev_type,
            room_index=frame.dev_room,
            device_index=0,
            sub_type=SubType.FLOOR,
        )
        state = ""
        if frame.payload[1] == 0x00:
            state = "unknown"
        else:
            if frame.payload[2] != 0x00:
                state = f"{chr(frame.payload[1])}{chr(frame.payload[2])}"
            else:
                if frame.payload[1] >> 4 == 0x08:
                    state = f"B{str(frame.payload[1] & 0x0F)}"
                else:
                    state = str(frame.payload[1])
        if state != "" and state != "unknown":
            self._device_storage["available_floor"] = True
        if self._device_storage.get("available_floor", False):
            dev = DeviceState(key=key, platform=Platform.SENSOR, attribute={}, state=state)
            states.append(dev)
        return states
    
    def _handle_motion(self, frame: PacketFrame) -> DeviceState:
        """모션 센서 핸들러."""
        if frame.command in (0x00, 0x04):
            key = DeviceKey(
                device_type=frame.dev_type,
                room_index=frame.dev_room,
                device_index=0,
                sub_type=SubType.NONE,
            )
            attribute = {
                "device_class": BinarySensorDeviceClass.MOTION
            }
            state = frame.command == 0x04
            dev = DeviceState(key=key, platform=Platform.BINARY_SENSOR, attribute=attribute, state=state)
            return dev
        
    def _handle_airquality(self, frame: PacketFrame) -> List[DeviceState]:
        """공기질 센서 핸들러."""
        states: List[DeviceState] = []
        if frame.command in (0x00, 0x3A):
            data_mapping = {
                SubType.PM10: (SensorDeviceClass.PM10, "µg/m³", frame.payload[0]),
                SubType.PM25: (SensorDeviceClass.PM25, "µg/m³", frame.payload[1]),
                SubType.CO2: (SensorDeviceClass.CO2, "ppm", int.from_bytes(frame.payload[2:4], 'big')),
                SubType.VOC: (SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS, "µg/m³", int.from_bytes(frame.payload[4:6], 'big')),
                SubType.TEMP: (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, frame.payload[6]),
                SubType.HUMIDITY: (SensorDeviceClass.HUMIDITY, "%", frame.payload[7]),
            }
            for key, value in data_mapping.items():
                device_class, native_unit, state = value
                key = DeviceKey(
                    device_type=frame.dev_type,
                    room_index=frame.dev_room,
                    device_index=0,
                    sub_type=key,
                )
                attribute = {
                    "device_class": device_class,
                    "unit_of_measurement": native_unit
                }
                if state > 0:
                    dev = DeviceState(key=key, platform=Platform.SENSOR, attribute=attribute, state=state)
                    states.append(dev)
            return states
    
    def _match_key_and(self, key: DeviceKey, cond: Predicate) -> Predicate:
        """키 일치 및 조건 검사 함수 생성기."""
        def _inner(dev: DeviceState) -> bool:
            if dev.key.key != key.key:
                return False
            return cond(dev)
        return _inner

    def _expect_for_switch_like(self, key: DeviceKey, action: str, **kwargs: Any) -> Tuple[Predicate, float]:
        """스위치류 기기 응답 기대 조건."""
        def _on(dev: DeviceState) -> bool:  return bool(dev.state) is True
        def _off(dev: DeviceState) -> bool: return bool(dev.state) is False

        if action == "turn_on":
            return self._match_key_and(key, _on), CMD_CONFIRM_TIMEOUT
        if action == "turn_off":
            return self._match_key_and(key, _off), CMD_CONFIRM_TIMEOUT
        return self._match_key_and(key, lambda _d: False), CMD_CONFIRM_TIMEOUT

    def _expect_for_ventilation(self, key: DeviceKey, action: str, **kwargs: Any) -> Tuple[Predicate, float]:
        """환기 장치 응답 기대 조건."""
        def is_on(d: DeviceState) -> bool:
            return isinstance(d.state, dict) and d.state.get("state") is True
        def is_off(d: DeviceState) -> bool:
            return isinstance(d.state, dict) and d.state.get("state") is False

        if action == "turn_on":
            return self._match_key_and(key, is_on), CMD_CONFIRM_TIMEOUT
        if action == "turn_off":
            return self._match_key_and(key, is_off), CMD_CONFIRM_TIMEOUT

        if action == "set_preset":
            pm = kwargs["preset_mode"]
            return self._match_key_and(key, lambda d: isinstance(d.state, dict) and d.state.get("preset_mode") == pm), CMD_CONFIRM_TIMEOUT
        if action == "set_percentage":
            speed = kwargs["speed"]
            return self._match_key_and(key, lambda d: isinstance(d.state, dict) and d.state.get("speed") == speed), CMD_CONFIRM_TIMEOUT

        return self._match_key_and(key, lambda _d: False), CMD_CONFIRM_TIMEOUT

    def _expect_for_gasvalve(self, key: DeviceKey, action: str, **kwargs: Any) -> Tuple[Predicate, float]:
        """가스 밸브 응답 기대 조건."""
        # 밸브는 동작이 느릴 수 있으니 기본 타임아웃 상향
        base_timeout = max(CMD_CONFIRM_TIMEOUT, 1.5)
        if action == "turn_on":
            return True, base_timeout
        if action == "turn_off":
            return self._match_key_and(key, lambda d: bool(d.state) is False), base_timeout
        return self._match_key_and(key, lambda _d: False), base_timeout

    def _expect_for_thermostat(self, key: DeviceKey, action: str, **kwargs: Any) -> Tuple[Predicate, float]:
        """난방기 응답 기대 조건."""
        if action == "set_hvac":
            hm = kwargs["hvac_mode"]
            return self._match_key_and(key, lambda d: isinstance(d.state, dict) and d.state.get("hvac_mode") == hm), CMD_CONFIRM_TIMEOUT
        if action == "set_preset":
            pm = kwargs["preset_mode"]
            return self._match_key_and(key, lambda d: isinstance(d.state, dict) and d.state.get("preset_mode") == pm), CMD_CONFIRM_TIMEOUT
        if action == "set_temperature":
            tt = kwargs["target_temp"]
            return self._match_key_and(key, lambda d: isinstance(d.state, dict) and d.state.get("target_temp") == tt), max(CMD_CONFIRM_TIMEOUT, 1.5)
        if action == "turn_on":
            return self._match_key_and(key, lambda d: isinstance(d.state, dict) and d.state.get("state") is True), CMD_CONFIRM_TIMEOUT
        if action == "turn_off":
            return self._match_key_and(key, lambda d: isinstance(d.state, dict) and d.state.get("state") is False), CMD_CONFIRM_TIMEOUT
        return self._match_key_and(key, lambda _d: False), CMD_CONFIRM_TIMEOUT
    
    def _expect_for_airconditioner(self, key: DeviceKey, action: str, **kwargs: Any) -> Tuple[Predicate, float]:
        """에어컨 응답 기대 조건."""
        if action == "set_hvac":
            hm = kwargs["hvac_mode"]
            return self._match_key_and(key, lambda d: isinstance(d.state, dict) and d.state.get("hvac_mode") == hm), CMD_CONFIRM_TIMEOUT
        if action == "set_fan":
            fm = kwargs["fan_mode"]
            return self._match_key_and(key, lambda d: isinstance(d.state, dict) and d.state.get("fan_mode") == fm), CMD_CONFIRM_TIMEOUT
        if action == "set_preset":
            pm = kwargs["preset_mode"]
            return self._match_key_and(key, lambda d: isinstance(d.state, dict) and d.state.get("preset_mode") == pm), CMD_CONFIRM_TIMEOUT
        if action == "set_temperature":
            tt = kwargs["target_temp"]
            return self._match_key_and(key, lambda d: isinstance(d.state, dict) and d.state.get("target_temp") == tt), max(CMD_CONFIRM_TIMEOUT, 1.5)
        if action == "turn_on":
            return self._match_key_and(key, lambda d: isinstance(d.state, dict) and d.state.get("state") is True), CMD_CONFIRM_TIMEOUT
        if action == "turn_off":
            return self._match_key_and(key, lambda d: isinstance(d.state, dict) and d.state.get("state") is False), CMD_CONFIRM_TIMEOUT
        return self._match_key_and(key, lambda _d: False), CMD_CONFIRM_TIMEOUT

    def build_expectation(self, key: DeviceKey, action: str, **kwargs: Any) -> Tuple[Predicate, float]:
        """기기별 명령 실행 후 기대 상태 생성."""
        dt = key.device_type
        if dt in (DeviceType.LIGHT, DeviceType.LIGHTCUTOFF, DeviceType.OUTLET, DeviceType.ELEVATOR):
            return self._expect_for_switch_like(key, action, **kwargs)
        if dt == DeviceType.VENTILATION:
            return self._expect_for_ventilation(key, action, **kwargs)
        if dt == DeviceType.GASVALVE:
            return self._expect_for_gasvalve(key, action, **kwargs)
        if dt == DeviceType.THERMOSTAT:
            return self._expect_for_thermostat(key, action, **kwargs)
        if dt == DeviceType.AIRCONDITIONER:
            return self._expect_for_airconditioner(key, action, **kwargs)            
        return self._match_key_and(key, lambda _d: False), CMD_CONFIRM_TIMEOUT

    def generate_command(self, key: DeviceKey, action: str, **kwargs) -> Tuple[bytes, Predicate, float]:
        """기기 제어 명령 패킷 생성.

        Args:
            key: 대상 기기 키
            action: 수행할 동작 (예: turn_on, set_temperature)
            **kwargs: 동작 파라미터

        Returns:
            (패킷 bytes, 기대 조건 함수, 타임아웃)

        Raises:
            ValueError: 잘못된 기기 타입인 경우
        """
        device_type = key.device_type
        room_index = key.room_index

        if device_type not in REV_DT_MAP:
            raise ValueError(f"Invalid device type: {device_type}")

        type_bytes = bytes([0x30, 0xBC])
        padding = bytes([0x00])
        dest_dev = bytes([REV_DT_MAP[device_type]])
        dest_room = bytes([room_index & 0xFF])
        src_dev = bytes([0x01])
        src_room = bytes([0x00])
        command = bytes([0x00])
        data = bytearray(8)

        if device_type in (DeviceType.LIGHT, DeviceType.OUTLET):
            data = self._generate_switch(key, action, data)
        elif device_type == DeviceType.VENTILATION:
            data = self._generate_ventilation(action, data, **kwargs)
        elif device_type == DeviceType.THERMOSTAT:
            data = self._generate_thermostat(action, data, **kwargs)
        elif device_type == DeviceType.AIRCONDITIONER:
            data = self._generate_airconditioner(action, data, **kwargs)
        elif device_type == DeviceType.GASVALVE:
            command = bytes([0x02])
        elif device_type == DeviceType.ELEVATOR:
            dest_dev = bytes([0x01])
            dest_room = bytes([0x00])
            src_dev = bytes([0x44])
            src_room = bytes([room_index & 0xFF])
            command = bytes([0x01])
        else:
            raise ValueError(f"Invalid device generator: {device_type}")

        body = b"".join([type_bytes, padding, dest_dev, dest_room, src_dev, src_room, command, bytes(data)])
        checksum = bytes([self._checksum(body)])
        packet = PACKET_PREFIX + body + checksum + PACKET_SUFFIX

        expect, timeout = self.build_expectation(key, action, **kwargs)
        return packet, expect, timeout

    def _generate_switch(self, key: DeviceKey, action: str, data: bytes) -> bytes:
        """스위치 패킷 데이터 생성."""
        for idx in range(8):
            new_key = replace(key, device_index=idx)
            st = self.gateway.registry.get(new_key)
            if idx != key.device_index:
                bit = 0xFF if (st and st.state is True) else 0x00
                data[idx] = bit
            else:
                data[idx] = 0xFF if action == "turn_on" else 0x00
        return data

    def _generate_ventilation(self, action: str, data: bytes, **kwargs: Any) -> bytes:
        """환기 장치 패킷 데이터 생성."""
        if action == "set_preset":
            pm = kwargs["preset_mode"]
            data[0] = 0x11
            data[1] = REV_VENT_PRESET_MAP[pm]
        elif action == "set_percentage":
            speed = kwargs["speed"]
            data[0] = 0x00 if speed == 0 else 0x11
            data[2] = speed
        else:
            data[0] = 0x11 if action == "turn_on" else 0x00
        return data
    
    def _generate_thermostat(self, action: str, data: bytes, **kwargs: Any) -> bytes:
        """난방기 패킷 데이터 생성."""
        if action == "set_hvac":
            hm = kwargs["hvac_mode"]
            data[0] = 0x11 if hm == HVACMode.HEAT else 0x00
            data[1] = 0x00
        elif action == "set_preset":
            pm = kwargs["preset_mode"]
            data[0] = 0x11
            data[1] = 0x01 if pm == PRESET_AWAY else 0x00
        elif action == "set_temperature":
            tt = kwargs["target_temp"]
            data[0] = 0x11
            data[2] = int(tt)
        return data
    
    def _generate_airconditioner(self, action: str, data: bytes, **kwargs: Any) -> bytes:
        """에어컨 패킷 데이터 생성."""
        if action == "set_hvac":
            hm = kwargs["hvac_mode"]
            if hm == HVACMode.OFF:
                data[0] = 0x00
            else:
                data[0] = 0x10
                data[1] = REV_AC_HVAC_MAP[hm]
        elif action == "set_fan":
            fm = kwargs["fan_mode"]
            data[0] = 0x10
            data[2] = REV_AC_FAN_MAP[fm]
        elif action == "set_temperature":
            tt = kwargs["target_temp"]
            data[0] = 0x10
            data[5] = int(tt)
        return data
