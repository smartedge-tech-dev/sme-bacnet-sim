# 克隆真实设备

`sme-bacnet-sim clone` 读取真实的 BACnet 设备并写出模拟器配置（YAML），之后的测试就可以离线对着模拟器进行，不再连接客户网络。

!!! warning "请先取得客户许可"
    读取客户网络上的设备需要客户许可，建议在非运营时间进行。路由器后面的 MS/TP 速度很慢，低端控制器可能因请求集中而负载升高：
    先用小范围的 `--who-is` 试，`--rate` 保持默认值。

## 只读保证

克隆客户端只能发送 **Who-Is、ReadProperty 和 ReadPropertyMultiple**。这在代码中强制执行：客户端应用拒绝其他所有 APDU
（`ReadOnlyViolation`），因此无法发送 WriteProperty、SubscribeCOV、DeviceCommunicationControl、ReinitializeDevice、
AtomicReadFile 等。它也是被动的：从不应答其他设备的请求（不发 I-Am，也不应答 ReadProperty）。测试会克隆一个模拟器实例，
并断言“真实”设备收到的只有这三种服务。

此外只有网络层流量：使用 `--network N` 而不带 `--address` 时，bacpypes3 可能发送 Who-Is-Router-To-Network 来查找路由器。

## 在网关上运行（Docker，主要方式）

典型场景：SSH 登录到客户 BACnet 网络上的 Linux 网关（例如 Moxa），在网关上运行克隆。主要方式是 Docker，只要有 Docker 就能运行，不需要 Python。

```sh
# 不能上外网的网关：把镜像 tar（通过 FTP 等）传上去再加载
docker load -i sme-bacnet-sim-<ver>-linux-<arch>.tar
# 能上外网时
docker pull ghcr.io/smartedge-tech-dev/sme-bacnet-sim:<ver>

docker run --rm --network host --user "$(id -u):$(id -g)" -v "$PWD":/out \
  ghcr.io/smartedge-tech-dev/sme-bacnet-sim:<ver> \
  sme-bacnet-sim clone --who-is 1000-1010 -o /out/site.yaml
```

- 必须使用 `--network host`：Who-Is 广播和 I-Am 应答无法穿过 Docker bridge 网络。
- `--user` 让容器能写入挂载的目录。也可以用 `python -m sme_bacnet_sim clone ...`。
- 把 `site.yaml`（和 `site.yaml.log.jsonl`）拷回来，用 `-c site.yaml` 启动模拟器。

### pip（次要方式）

有 Python 3.10 以上时，从源码检出或源码包安装：`python3 -m venv venv && venv/bin/pip install .`（不用 venv 时
`pip install --user .`），然后运行 `sme-bacnet-sim clone ...`。发布版的 PyInstaller 可执行文件只面向 x86-64 的
Windows / Linux / macOS，不覆盖 ARM 网关。

## 用法

```text
sme-bacnet-sim clone [--who-is LOW-HIGH | --address IP[:PORT] | --network N] [--devices ID,...]
                     [--ip IP/PREFIX] [--port 47808] [--client-device-id 4194300]
                     [--rate 5] [--timeout 3] [--retries 2] [--no-rpm]
                     [--object-list-file FILE.json] [--no-keep-ids] [--resume] -o OUT.yaml
```

| 选项 | 含义 |
|---|---|
| `--who-is LOW-HIGH` | 以该 instance 范围发 Who-Is（本地广播；只给一个数字即一台设备） |
| `--address IP[:PORT]` | 单播到该设备。与 `--devices` 同用时完全不发 Who-Is；不同用时先单播 Who-Is，再读取 `device,4194303`（通配 instance） |
| `--network N` | 远程网络：向 `N:*` 发 Who-Is；与 `--address` 同用时该地址是通往网络 N 的 BACnet 路由器 |
| `--devices ID,...` | 只克隆这些设备 instance（无 `--who-is` 时 Who-Is 范围取其最小..最大） |
| `--ip`, `--port` | 克隆客户端的本地地址和 UDP 端口（默认自动 / 47808） |
| `--client-device-id` | 克隆客户端自身的设备 instance（默认 4194300） |
| `--rate` | 每秒最大请求数（默认 5） |
| `--timeout`, `--retries` | 每个请求的 APDU 超时与重试次数；`--timeout` 也是 Who-Is 的等待时间 |
| `--no-rpm` | 不使用 ReadPropertyMultiple |
| `--object-list-file` | 读不出 object-list 的设备的对象表（见下文） |
| `--keep-ids` / `--no-keep-ids` | 保留设备 instance（默认）或从 1001 起重新编号 |
| `--resume` | 保留输出文件中已有的设备并跳过它们 |

