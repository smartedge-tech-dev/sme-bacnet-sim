# Life safety points and zones

```yaml
      - {type: lsp, name: Smoke-101, description: Smoke detector}   # life-safety-point (object type 21)
      - type: lsp
        name: Heat-101
        value: quiet               # initial state (BACnetLifeSafetyState: quiet, pre-alarm, alarm, fault, ...)
        mode: "on"                 # BACnetLifeSafetyMode (default on; quote on / off in YAML)
        accepted_modes: ["on", "off", test]   # default [off, on, test]
        operation_expected: none   # BACnetLifeSafetyOperation, read-only (default none)
        silenced: unsilenced       # initial BACnetSilencedState
        behavior: {type: random_alarm, probability: 0.001, state: alarm}  # optional, per sim second
      - {type: lsz, name: Zone-101, zone_members: [Smoke-101, Heat-101]}  # life-safety-zone (object type 22)
```

The simulator uses a simplified model (the full state machine is only specified in ASHRAE 135):

- **Tracking_Value** is the live detector state. Set it from the UI (detector-state menu of the row,
  `POST /api/devices/{id}/life-safety/{type:instance}/state`) or with the optional `random_alarm` behavior
  (goes to `state` at random, back to `quiet` on the next tick). It is read-only for BACnet clients.
- **Present_Value** follows Tracking_Value while that is not `quiet` and stays **latched** when it returns to
  `quiet`, until a reset. BACnet writes to present-value are only accepted while out-of-service.
- **Zone**: its Tracking_Value is the present value of the first member (in Zone_Members order) that is not
  `quiet`, else `quiet`. This is a simplification: no severity order between the states is applied.
- **LifeSafetyOperation**: `silence` / `silence-audible` / `silence-visual` set and `unsilence*` clear the
  audible / visible part of Silenced; `reset` / `reset-alarm` / `reset-fault` (all the same here) copy
  Tracking_Value to Present_Value and unsilence; `none` does nothing. An operation on a zone also acts on its
  members; without an object identifier it acts on every life safety object of the device. Vendor-specific
  operations return `services` / `optional-functionality-not-supported`, other object types `object` /
  `unsupported-object-type`. Every operation is written to the event log.
- **Mode** is writable but must be one of accepted-modes (else `property` / `value-out-of-range`);
  **zone-members** is writable (WriteProperty, AddListElement / RemoveListElement) and written back to the
  config as member names (references to other devices are ignored).
- ReinitializeDevice restores the configured state. EDE export lists them (object type 21 / 22, state number
  as value); EDE import keeps type, name and state.

Not supported: change-of-life-safety event reporting (alarm-values, life-safety-alarm-values, fault-values and
the event properties are not evaluated), the severity order of the states and mode-dependent transitions,
maintenance-required / direct-reading / setting behaviour, and creating / deleting life safety objects with
CreateObject / DeleteObject.
