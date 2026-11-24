# Life Safety Point 与 Life Safety Zone

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

完整的状态机只在 ASHRAE 135 中定义，模拟器使用简化模型：

- **Tracking_Value** 是探测器的实时状态。可在 UI（行的探测状态菜单，
  `POST /api/devices/{id}/life-safety/{type:instance}/state`）或用可选的 `random_alarm` behavior（随机变为
  `state`，下一个 tick 回到 `quiet`）设置。对 BACnet 客户端只读。
- **Present_Value** 在 Tracking_Value 非 `quiet` 时跟随它，回到 `quiet` 后保持**锁存**直到 reset。
  对 present-value 的 BACnet 写入仅在 out-of-service 时接受。
- **Zone** 的 Tracking_Value 取 Zone_Members 顺序中第一个非 `quiet` 成员的 present value（全部 `quiet` 则为
  `quiet`）。这是简化：不应用状态之间的严重程度顺序。
- **LifeSafetyOperation**：`silence` / `silence-audible` / `silence-visual` 置位、`unsilence*` 清除 Silenced 的
  audible / visible 部分；`reset` / `reset-alarm` / `reset-fault`（此处相同）把 Tracking_Value 复制到
  Present_Value 并解除消音；`none` 不做任何事。对 Zone 的操作也作用于其成员；不带 object identifier 时作用于
  设备的所有 Life Safety 对象。厂商自定义操作返回 `services` / `optional-functionality-not-supported`，其它对象
  类型返回 `object` / `unsupported-object-type`。所有操作都写入事件日志。
- **mode** 可写，但必须属于 accepted-modes（否则 `property` / `value-out-of-range`）；**zone-members** 可写
  （WriteProperty、AddListElement / RemoveListElement），并以成员名写回配置（指向其它设备的引用被忽略）。
- ReinitializeDevice 恢复配置的状态。EDE 导出包含它们（object type 21 / 22，值为状态编号），EDE 导入保留
  类型、名称和状态。

不支持：change-of-life-safety 事件报告（不评估 alarm-values、life-safety-alarm-values、fault-values 及事件属性）、
状态的严重程度顺序与依赖模式的状态转换、maintenance-required / direct-reading / setting 的行为、用
CreateObject / DeleteObject 创建 / 删除 Life Safety 对象。
