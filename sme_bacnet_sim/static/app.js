"use strict";
// SME BACnetSim web UI: vanilla JS, no build step. Generic chrome (header, menus, footer, theme, i18n)
// lives in shell/shell.js; this file holds the BACnet-specific UI.

// ------------------------------------------------------------------ product config (single spot)

const REPO_URL = "https://github.com/smartedge-tech-dev/sme-bacnet-sim";
// Company website contact page (the site's default language, ja, is served at "/").
const CONTACT_URL = "https://smartedge-tech.com/contact/";
const PRODUCT = {
  product: "SME BACnetSim",
  tagline: "BACNET DEVICE SIMULATOR",
  license: "MIT",
  year: 2026,
  links: {
    repo: REPO_URL,
    docs: `${REPO_URL}#readme`,
    issues: `${REPO_URL}/issues/new`,
    license: `${REPO_URL}/blob/main/LICENSE`,
  },
  // Company behind SME BACnetSim (facts from smartedge-tech.com). Blurb and services are i18n keys below.
  vendor: {
    name: "smart-edge",
    nameLocal: "智届科技",
    url: "https://smartedge-tech.com",
    contactUrl: CONTACT_URL,
    email: "business@smartedge-tech.com",
    logoUrl: "/static/brand/company-logo.svg",
    blurb: "vendor.blurb",
    services: ["vendor.svc.ems", "vendor.svc.market", "vendor.svc.edge", "vendor.svc.integration",
      "vendor.svc.ai", "vendor.svc.cloud"],
  },
  // Navy parts use currentColor so the mark follows the theme; the accent block stays brand blue.
  logoSvg: `<svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M8 34V9h15v25M12 15h7M12 20.5h7M12 26h7M4 34h32M30.5 34V22" stroke="currentColor" stroke-width="2.4"/>
    <rect x="25.5" y="11" width="10" height="10" fill="#087def"/></svg>`,
};

// ------------------------------------------------------------------ UI strings (en)

Shell.addStrings("en", {
  "vendor.blurb": "Nanjing Smart-Edge Technology Co., Ltd. (南京智届科技有限公司) has, since its founding in 2023, " +
    "developed end-to-end software for distributed energy resources such as solar, batteries and EVs — " +
    "from equipment control to the cloud and electricity markets. The team supports projects in Japanese, " +
    "from requirements definition through design, implementation, operation and maintenance.",
  "vendor.svc.ems": "Energy management systems (EMS)",
  "vendor.svc.market": "RA / AC systems for electricity markets (JEPX, EPRX, OCCTO)",
  "vendor.svc.edge": "Edge IoT and equipment-control software",
  "vendor.svc.integration": "Equipment integration: Modbus, MQTT, BACnet, ECHONET Lite, OpenADR 2.0b",
  "vendor.svc.ai": "Energy forecasting and data analytics",
  "vendor.svc.cloud": "Cloud infrastructure design, build and operation",
  "menu.file": "File",
  "menu.file.import": "Import…",
  "menu.file.import.title": "Import a YAML / JSON config file, an Excel point list (.xlsx), or EDE CSV files (main + state texts) / EDE zip",
  "menu.file.export": "Export",
  "menu.file.export.yaml": "YAML",
  "menu.file.export.json": "JSON",
  "menu.file.export.ede": "EDE (CSV zip)",
  "menu.file.export.xlsx": "Excel point list (.xlsx)",
  "menu.file.template": "Download blank Excel template",
  "menu.file.template.title": "Empty point-list workbook (Devices / Points / StateTexts / Network sheets) to fill in and import",
  "menu.file.save": "Save",
  "menu.file.save.title": "Write config back to {path}",
  "menu.file.save.none": "No config file to write back to",
  "menu.edit": "Edit",
  "menu.edit.config": "Edit configuration…",
  "menu.edit.add": "Add device…",
  "menu.edit.copy": "Copy",
  "menu.edit.copy.title": "Copy the selected points, or the device when no point is selected (Ctrl+C)",
  "menu.edit.paste": "Paste",
  "menu.edit.paste.title": "Paste the copied device / points into the current device (Ctrl+V)",
  "dev.copy": "Copy",
  "dev.copy.title": "Copy this device (Ctrl+C with no point selected; right-click a device in the list)",
  "dev.paste": "Paste",
  "dev.paste.title": "Paste: a copied device is duplicated; copied points are added to this device (Ctrl+V)",
  "dev.props": "Properties",
  "dev.props.title": "All properties of the device object",
  "row.props.title": "All properties of this object",
  "clip.device": "Copied device {name}",
  "clip.objects": "Copied {n} point(s) from {name}",
  "clip.empty": "Clipboard is empty",
  "clip.duplicated": "Device {name} ({id}) added",
  "clip.pasted": "Pasted {n} point(s)",
  "clip.rejected": "{n} point(s) not pasted: {list}",
  "props.title": "{object} — properties",
  "props.col.id": "ID",
  "props.col.name": "Property",
  "props.col.value": "Value",
  "props.col.type": "Datatype",
  "props.col.edit": "Write",
  "props.ro": "read-only",
  "props.constructed": "read-only here (constructed)",
  "props.set": "Set",
  "props.null": "Relinquish",
  "props.refresh": "Refresh",
  "props.written": "{prop} written",
  "menu.sim": "Simulation",
  "menu.sim.run": "Run",
  "menu.sim.pause": "Pause",
  "menu.sim.speed": "Speed",
  "menu.sim.sync": "Sync to PC clock",
  "dev.comm": "Communication: {state}",
  "dev.comm.title": "Disabled with DeviceCommunicationControl — only DCC / ReinitializeDevice are answered",
  "dev.comm.enable": "Enable communication",
  "menu.view": "View",
  "menu.view.log": "Event log",
  "status.running": "Running",
  "status.paused": "Paused",
  "status.toggle": "Simulation is {state} — click to toggle",
  "status.clock": "Simulation clock",
  "status.ws.on": "WebSocket connected",
  "status.ws.off": "WebSocket disconnected",
  "status.connecting": "connecting…",
  "net.info": "BACnet/IP {bind} · router {router} · VNET {vnet}",
  "net.bbmd": " · BBMD",
  "net.fd": " · FD → {bbmd} ({status})",
  "net.fd.ok": "ok",
  "net.fd.registering": "registering",
  "net.fd.timeout": "failed: no answer",
  "net.fd.nak": "failed: NAK",
  "side.filter": "Filter devices / points…",
  "side.add": "+ Add device",
  "dev.item": "device {id} · {addr}",
  "dev.empty": "No devices. Import a config file or add a device.",
  "dev.meta": "device,{id} · address {addr} · {template}",
  "dev.priority": "write priority",
  "dev.editYaml": "Edit YAML",
  "dev.delete": "Delete",
  "dev.confirmDelete": "Delete device {name} ({id})?",
  "col.name": "Name",
  "col.object": "Object",
  "col.value": "Value",
  "col.units": "Units",
  "col.pri": "Pri",
  "col.pri.title": "Current command priority",
  "col.oos": "OOS",
  "col.oos.title": "Out of service",
  "col.behavior": "Behavior",
  "col.command": "Command",
  "row.oos.title": "Out of service: freezes the simulated behavior",
  "val.active": "active",
  "val.inactive": "inactive",
  "cmd.on": "ON",
  "cmd.off": "OFF",
  "cmd.set": "Set",
  "loop.pv": "PV",
  "loop.sp": "SP",
  "cmd.relinquish": "Relinquish",
  "cmd.relinquish.title": "Release the current command priority",
  "trend.close": "Close trend",
  "tl.records": "{n} / {size} records",
  "tl.target": "logs {target} every {interval} s",
  "tl.enable": "Enable",
  "tl.enable.title": "Enable logging (BACnet Enable property)",
  "sch.targets": "writes {targets} @ priority {priority}",
  "sch.notargets": "no targets",
  "sch.next": "next {time} → {value}",
  "sch.nonext": "no change within 8 days",
  "sch.weekly": "Weekly schedule (default: {value})",
  "sch.exceptions": "Exceptions",
  "sch.prio": "priority {priority}",
  "sch.edit": "Read-only view; edit via Edit YAML or BACnet WriteProperty.",
  "cal.today": "today: {value}",
  "cal.dates": "Date list",
  "nc.priority": "Priority {offnormal}/{fault}/{normal}",
  "nc.ack": "Ack required: {flags}",
  "file.bytes": "{n} bytes",
  "file.records": "{n} records / {bytes} bytes",
  "file.readonly": "read-only",
  "file.modified": "modified {time}",
  "prog.change": "Program change…",
  "prog.change.title": "Write Program_Change (load / run / halt / restart / unload)",
  "ls.state": "Detector state…",
  "ls.state.title": "Set the detector state (Tracking_Value); Present_Value latches until a LifeSafetyOperation reset",
  "ls.tracking": "tracking",
  "ls.mode": "mode",
  "ls.members": "members: {names}",
  "nc.recipients": "{n} recipient(s)",
  "nc.norecipients": "no recipients",
  "ee.watch": "{event_type} on {object}",
  "ee.readonly": "Event enrollment: parameters are set in the configuration or by BACnet writes",
  "nc.recipient": "{recipient} (process {process}, {mode})",
  "nc.confirmed": "confirmed",
  "nc.unconfirmed": "unconfirmed",
  "nc.readonly": "Notification class (read-only here; edit it in the configuration)",
  "day.mon": "Mon", "day.tue": "Tue", "day.wed": "Wed", "day.thu": "Thu", "day.fri": "Fri", "day.sat": "Sat", "day.sun": "Sun",
  "log.title": "Event log",
  "dlg.cancel": "Cancel",
  "menu.view.alarms": "Alarms…",
  "status.alarms": "{active} active alarm(s), {unacked} unacknowledged — click for the list",
  "alarm.state.normal": "normal",
  "alarm.state.high-limit": "high limit",
  "alarm.state.low-limit": "low limit",
  "alarm.state.offnormal": "off-normal",
  "alarm.state.fault": "fault",
  "alarm.unacked": "unacknowledged",
  "alarm.ack": "Ack",
  "alarm.ack.title": "Acknowledge the alarm",
  "alarms.title": "Alarms",
  "alarms.empty": "No active or unacknowledged alarms",
  "alarms.col.device": "Device",
  "alarms.col.object": "Object",
  "alarms.col.state": "State",
  "alarms.col.value": "Value",
  "alarms.close": "Close",
  "dlg.apply": "Apply",
  "dlg.editDevice": "Edit device {id}",
  "dlg.editAll": "Edit full configuration",
  "add.title": "Add device",
  "add.template": "Template",
  "add.id": "Device ID",
  "add.id.ph": "auto",
  "add.name": "Name",
  "add.params": "Parameters (YAML)",
  "add.submit": "Add",
  "import.ok": "Configuration imported",
  "import.warn": "Imported with {n} warnings (see event log)",
  "import.fail": "Import failed: {msg}",
  "save.ok": "Configuration saved",
  "about.stack": "Protocol stack",
  "about.stack.value": "BACnet/IP (ASHRAE 135) via bacpypes3, virtual network behind a simulated router",
});
const t = Shell.t;

