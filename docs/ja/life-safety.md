# Life Safety Point と Life Safety Zone

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

完全な状態遷移は ASHRAE 135 にしか規定されていないため、シミュレーターは簡略化したモデルを使います。

- **Tracking_Value** は検知器の現在状態です。UI（行の検知状態メニュー、
  `POST /api/devices/{id}/life-safety/{type:instance}/state`）または任意の `random_alarm` behavior（ランダムに
  `state` になり、次の tick で `quiet` に戻る）で設定します。BACnet クライアントからは読み取り専用です。
- **Present_Value** は Tracking_Value が `quiet` 以外の間それに追従し、`quiet` に戻っても reset まで
  **ラッチ**されます。present-value への BACnet 書き込みは out-of-service 中のみ受け付けます。
- **Zone** の Tracking_Value は、Zone_Members の順で最初に `quiet` でないメンバーの present value
  （全員 `quiet` なら `quiet`）です。これは簡略化で、状態間の重大度の順序は適用しません。
- **LifeSafetyOperation**：`silence` / `silence-audible` / `silence-visual` は Silenced の audible / visible
  部分をセットし、`unsilence*` はクリアします。`reset` / `reset-alarm` / `reset-fault`（ここではすべて同じ）は
  Tracking_Value を Present_Value にコピーして unsilence します。`none` は何もしません。Zone への操作は
  メンバーにも適用され、object identifier なしの場合はデバイスの全 Life Safety オブジェクトに適用されます。
  ベンダー固有の操作は `services` / `optional-functionality-not-supported`、他のオブジェクト種別は `object` /
  `unsupported-object-type` を返します。すべての操作はイベントログに記録されます。
- **mode** は書き込み可能ですが accepted-modes のいずれかである必要があります（違反時 `property` /
  `value-out-of-range`）。**zone-members** は書き込み可能（WriteProperty、AddListElement / RemoveListElement）で、
  メンバー名として設定に書き戻されます（他デバイスへの参照は無視）。
- ReinitializeDevice で設定どおりの状態に戻ります。EDE エクスポートに含まれ（object type 21 / 22、値は状態番号）、
  EDE インポートでは種別・名前・状態を保持します。

非対応：change-of-life-safety イベント通知（alarm-values、life-safety-alarm-values、fault-values とイベント
プロパティは評価しません）、状態の重大度順序とモード依存の遷移、maintenance-required / direct-reading /
setting の動作、CreateObject / DeleteObject による Life Safety オブジェクトの作成 / 削除。
