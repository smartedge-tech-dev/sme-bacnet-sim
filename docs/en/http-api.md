# HTTP API

| Method | Path | |
|---|---|---|
| GET | `/api/version` | `{name, version, common_version}` |
| GET | `/api/state` | full snapshot |
| WS | `/ws` | snapshot + value changes + log events |
| POST | `/api/devices/{id}/objects/{type:instance}/write` | `{"value": 1, "priority": 8}` |
| POST | `.../relinquish`, `.../oos` | `{"priority": 8}`, `{"out_of_service": true}` |
| POST | `/api/devices/{id}/objects/{type:instance}/ack` | acknowledge all unacknowledged transitions of the object's alarm |
| POST | `/api/devices/{id}/dcc` | `{"state": "enable"}` (or `disable` / `disable-initiation`) |
| POST | `/api/simulation` | `{"running": true, "time_scale": 60, "set_time": "2026-11-23T08:00:00"}` (all optional; naive time = local) |
| GET/PUT | `/api/config` | whole config (PUT accepts YAML or JSON text) |
| POST | `/api/config/save` | write the running config to the `-c` file (400 if started without `-c`); returns `{ok, path}` |
| GET/PUT | `/api/network` | network settings + local IPv4 interfaces (`{network, bind, config_path, interfaces}`); PUT `{ip, port, network_number, virtual_network, mode, router, foreign_device}` validates, rebinds and writes the `network:` section back → `{ok, bind, saved, save_error}` |
| POST | `/api/config/import` | multipart upload: one YAML / JSON / Excel (`.xlsx`) file, or EDE CSV files / zip (field `file`, repeatable) |
| GET | `/api/config/export?format=yaml\|json\|ede` | download (`ede` = zip of main + state-text CSV; Excel: `GET /api/config/xlsx`) |
| GET | `/api/config/xlsx` | download the running config as an Excel point list |
| GET | `/api/config/xlsx-template` | blank Excel point-list template |
| GET | `/api/templates` | template catalog |
| POST | `/api/templates/reload` | reload user templates; returns `{dir, loaded, errors, templates}` |
| POST | `/api/templates/from-device/{id}` | `{"name": "my-ahu", "title": ..., "description": ..., "overwrite": false}` saves the device as a user template; returns `{ok, name, path}` (409 if it exists) |
| POST/PUT/DELETE | `/api/devices`, `/api/devices/{id}/config` | add / edit / delete device; POST `/api/devices` without `device_id` takes the first free ID from 1001 and returns `{ok, name, device}` (409 if the ID exists); `GET /api/devices/{id}/config` returns the device as YAML |
| POST | `/api/devices/{id}/duplicate` | copy of the device (optional `{"device_id"}`, else next free ID; name `Name (copy)`); returns `{ok, name, device}` (`name` = new device ID, `device` = the copy) |
| GET | `/api/devices/{id}/objects/config?keys=analog-value:1,...` | object configs (template objects expanded) for copying |
| POST | `/api/devices/{id}/objects/paste` | `{"objects": [object config, ...]}` → `{"pasted": [{name, key}], "rejected": [{name, reason}]}` |
| GET | `/api/devices/{id}/objects/{type:instance}/properties` | all properties (`device:{id}` = device object): `[{id, name, value, datatype, writable, editable, kind}]` |
| PUT | `/api/devices/{id}/objects/{type:instance}/properties/{property}` | `{"value": 21.5, "priority": 8}` (basic types only; `null` + priority relinquishes) |
| GET | `/api/history/{id}/{type:instance}` | trend samples |
| GET | `/api/devices/{id}/trendlog/{instance}` | trend-log buffer `[[timestamp, value], ...]` (simulated clock) |
| POST | `/api/devices/{id}/trendlog/{instance}/enable` | `{"enabled": true}` |
| POST | `/api/devices/{id}/program/{instance}/change` | `{"request": "halt"}` (load / run / halt / restart / unload / ready) |
| POST | `/api/devices/{id}/text-message` | `{"message": "...", "address": "100:2", "priority": "normal", "message_class": 5, "confirmed": false}` (address default: global broadcast) |
| POST | `/api/devices/{id}/life-safety/{type:instance}/state` | `{"state": "alarm"}` (Tracking_Value of a life safety point) |

Errors return `{"detail": ..., "error": message}`; import failures also carry a top-level `errors` list (per-row messages).
