"""코콤 월패드 이진 센서 플랫폼 (Binary Sensor Platform)."""

from __future__ import annotations

from typing import Any, List

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass
)

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .gateway import KocomGateway
from .models import DeviceState
from .entity_base import KocomBaseEntity
from .const import DOMAIN, LOGGER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """코콤 이진 센서 플랫폼 설정."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]

    @callback
    def async_add_binary_sensor(devices=None):
        """이진 센서 엔티티 추가."""
        if devices is None:
            devices = gateway.get_devices_from_platform(Platform.BINARY_SENSOR)

        entities: List[KocomBinarySensor] = []
        for dev in devices:
            entity = KocomBinarySensor(gateway, dev)
            entities.append(entity)
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(Platform.BINARY_SENSOR), async_add_binary_sensor
        )
    )
    async_add_binary_sensor()
    

class KocomBinarySensor(KocomBaseEntity, BinarySensorEntity):
    """코콤 이진 센서 엔티티."""

    def __init__(self, gateway: KocomGateway, device: DeviceState) -> None:
        """이진 센서 초기화."""
        super().__init__(gateway, device)

    @property
    def is_on(self) -> bool:
        """켜짐 여부 반환."""
        return self._device.state
    
    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        """기기 클래스 반환."""
        return self._device.attribute.get("device_class", None)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """추가 상태 속성 반환."""
        return self._device.attribute.get("extra_state", None)
