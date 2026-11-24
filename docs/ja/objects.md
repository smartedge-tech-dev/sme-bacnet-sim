# オブジェクト

| キー | 備考 |
|---|---|
| `type` | `ai ao av bi bo bv msi mso msv acc pc loop file prog tl sch cal nc ee`（または `analog-input`、`trend-log`、`schedule`、`calendar`、`notification-class`、`event-enrollment` などの正式名） |
| `instance` | 任意。タイプごとに自動採番 |
| `name`, `description` | `name` は式の中の変数名にもなります |
| `units` | BACnet の engineering units（例: `degrees-celsius`、`kilowatts`、`percent`） |
| `value` | 初期値（バイナリ: 0/1、マルチステート: 1 始まりのインデックス） |
| `states` | マルチステートのテキスト |
| `active_text`, `inactive_text` | バイナリのテキスト（`"ON"`/`"OFF"` は引用符で囲んでください — YAML では真偽値として解釈されます） |
| `commandable` | `av/bv/msv` 用。出力オブジェクトは常にコマンド可能です |
| `min`, `max`, `cov_increment` | アナログの上下限と COV increment |
| `behavior` | 値のシミュレーション方法（後述） |
| `log_object`, `log_property`, `log_interval`, `logging_type`, `client_cov_increment`, `buffer_size`, `enabled` | Trend Log 専用（後述） |
| `weekly`, `exceptions`, `default`, `targets`, `priority_for_writing`, `effective_period` | Schedule 専用（後述） |
| `dates` | Calendar 専用（後述） |
| `scale`, `prescale` | Accumulator 専用（後述） |
| `scale_factor`, `input_object` | Pulse Converter 専用（後述） |
| `controlled_object`, `manipulated_object`, `setpoint`, `setpoint_object`, `proportional_constant`, `integral_constant`, `derivative_constant`, `bias`, `action`, `update_interval` | Loop 専用（後述） |
| `file_type`, `access`, `content`, `path`, `read_only`, `program_state`, `instance_of`, `program_location` | File / Program 専用（後述） |
| `monitored_object`, `event_type`, `event_parameters`, `notification_class`, `event_enable`, `notify_type`, `time_delay`, `time_delay_normal` | Event Enrollment 専用（後述） |
