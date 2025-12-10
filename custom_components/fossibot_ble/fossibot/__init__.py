"""Public package surface for FossiBOT research utilities.

The `fossibot` package exposes modules for talking to the FossiBOT
power station over BLE (see :mod:`fossibot.ble`) and helpers for working
with the embedded Modbus register map (:mod:`fossibot.modbus`).
"""

from .ble import (
    MODBUS_NOTIFY_UUID,
    MODBUS_WRITE_UUID,
    SERVICE_UUID,
    FossibotBleClient,
    fetch_registers_once,
    stream_register_frames,
)
from .modbus import (  # noqa: F401
    ALL_REGISTER_DEFINITIONS,
    MODBUS_DEVICE_ADDRESS,
    MODBUS_FCN_READ_INPUT_REGISTER,
    MODBUS_READ_COUNT,
    MODBUS_READ_START,
    RegisterDefinition,
    RegisterReading,
    ModbusReadFrame,
    build_read_registers_request,
    decode_registers,
    format_bit_groups,
    format_register_value,
    parse_modbus_read_frame,
)

__all__ = [
    "ALL_REGISTER_DEFINITIONS",
    "MODBUS_DEVICE_ADDRESS",
    "MODBUS_FCN_READ_INPUT_REGISTER",
    "MODBUS_NOTIFY_UUID",
    "MODBUS_READ_COUNT",
    "MODBUS_READ_START",
    "MODBUS_WRITE_UUID",
    "SERVICE_UUID",
    "FossibotBleClient",
    "ModbusReadFrame",
    "RegisterDefinition",
    "RegisterReading",
    "build_read_registers_request",
    "decode_registers",
    "format_bit_groups",
    "format_register_value",
    "fetch_registers_once",
    "parse_modbus_read_frame",
    "stream_register_frames",
]