// ------------------------------------------------------------------ state

const $ = (id) => document.getElementById(id);
const ICONS = { lighting: "💡", split_ac: "❄️", ahu: "🌀", power_meter: "⚡", env_sensor: "🌡️", pv_inverter: "☀️", custom: "🧩" };
const SHORT = {
  "analog-input": "AI", "analog-output": "AO", "analog-value": "AV",
  "binary-input": "BI", "binary-output": "BO", "binary-value": "BV",
  "multi-state-input": "MSI", "multi-state-output": "MSO", "multi-state-value": "MSV",
  "trend-log": "TL",
  schedule: "SCH",
  calendar: "CAL",
  "notification-class": "NC",
  accumulator: "ACC",
  "pulse-converter": "PC",
  loop: "LOOP",
  file: "FILE",
  program: "PRG",
  "event-enrollment": "EE",
  "life-safety-point": "LSP",
  "life-safety-zone": "LSZ",
};
const SPEEDS = [1, 10, 60, 600, 3600];

const S = {
  snap: null,          // last snapshot
  dev: null,           // selected device id
  idx: new Map(),      // "d|k" -> object
  trend: null,         // {d, k, data: [[t, v]]}
  priority: 8,         // operator command priority
  filter: "",
  sel: new Set(),      // selected point keys of the current device
  anchor: null,        // last clicked point key (Shift range)
  clip: null,          // {kind: "device", device_id, name} | {kind: "objects", device_id, name, objects}
};

// ------------------------------------------------------------------ api

async function api(method, url, body, raw) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    if (raw) { opt.body = body; opt.headers["Content-Type"] = "text/plain"; }
    else if (body instanceof FormData) opt.body = body;
    else { opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
  }
  const r = await fetch(url, opt);
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(typeof data === "string" ? data : (data.detail || JSON.stringify(data)));
  return data;
}

// Errors go to both a toast and the event log; other kinds are toast only.
function toast(msg, kind = "error") {
  Shell.toast(msg, kind);
  if (kind === "error") addLog({ t: Date.now() / 1000, kind: "error", text: msg });
}

// ------------------------------------------------------------------ formatting

function fmtValue(o) {
  if (o.type.startsWith("binary")) return o.value ? (o.active_text || t("val.active")) : (o.inactive_text || t("val.inactive"));
  if (o.type.startsWith("multi-state")) return (o.states && o.states[o.value - 1]) || String(o.value);
  if (o.type === "accumulator") return String(o.value);
  const a = Math.abs(o.value);
  return o.value.toFixed(a >= 1000 ? 0 : a >= 100 ? 1 : 2);
}
const fmtUnits = (u) => (u || "").replace("degrees-celsius", "°C").replace("percent-relative-humidity", "%RH")
  .replace(/^percent$/, "%").replace("parts-per-million", "ppm").replace("kilowatt-hours", "kWh")
  .replace("kilowatts", "kW").replace(/^watts$/, "W").replace("luxes", "lx").replace("pascals", "Pa")
  .replace("amperes", "A").replace("volts", "V").replace("hertz", "Hz").replace("no-units", "");
const hhmm = (h) => `${String(Math.floor(h)).padStart(2, "0")}:${String(Math.floor((h % 1) * 60)).padStart(2, "0")}`;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ------------------------------------------------------------------ rendering

function setSnapshot(snap) {
  S.snap = snap;
  S.idx.clear();
  for (const d of snap.devices) for (const o of d.objects) S.idx.set(`${d.device_id}|${o.k}`, o);
  if (!snap.devices.some((d) => d.device_id === S.dev)) S.dev = snap.devices[0]?.device_id ?? null;
  if (snap.version) Shell.setVersion(snap.version);
  renderNet(snap.network);
  Shell.updateItem("file.save", {
    disabled: !snap.config_path,
    title: snap.config_path ? t("menu.file.save.title", { path: snap.config_path }) : t("menu.file.save.none"),
  });
  if (snap.sim_hour != null) $("clock").textContent = hhmm(snap.sim_hour);
  renderSim(snap.simulation);
  $("log").innerHTML = "";
  for (const e of snap.events) addLog(e);
  renderDevices();
  renderDevice();
  renderAlarms();
}

// ------------------------------------------------------------------ alarms

const ackAlarm = (d, k) => api("POST", `/api/devices/${d}/objects/${k}/ack`, {}).catch((e) => toast(e.message));

function alarmList() {
  const out = [];
  for (const d of S.snap?.devices || []) for (const o of d.objects) {
    if (o.alarm && (o.event_state !== "normal" || o.unacked)) out.push({ d, o });
  }
  return out;
}

function alarmBadge(o) {
  const st = o.event_state || "normal";
  const cls = st === "normal" ? "" : st === "fault" ? "fault" : "alarm";
  return `<span class="abadge ${cls} ${o.unacked ? "unacked" : ""}" title="${esc(o.unacked ? t("alarm.unacked") : "")}">${esc(t(`alarm.state.${st}`))}</span>`;
}

