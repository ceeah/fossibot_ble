"""BLE utilities for interacting with FossiBOT/BrightEMS devices."""

import asyncio
import inspect
import logging
from contextlib import suppress
from typing import AsyncIterator, Awaitable, Callable, Optional, Tuple

from bleak import BleakClient
from bleak.exc import BleakError
try:
    from bleak_retry_connector import establish_connection
except ImportError:  # pragma: no cover - optional in some environments
    establish_connection = None

from .modbus import (
    MODBUS_DEVICE_ADDRESS,
    MODBUS_FCN_READ_INPUT_REGISTER,
    MODBUS_READ_COUNT,
    MODBUS_READ_START,
    ModbusReadFrame,
    build_read_registers_request,
    parse_modbus_read_frame,
)

# BrightEMS custom service/characteristics that carry Modbus payloads
SERVICE_UUID = "0000a002-0000-1000-8000-00805f9b34fb"
MODBUS_WRITE_UUID = "0000c304-0000-1000-8000-00805f9b34fb"
MODBUS_NOTIFY_UUID = "0000c305-0000-1000-8000-00805f9b34fb"

FrameCallback = Callable[[ModbusReadFrame, bytes], Optional[Awaitable[None]]]

LOGGER = logging.getLogger(__name__)


class FossibotBleClient:
    """High-level BLE client that manages connections and Modbus notifications."""

    def __init__(
        self,
        mac_address: str,
        *,
        ble_device: object | None = None,
        start_register: int = MODBUS_READ_START,
        register_count: int = MODBUS_READ_COUNT,
        device_address: int = MODBUS_DEVICE_ADDRESS,
        function_code: int = MODBUS_FCN_READ_INPUT_REGISTER,
    ) -> None:
        self.mac_address = mac_address
        self._ble_device = ble_device
        self.start_register = start_register
        self.register_count = register_count
        self.device_address = device_address
        self.function_code = function_code

        self._client: BleakClient | None = None
        self._connected = False
        self._notifications_started = False
        self._frame_callback: Optional[FrameCallback] = None
        self._request_payload = build_read_registers_request(
            device_address, start_register, register_count, function_code=function_code
        )

    async def __aenter__(self) -> "FossibotBleClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        """Establish a BLE connection and resolve the Modbus characteristics."""
        if self._connected:
            return
        LOGGER.info("Connecting to device %s", self.mac_address)
        try:
            self._client = await self._establish_client()
        except BleakError as e:
            # Adapter may have moved to a different hci device
            if "adapter" in str(e).lower() and "not found" in str(e).lower():
                LOGGER.warning(
                    "Adapter for device %s not found: %s. Device may have moved to different adapter.",
                    self.mac_address,
                    e,
                )
                # Re-raise with adapter error flag for runtime to handle
                raise
            self._client = None
            raise
        self._connected = True
        LOGGER.info("Connection successful")

        client = self._require_client()
        service_cache = client.services
        if service_cache is None:
            get_services = getattr(client, "get_services", None)
            if callable(get_services):
                await get_services()
                service_cache = client.services
        if service_cache is None:
            raise RuntimeError("Unable to enumerate BLE services on device")

        service = service_cache.get_service(SERVICE_UUID)
        if service is None:
            raise RuntimeError("A002 service not found on device")

        write_characteristic = service.get_characteristic(MODBUS_WRITE_UUID)
        notify_characteristic = service.get_characteristic(MODBUS_NOTIFY_UUID)
        if not write_characteristic or not notify_characteristic:
            raise RuntimeError("C304/C305 characteristics not found on device")

    async def disconnect(self) -> None:
        """Stop notifications (if active) and close the BLE connection."""
        await self.stop_notifications()
        client = self._client
        if not self._connected or client is None:
            return
        try:
            await client.disconnect()
            LOGGER.debug("Disconnected from device.")
        finally:
            self._connected = False
            self._client = None

    async def subscribe_notifications(self, frame_callback: FrameCallback) -> None:
        """Subscribe for Modbus notifications."""
        if not self._connected:
            raise RuntimeError("Client must be connected before subscribing")
        if self._notifications_started:
            raise RuntimeError("Notifications already active")
        self._frame_callback = frame_callback
        await self._require_client().start_notify(
            MODBUS_NOTIFY_UUID, self._handle_notification
        )
        self._notifications_started = True

    async def stop_notifications(self) -> None:
        """Unsubscribe from Modbus notifications."""
        if not self._notifications_started:
            return
        try:
            await self._require_client().stop_notify(MODBUS_NOTIFY_UUID)
            LOGGER.debug("Notifications stopped.")
        finally:
            self._notifications_started = False
            self._frame_callback = None

    async def send_registers_read_request(self) -> None:
        """Send the default 'Read Input Registers' request."""
        if not self._connected:
            raise RuntimeError("Client must be connected before sending commands")
        LOGGER.debug("Sending Modbus read request %s", self._request_payload.hex())
        await self._require_client().write_gatt_char(
            MODBUS_WRITE_UUID, self._request_payload
        )

    def set_ble_device(self, ble_device: object | None) -> None:
        """Update the HA-resolved BLEDevice used for the next connection attempt."""
        self._ble_device = ble_device

    async def _establish_client(self) -> BleakClient:
        """Create and connect a fresh Bleak client for the current backend state."""
        target = self._ble_device or self.mac_address
        if establish_connection is not None:
            try:
                LOGGER.debug(
                    "Using bleak_retry_connector for %s connection establishment",
                    self.mac_address,
                )
                return await establish_connection(
                    BleakClient,
                    target,
                    self.mac_address,
                )
            except AttributeError as exc:
                # Some environments require a BLEDevice object instead of an address string.
                # Fall back to plain BleakClient.connect() instead of failing the runtime loop.
                LOGGER.debug(
                    "bleak_retry_connector incompatible for %s with address-only connect "
                    "(%s); falling back to BleakClient.connect()",
                    self.mac_address,
                    exc,
                )

        client = BleakClient(target)
        await client.connect()
        return client

    def _require_client(self) -> BleakClient:
        client = self._client
        if client is None:
            raise RuntimeError("BLE client is not initialized")
        return client

    def _handle_notification(self, _sender: int, data: bytearray) -> None:
        payload = bytes(data)
        try:
            frame = parse_modbus_read_frame(payload, self.start_register)
        except ValueError as exc:
            LOGGER.warning("Notification could not be parsed: %s", exc)
            return

        callback = self._frame_callback
        if callback is None:
            return
        try:
            maybe_coro = callback(frame, payload)
            if inspect.isawaitable(maybe_coro):
                asyncio.create_task(maybe_coro)
        except Exception as callback_error:  # pragma: no cover - defensive logging
            LOGGER.exception("Frame callback raised an exception: %s", callback_error)


async def fetch_registers_once(
    mac_address: str,
    *,
    start_register: int = MODBUS_READ_START,
    register_count: int = MODBUS_READ_COUNT,
    device_address: int = MODBUS_DEVICE_ADDRESS,
    function_code: int = MODBUS_FCN_READ_INPUT_REGISTER,
    timeout: float = 10.0,
) -> ModbusReadFrame:
    """Convenience helper that returns the first register frame observed."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[ModbusReadFrame] = loop.create_future()

    async with FossibotBleClient(
        mac_address,
        start_register=start_register,
        register_count=register_count,
        device_address=device_address,
        function_code=function_code,
    ) as client:
        await client.subscribe_notifications(
            lambda frame, _payload: future.done() or future.set_result(frame)
        )
        try:
            await client.send_registers_read_request()
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            await client.stop_notifications()


