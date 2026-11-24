# Device management services

Each simulated device also serves (bacpypes3 0.1.0 leaves most of these unimplemented or broken on the server
side, so the simulator implements them in `sme_bacnet_sim/engine.py` / `sme_bacnet_sim/devmgmt.py`):

- **COV increment default** (analog objects without `cov_increment`): a point with a `behavior` (it changes
  every tick) gets 1 % of its span (`min` / `max` of the object, else `min` / `max` of the behavior), else a
  per-unit default (0.1 for °C / kW / kWh / A, 0.5 for % / %RH / V / m³/h, 1 for W / Pa, 5 for ppm / lx / W/m²,
  0.01 Hz; see `_UNIT_COV` in `sme_bacnet_sim/engine.py`), else `0`; points without a behavior keep `0` (= any change).
  Set `cov_increment` explicitly to override.
- **SubscribeCOV** (confirmed / unconfirmed, with lifetime) on all value objects: a notification on a
  presentValue change of at least `covIncrement` (analog), whether it comes from a behavior, a BACnet write or the UI, and on any status-flags change
  (alarm, fault, out-of-service). **SubscribeCOVProperty** on any property, with the client's COV increment
  (default: the object's `covIncrement` for present-value); the notification carries the property and the
  status flags.
- **CreateObject / DeleteObject** for value objects (AI/AO/AV/BI/BO/BV/MSI/MSO/MSV, Accumulator, Pulse Converter), by object type (first free
  instance) or by object identifier, with optional initial values: object-name, present-value, description,
  units / cov-increment (analog), active-text / inactive-text (binary), state-text (multi-state, default
  `State 1`, `State 2`), out-of-service. A created object is appended to the device's `objects` in the
  running config (so Save / Export keep it) and appears in the UI at once. Deleting removes it from `objects`;
  if the object comes from a template its name is added to the device's `removed` list, which template
  expansion skips (remove the name from `removed` to get the template object back; creating an object with
  that name also drops it from `removed`). Not deletable (`object` / `object-deletion-not-permitted`): the
  device object, network ports, trend logs, schedules, calendars, notification classes, and value objects
  logged by a trend log or written by a schedule. Errors on create use CreateObject-Error with the failing
  element number (`dynamic-creation-not-supported`, `object-identifier-already-exists`, `duplicate-name`,
  `write-access-denied` for other properties, `invalid-data-type`).
- **TimeSynchronization / UTCTimeSynchronization** (to a device, or to the router / broadcast): moves the
  simulated clock so that it shows the received time (UTC is converted with the host's time zone); the
  elapsed simulated time keeps running, schedules are re-evaluated at once and trend logs continue on the new
  clock. *Simulation → Sync to PC clock* (or `POST /api/simulation {"set_time": ...}`) does the same from the UI.
- **DeviceCommunicationControl** enable / disable / disable-initiation with an optional time duration in
  minutes, measured on the **wall clock** (the duration is a real-world timeout in the standard, independent of
  the simulation speed). While disabled the device ignores everything except DeviceCommunicationControl and
  ReinitializeDevice and sends nothing (no I-Am, COV or event notifications); disable-initiation still answers
  requests and Who-Is but initiates nothing else. The device header in the UI shows the state with an
  *Enable communication* button.
- **ReinitializeDevice** warmstart: values back to the configured initial values, priority arrays
  relinquished, out-of-service cleared, behaviors and alarms (event state normal, all acknowledged) reset,
  communication re-enabled. Coldstart: the same, and trend-log buffers are cleared. Other states return
  `services` / `optional-functionality-not-supported`.

Device keys for these services:

```yaml
  - device_id: 1002
    name: AC-1F-East
    dcc_password: secret      # DeviceCommunicationControl password (default: none = not checked)
    reinit_password: boot     # ReinitializeDevice password (default: none = not checked)
    removed: [FilterAlarm]    # template objects deleted with DeleteObject (written by the simulator)
```

A wrong password returns `security` / `password-failure`.
