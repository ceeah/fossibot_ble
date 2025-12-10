#!/usr/bin/env python3
"""
Simple BLE scanner for FossiBOT/BrightEMS devices.

The script leverages Bleak to discover nearby BLE peripherals and prints the
name/MAC pairs for any device whose advertised name starts with ``POWER-``
(the FossiBOT broadcast prefix). Use ``--timeout`` to tweak how long the scan
runs and ``--prefix`` if you need to experiment with alternative name filters.
"""

import argparse
import asyncio
from typing import Iterable, List

from bleak import BleakScanner

DEFAULT_PREFIX = "POWER-"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan for FossiBOT BLE devices (names starting with POWER-)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Scan duration in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default=DEFAULT_PREFIX,
        help=f"Device name prefix to filter on (default: {DEFAULT_PREFIX!r})",
    )
    return parser.parse_args()


async def scan_devices(timeout: float, prefix: str) -> List[str]:
    """Run a BLE scan and return formatted strings for matching devices."""
    print(f"[I] Starting BLE scan for devices with names beginning {prefix!r}")
    devices = await BleakScanner.discover(timeout=timeout)
    matches: List[str] = []
    for device in devices:
        name = device.name or ""
        if name.startswith(prefix):
            matches.append(f"{name} ({device.address})")
    return matches


def print_results(results: Iterable[str]) -> None:
    """Pretty-print the list of matching devices."""
    results = list(results)
    if not results:
        print("No matching devices discovered. Try increasing --timeout or moving closer.")
        return

    print("\nDiscovered FossiBOT devices:")
    for entry in sorted(results):
        print(f"  - {entry}")


if __name__ == "__main__":
    args = parse_args()
    try:
        discovered = asyncio.run(scan_devices(args.timeout, args.prefix))
    except KeyboardInterrupt:
        print("\n[I] Scan interrupted by user.")
    except Exception as exc:
        print(f"[E] Failed to complete BLE scan: {exc}")
    else:
        print_results(discovered)
