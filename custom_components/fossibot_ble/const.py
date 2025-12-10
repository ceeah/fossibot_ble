"""Constants for the FossiBOT Home Assistant integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "fossibot_ble"
PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONF_MAC = "mac"
CONF_DEVICE_NAME = "device_name"

SIGNAL_UPDATE = "fossibot_update_signal"
SIGNAL_AVAILABILITY = "fossibot_availability_signal"

MIN_RECONNECT_DELAY = 5
MAX_RECONNECT_DELAY = 120
KEEPALIVE_INTERVAL = 90  # seconds between data sanity checks
MAX_KEEPALIVE_MISSES = 2  # reconnect after this many missed frames
