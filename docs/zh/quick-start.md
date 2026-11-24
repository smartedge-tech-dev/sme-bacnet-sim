# 快速开始

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m sme_bacnet_sim --config configs/demo-building.yaml
```

打开 http://127.0.0.1:8080/ 。选项：

| 选项 | 含义 |
|---|---|
| `-c, --config FILE` | YAML/JSON 配置（默认为 `configs/demo-building.yaml`） |
| `--ip 192.168.1.10/24` | BACnet/IP 使用的网卡地址（默认：自动检测，/24） |
| `--bacnet-port 47808` | BACnet/IP UDP 端口 |
| `--foreign-bbmd 192.168.2.1[:47808]` | 作为 foreign device 注册到该 BBMD（优先于配置文件） |
| `--foreign-ttl 300` | foreign device 的 Time-to-Live（秒，优先于配置文件） |
| `--host 0.0.0.0 --port 8080` | Web UI 绑定地址（默认仅限 localhost） |

## 连接 BACnet 客户端

客户端会在 `<ip>:47808` 看到路由器（`device 4194000`），并通过它路由访问地址形如 `100:1`、`100:2` 的模拟设备（网络 100，MAC 1、2……）。在 Yabe 中：*Add device → BACnet/IP over UDP*，然后执行 *Who-Is*。

> **同一台 PC 的注意事项：** 在 Windows 上，同一台机器上的客户端可能收不到广播回复（Who-Is/I-Am），单播则正常。请把客户端运行在另一台机器上，或让模拟器与客户端绑定不同的网卡，或设置 `network.mode: bbmd` 并将客户端注册为 foreign device。
