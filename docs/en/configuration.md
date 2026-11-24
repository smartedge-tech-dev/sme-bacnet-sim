# Configuration

```yaml
network:
  ip: auto                # or "192.168.1.10/24"
  port: 47808
  network_number: 1       # IP-side network number
  virtual_network: 100    # network number of the simulated devices
  mode: normal            # or bbmd
  # foreign_device: {bbmd: "192.168.2.1:47808", ttl: 300}   # register with an external BBMD
  router: {device_id: 4194000, name: SME-BACnetSim-Router}

simulation:
  tick_seconds: 1.0
  time_scale: 1.0         # 60 = 1 simulated minute per second
  history_size: 600       # trend samples kept per point

devices:
  - device_id: 1002
    name: AC-1F-East
    template: split_ac             # optional
    params: {rated_kw: 2.8}        # template parameters
    objects:                       # add objects, or override template objects by name
      - {name: SetPoint, type: av, value: 24.0, commandable: true}
```

The `network` section can also be changed in the web UI (*Edit → BACnet network…*), see the quick start.
