# FossiBOT Home Assistant integration over BLE

This integration exposes local telemetry from FossiBOT F2400 power stations.
It uses ble for local connection to the power station and therefore requires no extra cloud connectivity. For now it only reads  telemetry values, but can be extended to control the device as well with more research.

## ⚠️ Disclaimer

This integration is **unofficial** and not affiliated with or endorsed by Fossibot, Sydpower, or BrightEMS.

**USE AT YOUR OWN RISK.** The author is not responsible for any damage to your devices, loss of data, or any other issues that may arise from using this integration. This is provided as-is with no warranty or guarantees of any kind.

**Status:** This project is a new implementation of a relatively new API. Consider this code alpha.

Contributions are welcomed.

## Credits

Kudos to https://github.com/iamslan/fossibot whose code was heavily used during research

## Installation

1. Copy `custom_components/fossibot` into your Home Assistant `config` directory.
2. Restart Home Assistant so it discovers the integration.
3. Ensure Home Assistant’s Bluetooth integration is enabled for devices to be discovered.

## Research documentation

For those who are interested how it works, here is a [writeup on the protocol](docs/fossibot.md).

## Sensors

![Sensors](/docs/sensors.png?raw=true "Sensors")