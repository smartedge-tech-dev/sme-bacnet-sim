# Changelog

All notable changes to SME BACnetSim are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- BACnet network settings in the web UI (#6): *Edit → BACnet network…* (or a click on the status-bar address)
  picks the network adapter from the local IPv4 interfaces (or auto-detect) and sets the UDP port, IP-side / virtual
  network numbers, router device ID and normal / BBMD / foreign-device mode. Settings are validated (local address,
  free UDP port, network numbers, device IDs), applied without a restart (the BACnet stack rebinds) and the
  `network:` section is written back to the config file. API: `GET/PUT /api/network`.

### Changed
- The `start:` log line names the IP-side network number and the mode (`BBMD` / foreign device of a BBMD) (#7).
- Point table: names, values, units and command buttons wrap so the Command column (e.g. *Relinquish*) stays in
  view on ~1024 px windows in English (#7); `cubic-meters-per-hour` is shown as `m³/h`.
- Docker image installs `tzdata`; set `-e TZ=Asia/Tokyo` etc. for schedules and the UI clock (default UTC) (#7).
- `network.port` (1–65535) and `network.router.device_id` (0–4194302) are range-checked.

### Documentation
- Clients bound to a UDP port other than 47808 do not receive I-Am broadcasts: use the same port or
  `mode: bbmd` + foreign-device registration (#7). Docker `TZ` usage (#7).

## [0.3.0] - 2026-11-24

### Added
- `sme-bacnet-sim record` (#4): poll present-values into a replay CSV (RPM with RP fallback, `--interval` / `--duration` / `--count`, `--resume`) and `--trend-log` (ReadRange of Trend Log buffers); read-only like clone. See `docs/en/cloning.md`.

## [0.2.0] - 2026-11-24

### Added
- CSV time-series replay behavior (#3): `{type: replay, file: data/day.csv, column: oat, interpolate: linear|step, loop: true, offset: "06:00:00"}` plays a CSV column on the simulated clock (follows `time_scale`); one CSV can feed many points, parsed once. Timestamps: `HH:MM:SS`, seconds or ISO datetime. The point row shows the replay position. Example: `configs/replay-example.yaml`.
- Excel point-list import / export (#2): File → Import accepts `.xlsx`, File → Export → Excel point list and
  File → Download blank Excel template (`Devices` / `Points` / `StateTexts` / `Network` sheets). Import errors name
  the sheet, row and column; warnings go to the event log. New dependency: `openpyxl`. See `docs/en/excel.md`.
- `sme-bacnet-sim clone`: read-only clone of real BACnet devices into a simulator config (Who-Is / ReadProperty /
  ReadPropertyMultiple only), for offline tests (#1). See `docs/en/cloning.md`.
- `clone --foreign-bbmd HOST[:PORT]` / `--foreign-ttl`: register as a foreign device with a BBMD to clone devices on
  another subnet; without `--ip` the client binds to the interface that routes to the target (VPN / overlay routes).
- Multi-arch Docker image: `ghcr.io/smartedge-tech-dev/sme-bacnet-sim` is now published for `linux/amd64`,
  `linux/arm64` and `linux/arm/v7` (e.g. Moxa gateways).
- Offline image archives on each release: `sme-bacnet-sim-<ver>-linux-amd64.tar.gz`, `-linux-arm64.tar.gz`,
  `-linux-arm-v7.tar.gz`, for gateways without internet access (`docker load -i <file>.tar.gz`).

### Changed
- The Docker image is built in two stages so dependencies without a wheel for an architecture are compiled in
  the builder stage; the final image carries no compiler.

## [0.1.2] - 2026-11-24

### Fixed
- Event log: messages published around a reload (`pasted ...`, `duplicated ...`, `imported ...`) were shown
  twice in the UI. WebSocket events now carry a sequence number and a message already contained in a
  snapshot is not sent again.
- Calendar date lists and Schedule lists of object property references written by `WriteProperty`,
  `AddListElement` and `RemoveListElement` are now kept in the config (Save / Export). New schedule
  references re-target the schedule; references the schedule cannot write are rejected with
  `value-out-of-range`.
- Recipient lists (and the new list writes) of objects that come from a template are kept as an
  override entry, like alarm properties.
- `Weekly_Schedule`, `Exception_Schedule` and `Schedule_Default` written by a BACnet client are converted
  back to the config keys `weekly` / `exceptions` / `default` and kept for Save / Export. Content the
  config cannot reproduce is logged and not kept.
- Schedules that come from a template get an override entry that also carries `weekly` / `exceptions`,
  so persisted write targets of template schedules are valid.
- macOS / BSD: the interface netmask is read from `ifconfig` instead of falling back to /24.

### Changed
- CI now also runs on macOS.

## [0.1.1] - 2026-11-24

### Fixed
- Windows exe failed to start (`attempted relative import with no known parent package`): PyInstaller now
  starts from an absolute-import entry script.

## [0.1.0] - 2026-11-24

First public release.

> **Known issue:** the Windows exe of this release does not start. Use 0.1.1 or later.

### Added
- Many simulated devices on one UDP port: a built-in BACnet router (default device 4194000) with the
  devices on a virtual network (default 100), so one Who-Is discovers them all. Normal and BBMD modes,
  Foreign Device registration with an external BBMD (`network.foreign_device`, `--foreign-bbmd`).
- Realistic behaviors (room temperature, energy integration, lighting feedback, PV day curve with
  curtailment) and device templates; commandable outputs with a 16-level priority array, out-of-service,
  COV increments, Device and Network Port objects.
- Configuration in YAML / JSON, EDE export, editing a device as YAML in the browser, adding devices from
  templates, saving back to the config file.
- COV subscriptions; alarms with Notification Class and Event Enrollment objects.
- Schedule and Calendar objects, Trend Log, Accumulator, Pulse Converter and Loop.
- File and Program objects with Atomic Read/Write File services, Life Safety Point / Zone.
- Device management services, TextMessage, PrivateTransfer, AddListElement / RemoveListElement.
- Live web UI: values over WebSocket, trend chart per point, event log of BACnet and UI writes,
  property table, copy and paste of devices and objects; English, Japanese and Simplified Chinese.
- Distribution as a Windows exe and a Docker image (`ghcr.io/smartedge-tech-dev/sme-bacnet-sim`).

[Unreleased]: https://github.com/smartedge-tech-dev/sme-bacnet-sim/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/smartedge-tech-dev/sme-bacnet-sim/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/smartedge-tech-dev/sme-bacnet-sim/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/smartedge-tech-dev/sme-bacnet-sim/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/smartedge-tech-dev/sme-bacnet-sim/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/smartedge-tech-dev/sme-bacnet-sim/releases/tag/v0.1.0
