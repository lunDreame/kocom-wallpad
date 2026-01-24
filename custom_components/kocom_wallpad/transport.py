"""Transport for Kocom Wallpad."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple
import asyncio
import time
import logging

try:
    import serial_asyncio_fast as serial_asyncio
except ImportError:
    try:
        import pyserial_asyncio_fast as serial_asyncio
    except ImportError:
        import serial_asyncio

from .const import LOGGER, PACKET_PREFIX, PACKET_SUFFIX, PACKET_LEN


@dataclass
class AsyncConnection:
    """Async Connection."""
    host: str
    port: Optional[int]
    serial_baud: int = 9600
    connect_timeout: float = 5.0
    reconnect_backoff: Tuple[float, float] = (1.0, 30.0)  # min, max seconds

    def __post_init__(self) -> None:
        """Initialize the connection."""
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._last_activity_mono: float = time.monotonic()
        self._last_reconn_delay: float = 0.0
        self._connected = True
        self._buffer = bytearray()

    async def open(self) -> None:
        try:
            if self.port is None:
                self._reader, self._writer = await serial_asyncio.open_serial_connection(
                    url=self.host, baudrate=self.serial_baud
                )
                LOGGER.info("Connection opened for serial: %s", self.host)
            else:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port),
                    timeout=self.connect_timeout,
                )
                LOGGER.info("Connection opened for socket: %s:%s", self.host, self.port)
            self._connected = True
            self._touch()
        except Exception as e:
            LOGGER.warning("Connection open failed: %r", e)
            await self.reconnect()

    async def close(self) -> None:
        if self._writer is not None:
            LOGGER.info("Closing connection")
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
        return self._connected

    def _touch(self) -> None:
        self._last_activity_mono = time.monotonic()

    def idle_since(self) -> float:
        return max(0.0, time.monotonic() - self._last_activity_mono)

    @staticmethod
    def _checksum(buf: bytes) -> int:
        return sum(buf) % 256

    async def send_packet(self, data: bytes) -> bool:
        """Send packet with exponential backoff retry."""
        delays = [0.5, 1.0, 2.0]
        for attempt in range(len(delays) + 1):
            if not self._writer:
                # Try to reconnect if not connected
                await self.reconnect()

            if self._writer:
                try:
                    LOGGER.debug("Sending packet (attempt %d): %s", attempt + 1, data.hex())
                    self._writer.write(data)
                    await self._writer.drain()
                    self._touch()
                    return True
                except Exception as e:
                    LOGGER.warning("Send failed on attempt %d: %r", attempt + 1, e)

            if attempt < len(delays):
                wait_time = delays[attempt]
                LOGGER.info("Latency detected, retrying packet send in %.1fs...", wait_time)
                await asyncio.sleep(wait_time)
                if not self._connected:
                    await self.reconnect()
            else:
                LOGGER.error("Failed to send packet after %d attempts", attempt + 1)

        return False

    async def recv_packet(self) -> Optional[bytes]:
        """Receive a full valid packet."""
        if not self._reader:
             await asyncio.sleep(0.1)
             if not self._reader:
                 return None

        while True:
            # 1. Find Header
            start_idx = self._buffer.find(PACKET_PREFIX)
            if start_idx == -1:
                # Keep last byte just in case it's 0xAA (half header)
                if len(self._buffer) > 0:
                     last_byte = self._buffer[-1:]
                     self._buffer.clear()
                     self._buffer.extend(last_byte)

                try:
                    # 5.0s general read timeout
                    chunk = await asyncio.wait_for(self._reader.read(512), timeout=5.0)
                    if not chunk:
                        # EOF
                        await self.reconnect()
                        return None
                    self._buffer.extend(chunk)
                    self._touch()
                    continue
                except asyncio.TimeoutError:
                    return None
                except Exception as e:
                    LOGGER.warning("Read error: %s", e)
                    await self.reconnect()
                    return None

            # Header found. Discard garbage before header.
            if start_idx > 0:
                del self._buffer[:start_idx]

            # Now self._buffer starts with 0xAA 0x55
            # We need 21 bytes total.

            start_time = time.monotonic()
            while len(self._buffer) < PACKET_LEN:
                 needed = PACKET_LEN - len(self._buffer)
                 elapsed = time.monotonic() - start_time
                 remaining_time = 2.0 - elapsed

                 if remaining_time <= 0:
                     LOGGER.warning("Packet assembly timeout (header found but body incomplete). Clearing buffer.")
                     self._buffer.clear()
                     break

                 try:
                     chunk = await asyncio.wait_for(self._reader.read(needed), timeout=remaining_time)
                     if not chunk:
                         await self.reconnect()
                         return None
                     self._buffer.extend(chunk)
                     self._touch()
                 except asyncio.TimeoutError:
                     LOGGER.warning("Packet assembly timeout. Clearing buffer.")
                     self._buffer.clear()
                     break
                 except Exception as e:
                     LOGGER.warning("Read error during packet assembly: %s", e)
                     await self.reconnect()
                     return None

            if len(self._buffer) < PACKET_LEN:
                continue # Buffer cleared, retry from start

            # We have >= 21 bytes
            packet_candidate = self._buffer[:PACKET_LEN]

            # Verify Suffix
            if not packet_candidate.endswith(PACKET_SUFFIX):
                LOGGER.warning("Invalid packet suffix. Frame shifting.")
                del self._buffer[0] # Shift one byte and retry finding prefix
                continue

            # Verify Checksum
            # Data bytes for checksum: indices 2 to 17
            calc_sum = self._checksum(packet_candidate[2:18])
            recv_sum = packet_candidate[18]

            if calc_sum != recv_sum:
                LOGGER.warning("Checksum fail (calc %02x != recv %02x). Frame shifting.", calc_sum, recv_sum)
                del self._buffer[0]
                continue

            # Valid packet!
            del self._buffer[:PACKET_LEN]
            return bytes(packet_candidate)

    async def reconnect(self) -> None:
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
        
        LOGGER.info("Connection lost. Reconnecting in %.1f sec...", delay)
        await asyncio.sleep(delay)
        self._last_reconn_delay = min(delay * 2, delay_max)
        await self.open()

        if self._is_connected():
            LOGGER.info("Connection reconnected")
            self._last_reconn_delay = delay_min