function renderAlarms() {
  const list = alarmList();
  const active = list.filter((x) => x.o.event_state !== "normal").length;
  const unacked = list.filter((x) => x.o.unacked).length;
  const ind = $("alarmInd");
  ind.hidden = !list.length;
  ind.classList.toggle("unacked", unacked > 0);
  ind.querySelector(".st-alarm-n").textContent = String(active);
  ind.title = t("status.alarms", { active, unacked });
  ind.setAttribute("aria-label", ind.title);
  renderAlarmDialog();
}

function renderAlarmDialog() {
  const dlg = $("dlgAlarms");
  if (!dlg || !dlg.open) return;
  const list = alarmList();
  const rows = list.map(({ d, o }) => `<tr>
      <td><a href="#" data-go="${d.device_id}">${esc(d.name)}</a></td>
      <td>${esc(o.name)} <small>${SHORT[o.type]}:${o.instance}</small></td>
      <td>${alarmBadge(o)}</td><td class="num">${esc(o.event_enrollment ? eeValue(d, o) : fmtValue(o))} ${esc(fmtUnits(o.units))}</td>
      <td>${o.unacked ? `<button class="btn small" data-d="${d.device_id}" data-k="${esc(o.k)}" title="${esc(t("alarm.ack.title"))}">${esc(t("alarm.ack"))}</button>` : ""}</td></tr>`);
  dlg.querySelector(".alarmbody").innerHTML = list.length
    ? `<table class="alarms"><thead><tr><th>${esc(t("alarms.col.device"))}</th><th>${esc(t("alarms.col.object"))}</th>
        <th>${esc(t("alarms.col.state"))}</th><th class="num">${esc(t("alarms.col.value"))}</th><th></th></tr></thead>
        <tbody>${rows.join("")}</tbody></table>`
    : `<p class="empty">${esc(t("alarms.empty"))}</p>`;
  dlg.querySelectorAll("button[data-k]").forEach((b) => { b.onclick = (e) => { e.preventDefault(); ackAlarm(b.dataset.d, b.dataset.k); }; });
  dlg.querySelectorAll("a[data-go]").forEach((a) => {
    a.onclick = (e) => { e.preventDefault(); S.dev = Number(a.dataset.go); renderDevices(); renderDevice(); dlg.close(); };
  });
}

function openAlarms() {
  let dlg = $("dlgAlarms");
  if (!dlg) {
    dlg = document.createElement("dialog");
    dlg.id = "dlgAlarms";
    dlg.className = "dialog sh-dialog";
    dlg.innerHTML = `<form method="dialog" class="dlgform"><h3>${esc(t("alarms.title"))}</h3><div class="alarmbody"></div>
      <div class="dlgbtns"><button class="btn" value="cancel">${esc(t("alarms.close"))}</button></div></form>`;
    document.body.append(dlg);
  }
  if (!dlg.open) dlg.showModal();
  renderAlarmDialog();
}

function speedItems(cur) {
  const list = cur == null || SPEEDS.includes(cur) ? SPEEDS : [...SPEEDS, cur].sort((a, b) => a - b);
  return list.map((s) => ({ id: `sim.speed.${s}`, label: `${s}×`, radio: true, checked: s === cur, onClick: () => setSim({ time_scale: s }) }));
}

function renderSim(sim) {
  const ind = $("runInd");
  const state = sim.running ? t("status.running") : t("status.paused");
  ind.classList.toggle("paused", !sim.running);
  ind.querySelector(".st-run-lbl").textContent = state;
  ind.title = t("status.toggle", { state: state.toLowerCase() });
  ind.setAttribute("aria-label", ind.title);
  Shell.updateItem("sim.run", { label: sim.running ? "menu.sim.pause" : "menu.sim.run" });
  Shell.updateItem("sim.speed", { submenu: speedItems(sim.time_scale) });
}

function renderDevices() {
  const f = S.filter.toLowerCase();
  const ul = $("devList");
  ul.innerHTML = "";
  for (const d of S.snap.devices) {
    const hit = !f || d.name.toLowerCase().includes(f) || String(d.device_id).includes(f)
      || d.objects.some((o) => o.name.toLowerCase().includes(f));
    if (!hit) continue;
    const errs = d.objects.filter((o) => o.error).length;
    const li = document.createElement("li");
    li.className = d.device_id === S.dev ? "sel" : "";
    li.innerHTML = `<span class="ico">${ICONS[d.template] || "🧩"}</span>
      <span class="dn">${esc(d.name)}</span>
      <span class="badge ${errs ? "err" : ""}">${errs ? `⚠ ${errs}` : d.objects.length}</span>
      <span class="di">${esc(t("dev.item", { id: d.device_id, addr: d.address }))}</span>`;
    li.onclick = () => selectDevice(d.device_id);
    li.oncontextmenu = (e) => { e.preventDefault(); selectDevice(d.device_id); copyDevice(d); };
    ul.appendChild(li);
  }
}

function currentDevice() { return S.snap?.devices.find((d) => d.device_id === S.dev); }

function renderDevice() {
  const d = currentDevice();
  const head = $("devHeader"), body = $("points");
  body.innerHTML = "";
  if (!d) { head.innerHTML = `<div class="empty">${esc(t("dev.empty"))}</div>`; return; }
  const meta = t("dev.meta", { id: d.device_id, addr: d.address, template: d.template || "custom" });
  head.innerHTML = `<span style="font-size:22px">${ICONS[d.template] || "🧩"}</span>
    <div><h2>${esc(d.name)}</h2>
      <div class="meta">${esc(meta)}${d.description ? " · " + esc(d.description) : ""}</div></div>
    <div class="spacer"></div>
    ${d.comm && d.comm !== "enable" ? `<span class="meta" style="color:var(--danger,#c0392b);font-weight:600"
      title="${esc(t("dev.comm.title"))}">${esc(t("dev.comm", { state: d.comm }))}</span>
      <button class="btn" id="btnDccEnable">${esc(t("dev.comm.enable"))}</button>` : ""}
    <label class="meta">${esc(t("dev.priority"))}
      <select id="selPri">${Array.from({ length: 16 }, (_, i) => `<option ${i + 1 === S.priority ? "selected" : ""}>${i + 1}</option>`).join("")}</select></label>
    <button class="btn" id="btnCopyDev" title="${esc(t("dev.copy.title"))}">${esc(t("dev.copy"))}</button>
    <button class="btn" id="btnPaste" title="${esc(t("dev.paste.title"))}">${esc(t("dev.paste"))}</button>
    <button class="btn" id="btnPropsDev" title="${esc(t("dev.props.title"))}">${esc(t("dev.props"))}</button>
    <button class="btn" id="btnEditDev">${esc(t("dev.editYaml"))}</button>
    <button class="btn danger" id="btnDelDev">${esc(t("dev.delete"))}</button>`;
  $("selPri").onchange = (e) => { S.priority = Number(e.target.value); };
  $("btnEditDev").onclick = () => editDevice(d.device_id);
  $("btnCopyDev").onclick = () => copyDevice(d);
  $("btnPaste").onclick = pasteClip;
  $("btnPropsDev").onclick = () => openProps(d.device_id, `device:${d.device_id}`, d.name);
  if ($("btnDccEnable")) $("btnDccEnable").onclick = async () => {
    try { await api("POST", `/api/devices/${d.device_id}/dcc`, { state: "enable" }); } catch (e) { toast(e.message); }
  };
  $("btnDelDev").onclick = async () => {
    if (!confirm(t("dev.confirmDelete", { name: d.name, id: d.device_id }))) return;
    try { await api("DELETE", `/api/devices/${d.device_id}`); } catch (e) { toast(e.message); }
  };
  const f = S.filter.toLowerCase();
  for (const o of d.objects) {
    if (f && !d.name.toLowerCase().includes(f) && !o.name.toLowerCase().includes(f)) continue;
    body.appendChild(renderRow(d, o));
  }
}

