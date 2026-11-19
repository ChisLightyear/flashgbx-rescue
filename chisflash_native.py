"""FlashGBX 5.2.1 的 ChisFlash 独立后端与盖中盖原生后端。"""
import copy
import configparser
import json
import math
import os
from pathlib import Path
import datetime
import re
import struct
import sys
import threading
import time
from types import SimpleNamespace
import zlib

import serial
import serial.tools.list_ports
from FlashGBX.app import AppContext, HW_DEVICES
from FlashGBX.hw_GBFlash import GbxDevice as _GBFlashBase
from FlashGBX.hw_JoeyJr import GbxDevice as _DeviceBase
from FlashGBX.LK_Device import LK_Device, ANSI, dprint
from FlashGBX import i18n
from FlashGBX.i18n import __
from FlashGBX.RomFileAGB import RomFileAGB
from FlashGBX.RomFileDMG import RomFileDMG

PLUGIN_NAME = "GBFlash and ChisFlash Carbonate / Beggar"
PLUGIN_VERSION = "0.3.4"
PLUGIN_DESCRIPTION = "Adds support for ChisFlash Carbonate and Beggar and a power-on delay for GBFlash."
IDENTITY_REQUEST = b'\x55\xaa'
CARBONATE_PRODUCTS = ('ChisFlash Carbonate', 'ChisFlash Carbonate Original')


def _localized_label(english, chinese):
    return chinese if i18n.CONFIGURED_LANGUAGE == 'zh_CN' else english

def _usb_products():
    """只读系统中的 USB 产品名称，不打开串口或向设备发送探测命令。"""
    ports = serial.tools.list_ports.comports()
    result = {p.device: (getattr(p, 'product', None) or '') for p in ports}
    if sys.platform != 'win32':
        return result
    import ctypes
    import uuid
    import winreg
    from ctypes import wintypes

    class PropertyKey(ctypes.Structure):
        _fields_ = [('guid', ctypes.c_ubyte * 16), ('pid', wintypes.DWORD)]

    # DEVPKEY_Device_BusReportedDeviceDesc：Windows 缓存的设备产品描述。
    key = PropertyKey((ctypes.c_ubyte * 16).from_buffer_copy(
        uuid.UUID('540b947e-8b40-45bc-a8a2-6a0b894cbda2').bytes_le), 4)
    cfg = ctypes.WinDLL('cfgmgr32')
    locate = cfg.CM_Locate_DevNodeW
    locate.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.ULONG]
    locate.restype = wintypes.ULONG
    get_property = cfg.CM_Get_DevNode_PropertyW
    get_property.argtypes = [wintypes.DWORD, ctypes.POINTER(PropertyKey), ctypes.POINTER(wintypes.ULONG),
                            ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG), wintypes.ULONG]
    get_property.restype = wintypes.ULONG
    parent = cfg.CM_Get_Parent
    parent.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.ULONG]
    parent.restype = wintypes.ULONG
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Enum\USB') as usb:
            for index in range(winreg.QueryInfoKey(usb)[0]):
                name = winreg.EnumKey(usb, index)
                if not name.upper().startswith('VID_0483&PID_0721'):
                    continue
                with winreg.OpenKey(usb, name) as device:
                    for item in range(winreg.QueryInfoKey(device)[0]):
                        instance = winreg.EnumKey(device, item)
                        try:
                            with winreg.OpenKey(device, instance + r'\Device Parameters') as params:
                                port = winreg.QueryValueEx(params, 'PortName')[0]
                            if port not in result:
                                continue
                            node = wintypes.DWORD()
                            if locate(ctypes.byref(node), 'USB\\' + name + '\\' + instance, 0):
                                continue
                            for _ in range(3):
                                text = ctypes.create_unicode_buffer(256)
                                size, kind = wintypes.ULONG(ctypes.sizeof(text)), wintypes.ULONG()
                                if get_property(node.value, ctypes.byref(key), ctypes.byref(kind), text,
                                                ctypes.byref(size), 0) == 0 and kind.value == 0x12:
                                    result[port] = text.value
                                    break
                                next_node = wintypes.DWORD()
                                if parent(ctypes.byref(next_node), node.value, 0):
                                    break
                                node = next_node
                        except OSError:
                            continue
    except OSError:
        pass
    return result


def _prepare_serial(raw):
    raw.rts = True
    raw.dtr = True
    raw.rts = False
    raw.dtr = False
    time.sleep(0.01)
    raw.reset_input_buffer()
    raw.reset_output_buffer()


