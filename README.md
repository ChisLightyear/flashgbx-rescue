# FlashGBX Rescue

[English](README.md) · [简体中文](README.zh-CN.md)

## FlashGBX device compatibility plugins

FlashGBX Rescue collects community-maintained plugins that let more GB/GBA cartridge readers and writers work with the official FlashGBX application.

| Device | Plugin status |
| --- | --- |
| **Gaizhonggai (盖中盖)** | Supports native connections, basic read and write operations, and ROM programming with standard AMD flash. |
| **ChisFlash Carbonate (碳酸钙)** | Identifies the device by its own name and uses the official FlashGBX Joey Jr backend. The current firmware for use with the plugin is RC39. |
| **GBxCart RW v1.3** | Restores connectivity in 5.2.1 for devices running L1 firmware. Simulated read and write tests passed. Flashing on real hardware is pending verification. |

## Install the plugins

These instructions apply to **FlashGBX 5.2.1 on Windows**.

1. Download the appropriate plugin from the [release page](https://github.com/ChisLightyear/flashgbx-rescue/releases/latest).
   - Use `chisflash_native.py` for Gaizhonggai or ChisFlash Carbonate.
   - Use `gbxcart_rw_v13.py` for GBxCart RW v1.3.
   - You can place both files in the same plugin directory.
2. Close FlashGBX and copy the files to its plugin directory.

   | FlashGBX edition | Plugin directory |
   | --- | --- |
   | Official portable edition | `FlashGBX\config\plugins\` inside the extracted folder |
   | Official installed edition | `%LOCALAPPDATA%\FlashGBX\plugins\` |

   For the installed edition, paste the path into the File Explorer address bar. If the `plugins` folder is missing, create it.
3. Restart FlashGBX, confirm that you want to load the plugin when prompted, then connect your device.

If you also downloaded an `fc_*.txt` cartridge profile, place it one level above `plugins`. FlashGBX loads cartridge profiles from that directory.

Please share hardware test results in Issues. Include the device model, firmware version, cartridge profile, and whether detection, reading, or programming succeeded.

## Acknowledgments

Thanks to Lesserkuma and the FlashGBX contributors for building and maintaining FlashGBX and adding plugin support. [Official FlashGBX repository](https://github.com/Lesserkuma/FlashGBX)
