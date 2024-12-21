"""Switch Platform for Kocom Wallpad."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .pywallpad.const import POWER
from .pywallpad.enums import DeviceType
from .pywallpad.packet import KocomPacket, OutletPacket, GasPacket

from .gateway import KocomGateway
from .entity import KocomEntity
from .const import DOMAIN, LOGGER


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kocom switch platform."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]
    
    @callback
    def async_add_switch(packet: KocomPacket) -> None:
        """Add new switch entity."""
        if isinstance(packet, (OutletPacket, GasPacket)):
            async_add_entities([KocomSwitchEntity(gateway, packet)])
        else:
            LOGGER.warning(f"Unsupported packet type: {packet}")
    
    for entity in gateway.get_entities(Platform.SWITCH):
        async_add_switch(entity)
        
    entry.async_on_unload(
        async_dispatcher_connect(hass, f"{DOMAIN}_switch_add", async_add_switch)
    )


class KocomSwitchEntity(KocomEntity, SwitchEntity):
    """Representation of a Kocom switch."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    
    def __init__(
        self,
        gateway: KocomGateway,
        packet: KocomPacket,
    ) -> None:
        """Initialize the switch."""
        super().__init__(gateway, packet)

        if self.packet.device_type == DeviceType.OUTLET:
            self._attr_device_class = SwitchDeviceClass.OUTLET

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        return self.device.state[POWER]
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on switch."""
        packet = self.packet.make_status(power=True)
        await self.send(packet)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off switch."""
        packet = self.packet.make_status(power=False)
        await self.send(packet)