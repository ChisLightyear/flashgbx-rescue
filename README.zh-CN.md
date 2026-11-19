# FlashGBX Rescue

[English](README.md) · [简体中文](README.zh-CN.md)

## FlashGBX 烧录器兼容插件集

FlashGBX Rescue 收录社区维护的烧录器插件，让更多 GB/GBA 烧录器可以在官方 FlashGBX 上使用。

| 烧录器 | 插件状态 |
| --- | --- |
| **盖中盖** | 支持原生连接、基础读写和标准 AMD ROM 烧录 |
| **ChisFlash 碳酸钙** | 支持本名识别，沿用 FlashGBX 官方 Joey Jr 后端，当前配套固件为 RC39 |
| **GBxCart RW v1.3** | 恢复 L1 固件设备在 5.2.1 的连接。已通过模拟读写测试，实机烧录待验证 |

## 安装插件

本教程以 **Windows 版 FlashGBX 5.2.1** 为例。

1. 从[发布页](https://github.com/ChisLightyear/flashgbx-rescue/releases/latest)下载对应的插件文件。
   - 盖中盖、ChisFlash 碳酸钙用 `chisflash_native.py`。
   - GBxCart RW v1.3 用 `gbxcart_rw_v13.py`。
   - 两个文件可以放在同一个插件目录里。
2. 关闭 FlashGBX，把文件放进插件目录。

   | FlashGBX 版本 | 插件目录 |
   | --- | --- |
   | 官方免安装版 | 解压目录里的 `FlashGBX\config\plugins\` |
   | 官方安装版 | `%LOCALAPPDATA%\FlashGBX\plugins\` |

   安装版可以把路径粘贴到资源管理器地址栏。若没有 `plugins` 文件夹，手动新建即可。
3. 重新打开 FlashGBX。首次发现插件时会弹出确认窗口，选择加载，然后连接烧录器。

如果还下载了 `fc_*.txt` 卡带配置，把它放在 `plugins` 的上一级目录。FlashGBX 会从那里读取卡带配置。

欢迎在 Issues 分享实测结果。请注明烧录器型号、固件版本、卡带配置，以及完成的是识别、读取还是烧录。

## 鸣谢

感谢 Lesserkuma 和 FlashGBX 贡献者开发和维护 FlashGBX，并提供插件支持。 [FlashGBX 官方主线](https://github.com/Lesserkuma/FlashGBX)
