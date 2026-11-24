# Foreign device 注册（跨子网）

需要让其他子网的客户端访问时，可把路由器端口作为 foreign device 注册到已有的 BBMD：
`network.foreign_device: {bbmd: "<ipv4>[:port]", ttl: <秒>}` 或 `--foreign-bbmd` / `--foreign-ttl`
（命令行优先；TTL 默认 300 秒，端口默认 47808）。注册使用 bacpypes3 的 foreign 链路层：每个 TTL 周期续订，
无应答时持续重试，停止或重新加载时注销（TTL 0）。结果（已注册 / NAK / 10 秒内无应答 / 过期）写入事件日志，
并在状态栏显示为 `FD → <bbmd> (…)`；快照 API 通过 `network.foreign_device` 提供。

Not supported：`foreign_device` 与 `mode: bbmd` 同时使用、BBMD 主机名（仅支持 IPv4 地址）、
读写 BBMD 的表（Read-Broadcast-Distribution-Table、Read-Foreign-Device-Table 等）。
