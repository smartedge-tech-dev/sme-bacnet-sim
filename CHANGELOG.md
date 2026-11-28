# Changelog

All notable changes to SME BACnetSim are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.5.2] - 2026-11-28

### Fixed
- Windows executable: started without `-c`, the config is now `~/.sme-bacnet-sim/config.yaml` (created from the
  bundled demo config on the first run). It used to be the demo config inside the temporary PyInstaller extraction
  directory, so every change saved from the web UI was lost when the exe exited. `-c FILE`, pip, source and Docker
  runs are unchanged.

## [0.5.1] - 2026-11-26

### Added
- Web UI: **Save as device template** button in the device header saves the selected device as a user device
  template (`POST /api/templates/from-device/{id}`), asking before it overwrites an existing one; the template is
  available in **Add device** at once. Documented under Behaviors & templates.

## [0.5.0] - 2026-11-25

BACnetSim is now built on [sme-sim-common](https://pypi.org/project/sme-sim-common/) 1.x, the shared base of the
SME simulator series (web shell, standard HTTP routes, behaviors, templates, Excel workbook and CLI helpers).
Configs, Excel point lists and EDE files from 0.4.0 load unchanged; Excel exports are cell-identical to 0.4.0.

### Changed (breaking)
- **Python 3.11 or later** is required (was 3.10). FastAPI, PyYAML, python-multipart and openpyxl now come with
  `sme-sim-common[xlsx]>=1.0,<2`.
- Excel point-list export moved to `GET /api/config/xlsx`; `GET /api/config/export?format=xlsx` now returns 400
  (`format=yaml|json|ede` are unchanged).
- `POST /api/devices` and `POST /api/devices/{id}/duplicate` return `{"ok": true, "name": <device id>, "device": {...}}`
  (duplicate returned `{"device_id", "name"}`).
- Event log entries (`/api/state`, `/ws`) carry `level` and `message` (was `text`); the BACnet category stays in `kind`.
- Error responses use the sme-sim-common body (`detail` plus `error`); Excel import row errors are listed in `errors`.

### Added
- CLI: `--http-port` for the web UI port (`--port` is still accepted), `--browser` to open the web UI in the
  default browser (still off by default; `--no-browser`), `--templates-dir` for user templates, `--version`, and
  `sme-bacnet-sim validate CONFIG` to check a config file without starting the simulator (exit code 2 on errors).
- HTTP API: `GET /api/version`, `POST /api/templates/reload`, `POST /api/templates/from-device/{id}` (save a device
  as a user template).

### Changed
- Web UI uses the shared sme-sim-common shell (menus, About / Help, event log, dialogs, light / dark theme); the
  brand blue accent, default port 8080 and the browser storage key are unchanged.
- *File → Import* sends every file type (YAML, JSON, Excel `.xlsx`, EDE `.csv` / `.zip`) to `POST /api/config/import`.
- Duplicating a device still uses the first free device ID after the source (skipping the router's device ID).
- Excel: the cell-limit warning uses the shared wording (`Devices row 3, column 'description': longer than 32767
  characters (Excel cell limit), left out`); with errors on several sheets, errors are listed sheet by sheet after
  all sheets are read.
- Docker image starts the web UI with `--http-port 8080`.
- Excel import: `Network` rows now override the running network / simulation settings key by key; keys that are
  not listed or have an empty value keep their running value (they used to fall back to the defaults) (#8).

### Fixed
- Device list subtitle (`device {id} · address …`) and the missing Japanese / Chinese label for BBMD mode in the network dialog.

## [0.4.0] - 2026-11-24

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

[Unreleased]: https://github.com/smartedge-tech-dev/sme-bacnet-sim/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/smartedge-tech-dev/sme-bacnet-sim/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/smartedge-tech-dev/sme-bacnet-sim/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/smartedge-tech-dev/sme-bacnet-sim/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/smartedge-tech-dev/sme-bacnet-sim/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/smartedge-tech-dev/sme-bacnet-sim/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/smartedge-tech-dev/sme-bacnet-sim/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/smartedge-tech-dev/sme-bacnet-sim/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/smartedge-tech-dev/sme-bacnet-sim/releases/tag/v0.1.0
