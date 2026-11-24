# Excel point list

Besides YAML and EDE, the configuration can be written and read as an Excel workbook (`.xlsx`): a point list
that can be filled in by hand and imported, or exported from the running simulator, edited and re-imported.

- **File → Download blank Excel template** (`GET /api/config/xlsx-template`): an empty workbook with all
  sheets and columns.
- **File → Export → Excel point list** (`GET /api/config/export?format=xlsx`): the running configuration.
- **File → Import…** accepts a single `.xlsx` file (`POST /api/config/import`).

## Workbook layout

Every sheet has one header row with the English column names (case-insensitive; columns may be reordered).
The row below starts with `#` and describes each column in Japanese / Chinese. Any row whose first non-empty
cell starts with `#` is a comment and is ignored, empty rows too. Empty cells mean "not set" (the default).

| Sheet | One row per | Columns |
|---|---|---|
| `Devices` | device | `device_id`*, `name`*, `description`, `template`, `params`, `vendor_id`, `vendor_name`, `model_name`, `location`, `dcc_password`, `reinit_password`, `extra` |
| `Points` | object | `device_id`*, `type`*, `instance`, `name`*, `description`, `units`, `value`, `commandable`, `min`, `max`, `cov_increment`, `state_texts`, `inactive_text`, `active_text`, `behavior`, `alarm_class`, `alarm_high_limit`, `alarm_low_limit`, `alarm_deadband`, `alarm_values`, `alarm_time_delay`, `extra` |
| `StateTexts` | state-text list | `ref`*, `text_1`, `text_2`, ... (as many `text_N` columns as needed) |
| `Network` (optional) | setting | `key`, `value` — e.g. `network.ip`, `network.port`, `network.foreign_device.bbmd`, `simulation.time_scale` |

\* required.

- `Points.device_id` must be listed in `Devices`. `type` is the BACnet object type name (`analog-input`) or
  its number (`0`). `instance` empty = auto-assigned. `units` is a BACnet engineering-units name
  (`degrees-celsius`) or its number (`62`). `commandable`: `TRUE` / `FALSE` (also yes / no, 1 / 0).
- `state_texts` refers to a `StateTexts.ref`; for multi-state objects the texts are states 1..N, for binary
  objects `text_1` / `text_2` are used as inactive / active text unless `inactive_text` / `active_text` are set.
  Objects with the same texts share a ref on export.
- `alarm_*` build the object's `alarm:` (intrinsic reporting): `alarm_class` is the notification-class name or
  number, `alarm_values` is the binary alarm value (`active`) or a comma-separated list of multi-state states
  (`2,3`).
- `params`, `behavior` and `extra` are YAML flow mappings, e.g. `{zones: 4}` or
  `{type: sine, min: 20, max: 26, period: 600}`. `extra` holds every setting without its own column, with the
  same keys as in YAML (trend-log settings, schedules, notification-class recipients, loop constants, other
  alarm settings such as `{alarm: {notify_type: event}}` ...). Column values win over `extra`.
- Devices with a `template` keep it: their `Points` rows are overrides / additions to the template objects,
  exactly as `objects:` in YAML.
- Without a `Network` sheet (or with no rows in it) the network and simulation settings of the running
  configuration are kept. With rows, unspecified keys take their defaults.

## Import checks

Every row is checked; all errors are reported together, each with the sheet, the row number and the column,
e.g. `Points row 12, column 'instance': not an integer: 'abc'` — nothing is applied while errors remain.
Checked are number / boolean / YAML formats, object types and unit codes, `device_id` references, duplicate
device ids, object names and instances, `state_texts` references and the object settings themselves.
Warnings (e.g. an unknown column that was ignored) are written to the event log, as for EDE import.

## Round trip and export warnings

Export → import gives back an equivalent configuration. A value that does not fit in an Excel cell
(more than 32,767 characters) is left out with a warning in the event log; a file object loaded from `path`
is exported as that path reference, also with a warning.
