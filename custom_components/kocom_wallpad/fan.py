"""코콤 월패드 팬 플랫폼 (Fan Platform)."""

from __future__ import annotations

from typing import Any, Optional, List

from homeassistant.components.fan import FanEntity, FanEntityFeature

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .gateway import KocomGateway
from .models import DeviceState
from .entity_base import KocomBaseEntity
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """코콤 팬 플랫폼 설정."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]

    @callback
    def async_add_fan(devices=None):
        """팬 엔티티 추가."""
        if devices is None:
            devices = gateway.get_devices_from_platform(Platform.FAN)

        entities: List[KocomFan] = []
        for dev in devices:
            entity = KocomFan(gateway, dev)
            entities.append(entity)
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(Platform.FAN), async_add_fan
        )
    )
    async_add_fan()


class KocomFan(KocomBaseEntity, FanEntity):
    """코콤 팬(환기장치) 엔티티."""

    def __init__(self, gateway: KocomGateway, device: DeviceState) -> None:
        """팬 초기화."""
        super().__init__(gateway, device)
        self._attr_supported_features = (
            FanEntityFeature.SET_SPEED |
            FanEntityFeature.TURN_OFF |
            FanEntityFeature.TURN_ON
        )
        if device.attribute["feature_preset"]:
            self._attr_supported_features |= FanEntityFeature.PRESET_MODE

    @property
    def is_on(self) -> bool:
        """켜짐 여부 반환."""
        return self._device.state["state"]
    
    @property
    def speed_count(self) -> int:
        """속도 단계 수 반환."""
        return len(self._device.attribute["speed_list"])

    @property
    def percentage(self) -> int:
        """현재 속도 백분율 반환."""
        if not self._device.state["state"] or self._device.state["speed"] == 0:
            return 0
        return ordered_list_item_to_percentage(self._device.attribute["speed_list"], self._device.state["speed"])
    
    @property
    def preset_mode(self) -> str:
        """현재 프리셋 모드 반환."""
        return self._device.state["preset_mode"]
    
    @property
    def preset_modes(self) -> List[str]:
        """지원 가능한 프리셋 모드 목록 반환."""
        return self._device.attribute["preset_modes"]

    async def async_set_percentage(self, percentage: int) -> None:
        """속도 백분율 설정."""
        args = {"speed": 0}
        if percentage > 0:
            args["speed"] = percentage_to_ordered_list_item(self._device.attribute["speed_list"], percentage)
        await self.gateway.async_send_action(self._device.key, "set_percentage", **args)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """프리셋 모드 설정."""
        args = {"preset_mode": preset_mode}
        await self.gateway.async_send_action(self._device.key, "set_preset", **args)

    async def async_turn_on(
        self,
        speed: Optional[str] = None,
        percentage: Optional[int] = None,
        preset_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """팬 켜기."""
        await self.gateway.async_send_action(self._device.key, "turn_on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """팬 끄기."""
        await self.gateway.async_send_action(self._device.key, "turn_off")
        