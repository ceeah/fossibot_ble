"""Reusable utilities for interacting with FossiBOT/BrightEMS Modbus registers."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

# Modbus read configuration derived from ble packet analysis
MODBUS_DEVICE_ADDRESS = 0x11
MODBUS_READ_START = 0x0000
MODBUS_READ_COUNT = 0x0055
MODBUS_FCN_READ_INPUT_REGISTER = 0x04  # Read Input Registers


@dataclass(frozen=True)
class RegisterDefinition:
    name: str
    unit: str = ""
    description: str = ""
    possible_values: Optional[Sequence[int]] = None
    scale: float = 1
    value_labels: Optional[Dict[int, str]] = None


@dataclass(frozen=True)
class ModbusReadFrame:
    device_address: int
    function_code: int
    start_register: int
    register_values: Sequence[int]


@dataclass(frozen=True)
class RegisterReading:
    address: int
    name: str
    raw_value: int
    formatted_value: str
    notes: str
    metadata: Optional[RegisterDefinition] = None


# Input register (function 0x04) map
REGISTER_CHARGING_CURRENT_SETTING = 2
REGISTER_DC_INPUT_POWER = 4
REGISTER_TOTAL_INPUT = 6
REGISTER_AC_OUTPUT_VOLTAGE = 18
REGISTER_AC_OUTPUT_FREQUENCY = 19
REGISTER_AC_INPUT_VOLTAGE = 21
REGISTER_AC_INPUT_FREQUENCY = 22
REGISTER_TOTAL_OUTPUT = 39
REGISTER_ACTIVE_OUTPUT_LIST = 41
REGISTER_STATE_OF_CHARGE = 56
REGISTER_REMAINING_DISCHARGE_TIME = 59

# The vendor API exposes many more registers, but the BLE telemetry for
# these addresses is currently unreliable. Keep the symbolic names here for
# reference, but do not surface them in decoded output until confirmed:
# REGISTER_AC_CHARGING_RATE = 13
# REGISTER_MAXIMUM_CHARGING_CURRENT = 20
# REGISTER_STATE_OF_CHARGE_SLAVE_1 = 53
# REGISTER_STATE_OF_CHARGE_SLAVE_2 = 55
# REGISTER_AC_SILENT_CHARGING = 57
# REGISTER_AC_STANDBY_TIME = 60
# REGISTER_DC_STANDBY_TIME = 61
# REGISTER_SCREEN_REST_TIME = 62
# REGISTER_STOP_CHARGE_AFTER = 63
# REGISTER_DISCHARGE_LOWER_LIMIT = 66
# REGISTER_AC_CHARGE_LIMIT = 67
# REGISTER_SLEEP_TIME = 68
# REGISTER_REMAINING_CHARGE_TIME = 71
# REGISTER_REMAINING_DISCHARGE_ESTIMATE = 72

MINUTE_STANDBY_REGISTERS: set[int] = {
    REGISTER_REMAINING_DISCHARGE_TIME,
}


INPUT_REGISTER_DEFINITIONS: Dict[int, RegisterDefinition] = {
    REGISTER_DC_INPUT_POWER: RegisterDefinition(
        name="DC Input Power",
        unit="W",
        description="Wattage arriving from XT60/PV/car inputs",
    ),
    REGISTER_TOTAL_INPUT: RegisterDefinition(
        name="Total Input Power",
        unit="W",
        description="Sum of AC and DC charging inputs reported by the inverter",
    ),
    REGISTER_CHARGING_CURRENT_SETTING: RegisterDefinition(
        name="Charging current setting",
        value_labels={
            1: "300 W",
            2: "500 W",
            3: "700 W",
            4: "900 W",
            5: "1100 W",
        },
        description="Selects AC charging power level",
    ),
    REGISTER_TOTAL_OUTPUT: RegisterDefinition(
        name="Total Output Power", unit="W", description="Combined AC/DC load draw"
    ),
    REGISTER_AC_OUTPUT_VOLTAGE: RegisterDefinition(
        name="AC Output Voltage",
        unit="V",
        scale=0.1,
        description="RMS voltage measured at the inverter output",
    ),
    REGISTER_AC_OUTPUT_FREQUENCY: RegisterDefinition(
        name="AC Output Frequency",
        unit="Hz",
        scale=0.1,
        description="Output frequency while the inverter is active",
    ),
    REGISTER_AC_INPUT_VOLTAGE: RegisterDefinition(
        name="AC Input Voltage",
        unit="V",
        scale=0.1,
        description="Grid passthrough voltage measurement",
    ),
    REGISTER_AC_INPUT_FREQUENCY: RegisterDefinition(
        name="AC Input Frequency",
        unit="Hz",
        scale=0.01,
        description="Grid frequency measurement",
    ),
    REGISTER_ACTIVE_OUTPUT_LIST: RegisterDefinition(
        name="Active outputs list",
        description="Bitfield describing AC/DC/USB output states",
    ),
    REGISTER_STATE_OF_CHARGE: RegisterDefinition(
        name="Charge Level",
        unit="%",
        scale=0.1,
        description="Main battery SOC (0.1% increments)",
    ),
    REGISTER_REMAINING_DISCHARGE_TIME: RegisterDefinition(
        name="Remaining Discharge Time",
        unit="minutes",
        description="Estimated minutes until depletion at current load",
    ),
}

ALL_REGISTER_DEFINITIONS: Dict[int, RegisterDefinition] = {
    **INPUT_REGISTER_DEFINITIONS,
}

REGISTER_BIT_LABELS = {
    REGISTER_ACTIVE_OUTPUT_LIST: {
        0: "Reserved/unknown",
        1: "AC input detected (passthrough relay)",
        2: "AC output state",
        3: "AC inverter cooling",
        4: "AC output enabled",
        5: "AC load detected",
        6: "AC grid sense",
        7: "DC subsystem enabled",
        8: "DC rail status",
        9: "USB outputs",
        10: "DC outputs",
        11: "AC output auxiliary rail",
        12: "LED light",
    }
}


def build_read_registers_request(
    device_address: int, start_register: int, register_count: int, *, function_code: int = MODBUS_FCN_READ_INPUT_REGISTER
) -> bytes:
    """Construct a Modbus RTU frame for function 0x04/0x03 reads."""
    message = bytearray()
    message.append(device_address)
    message.append(function_code)
    message.extend(start_register.to_bytes(2, byteorder="big"))
    message.extend(register_count.to_bytes(2, byteorder="big"))
    message.extend(modbus_crc(message))
    return bytes(message)


def modbus_crc(payload: bytes) -> bytes:
    crc = 0xFFFF
    for byte in payload:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc.to_bytes(2, byteorder="big")  # FossiBOT packets expect big-endian CRC


def parse_modbus_read_frame(
    payload: bytes, fallback_start: int = MODBUS_READ_START
) -> ModbusReadFrame:
    """Validate and unpack a binary Modbus response."""
    if len(payload) < 5:
        raise ValueError("Frame too short to be a Modbus response")

    data = payload[:-2]
    incoming_crc = payload[-2:]
    expected_crc = modbus_crc(data)
    if incoming_crc != expected_crc:
        raise ValueError(
            f"CRC mismatch (expected {expected_crc.hex()}, received {incoming_crc.hex()})"
        )

    device_address = data[0]
    function_code = data[1]
    byte_count = data[2]
    register_blob = data[3:]

    if byte_count and byte_count == len(register_blob):
        if byte_count % 2:
            raise ValueError("Register payload length must be an even number of bytes")
        registers = [
            int.from_bytes(register_blob[i : i + 2], byteorder="big")
            for i in range(0, byte_count, 2)
        ]
        return ModbusReadFrame(
            device_address=device_address,
            function_code=function_code,
            start_register=fallback_start,
            register_values=registers,
        )

    if len(data) >= 6:
        start_register = int.from_bytes(data[2:4], byteorder="big")
        register_count = int.from_bytes(data[4:6], byteorder="big")
        register_blob = data[6:]
        if len(register_blob) != register_count * 2:
            raise ValueError(
                f"Register count {register_count} did not match payload length {len(register_blob)}"
            )
        registers = [
            int.from_bytes(register_blob[i : i + 2], byteorder="big")
            for i in range(0, len(register_blob), 2)
        ]
        return ModbusReadFrame(
            device_address=device_address,
            function_code=function_code,
            start_register=start_register,
            register_values=registers,
        )

    raise ValueError("Unrecognized Modbus response layout")


def format_register_value(
    register: int, raw_value: int, register_definitions: Dict[int, RegisterDefinition]
) -> str:
    """Convert a raw register value into a formatted string."""
    meta = register_definitions.get(register)
    if not meta:
        return str(raw_value)

    if register == REGISTER_ACTIVE_OUTPUT_LIST:
        bit_description = describe_bitfield(register, raw_value, detailed=True)
        return f"0x{raw_value:04X} ({format_bit_groups(raw_value)}){bit_description}"

    if meta.unit == "boolean":
        return "ON" if raw_value else "OFF"

    if register in MINUTE_STANDBY_REGISTERS:
        return format_duration_minutes(raw_value)

    value = raw_value * meta.scale
    if isinstance(value, float):
        value_str = f"{value:.1f}" if not value.is_integer() else str(int(value))
    else:
        value_str = str(value)

    suffix = ""
    if meta.unit in {"W", "%"}:
        suffix = meta.unit
    elif meta.unit == "permille":
        suffix = "%"
    elif meta.unit == "minutes":
        suffix = "min"
    elif meta.unit == "hours":
        suffix = "h"
    elif meta.unit == "seconds":
        suffix = "s"

    if suffix:
        value_str = f"{value_str} {suffix}"

    if meta.value_labels and raw_value in meta.value_labels:
        value_str = f"{value_str} ({meta.value_labels[raw_value]})"

    return value_str


def build_register_note(meta: Optional[RegisterDefinition], raw_value: int) -> str:
    """Return any auxiliary notes for a formatted register line."""
    if meta is None:
        return ""
    notes: List[str] = []
    if meta.description:
        notes.append(meta.description)
    if meta.possible_values and raw_value not in meta.possible_values:
        valid = ", ".join(str(v) for v in meta.possible_values)
        notes.append(f"Expected one of [{valid}]")
    return " ".join(notes)


def format_duration_minutes(minutes: int) -> str:
    """Format a duration in minutes using h/m components."""
    hours, mins = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if mins or not parts:
        parts.append(f"{mins}m")
    return " ".join(parts)


def format_bit_groups(value: int) -> str:
    """Return a grouped 16-bit binary string."""
    bit_string = f"{value:016b}"
    return " ".join(bit_string[i : i + 4] for i in range(0, 16, 4))


def describe_bitfield(register: int, value: int, detailed: bool = False) -> str:
    """Generate either a terse or detailed description for a bitfield."""
    labels = REGISTER_BIT_LABELS.get(register)
    if not labels:
        return ""
    lines: List[str] = []
    for bit in range(0, 16):
        name = labels.get(bit, f"Bit {bit}")
        state = "1" if value & (1 << bit) else "0"
        if detailed:
            lines.append(f"{state} - {name}")
        elif state == "1":
            lines.append(name)
    if detailed:
        return "\n        " + "\n        ".join(lines)
    if not lines:
        return "[none]"
    return "[" + ", ".join(lines) + "]"


def decode_registers(frame: ModbusReadFrame) -> List[RegisterReading]:
    """Produce a list of structured register readings for integrations."""
    readings: List[RegisterReading] = []
    for offset, raw_value in enumerate(frame.register_values):
        address = frame.start_register + offset
        meta = INPUT_REGISTER_DEFINITIONS.get(address)
        if not meta:
            continue
        formatted = format_register_value(address, raw_value, INPUT_REGISTER_DEFINITIONS)
        notes = build_register_note(meta, raw_value)
        readings.append(
            RegisterReading(
                address=address,
                name=meta.name,
                raw_value=raw_value,
                formatted_value=formatted,
                notes=notes,
                metadata=meta,
            )
        )
    return readings


__all__ = [
    "MODBUS_DEVICE_ADDRESS",
    "MODBUS_READ_START",
    "MODBUS_READ_COUNT",
    "MODBUS_FCN_READ_INPUT_REGISTER",
    "RegisterDefinition",
    "RegisterReading",
    "ModbusReadFrame",
    "build_read_registers_request",
    "parse_modbus_read_frame",
    "decode_registers",
    "ALL_REGISTER_DEFINITIONS",
]
