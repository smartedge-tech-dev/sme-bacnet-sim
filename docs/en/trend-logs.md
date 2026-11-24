# Trend logs

`type: tl` (or `trend-log`) creates a BACnet Trend Log object that logs another object of the **same
device** (polled or on change) and keeps the samples in a ring buffer (oldest records are dropped,
`stop-when-full` is false):

```yaml
- {type: tl, name: RoomTemp_Log, log_object: RoomTemp, log_interval: 60, buffer_size: 1000}
- {type: tl, name: RoomTemp_Cov, log_object: RoomTemp, logging_type: cov, client_cov_increment: 0.5}
```

| Key | Default | Notes |
|---|---|---|
| `log_object` | (required) | name of the logged object; must exist in the device |
| `log_property` | `present-value` | any numeric / enumerated / boolean property of the target |
| `log_interval` | `60` | **simulated** seconds (BACnet `log-interval` is reported in 1/100 s); polled mode only |
| `logging_type` | `polled` | `polled` or `cov` (BACnet `logging-type`) |
| `client_cov_increment` | target's `cov-increment` | `cov` mode only; minimum change of a real value that is logged |
| `buffer_size` | `1000` | ring buffer size |
| `enabled` | `true` | initial value of the `enable` property (also writable over BACnet and from the UI) |

Samples are taken on the simulated clock and time-stamped with the simulated date/time, so with
`time_scale: 3600` an hour of real time yields a day of history at the configured interval. When one tick
is longer than `log_interval`, the missed intervals collapse into one sample. Read the buffer with
**ReadRange** (by position, by sequence number, by time, or without a range for everything that fits in
the response); `log-buffer` is not readable with ReadProperty. Writing `0` to `record-count` clears the log.
The `split_ac` and `power_meter` templates include one trend log each. EDE export / import carries trend logs
(see EDE below).

**COV logging** (`logging_type: cov`): instead of sampling on an interval, a record is appended whenever the
logged value has changed since the last record by at least the increment — `client_cov_increment` if set
(read back as `client-cov-increment`), else the target's `cov-increment` when logging its present value, else
any change; boolean / enumerated / integer values log on any change — or when the target's status flags
change. The first record is taken as soon as the log is enabled with an empty buffer (also after clearing).
Changes are detected once per simulation tick and stamped with the simulated clock; `log-interval` reads 0.
Not supported: the `triggered` logging type, logging objects of other devices (and therefore COV
subscriptions to them / `cov-resubscription-interval`), and log-status / time-change records in the buffer.