// Trend-log row: target object, record count and an enable toggle (no value / command columns).
function renderTrendLogRow(d, o) {
  const tr = document.createElement("tr");
  tr.id = `row-${d.device_id}-${o.k}`;
  if (S.trend && S.trend.d === d.device_id && S.trend.k === o.k) tr.className = "sel";
  tr.innerHTML = `
    <td class="nm">${esc(o.name)}<small>${esc(o.description || t("tl.target", { target: o.target, interval: o.log_interval }))}</small></td>
    <td class="obj">${SHORT[o.type]}:${o.instance}</td>
    <td class="val"></td>
    <td>${esc(fmtUnits(o.units))}</td>
    <td class="pri"></td>
    <td></td>
    <td class="beh">${esc(o.target)}</td>
    <td class="cmd"><label class="meta"><input type="checkbox" class="tlen" title="${esc(t("tl.enable.title"))}"> ${esc(t("tl.enable"))}</label></td>`;
  tr.onclick = (e) => { if (!e.target.closest("input,select,button,label")) openTrend(d.device_id, o); };
  tr.querySelector(".tlen").onchange = (e) =>
    api("POST", `/api/devices/${d.device_id}/trendlog/${o.instance}/enable`, { enabled: e.target.checked }).catch((er) => toast(er.message));
  updateTrendLogRow(tr, o, false);
  return tr;
}

function updateTrendLogRow(tr, o, flash = true) {
  const v = tr.querySelector(".val");
  v.textContent = t("tl.records", { n: o.value, size: o.buffer_size });
  if (flash) { v.classList.add("flash"); setTimeout(() => v.classList.remove("flash"), 60); }
  tr.querySelector(".tlen").checked = !!o.enabled;
}

