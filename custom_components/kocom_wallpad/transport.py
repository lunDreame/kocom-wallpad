"""Kocom Wallpad Transport Layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple
import asyncio
import time

try:
    import serial_asyncio_fast as serial_asyncio
except ImportError:
    try:
        import pyserial_asyncio_fast as serial_asyncio
    except ImportError:
        import serial_asyncio

from .const import LOGGER, PACKET_PREFIX, PACKET_SUFFIX, PACKET_LEN


class RingBuffer:
    """고성능 순환 버퍼 (Circular Buffer).

    메모리 재할당을 최소화하기 위해 고정된 크기의 버퍼를 사용합니다.
    """

    def __init__(self, size: int = 4096) -> None:
        """버퍼 초기화.

        Args:
            size: 버퍼 크기 (bytes)
        """
        self._data = bytearray(size)
        self._size = size
        self._head = 0  # Write pointer
        self._tail = 0  # Read pointer
        self._count = 0 # Data available

    def clear(self) -> None:
        """버퍼 초기화."""
        self._head = 0
        self._tail = 0
        self._count = 0

    def write(self, data: bytes) -> int:
        """데이터 쓰기.

        Args:
            data: 쓸 데이터

        Returns:
            쓴 바이트 수
        """
        n = len(data)
        if n == 0:
            return 0

        free = self._size - self._count
        if n > free:
            # 공간 부족 시 전체 초기화 후 쓰기 (데이터 유실보다 최신 데이터 우선)
            self.clear()

        # 1st part
        first_chunk = min(n, self._size - self._head)
        self._data[self._head : self._head + first_chunk] = data[:first_chunk]
        self._head = (self._head + first_chunk) % self._size

        # 2nd part (wrap around)
        if first_chunk < n:
            second_chunk = n - first_chunk
            self._data[0 : second_chunk] = data[first_chunk:]
            self._head = (self._head + second_chunk) % self._size

        self._count += n
        return n

    def peek(self, length: int) -> bytes:
        """데이터 미리보기 (포인터 이동 없음).

        Args:
            length: 읽을 길이

        Returns:
            데이터 bytes
        """
        if length > self._count:
            length = self._count

        if length == 0:
            return b""

        # 1st part
        first_chunk = min(length, self._size - self._tail)
        result = self._data[self._tail : self._tail + first_chunk]

        # 2nd part
        if first_chunk < length:
            second_chunk = length - first_chunk
            result += self._data[0 : second_chunk]

        return bytes(result)

    def advance(self, length: int) -> None:
        """읽기 포인터 이동 (데이터 소비).

        Args:
            length: 이동할 바이트 수
        """
        if length > self._count:
            length = self._count

        self._tail = (self._tail + length) % self._size
        self._count -= length

    def find(self, pattern: bytes) -> int:
        """패턴 검색.

        Args:
            pattern: 찾을 바이트 패턴

        Returns:
            패턴 시작 인덱스 (현재 tail 기준 상대 위치), 없으면 -1
        """
        pat_len = len(pattern)
        if pat_len == 0 or self._count < pat_len:
            return -1

        # 성능을 위해 현재 유효한 데이터의 스냅샷에서 검색
        snapshot = self.peek(self._count)
        return snapshot.find(pattern)

    def __len__(self) -> int:
        return self._count


@dataclass
class AsyncConnection:
    """비동기 통신 관리자 (Async Connection).

    TCP 소켓 및 시리얼 연결을 관리하며, 패킷의 송수신 및 오류 복구를 담당합니다.
    """
    host: str
    port: Optional[int]
    serial_baud: int = 9600
    connect_timeout: float = 5.0
    reconnect_backoff: Tuple[float, float] = (1.0, 30.0)  # 최소, 최대 대기 시간 (초)

    # 상태 모니터링 필드 (초기화는 __post_init__에서)
    rx_success_count: int = field(init=False, default=0)
    rx_error_count: int = field(init=False, default=0)
    last_packet_time: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        """연결 초기화."""
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._last_activity_mono: float = time.monotonic()
        self._last_reconn_delay: float = 0.0
        self._connected = True

        # 고성능 순환 버퍼 도입
        self._buffer = RingBuffer(4096)

        # 동시성 제어 (쓰기 충돌 방지)
        self._lock = asyncio.Lock()

        # 자가 치유를 위한 연속 에러 카운터
        self._consecutive_errors = 0

    async def open(self) -> None:
        """연결 열기."""
        try:
            if self.port is None:
                self._reader, self._writer = await serial_asyncio.open_serial_connection(
                    url=self.host, baudrate=self.serial_baud
                )
                LOGGER.info("시리얼 연결 성공: %s", self.host)
            else:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port),
                    timeout=self.connect_timeout,
                )
                LOGGER.info("소켓 연결 성공: %s:%s", self.host, self.port)
            self._connected = True
            self._touch()

            # 연결 시 버퍼 초기화
            self._buffer.clear()
            self._consecutive_errors = 0

        except Exception as e:
            LOGGER.warning("연결 실패: %r", e)
            await self.reconnect()

    async def close(self) -> None:
        """연결 닫기."""
        if self._writer is not None:
            LOGGER.info("연결 종료 중...")
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            finally:
                self._writer = None
        self._reader = None
        self._connected = False
        self._buffer.clear()

    def _is_connected(self) -> bool:
        """연결 여부 확인."""
        return self._connected

    def _touch(self) -> None:
        """마지막 활동 시간 갱신."""
        self._last_activity_mono = time.monotonic()

    def idle_since(self) -> float:
        """마지막 활동 이후 경과 시간 (초)."""
        return max(0.0, time.monotonic() - self._last_activity_mono)

    @staticmethod
    def _checksum(buf: bytes) -> int:
        """체크섬 계산."""
        return sum(buf) % 256

    async def send_packet(self, data: bytes) -> bool:
        """패킷 전송 (재시도 및 백오프 포함).

        Args:
            data: 전송할 바이트 데이터

        Returns:
            성공 여부 (bool)
        """
        async with self._lock:  # 스레드 안전성 보장
            delays = [0.5, 1.0, 2.0]
            for attempt in range(len(delays) + 1):
                if not self._writer:
                    await self.reconnect()

                if self._writer:
                    try:
                        LOGGER.debug("패킷 전송 (시도 %d): %s", attempt + 1, data.hex())
                        self._writer.write(data)
                        await self._writer.drain()
                        self._touch()
                        return True
                    except Exception as e:
                        LOGGER.warning("전송 실패 (시도 %d): %r", attempt + 1, e)

                if attempt < len(delays):
                    wait_time = delays[attempt]
                    LOGGER.info("지연 감지, %.1f초 후 재시도...", wait_time)
                    await asyncio.sleep(wait_time)
                    if not self._connected:
                        await self.reconnect()
                else:
                    LOGGER.error("%d회 시도 후 전송 실패", attempt + 1)

            return False

    async def recv_packet(self) -> Optional[bytes]:
        """유효한 패킷 수신 대기.

        Returns:
            수신된 패킷 (bytes) 또는 None (타임아웃/에러)
        """
        if not self._reader:
             await asyncio.sleep(0.1)
             if not self._reader:
                 return None

        while True:
            # 1. 버퍼에 데이터 채우기
            try:
                # 패킷 하나 완성될 만큼 없으면 읽기 시도
                if len(self._buffer) < PACKET_LEN:
                     # 5.0초 타임아웃
                     chunk = await asyncio.wait_for(self._reader.read(512), timeout=5.0)
                     if not chunk:
                         LOGGER.warning("연결 끊김 (EOF)")
                         await self.reconnect()
                         return None
                     self._buffer.write(chunk)
                     self._touch()
            except asyncio.TimeoutError:
                return None
            except Exception as e:
                LOGGER.warning("읽기 오류: %s", e)
                self.rx_error_count += 1
                await self.reconnect()
                return None

            # 2. 헤더 찾기 (0xAA 0x55)
            start_idx = self._buffer.find(PACKET_PREFIX)

            if start_idx == -1:
                # 헤더가 없으면 버퍼 정리 (마지막 바이트가 0xAA일 수 있으니 보존)
                if len(self._buffer) > 0:
                    last_byte = self._buffer.peek(len(self._buffer))[-1:]
                    self._buffer.clear()
                    if last_byte == b'\xAA':
                        self._buffer.write(last_byte)
                continue

            # 헤더 앞의 가비지 제거
            if start_idx > 0:
                self._buffer.advance(start_idx)

            # 버퍼는 0xAA 0x55 로 시작. 전체 길이 확인
            if len(self._buffer) < PACKET_LEN:
                continue

            # 패킷 후보 추출
            packet_candidate = self._buffer.peek(PACKET_LEN)

            # 3. 서픽스 검증 (0x0D 0x0D)
            if not packet_candidate.endswith(PACKET_SUFFIX):
                LOGGER.warning("잘못된 패킷 서픽스. 프레임 시프트 수행.")
                self._buffer.advance(1) # 1바이트 버리고 다시 탐색
                self.rx_error_count += 1
                if await self._check_self_correction():
                    return None
                continue

            # 4. 체크섬 검증 (인덱스 2 ~ 17 합계)
            calc_sum = self._checksum(packet_candidate[2:18])
            recv_sum = packet_candidate[18]

            if calc_sum != recv_sum:
                LOGGER.warning("체크섬 불일치 (계산: %02x != 수신: %02x). 프레임 시프트.", calc_sum, recv_sum)
                self._buffer.advance(1)
                self.rx_error_count += 1
                if await self._check_self_correction():
                    return None
                continue

            # 5. 유효한 패킷
            self._buffer.advance(PACKET_LEN)
            self.rx_success_count += 1
            self.last_packet_time = time.time()
            self._consecutive_errors = 0 # 에러 카운터 초기화

            return packet_candidate

    async def _check_self_correction(self) -> bool:
        """에러 연속 발생 확인 및 자가 치유 수행.

        Returns:
            재접속이 트리거되었는지 여부 (True면 루프 중단 필요)
        """
        self._consecutive_errors += 1
        if self._consecutive_errors > 3:
            LOGGER.error("연속된 패킷 에러(%d회) 감지. 자가 치유를 위해 버퍼 초기화 및 소켓 재시작.", self._consecutive_errors)
            self._buffer.clear()
            self._consecutive_errors = 0
            await self.reconnect()
            return True
        return False

    async def reconnect(self) -> None:
        """재연결 수행."""
        self._connected = False
        delay_min, delay_max = self.reconnect_backoff

        if self._last_reconn_delay > 0.0:
            delay = self._last_reconn_delay
        else:
            delay = delay_min

        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        
        LOGGER.info("연결 끊김. %.1f초 후 재연결 시도...", delay)
        await asyncio.sleep(delay)

        self._last_reconn_delay = min(delay * 2, delay_max)
        await self.open()

        if self._is_connected():
            LOGGER.info("재연결 성공")
            self._last_reconn_delay = delay_min
