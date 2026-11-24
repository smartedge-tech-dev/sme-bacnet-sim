# EDE import / export

SME BACnetSim reads and writes EDE files (B.I.G.-EU Engineering Data Exchange, layout 2.3), the CSV point list
most BACnet tools and integrators exchange.

- **Export**: the `EDE` button (`GET /api/config/export?format=ede`) downloads a zip with the main file
  `sme-bacnet-sim-ede.csv` (one row per object, plus one device row with object-type 8; numeric object-type and
  unit codes; templates expanded) and the state-text file `sme-bacnet-sim-ede-statetexts.csv`
  (binary objects: Text 1 = inactive, Text 2 = active; multi-state objects: states 1..N).
- **Import**: select the main CSV, optionally together with the state-text CSV (or the exported zip).
  The state-text file is recognised by its header. Semicolon or comma delimiters, UTF-8 (with or without
  BOM) and cp1252 are accepted. Rows are grouped into one device per device instance (name taken from the
  device row, else `Device-<id>`); `settable = Y` on AV/BV/MSV makes the object commandable. Object types
  the simulator does not support are skipped and reported as warnings in the event log. Network and
  simulation settings of the running config are kept; imported objects are static (no behaviors).
- **Trend logs** (object type 20): export writes the trend-log settings into the `vendor-specific-address`
  column as `key=value` pairs separated by `|` (e.g. `log_object=RoomTemp|log_interval=60|logging_type=cov`;
  keys as in YAML), so an exported file re-imports with its trend logs. Files from other tools carry no logged
  object reference; the import then logs `<name>` for a trend log named `<name>_Log` when that object exists,
  else the first analog / binary / multi-state object of the device (polled, 60 s), with a warning.
- **Accumulator / Pulse Converter / Loop** (object types 23 / 24 / 12): see Objects above.
- **hi-limit / low-limit** map to `alarm.high_limit` / `alarm.low_limit` of analog objects. On import the alarm
  uses the device's first notification class; if the file has none, `NC-1` (instance 1, no recipients) is
  created. Notification classes are imported with default priorities and no recipients (EDE has no columns for
  them). Other alarm settings (deadband, time delay, binary / multi-state alarm values) are not carried by EDE.