// Schedule / calendar row: current value, next transition, targets; click opens the read-only detail.
const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
const pad2 = (n) => String(n).padStart(2, "0");
function fmtSimTime(ts) {
  const d = new Date(ts * 1000);
  return `${t("day." + DAYS[(d.getDay() + 6) % 7])} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

function renderSchedRow(d, o) {
  const tr = document.createElement("tr");
  tr.id = `row-${d.device_id}-${o.k}`;
  if (S.trend && S.trend.d === d.device_id && S.trend.k === o.k) tr.className = "sel";
  const sub = o.description || (o.schedule
    ? (o.targets.length ? t("sch.targets", { targets: o.targets.join(", "), priority: o.write_priority }) : t("sch.notargets"))
    : "");
  tr.innerHTML = `
    <td class="nm">${esc(o.name)}${sub ? `<small>${esc(sub)}</small>` : ""}</td>
    <td class="obj">${SHORT[o.type]}:${o.instance}</td>
    <td class="val"></td>
    <td></td>
    <td class="pri">${o.schedule ? o.write_priority : ""}</td>
    <td></td>
    <td class="beh">${esc(o.schedule ? o.targets.join(", ") : "")} <span class="errmark"></span></td>
    <td class="cmd meta"></td>`;
  tr.onclick = () => openTrend(d.device_id, o);
  updateSchedRow(tr, o, false);
  return tr;
}

function updateSchedRow(tr, o, flash = true) {
  const v = tr.querySelector(".val");
  v.textContent = o.calendar ? String(!!o.value) : String(o.value ?? "—");
  if (flash) { v.classList.add("flash"); setTimeout(() => v.classList.remove("flash"), 60); }
  tr.querySelector(".errmark").textContent = o.error ? "⚠" : "";
  tr.querySelector(".errmark").title = o.error || "";
  tr.querySelector(".cmd").textContent = o.calendar ? `${o.dates.length} ${t("cal.dates")}`
    : o.next ? t("sch.next", { time: fmtSimTime(o.next[0]), value: o.next[1] }) : t("sch.nonext");
}

function renderSchedView() {
  const o = S.trend && S.trend.o, box = $("schedView");
  if (!o || !(o.schedule || o.calendar)) return;
  const times = (list) => list.map(([tm, v]) => `${esc(tm)} → ${esc(v ?? "null")}`).join(", ");
  let h = "";
  if (o.schedule) {
    h += `<h4>${esc(t("sch.weekly", { value: o.default }))}</h4><table>`;
    for (const day of DAYS) h += `<tr><th>${esc(t("day." + day))}</th><td>${times((o.weekly || {})[day] || [])}</td></tr>`;
    h += "</table>";
    if ((o.exceptions || []).length) {
      h += `<h4>${esc(t("sch.exceptions"))}</h4><table>`;
      for (const ex of o.exceptions) h += `<tr><th>${esc(ex.period)}</th><td>${esc(t("sch.prio", { priority: ex.priority }))}: ${times(ex.times)}</td></tr>`;
      h += "</table>";
    }
  } else {
    h += `<h4>${esc(t("cal.dates"))} (${esc(t("cal.today", { value: !!o.value }))})</h4><table>`;
    for (const dt of o.dates || []) h += `<tr><td>${esc(dt)}</td></tr>`;
    h += "</table>";
  }
  box.innerHTML = h + `<p class="meta">${esc(t("sch.edit"))}</p>`;
}

// Notification-class row (read-only): priorities, ack-required flags (to-offnormal / to-fault / to-normal)
// and a recipient summary.
function renderNcRow(d, o) {
  const tr = document.createElement("tr");
  tr.id = `row-${d.device_id}-${o.k}`;
  tr.title = t("nc.readonly");
  const [po, pf, pn] = o.nc_priority;
  const flags = o.ack_required.map((x) => (x ? "Y" : "N")).join("/");
  const rcps = o.recipients.map((r) => t("nc.recipient", {
    recipient: r.recipient, process: r.process_id, mode: t(r.confirmed ? "nc.confirmed" : "nc.unconfirmed") }));
  const sub = o.description || (rcps.length ? t("nc.recipients", { n: rcps.length }) : t("nc.norecipients"));
  tr.innerHTML = `
    <td class="nm">${esc(o.name)}<small>${esc(sub)}</small></td>
    <td class="obj">${SHORT[o.type]}:${o.instance}</td>
    <td class="val">${esc(t("nc.priority", { offnormal: po, fault: pf, normal: pn }))}</td>
    <td></td>
    <td></td>
    <td></td>
    <td class="beh">${esc(rcps.join("; "))}</td>
    <td class="cmd meta">${esc(t("nc.ack", { flags }))}</td>`;
  return tr;
}

// Event Enrollment row: monitored object and its value, event state badge and an Ack button.
function renderEERow(d, o) {
  const tr = document.createElement("tr");
  tr.id = `row-${d.device_id}-${o.k}`;
  tr.title = t("ee.readonly");
  const sub = o.description || t("ee.watch", { event_type: o.event_type, object: o.monitored });
  tr.innerHTML = `
    <td class="nm">${esc(o.name)}<span class="abox"></span><small>${esc(sub)}</small></td>
    <td class="obj">${SHORT[o.type]}:${o.instance}</td>
    <td class="val"></td>
    <td>${esc(fmtUnits(o.units))}</td>
    <td></td>
    <td></td>
    <td class="beh">${esc(o.event_type)}</td>
    <td class="cmd"></td>`;
  const a = document.createElement("button");
  a.className = "btn small ackbtn";
  a.textContent = t("alarm.ack");
  a.title = t("alarm.ack.title");
  a.onclick = () => ackAlarm(d.device_id, o.k);
  tr.querySelector(".cmd").appendChild(a);
  updateEERow(tr, d, o, false);
  return tr;
}

// value of the monitored object, formatted like that object's own row
function eeValue(d, o) {
  const m = S.idx.get(`${d.device_id ?? d}|${o.monitored_key}`);
  return `${o.monitored}: ${m ? fmtValue({ ...m, value: o.value }) : o.value}`;
}

function updateEERow(tr, d, o, flash = true) {
  const v = tr.querySelector(".val");
  v.textContent = eeValue(d, o);
  tr.querySelector(".abox").innerHTML = alarmBadge(o);
  tr.querySelector(".ackbtn").hidden = !o.unacked;
  if (flash) { v.classList.add("flash"); setTimeout(() => v.classList.remove("flash"), 60); }
}

// File row: size (and record count), MIME type, access method; Program row: state plus a Program_Change menu.
const PROG_REQUESTS = ["load", "run", "halt", "restart", "unload"];
function renderFileProgRow(d, o) {
  const tr = document.createElement("tr");
  tr.id = `row-${d.device_id}-${o.k}`;
  const sub = o.description || (o.file ? (o.path || o.file_type) : o.instance_of);
  tr.innerHTML = `
    <td class="nm">${esc(o.name)}${sub ? `<small>${esc(sub)}</small>` : ""}</td>
    <td class="obj">${SHORT[o.type]}:${o.instance}</td>
    <td class="val"></td>
    <td></td>
    <td></td>
    <td></td>
    <td class="beh">${esc(o.file ? `${o.file_type} (${o.access})` : "")}</td>
    <td class="cmd meta"></td>`;
  if (o.program) {
    const sel = document.createElement("select");
    sel.title = t("prog.change.title");
    sel.innerHTML = `<option value="">${esc(t("prog.change"))}</option>`
      + PROG_REQUESTS.map((r) => `<option value="${r}">${r}</option>`).join("");
    sel.onchange = () => {
      const request = sel.value;
      sel.value = "";
      if (request) api("POST", `/api/devices/${d.device_id}/program/${o.instance}/change`, { request }).catch((er) => toast(er.message));
    };
    tr.querySelector(".cmd").appendChild(sel);
  }
  updateFileProgRow(tr, o, false);
  return tr;
}

function updateFileProgRow(tr, o, flash = true) {
  const v = tr.querySelector(".val");
  if (o.file) {
    v.textContent = o.records != null ? t("file.records", { n: o.records, bytes: o.value }) : t("file.bytes", { n: o.value });
    tr.querySelector(".beh").title = o.modified ? t("file.modified", { time: new Date(o.modified * 1000).toLocaleString() }) : "";
    if (o.read_only) tr.querySelector(".cmd").textContent = t("file.readonly");
  } else {
    v.textContent = o.value + (o.value === "halted" && o.halt_text ? ` (${o.halt_text})` : "");
  }
  if (flash) { v.classList.add("flash"); setTimeout(() => v.classList.remove("flash"), 60); }
}

// Life safety row: present value (with the tracking value while they differ), mode and silenced state;
// points get a detector-state menu (zones follow their members).
const LS_STATES = ["quiet", "pre-alarm", "alarm", "fault", "fault-alarm", "supervisory", "tamper", "test-alarm"];
function renderLifeSafetyRow(d, o) {
  const tr = document.createElement("tr");
  tr.id = `row-${d.device_id}-${o.k}`;
  const sub = o.description || (o.zone ? t("ls.members", { names: (o.members || []).join(", ") || "-" }) : "");
  tr.innerHTML = `
    <td class="nm">${esc(o.name)}${sub ? `<small>${esc(sub)}</small>` : ""}</td>
    <td class="obj">${SHORT[o.type]}:${o.instance}</td>
    <td class="val"></td>
    <td></td>
    <td></td>
    <td></td>
    <td class="beh"></td>
    <td class="cmd"></td>`;
  if (!o.zone) {
    const sel = document.createElement("select");
    sel.title = t("ls.state.title");
    sel.innerHTML = `<option value="">${esc(t("ls.state"))}</option>`
      + LS_STATES.map((s) => `<option value="${s}">${s}</option>`).join("");
    sel.onchange = () => {
      const state = sel.value;
      sel.value = "";
      if (state) api("POST", `/api/devices/${d.device_id}/life-safety/${o.k}/state`, { state }).catch((er) => toast(er.message));
    };
    tr.querySelector(".cmd").appendChild(sel);
  }
  updateLifeSafetyRow(tr, o, false);
  return tr;
}

function updateLifeSafetyRow(tr, o, flash = true) {
  const v = tr.querySelector(".val");
  v.textContent = o.value + (o.tracking && o.tracking !== o.value ? ` (${t("ls.tracking")}: ${o.tracking})` : "");
  v.style.color = o.value !== "quiet" ? "var(--bad, #c62828)" : "";
  tr.querySelector(".beh").textContent = `${t("ls.mode")}: ${o.mode}` + (o.silenced !== "unsilenced" ? ` · ${o.silenced}` : "");
  if (flash) { v.classList.add("flash"); setTimeout(() => v.classList.remove("flash"), 60); }
}

// Every point row: multi-select with Ctrl / Shift click (for copy) and a properties button.
function renderRow(d, o) {
  const tr = renderRowInner(d, o);
  tr.dataset.k = o.k;
  if (S.sel.has(o.k)) tr.classList.add("picked");
  tr.addEventListener("click", (e) => {
    if (e.target.closest("input,select,button,a")) return;
    pickRow(o.k, e);
    if (e.ctrlKey || e.metaKey || e.shiftKey) e.stopImmediatePropagation();
  }, true);
  const b = document.createElement("button");
  b.className = "btn small propbtn"; b.textContent = "⚙"; b.title = t("row.props.title");
  b.onclick = (e) => { e.stopPropagation(); openProps(d.device_id, o.k, o.name); };
  tr.querySelector("td").prepend(b);
  return tr;
}

function pickRow(k, e) {
  const keys = [...document.querySelectorAll("#points tr[data-k]")].map((r) => r.dataset.k);
  if (e.shiftKey && S.anchor && keys.includes(S.anchor)) {
    const [a, b] = [keys.indexOf(S.anchor), keys.indexOf(k)].sort((x, y) => x - y);
    if (!(e.ctrlKey || e.metaKey)) S.sel.clear();
    keys.slice(a, b + 1).forEach((x) => S.sel.add(x));
  } else if (e.ctrlKey || e.metaKey) {
    if (S.sel.has(k)) S.sel.delete(k); else S.sel.add(k);
    S.anchor = k;
  } else {
    S.sel = new Set([k]); S.anchor = k;
  }
  document.querySelectorAll("#points tr[data-k]").forEach((r) => r.classList.toggle("picked", S.sel.has(r.dataset.k)));
}

function renderRowInner(d, o) {
  if (o.file || o.program) return renderFileProgRow(d, o);
  if (o.life_safety) return renderLifeSafetyRow(d, o);
  if (o.notification_class) return renderNcRow(d, o);
  if (o.event_enrollment) return renderEERow(d, o);
  if (o.trendlog) return renderTrendLogRow(d, o);
  if (o.schedule || o.calendar) return renderSchedRow(d, o);
  const tr = document.createElement("tr");
  tr.id = `row-${d.device_id}-${o.k}`;
  if (S.trend && S.trend.d === d.device_id && S.trend.k === o.k) tr.className = "sel";
  const beh = o.behavior ? `<span title="${esc(JSON.stringify(o.behavior_spec))}">${esc(o.behavior)}</span>` : "";
  tr.innerHTML = `
    <td class="nm">${esc(o.name)}${o.alarm ? '<span class="abox"></span>' : ""}${o.description ? `<small>${esc(o.description)}</small>` : ""}</td>
    <td class="obj">${SHORT[o.type]}:${o.instance}</td>
    <td class="val"></td>
    <td>${esc(fmtUnits(o.units))}</td>
    <td class="pri"></td>
    <td><input type="checkbox" class="oos" title="${esc(t("row.oos.title"))}"></td>
    <td class="beh">${beh} <span class="errmark"></span></td>
    <td class="cmd"></td>`;
  tr.onclick = (e) => { if (!e.target.closest("input,select,button")) openTrend(d.device_id, o); };
  tr.querySelector(".oos").onchange = (e) =>
    api("POST", `/api/devices/${d.device_id}/objects/${o.k}/oos`, { out_of_service: e.target.checked }).catch((er) => toast(er.message));
  buildCommand(tr.querySelector(".cmd"), d, o);
  updateRow(tr, o, false);
  return tr;
}

function buildCommand(td, d, o) {
  const url = `/api/devices/${d.device_id}/objects/${o.k}`;
  const send = (value) => api("POST", `${url}/write`, { value, priority: o.commandable ? S.priority : null }).catch((e) => toast(e.message));
  const button = (label) => { const b = document.createElement("button"); b.className = "btn small"; b.textContent = label; return b; };
  if (o.type.startsWith("binary")) {
    const on = button(o.active_text || t("cmd.on"));
    const off = button(o.inactive_text || t("cmd.off"));
    on.onclick = () => send(1); off.onclick = () => send(0);
    td.append(on, off);
  } else if (o.type.startsWith("multi-state")) {
    const sel = document.createElement("select");
    o.states.forEach((s, i) => sel.add(new Option(`${i + 1}: ${s}`, i + 1)));
    sel.value = o.value;
    sel.onchange = () => send(Number(sel.value));
    td.append(sel);
  } else {
    const inp = document.createElement("input"); inp.type = "number"; inp.step = "any"; inp.placeholder = fmtValue(o);
    if (o.min != null) inp.min = o.min;
    if (o.max != null) inp.max = o.max;
    const b = button(t("cmd.set"));
    const go = () => { if (inp.value !== "") { send(Number(inp.value)); inp.value = ""; } };
    b.onclick = go; inp.onkeydown = (e) => { if (e.key === "Enter") go(); };
    td.append(inp, b);
  }
  if (o.alarm) {
    const a = button(t("alarm.ack"));
    a.classList.add("ackbtn");
    a.title = t("alarm.ack.title");
    a.onclick = () => ackAlarm(d.device_id, o.k);
    td.append(a);
  }
  if (o.commandable) {
    const r = button(t("cmd.relinquish"));
    r.title = t("cmd.relinquish.title");
    r.onclick = () => api("POST", `${url}/relinquish`, {}).catch((e) => toast(e.message));
    td.append(r);
  }
}

function updateRow(tr, o, flash = true) {
  const v = tr.querySelector(".val");
  const text = fmtValue(o);
  v.innerHTML = o.type.startsWith("binary") ? `<span class="pill ${o.value ? "active" : ""}">${esc(text)}</span>` : esc(text);
  if (o.type === "loop" && o.sp != null) {
    // Loop: output plus controlled variable (PV) and setpoint (SP)
    v.innerHTML += ` <small style="color: var(--muted)" title="${esc(`${o.loop?.controlled ?? ""} -> ${o.loop?.manipulated ?? ""}`)}">`
      + `${esc(t("loop.pv"))} ${o.cv.toFixed(2)} / ${esc(t("loop.sp"))} ${o.sp.toFixed(2)}</small>`;
  }
  if (flash) { v.classList.add("flash"); setTimeout(() => v.classList.remove("flash"), 60); }
  tr.querySelector(".pri").innerHTML = o.commandable && o.priority ? `<span class="prio">${o.priority}</span>` : "";
  tr.querySelector(".oos").checked = !!o.oos;
  const ab = tr.querySelector(".abox");
  if (ab) ab.innerHTML = alarmBadge(o);
  const ack = tr.querySelector(".ackbtn");
  if (ack) ack.hidden = !o.unacked;
  const em = tr.querySelector(".errmark");
  em.textContent = o.error ? "⚠" : ""; em.title = o.error || "";
  const sel = tr.querySelector(".cmd select");
  if (sel && document.activeElement !== sel) sel.value = o.value;
  const inp = tr.querySelector(".cmd input");
  if (inp) inp.placeholder = text;
}

function applyChanges(msg) {
  if (msg.sim_hour != null) $("clock").textContent = hhmm(msg.sim_hour);
  let listDirty = false, alarmsDirty = false;
  for (const c of msg.changes) {
    const o = S.idx.get(`${c.d}|${c.k}`);
    if (!o) continue;
    const hadErr = !!o.error;
    if (o.file || o.program) {
      const { d: _d, k: _k, ...st } = c;
      Object.assign(o, st);
      const tr = c.d === S.dev && document.getElementById(`row-${c.d}-${c.k}`);
      if (tr) updateFileProgRow(tr, o);
      continue;
    }
    if (o.life_safety) {
      const { d: _d, k: _k, ...st } = c;
      Object.assign(o, st);
      const tr = c.d === S.dev && document.getElementById(`row-${c.d}-${c.k}`);
      if (tr) updateLifeSafetyRow(tr, o);
      continue;
    }
    if (o.event_enrollment) {
      if (o.event_state !== c.event_state || o.unacked !== c.unacked) alarmsDirty = true;
      Object.assign(o, { value: c.value, event_state: c.event_state, unacked: c.unacked });
      const tr = c.d === S.dev && document.getElementById(`row-${c.d}-${c.k}`);
      if (tr) updateEERow(tr, c.d, o);
      continue;
    }
    if (o.schedule || o.calendar) {
      const { d: _d, k: _k, ...st } = c;
      Object.assign(o, st);
      if (!("error" in c)) delete o.error;
      const tr = c.d === S.dev && document.getElementById(`row-${c.d}-${c.k}`);
      if (tr) updateSchedRow(tr, o);
      if (S.trend && S.trend.d === c.d && S.trend.k === c.k) renderSchedView();
      continue;
    }
    if (o.trendlog) {
      Object.assign(o, { value: c.value, total: c.total, enabled: c.enabled, last: c.last });
      const tr = c.d === S.dev && document.getElementById(`row-${c.d}-${c.k}`);
      if (tr) updateTrendLogRow(tr, o);
      const td = S.trend && S.trend.d === c.d && S.trend.k === c.k ? S.trend.data : null;
      if (td && c.last && (!td.length || c.last[0] > td[td.length - 1][0])) {
        td.push(c.last);
        while (td.length > o.buffer_size) td.shift();  // mirror the ring buffer
        drawTrend();
      }
      continue;
    }
    Object.assign(o, { value: c.value, oos: c.oos, priority: c.priority, error: c.error });
    if ("event_state" in c) {
      if (o.event_state !== c.event_state || o.unacked !== c.unacked) alarmsDirty = true;
      Object.assign(o, { event_state: c.event_state, unacked: c.unacked });
    }
    if (hadErr !== !!o.error) listDirty = true;
    if (c.d === S.dev) {
      const tr = document.getElementById(`row-${c.d}-${c.k}`);
      if (tr) updateRow(tr, o);
    }
    if (S.trend && S.trend.d === c.d && S.trend.k === c.k) {
      S.trend.data.push([msg.t, c.value]);
      if (S.trend.data.length > 2000) S.trend.data.shift();
      drawTrend();
    }
  }
  if (listDirty) renderDevices();
  if (alarmsDirty) renderAlarms();
}

// ------------------------------------------------------------------ trend

async function openTrend(d, o) {
  S.trend = { d, k: o.k, o, data: [] };
  $("trend").hidden = false;
  const sched = !!(o.schedule || o.calendar);
  $("trendCanvas").hidden = sched;
  $("schedView").hidden = !sched;
  $("trendTitle").textContent = `${currentDevice()?.name} / ${o.name} (${SHORT[o.type]}:${o.instance}) ${fmtUnits(o.units)}`;
  document.querySelectorAll(".points tr.sel").forEach((r) => r.classList.remove("sel"));
  document.getElementById(`row-${d}-${o.k}`)?.classList.add("sel");
  // trend logs show their logged buffer (simulated-clock timestamps); points show the live history
  if (sched) { renderSchedView(); return; }
  const url = o.trendlog ? `/api/devices/${d}/trendlog/${o.instance}` : `/api/history/${d}/${o.k}`;
  try { S.trend.data = await api("GET", url); } catch (e) { toast(e.message); }
  drawTrend();
}

function drawTrend() {
  const tr = S.trend, cv = $("trendCanvas");
  if (!tr || $("trend").hidden || tr.o.schedule || tr.o.calendar) return;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext("2d"); g.scale(dpr, dpr); g.clearRect(0, 0, W, H);
  // Colors come from the shell theme tokens, so the chart follows light / dark.
  const css = getComputedStyle(document.documentElement);
  const tok = (name) => css.getPropertyValue(name).trim();
  const line = tok("--line"), muted = tok("--muted"), acc = tok("--accent");
  const data = tr.data;
  if (data.length < 1) return;
  const L = 56, R = 10, T = 8, B = 20;
  const t1 = data[data.length - 1][0], t0 = Math.min(data[0][0], t1 - 10);
  let lo = Math.min(...data.map((p) => p[1])), hi = Math.max(...data.map((p) => p[1]));
  if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const x = (tt) => L + (tt - t0) / (t1 - t0) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  g.font = `11px ${tok("--font") || "Arial, sans-serif"}`; g.fillStyle = muted; g.strokeStyle = line; g.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const v = lo + (hi - lo) * i / 4, yy = y(v);
    g.beginPath(); g.moveTo(L, yy); g.lineTo(W - R, yy); g.stroke();
    g.fillText(v.toFixed(Math.abs(hi - lo) < 10 ? 2 : 0), 4, yy + 4);
  }
  const fmtT = (s) => new Date(s * 1000).toLocaleTimeString();
  g.fillText(fmtT(t0), L, H - 4);
  g.textAlign = "right"; g.fillText(fmtT(t1), W - R, H - 4); g.textAlign = "left";
  const ttype = tr.o.trendlog ? (tr.o.target_key || "").split(":")[0] : tr.o.type;
  const stepped = !ttype.startsWith("analog");
  g.strokeStyle = acc; g.lineWidth = 1.8; g.beginPath();
  data.forEach(([tt, v], i) => {
    if (i === 0) g.moveTo(x(tt), y(v));
    else { if (stepped) g.lineTo(x(tt), y(data[i - 1][1])); g.lineTo(x(tt), y(v)); }
  });
  g.lineTo(W - R, y(data[data.length - 1][1]));
  g.stroke();
}

// ------------------------------------------------------------------ log

function addLog(e) {
  const li = document.createElement("li");
  li.innerHTML = `<span class="t">${new Date(e.t * 1000).toLocaleTimeString()}</span><span class="k-${esc(e.kind)}">[${esc(e.kind)}] ${esc(e.text)}</span>`;
  const ul = $("log");
  ul.prepend(li);
  while (ul.children.length > 200) ul.lastChild.remove();
  $("logCount").textContent = `(${ul.children.length})`;
}

function toggleLog() {
  const bar = $("logbar");
  bar.hidden = !bar.hidden;
  Shell.updateItem("view.log", { checked: !bar.hidden });
}

// ------------------------------------------------------------------ dialogs

function yamlDialog(title, text, onApply) {
  $("yamlTitle").textContent = title;
  $("yamlText").value = text;
  $("yamlErr").textContent = "";
  $("yamlApply").onclick = async (ev) => {
    ev.preventDefault();
    try { await onApply($("yamlText").value); $("dlgYaml").close(); }
    catch (e) { $("yamlErr").textContent = e.message; }
  };
  $("dlgYaml").showModal();
}

async function editDevice(id) {
  try {
    const text = await api("GET", `/api/devices/${id}/config`);
    yamlDialog(t("dlg.editDevice", { id }), text, (x) => api("PUT", `/api/devices/${id}/config`, x, true));
  } catch (e) { toast(e.message); }
}

async function editConfig() {
  try {
    const text = await api("GET", "/api/config?format=yaml");
    yamlDialog(t("dlg.editAll"), text, (x) => api("PUT", "/api/config", x, true));
  } catch (e) { toast(e.message); }
}

async function openAdd() {
  let tpls;
  try { tpls = await api("GET", "/api/templates"); } catch (e) { toast(e.message); return; }
  const sel = $("addTemplate");
  sel.innerHTML = "";
  for (const tp of tpls) sel.add(new Option(`${ICONS[tp.name] || ""} ${tp.title} (${tp.name})`, tp.name));
  const fill = () => {
    const tp = tpls.find((x) => x.name === sel.value);
    $("addParams").value = JSON.stringify(tp.params, null, 2);
    $("addName").value = `${tp.name}-${((S.snap?.devices.length || 0) + 1)}`;
  };
  sel.onchange = fill; fill();
  $("addId").value = ""; $("addErr").textContent = "";
  $("addApply").onclick = async (ev) => {
    ev.preventDefault();
    try {
      const params = $("addParams").value.trim() ? JSON.parse($("addParams").value) : {};
      const body = { template: sel.value, name: $("addName").value.trim(), params };
      if ($("addId").value) body.device_id = Number($("addId").value);
      const r = await api("POST", "/api/devices", body);
      S.dev = r.device_id;
      $("dlgAdd").close();
    } catch (e) { $("addErr").textContent = e.message; }
  };
  $("dlgAdd").showModal();
}

// ------------------------------------------------------------------ clipboard (page memory)

function selectDevice(id) {
  if (id !== S.dev) { S.sel.clear(); S.anchor = null; }
  S.dev = id; renderDevices(); renderDevice();
}

function copyDevice(d) {
  S.clip = { kind: "device", device_id: d.device_id, name: d.name };
  toast(t("clip.device", { name: d.name }), "ok");
}

async function copySel() {
  const d = currentDevice();
  if (!d) return;
  const keys = d.objects.map((o) => o.k).filter((k) => S.sel.has(k));
  if (!keys.length) { copyDevice(d); return; }
  try {
    const objects = await api("GET", `/api/devices/${d.device_id}/objects/config?keys=${encodeURIComponent(keys.join(","))}`);
    S.clip = { kind: "objects", device_id: d.device_id, name: d.name, objects };
    toast(t("clip.objects", { n: objects.length, name: d.name }), "ok");
  } catch (e) { toast(e.message); }
}

async function pasteClip() {
  const c = S.clip;
  if (!c) { toast(t("clip.empty"), "info"); return; }
  try {
    if (c.kind === "device") {
      const r = await api("POST", `/api/devices/${c.device_id}/duplicate`);
      S.dev = r.device_id; S.sel.clear();
      toast(t("clip.duplicated", { name: r.name, id: r.device_id }), "ok");
      return;
    }
    if (S.dev == null) return;
    const r = await api("POST", `/api/devices/${S.dev}/objects/paste`, { objects: c.objects });
    if (r.pasted.length) toast(t("clip.pasted", { n: r.pasted.length }), "ok");
    S.sel = new Set(r.pasted.map((p) => p.key));
    if (r.rejected.length) {
      toast(t("clip.rejected", { n: r.rejected.length, list: r.rejected.map((x) => `${x.name}: ${x.reason}`).join("; ") }));
    }
  } catch (e) { toast(e.message); }
}

// Ctrl+C / Ctrl+V act on points / devices only while no text field, dialog or text selection has the focus.
document.addEventListener("keydown", (e) => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return;
  const el = e.target;
  if (el.closest && el.closest("input,textarea,select,[contenteditable],dialog")) return;
  if (document.querySelector("dialog[open]") || String(window.getSelection() || "")) return;
  const k = e.key.toLowerCase();
  if (k === "c") { e.preventDefault(); copySel(); }
  else if (k === "v") { e.preventDefault(); pasteClip(); }
});

// ------------------------------------------------------------------ property grid

const fmtProp = (v) => (v === null || typeof v !== "object" ? String(v) : JSON.stringify(v));

async function openProps(devId, key, label) {
  const dlg = $("dlgProps");
  $("propsTitle").textContent = t("props.title", { object: `${label} (${key})` });
  $("propsErr").textContent = "";
  $("propsRefresh").onclick = () => loadProps(devId, key);
  await loadProps(devId, key);
  if (!dlg.open) dlg.showModal();
}

async function loadProps(devId, key) {
  let list;
  try { list = await api("GET", `/api/devices/${devId}/objects/${key}/properties`); }
  catch (e) { $("propsErr").textContent = e.message; return; }
  const body = $("propsBody");
  body.innerHTML = "";
  for (const p of list) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="num">${p.id}</td><td>${esc(p.name)}</td><td class="pv">${esc(fmtProp(p.value))}</td>
      <td><small>${esc(p.datatype)}</small></td><td class="pe"></td>`;
    const td = tr.querySelector(".pe");
    if (!p.writable) td.innerHTML = `<small class="muted">${esc(t("props.ro"))}</small>`;
    else if (!p.editable) td.innerHTML = `<small class="muted">${esc(t("props.constructed"))}</small>`;
    else td.append(...propEditor(devId, key, p));
    body.appendChild(tr);
  }
}

