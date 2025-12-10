# FossiBOT F2400 Protocol Analysis

This document describes the protocols used to talk to Fossibot F2400 power station. It uses the BLE transport, that wraps Modbus protocol inside to read and control the device. By utilizing this protocol we can operate the unit locally without depending on vendor's cloud connection.

## 1. Device & Protocol Overview

- **Model**: FossiBOT F2400 portable AC power station with built‑in battery and multiple DC/AC outputs.
- **Control surface**: A proprietary BLE GATT service wraps a Modbus RTU link; requests are written to one characteristic and responses arrive via notifications.
- **Addressing**: The embedded Modbus slave uses device address `0x11`. We can use function `0x04` (“Read Input Register”), but the firmware also accepts writing the holding register `0x03` writes for configuration.
- **Sampling cadence**: The firmware broadcasts telemetry roughly once per minute, or immediately when a state change occurs (power plugged in, button toggled, etc.). After connecting we send an explicit read command so the first register reading arrives right away, then rely on the device’s own push cadence.

## 2. BLE Transport Layer

| Component                   | UUID                                   | Direction         | Notes                                    |
|-----------------------------|----------------------------------------|-------------------|------------------------------------------|
| Service                     | `0000a002-0000-1000-8000-00805f9b34fb` | Peripheral → Host | Single custom service hosting Modbus IO  |
| Modbus write characteristic | `0000c304-0000-1000-8000-00805f9b34fb` | Write w/o resp    | Send Modbus request frames here          |
| Modbus notify characteristic| `0000c305-0000-1000-8000-00805f9b34fb` | Notify            | Device publishes Modbus responses here   |

**Connection checklist**

1. Device advertises itself as POWER-0084
2. Subscribe to `0xC305` characteristic before sending any requests; otherwise the response may arrive before notifications are enabled.
3. Send Modbus commands to `0xC304`. The device replies on `0xC305`.
4. After subscribing, you can send a read request immediately to fetch register values; afterward the device publishes changes on it's own, so continuous polling is optional unless you need force-refreshes.
5. Device can be controlled by modifying registers in holding register (0x03), but it is out of scope of this document.

The device only supports a single central at a time; a second connection is rejected until the first disconnects or times out.

## 3. Modbus protocol

Modbus is an open serial communications protocol introduced by Modicon (now Schneider Electric) in 1979 to link programmable logic controllers (PLCs) inside industrial plants. Its simplicity, royalty-free specification, and resilience on noisy RS-485 lines helped it spread across SCADA systems, energy meters, HVAC controllers, and countless embedded devices. Modern products often tunnel the same Modbus framing over TCP, BLE, or other links — the FossiBOT F2400 is one such example.

Key concepts to know before working with the F2400:

- **Input registers (`function 0x04`)** – 16-bit read-only values holding telemetry (power readings, timers, status bitfields). Addresses start at `0x0000`; This device has 85 registers.
- **Holding registers (`function 0x03`)** – 16-bit read/write values used for configuration (charge limits, schedules, output toggles). This document concentrates on telemetry, but write requests reuse the same frame structure with function `0x03`.

Modbus RTU frame request structure:
`[device][function][start_hi][start_lo][count_hi][count_lo][CRC_hi][CRC_lo]`
Modbus RTU frame response structure:
`[device][function][byte_count][payload...][CRC_hi][CRC_lo]`
Addresses are zero-based, so “register 2” refers to the third 16-bit slot. Multi-word values use the common big-endian convention (high word first). With this primer, the remaining sections describe how the F2400 transports those frames over BLE.


## 4. Fossibot Modbus Frame Structure

FossiBOT embeds standard Modbus RTU frames (“big‑endian variant”) inside the BLE payloads. Example request to read all the values in input regiser:

```
11 04 00 00 00 55 A5 32
└┘ └┘ └───┘ └───┘ └─── CRC16 (big endian)
|  |  |     |
|  |  |     └─ Number of registers to read (0x0055 = 85)
|  |  └─ Start register address (0x0000)
|  └─ Function code (0x04 Read Input Registers)
└─ Device address (0x11)
```

The response arrives as: `[device][function][byte-count][register values...][CRC_hi][CRC_lo]`.

- **CRC endianness**: Unlike classical Modbus RTU (little‑endian CRC), the FossiBOT implementation expects the CRC bytes in big‑endian order.
- **Frame lengths**: A full `0x04` response for 85 registers is 2 + 1 + 170 + 2 = 175 bytes.
- **Validation**: Always verify CRC and byte count before attempting to parse register values; corrupted packets occasionally occur when RSSI is low.


## 5. Register Map Highlights

The F2400 firmware exposes a large register block. Below are the most useful addresses we decoded. Unless stated otherwise, values are unsigned 16‑bit integers.

| Reg | Name                     | Unit / Scale     | Notes                                                |
|-----|--------------------------|------------------|------------------------------------------------------|
| 2   | Charging current setting | Enumerated       | Values 1–5 map to 300/500/700/900/1100 W AC charging |
| 6   | Total Input              | Watts            | Combined AC+DC input wattage                         |
| 39  | Total Output             | Watts            | Total output power as shown on the screen            |
| 41  | Active outputs list      | Bitmask          | See bit breakdown below                              |
| 56  | Carge level              | % (value ÷ 10)   | Example: raw `894` ⇒ `89.4 %`                       |
| 57  | AC silent charging       | Boolean          | 1 when “silent/eco” AC charging mode is on           |
| 59  | Battery standby time     | Minutes          | Not valid while device is charging                   |

### Register 41 bit layout

`Active outputs list` encodes subsystem states:

| Bit   | Meaning                                              |
|-------|------------------------------------------------------|
| 0     | Reserved/unknown                                     |
| 1     | AC input detected (grid passthrough relay energized) |
| 2     | AC output state (inverter producing power)           |
| 3     | AC inverter cooling fans active                      |
| 4     | AC output enabled flag                               |
| 5     | AC load detected                                     |
| 6     | AC grid sense                                        |
| 7     | DC subsystem enabled                                 |
| 8     | DC rail status                                       |
| 9     | USB outputs                                          |
| 10    | DC outputs (car socket / XT60)                       |
| 11    | AC output auxiliary rail                             |
| 12    | LED light                                            |
| 13‑15 | Unused/unknown                                       |
