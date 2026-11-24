# Schedules and calendars

`type: sch` (or `schedule`) creates a BACnet Schedule object that writes its value to objects of the
same device or of **another simulated device**; `type: cal` (or `calendar`) creates a Calendar object whose `present-value` is true on
the listed dates.

```yaml
- {type: cal, name: Holidays, dates: ["2026-12-25", {from: "2026-12-29", to: "2027-01-03"}, "*-01-01"]}
- type: sch
  name: Light_Sch
  targets:                      # written via list-of-object-property-references
    - Zone1_Cmd                 # object of this device
    - {device: AHU-1, object: Fan_Cmd}            # object of another simulated device (name or device id)
    - {device: 300100, object: "binary-value:4"}  # device outside the simulator: listed, never written
  priority_for_writing: 16
  default: "OFF"                # schedule-default
  weekly:
    weekdays: [{time: "08:00", value: "ON"}, {time: "18:00", value: "OFF"}]
    sat: [{time: "09:00", value: "ON"}, {time: "12:00", value: null}]   # null = back to default
  exceptions:
    - {calendar: Holidays, priority: 10, times: [{time: "00:00", value: "OFF"}]}
    - {date: "2026-11-03", priority: 5, times: [{time: "10:00", value: "ON"}]}
    - {date: {from: "2026-08-10", to: "2026-08-14"}, priority: 6, times: [{time: "00:00", value: "OFF"}]}
    - {date: {weeknday: ["*", 6, 5]}, priority: 8, times: [{time: "13:00", value: "OFF"}]}  # last Friday
  effective_period: {from: "2026-01-01", to: "2027-12-31"}   # optional, default always
```

| Key | Default | Notes |
|---|---|---|
| `weekly` | — | keys `mon`..`sun`, or `weekdays` / `weekend` / `daily`; each a list of `{time: "HH:MM[:SS]", value}` |
| `exceptions` | — | special events: one of `date` (same forms as calendar `dates`: `YYYY-MM-DD` with `*` wildcards, a `{from, to}` range or `{weeknday: [...]}`) or `calendar` (calendar object name), `priority` 1–16 (1 wins), `times` |
| `default` | 0 / `OFF` / 1 | schedule-default; at least one of `weekly` / `exceptions` is required |
| `targets` | none | output or value objects, all of the same kind: a name (this device) or `{device, object}`; `device` is a simulated device's name or id, `object` a name or `type:instance` (`av:3`, `binary-output:1`). A device id not in the simulator needs `object: type:instance`; it appears in `list-of-object-property-references` with its `deviceIdentifier`, is skipped (logged once at start) and never written over the network |
| `priority_for_writing` | `16` | priority-array slot used for commandable targets |
| `effective_period` | always | `{from, to}`; outside it the schedule keeps its value and writes nothing |
| `dates` (calendar) | `[]` | dates, `{from, to}` ranges, or `{weeknday: [month, week-of-month, day-of-week]}` (`*` = any; month 13 / 14 = odd / even months; week 1–5 = days 1–7 … 29–31, 6 = last 7 days of the month, 7–9 = the 7-day blocks before that; day 1 = Monday) |

The value type follows the targets: analog → REAL, binary → ENUMERATED (`0/1`, `true/false`, `ON/OFF`,
`active/inactive` or the target's texts), multi-state → UNSIGNED state number. Without targets the
values are REAL. Quote times (`"18:00"`): unquoted, YAML 1.1 reads `18:00` as the number 1080 (it is
still understood, but quoting is clearer).

Schedules run on the **simulated clock**, so `time_scale` fast-forwards them. bacpypes3's own schedule
interpreter uses the wall clock and asyncio timers, so the simulator keeps its Schedule object and
evaluation rules but re-evaluates every tick from the simulated date/time. When the value changes, or a
time entry of the weekly / exception schedule is reached (even with the same value, so a scheduled action
overrides operator changes), the schedule's `present-value` is set and the value is written to each target
at `priority_for_writing` (non-commandable value objects get `present-value` directly); between scheduled
actions nothing is written. A relinquish from a client therefore works normally; the schedule writes again
at its next time entry. Targets in other simulated devices are written directly into that device's object.
A ReinitializeDevice of a target's device re-commands the scheduled value; COV subscriptions are kept. `weekly-schedule`, `exception-schedule` and
`schedule-default` are writable over BACnet and take effect on the next tick (values of the wrong type set
`reliability` to `configuration-error`); exception entries may use dates, date ranges, weekNDay or
calendar references. The written content is kept in the config (Save / Export) as `weekly` / `exceptions` / `default` (binary values as 0 / 1, only the changed keys are rewritten; for a template schedule as an override entry); content the config cannot hold (wrong datatype, a calendar reference that is not a calendar of this device, a value the targets do not accept) is not kept and the config keeps the last valid content. `exception-schedule` is an array, so Add/RemoveListElement answers `property-is-not-a-list`. Calendar `date-list` is writable, too, and writing `list-of-object-property-references` changes the targets (present-value of output / value objects of the schedule's kind on this or another simulated device, or of a device outside the simulator; anything else is `value-out-of-range`); both are kept in the config (Save / Export). A client write to the schedule's own
`present-value` (with the schedule datatype, otherwise `invalid-data-type`) is forwarded to all targets at
`priority_for_writing` and holds until the next scheduled time entry; it is accepted whether or not
`out-of-service` is set.

Not supported: writing to targets on devices outside the simulator (no network WriteProperty).

The `lighting` template has a schedule switching `Zone1_Cmd` (weekdays 08:00 on, 18:00 off) and the
`split_ac` template one for `OnOff` (weekdays 09:00–18:00); disable them with the template parameter
`schedule: false`. The UI lists schedules and calendars with their current value and next transition;
click a row for the weekly / exception table. EDE export lists them as object types 17 / 6; EDE import
skips them.
