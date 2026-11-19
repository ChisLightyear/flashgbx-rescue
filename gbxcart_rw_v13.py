"""为 FlashGBX 5.2.1 恢复 GBxCart RW v1.3 连接。"""

from types import SimpleNamespace

from FlashGBX.app import HW_DEVICES
from FlashGBX.hw_GBxCartRW import GbxDevice as OfficialGBxCartRW


PLUGIN_NAME = "GBxCart RW v1.3"
PLUGIN_DESCRIPTION = "在 FlashGBX 5.2.1 中恢复 GBxCart RW v1.3 的使用，沿用官方设备后端。"
PLUGIN_VERSION = "0.1.0"


class GBxCartRWDevice(OfficialGBxCartRW):
    def FirmwareUpdateAvailable(self):
        pcb = self.FW["pcb_ver"]
        if pcb != 4:
            return super().FirmwareUpdateAvailable()

        # 恢复 5.1 对 v1.3 的固件要求，继续使用宿主的固件更新入口。
        self.FW_UPDATE_REQ = (
            self.FW["fw_ver"] == 0 or self.FW["fw_ts"] != self.DEVICE_LATEST_FW_TS[pcb]
        )
        return self.FW_UPDATE_REQ


def plugin_entry():
    for index, module in enumerate(HW_DEVICES):
        if module.GbxDevice is OfficialGBxCartRW:
            HW_DEVICES[index] = SimpleNamespace(GbxDevice=GBxCartRWDevice)
            break
