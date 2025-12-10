# FossiBOT Home Assistant integration over BLE

This integration exposes local telemetry from FossiBOT F2400 power stations.
It uses ble for local connection to the power station and therefore requires no extra cloud connectivity.

## Installation

1. Copy `custom_components/fossibot` into your Home Assistant `config` directory.
2. Restart Home Assistant so it discovers the integration.
3. Ensure Home Assistant’s Bluetooth integration is enabled for devices to be discovered.
