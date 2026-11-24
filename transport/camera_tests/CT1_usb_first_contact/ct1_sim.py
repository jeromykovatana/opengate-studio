"""A stand-in for the camera's service-mode USB endpoints, for the dry run and the self-test.

It plays the camera's side of the exchange as PMCA-RE's client code expects it,
so the real stage code and the real PMCA-RE classes can run with no camera.
It proves our flow and our guards, not the camera: the framing here mirrors
PMCA-RE's reader (pmca/usb/sony.py, SonySenserDevice.sendSenserPacket).

The simulated camera refuses to answer anything CT1 must never send, and
records it in `unexpected`, so a self-test can assert that list is empty.
"""
import hashlib
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ct1_common as c

AUTH_FORMAT = ">HH512s"                 # PMCA AuthPacket: cmd (inverted), salt, data
AUTH_SIZE = struct.calcsize(AUTH_FORMAT)
HEADER_FORMAT = "<IHHBBBB"              # PMCA SenserPacketHeader
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
PART_MAX = 0x100000
CHUNK = 0x8000
ZLP = object()                          # the short read PMCA makes after a chunk that is a multiple of 0x200

SIM_MSC_ID = (c.SONY_VID, 0x0DA5)       # the camera's mass-storage product id (seen 2026-11-13)


class SimUsbError(Exception):
    """What the real driver reports as 'A device attached to the system is not functioning'."""
SIM_SENSER_ID = (c.SONY_VID, 0x0336)


