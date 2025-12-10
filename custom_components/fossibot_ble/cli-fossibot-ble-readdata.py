#!/usr/bin/env python3
"""
BLE Modbus monitor for FossiBOT/BrightEMS devices.

This script connects to the portable power station over BLE, sends a
Modbus “Read Input Registers” request, and pretty-prints the response.
Known registers are decoded into human-friendly units (watts, percentages, booleans, etc.)
using the shared `fossibot.modbus` helpers, while keeping the reusable
library slim for Home Assistant integration work.

Usage: python3 fossibot-ble-readdata.py [--raw] [--mac ...] [--poll]
"""

import argparse
import asyncio
import logging
from typing import Dict, Mapping, Sequence

from fossibot import (
    ALL_REGISTER_DEFINITIONS,
    FossibotBleClient,
    RegisterDefinition,
    ModbusReadFrame,
    format_register_value,
)

DEFAULT_DEVICE_MAC = "34:CD:B0:6F:73:1A"


class RegisterNotificationPrinter:
    """CLI helper that mirrors BLE notifications to stdout."""

    def __init__(
        self,
        *,
        show_unknown_changes: bool = True,
        show_raw_values: bool = False,
        register_definitions: Mapping[int, RegisterDefinition] = ALL_REGISTER_DEFINITIONS,
    ) -> None:
        self._show_unknown_changes = show_unknown_changes
        self._show_raw_values = show_raw_values
        self._register_definitions = register_definitions
        self._previous_registers: Dict[int, Dict[int, int]] = {}

    def handle_frame(self, frame: ModbusReadFrame) -> None:
        """Process a parsed Modbus frame emitted by the BLE monitor."""
        print(
            f"\n🔔 Notification "
            f"(device {frame.device_address:#02x}, function:{frame.function_code:#02x}, "
            f"{len(frame.register_values)} registers)"
        )
        if self._show_unknown_changes:
            self._report_unknown_changes(frame)
        pretty_print_register_block(
            frame.register_values,
            frame.start_register,
            self._register_definitions,
            show_raw_values=self._show_raw_values,
        )
        if self._show_raw_values:
            hex_words = " ".join(f"{value:04X}" for value in frame.register_values)
            print(f"    Raw registers: {hex_words}")

    def _report_unknown_changes(self, frame: ModbusReadFrame) -> None:
        """Print any changes in registers we don't yet understand."""
        current = {
            frame.start_register + offset: value
            for offset, value in enumerate(frame.register_values)
        }

        previous_map = self._previous_registers.get(frame.function_code)
        if previous_map is None:
            self._previous_registers[frame.function_code] = current
            return

        changes = []
        for register, value in current.items():
            if register in self._register_definitions:
                continue
            previous_value = previous_map.get(register)
            if previous_value is None or previous_value == value:
                continue
            changes.append((register, previous_value, value))

        if changes:
            print("    Unknown register changes detected:")
            for register, old, new in sorted(changes):
                print(f"      - Reg {register}: {old} -> {new}")

        self._previous_registers[frame.function_code] = current


def pretty_print_register_block(
    register_values: Sequence[int],
    start_register: int,
    register_definitions: Mapping[int, RegisterDefinition],
    *,
    show_raw_values: bool = False,
) -> None:
    """Render a table of register values with optional raw column."""
    interesting_registers = sorted(register_definitions.keys())
    header = f"{'Reg':>4}  {'Name':<32} {'Value':<20} Raw"
    print(header)
    print("-" * len(header))

    for register in interesting_registers:
        index = register - start_register
        if index < 0 or index >= len(register_values):
            continue
        meta = register_definitions[register]
        raw_value = register_values[index]
        formatted = format_register_value(register, raw_value, register_definitions)
        if show_raw_values:
            formatted = f"{formatted} (raw:{raw_value})"
        print(f"{register:>4}  {meta.name:<32} {formatted:<20} {raw_value}")
        note = build_register_note(meta, raw_value)
        if note:
            print(f"      ↳ {note}")


def build_register_note(meta: RegisterDefinition, raw_value: int) -> str:
    """Return any auxiliary notes for a formatted register line."""
    notes = []
    if meta.description:
        notes.append(meta.description)
    if meta.possible_values and raw_value not in meta.possible_values:
        valid = ", ".join(str(v) for v in meta.possible_values)
        notes.append(f"Expected one of [{valid}]")
    return " ".join(notes)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor FossiBOT data over BLE")
    parser.add_argument(
        "--raw",
        dest="show_raw_values",
        action="store_true",
        help="Display raw register values",
    )
    parser.add_argument(
        "--mac",
        dest="mac_address",
        type=str,
        default=DEFAULT_DEVICE_MAC,
        help=f"Device MAC address (default: {DEFAULT_DEVICE_MAC})",
    )
    parser.add_argument(
        "--poll",
        dest="poll",
        action="store_true",
        help="Poll the device updates indefinitely",
    )
    return parser.parse_args()


async def run_monitor(args: argparse.Namespace) -> None:
    """Entrypoint that wires CLI concerns into the shared BLE helper."""
    printer = RegisterNotificationPrinter(show_raw_values=args.show_raw_values)
    queue: asyncio.Queue = asyncio.Queue()

    def _handle_frame(frame: ModbusReadFrame, _payload: bytes) -> None:
        queue.put_nowait(frame)

    power_station = FossibotBleClient(args.mac_address)
    await power_station.connect()
    try:
        await power_station.subscribe_notifications(_handle_frame)
        # Ask device to send us first data right away
        await power_station.send_registers_read_request()

        if args.poll:
            print("Polling for data updates. Press Ctrl+C to stop.")
            while True:
                frame = await queue.get()
                printer.handle_frame(frame)
        else:
            print("Fetching data from device...")
            frame = await queue.get()
            printer.handle_frame(frame)
    finally:
        await power_station.stop_notifications()
        await power_station.disconnect()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )


if __name__ == "__main__":
    configure_logging()
    cli_args = parse_args()
    try:
        asyncio.run(run_monitor(cli_args))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[I] Caught Ctrl+C, stopping monitor…")
    except Exception as exc:
        print(f"[E] Monitor failed: {exc}")