def _identify_chisflash(raw):
    """仅对产品名称已确认的碳酸钙查询身份，使用以换行结束的短响应。"""
    packet = IDENTITY_REQUEST
    if raw.write(packet) != len(packet):
        raise IOError('设备身份请求未完整发送')
    raw.flush()
    reply = bytearray()
    deadline = time.monotonic() + 1
    while len(reply) < 96 and time.monotonic() < deadline:
        part = raw.read(1)
        if part:
            reply.extend(part)
            if part == b'\n':
                break
    if not reply.endswith(b'\n'):
        raise IOError('碳酸钙身份响应不完整')
    if not reply.startswith(b'\x01ChisFlash'):
        return None
    match = re.fullmatch(rb'\x01ChisFlash( Original)? FW C([0-9]+) (RC[^\r\n ]+)\r\n', bytes(reply))
    if match is None:
        raise IOError('设备身份响应不完整或无法识别')
    return {'board': 'original' if match[1] else 'modified',
            'protocol': int(match[2]), 'version': match[3].decode('ascii')}


def _power_on_delay_seconds():
    """两个可控供电后端共用设置；缺省为本轮实测通过的额外 500 ms。"""
    settings = configparser.ConfigParser(interpolation=None)
    try:
        settings.read(Path(AppContext.CONFIG_PATH) / 'settings.ini', encoding='utf-8-sig')
        milliseconds = settings.getfloat('General', 'ChisFlashPowerOnDelayMs', fallback=500)
        if not math.isfinite(milliseconds) or not 0 <= milliseconds <= 10000:
            return 0.5
        return milliseconds / 1000
    except (OSError, ValueError, configparser.Error, TypeError):
        return 0.5


class _PowerOnDelayMixin:
    """仅在真正发送上电命令后等待，不改变卡带事务或增加读回。"""
    def CartPowerOn(self):
        previous = getattr(self, '_power_on_delay_context', False)
        self._power_on_delay_context = True
        try:
            return super().CartPowerOn()
        finally:
            self._power_on_delay_context = previous

    def _write(self, data, wait=False):
        if not getattr(self, '_power_on_delay_context', False):
            return super()._write(data, wait=wait)
        command = bytes([data]) if isinstance(data, int) else bytes(data)
        if command != bytes([self.DEVICE_CMD['CART_PWR_ON']]):
            return super()._write(data, wait=wait)
        result = super()._write(data, wait=wait)
        if result is not False:
            time.sleep(_power_on_delay_seconds())
        return result


class GBFlashDevice(_PowerOnDelayMixin, _GBFlashBase):
    """保留官方 GBFlash 识别与读写，仅追加上电等待。"""
    pass


