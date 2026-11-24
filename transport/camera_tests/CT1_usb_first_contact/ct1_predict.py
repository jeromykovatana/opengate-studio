"""CT1 predictions, generated from the map and frozen before the camera is touched.

Writes predictions.json. It has no date in it, so running this again on an
unchanged map gives the same bytes; the stage manifests record its SHA-256.

  python -I -B ct1_predict.py            write predictions.json (refuses to change an existing one)
  python -I -B ct1_predict.py --check    exit 1 if the file differs from what the map gives now
  python -I -B ct1_predict.py --replace  overwrite (only before the run; say why in BUILD_LOG.md)
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ct1_common as c

BUILD = "a7iv_602"
DEVICE_INFO = "0700_part_image/dev/nflasha15/share/pmbp/DeviceInfo.xml"
PROFILE_BYTES = 2369436          # size of every regional settings profile in the 6.02 update


def bkid_catalogue(db):
    """{property id: (name, size, capacity, attr, default_hex, default_truncated, uniform)}"""
    out = {}
    for key, name, value_json in db.execute(
            "SELECT key, name, value_json FROM catalog_item WHERE build=? AND kind='bkid'", (BUILD,)):
        v = json.loads(value_json)
        out[int(key, 16)] = (name, v["size"], v["capacity"], int(v["attr"], 16), v["default_hex"],
                             bool(v.get("default_truncated")), bool(v.get("uniform")))
    return out


def bkid_digest(catalogue):
    h = hashlib.sha256()
    for pid in sorted(catalogue):
        _name, size, capacity, attr, default_hex, _trunc, _uniform = catalogue[pid]
        h.update(("%08x %d %d %04x %s\n" % (pid, size, capacity, attr, default_hex)).encode())
    return h.hexdigest()


def build():
    db = sqlite3.connect(c.CORE_DB.as_uri() + "?mode=ro", uri=True)
    ptp = {}
    for key, name, value_json in db.execute(
            "SELECT key, name, value_json FROM catalog_item WHERE build=? AND kind='ptp_prop' ORDER BY key",
            (BUILD,)):
        v = json.loads(value_json)
        ptp[key] = {"name": name, "datatype_name": v.get("datatype_name")}
    catalogue = bkid_catalogue(db)
    desqueeze = catalogue[0x02CF1BF2]
    device_info = (c.EXTRACTED / DEVICE_INFO).read_bytes()

    predictions = [
        {"id": "P1", "stage": 1, "text": "PTP DeviceInfo model is ILCE-7M4 and a Sony vendor extension is present",
         "source": "camera identity"},
        {"id": "P2", "stage": 1, "text": "Every property code the camera advertises is one of the map's %d" % len(ptp),
         "source": "F241"},
        {"id": "P3", "stage": 1, "text": "Property 0xd214 is present and its datatype is UINT32", "source": "F241"},
        {"id": "P4", "stage": 1, "text": "Operation 0x9209 is advertised and the Sony protocol version is 0x012c",
         "source": "leogenot/sony-a7iv-feature-research scripts/a7iv_ptp_snapshot.py"},
        {"id": "P5", "stage": 1, "text": "Two snapshots a few seconds apart list the same codes with the same "
                                         "datatypes; only current values and enabled flags may differ",
         "source": "none (stability check)"},
        {"id": "P6", "stage": 2, "text": "After the start request and the first exchange the camera re-enumerates "
                                         "as 054C:0336, vendor-specific class", "source": "F410 (external claim)"},
        {"id": "P7", "stage": 2, "text": "Three SHA-256 rounds with the public session keys pass and the closing "
                                         "command is accepted", "source": "F421"},
        {"id": "P8", "stage": 2, "text": "The backup is %d bytes, parses as BK4 with valid checksums, and its first "
                                         "bank holds %d properties" % (PROFILE_BYTES, len(catalogue)),
         "source": "regional profiles in the 6.02 update; leogenot docs/SERVICE_MODE.md (same size)"},
        {"id": "P9", "stage": 2, "text": "The first bank has exactly the catalogue's property ids, each with the "
                                         "catalogue's size and attribute; its region string names one of the 32 "
                                         "regional profiles", "source": "catalogue kind bkid (import_backup_profiles.py)"},
        {"id": "P10", "stage": 2, "text": "Property 0x02cf1bf2 (BKID_APP_SETTING_DE_SQUEEZE_DISP) is one byte, 00",
         "source": "F11; A7iv Claude camera_tests/DESQUEEZE_TEST_1B.md"},
        {"id": "P11", "stage": 3, "text": "/usr/share/pmbp/DeviceInfo.xml reads back as %d bytes with the SHA-256 of "
                                          "the file in the 6.02 update" % len(device_info), "source": "F411"},
        {"id": "P12", "stage": 3, "text": "/proc/cmdline comes back with no content (the size is taken from stat, "
                                          "which reports 0), either as an empty answer or an error status",
         "source": "F418 (modding/USB_READ_CHECK_DESIGN.md part 2)"},
    ]
    return {
        "test": "CT1",
        "build": BUILD,
        "generated_by": "camera_tests/CT1_usb_first_contact/ct1_predict.py from a7iv.sqlite catalog_item",
        "expected": {"model": c.EXPECTED_MODEL, "firmware": c.EXPECTED_FIRMWARE,
                     "service_usb_id": "054c:0336", "sony_protocol_version": "0x012c"},
        "predictions": predictions,
        "ptp": {"count": len(ptp), "codes": sorted(ptp),
                "named": {k: v for k, v in ptp.items() if v["name"]}},
        "bkid": {"rows": len(catalogue), "digest_sha256": bkid_digest(catalogue),
                 "digest_recipe": "sha256 of '%08x %d %d %04x %s\\n' % (id, size, capacity, attr, default_hex), ids ascending",
                 "backup_bytes": PROFILE_BYTES,
                 "desqueeze": {"id": "0x02cf1bf2", "size": desqueeze[1], "default_hex": desqueeze[4]}},
        "files": {"/usr/share/pmbp/DeviceInfo.xml": {"bytes": len(device_info), "sha256": c.sha256(device_info)},
                  "/proc/cmdline": {"bytes": 0}},
    }


def render():
    return (json.dumps(build(), indent=1) + "\n").encode("utf-8")


def main():
    new = render()
    if "--check" in sys.argv:
        same = c.PREDICTIONS.exists() and c.PREDICTIONS.read_bytes() == new
        print("predictions.json %s (sha256 %s)" % ("matches the map" if same else "DIFFERS from the map", c.sha256(new)))
        raise SystemExit(0 if same else 1)
    if c.PREDICTIONS.exists() and c.PREDICTIONS.read_bytes() != new and "--replace" not in sys.argv:
        raise SystemExit("predictions.json exists and differs; it is frozen. Use --replace only before the run.")
    c.PREDICTIONS.write_bytes(new)
    print("predictions.json written: %d bytes, sha256 %s" % (len(new), c.sha256(new)))


if __name__ == "__main__":
    main()
