# Quick start

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m sme_bacnet_sim --config configs/demo-building.yaml
```

Open http://127.0.0.1:8080/ . Options:

| Option | Meaning |
|---|---|
| `-c, --config FILE` | YAML/JSON config (defaults to `configs/demo-building.yaml`) |
| `--ip 192.168.1.10/24` | NIC address for BACnet/IP (default: auto-detect, /24) |
| `--bacnet-port 47808` | BACnet/IP UDP port |
| `--foreign-bbmd 192.168.2.1[:47808]` | Register as a foreign device with this BBMD (overrides config) |
| `--foreign-ttl 300` | Foreign device Time-to-Live in seconds (overrides config) |
| `--host 0.0.0.0 --port 8080` | Web UI bind address (default localhost only) |

## Connecting a BACnet client

The client sees the router (`device 4194000`) at `<ip>:47808` and the simulated devices at addresses such as
`100:1`, `100:2` (network 100, MAC 1, 2…) routed through it. In Yabe: *Add device → BACnet/IP over UDP*,
then *Who-Is*.

> **Same PC caveat:** on Windows, a client on the same machine may not receive broadcast replies
> (Who-Is/I-Am) — unicast works. Run the client on another machine, bind the simulator to a different NIC
> than the client, or set `network.mode: bbmd` and register the client as a foreign device.
