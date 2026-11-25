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
| `--host 0.0.0.0 --http-port 8080` | Web UI 绑定地址（默认仅限 localhost） |
| `--browser` | 启动时在浏览器中打开 Web UI（默认不打开；默认为 `--no-browser`） |

## 连接 BACnet 客户端

客户端会在 `<ip>:47808` 看到路由器（`device 4194000`），并通过它路由访问地址形如 `100:1`、`100:2` 的模拟设备（网络 100，MAC 1、2……）。在 Yabe 中：*Add device → BACnet/IP over UDP*，然后执行 *Who-Is*。

> **同一台 PC 的注意事项：** 在 Windows 上，同一台机器上的客户端可能收不到广播回复（Who-Is/I-Am），单播则正常。请把客户端运行在另一台机器上，或让模拟器与客户端绑定不同的网卡，或设置 `network.mode: bbmd` 并将客户端注册为 foreign device。

> **客户端使用其他 UDP 端口：** Who-Is / I-Am 广播发往模拟器的端口（默认 47808）。绑定在其他端口（如 47809）的客户端
> 收不到 I-Am 广播，因此发现不了设备。请让两边使用同一端口，或设置 `network.mode: bbmd` 并把客户端作为 foreign device
> 注册到模拟器（`<模拟器 IP>:47808`），I-Am 应答会转发给客户端。

## 在 Web 界面设置网络

*编辑 → BACnet 网络…*（或点击状态栏的 BACnet/IP 地址）可以修改网卡（按名称和地址/前缀列出，或选*自动检测*）、UDP 端口、
IP 侧与虚拟网络号、路由器设备 ID 和运行模式（普通 / BBMD / foreign device：BBMD 地址与 TTL）。*应用* 时先校验设置
（是否为本机地址、UDP 端口是否空闲、网络号是否不同、设备 ID 是否唯一），然后无需重启即重新绑定 BACnet/IP，
并把 `network:` 部分写回配置文件（其他部分和未保存的修改保持不变；`network:` 内的注释会丢失）。
`--ip` / `--bacnet-port` 等命令行选项在下次启动时仍然优先。修改后客户端需要重新发现设备。
Not supported：关闭 Read-Property-Multiple 或分段（segmentation）支持（始终开启）。

## Docker

```bash
docker run --rm --network host -e TZ=Asia/Tokyo ghcr.io/smartedge-tech-dev/sme-bacnet-sim:<ver>
```

Who-Is / I-Am 广播需要 `--network host`（Linux）。不指定 `TZ` 时容器时钟为 UTC，排程和界面时钟也按 UTC 计算
（镜像已包含 tzdata）。
