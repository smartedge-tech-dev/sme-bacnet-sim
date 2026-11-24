# Event enrollments (algorithmic reporting)

`type: ee` (or `event-enrollment`) creates an Event Enrollment object that monitors the present-value of
another value object of the same device and reports through a notification class, so a point without an
`alarm` block (e.g. a template's temperature) can still raise alarms:

```yaml
- type: ee
  name: RoomTempWatch
  monitored_object: Temperature
  event_type: out-of-range
  event_parameters: {low_limit: 18, high_limit: 28, deadband: 0.5}
  notification_class: RoomAlarms
  time_delay: 60
- {type: ee, name: ModeWatch, monitored_object: OperationMode, event_type: change-of-state,
   event_parameters: {alarm_values: [Maintenance]}, notification_class: 1, notify_type: event}
```

| key | meaning |
|---|---|
| `monitored_object` | name of a value object of the same device (Object_Property_Reference = its present-value) |
| `event_type` | `out-of-range` (analog, accumulator excluded) or `change-of-state` (binary / multi-state) |
| `event_parameters` | out-of-range: `low_limit`, `high_limit` (both required, both always enabled), `deadband`; change-of-state: `alarm_values` (state numbers or texts, `active` / `inactive` for binary) |
| `notification_class` | name or instance of a notification-class object in the same device |
| `time_delay`, `time_delay_normal` | **simulated** seconds (default 0 / `time_delay`); `time_delay` is the Time_Delay of Event_Parameters |
| `event_enable` | `[to-offnormal, to-fault, to-normal]`, default all true |
| `notify_type` | `alarm` (default) or `event` |

Event enrollments use the same event state machine, notifications, AcknowledgeAlarm,
GetEventInformation / GetAlarmSummary / GetEnrollmentSummary and web UI (row with badge and **Ack**,
*View → Alarms*) as intrinsic reporting. BACnet writes to `event-parameters` (same event type),
`event-enable`, `notify-type`, `time-delay-normal` and `notification-class` take effect and are written into
the config; `acked-transitions` is read-only. The demo configuration's `Room-Sensor-101` has one. EDE export
lists event enrollments (object type 9); EDE import skips them with a warning (EDE carries no monitored
object or parameters).

Not supported: the event types `floating-limit`, `change-of-value` and all others (their exact algorithms are
specified only in ASHRAE 135), fault detection of event enrollments (no `fault` state / change-of-reliability),
monitoring objects of other devices or properties other than present-value, changing `event-type` or
`object-property-reference` by a BACnet write, and creating / deleting event enrollments with
CreateObject / DeleteObject. A value object monitored by an event enrollment cannot be deleted.
