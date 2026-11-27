# SPDX-License-Identifier: GPL-3.0-or-later
"""Clean-room pyusb-compatible Android USB-OTG shim for vendored sony-pmca-re.

Maps ``usb.core`` and ``usb.util`` calls from ``pmca.usb.driver.generic.libusb``
onto an injected Android ``UsbBridge`` implementation backed by ``UsbManager`` /
``UsbDeviceConnection`` with forceful interface claiming and 30s service-mode
enumeration timeouts.
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_SERVICE_TIMEOUT_MS = 30_000

CTRL_OUT = 0x00
CTRL_IN = 0x80
CTRL_TYPE_STANDARD = 0x00
CTRL_TYPE_CLASS = 0x20
CTRL_TYPE_VENDOR = 0x40
CTRL_RECIPIENT_DEVICE = 0x00
CTRL_RECIPIENT_INTERFACE = 0x01
CTRL_RECIPIENT_ENDPOINT = 0x02
CTRL_RECIPIENT_OTHER = 0x03

ENDPOINT_IN = 0x80
ENDPOINT_OUT = 0x00
ENDPOINT_TYPE_BULK = 0x02


class AndroidUsbError(Exception):
    """Raised when the Android USB host bridge reports an I/O or permission error."""


class _BytePayload(bytes):
    """Bytes subclass providing pyusb's ``.tobytes()`` convenience method."""

    def tobytes(self) -> bytes:
        return bytes(self)


@dataclass(frozen=True)
class AndroidUsbEndpoint:
    bEndpointAddress: int
    bmAttributes: int = ENDPOINT_TYPE_BULK
    wMaxPacketSize: int = 512


class AndroidUsbInterface:
    """Represents a single USB interface and supports ``[(0, 0)]`` endpoint lookup."""

    def __init__(
        self,
        interface_number: int,
        bInterfaceClass: int,
        bInterfaceProtocol: int,
        endpoints: list[AndroidUsbEndpoint],
    ) -> None:
        self.bInterfaceNumber = interface_number
        self.bInterfaceClass = bInterfaceClass
        self.bInterfaceProtocol = bInterfaceProtocol
        self._endpoints = list(endpoints)

    def __iter__(self):
        return iter(self._endpoints)


class AndroidUsbConfiguration:
    """Represents the active USB configuration."""

    def __init__(self, interfaces: list[AndroidUsbInterface]) -> None:
        self._interfaces = list(interfaces)

    def __iter__(self):
        return iter(self._interfaces)

    def __getitem__(self, key: tuple[int, int]) -> AndroidUsbInterface:
        iface_num, _alt = key
        for iface in self._interfaces:
            if iface.bInterfaceNumber == iface_num:
                return iface
        if self._interfaces:
            return self._interfaces[0]
        raise KeyError(key)