function propEditor(devId, key, p) {
  let inp;
  if (p.kind === "boolean" || p.kind === "enumerated") {
    inp = document.createElement("select");
    (p.kind === "boolean" ? ["false", "true"] : p.choices).forEach((c) => inp.add(new Option(c, c)));
    inp.value = String(p.value);
  } else {
    inp = document.createElement("input");
    inp.type = p.kind === "charstring" ? "text" : "number";
    if (p.kind !== "charstring") inp.step = p.kind === "real" || p.kind === "double" ? "any" : "1";
    inp.value = p.value ?? "";
  }
  const out = [inp];
  let pri = null;
  if (p.commandable) {  // commandable present-value: write at a chosen priority, or relinquish it
    pri = document.createElement("select");
    for (let i = 1; i <= 16; i++) pri.add(new Option(String(i), i));
    pri.value = S.priority;
    out.push(pri);
  }
  const send = async (value) => {
    $("propsErr").textContent = "";
    try {
      await api("PUT", `/api/devices/${devId}/objects/${key}/properties/${p.name}`, { value, priority: pri ? Number(pri.value) : null });
      toast(t("props.written", { prop: p.name }), "ok");
      await loadProps(devId, key);
    } catch (e) { $("propsErr").textContent = e.message; }
  };
  const read = () => {
    if (p.kind === "boolean") return inp.value === "true";
    if (p.kind === "charstring" || p.kind === "enumerated") return inp.value;
    return Number(inp.value);
  };
  const b = document.createElement("button");
  b.type = "button"; b.className = "btn small"; b.textContent = t("props.set");
  b.onclick = () => send(read());
  if (inp.tagName === "INPUT") inp.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); send(read()); } };
  out.push(b);
  if (pri) {
    const r = document.createElement("button");
    r.type = "button"; r.className = "btn small"; r.textContent = t("props.null");
    r.onclick = () => send(null);
    out.push(r);
  }
  return out;
}

