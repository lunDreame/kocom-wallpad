"""Base platform for Kocom Wallpad."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity, RestoredExtraData
from homeassistant.core import callback
from homeassistant.const import Platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.components.light import LightEntityDescription
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.components.climate import ClimateEntityDescription
from homeassistant.components.fan import FanEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.components.binary_sensor import BinarySensorEntityDescription

from .const import DOMAIN, DeviceType, SubType


ENTITY_DESCRIPTION_MAP = {
    Platform.LIGHT: LightEntityDescription,
    Platform.SWITCH: SwitchEntityDescription,
    Platform.CLIMATE: ClimateEntityDescription,
    Platform.FAN: FanEntityDescription,
    Platform.SENSOR: SensorEntityDescription,
    Platform.BINARY_SENSOR: BinarySensorEntityDescription
}


class KocomBaseEntity(RestoreEntity):
    """Base class for Kocom entities."""

    def __init__(self, gateway, device) -> None:
        """Initialize the base entity."""
        super().__init__()
        self.gateway = gateway
        self._device = device
        self._unsubs: list[callable] = []

        self._attr_unique_id = f"{device.key.unique_id}:{self.gateway.host}"
        self.entity_description = ENTITY_DESCRIPTION_MAP[self._device.platform](
            key=self.format_key,
            has_entity_name=True,
            translation_key=self.format_key,
            translation_placeholders={"id": self.format_translation_placeholders}
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{self.format_identifiers}")},
            manufacturer="KOCOM Co., Ltd",
            model="Smart Wallpad",
            name=f"{self.format_identifiers}",
            via_device=(DOMAIN, str(self.gateway.host)),
        )
        
    @property
    def format_key(self) -> str:
        if self._device.key.sub_type == SubType.NONE:
            return self._device.key.device_type.name.lower()
        else:
            return f"{self._device.key.device_type.name.lower()}-{self._device.key.sub_type.name.lower()}"

    @property
    def format_translation_placeholders(self) -> str:
        if self._device.key.sub_type == SubType.NONE:
            return f"{str(self._device.key.room_index)}-{str(self._device.key.device_index)}"
        else:
            return f"{str(self._device.key.room_index)}-{str(self._device.key.device_index)}"

    @property
    def format_identifiers(self) -> str:
        if self._device.key.device_type in {
            DeviceType.VENTILATION, DeviceType.GASVALVE, DeviceType.ELEVATOR, DeviceType.MOTION
        }:
            return f"KOCOM"
        elif self._device.key.device_type in {
            DeviceType.LIGHT, DeviceType.LIGHTCUTOFF, DeviceType.DIMMINGLIGHT
        }:
            return f"KOCOM LIGHT"
        else:
            return f"KOCOM {self._device.key.device_type.name}"

    async def async_added_to_hass(self):
        sig = self.gateway.async_signal_device_updated(self._device.key.unique_id)

        @callback
        def _handle_update(dev):
            self._device = dev
            self.update_from_state()
        self._unsubs.append(async_dispatcher_connect(self.hass, sig, _handle_update))

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:
                pass
        self._unsubs.clear()

    @callback
    def update_from_state(self) -> None:
        self.async_write_ha_state()

    @property
    def extra_restore_state_data(self) -> RestoredExtraData:
        return RestoredExtraData({
            "packet": getattr(self._device, "_packet", bytes()).hex(),
            "device_storage": self.gateway.controller._device_storage
        })
