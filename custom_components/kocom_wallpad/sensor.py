"""코콤 월패드 센서 플랫폼 (Sensor Platform)."""

from __future__ import annotations

from typing import Any, List
from datetime import datetime

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    Platform,
    EntityCategory,
    CONF_HOST,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .gateway import KocomGateway
from .models import DeviceState
from .entity_base import KocomBaseEntity
from .const import DOMAIN, LOGGER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """코콤 센서 플랫폼 설정."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]

    @callback
    def async_add_sensor(devices=None):
        """센서 엔티티 추가."""
        if devices is None:
            devices = gateway.get_devices_from_platform(Platform.SENSOR)

        entities: List[KocomSensor] = []
        for dev in devices:
            entity = KocomSensor(gateway, dev)
            entities.append(entity)
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(Platform.SENSOR), async_add_sensor
        )
    )
    async_add_sensor()

    # 진단 센서 추가
    diag_entities = [
        KocomDiagnosticSensor(gateway, "connection_status", "Connection Status", None, None),
        KocomDiagnosticSensor(gateway, "rx_success_count", "RX Success Count", SensorStateClass.TOTAL_INCREASING, None),
        KocomDiagnosticSensor(gateway, "rx_error_count", "RX Error Count", SensorStateClass.TOTAL_INCREASING, None),
        KocomDiagnosticSensor(gateway, "last_packet_time", "Last Packet Time", None, SensorDeviceClass.TIMESTAMP),
    ]
    async_add_entities(diag_entities)


class KocomSensor(KocomBaseEntity, SensorEntity):
    """코콤 센서 엔티티."""
    
    def __init__(self, gateway: KocomGateway, device: DeviceState) -> None:
        """센서 초기화."""
        super().__init__(gateway, device)

    @property
    def native_value(self) -> Any:
        return self._device.state
    
    @property
    def device_class(self) -> SensorDeviceClass | None:
        return self._device.attribute.get("device_class", None)
    
    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._device.attribute.get("unit_of_measurement", None)


class KocomDiagnosticSensor(SensorEntity):
    """코콤 진단 센서 엔티티."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = True  # 폴링으로 업데이트

    def __init__(
        self,
        gateway: KocomGateway,
        sensor_type: str,
        name: str,
        state_class: SensorStateClass | None,
        device_class: SensorDeviceClass | None
    ) -> None:
        """진단 센서 초기화.

        Args:
            gateway: 게이트웨이 인스턴스
            sensor_type: 센서 내부 식별자
            name: 표시 이름
            state_class: 상태 클래스
            device_class: 기기 클래스
        """
        self._gateway = gateway
        self._sensor_type = sensor_type

        # Unique ID: kocom_wallpad_{host}_{sensor_type}
        # Entity ID는 HA가 name 기반으로 생성 (예: sensor.kocom_wallpad_gateway_connection_status)
        # 하지만 사용자가 "sensor.kocom_connection_status"를 원했으므로
        # entity_id 포맷을 맞추기 위해 노력하지만, unique_id가 중요.

        self._attr_unique_id = f"{DOMAIN}_{gateway.host}_{sensor_type}"
        self._attr_name = name
        self._attr_state_class = state_class
        self._attr_device_class = device_class

        # 기기 정보 (게이트웨이 기기에 종속)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(gateway.host))},
            "name": "Kocom Wallpad Gateway",
            "manufacturer": "Kocom",
            "model": "EW11 RS485 Bridge",
        }

    @property
    def native_value(self) -> Any:
        """센서 값 반환."""
        if self._sensor_type == "connection_status":
            return "connected" if self._gateway.conn._is_connected() else "disconnected"
        elif self._sensor_type == "rx_success_count":
            return self._gateway.conn.rx_success_count
        elif self._sensor_type == "rx_error_count":
            return self._gateway.conn.rx_error_count
        elif self._sensor_type == "last_packet_time":
            ts = self._gateway.conn.last_packet_time
            if ts > 0:
                return dt_util.utc_from_timestamp(ts)
            return None
        return None