// ------------------------------------------------------------------ actions

const setSim = (body) => api("POST", "/api/simulation", body).catch((e) => toast(e.message));
const toggleRun = () => { if (S.snap) setSim({ running: !S.snap.simulation.running }); };
const saveConfig = () => api("POST", "/api/config/save").then(() => toast(t("save.ok"), "ok")).catch((e) => toast(e.message));

async function importFiles(e) {
  const files = [...e.target.files]; if (!files.length) return;
  const fd = new FormData(); files.forEach((f) => fd.append("file", f));
  try {
    const r = await api("POST", "/api/config/import", fd);
    if (r && r.warnings && r.warnings.length) toast(t("import.warn", { n: r.warnings.length }), "info");
    else toast(t("import.ok"), "ok");
  } catch (er) { toast(t("import.fail", { msg: er.message })); }
  e.target.value = "";
}

// ------------------------------------------------------------------ shell / menus

Shell.init({
  ...PRODUCT,
  about: [["about.stack", t("about.stack.value")]],
  // A function so Shell.helpMenu() sees the links passed above.
  menus: () => [
    { id: "file", label: "menu.file", items: [
      { id: "file.import", label: "menu.file.import", title: t("menu.file.import.title"), onClick: () => $("fileImport").click() },
      { id: "file.export", label: "menu.file.export", submenu: [
        { id: "file.export.yaml", label: "menu.file.export.yaml", href: "/api/config/export?format=yaml", download: true },
        { id: "file.export.json", label: "menu.file.export.json", href: "/api/config/export?format=json", download: true },
        { id: "file.export.ede", label: "menu.file.export.ede", href: "/api/config/export?format=ede", download: true },
        { id: "file.export.xlsx", label: "menu.file.export.xlsx", href: "/api/config/export?format=xlsx", download: true },
      ] },
      { id: "file.template", label: "menu.file.template", title: t("menu.file.template.title"), href: "/api/config/xlsx-template", download: true },
      { separator: true },
      { id: "file.save", label: "menu.file.save", disabled: true, onClick: saveConfig },
    ] },
    { id: "edit", label: "menu.edit", items: [
      { id: "edit.copy", label: "menu.edit.copy", title: t("menu.edit.copy.title"), onClick: copySel },
      { id: "edit.paste", label: "menu.edit.paste", title: t("menu.edit.paste.title"), onClick: pasteClip },
      { id: "edit.config", label: "menu.edit.config", onClick: editConfig },
      { id: "edit.add", label: "menu.edit.add", onClick: openAdd },
    ] },
    { id: "sim", label: "menu.sim", items: [
      { id: "sim.run", label: "menu.sim.pause", onClick: toggleRun },
      { id: "sim.speed", label: "menu.sim.speed", submenu: speedItems(null) },
      { id: "sim.sync", label: "menu.sim.sync", onClick: async () => {
        try { await api("POST", "/api/simulation", { set_time: new Date().toISOString() }); } catch (e) { toast(e.message); }
      } },
    ] },
    { id: "view", label: "menu.view", items: [
      { id: "view.log", label: "menu.view.log", checked: true, onClick: toggleLog },
      { id: "view.alarms", label: "menu.view.alarms", onClick: openAlarms },
      { separator: true },
      Shell.themeItem(),
      Shell.langItem(),
    ] },
    Shell.helpMenu(),
  ],
});