class AndroidUsbDevice:
    """pyusb-compatible device wrapper backed by an Android ``UsbBridge``."""

    def __init__(
        self,
        bridge: Any,
        device_id: Any,
        id_vendor: int,
        id_product: int,
        interfaces: list[AndroidUsbInterface],
        *,
        serial_number: str = "",
        default_timeout: int = DEFAULT_SERVICE_TIMEOUT_MS,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self._bridge = bridge
        self.device_id = device_id
        self.idVendor = int(id_vendor)
        self.idProduct = int(id_product)
        self.serial_number = serial_number
        self.default_timeout = int(default_timeout)
        self._cancel_check = cancel_check
        self._config = AndroidUsbConfiguration(interfaces)
        self._handle: Any = None

    def __iter__(self):
        return iter([self._config])

    def get_active_configuration(self) -> AndroidUsbConfiguration:
        return self._config

    def _ensure_open(self) -> Any:
        if self._cancel_check is not None and self._cancel_check():
            raise AndroidUsbError("Cancelled before opening USB device")
        if self._handle is None:
            try:
                self._handle = self._bridge.openAndClaim(self.device_id, self.default_timeout)
            except Exception as exc:
                raise AndroidUsbError(f"openAndClaim failed: {exc}") from exc
            if self._handle is None:
                raise AndroidUsbError("USB permission denied or device disconnected")
        return self._handle

    def is_kernel_driver_active(self, interface: int = 0) -> bool:
        return False

    def detach_kernel_driver(self, interface: int = 0) -> None:
        # Android UsbDeviceConnection.claimInterface(iface, true) detaches kernel MSC driver.
        self._ensure_open()

    def clear_halt(self, ep: Any) -> None:
        ep_addr = ep.bEndpointAddress if hasattr(ep, "bEndpointAddress") else int(ep)
        if hasattr(self._bridge, "clearHalt"):
            try:
                self._bridge.clearHalt(self._ensure_open(), int(ep_addr))
            except Exception as exc:
                raise AndroidUsbError(f"clearHalt failed: {exc}") from exc

    def read(self, ep: Any, length: int, timeout: int | None = None) -> _BytePayload:
        ep_addr = ep.bEndpointAddress if hasattr(ep, "bEndpointAddress") else int(ep)
        eff_timeout = self.default_timeout if timeout is None else int(timeout)
        handle = self._ensure_open()
        try:
            raw = self._bridge.bulkRead(handle, int(ep_addr), int(length), eff_timeout)
        except Exception as exc:
            raise AndroidUsbError(f"bulkRead failed: {exc}") from exc
        return _BytePayload(bytes(raw or b""))

    def write(self, ep: Any, data: bytes | bytearray, timeout: int | None = None) -> int:
        ep_addr = ep.bEndpointAddress if hasattr(ep, "bEndpointAddress") else int(ep)
        eff_timeout = self.default_timeout if timeout is None else int(timeout)
        handle = self._ensure_open()
        payload = bytes(data)
        try:
            written = self._bridge.bulkWrite(handle, int(ep_addr), payload, eff_timeout)
        except Exception as exc:
            raise AndroidUsbError(f"bulkWrite failed: {exc}") from exc
        return len(payload) if written is None else int(written)

    def ctrl_transfer(
        self,
        bmRequestType: int,
        bRequest: int,
        wValue: int = 0,
        wIndex: int = 0,
        data_or_wLength: bytes | int = 0,
        timeout: int | None = None,
    ) -> Any:
        eff_timeout = self.default_timeout if timeout is None else int(timeout)
        handle = self._ensure_open()
        try:
            res = self._bridge.controlTransfer(
                handle,
                int(bmRequestType),
                int(bRequest),
                int(wValue),
                int(wIndex),
                data_or_wLength,
                eff_timeout,
            )
        except Exception as exc:
            raise AndroidUsbError(f"controlTransfer failed: {exc}") from exc
        if isinstance(data_or_wLength, int):
            return _BytePayload(bytes(res or b""))
        return len(data_or_wLength) if res is None else int(res)

    def reset(self) -> None:
        if self._handle is not None and hasattr(self._bridge, "resetDevice"):
            try:
                self._bridge.resetDevice(self._handle)
            except Exception as exc:
                raise AndroidUsbError(f"resetDevice failed: {exc}") from exc

    def dispose(self) -> None:
        if self._handle is not None:
            try:
                self._bridge.close(self._handle)
            finally:
                self._handle = None


class AndroidUsbBackend:
    """Implements ``usb.core.find`` against a Kotlin/Java or Python test ``UsbBridge``."""

    def __init__(
        self,
        bridge: Any,
        *,
        default_timeout_ms: int = DEFAULT_SERVICE_TIMEOUT_MS,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.bridge = bridge
        self.default_timeout_ms = int(default_timeout_ms)
        self.cancel_check = cancel_check

    def find(
        self,
        find_all: bool = False,
        idVendor: int | None = None,
        idProduct: int | None = None,
        **_: Any,
    ) -> list[AndroidUsbDevice] | AndroidUsbDevice | None:
        if self.cancel_check is not None and self.cancel_check():
            return [] if find_all else None

        raw_devices = self.bridge.findDevices(idVendor)
        devices: list[AndroidUsbDevice] = []
        for desc in raw_devices or []:
            vid = int(desc["idVendor"])
            pid = int(desc["idProduct"])
            if idVendor is not None and vid != int(idVendor):
                continue
            if idProduct is not None and pid != int(idProduct):
                continue

            ifaces: list[AndroidUsbInterface] = []
            for iface_d in desc.get("interfaces", []):
                eps = [
                    AndroidUsbEndpoint(
                        bEndpointAddress=int(ep_d["address"]),
                        bmAttributes=int(ep_d.get("attributes", ENDPOINT_TYPE_BULK)),
                        wMaxPacketSize=int(ep_d.get("maxPacketSize", 512)),
                    )
                    for ep_d in iface_d.get("endpoints", [])
                ]
                ifaces.append(
                    AndroidUsbInterface(
                        interface_number=int(iface_d.get("number", 0)),
                        bInterfaceClass=int(iface_d["interfaceClass"]),
                        bInterfaceProtocol=int(iface_d.get("interfaceProtocol", 0)),
                        endpoints=eps,
                    )
                )

            devices.append(
                AndroidUsbDevice(
                    self.bridge,
                    desc["deviceId"],
                    vid,
                    pid,
                    ifaces,
                    serial_number=str(desc.get("serialNumber", "")),
                    default_timeout=self.default_timeout_ms,
                    cancel_check=self.cancel_check,
                )
            )

        if find_all:
            return devices
        return devices[0] if devices else None


def install_usb_shim(
    bridge: Any,
    *,
    default_timeout_ms: int = DEFAULT_SERVICE_TIMEOUT_MS,
    cancel_check: Callable[[], bool] | None = None,
) -> AndroidUsbBackend:
    """Install ``usb``, ``usb.core``, and ``usb.util`` into ``sys.modules``."""
    backend = AndroidUsbBackend(
        bridge,
        default_timeout_ms=default_timeout_ms,
        cancel_check=cancel_check,
    )

    usb_mod = types.ModuleType("usb")
    usb_core = types.ModuleType("usb.core")
    usb_util = types.ModuleType("usb.util")

    usb_core.USBError = AndroidUsbError  # type: ignore[attr-defined]
    usb_core.find = backend.find  # type: ignore[attr-defined]

    def _dispose_resources(dev: Any) -> None:
        if hasattr(dev, "dispose"):
            dev.dispose()

    def _endpoint_direction(address: int) -> int:
        return int(address) & ENDPOINT_IN

    def _endpoint_type(attributes: int) -> int:
        return int(attributes) & 0x03

    def _find_descriptor(desc_iter: Any, **kwargs: Any) -> Any:
        custom_match = kwargs.pop("custom_match", None)
        find_all = bool(kwargs.pop("find_all", False))
        matches = []
        for item in desc_iter:
            if all(getattr(item, k, None) == v for k, v in kwargs.items()):
                if custom_match is None or custom_match(item):
                    matches.append(item)
        if find_all:
            return matches
        return matches[0] if matches else None

    usb_util.CTRL_OUT = CTRL_OUT  # type: ignore[attr-defined]
    usb_util.CTRL_IN = CTRL_IN  # type: ignore[attr-defined]
    usb_util.CTRL_TYPE_STANDARD = CTRL_TYPE_STANDARD  # type: ignore[attr-defined]
    usb_util.CTRL_TYPE_CLASS = CTRL_TYPE_CLASS  # type: ignore[attr-defined]
    usb_util.CTRL_TYPE_VENDOR = CTRL_TYPE_VENDOR  # type: ignore[attr-defined]
    usb_util.CTRL_RECIPIENT_DEVICE = CTRL_RECIPIENT_DEVICE  # type: ignore[attr-defined]
    usb_util.CTRL_RECIPIENT_INTERFACE = CTRL_RECIPIENT_INTERFACE  # type: ignore[attr-defined]
    usb_util.CTRL_RECIPIENT_ENDPOINT = CTRL_RECIPIENT_ENDPOINT  # type: ignore[attr-defined]
    usb_util.CTRL_RECIPIENT_OTHER = CTRL_RECIPIENT_OTHER  # type: ignore[attr-defined]
    usb_util.ENDPOINT_IN = ENDPOINT_IN  # type: ignore[attr-defined]
    usb_util.ENDPOINT_OUT = ENDPOINT_OUT  # type: ignore[attr-defined]
    usb_util.ENDPOINT_TYPE_BULK = ENDPOINT_TYPE_BULK  # type: ignore[attr-defined]
    usb_util.dispose_resources = _dispose_resources  # type: ignore[attr-defined]
    usb_util.endpoint_direction = _endpoint_direction  # type: ignore[attr-defined]
    usb_util.endpoint_type = _endpoint_type  # type: ignore[attr-defined]
    usb_util.find_descriptor = _find_descriptor  # type: ignore[attr-defined]

    usb_mod.core = usb_core  # type: ignore[attr-defined]
    usb_mod.util = usb_util  # type: ignore[attr-defined]

    sys.modules["usb"] = usb_mod
    sys.modules["usb.core"] = usb_core
    sys.modules["usb.util"] = usb_util
    return backend


def uninstall_usb_shim() -> None:
    """Remove the installed ``usb`` shim modules from ``sys.modules``."""
    for name in ("usb.util", "usb.core", "usb"):
        sys.modules.pop(name, None)
