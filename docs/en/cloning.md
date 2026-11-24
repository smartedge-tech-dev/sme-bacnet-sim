# Cloning real devices

`sme-bacnet-sim clone` reads real BACnet devices and writes a simulator config (YAML), so later tests run
offline against the simulator instead of the customer's network.

!!! warning "Get the customer's permission first"
    Reading devices on a customer network needs the customer's permission. Prefer non-operating hours.
    MS/TP trunks behind routers are slow and low-end controllers can be loaded by a burst of requests:
    start with a small `--who-is` range and keep the default `--rate`.

## Read-only guarantee

The clone client can only send **Who-Is, ReadProperty and ReadPropertyMultiple**. This is enforced in code: the
client application refuses every other APDU (`ReadOnlyViolation`), so no WriteProperty, SubscribeCOV,
DeviceCommunicationControl, ReinitializeDevice, AtomicReadFile etc. can be sent. It is also passive: it never
answers requests from other devices (no I-Am, no ReadProperty answers). A test clones a simulator instance and
asserts that the "real" devices received nothing but these three services.

The only other traffic is network layer: with `--network N` and no `--address`, bacpypes3 may send
Who-Is-Router-To-Network to find the router.

## Running it on a gateway (Docker, main path)

A typical setup: SSH into a Linux gateway (e.g. a Moxa) on the customer's BACnet network and run the clone there.
Docker is the main path; the image runs on any machine with Docker and needs no Python.

Images are published for `linux/amd64`, `linux/arm64` and `linux/arm/v7` (one multi-arch tag; `docker pull` picks
the right one). Check the gateway with `uname -m`: `x86_64` = amd64, `aarch64` = arm64, `armv7l` = arm-v7 (e.g.
Moxa UC series). For a gateway without internet access, download the matching offline archive from the GitHub
Release, `sme-bacnet-sim-<ver>-linux-amd64.tar.gz`, `-linux-arm64.tar.gz` or `-linux-arm-v7.tar.gz`, and copy it
over (FTP, SCP, USB). `docker load -i` reads the `.tar.gz` as is (no need to gunzip). The loaded image is tagged
`ghcr.io/smartedge-tech-dev/sme-bacnet-sim:<ver>`, so the commands are the same as after `docker pull`.

```sh
# offline gateway: copy the image tar (e.g. by FTP) and load it
docker load -i sme-bacnet-sim-<ver>-linux-<arch>.tar.gz
# or, with internet access
docker pull ghcr.io/smartedge-tech-dev/sme-bacnet-sim:<ver>

docker run --rm --network host --user "$(id -u):$(id -g)" -v "$PWD":/out \
  ghcr.io/smartedge-tech-dev/sme-bacnet-sim:<ver> \
  sme-bacnet-sim clone --who-is 1000-1010 -o /out/site.yaml
```

- On an armv7 gateway (e.g. Moxa): `docker load -i sme-bacnet-sim-<ver>-linux-arm-v7.tar.gz`, then the same
  `docker run`. `docker images` should list `ghcr.io/smartedge-tech-dev/sme-bacnet-sim` with tag `<ver>`.
- `--network host` is required: Who-Is broadcasts and I-Am answers do not cross a Docker bridge network.
- `--user` lets the container write into the mounted directory. `python -m sme_bacnet_sim clone ...` works too.
- Copy `site.yaml` (and `site.yaml.log.jsonl`) back and start the simulator with `-c site.yaml`.

### pip (secondary path)

Where Python 3.10+ is available, from a checkout or source archive: `python3 -m venv venv && venv/bin/pip install .`
(or without a venv: `pip install --user .`), then `sme-bacnet-sim clone ...`. The PyInstaller executables of the
releases are built for x86-64 Windows / Linux / macOS only and do not cover ARM gateways.

## Usage

```text
sme-bacnet-sim clone [--who-is LOW-HIGH | --address IP[:PORT] | --network N] [--devices ID,...]
                     [--ip IP/PREFIX] [--port 47808] [--client-device-id 4194300]
                     [--rate 5] [--timeout 3] [--retries 2] [--no-rpm]
                     [--object-list-file FILE.json] [--no-keep-ids] [--resume] -o OUT.yaml
```

