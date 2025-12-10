"""BLE runtime that bridges FossiBOT frames into Home Assistant."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime
from typing import Dict, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .fossibot import FossibotBleClient, ModbusReadFrame

from .const import (
    CONF_DEVICE_NAME,
    CONF_MAC,
    DOMAIN,
    KEEPALIVE_INTERVAL,
    MAX_KEEPALIVE_MISSES,
    MAX_RECONNECT_DELAY,
    MIN_RECONNECT_DELAY,
)

LOGGER = logging.getLogger(__name__)


class FossibotRuntime:
    """Manages BLE connectivity and exposes register data to entities."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._mac: str = entry.data[CONF_MAC]
        self._device_name: str = entry.data.get(CONF_DEVICE_NAME, self._mac)

        self._client = FossibotBleClient(self._mac)
        self._queue: asyncio.Queue[ModbusReadFrame] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._stopped = False

        self._register_values: Dict[int, int] = {}
        self._last_update: Optional[datetime] = None
        self._available = False

        self.update_signal = f"{DOMAIN}_{entry.entry_id}_update"
        self.availability_signal = f"{DOMAIN}_{entry.entry_id}_availability"

    @property
    def mac(self) -> str:
        return self._mac

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def available(self) -> bool:
        return self._available

    @property
    def last_update(self) -> Optional[datetime]:
        return self._last_update

    def get_register(self, register: int) -> Optional[int]:
        """Return the latest raw value for a register address."""
        return self._register_values.get(register)

    async def async_start(self) -> None:
        """Begin the BLE background loop."""
        if self._task:
            return
        self._stopped = False
        self._task = self._hass.loop.create_task(self._run())

    async def async_stop(self) -> None:
        """Stop the BLE background loop."""
        self._stopped = True
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._cleanup_client()

    async def _run(self) -> None:
        reconnect_delay = MIN_RECONNECT_DELAY
        while not self._stopped:
            try:
                await self._connect()
                reconnect_delay = MIN_RECONNECT_DELAY
                await self._process_frames()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive logging
                LOGGER.warning("BLE loop error for %s: %s", self._mac, exc)
            finally:
                await self._cleanup_client()
                if self._stopped:
                    break
                self._set_available(False)
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY)

    async def _connect(self) -> None:
        LOGGER.info("Connecting to FossiBOT device %s", self._mac)
        await self._client.connect()
        self._queue = asyncio.Queue()
        await self._client.subscribe_notifications(self._handle_frame)
        await self._client.send_registers_read_request()
        LOGGER.info("Subscribed to notifications for %s", self._mac)

    async def _process_frames(self) -> None:
        missed_frames = 0
        while not self._stopped:
            try:
                frame = await asyncio.wait_for(self._queue.get(), timeout=KEEPALIVE_INTERVAL)
            except asyncio.TimeoutError:
                missed_frames += 1
                LOGGER.debug(
                    "No Modbus data received from %s for %ss (miss %s/%s)",
                    self._mac,
                    KEEPALIVE_INTERVAL,
                    missed_frames,
                    MAX_KEEPALIVE_MISSES,
                )
                with suppress(Exception):
                    await self._client.send_registers_read_request()
                if missed_frames >= MAX_KEEPALIVE_MISSES:
                    raise TimeoutError(f"No data received from {self._mac}")
                continue

            missed_frames = 0
            start_address = frame.start_register
            for offset, value in enumerate(frame.register_values):
                self._register_values[start_address + offset] = value
            self._last_update = dt_util.utcnow()
            self._set_available(True)
            async_dispatcher_send(self._hass, self.update_signal)

    def _handle_frame(self, frame: ModbusReadFrame, _payload: bytes) -> None:
        self._queue.put_nowait(frame)

    def _set_available(self, available: bool) -> None:
        if self._available == available:
            return
        self._available = available
        async_dispatcher_send(self._hass, self.availability_signal, available)

    async def _cleanup_client(self) -> None:
        with suppress(Exception):
            await self._client.stop_notifications()
        with suppress(Exception):
            await self._client.disconnect()