`--who-is`、`--address`、`--devices` 至少要给一个：默认不会全网广播。

读取方式：

- 逐台读取，请求间隔由 `--rate` 控制。进度输出到 stderr。
- object-list 按元素读取（index 0 = 个数，然后 1..N），不支持分段的设备也能读；失败时整体读取；仍失败时使用 `--object-list-file`。
- 每个对象用 ReadPropertyMultiple 读取（对不支持分段的设备按其 max-apdu-length-accepted 发小请求）。RPM 第一次出错、
  被 reject 或 abort 后，该设备其余部分改用 ReadProperty。设备没有的属性会被跳过。
- 每读完一台设备就重写一次 YAML：Ctrl+C 中断后已读的设备都在文件里；用 `--resume` 继续。
- `<out>.log.jsonl` 记录每个请求、应答、错误和警告（每行一个 JSON）。

### 对象表文件

读不出 object-list 的设备，可以用 JSON 文件给出对象（兼容现场已有文件的格式；`properties` 等其他键会被忽略）：

```json
[{"deviceID": 1011, "objectList": [{"objectType": "analogInput", "objectInstance": 1},
                                   {"objectType": "binaryValue", "objectInstance": 3}]}]
```

`objectType` 可以是 bacpypes 的 camelCase 名称（`analogInput`），也可以是连字符形式的 BACnet 名称（`analog-input`）。

## 克隆的内容

输出只有 `devices:`；网络设置保持模拟器默认值，因此设备以原 instance 在内置路由器后面的虚拟网络上提供服务。

- **设备**：object-name、description、location、厂商名 / ID、型号名。max-apdu 和分段能力记入日志。
- **模拟器支持的所有对象类型**；其他类型（例如私有类型）跳过并给出警告。
- **值对象**（AI/AO/AV、BI/BO/BV、MSI/MSO/MSV）：名称、description、单位、COV 增量、present value 最小 / 最大值、
  active / inactive 文本、状态文本（只有 number-of-states 没有 state-text 时为 `State 1..N`）、commandable（是否有 priority array）。
  值：可命令对象取 relinquish default，否则取 present value。
- **报警**：notification-class、high / low limit、deadband、limit-enable、alarm value(s)、fault values、event-enable、notify-type、
  time-delay（-normal）。对应的 Notification Class 未被克隆时跳过并警告。
- **Notification Class**：priority、ack-required、按设备指定的接收方（按地址指定的接收方跳过）。
- **Schedule / Calendar**：周计划与例外计划、默认值、同一设备内的目标、写入优先级、有效期；日历日期。
- **Trend Log**：被记录对象（同一设备）、属性、间隔、缓冲大小、enable、logging type（`triggered` 改为 polled 并警告）。
- **Accumulator、Pulse Converter、Loop、Program、Event Enrollment**（out-of-range / change-of-state）、
  **Life Safety Point / Zone**：其可配置属性。
- **File**：类型、访问方式、read-only。**不**克隆内容（不使用 AtomicReadFile）。
- 指向其他设备的引用（Trend Log、Schedule 目标、Event Enrollment）会被丢弃并警告。

present value 是快照；克隆出的配置中没有 behavior。

## 与网关上已有 BACnet 客户端共存

网关上常常已经运行着 BACnet 客户端（例如以 host 网络占用 `<ip>:47808` 的 BAC0）。

- **端口**：47808 被占用时，克隆会给出明确错误并停止。请改用 `--port 47809`（或其他空闲端口），或先停掉占用 47808 的程序。
- **其他端口上的 I-Am**：很多设备把 I-Am 广播到 47808，因此在 47809 上的克隆可能收不到 Who-Is 的应答。用
  `--address <设备IP>`（单播）加 `--devices <instance>`，就完全不需要 Who-Is。不给 `--devices` 时，克隆会读取该地址的
  `device,4194303` 来获得 instance。
- **设备 instance**：克隆客户端本身也是一个 BACnet 设备，默认 instance 为 **4194300**。若与已有客户端的 instance 冲突，
  用 `--client-device-id` 换一个。

## 离线：EDE

网关上什么都不能运行时，从客户的 BACnet 工具导出 EDE 文件，使用 [EDE 导入](ede.md)。EDE 携带的属性较少（没有报警细节、计划和接收方）。