async def stream_register_frames(
    mac_address: str,
    *,
    start_register: int = MODBUS_READ_START,
    register_count: int = MODBUS_READ_COUNT,
    device_address: int = MODBUS_DEVICE_ADDRESS,
    function_code: int = MODBUS_FCN_READ_INPUT_REGISTER,
) -> AsyncIterator[Tuple[ModbusReadFrame, bytes]]:
    """Yield Modbus frames continuously until cancelled."""
    client = FossibotBleClient(
        mac_address,
        start_register=start_register,
        register_count=register_count,
        device_address=device_address,
        function_code=function_code,
    )
    await client.connect()

    queue: asyncio.Queue[Tuple[ModbusReadFrame, bytes]] = asyncio.Queue()

    def _queue_frame(frame: ModbusReadFrame, payload: bytes) -> None:
        queue.put_nowait((frame, payload))

    await client.subscribe_notifications(_queue_frame)
    await client.send_registers_read_request()

    try:
        while True:
            yield await queue.get()
    finally:
        await client.stop_notifications()
        with suppress(Exception):
            await client.disconnect()


__all__ = [
    "SERVICE_UUID",
    "MODBUS_WRITE_UUID",
    "MODBUS_NOTIFY_UUID",
    "FossibotBleClient",
    "fetch_registers_once",
    "stream_register_frames",
]
