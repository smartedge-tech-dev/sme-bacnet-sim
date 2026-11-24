# SME BACnetSim


A BACnet/IP device simulator with a live web UI. Simulate lighting controllers, air conditioners, AHUs,
power meters, sensors, PV inverters — or any device you describe in YAML — and watch their values change
in the browser while a real BACnet client (Yabe, Niagara, your own EMS…) reads and commands them.

- **Many devices on one port.** A built-in BACnet router owns UDP 47808; every simulated device sits on a
  virtual network behind it (default network 100), so clients discover them all with one Who-Is.
- **Realistic behavior.** Room temperature follows the set point when the AC is on, energy integrates power,
  lights report feedback and power, PV output follows a day curve and respects a curtailment limit.
- **Real BACnet semantics.** Commandable outputs with a 16-level priority array and relinquish,
  out-of-service override, COV increments, Device / Network Port objects.
- **Configurable.** Import / export YAML or JSON, edit any device as YAML in the browser, add devices from
  templates, or save back to the config file.
- **Live UI.** Values stream over WebSocket, trend chart per point, event log of BACnet and UI writes.
- **English, Japanese and Simplified Chinese.** The UI follows the browser language; switch it under
  View → Language.

Built on [bacpypes3](https://github.com/JoelBender/BACpypes3) (asyncio BACnet stack, supports BACnet/IP,
IPv6 and BACnet/SC) and FastAPI. No front-end build step.

SME BACnetSim is free and MIT-licensed, developed by [smart-edge (智届科技)](https://smartedge-tech.com) —
custom development is available, see [Commercial support & custom development](commercial-support.md).
