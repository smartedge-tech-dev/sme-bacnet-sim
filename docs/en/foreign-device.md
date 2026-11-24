# Foreign device registration (cross-subnet)

To reach clients on another subnet, the router port can register as a foreign device with an existing BBMD:
`network.foreign_device: {bbmd: "<ipv4>[:port]", ttl: <seconds>}` or `--foreign-bbmd` / `--foreign-ttl`
(the command line wins; TTL defaults to 300 s, port to 47808). The registration uses bacpypes3's foreign
link layer: it is renewed every TTL, retried while unanswered, and cancelled (TTL 0) on stop or reload. Results
(registered / NAK / no answer within 10 s / expired) are written to the event log and shown in the status bar as
`FD → <bbmd> (…)`; the snapshot API reports them in `network.foreign_device`.

Not supported: combining `foreign_device` with `mode: bbmd`, BBMD host names (IPv4 literals only), and reading
or editing the BBMD's tables (Read-Broadcast-Distribution-Table, Read-Foreign-Device-Table and similar).