class CarbonateDevice(_PowerOnDelayMixin, _DeviceBase):
    """沿用官方 JR 后端，仅适配碳酸钙本名身份与硬件能力。"""
    DEVICE_NAME = 'ChisFlash Carbonate'
    DEVICE_NAME_ZH = 'ChisFlash（碳酸钙）'
    DEVICE_LABEL_LONG = DEVICE_NAME
    DEVICE_LABEL_SHORT = 'Carbonate'
    USB_IDS = ((0x0483, 0x0721),)
    PCB_VERSIONS = {2: ''}
    MAX_BUFFER_READ = 0x2000
    MAX_BUFFER_WRITE = 0x800
    FWUPDATE_ACTION = None
    CLI_UPDATER_METHOD = None
    @staticmethod
    def DEVICE_SUPPORT_MESSAGE():
        return _localized_label(
            'Use the firmware updater for your board revision.',
            '固件升级请使用对应板型的刷写工具。')

    def __init__(self):
        self.DEVICE, self.FW, self.IDENTITY = None, {}, None
        self.PORT, self.MODE = '', None
        self.FW_VAR, self.SUPPORTED_CARTS = {}, {}
        self.INFO = {'action': None, 'last_action': None, 'dump_info': {}}
        self.ERROR_ARGS, self.CANCEL_ARGS = {}, {}
        self.ERROR = self.CANCEL = False
        self.LAST_CHECK_ACTIVE = 0

    def GetCandidatePorts(self, comports=None):
        products = _usb_products()
        return [port for port in super().GetCandidatePorts(comports) if products.get(port) in CARBONATE_PRODUCTS]

    def TryConnect(self, port, baudrate, keep_open=False):
        if _usb_products().get(port) not in CARBONATE_PRODUCTS:
            return False
        return super().TryConnect(port, baudrate, keep_open=keep_open)

    def Initialize(self, flashcarts, port=None, max_baud=2000000):
        if self.DEVICE is not None: self.DEVICE.close()
        self.DEVICE = None
        self.FW = None
        conn_msg = []
        ports = []
        if port is not None:
            ports = [ port ]
        else:
            ports = self.GetCandidatePorts()
            if len(ports) == 0: return False

        for i in range(0, len(ports)):
            if self.TryConnect(ports[i], max_baud, keep_open=True):
                self.BAUDRATE = max_baud
                dev = self.DEVICE
            else:
                continue

            if self.FW is None or self.FW == {}: continue

            dprint(f"Found a {self.DEVICE_NAME}")
            dprint("Firmware information:", self.FW)

            if self.DEVICE is None or not self.IsConnected():
                dev.close()
                self.DEVICE = None
                if self.FW is not None:
                    conn_msg.append([0, __("Couldn’t communicate with the {device_name} on port {port}. Please disconnect and reconnect the device, then try again.", device_name=self.DEVICE_NAME, port=ports[i])])
                continue
            elif self.FW is None:
                dev.close()
                self.DEVICE = None
                continue
            elif self.FW["cfw_id"] == "G":  # 沿用 JR 对其他固件家族的分支。
                dprint("Device runs the JoeyGUI firmware")
            elif self.FW["pcb_ver"] not in self.PCB_VERSIONS.keys() or "cfw_id" not in self.FW or self.FW["cfw_id"] != 'C' or self.FW["fw_ver"] < self.DEVICE_MIN_FW:  # 只将 JR 的 L 家族识别改为碳酸钙 C 家族。
                dprint("Incompatible firmware:", self.FW)
                dev.close()
                self.DEVICE = None
                continue
            elif self.FW["fw_ts"] > self.DEVICE_LATEST_FW_TS:
                conn_msg.append([1, __("Note: The {device_name} on port {port} is running a firmware version that is newer than what this version of FlashGBX was developed to work with, so errors may occur.", device_name=self.DEVICE_NAME, port=ports[i])])

            if (self.FW["pcb_ver"] & 0x7F) == 1:
                conn_msg.append([2, __("Warning: Your {device_name} does not support the software-controlled voltage setting feature, so please be extra careful and always set the switch to the correct voltage before inserting a cartridge.", device_name=self.DEVICE_NAME)])

            self.PORT = ports[i]
            self.DEVICE.timeout = self.DEVICE_TIMEOUT

            # 沿用 JR 的卡带配置加载。
            self.UpdateFlashCarts(flashcarts)

            # 找到第一个设备后结束扫描。
            break

        return conn_msg

    def CheckActive(self):
        if self.LAST_CHECK_ACTIVE and time.monotonic() < self.LAST_CHECK_ACTIVE + 1: return True
        dprint("Checking if device is active")
        if self.DEVICE is None: return False
        if self.FW["pcb_name"] is None:
            if self.LoadFirmwareVersion():
                self.LAST_CHECK_ACTIVE = time.monotonic()
                return True
            else:
                return False
        try:
            if self.FW.get("cfw_id") == "C" and self.FW.get("fw_ver", 0) >= 15:
                challenge = os.urandom(1)[0]
                self._write(bytearray([self.DEVICE_CMD["PING"], challenge]))
                response = self._read(1)
                if response is False or response != ((~challenge) & 0xFF):
                    raise ConnectionError("Invalid firmware response (ping response was {response} instead of {expected})".format(response=str(response), expected=str((~challenge) & 0xFF)))
            else:
                modes = self.GetSupportedModes()
                mode = self._get_fw_variable("CART_MODE")
                if mode > len(modes):
                    raise ConnectionError("Invalid firmware response (mode={mode})".format(mode=str(mode - 1)))
            self.LAST_CHECK_ACTIVE = time.monotonic()
            return True
        except Exception as e:
            if self.USER_ANSWER is not True:  # 沿用 CartPowerCycleOrAskReconnect() 的处理。
                print(ANSI.RED + __("Disconnecting from the device, because a critical error occurred!\n{error}", error=str(e)) + ANSI.RESET)
                dprint(__("Disconnecting from the device, because a critical error occurred!\n{error}", error=str(e)))
            try:
                if self.DEVICE.isOpen():
                    self.DEVICE.reset_input_buffer()
                    self.DEVICE.reset_output_buffer()
                    self.DEVICE.close()
                self.DEVICE = None
            except:
                pass
            return False

    def _exact_info(self, count):
        data = bytearray()
        deadline = time.monotonic() + self.DEVICE_TIMEOUT
        while len(data) < count and time.monotonic() < deadline:
            data.extend(self.DEVICE.read(count - len(data)))
        if len(data) != count:
            raise IOError('碳酸钙固件信息响应不完整')
        return bytes(data)

    def LoadFirmwareVersion(self):
        try:
            if self.DEVICE is None:
                return False
            self.DEVICE.timeout = 0.075
            self.DEVICE.reset_input_buffer()
            self.DEVICE.reset_output_buffer()
            self.IDENTITY = _identify_chisflash(self.DEVICE)
            if self.IDENTITY is None:
                return False
            self.DEVICE.timeout = self.DEVICE_TIMEOUT
            self._write(self.DEVICE_CMD['QUERY_FW_INFO'])
            if self._exact_info(1) != b'\x08':
                return False
            family, protocol, pcb, timestamp = struct.unpack('>cHBI', self._exact_info(8))
            if family != b'C' or protocol != self.IDENTITY['protocol']:
                return False
            length = self._exact_info(1)[0]
            name = self._exact_info(length).decode('ascii')
            expected_name = 'ChisFlash Original' if self.IDENTITY['board'] == 'original' else 'ChisFlash'
            if name != expected_name:
                return False
            power, boot = self._exact_info(2)
            self.FW = {'cfw_id': 'C', 'fw_ver': protocol, 'pcb_ver': pcb,
                       'fw_ts': timestamp, 'fw_dt': datetime.datetime.fromtimestamp(timestamp).astimezone().isoformat(),
                       'pcb_name': name, 'ofw_ver': None, 'device_serial': None,
                       'cart_power_ctrl': bool(power & 1), 'cart_presence_switch': bool(power & 2),
                       'cart_mode_switch': bool(power & 4), 'bootloader_reset': bool(boot & 1)}
            return True
        except Exception as e:
            dprint("Disconnecting due to an error", e, sep="\n")
            try:
                if self.DEVICE.isOpen():
                    self.DEVICE.reset_input_buffer()
                    self.DEVICE.reset_output_buffer()
                    self.DEVICE.close()
                self.DEVICE = None
            except:
                pass
            return False

    def Close(self, cartPowerOff=False):
        if self.DEVICE is None:
            return
        return super().Close(cartPowerOff=cartPowerOff)

    def DetectFlash(self, limitVoltage=False):
        """用既有扩展 ID 命中和 CFI 结果区分 02G，不追加设备事务。"""
        result = super().DetectFlash(limitVoltage=limitVoltage)
        if self.MODE != 'AGB':
            return result
        matched, selected, id_text, cfi_text, cfi, detected_size = result
        carts = list(self.SUPPORTED_CARTS['AGB'].values())
        s70 = [index for index in matched
               if carts[index].get('flash_size') == 0x10000000
               and carts[index].get('flash_bank_select_type') == 1
               and carts[index].get('flash_id_offsets') == [28, 29, 30, 31]
               and carts[index].get('flash_ids') == [[0x48, 0x22, 0x01, 0x22]]]
        if len(s70) == 1 and cfi and cfi.get('device_size') == 0x10000000:
            return (matched, s70[0], id_text, cfi_text, cfi, 0x10000000)
        return result

    def GetFirmwareVersion(self, more=False):
        unknown = _localized_label('Unknown', '未知')
        version = self.IDENTITY['version'] if self.IDENTITY else unknown
        if not more:
            return version
        protocol = self.FW.get('fw_ver', unknown)
        return _localized_label(f'{version} (protocol {protocol})', f'{version}（协议 {protocol}）')

    def GetName(self):
        return _localized_label(self.DEVICE_NAME, self.DEVICE_NAME_ZH)

    def GetFullName(self): return self.GetName()

    def GetFullNameLabel(self):
        firmware = _localized_label('Firmware', '固件')
        return f'{self.GetFullName()} – {firmware} {self.GetFirmwareVersion()}'

    def GetFullNameExtended(self, more=False):
        return f'{self.GetFullName()} · {self.GetFirmwareVersion(more)} · {self.PORT}'
    def GetSupportedModes(self): return ['DMG', 'AGB']
    def CanSetVoltageBySwitch(self): return False
    def CanSetVoltageByCode(self): return self.FW.get('pcb_ver') == 2
    def CanSetVoltageByAutoswitch(self): return False
    def CanPowerCycleCart(self): return self.FW.get('cart_power_ctrl', False)
    def IsSupported3dMemory(self): return True
    def IsClkConnected(self): return True
    def SupportsAudioAsWe(self): return True
    def ChangeBaudRate(self, value): pass
    def ResetLEDs(self): pass
    def SupportsFirmwareUpdates(self): return False
    def FirmwareUpdateAvailable(self): return False
    def GetFirmwareUpdaterClass(self): return None
    def SupportsBootloaderReset(self): return False
    def BootloaderReset(self): return False


