"""Binary sensor entities derived from FossiBOT register bitfields."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .fossibot.modbus import REGISTER_ACTIVE_OUTPUT_LIST

from .const import DOMAIN
from .runtime import FossibotRuntime


@dataclass
class FossibotBinarySensorDescription(BinarySensorEntityDescription):
    """Metadata for a bit-backed FossiBOT binary sensor."""

    register: int = 0
    bit: int = 0


ACTIVE_OUTPUT_SENSORS: tuple[FossibotBinarySensorDescription, ...] = (
    FossibotBinarySensorDescription(
        key="ac_input_detected",
        name="AC Input Detected",
        register=REGISTER_ACTIVE_OUTPUT_LIST,
        bit=1,
    ),
    FossibotBinarySensorDescription(
        key="ac_output_state",
        name="AC Output State",
        register=REGISTER_ACTIVE_OUTPUT_LIST,
        bit=2,
    ),
    FossibotBinarySensorDescription(
        key="ac_inverter_cooling",
        name="AC Inverter Cooling",
        register=REGISTER_ACTIVE_OUTPUT_LIST,
        bit=3,
    ),
    FossibotBinarySensorDescription(
        key="ac_output_enabled",
        name="AC Output Enabled",
        register=REGISTER_ACTIVE_OUTPUT_LIST,
        bit=4,
    ),
    FossibotBinarySensorDescription(
        key="ac_load_detected",
        name="AC Load Detected",
        register=REGISTER_ACTIVE_OUTPUT_LIST,
        bit=5,
    ),
    FossibotBinarySensorDescription(
        key="ac_grid_sense",
        name="AC Grid Sense",
        register=REGISTER_ACTIVE_OUTPUT_LIST,
        bit=6,
    ),
    FossibotBinarySensorDescription(
        key="dc_subsystem_enabled",
        name="DC Subsystem Enabled",
        register=REGISTER_ACTIVE_OUTPUT_LIST,
        bit=7,
    ),
    FossibotBinarySensorDescription(
        key="dc_rail_status",
        name="DC Rail Active",
        register=REGISTER_ACTIVE_OUTPUT_LIST,
        bit=8,
    ),
    FossibotBinarySensorDescription(
        key="usb_outputs",
        name="USB Outputs Active",
        register=REGISTER_ACTIVE_OUTPUT_LIST,
        bit=9,
    ),
    FossibotBinarySensorDescription(
        key="dc_outputs",
        name="DC Outputs Active",
        register=REGISTER_ACTIVE_OUTPUT_LIST,
        bit=10,
    ),
    FossibotBinarySensorDescription(
        key="ac_auxiliary_rail",
        name="AC Auxiliary Rail",
        register=REGISTER_ACTIVE_OUTPUT_LIST,
        bit=11,
    ),
    FossibotBinarySensorDescription(
        key="led_light",
        name="LED Light",
        register=REGISTER_ACTIVE_OUTPUT_LIST,
        bit=12,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up FossiBOT binary sensors."""
    runtime: FossibotRuntime = hass.data[DOMAIN][entry.entry_id]
    entities = [
        FossibotRegisterBinarySensor(runtime, description)
        for description in ACTIVE_OUTPUT_SENSORS
    ]
    async_add_entities(entities)


class FossibotRegisterBinarySensor(BinarySensorEntity):
    """Binary sensor derived from a single bit inside a register."""

    entity_description: FossibotBinarySensorDescription

    def __init__(
        self, runtime: FossibotRuntime, description: FossibotBinarySensorDescription
    ) -> None:
        self._runtime = runtime
        self.entity_description = description
        self._attr_should_poll = False
        self._attr_unique_id = f"{runtime.mac}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.mac)},
            manufacturer="FossiBOT",
            model="F2400",
            name=runtime.device_name,
        )

    async def async_added_to_hass(self) -> None:
        """Attach dispatcher listeners for updates."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self._runtime.update_signal, self._handle_coordinator_update
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                self._runtime.availability_signal,
                self._handle_availability,
            )
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    @callback
    def _handle_availability(self, _available: bool) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._runtime.available and self.is_on is not None

    @property
    def is_on(self) -> bool | None:
        raw = self._runtime.get_register(self.entity_description.register)
        if raw is None:
            return None
        return bool(raw & (1 << self.entity_description.bit))