| Option | Meaning |
|---|---|
| `--who-is LOW-HIGH` | Who-Is with this instance range (local broadcast; one number = one device) |
| `--address IP[:PORT]` | Unicast to this device. With `--devices`, no Who-Is is sent at all; without, a unicast Who-Is, then a read of `device,4194303` (wildcard instance) |
| `--network N` | Remote network: Who-Is to `N:*`; with `--address`, the address is the BACnet router to network N |
| `--devices ID,...` | Only these device instances (without `--who-is` the Who-Is range is their min..max) |
| `--ip`, `--port` | Local address and UDP port of the clone client (default auto / 47808) |
| `--client-device-id` | Device instance of the clone client itself (default 4194300) |
| `--rate` | Max requests per second (default 5) |
| `--timeout`, `--retries` | Per request (APDU timeout and retries); `--timeout` is also the Who-Is wait |
| `--no-rpm` | Never use ReadPropertyMultiple |
| `--object-list-file` | Object table for devices whose object-list cannot be read (see below) |
| `--keep-ids` / `--no-keep-ids` | Keep device instances (default) or renumber from 1001 |
| `--resume` | Keep the devices already in the output file and skip them |

At least one of `--who-is`, `--address` or `--devices` is required: nothing is broadcast network-wide by default.

How devices are read:

- One device after the other, requests paced by `--rate`. Progress goes to stderr.
- The object list is read element by element (index 0 = count, then 1..N), so devices without segmentation work;
  if that fails, as a whole; if that fails too, from `--object-list-file`.
- Each object is read with ReadPropertyMultiple (small requests for devices without segmentation, based on the
  device's max-apdu-length-accepted). On the first RPM error, reject or abort the rest of the device is read with
  ReadProperty. Properties a device does not have are skipped.
- The YAML is rewritten after every device: after Ctrl+C the devices read so far are in the file;
  `--resume` continues.
- `<out>.log.jsonl` logs every request, answer, error and warning (one JSON object per line).

### Object list file

For devices whose object-list cannot be read, give the objects in a JSON file (format of existing field files;
other keys such as `properties` are ignored):

```json
[{"deviceID": 1011, "objectList": [{"objectType": "analogInput", "objectInstance": 1},
                                   {"objectType": "binaryValue", "objectInstance": 3}]}]
```

`objectType` is the bacpypes camelCase name (`analogInput`) or the hyphenated BACnet name (`analog-input`).

## What is cloned

The output has `devices:` only; network settings stay at the simulator defaults, so the devices are served on
the virtual network behind the built-in router with their original instances.

- **Device**: object-name, description, location, vendor name / identifier, model name. max-apdu and
  segmentation are logged.
- **All object types the simulator supports**; others (e.g. proprietary types) are skipped with a warning.
- **Value objects** (AI/AO/AV, BI/BO/BV, MSI/MSO/MSV): name, description, units, COV increment, min / max
  present value, active / inactive text, state texts (number-of-states without state-text gives
  `State 1..N`), commandable (a priority array present). The value is the relinquish default of commandable
  objects, else the present value.
- **Alarms**: notification-class, high / low limit, deadband, limit-enable, alarm value(s), fault values,
  event-enable, notify-type, time-delay (-normal). Skipped with a warning when the notification class was not
  cloned.
- **Notification class**: priority, ack-required, recipients by device (address recipients are skipped).
- **Schedule / Calendar**: weekly and exception schedule, default, targets in the same device, priority for
  writing, effective period; calendar dates.
- **Trend log**: logged object (same device), property, interval, buffer size, enable, logging type
  (`triggered` becomes polled with a warning).
- **Accumulator, pulse converter, loop, program, event enrollment** (out-of-range / change-of-state),
  **life safety point / zone**: their configurable properties.
- **File**: type, access method, read-only. The content is **not** cloned (AtomicReadFile is not used).
- References to other devices (trend logs, schedule targets, event enrollments) are dropped with a warning.

Present values are a snapshot; there are no behaviors in the cloned config.

## Coexisting with another BACnet client on the gateway

Gateways often run a BACnet client already (e.g. BAC0 with host networking on `<ip>:47808`).

- **Port**: if 47808 is in use, clone stops with a clear error. Use `--port 47809` (or another free port), or
  stop the program that holds 47808 first.
- **I-Am on another port**: many devices broadcast their I-Am to port 47808, so a clone on 47809 may not see
  answers to Who-Is. Use `--address <device IP>` (unicast) with `--devices <instance>`: then no Who-Is is needed
  at all. Without `--devices`, clone reads `device,4194303` at that address to learn the instance.
- **Device instance**: the clone client is itself a BACnet device, default instance **4194300**. Choose
  another one with `--client-device-id` if it collides with the existing client's instance.

## Offline: EDE

If nothing can run on the gateway, export an EDE file from the customer's BACnet tool and use the
[EDE import](ede.md). EDE carries fewer properties (no alarm details, schedules or recipients).