class NativeProtocolError(IOError):
    pass


class UnsupportedNativeFeature(NotImplementedError):
    pass


class NativeLink:
    """单个请求完整接收响应后才发送下一帧；不把占位响应头当作 CRC 校验。"""
    def __init__(self, port, cancelled=lambda: False):
        self.port = port
        self.cancelled = cancelled
        self.lock = threading.RLock()
        self.history = []

    @staticmethod
    def frame(command, body=b''):
        packet = struct.pack('<H', len(body) + 5) + bytes([command]) + bytes(body)
        # 原客户端保留两个零字节，未启用请求 CRC16。
        return packet + b'\x00\x00'

    @staticmethod
    def chunk_size(left, overhead, unit=1):
        size = min(left, 4096)
        size -= size % unit
        return size

    def exact(self, count, timeout):
        result = bytearray()
        deadline = time.monotonic() + timeout
        while len(result) < count:
            if self.cancelled():
                raise NativeProtocolError('操作已取消')
            part = self.port.read(count - len(result))
            if part:
                result.extend(part)
            elif time.monotonic() >= deadline:
                raise NativeProtocolError(f'盖中盖响应超时：需要 {count} 字节，收到 {len(result)} 字节')
        return bytes(result)

    def request(self, command, body=b'', read_length=None, ack=False, timeout=5):
        with self.lock:
            if self.cancelled():
                raise NativeProtocolError('操作已取消')
            packet = self.frame(command, body)
            self.history.append((command, len(packet)))
            written = self.port.write(packet)
            if written != len(packet):
                raise NativeProtocolError('盖中盖请求未完整发送')
            self.port.flush()
            if ack:
                response = self.exact(1, timeout)
                # 原版单字节 ACK 接收后丢弃残留输入；数据响应不做此处理。
                self.port.reset_input_buffer()
                if response != b'\xaa':
                    raise NativeProtocolError(f'盖中盖 ACK 错误：{response.hex()}')
                return b''
            if read_length is not None:
                response = self.exact(read_length + 2, timeout)
                self.last_response_header = response[:2]
                return response[2:]
            return b''

    def read(self, mode, address, length):
        result = bytearray()
        while len(result) < length:
            size = min(4096, length - len(result))
            base = address + len(result)
            if mode == 'AGB':
                aligned = base & ~1
                count = (size + (base & 1) + 1) & ~1
                raw = self.request(0xf6, struct.pack('<IH', aligned, count), read_length=count)
                result.extend(raw[base & 1:(base & 1) + size])
            else:
                command = 0xf8 if mode == 'SRAM' else 0xfb
                result.extend(self.request(command, struct.pack('<IH', base, size), read_length=size))
        return bytes(result)

    def write(self, mode, address, data, buffer_size=None):
        data = bytes(data)
        unit = 2 if mode == 'AGB' else 1
        if mode == 'AGB' and len(data) & 1:
            data += b'\x00'  # 沿用原版奇数字节补一个 00。
        offset = 0
        while offset < len(data):
            overhead = 11 if buffer_size is not None else 9
            size = self.chunk_size(len(data) - offset, overhead, unit)
            # 原生 F5 使用字地址，F4/F6 使用字节地址，不能共用同一换算。
            wire_address = (address + offset) // 2 if mode == 'AGB' and buffer_size is None else address + offset
            body = struct.pack('<I', wire_address)
            if buffer_size is not None:
                body += struct.pack('<H', buffer_size)
                command = 0xf4 if mode == 'AGB' else 0xfc
            else:
                command = 0xf5 if mode == 'AGB' else 0xf7 if mode == 'SRAM' else 0xfa
            self.request(command, body + data[offset:offset + size], ack=True, timeout=30)
            offset += size


