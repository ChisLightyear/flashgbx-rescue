# FlashGBX Rescue

[简体中文](#简体中文) · [English](#english)

## 简体中文

### FlashGBX 烧录器兼容插件集

FlashGBX Rescue 收录社区维护的烧录器插件，让更多 GB/GBA 烧录器可以在官方 FlashGBX 上使用。将对应插件放进 FlashGBX 的插件目录，重启后启用即可。

| 烧录器 | 插件状态 |
| --- | --- |
| **盖中盖** | 支持原生连接、基础读写和标准 AMD ROM 烧录 |
| **ChisFlash 碳酸钙** | 支持本名识别，沿用 FlashGBX 官方 Joey Jr 后端，当前配套固件为 RC39 |
| **GBxCart RW v1.3** | 恢复 L1 固件设备在 5.2.1 的连接。已通过模拟读写测试，实机烧录待验证 |

### 安装插件

本教程以 **Windows 版 FlashGBX 5.2.1** 为例。

1. **从[发布页](https://github.com/ChisLightyear/flashgbx-rescue/releases/latest)下载对应的插件文件**
   - 盖中盖、ChisFlash 碳酸钙用 `chisflash_native.py`。
   - GBxCart RW v1.3 用 `gbxcart_rw_v13.py`。
   - 两个文件可以放在同一个插件目录里。
2. **关闭 FlashGBX，把文件放进插件目录**

   | FlashGBX 版本 | 插件目录 |
   | --- | --- |
   | 官方免安装版 | 解压目录里的 `FlashGBX\config\plugins\` |
   | 官方安装版 | `%LOCALAPPDATA%\FlashGBX\plugins\` |

   安装版可以把路径粘贴到资源管理器地址栏。若没有 `plugins` 文件夹，手动新建即可。
3. **重新打开 FlashGBX**。首次发现插件时会弹出确认窗口，选择加载，然后连接烧录器。

如果还下载了 `fc_*.txt` 卡带配置，把它放在 **`plugins` 的上一级目录**。FlashGBX 会从那里读取卡带配置。

欢迎在 Issues 分享实测结果。请注明烧录器型号、固件版本、卡带配置，以及完成的是识别、读取还是烧录。

### 鸣谢

感谢 Lesserkuma 和 FlashGBX 贡献者开发和维护 FlashGBX，并提供插件支持。 [FlashGBX 官方主线](https://github.com/Lesserkuma/FlashGBX)

## English

### FlashGBX device compatibility plugins

FlashGBX Rescue collects community-maintained plugins that bring more GB/GBA cartridge readers and writers to the official FlashGBX application. Place the appropriate plugin in the FlashGBX plugin directory, restart the application, and enable it.

| Device | Plugin status |
| --- | --- |
| **Gaizhonggai (盖中盖)** | Supports native connections, basic read and write operations, and ROM programming with standard AMD flash. |
| **ChisFlash Carbonate (碳酸钙)** | Identifies the device by its own name and uses the official FlashGBX Joey Jr backend. The current firmware for use with the plugin is RC39. |
| **GBxCart RW v1.3** | Restores connectivity in 5.2.1 for devices running L1 firmware. Simulated read and write tests passed. Flashing on real hardware is pending verification. |

### Install the plugins

These instructions apply to **FlashGBX 5.2.1 on Windows**.

1. **Download the appropriate plugin file from the [release page](https://github.com/ChisLightyear/flashgbx-rescue/releases/latest)**
   - Use `chisflash_native.py` for Gaizhonggai or ChisFlash Carbonate.
   - Use `gbxcart_rw_v13.py` for GBxCart RW v1.3.
   - You can place both files in the same plugin directory.
2. **Close FlashGBX and copy the files to its plugin directory**

   | FlashGBX edition | Plugin directory |
   | --- | --- |
   | Official portable edition | `FlashGBX\config\plugins\` inside the extracted folder |
   | Official installed edition | `%LOCALAPPDATA%\FlashGBX\plugins\` |

   For the installed edition, paste the path into the File Explorer address bar. If the `plugins` folder is missing, create it.
3. **Restart FlashGBX**. When FlashGBX first detects a plugin, confirm that you want to load it, then connect the device.

If you also downloaded an `fc_*.txt` cartridge profile, place it **one level above `plugins`**. FlashGBX loads cartridge profiles from that directory.

Please share hardware test results in Issues. Include the device model, firmware version, cartridge profile, and whether detection, reading, or programming succeeded.

### Acknowledgments

Thanks to Lesserkuma and the FlashGBX contributors for building and maintaining FlashGBX and adding plugin support. [Official FlashGBX repository](https://github.com/Lesserkuma/FlashGBX)
