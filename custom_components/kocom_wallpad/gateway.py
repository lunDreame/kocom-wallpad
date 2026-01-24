"""Kocom Wallpad 게이트웨이 (Gateway)."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Optional, Dict, Tuple, List, Callable

from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import entity_registry as er, restore_state, device_registry as dr
from homeassistant.const import Platform
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    LOGGER,
    DOMAIN,
    IDLE_GAP_SEC,
    DeviceType,
)
from .models import DeviceKey, DeviceState
from .transport import AsyncConnection
from .controller import KocomController


@dataclass(slots=True)
class _CmdItem:
    """명령 큐 아이템."""
    key: DeviceKey
    action: str
    kwargs: dict
    future: asyncio.Future = field(default_factory=asyncio.get_running_loop().create_future)


class _PendingWaiter:
    """응답 대기자."""

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
    """인메모리 엔티티 레지스트리 (게이트웨이 내부용)."""

    def __init__(self) -> None:
        """레지스트리 초기화."""
        self._states: Dict[Tuple[int, int, int, int], DeviceState] = {}
        self._shadow: Dict[Tuple[int, int, int, int], DeviceState] = {}
        self.by_platform: Dict[Platform, Dict[str, DeviceState]] = {}

    def upsert(self, dev: DeviceState, allow_insert: bool = True) -> tuple[bool, bool]:
        """기기 상태 업데이트 또는 삽입."""
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
        """기기 상태 조회."""
        dev = self._states.get(key.key)
        if dev is None and include_shadow:
            return self._shadow.get(key.key)
        return dev

    def promote(self, key: DeviceKey) -> bool:
        """섀도우 상태를 실제 상태로 승격."""
        k = key.key
        dev = self._shadow.pop(k, None)
        if dev is None:
            return False
        self._states[k] = dev
        self.by_platform.setdefault(dev.platform, {})[dev.key.unique_id] = dev
        return True

    def all_by_platform(self, platform: Platform) -> List[DeviceState]:
        """플랫폼별 모든 기기 반환."""
        return list(self.by_platform.get(platform, {}).values())


class KocomGateway:
    """코콤 월패드 게이트웨이.

    연결, 수신 루프, 전송 큐, 엔티티 레지스트리를 관리합니다.
    """

    def __init__(
        self, 
        hass: HomeAssistant, 
        entry: ConfigEntry,
        host: str,
        port: int | None
    ) -> None:
        """게이트웨이 초기화."""
        self.hass = hass
        self.entry = entry
        self.host = host
        self.port = port
        self.conn = AsyncConnection(host=host, port=port)
        self.controller = KocomController(self)
        self.registry = EntityRegistry()
        self._tx_queue: asyncio.Queue[_CmdItem] = asyncio.Queue()
        self._task_reader: asyncio.Task | None = None
        self._task_sender: asyncio.Task | None = None
        self._pendings: list[_PendingWaiter] = []
        self._last_rx_monotonic: float = 0.0
        self._last_tx_monotonic: float = 0.0
        self._restore_mode: bool = False
        self._force_register_uid: str | None = None

    async def async_start(self) -> None:
        """게이트웨이 시작."""
        LOGGER.info("게이트웨이 시작 - %s:%s", self.host, self.port or "")

        # 브리지 기기(Hub) 등록
        device_registry = dr.async_get(self.hass)
        device_registry.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, str(self.host))},
            manufacturer="Kocom",
            model="EW11 RS485 Bridge",
            name="Kocom Wallpad Gateway",
        )

        await self.conn.open()
        self._last_rx_monotonic = self.conn.idle_since()
        self._last_tx_monotonic = self.conn.idle_since()
        self._task_reader = asyncio.create_task(self._read_loop())
        self._task_sender = asyncio.create_task(self._sender_loop())

    async def async_stop(self, event: Event | None = None) -> None:
        """게이트웨이 중지."""
        LOGGER.info("게이트웨이 중지 - %s:%s", self.host, self.port or "")
        if self._task_reader:
            self._task_reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task_reader
        if self._task_sender:
            self._task_sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task_sender
        await self.conn.close()

    def is_idle(self) -> bool:
        """회선 유휴 상태 확인."""
        return self.conn.idle_since() >= IDLE_GAP_SEC

    async def _read_loop(self) -> None:
        """수신 루프."""
        try:
            LOGGER.debug("수신 루프 시작")
            while True:
                if not self.conn._is_connected():
                    await asyncio.sleep(5)
                    continue

                packet = await self.conn.recv_packet()
                if packet:
                    self._last_rx_monotonic = asyncio.get_running_loop().time()
                    self.controller.process_packet(packet)
        except asyncio.CancelledError:
            LOGGER.debug("수신 루프 취소됨")
            raise

    async def async_send_action(self, key: DeviceKey, action: str, **kwargs) -> bool:
        """기기 제어 액션 전송."""
        item = _CmdItem(key=key, action=action, kwargs=kwargs)
        await self._tx_queue.put(item)
        try:
            res = await item.future   # 워커가 set_result(True/False)
            return bool(res)
        except asyncio.CancelledError:
            if not item.future.done():
                item.future.set_result(False)
            raise

    async def send_raw_packet(self, packet_hex: str) -> None:
        """Raw 패킷 전송 서비스.

        Args:
            packet_hex: 16진수 패킷 문자열 (예: "AA55...")
        """
        try:
            packet_hex = packet_hex.replace(" ", "")
            packet = bytes.fromhex(packet_hex)
            await self.conn.send_packet(packet)
            LOGGER.info("디버그 패킷 전송: %s", packet_hex)
        except ValueError as e:
            LOGGER.error("잘못된 16진수 문자열: %s", e)
        except Exception as e:
            LOGGER.error("패킷 전송 실패: %s", e)

    def on_device_state(self, dev: DeviceState) -> None:
        """기기 상태 수신 시 콜백."""
        allow_insert = True
        if dev.key.device_type in (DeviceType.LIGHT, DeviceType.OUTLET):
            allow_insert = bool(getattr(dev, "_is_register", True))
            if getattr(self, "_force_register_uid", None) == dev.key.unique_id:
                allow_insert = True

        is_new, changed = self.registry.upsert(dev, allow_insert=allow_insert)
        if is_new:
            LOGGER.info("새로운 기기 발견. 등록 -> %s", dev.key)
            async_dispatcher_send(
                self.hass,
                self.async_signal_new_device(dev.platform),
                [dev],
            )
            self._notify_pendings(dev)
            return

        if changed:
            LOGGER.debug("기기 상태 변경됨. 업데이트 -> %s", dev.key)
            async_dispatcher_send(
                self.hass,
                self.async_signal_device_updated(dev.key.unique_id),
                dev,
            )
        self._notify_pendings(dev)

    @callback
    def async_signal_new_device(self, platform: Platform) -> str:
        """새 기기 발견 시그널 이름."""
        return f"{DOMAIN}_new_{platform.value}_{self.host}"

    @callback
    def async_signal_device_updated(self, unique_id: str) -> str:
        """기기 업데이트 시그널 이름."""
        return f"{DOMAIN}_updated_{unique_id}"

    def get_devices_from_platform(self, platform: Platform) -> list[DeviceState]:
        """플랫폼에 속한 모든 기기 반환."""
        return self.registry.all_by_platform(platform)

    async def _async_put_entity_dispatch_packet(self, entity_id: str) -> None:
        """엔티티 상태 복구 및 패킷 주입."""
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
        LOGGER.debug("상태 복구 -> 패킷: %s", packet)
        self.controller._dispatch_packet(bytes.fromhex(packet))
        self._force_register_uid = None
        device_storage = state.extra_data.as_dict().get("device_storage", {})
        LOGGER.debug("상태 복구 -> device_storage: %s", device_storage)
        self.controller._device_storage = device_storage

    async def async_get_entity_registry(self) -> None:
        """저장된 엔티티 레지스트리 로드."""
        self._restore_mode = True
        try:
            entity_registry = er.async_get(self.hass)
            entities = er.async_entries_for_config_entry(entity_registry, self.entry.entry_id)
            for entity in entities:
                await self._async_put_entity_dispatch_packet(entity.entity_id)
        finally:
            self._restore_mode = False

    def _notify_pendings(self, dev: DeviceState) -> None:
        """대기 중인 명령 완료 알림."""
        if not self._pendings:
            return
        hit: list[_PendingWaiter] = []
        for p in self._pendings:
            try:
                if p.key.key == dev.key.key and p.predicate(dev):
                    hit.append(p)
            except Exception:
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
        """명령 수행 후 상태 변경 대기."""
        loop = asyncio.get_running_loop()
        waiter = _PendingWaiter(key, predicate, loop)
        self._pendings.append(waiter)
        try:
            return await asyncio.wait_for(waiter.future, timeout=timeout)
        finally:
            if waiter in self._pendings:
                try:
                    self._pendings.remove(waiter)
                except ValueError:
                    pass

    async def _sender_loop(self) -> None:
        """전송 루프."""
        LOGGER.debug("전송 루프 시작")
        try:
            while True:
                item = await self._tx_queue.get()
                if item is None:
                    continue

                # 패킷 생성 및 기대 조건 설정
                try:
                    packet, expect_predicate, timeout = self.controller.generate_command(
                        item.key, item.action, **item.kwargs
                    )
                except Exception as e:
                    LOGGER.exception("명령 생성 실패: %s", e)
                    if not item.future.done():
                        item.future.set_result(False)
                    self._tx_queue.task_done()
                    continue

                # 유휴 대기
                t0 = asyncio.get_running_loop().time()
                while not self.is_idle():
                    await asyncio.sleep(0.01)
                    if asyncio.get_running_loop().time() - t0 > 1.0:
                        LOGGER.debug("유휴 대기 타임아웃 (%.2fs).", asyncio.get_running_loop().time() - t0)
                        break

                # 전송
                success = False
                if await self.conn.send_packet(packet):
                    self._last_tx_monotonic = asyncio.get_running_loop().time()

                    # 확인 대기
                    try:
                        _ = await self._wait_for_confirmation(item.key, expect_predicate, timeout)
                        LOGGER.debug("명령 '%s' 확인됨.", item.action)
                        success = True
                    except asyncio.TimeoutError:
                        LOGGER.warning("명령 '%s' 전송됨, 그러나 확인 응답 없음 (%.1fs).", item.action, timeout)
                else:
                    LOGGER.error("명령 '%s' 전송 실패 (재시도 초과).", item.action)

                if not item.future.done():
                    item.future.set_result(success)

                self._tx_queue.task_done()
        except asyncio.CancelledError:
            LOGGER.debug("전송 루프 취소됨")
            raise
