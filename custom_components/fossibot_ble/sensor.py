"""Sensor entities for the FossiBOT integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .fossibot.modbus import (
    REGISTER_AC_INPUT_FREQUENCY,
    REGISTER_AC_INPUT_VOLTAGE,
    REGISTER_AC_OUTPUT_FREQUENCY,
    REGISTER_AC_OUTPUT_VOLTAGE,
    REGISTER_DC_INPUT_POWER,
    REGISTER_REMAINING_DISCHARGE_TIME,
    REGISTER_STATE_OF_CHARGE,
    REGISTER_TOTAL_INPUT,
    REGISTER_TOTAL_OUTPUT,
)

from .const import DOMAIN
from .runtime import FossibotRuntime


@dataclass
class FossibotSensorDescription(SensorEntityDescription):
    """Describes a FossiBOT register-backed sensor."""

    register: int = 0
    scale: float = 1.0
    decimals: Optional[int] = None
    value_fn: Optional[Callable[[int], float | int]] = None


SENSOR_DESCRIPTIONS: tuple[FossibotSensorDescription, ...] = (
    FossibotSensorDescription(
        key="dc_input",
        name="DC Input Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=REGISTER_DC_INPUT_POWER,
    ),
    FossibotSensorDescription(
        key="total_input",
        name="Total Input Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=REGISTER_TOTAL_INPUT,
    ),
    FossibotSensorDescription(
        key="total_output",
        name="Total Output Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        register=REGISTER_TOTAL_OUTPUT,
    ),
    FossibotSensorDescription(
        key="ac_output_voltage",
        name="AC Output Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        register=REGISTER_AC_OUTPUT_VOLTAGE,
        scale=0.1,
        decimals=1,
    ),
    FossibotSensorDescription(
        key="ac_output_frequency",
        name="AC Output Frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        register=REGISTER_AC_OUTPUT_FREQUENCY,
        scale=0.1,
        decimals=1,
    ),
    FossibotSensorDescription(
        key="ac_input_voltage",
        name="AC Input Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        register=REGISTER_AC_INPUT_VOLTAGE,
        scale=0.1,
        decimals=1,
    ),
    FossibotSensorDescription(
        key="ac_input_frequency",
        name="AC Input Frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        register=REGISTER_AC_INPUT_FREQUENCY,
        scale=0.01,
        decimals=2,
    ),
    FossibotSensorDescription(
        key="charge_level",
        name="Charge Level",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        register=REGISTER_STATE_OF_CHARGE,
        scale=0.1,
        decimals=1,
    ),
    FossibotSensorDescription(
        key="remaining_discharge_time",
        name="Remaining Discharge Time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        register=REGISTER_REMAINING_DISCHARGE_TIME,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up FossiBOT sensor entities."""
    runtime: FossibotRuntime = hass.data[DOMAIN][entry.entry_id]
    entities = [FossibotRegisterSensor(runtime, description) for description in SENSOR_DESCRIPTIONS]
    async_add_entities(entities)


class FossibotRegisterSensor(SensorEntity):
    """Representation of a telemetry register exposed as a sensor."""

    entity_description: FossibotSensorDescription

    def __init__(self, runtime: FossibotRuntime, description: FossibotSensorDescription) -> None:
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
        """Attach dispatcher listeners."""
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._runtime.update_signal, self._handle_coordinator_update)
        )
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._runtime.availability_signal, self._handle_availability)
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

    @callback
    def _handle_availability(self, _available: bool) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._runtime.available and self.native_value is not None

    @property
    def native_value(self) -> float | int | None:
        raw = self._runtime.get_register(self.entity_description.register)
        if raw is None:
            return None
        if self.entity_description.value_fn:
            return self.entity_description.value_fn(raw)
        value: float | int = raw * self.entity_description.scale
        if isinstance(value, float) and self.entity_description.decimals is not None:
            value = round(value, self.entity_description.decimals)
        return value
