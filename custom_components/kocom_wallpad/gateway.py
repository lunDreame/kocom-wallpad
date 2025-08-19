"""Gateway for Kocom Wallpad."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Optional, Dict, Tuple, List, Callable

from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import entity_registry as er, restore_state
from homeassistant.const import Platform
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    LOGGER,
    DOMAIN,
    RECV_POLL_SEC,
    IDLE_GAP_SEC,
    SEND_RETRY_MAX,
    SEND_RETRY_GAP,
    DeviceType,
)
from .models import DeviceKey, DeviceState
from .transport import AsyncConnection
from .controller import KocomController


class _PendingWaiter:

    __slots__ = ("key", "predicate", "future")

    def __init__(
        self, 
        key: DeviceKey,
        predicate: Callable[[DeviceState], bool],
        loop: asyncio.AbstractEventLoop
    ) -> None:
        self.key = key
        self.predicate = predicate
        self.future: asyncio.Future[DeviceState] = loop.create_future()


class EntityRegistry:
    """In-memory entity registry (for gateway internal use)."""

    def __init__(self) -> None:
        """Initialize the registry."""
        self._states: Dict[Tuple[int, int, int, int], DeviceState] = {}
        self._shadow: Dict[Tuple[int, int, int, int], DeviceState] = {}
        self.by_platform: Dict[Platform, Dict[str, DeviceState]] = {}

    def upsert(self, dev: DeviceState, allow_insert: bool = True) -> tuple[bool, bool]:
        k = dev.key.key
        old = self._states.get(k)
        is_new = old is None

        if is_new and not allow_insert:
            return False, False
        if is_new:
            self._states[k] = dev
            self.by_platform.setdefault(dev.platform, {})[dev.key.unique_id] = dev
            return True, True

        platform_changed = (old.platform != dev.platform)
        state_changed = (old.state != dev.state)
        attr_changed = (old.attribute != dev.attribute)
        changed = platform_changed or state_changed or attr_changed

        if changed:
            if platform_changed:
                self.by_platform.get(old.platform, {}).pop(old.key.unique_id, None)
            self.by_platform.setdefault(dev.platform, {})[dev.key.unique_id] = dev
            self._states[k] = dev
        return False, changed

    def get(self, key: DeviceKey, include_shadow: bool = False) -> Optional[DeviceState]:
        dev = self._states.get(key.key)
        if dev is None and include_shadow:
            return self._shadow.get(key.key)
        return dev

    def promote(self, key: DeviceKey) -> bool:
        """shadow -> real promotion (becomes a target for entity creation)"""
        k = key.key
        dev = self._shadow.pop(k, None)
        if dev is None:
            return False
        self._states[k] = dev
        self.by_platform.setdefault(dev.platform, {})[dev.key.unique_id] = dev
        return True

    def all_by_platform(self, platform: Platform) -> List[DeviceState]:
        return list(self.by_platform.get(platform, {}).values())


class KocomGateway:
    """Connection/Receive Loop/Transmission Queue/Entity Registry Management Hub."""

    def __init__(
        self, 
        hass: HomeAssistant, 
        entry: ConfigEntry,
        host: str,
        port: int | None
    ) -> None:
        """Initialize the gateway."""
        self.hass = hass
        self.entry = entry
        self.host = host
        self.port = port
        self.conn = AsyncConnection(host=host, port=port)
        self.controller = KocomController(self)
        self.registry = EntityRegistry()
        self._task_reader: asyncio.Task | None = None
        self._send_lock = asyncio.Lock()
        self._pendings: list[_PendingWaiter] = []
        self._last_rx_monotonic: float = 0.0
        self._last_tx_monotonic: float = 0.0
        self._restore_mode: bool = False
        self._force_register_uid: str | None = None

    async def async_start(self) -> None:
        LOGGER.info("Starting gateway - %s:%s", self.host, self.port or "")
        await self.conn.open()
        self._last_rx_monotonic = self.conn.idle_since()
        self._last_tx_monotonic = self.conn.idle_since()
        self._task_reader = asyncio.create_task(self._read_loop())

    async def async_stop(self, event: Event | None = None) -> None:
        LOGGER.info("Stopping gateway - %s:%s", self.host, self.port or "")
        if self._task_reader:
            self._task_reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task_reader
        await self.conn.close()

    def is_idle(self) -> bool:
        return self.conn.idle_since() >= IDLE_GAP_SEC

    async def _read_loop(self) -> None:
        try:
            LOGGER.debug("Starting read loop")
            while True:
                if not self.conn._is_connected():
                    await asyncio.sleep(5)
                    continue
                chunk = await self.conn.recv(512, RECV_POLL_SEC)
                if chunk:
                    self._last_rx_monotonic = asyncio.get_running_loop().time()
                    self.controller.feed(chunk)
        except asyncio.CancelledError:
            raise

    async def async_send_action(self, key: DeviceKey, action: str, **kwargs) -> bool:
        if key.device_type == DeviceType.INTERPHONE:
            packet, expect_predicate, timeout = self.controller.generate_interphone_command(
                key, action, **kwargs
            )
        else:
            packet, expect_predicate, timeout = self.controller.generate_command(
                key, action, **kwargs
            )

        async with self._send_lock:
            for attempt in range(1, SEND_RETRY_MAX + 1):
                # idle 대기
                LOGGER.debug("Waiting for idle state (max %.1f sec)...", 1.0)
                t0 = asyncio.get_running_loop().time()
                while not self.is_idle():
                    await asyncio.sleep(0.01)
                    if asyncio.get_running_loop().time() - t0 > 1.0:
                        LOGGER.debug("Idle wait timeout after %.1f sec",
                                     asyncio.get_running_loop().time() - t0)
                        break

                # 전송
                if not self.conn._is_connected():
                    return False
                await self.conn.send(packet)
                self._last_tx_monotonic = asyncio.get_running_loop().time()

                # 확인 대기
                try:
                    _ = await self._wait_for_confirmation(key, expect_predicate, timeout)
                    LOGGER.debug("Command '%s' confirmed on attempt %d", action, attempt)
                    return True
                except asyncio.TimeoutError:
                    if attempt < SEND_RETRY_MAX:
                        LOGGER.warning(
                            "No confirmation for '%s' (attempt %d/%d). Retrying in %.2fs...",
                            action, attempt, SEND_RETRY_MAX, SEND_RETRY_GAP
                        )
                        await asyncio.sleep(SEND_RETRY_GAP)
                    else:
                        LOGGER.error("Command '%s' failed after %d attempts.", action, SEND_RETRY_MAX)
                        return False

    def on_device_state(self, dev: DeviceState) -> None:  
        allow_insert = True
        if dev.key.device_type in (DeviceType.LIGHT, DeviceType.OUTLET):
            allow_insert = bool(getattr(dev, "_is_register", True))
            if getattr(self, "_force_register_uid", None) == dev.key.unique_id:
                allow_insert = True

        is_new, changed = self.registry.upsert(dev, allow_insert=allow_insert)
        if is_new:
            LOGGER.info("New device has been detected. Register -> %s", dev.key)
            async_dispatcher_send(
                self.hass,
                self.async_signal_new_device(dev.platform),
                [dev],
            )
            self._notify_pendings(dev)
            return

        if changed:
            LOGGER.debug("Device state has been changed. Update -> %s", dev.key)
            async_dispatcher_send(
                self.hass,
                self.async_signal_device_updated(dev.key.unique_id),
                dev,
            )
        self._notify_pendings(dev)

    @callback
    def async_signal_new_device(self, platform: Platform) -> str:
        return f"{DOMAIN}_new_{platform.value}_{self.host}"

    @callback
    def async_signal_device_updated(self, unique_id: str) -> str:
        return f"{DOMAIN}_updated_{unique_id}"

    def get_devices_from_platform(self, platform: Platform) -> list[DeviceState]:
        return self.registry.all_by_platform(platform)

    async def _async_put_entity_dispatch_packet(self, entity_id: str) -> None:
        state = restore_state.async_get(self.hass).last_states.get(entity_id)
        if not (state and state.extra_data):
            return
        packet = state.extra_data.as_dict().get("packet")
        if not packet:
            return
        ent_reg = er.async_get(self.hass)
        ent_entry = ent_reg.async_get(entity_id)
        if ent_entry and ent_entry.unique_id:
            self._force_register_uid = ent_entry.unique_id.split(":")[0]
        LOGGER.debug("Restore state -> packet: %s", packet)
        self.controller._dispatch_packet(bytes.fromhex(packet))
        self._force_register_uid = None
        device_storage = state.extra_data.as_dict().get("device_storage", {})
        LOGGER.debug("Restore state -> device_storage: %s", device_storage)
        self.controller._device_storage = device_storage

    async def async_get_entity_registry(self) -> None:
        self._restore_mode = True
        try:
            entity_registry = er.async_get(self.hass)
            entities = er.async_entries_for_config_entry(entity_registry, self.entry.entry_id)
            for entity in entities:
                await self._async_put_entity_dispatch_packet(entity.entity_id)
        finally:
            self._restore_mode = False

    def _notify_pendings(self, dev: DeviceState) -> None:
        if not self._pendings:
            return
        hit: list[_PendingWaiter] = []
        for p in self._pendings:
            try:
                if p.key.key == dev.key.key and p.predicate(dev):
                    hit.append(p)
            except Exception:
                # predicate 내부 오류 방어
                continue
        if hit:
            for p in hit:
                if not p.future.done():
                    p.future.set_result(dev)
                try:
                    self._pendings.remove(p)
                except ValueError:
                    pass

    async def _wait_for_confirmation(
        self,
        key: DeviceKey,
        predicate: Callable[[DeviceState], bool],
        timeout: float,
    ) -> DeviceState:
        loop = asyncio.get_running_loop()
        waiter = _PendingWaiter(key, predicate, loop)
        self._pendings.append(waiter)
        try:
            return await asyncio.wait_for(waiter.future, timeout=timeout)
        finally:
            # 타임아웃 등으로 끝났을 때 누수 방지
            if waiter in self._pendings:
                try:
                    self._pendings.remove(waiter)
                except ValueError:
                    pass
