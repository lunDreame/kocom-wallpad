"""코콤 월패드 냉난방 플랫폼 (Climate Platform)."""

from __future__ import annotations

from typing import List

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACMode,
)

from homeassistant.const import Platform, UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .gateway import KocomGateway
from .models import DeviceState
from .entity_base import KocomBaseEntity
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """코콤 냉난방 플랫폼 설정."""
    gateway: KocomGateway = hass.data[DOMAIN][entry.entry_id]

    @callback
    def async_add_climate(devices=None):
        """냉난방 엔티티 추가."""
        if devices is None:
            devices = gateway.get_devices_from_platform(Platform.CLIMATE)

        entities: List[KocomClimate] = []
        for dev in devices:
            entity = KocomClimate(gateway, dev)
            entities.append(entity)
        if entities:
            async_add_entities(entities)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, gateway.async_signal_new_device(Platform.CLIMATE), async_add_climate
        )
    )
    async_add_climate()


class KocomClimate(KocomBaseEntity, ClimateEntity):
    """코콤 냉난방 기기 엔티티."""
    
    _enable_turn_on_off_backwards_compatibility = False

    _attr_min_temp = 5
    _attr_max_temp = 40
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, gateway: KocomGateway, device: DeviceState) -> None:
        """냉난방 기기 초기화."""
        super().__init__(gateway, device)
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE |
            ClimateEntityFeature.TURN_OFF |
            ClimateEntityFeature.TURN_ON
        )
        if device.attribute.get("feature_fan", False):
            self._attr_supported_features |= ClimateEntityFeature.FAN_MODE
        if device.attribute.get("feature_preset", False):
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE

    @property
    def hvac_mode(self) -> HVACMode:
        """현재 HVAC 모드 반환."""
        return self._device.state["hvac_mode"]
    
    @property
    def hvac_modes(self) -> List[HVACMode]:
        """지원 가능한 HVAC 모드 목록 반환."""
        return self._device.attribute["hvac_modes"]
    
    @property
    def fan_mode(self) -> str:
        """현재 팬 모드 반환."""
        return self._device.state["fan_mode"]
    
    @property
    def fan_modes(self) -> List[str]:
        """지원 가능한 팬 모드 목록 반환."""
        return self._device.attribute["fan_modes"]

    @property
    def preset_mode(self) -> str:
        """현재 프리셋 모드 반환."""
        return self._device.state["preset_mode"]
    
    @property
    def preset_modes(self) -> List[str]:
        """지원 가능한 프리셋 모드 목록 반환."""
        return self._device.attribute["preset_modes"]

    @property
    def current_temperature(self) -> float:
        """현재 온도 반환."""
        return self._device.state["current_temp"]

    @property
    def target_temperature(self) -> float:
        """목표 온도 반환."""
        return self._device.state["target_temp"]
    
    @property
    def target_temperature_step(self) -> float:
        """목표 온도 조절 단위 반환."""
        return self._device.attribute["temp_step"]
    
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """HVAC 모드 설정."""
        args = {"hvac_mode": hvac_mode}
        await self.gateway.async_send_action(self._device.key, "set_hvac", **args)
        
    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """팬 모드 설정."""
        args = {"fan_mode": fan_mode}
        await self.gateway.async_send_action(self._device.key, "set_fan", **args)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """프리셋 모드 설정."""
        args = {"preset_mode": preset_mode}
        await self.gateway.async_send_action(self._device.key, "set_preset", **args)

    async def async_set_temperature(self, **kwargs) -> None:
        """목표 온도 설정."""
        args = {"target_temp": float(kwargs[ATTR_TEMPERATURE])}
        await self.gateway.async_send_action(self._device.key, "set_temperature", **args)
