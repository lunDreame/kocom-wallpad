"""코콤 월패드 컴포넌트 설정 (Component Setup)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.const import CONF_HOST, CONF_PORT, EVENT_HOMEASSISTANT_STOP

from .const import DOMAIN, PLATFORMS
from .gateway import KocomGateway


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config Entry를 사용하여 코콤 월패드 설정."""
    host: str = entry.data[CONF_HOST]
    port: int = entry.data[CONF_PORT]

    gateway = KocomGateway(hass, entry, host=host, port=port)
    await gateway.async_get_entity_registry()
    await gateway.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = gateway

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, gateway.async_stop)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 디버그 서비스 등록 (최초 1회)
    if not hass.services.has_service(DOMAIN, "send_raw_command"):
        async def handle_send_raw_command(call: ServiceCall) -> None:
            """Raw 패킷 전송 서비스 핸들러."""
            packet = call.data.get("packet")
            # 등록된 모든 게이트웨이에 전송
            for gw in hass.data.get(DOMAIN, {}).values():
                await gw.send_raw_packet(packet)

        hass.services.async_register(DOMAIN, "send_raw_command", handle_send_raw_command)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config Entry 언로드."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        gateway: KocomGateway = hass.data[DOMAIN].pop(entry.entry_id)
        await gateway.async_stop()
    return unload_ok
