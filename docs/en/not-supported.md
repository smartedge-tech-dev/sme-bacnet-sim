# Not supported

## [Foreign device registration (cross-subnet)](foreign-device.md)

Not supported: combining `foreign_device` with `mode: bbmd`, BBMD host names (IPv4 literals only), and reading
or editing the BBMD's tables (Read-Broadcast-Distribution-Table, Read-Foreign-Device-Table and similar).

## [Accumulators, pulse converters and loops](accumulators-loops.md)

Not supported: applying Prescale (stored only), Value_Set / Value_Before_Change / Value_Change_Time /
Logging_Record / Pulse_Rate and limit monitoring of the Accumulator; the Adjust_Value semantics of the
Pulse Converter (it is a plain writable property: Count and Present_Value are not adjusted),
Count_Before_Change / Count_Change_Time / Update_Time and COV_Period periodic notifications; intrinsic
reporting on these three types (`alarm` is rejected); references to other devices or to properties other
than Present_Value.

## [Files and programs](files-programs.md)

Not supported: the transitional states `loading`, `waiting` and `unloading`, rejecting requests that are not
valid in the current state, any real program execution or failure (Reason_For_Halt other than `normal`),
writing File_Size to truncate a file, the Archive semantics (plain writable flag) and a consistency check of
the request's Record_Count against the records sent; the exact rules exist only in the paid ASHRAE 135 text.

## [Trend logs](trend-logs.md)

Not supported: the `triggered` logging type, logging objects of other devices (and therefore COV
subscriptions to them / `cov-resubscription-interval`), and log-status / time-change records in the buffer.

## [Schedules and calendars](schedules-calendars.md)

Not supported: writing to targets on devices outside the simulator (no network WriteProperty).

## [Alarms (intrinsic reporting)](alarms.md)

Not supported: acknowledgment notifications (notify type `ack-notification`). AcknowledgeAlarm is answered and
updates Acked_Transitions, but no notification is sent to recipients. Exact all-or-nothing semantics of
WritePropertyMultiple beyond the up-front validation above (rollback of already applied writes). SME BACnetSim is free and is built from
public sources only; behaviors that can only be specified from the paid ASHRAE 135 text are left out.

## [Event enrollments (algorithmic reporting)](event-enrollments.md)

Not supported: the event types `floating-limit`, `change-of-value` and all others (their exact algorithms are
specified only in ASHRAE 135), fault detection of event enrollments (no `fault` state / change-of-reliability),
monitoring objects of other devices or properties other than present-value, changing `event-type` or
`object-property-reference` by a BACnet write, and creating / deleting event enrollments with
CreateObject / DeleteObject. A value object monitored by an event enrollment cannot be deleted.

## [Life safety points and zones](life-safety.md)

Not supported: change-of-life-safety event reporting (alarm-values, life-safety-alarm-values, fault-values and
the event properties are not evaluated), the severity order of the states and mode-dependent transitions,
maintenance-required / direct-reading / setting behaviour, and creating / deleting life safety objects with
CreateObject / DeleteObject.

## [Text messages, private transfer and list element services](text-private-transfer.md)

Not supported: vendor-specific meaning of private transfer parameters (they are not decoded), text messages
from the router device, and the AddListElement / RemoveListElement rules that only ASHRAE 135 defines for
individual properties beyond the checks above.
