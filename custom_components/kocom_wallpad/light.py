"""Light platform for Kocom Wallpad."""

from __future__ import annotations

from typing import Any, List

from homeassistant.components.light import LightEntity, ColorMode, ATTR_BRIGHTNESS

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
    async_add_entities: AddEntitiesCallback
) -> bool:
    """Set up Kocom light platform."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]

    @callback
    def async_add_light(devices=None):
        """Add light entities."""
        if devices is None:
            devices = gateway.get_devices_from_platform(Platform.LIGHT)

        entities: List[KocomLight] = []
        for dev in devices:
            entity = KocomLight(gateway, dev)
            entities.append(entity)
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(Platform.LIGHT), async_add_light
        )
    )
    async_add_light()


class KocomLight(KocomBaseEntity, LightEntity):
    """Representation of a Kocom light."""

    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    def __init__(self, gateway: KocomGateway, device: DeviceState) -> None:
        """Initialize the light."""
        super().__init__(gateway, device)

    @property
    def is_on(self) -> bool:
        state = self._device.state
        if isinstance(state, dict):
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
            return state["state"]
        return state
    
    @property
    def brightness(self) -> int:
        level = self._device.state["level"]
        levels = self._device.state["levels"]
        if not self._device.state["state"]:
            return 0
        if levels and level in levels:
            index = levels.index(level) + 1
            brightness = round(index * 255 / len(levels))
        else:
            brightness = 0
        return brightness

    async def async_turn_on(self, **kwargs: Any) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
            levels = self._device.state["levels"]
            step_size = 255 / len(levels)
            index = round(brightness / step_size)
            index = min(max(index, 1), len(levels))
            level = levels[index - 1]
            args = {"brightness": level}
            await self.gateway.async_send_action(self._device.key, "set_brightness", **args)
        else:
            await self.gateway.async_send_action(self._device.key, "turn_on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.gateway.async_send_action(self._device.key, "turn_off")
