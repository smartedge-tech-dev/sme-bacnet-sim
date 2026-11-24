# Text messages, private transfer and list element services

- **ConfirmedTextMessage / UnconfirmedTextMessage** received by a simulated device are written to the event
  log (kind `text-message`: sender address and device, priority, message class, text). A simulated device can
  send one with `POST /api/devices/{id}/text-message`
  `{"message": "...", "address": "100:2", "priority": "normal", "message_class": 5, "confirmed": false}`
  (`address` default: global broadcast `*:*`, which cannot be confirmed; `message_class` a number or text).
- **ConfirmedPrivateTransfer / UnconfirmedPrivateTransfer** are written to the event log (kind
  `private-transfer`). A confirmed request is answered as declared in the device's `private_transfer` list;
  `result: echo` (default) returns the service parameters as the result block, `null` no result block, a
  string / integer / real / boolean that value. Without a matching entry the answer is a
  ConfirmedPrivateTransfer-Error `services` / `optional-functionality-not-supported`: the device does support
  the service, only not that vendor / service number, so the simulator uses this error rather than a
  `unrecognized-service` reject (which would claim the whole service is missing).
- **AddListElement / RemoveListElement** on any writable list property (e.g. notification class
  recipient-list, calendar date-list, schedule list-of-object-property-references, life safety zone
  zone-members). Elements are decoded with the bacpypes3 property datatype; the new list is written exactly
  like a WriteProperty of the whole list (same checks and follow-ups). Elements already in the list are
  ignored on add. Errors (Add/RemoveListElement-Error): unknown object / property, `services` /
  `property-is-not-a-list` (property is not a list), `property` / `property-is-not-an-array` (array index
  given), `write-access-denied`, `invalid-data-type`, and `services` / `list-element-not-found` with the
  (1-based) number of the first element that is not in the list on remove. Written back to the config:
  zone-members, recipient-list (also used for sending notifications at once), date-list and
  list-of-object-property-references (the schedule writes to the new targets), as with WriteProperty; objects that
  come from a template are kept as an override entry.

```yaml
  - device_id: 1006
    name: Room-Sensor-101
    private_transfer:
      - {vendor_id: 999, service_number: 1}              # result: echo (default)
      - {vendor_id: 999, service_number: 2, result: 42}  # fixed value
```

Not supported: vendor-specific meaning of private transfer parameters (they are not decoded), text messages
from the router device, and the AddListElement / RemoveListElement rules that only ASHRAE 135 defines for
individual properties beyond the checks above.
