"""BLE runtime that bridges FossiBOT frames into Home Assistant."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime
from typing import Dict, Optional

from bleak.exc import BleakError
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .fossibot import FossibotBleClient, ModbusReadFrame

from .const import (
    ADAPTER_ERROR_BACKOFF,
    CONF_DEVICE_NAME,
    CONF_MAC,
    DOMAIN,
    KEEPALIVE_INTERVAL,
    MAX_ADAPTER_ERROR_RETRIES,
    MAX_KEEPALIVE_MISSES,
    MAX_RECONNECT_DELAY,
    MIN_RECONNECT_DELAY,
)

LOGGER = logging.getLogger(__name__)


def _is_adapter_not_found_error(exc: BleakError) -> bool:
    message = str(exc).lower()
    return "adapter" in message and "not found" in message


def _is_connection_slot_error(exc: BleakError) -> bool:
    return "available connection slot" in str(exc).lower()


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
        self._adapter_error_count = 0

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
            reset_client_after_cleanup = False
            cancelled = False
            try:
                await self._connect()
                reconnect_delay = MIN_RECONNECT_DELAY
                self._adapter_error_count = 0
                await self._process_frames()
            except asyncio.CancelledError:
                cancelled = True
            except BleakError as exc:
                if _is_adapter_not_found_error(exc):
                    # Adapter moved or unavailable - use longer backoff and rebuild state.
                    self._adapter_error_count += 1
                    LOGGER.warning(
                        "Adapter error for %s (attempt %s/%s): %s. Waiting %ss before retry.",
                        self._mac,
                        self._adapter_error_count,
                        MAX_ADAPTER_ERROR_RETRIES,
                        exc,
                        ADAPTER_ERROR_BACKOFF,
                    )
                    if self._adapter_error_count >= MAX_ADAPTER_ERROR_RETRIES:
                        LOGGER.info(
                            "Resetting BLE client for %s after %s adapter errors",
                            self._mac,
                            self._adapter_error_count,
                        )
                        reset_client_after_cleanup = True
                        self._adapter_error_count = 0
                    reconnect_delay = ADAPTER_ERROR_BACKOFF
                elif _is_connection_slot_error(exc):
                    # Temporary scanner/backend capacity issue. Recreate client so the next
                    # attempt rebinds against the current HA Bluetooth backend state.
                    self._adapter_error_count = 0
                    reset_client_after_cleanup = True
                    reconnect_delay = max(MIN_RECONNECT_DELAY, ADAPTER_ERROR_BACKOFF)
                    LOGGER.warning(
                        "No BLE connection slot available for %s. Retrying in %ss: %s",
                        self._mac,
                        reconnect_delay,
                        exc,
                    )
                else:
                    # Other Bleak errors - standard exponential backoff
                    self._adapter_error_count = 0
                    LOGGER.warning("BLE error for %s: %s", self._mac, exc)
                    reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY)
            except Exception as exc:  # pragma: no cover - defensive logging
                LOGGER.warning("BLE loop error for %s: %s", self._mac, exc)
                reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY)
            finally:
                await self._cleanup_client()
                if reset_client_after_cleanup:
                    self._client = FossibotBleClient(self._mac)
                if self._stopped or cancelled:
                    break
                self._set_available(False)
                await asyncio.sleep(reconnect_delay)

    async def _connect(self) -> None:
        LOGGER.info("Connecting to FossiBOT device %s", self._mac)
        ble_device = self._resolve_ble_device()
        self._client.set_ble_device(ble_device)
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

    def _resolve_ble_device(self) -> object | None:
        """Resolve the current HA BLEDevice for this address, if available."""
        try:
            ble_device = bluetooth.async_ble_device_from_address(
                self._hass,
                self._mac,
                connectable=True,
            )
        except TypeError:
            # Older HA versions may not support the connectable kwarg.
            ble_device = bluetooth.async_ble_device_from_address(self._hass, self._mac)
        except Exception as exc:  # pragma: no cover - defensive logging
            LOGGER.debug(
                "Failed to resolve BLEDevice for %s from HA bluetooth registry: %s",
                self._mac,
                exc,
            )
            return None

        if ble_device is None:
            LOGGER.debug(
                "No HA BLEDevice currently available for %s; using address-only connect",
                self._mac,
            )
        return ble_device

    async def _cleanup_client(self) -> None:
        with suppress(Exception):
            await self._client.stop_notifications()
        with suppress(Exception):
            await self._client.disconnect()