class GbxDevice(_DeviceBase):
    DEVICE_NAME = 'ChisFlash Beggar (Native)'
    DEVICE_NAME_ZH = 'ChisFlash（盖中盖原生）'
    DEVICE_LABEL_LONG = DEVICE_NAME
    DEVICE_LABEL_SHORT = 'Beggar (Native)'
    USB_IDS = ((0x0483, 0x0721),)
    MAX_BUFFER_READ = 4096
    MAX_BUFFER_WRITE = 4096
    FWUPDATE_ACTION = None
    CLI_UPDATER_METHOD = None
    @staticmethod
    def DEVICE_SUPPORT_MESSAGE():
        return _localized_label(
            'Experimental Beggar plugin with standard AMD ROM programming, standard SRAM access, and cartridge detection.',
            '实验版盖中盖插件，支持标准 AMD ROM 烧录、普通 SRAM 读写和卡带识别。')

    def __init__(self):
        self.DEVICE = None
        self.PORT = ''
        # ???????? FlashGBX ?????????
        self.MODE = None
        self.FW = {'pcb_ver': 2, 'pcb_name': self.DEVICE_NAME, 'cfw_id': 'N', 'fw_ver': 15,
                   'fw_ts': 0, 'fw_dt': '原生协议不提供固件版本查询', 'cart_power_ctrl': False,
                   'bootloader_reset': False, 'cart_presence_switch': False, 'cart_mode_switch': False}
        # fw_ver 仅供复用上位机逻辑判断接口级别，不代表设备中安装了 LK 固件。
        self.FW_VAR = {name: 0 for name in self.DEVICE_VAR}
        self.FW_VAR.update(STATUS_REGISTER_MASK=0x80, STATUS_REGISTER_VALUE=0x80)
        self.INFO = {'action': None, 'last_action': None, 'dump_info': {}}
        self.ERROR_ARGS, self.CANCEL_ARGS = {}, {}
        self.ERROR = self.CANCEL = False
        self.SUPPORTED_CARTS = {}
        self._commands = [(0, 0)] * 6
        self._input, self._reply = bytearray(), bytearray()
        self._payload = None
        self._busy = False
        self._lock = threading.RLock()
        self._native = None
        self.LAST_CHECK_ACTIVE = 0

    def GetCandidatePorts(self, serial_ports=None):
        ports = serial.tools.list_ports.comports() if serial_ports is None else serial_ports
        products = _usb_products()
        return [p.device for p in ports if (p.vid, p.pid) in self.USB_IDS and products.get(p.device) not in CARBONATE_PRODUCTS]

    def Initialize(self, flashcarts, port=None, max_baud=2000000):
        for candidate in ([port] if port else self.GetCandidatePorts()):
            if _usb_products().get(candidate) in CARBONATE_PRODUCTS:
                continue
            raw = None
            try:
                raw = serial.Serial(candidate, baudrate=9600, timeout=0.05, write_timeout=5)
                _prepare_serial(raw)
                self.DEVICE, self.PORT = raw, candidate
                self._native = NativeLink(raw, lambda: self.CANCEL)
                self.MODE = None
                self.FW_VAR.update(CART_MODE=0, ADDRESS=0)
                self.UpdateFlashCarts(flashcarts)
                return []
            except (OSError, serial.SerialException, NativeProtocolError) as error:
                if raw is not None:
                    raw.close()
                self.DEVICE = None
                self._native = None
                self.ERROR_ARGS['connection'] = str(error)
        return False

    def IsConnected(self):
        return self.DEVICE is not None and self.DEVICE.is_open

    def CheckActive(self):
        return self.IsConnected()

    def Close(self, cartPowerOff=False):
        if self.IsConnected():
            self.DEVICE.close()
        self.DEVICE = None

    def SetMode(self, mode, delay=0.1):
        if mode not in ('AGB', 'DMG'):
            raise ValueError('不支持的卡带模式')
        self.MODE = mode
        self.FW_VAR.update(CART_MODE=2 if mode == 'AGB' else 1, ADDRESS=0)

    def GetMode(self):
        return self.MODE

    def CartPowerOn(self):
        raise UnsupportedNativeFeature('盖中盖原生协议不支持供电切换')

    def CartPowerOff(self):
        raise UnsupportedNativeFeature('盖中盖原生协议不支持供电切换')

    def CartPowerCycle(self):
        raise UnsupportedNativeFeature('盖中盖原生协议不支持供电切换')

    def SetAutoPowerOff(self, value):
        self.SKIP_POWERCYCLE = True

    def _thread_worker_auto_poweroff_start(self):
        self._busy = True

    def _thread_worker_auto_poweroff_finish(self):
        self._busy = False

    def _set_fw_variable(self, key, value, log=True):
        if key not in self.DEVICE_VAR:
            raise KeyError(key)
        bits = self.DEVICE_VAR[key][0]
        self.FW_VAR[key] = int(value) & ((1 << bits) - 1)
        return 1

    def _get_fw_variable(self, key):
        return self.FW_VAR.get(key, 0)

    def ReadROM(self, address, length, skip_init=False, max_length=4096):
        with self._lock:
            if skip_init:
                address = self.FW_VAR['ADDRESS'] * (2 if self.MODE == 'AGB' else 1)
            raw = self._native.read(self.MODE, address, length)
            self.FW_VAR['ADDRESS'] = (address + length) // 2 if self.MODE == 'AGB' else address + length
            if self.INFO.get('action') in (1, 2, 4) and not self.NO_PROG_UPDATE:
                self.SetProgress({'action': 'READ', 'bytes_added': len(raw)})
            return bytearray(raw)

    def ReadHeader(self, checkRtc=True):
        # 普通原生读头不调用 LK 的供电、启动脉冲或 RTC 专用固件命令。
        self.SIGNAL = None
        header = self.ReadROMHeader()
        parser = RomFileAGB if self.MODE == 'AGB' else RomFileDMG
        data = parser.GetParser(header).GetHeader()
        if not data:
            return False
        if self.MODE == 'AGB':
            # 沿用头解析信息和界面容量选择，不为初始化追加容量读取探针。
            data.setdefault('rom_size', 0x2000000)
        data.update(raw=header, has_rtc=False, rtc_dict={}, rtc_string='首版插件未读取 RTC',
                    no_rtc_reason='盖中盖 RTC 适配尚未实现')
        self.INFO.update(data)
        self.INFO.setdefault('dump_info', {})['header'] = data
        self.INFO['flash_type'] = data.get('flash_type', 0)
        self.INFO['last_action'] = 0
        return data

    def ReadRAM(self, address, length, command=None, max_length=4096):
        if command not in (None, self.DEVICE_CMD['AGB_CART_READ_SRAM'], self.DEVICE_CMD['DMG_CART_READ']):
            raise UnsupportedNativeFeature('该存档读取协议尚未适配盖中盖插件')
        with self._lock:
            target = address if self.MODE == 'AGB' else 0xa000 + address
            raw = self._native.read('SRAM' if self.MODE == 'AGB' else 'DMG', target, length)
            self.FW_VAR['ADDRESS'] = target + length
            if not self.NO_PROG_UPDATE:
                self.SetProgress({'action': 'READ', 'bytes_added': len(raw)})
            return bytearray(raw)

    def WriteRAM(self, address, buffer, command=None, max_length=256):
        if command not in (None, self.DEVICE_CMD['AGB_CART_WRITE_SRAM'], self.DEVICE_CMD['DMG_CART_WRITE_SRAM']):
            raise UnsupportedNativeFeature('首版插件仅支持普通 SRAM/FRAM 字节接口，不支持 EEPROM/Flash 存档编程')
        with self._lock:
            target = address if self.MODE == 'AGB' else 0xa000 + address
            self._native.write('SRAM' if self.MODE == 'AGB' else 'DMG', target, buffer)
            self.FW_VAR['ADDRESS'] = target + len(buffer)
            if self.INFO.get('action') == 3 and not self.NO_PROG_UPDATE:
                self.SetProgress({'action': 'WRITE', 'bytes_added': len(buffer)})
            return True

    def _cart_write(self, address, value, flashcart=False, sram=False):
        with self._lock:
            if self.MODE == 'AGB' and not sram:
                # 配置的命令地址以字节计；与主线相同，输出时忽略字地址的 A0。
                self._native.write('AGB', address & ~1, struct.pack('<H', value & 65535))
            else:
                self._native.write('SRAM' if self.MODE == 'AGB' else 'DMG', address, bytes([value & 255]))
            return True

    def _cart_write_flash(self, commands, flashcart=False):
        for address, value in commands:
            self._cart_write(address, value, flashcart=flashcart, sram=self.MODE == 'AGB' and not flashcart)
        return True

    def CompareCRC32(self, buffer, offset, length, address, flashcart=None, max_length=0x20000, reset=False, mbc=None, bank=0):
        expected = zlib.crc32(buffer[offset:offset + length])
        actual = 0
        done = 0
        while done < length:
            size = min(4096, length - done)
            actual = zlib.crc32(self.ReadROM(address + done, size), actual)
            done += size
        return True if expected == actual else (expected, actual)

    def WriteROM(self, address, buffer, flash_buffer_size=False, skip_init=False, rumble_stop=False, max_length=4096):
        if self.FW_VAR['FLASH_COMMAND_SET'] != 1 or self.FW_VAR['FLASH_METHOD'] not in (1, 2):
            raise UnsupportedNativeFeature('首版盖中盖插件尚未实现 Intel 或特殊卡带编程算法')
        if self.FW_VAR.get('FLASH_WE_PIN', 1) not in (0, 1):
            raise UnsupportedNativeFeature('盖中盖基础命令不提供 AUDIO/RESET 写脚控制')
        if self.MODE == 'DMG' and (self.FW_VAR.get('FLASH_COMMANDS_BANK_1') or self.FW_VAR.get('FLASH_PULSE_RESET')):
            raise UnsupportedNativeFeature('首版插件尚未实现编程命令期间的特殊换 Bank/复位时序')
        unit = 2 if self.MODE == 'AGB' else 1
        data = bytes(buffer)
        if self.MODE == 'AGB' and len(data) & 1:
            data += b'\x00'
        page = int(flash_buffer_size or 0)
        prefixes = [(a * unit, v) for a, v in self._commands[:3]]
        normal = (prefixes[:2] == [(0xaaa, 0xaa), (0x554 if unit == 2 else 0x555, 0x55)]
                  and prefixes[2][1] == (0x25 if page else 0xa0)
                  and (bool(page) or prefixes[2][0] == 0xaaa)
                  and (not page or self._commands[5][1] == 0x29)
                  and not self.FW_VAR.get('FLASH_DOUBLE_DIE'))
        if not normal:
            raise UnsupportedNativeFeature('原版盖中盖编程入口不提供该命令表，不改用自写编程流程')
        with self._lock:
            done = 0
            while done < len(data):
                if self.CANCEL:
                    raise NativeProtocolError('操作已取消')
                size = min(4096, len(data) - done)
                part = data[done:done + size]
                # F4/FC 在原版固件内执行编程及完成轮询，上位机只接收 ACK。
                self._native.write(self.MODE, address + done, part, buffer_size=page)
                done += len(part)
                self.FW_VAR['ADDRESS'] = (address + done) // unit
                self.SetProgress({'action': 'WRITE', 'bytes_added': len(part), 'skipping': False})
            self.SKIPPING = False
            return None

    def _write(self, data, wait=False):
        # 这里只解析上位机共享 worker 的控制状态；实际 USB 线上不发送 LK 命令。
        self._input.extend(bytes([data]) if isinstance(data, int) else bytes(data))
        while self._input:
            command = self._input[0]
            length = 40 if command == 0xa7 else (2 + self._input[1] * 5 if command == 0xb8 and len(self._input) >= 2 else 2 if command == 0xb8 else 1)
            if len(self._input) < length:
                break
            packet = bytes(self._input[:length])
            del self._input[:length]
            if command == 0xa7:
                self.FW_VAR.update(FLASH_COMMAND_SET=packet[1], FLASH_METHOD=packet[2], FLASH_WE_PIN=packet[3])
                self._commands = [struct.unpack_from('>IH', packet, 4 + i * 6) for i in range(6)]
            elif command == 0xb8:
                pass  # 标准 AMD 路径由上位机 mapper 自行换 Bank。
            elif command == self.DEVICE_CMD['SET_MODE_AGB']:
                self.MODE = 'AGB'
                self.FW_VAR['CART_MODE'] = 2
            elif command == self.DEVICE_CMD['SET_MODE_DMG']:
                self.MODE = 'DMG'
                self.FW_VAR['CART_MODE'] = 1
            elif command in (self.DEVICE_CMD['SET_VOLTAGE_3_3V'], self.DEVICE_CMD['SET_VOLTAGE_5V']):
                if command == self.DEVICE_CMD['SET_VOLTAGE_5V']:
                    raise UnsupportedNativeFeature('当前设备不由插件切换电压，首版不支持要求切到 5V 的烧录流程')
                # 主线对固定电压设备也发送 3.3V 选择；不伪造实际电源切换。
            elif command == self.DEVICE_CMD['CART_PWR_ON']:
                self.CartPowerOn()
            elif command == self.DEVICE_CMD['CART_PWR_OFF']:
                self.CartPowerOff()
            elif command not in (self.DEVICE_CMD['ENABLE_PULLUPS'], self.DEVICE_CMD['DISABLE_PULLUPS'],
                                 self.DEVICE_CMD['SET_ADDR_AS_INPUTS'], self.DEVICE_CMD['DMG_MBC_RESET'], self.DEVICE_CMD['NULL']):
                raise UnsupportedNativeFeature(f'该功能尚未适配盖中盖插件：0x{command:02X}')
            self._reply.append(1)
        return self._read(1) if wait else None

    def _read(self, count):
        if len(self._reply) < count:
            return False
        raw = self._reply[:count]
        del self._reply[:count]
        return raw[0] if count == 1 else bytearray(raw)

    def _try_write(self, data, retries=5):
        return self._write(data, wait=True)

    def LoadFirmwareVersion(self): return self.IsConnected()
    def GetFirmwareVersion(self, more=False):
        return _localized_label('Plugin', '插件') + ' ' + PLUGIN_VERSION

    def GetName(self):
        return _localized_label(self.DEVICE_NAME, self.DEVICE_NAME_ZH)

    def GetFullName(self): return self.GetName()

    def GetFullNameLabel(self):
        return f'{self.GetFullName()} – {self.GetFirmwareVersion()}'

    def GetFullNameExtended(self, more=False):
        return f'{self.GetFullName()} · {self.PORT} · {self.GetFirmwareVersion()}'
    def GetSupportedModes(self): return ['DMG', 'AGB']
    def GetSupprtedModes(self): return self.GetSupportedModes()
    def CanSetVoltageBySwitch(self): return False
    def CanSetVoltageByCode(self): return False
    def CanSetVoltageByAutoswitch(self): return False
    def CanPowerCycleCart(self): return False
    def IsSupported3dMemory(self): return False
    def IsClkConnected(self): return False
    def SupportsFirmwareUpdates(self): return False
    def FirmwareUpdateAvailable(self): return False
    def GetFirmwareUpdaterClass(self): return None
    def SupportsBootloaderReset(self): return False
    def SupportsAudioAsWe(self): return False
    def ChangeBaudRate(self, value): return None
    def GetDeviceSerial(self): return None
    def _clk_toggle(self, num=1):
        raise UnsupportedNativeFeature('盖中盖基础协议不支持逐次 CLK 脉冲')


def plugin_entry():
    # 替换注册表中的官方后端，不增加第二个候选，也不修改官方模块。
    for index, module in enumerate(HW_DEVICES):
        if module.GbxDevice is _GBFlashBase:
            HW_DEVICES[index] = SimpleNamespace(GbxDevice=GBFlashDevice)
    for backend in (GbxDevice, CarbonateDevice):
        if not any(getattr(module.GbxDevice, 'DEVICE_NAME', None) == backend.DEVICE_NAME for module in HW_DEVICES):
            HW_DEVICES.insert(0, SimpleNamespace(GbxDevice=backend))