Shell.setStatus(`
  <button type="button" class="st-alarm" id="alarmInd" hidden><span aria-hidden="true">⚠</span><span class="st-alarm-n">0</span></button>
  <span class="st-clock" id="clock" title="${esc(t("status.clock"))}">--:--</span>
  <button type="button" class="st-run" id="runInd"><span class="st-run-lbl"></span></button>
  <span class="st-net" id="netinfo">${esc(t("status.connecting"))}</span>
  <span class="conn off" id="conn" role="img" title="${esc(t("status.ws.off"))}" aria-label="${esc(t("status.ws.off"))}"></span>`);
renderSim({ running: true, time_scale: null });

function setConn(on) {
  const c = $("conn"), label = t(on ? "status.ws.on" : "status.ws.off");
  c.classList.toggle("off", !on); c.title = label; c.setAttribute("aria-label", label);
}

function renderNet(n) {
  const net = t("net.info", { bind: n.bind, router: n.router_device_id, vnet: n.virtual_network }) + (n.mode === "bbmd" ? t("net.bbmd") : "")
    + (n.foreign_device ? t("net.fd", { bbmd: n.foreign_device.bbmd, status: t(`net.fd.${n.foreign_device.status}`) }) : "");
  $("netinfo").textContent = net;
  $("netinfo").title = net;
}

function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onopen = () => setConn(true);
  ws.onclose = () => { setConn(false); setTimeout(connect, 2000); };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "snapshot") setSnapshot(msg.data);
    else if (msg.type === "values") applyChanges(msg);
    else if (msg.type === "log") addLog(msg.event);
    else if (msg.type === "network" && S.snap) {
      S.snap.network.foreign_device = msg.foreign_device; renderNet(S.snap.network);
    }
    else if (msg.type === "sim" && S.snap) {
      S.snap.simulation.running = msg.running; S.snap.simulation.time_scale = msg.time_scale; renderSim(S.snap.simulation);
    }
  };
}

$("runInd").onclick = toggleRun;
$("alarmInd").onclick = openAlarms;
$("fileImport").onchange = importFiles;
$("btnAdd").onclick = openAdd;
$("search").oninput = (e) => { S.filter = e.target.value; renderDevices(); renderDevice(); };
$("trendClose").onclick = () => { $("trend").hidden = true; S.trend = null; document.querySelectorAll(".points tr.sel").forEach((r) => r.classList.remove("sel")); };
$("logHead").onclick = () => $("logbar").classList.toggle("collapsed");
window.addEventListener("resize", drawTrend);
window.addEventListener("shell:themechange", drawTrend);
connect();
