"""CT1: compare what the camera returned with the frozen predictions. Offline; sends nothing.

  python -I -B ct1_compare.py --stage1 <session folder> --stage2 <session folder> --out <evidence folder>

Reads the private session folders and writes results.json to the evidence folder
inside the map. That file holds outcomes, counts, hashes and property ids. It
holds no serial number and no setting value except the one de-squeeze byte P10
is about, because a settings backup can contain private data (Wi-Fi keys, names).
"""
import argparse
import json
import sqlite3
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ct1_common as c
import ct1_predict

PASS, FAIL, NOT_RUN = "confirmed", "refuted", "not run"


def outcome(pid, ok, detail):
    return {"id": pid, "outcome": PASS if ok else FAIL, "detail": detail}


def load_predictions():
    return json.loads(c.PREDICTIONS.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- stage 1

def evaluate_stage1(snapshot, pred):
    """snapshot: the dict stage 1 saved as ptp_snapshot.json."""
    info = c.parse_device_info(bytes.fromhex(snapshot["device_info_raw"]))
    ext = c.parse_ext_device_info(bytes.fromhex(snapshot["ext_device_info_raw"]))
    first = c.parse_all_prop_info(bytes.fromhex(snapshot["all_prop_info_raw"][0]))
    second = c.parse_all_prop_info(bytes.fromhex(snapshot["all_prop_info_raw"][1]))
    map_codes = {int(k, 16) for k in pred["ptp"]["codes"]}

    out = []
    out.append(outcome("P1", info["model"] == pred["expected"]["model"] and info["vendor_extension_id"] != 0,
                       "model %r, vendor extension id 0x%x %r, device version %r"
                       % (info["model"], info["vendor_extension_id"], info["vendor_extension_desc"],
                          info["device_version"])))

    advertised = set(ext["properties"]) | {d["code"] for d in first}
    unknown = sorted(advertised - map_codes)
    out.append(outcome("P2", not unknown,
                       "%d codes advertised (%d in the extended info list, %d descriptors); %d are in the map; "
                       "%d are not: %s; %d of the map's %d codes are not advertised in this mode"
                       % (len(advertised), len(ext["properties"]), len(first), len(advertised & map_codes),
                          len(unknown), ["0x%04x" % x for x in unknown][:40],
                          len(map_codes - advertised), len(map_codes))))

    d214 = next((d for d in first if d["code"] == 0xD214), None)
    out.append(outcome("P3", d214 is not None and d214["datatype"] == 6,
                       "0xd214 " + ("datatype %s, enabled %d" % (d214["datatype_name"], d214["enabled"])
                                    if d214 else "is not in the property block")))

    out.append(outcome("P4", c.SDIO_GET_ALL_EXT_DEVICE_PROP_INFO in info["operations"]
                       and ext["version"] == c.SONY_PROTOCOL_3_00,
                       "0x9209 %s; Sony protocol version 0x%04x"
                       % ("advertised" if c.SDIO_GET_ALL_EXT_DEVICE_PROP_INFO in info["operations"]
                          else "NOT advertised", ext["version"])))

    shape1 = [(d["code"], d["datatype"]) for d in first]
    shape2 = [(d["code"], d["datatype"]) for d in second]
    by_code = {d["code"]: d for d in second}
    moved = sorted(d["code"] for d in first
                   if d["code"] in by_code and (d["current"], d["enabled"])
                   != (by_code[d["code"]]["current"], by_code[d["code"]]["enabled"]))
    out.append(outcome("P5", shape1 == shape2,
                       "%d and %d descriptors; %d changed value or enabled flag between the two reads: %s"
                       % (len(first), len(second), len(moved), ["0x%04x" % x for x in moved][:40])))

    facts = {
        "model": info["model"], "device_version": info["device_version"],
        "manufacturer": info["manufacturer"],
        "vendor_extension_id": "0x%x" % info["vendor_extension_id"],
        "vendor_extension_version": info["vendor_extension_version"],
        "vendor_extension_desc": info["vendor_extension_desc"],
        "operations": ["0x%04x" % x for x in sorted(info["operations"])],
        "events": ["0x%04x" % x for x in sorted(info["events"])],
        "standard_properties": ["0x%04x" % x for x in sorted(info["properties"])],
        "sony_protocol_version": "0x%04x" % ext["version"],
        "advertised_property_codes": ["0x%04x" % x for x in sorted(ext["properties"])],
        "control_codes": ["0x%04x" % x for x in sorted(ext["controls"])],
        "control_codes_in_map": len(set(ext["controls"]) & map_codes),
        "advertised_not_in_map": ["0x%04x" % x for x in unknown],
        "map_codes_not_advertised": ["0x%04x" % x for x in sorted(map_codes - advertised)],
        "descriptors": [{"code": "0x%04x" % d["code"], "datatype": d["datatype_name"], "get_set": d["get_set"],
                         "enabled": d["enabled"], "form": d["form"],
                         "enum_count": len(d.get("enum", [])), "size": d["size"]} for d in first],
    }
    return out, facts


# ---------------------------------------------------------------- stage 2

def parse_backup(blob):
    """All BK4 banks in a backup (checksums verified by the parser)."""
    bk4 = c.use_bk4()
    banks = []
    for base in bk4.PROFILE_BANK_OFFSETS:
        if base + 16 <= len(blob) and blob[base + 12:base + 16] == b"BK4\0":
            banks.append(bk4.BK4(blob, base, "live@0x%x" % base))
    if not banks:
        raise ValueError("no BK4 header found")
    return banks


def auth_summary(events, label):
    """Decode the answers to the authentication packets from the raw USB log."""
    rets = []
    for e in events:
        if e["kind"] == "service_out":           # authentication is over once service packets start
            break
        if e["kind"] == "usb_in" and e.get("dev") == label and e.get("asked") == 516 and len(e["head"]) >= 8:
            cmd, salt = struct.unpack(">HH", bytes.fromhex(e["head"][:8]))
            rets.append((~cmd & 0xFFFF) - salt)
    return {"answers": rets, "rounds_passed": rets.count(4), "closed": bool(rets) and rets[-1] == 6,
            "variant": "sha256" if 8 in rets else ("sha1" if 2 in rets else None)}


def profile_for_region(region):
    bk4 = c.use_bk4()
    for path in bk4.profile_paths(c.EXTRACTED / "update"):
        if path.stem == region:
            return path
    return None


def evaluate_backup(blob, pred):
    """P8, P9, P10 from the backup bytes."""
    out = []
    facts = {"bytes": len(blob), "sha256": c.sha256(blob)}
    try:
        banks = parse_backup(blob)
    except Exception as exc:
        out.append(outcome("P8", False, "%d bytes; does not parse: %s" % (len(blob), exc)))
        return out, facts
    live = banks[0]
    facts.update(banks=len(banks), region=live.region, version=live.version,
                 properties=[len(b.props) for b in banks])
    out.append(outcome("P8", len(blob) == pred["bkid"]["backup_bytes"] and len(live.props) == pred["bkid"]["rows"],
                       "%d bytes (predicted %d); %d bank(s), checksums valid; first bank %d properties "
                       "(predicted %d); region %r, version %r"
                       % (len(blob), pred["bkid"]["backup_bytes"], len(banks), len(live.props),
                          pred["bkid"]["rows"], live.region, live.version)))

    db = sqlite3.connect(c.CORE_DB.as_uri() + "?mode=ro", uri=True)
    catalogue = ct1_predict.bkid_catalogue(db)
    if ct1_predict.bkid_digest(catalogue) != pred["bkid"]["digest_sha256"]:
        raise c.StopTest("the settings catalogue changed since predictions.json was frozen")
    only_live = sorted(set(live.props) - set(catalogue))
    only_map = sorted(set(catalogue) - set(live.props))
    size_bad = sorted(k for k, p in live.props.items() if k in catalogue and catalogue[k][1] != len(p.data))
    attr_bad = sorted(k for k, p in live.props.items() if k in catalogue and catalogue[k][3] != p.attr)
    profile = profile_for_region(live.region)
    out.append(outcome("P9", not (only_live or only_map or size_bad or attr_bad) and profile is not None,
                       "ids only in the backup: %d; only in the catalogue: %d; size mismatches: %d; attribute "
                       "mismatches: %d; region %r %s"
                       % (len(only_live), len(only_map), len(size_bad), len(attr_bad), live.region,
                          "is one of the regional profiles" if profile else "is NOT a regional profile name")))

    def named(ids):
        return [{"id": "0x%08x" % k, "name": catalogue[k][0] if k in catalogue else None} for k in ids]

    facts.update(ids_only_in_backup=named(only_live), ids_only_in_catalogue=named(only_map),
                 size_mismatches=named(size_bad), attr_mismatches=named(attr_bad))
    if profile is not None:
        bk4 = c.use_bk4()
        factory = bk4.load_backup(profile)[0]
        changed = sorted(k for k, p in live.props.items()
                         if k in factory.props and p.data != factory.props[k].data)
        facts.update(regional_profile=profile.stem, values_differing_from_profile=len(changed),
                     differing_ids=named(changed))        # ids and names only, never values
    prop = live.props.get(0x02CF1BF2)
    out.append(outcome("P10", prop is not None and prop.data == b"\x00",
                       "0x02cf1bf2 " + (("is " + prop.data.hex()) if prop is not None else "is absent")))
    return out, facts


def evaluate_stage2(folder, pred):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    results = manifest["results"]
    out = []
    facts = {"usb": {k: results.get(k) for k in ("msc_usb_id", "msc_inquiry", "service_usb_id",
                                                 "service_interface_class", "libusb_backend")}}
    if "service_usb_id" in results:
        out.append(outcome("P6", results["service_usb_id"] == pred["expected"]["service_usb_id"]
                           and results.get("service_interface_class") == 255,
                           "service device %s, interface class %s"
                           % (results["service_usb_id"], results.get("service_interface_class"))))
    if "auth_service" in results:
        a = results["auth_service"]
        facts["auth"] = {"mass_storage_phase": results.get("auth_msc"), "service_phase": a}
        out.append(outcome("P7", a["rounds_passed"] == 3 and a["closed"] and a["variant"] == "sha256",
                           "answers %s; %d rounds passed; variant %s; closing %s"
                           % (a["answers"], a["rounds_passed"], a["variant"],
                              "accepted" if a["closed"] else "not accepted")))
    backup = folder / "backup_live.bin"
    if backup.exists():
        more, backup_facts = evaluate_backup(backup.read_bytes(), pred)
        out += more
        facts["backup"] = backup_facts
    for pid, key, path in (("P11", "probe1", "/usr/share/pmbp/DeviceInfo.xml"), ("P12", "probe2", "/proc/cmdline")):
        probe = results.get(key)
        if probe is None:
            continue
        facts[key] = probe
        want = pred["files"][path]
        if pid == "P11":
            ok = probe.get("bytes") == want["bytes"] and probe.get("sha256") == want["sha256"]
        else:
            ok = probe.get("bytes", 0) == 0
        out.append(outcome(pid, ok, "status %s, %s bytes, sha256 %s, error %s"
                           % (probe.get("status"), probe.get("bytes"), probe.get("sha256"), probe.get("error"))))
    facts["manifest_status"] = manifest["status"]
    facts["manifest_error"] = manifest["error"]
    return out, facts


def print_outcomes(outcomes):
    for o in outcomes:
        print("  %-4s %-9s %s" % (o["id"], o["outcome"], o["detail"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage1", type=Path)
    parser.add_argument("--stage2", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    pred = load_predictions()
    outcomes, evidence = [], {"predictions_sha256": c.sha256(c.PREDICTIONS.read_bytes())}
    if args.stage1:
        snapshot = json.loads((args.stage1 / "ptp_snapshot.json").read_text(encoding="utf-8"))
        o, facts = evaluate_stage1(snapshot, pred)
        outcomes += o
        evidence["stage1"] = facts
        evidence["stage1_session"] = args.stage1.name
    if args.stage2:
        o, facts = evaluate_stage2(args.stage2, pred)
        outcomes += o
        evidence["stage2"] = facts
        evidence["stage2_session"] = args.stage2.name
    seen = {o["id"] for o in outcomes}
    outcomes += [{"id": p["id"], "outcome": NOT_RUN, "detail": ""} for p in pred["predictions"] if p["id"] not in seen]
    outcomes.sort(key=lambda o: int(o["id"][1:]))
    evidence["outcomes"] = outcomes
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(evidence, indent=1) + "\n", encoding="utf-8")
    print_outcomes(outcomes)
    print("Written: %s" % (args.out / "results.json"))


if __name__ == "__main__":
    main()