class SimDriver:
    """Looks like a PMCA GenericUsbDriver to the code above it."""

    def __init__(self, mode, backup=b"", files=None, style="stream", rules=None, props=None):
        # style "stream": what the camera did on Windows with libusb-win32 on 2026-11-13. Each
        #   12-byte header is its own short transfer; each part's data follows as one run with
        #   no padding; a read ends early only at a short packet; a read whose length is not a
        #   multiple of 512 while more full packets are coming fails (overflow).
        # style "zlp": what PMCA-RE's reader assumes: 0x8000-byte chunks, each followed by a
        #   read that returns nothing.
        assert mode in ("msc", "senser") and style in ("stream", "zlp")
        self.mode = mode
        self.style = style
        self.rules = rules
        self.props = dict(props or {})      # settings in memory
        self.saved = dict(self.props)       # settings as last saved
        self.backup = backup
        self.files = files or {}
        self.queue = []
        self.vendor_requests = []
        self.unexpected = []
        self.service_packets = []
        self.service_writes = []
        self._challenge = None
        self._rounds = 0
        self._authed = False
        self._path = None

    # ---- driver surface ----
    def getId(self):
        return SIM_MSC_ID if self.mode == "msc" else SIM_SENSER_ID

    def reset(self):
        pass

    def vendorRequestOut(self, request, value, index, data=b""):
        self.vendor_requests.append((request, value, index, bytes(data)))

    def write(self, data, ep=0):
        data = bytes(data)
        if ep != 0:
            self.unexpected.append(("write on endpoint index", ep))
            return
        if not self._authed:
            self._auth(data)
        else:
            self.service_writes.append(data)
            self._service(data)

    def read(self, length, ep=0, timeout=None):
        if not self.queue:
            raise AssertionError("simulated camera: read with nothing to send")
        if self.style == "stream":
            return self._read_stream(length)
        head = self.queue[0]
        if head is ZLP:
            self.queue.pop(0)
            return b""
        out, rest = head[:length], head[length:]
        if rest:
            self.queue[0] = rest
        else:
            self.queue.pop(0)
        return out

    def _read_stream(self, length):
        # bytes on offer before the next short packet ends the read
        run = 0
        for transfer, total in self.queue:
            run += len(transfer)
            if total % 512:
                break
        if length % 512 and run > length:
            raise SimUsbError("overflow: asked for %d bytes while full packets were still coming" % length)
        out = b""
        while self.queue and len(out) < length:
            transfer, total = self.queue[0]
            take = transfer[:length - len(out)]
            out += take
            if len(take) < len(transfer):
                self.queue[0] = (transfer[len(take):], total)
                break
            self.queue.pop(0)
            if total % 512:
                break
        return out

    def _push(self, data):
        self.queue.append((data, len(data)) if self.style == "stream" else data)

    # ---- camera side ----
    def _auth_reply(self, ret, data=b""):
        self._push(struct.pack(AUTH_FORMAT, ~ret & 0xFFFF, 0, data))

    def _auth(self, packet):
        if len(packet) != AUTH_SIZE:
            self.unexpected.append(("packet before authentication", len(packet)))
            return
        cmd, _salt, data = struct.unpack(AUTH_FORMAT, packet)
        cmd = ~cmd & 0xFFFF
        if cmd == 1:
            self._challenge = os.urandom(512)
            self._auth_reply(8, self._challenge)                     # 8 = SHA-256 variant
        elif cmd == 3:
            if self.mode == "senser":
                from pmca.usb import constants                       # public keys, used in place
                expected = hashlib.sha256(self._challenge + constants.senserKeysSha256[self._rounds]).digest()
            else:
                expected = hashlib.sha256(self._challenge[:4]).digest()
            ok = data[0] == 1 and data[1:33] == expected
            self._rounds += 1 if ok else 0
            self._auth_reply(4 if ok else 0xFF)
        elif cmd == 5:
            self._authed = self._rounds == 3
            self._auth_reply(6, bytes([1 if self._authed else 0]))
        else:
            self.unexpected.append(("authentication command", cmd))

    def _service(self, packet):
        size, pfunc, sequence, _v, _m, _o, _r = struct.unpack_from(HEADER_FORMAT, packet, 0)
        body = packet[HEADER_SIZE:HEADER_SIZE + size]
        self.service_packets.append((pfunc, body))
        response, out = self._handle(pfunc, body)
        remaining = len(out)
        position = 0
        while True:
            self._push(struct.pack(HEADER_FORMAT, remaining, pfunc, sequence, 0, 0, 0, response))
            part = min(remaining, PART_MAX)
            done = 0
            if self.style == "stream":
                if part:
                    self._push(out[position:position + part])
                position += part
                done = part
            while done < part:
                n = min(part - done, CHUNK)
                self.queue.append(out[position:position + n])
                if not (n & 0x1FF):
                    self.queue.append(ZLP)
                position += n
                done += n
            if remaining <= PART_MAX:
                break
            remaining -= part

    def _handle(self, pfunc, body):
        try:
            name = c.classify_service_packet(pfunc, body, self.rules)
        except c.GuardRefusal as exc:
            self.unexpected.append(("service packet", pfunc, body[:16].hex(), str(exc)))
            return 0xEE, b""
        if name == "READ_HASP":
            return 1, bytes(32)
        if name == "BACKUP_READ_FROM_MEMORY":
            return 0, self.backup
        if name == "SET_FILE_PATH":
            self._path = body[5:]
            return 0, b""
        if name == "GET_FILE2":
            content = self.files.get(self._path)
            if content is None:
                return 0, struct.pack("<I", 2)                       # inner status: not found
            return 0, struct.pack("<I", 0) + content
        if name == "BACKUP_READ":
            return 0, self.props[struct.unpack_from("<I", body, 4)[0]]
        if name == "BACKUP_WRITE":
            self.props[struct.unpack_from("<I", body, 4)[0]] = body[8:]
            return 0, b""
        if name == "BACKUP_SAVE":
            self.saved = dict(self.props)
            return 0, b""
        raise AssertionError(name)


def default_files():
    """What the simulated camera returns for the two probe paths (the predicted answers)."""
    device_info = (c.EXTRACTED / "0700_part_image/dev/nflasha15/share/pmbp/DeviceInfo.xml").read_bytes()
    return {c.PROBE_PATHS[0]: device_info, c.PROBE_PATHS[1]: b""}


def default_backup():
    """A regional profile from the update stands in for the live backup (same format and size)."""
    bk4 = c.use_bk4()
    return bk4.profile_paths(c.EXTRACTED / "update")[0].read_bytes()
