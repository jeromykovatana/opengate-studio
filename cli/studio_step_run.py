#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Multi-body CT6 volatile RAM step runner for OpenGate Studio (zve1_202, a7s3_501, fx3_702)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
KITS_DIR = REPO_ROOT / "kits"
SRC_DIR = REPO_ROOT / "src"
CT1_DIR = REPO_ROOT / "transport" / "camera_tests" / "CT1_usb_first_contact"
CT6_DIR = REPO_ROOT / "transport" / "camera_tests" / "CT6_memory_read_check"

for _p in (CT1_DIR, CT6_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ct1_common as c  # noqa: E402
import ct1_sim  # noqa: E402
import ct6_level1_run as R  # noqa: E402

BODY_CONFIG: dict[str, dict[str, str]] = {
    "zve1_202": {
        "prefix": "zv",
        "model": "ZV-E1",
        "header_model": "ZV-E1",
        "reader": "zvread",
        "firmware": "2.02",
        "expected_json": "zv_expected.json",
        "report_name": "zv_report.txt",
        "power_switch_note": (
            "This was a WRITE step. A cold boot (battery out for 10 seconds) undoes everything written. "
            "On the ZV-E1 the power switch undoes only part of it (the encoder side stays): keep the camera on between steps."
        ),
    },
    "a7s3_501": {
        "prefix": "s3",
        "model": "ILCE-7SM3",
        "header_model": "ILCE-7SM3",
        "reader": "s3read",
        "firmware": "5.01",
        "expected_json": "s3_expected.json",
        "report_name": "s3_report.txt",
        "power_switch_note": (
            "This was a WRITE step. A cold boot (battery out for 10 seconds) undoes everything written. "
            "On the a7S III (5.01), toggling the power switch resets coprocessor RAM while retaining encoder patches: always pull the battery >= 10s to restore stock, and keep the camera on between steps."
        ),
    },
    "fx3_702": {
        "prefix": "fx3",
        "model": "ILME-FX3",
        "header_model": "ILME-FX3",
        "reader": "fx3read",
        "firmware": "7.02",
        "expected_json": "fx3_expected.json",
        "report_name": "fx3_report.txt",
        "power_switch_note": (
            "This was a WRITE step. A cold boot (battery out for 10 seconds) undoes everything written. "
            "On the FX3 / a7S III coprocessor software the power switch may clear only part of it: keep the camera on between steps, and pull the battery >= 10s to restore stock."
        ),
    },
}

STEP_LEVEL_BASE: dict[str, int] = {
    "L": 200,
    "S": 300,
    "C": 400,
    "M": 500,
    "V": 600,
    "H": 700,
    "B": 800,
    "I": 900,
    "P": 1000,
}

# Active context configured by use()
CURRENT_BODY: str = "zve1_202"
CURRENT_WHICH: str = "check"
CURRENT_KIT_DIR: Path = KITS_DIR / "zve1_202"
CURRENT_MANIFEST: dict[str, Any] = {}
CURRENT_EXPECTED: dict[str, Any] = {}
CURRENT_WRITE_STEPS: dict[str, tuple[str, str, str]] = {}


def private_root() -> Path:
    return Path(os.environ.get("OPENGATE_CAMERA_PRIVATE") or c.PRIVATE_ROOT)


def load_body_manifest(body_id: str) -> tuple[Path, dict[str, Any]]:
    if body_id not in BODY_CONFIG:
        raise ValueError(f"Unsupported body_id: {body_id!r}")
    kit_dir = KITS_DIR / body_id
    man_path = kit_dir / "manifest.json"
    if not man_path.is_file():
        raise FileNotFoundError(f"Missing manifest: {man_path}")
    return kit_dir, json.loads(man_path.read_text(encoding="utf8"))


def load_body_expected(body_id: str) -> dict[str, Any]:
    cfg = BODY_CONFIG[body_id]
    exp_path = SRC_DIR / body_id / cfg["expected_json"]
    if not exp_path.is_file():
        raise FileNotFoundError(f"Missing expected JSON: {exp_path}")
    return json.loads(exp_path.read_text(encoding="utf8"))


def step_level(which: str) -> int:
    if which == "check":
        return 101
    if which == "dump":
        return 102
    if len(which) < 2 or which[0] not in STEP_LEVEL_BASE or not which[1:].isdigit():
        raise ValueError(f"Unsupported step name: {which!r}")
    return STEP_LEVEL_BASE[which[0]] + int(which[1:])


def step_pins(manifest: dict[str, Any]) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str, str]]]:
    pins: dict[str, tuple[str, str]] = {}
    for k in ("check", "dump"):
        entry = manifest.get("readonly", {}).get(k)
        if isinstance(entry, dict):
            pins[k] = (entry["file"], entry["sha256"])
    write_steps: dict[str, tuple[str, str, str]] = {}
    for k, entry in manifest.get("steps", {}).items():
        pins[k] = (entry["file"], entry["sha256"])
        write_steps[k] = (entry["file"], entry["sha256"], entry.get("summary", k))
    return pins, write_steps


def parse_write_result(which: str, what: str, data: bytes) -> dict[str, Any]:
    text = data.decode("utf8", "replace")
    lines = text.split("\n")
    pick = lambda start: next((ln for ln in lines if ln.startswith(start)), None)
    outcome = (
        "UNDO INCOMPLETE"
        if (pick("!! UNDO INCOMPLETE") or pick("UNDO INCOMPLETE"))
        else "DONE"
        if pick("DONE: ")
        else "NOTHING TO DO"
        if pick("NOTHING TO DO")
        else "NOT DONE (everything put back)"
        if pick("NOT DONE: ")
        else "NOTHING WRITTEN"
        if any("nothing is written" in ln for ln in lines)
        else "UNKNOWN"
    )
    problems = [ln for ln in lines if ln.startswith("!!")]
    header_ok = bool(lines) and lines[0].startswith(f"readcheck 1 level {which[1:]}")
    complete = any(ln.startswith("== done") for ln in lines[-3:])
    ok = outcome in ("DONE", "NOTHING TO DO") and header_ok and complete and not problems
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "header_ok": header_ok,
        "euid": "see the result",
        "sections": [ln for ln in lines if ln.startswith("== ")],
        "problems": len(problems),
        "complete": complete,
        "s3": {
            "step": which,
            "what": what,
            "outcome": outcome,
            "ok": ok,
            "outcome_line": (
                pick("DONE: ")
                or pick("NOTHING TO DO")
                or pick("NOT DONE: ")
                or pick("!! UNDO INCOMPLETE")
                or pick("UNDO INCOMPLETE")
            ),
            "problem_lines": problems,
        },
    }


def parse_readonly_result(
    body_id: str,
    which: str,
    data: bytes,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = BODY_CONFIG[body_id]
    if spec is None:
        spec = load_body_expected(body_id)
    fw = cfg["firmware"]
    text = data.decode("utf8", "replace")
    lines = text.split("\n")
    head = lines[0] if lines else ""
    expected_header = f"{cfg['reader']} {spec['label']} {which} for {cfg['header_model']} {fw}; read-only"
    header_ok = head == expected_header
    complete = "== done" in lines[-3:] and lines[-3:].count("== done") == 1
    problem_lines = [ln for ln in lines if ln.startswith("!!")]

    same_pat = re.compile(rf" sha256 ([0-9a-f]{{64}})  SAME as the {re.escape(fw)} update$", re.M)
    diff_pat = re.compile(rf"DIFFERS from the {re.escape(fw)} update$")
    same_hashes = same_pat.findall(text)
    identity_differs = sum(1 for ln in lines if diff_pat.search(ln))
    expected_id_hashes = [*spec["id_files"].values(), *spec["id_pages"].values()]
    identity_ok = identity_differs == 0 and sorted(same_hashes) == sorted(expected_id_hashes)

    pages: dict[int, tuple[str, bytes]] = {}
    for ln in lines:
        if ln.startswith("cppage "):
            _, name, addr, hx = ln.split(" ", 3)
            pages[int(addr, 16)] = (name, bytes.fromhex(hx.strip()))

    sites: list[dict[str, Any]] = []
    site_lines_count = 0
    for ln in lines:
        if ln.startswith("site "):
            site_lines_count += 1
            m = re.match(
                r"site (\S+) (0x[0-9a-f]+) len (\d+)(?: bytes (?:differing from stock )?(\S+))?  (STOCK|TARGET|OTHER.*|NOT READ)$",
                ln,
            )
            if m:
                sites.append({
                    "name": m.group(1),
                    "address": m.group(2),
                    "length": int(m.group(3)),
                    "shown": m.group(4),
                    "state": m.group(5),
                })

    cp_ok = len(sites) == site_lines_count == len(spec["cp_sites"])
    if cp_ok:
        expected_cp = {int(row["address"], 16): row for row in spec["cp_sites"]}
        for row in sites:
            want = expected_cp.pop(int(row["address"], 16), None)
            if not want or row["length"] != want["length"] or row["name"] != want["name"]:
                cp_ok = False
                break
            st = row["state"]
            is_fx3_screen = body_id == "fx3_702" and want["name"].startswith("screen")
            if not want["soft"] or is_fx3_screen:
                if st not in ("STOCK", "TARGET"):
                    cp_ok = False
                    break
            else:
                if st not in ("STOCK", "TARGET", "OTHER (not counted: filled at run time)"):
                    cp_ok = False
                    break
        if expected_cp:
            cp_ok = False

    lm_lines = [ln for ln in lines if ln.startswith("lm ")]
    av_lines = [ln for ln in lines if ln.startswith("av ")]
    lm_stock = sum(1 for ln in lm_lines if ln.endswith("  STOCK"))
    lm_target = sum(1 for ln in lm_lines if ln.endswith("  TARGET"))
    lm_other = len(lm_lines) - lm_stock - lm_target
    av_stock = sum(1 for ln in av_lines if ln.endswith("  STOCK"))
    av_target = sum(1 for ln in av_lines if ln.endswith("  TARGET"))
    av_other = len(av_lines) - av_stock - av_target
    mp_ok = (
        len(lm_lines) == spec["lm_sites"]
        and len(av_lines) == spec["av_sites"]
        and lm_other == 0
        and av_other == 0
    )

    guard_lines = [ln for ln in lines if ln.startswith("guard ")]
    same_guards = [ln.split()[1] for ln in guard_lines if ln.endswith("  SAME")]
    guards_ok = len(same_guards) == len(guard_lines) and sorted(same_guards) == sorted(spec["av_guards"])

    verdicts = [ln for ln in lines if ln.startswith("VERDICT ")]
    all_checks_ok = header_ok and complete and not problem_lines and identity_ok and cp_ok and mp_ok and guards_ok

    if all_checks_ok and verdicts == ["VERDICT READY (stock preflight)"]:
        ready, state, verdict = True, "stock", "VERDICT READY (stock preflight)"
    elif all_checks_ok and verdicts == ["VERDICT READY (open gate applied)"]:
        ready, state, verdict = True, "applied", "VERDICT READY (open gate applied)"
    else:
        ready, state, verdict = False, "not_ready", "VERDICT NOT READY"

    cmd = re.search(r"== file /proc/cmdline\n(.*?)\n== end", text, re.S)
    ver = re.search(r"== file /proc/version\n(.*?)\n== end", text, re.S)

    s3 = {
        "header": head,
        "verdict": verdict,
        "state": state,
        "ready": ready,
        "identity_same": len(same_hashes),
        "identity_differs": identity_differs,
        "coprocessor_sites": sites,
        "libmpr_sites": lm_lines,
        "avcam_stock": av_stock,
        "avcam_target": av_target,
        "avcam_other": av_other,
        "avcam_guards": guard_lines,
        "problem_lines": problem_lines,
        "pages": len(pages),
        "kernel_command_line": cmd.group(1).strip() if cmd else None,
        "kernel_version": ver.group(1).strip() if ver else None,
    }
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "header_ok": header_ok,
        "euid": "not read",
        "sections": [ln for ln in lines if ln.startswith("== ")],
        "problems": len(problem_lines),
        "complete": complete,
        "s3": s3,
        "_pages": pages,
    }


def check_result(data: bytes) -> dict[str, Any]:
    if CURRENT_WHICH in CURRENT_WRITE_STEPS:
        return parse_write_result(CURRENT_WHICH, CURRENT_WRITE_STEPS[CURRENT_WHICH][2], data)
    return parse_readonly_result(CURRENT_BODY, CURRENT_WHICH, data, CURRENT_EXPECTED)


def known_answer(session: Any, camera: Any) -> None:
    cfg = BODY_CONFIG[CURRENT_BODY]
    want = (CURRENT_KIT_DIR / "DeviceInfo.xml").read_bytes()
    dev_pin = CURRENT_MANIFEST.get("device_info", {})
    if isinstance(dev_pin, dict) and dev_pin.get("sha256"):
        if c.sha256(want) != dev_pin["sha256"]:
            raise c.StopTest("Kit DeviceInfo.xml SHA-256 mismatch; nothing sent")
    there, data = R.read(camera, R.KNOWN_PATH)
    if not there or data != want:
        detail = (
            "the camera returned no file"
            if not there
            else f"{len(data)} bytes, SHA-256 {c.sha256(data)[:16]}"
        )
        raise c.StopTest(
            f"DeviceInfo.xml is not the file of the {cfg['firmware']} update ({detail}); nothing else is sent"
        )
    session.say(f"Known-answer read: DeviceInfo.xml equals the {cfg['firmware']} file")


def run_helper(data: bytes) -> tuple[bytes, str]:
    del data
    if CURRENT_WHICH in CURRENT_WRITE_STEPS:
        lvl = CURRENT_WHICH[1:]
        text = (
            f"readcheck 1 level {lvl}\n"
            "euid 0\n"
            f"== level {lvl}\n"
            "DONE: every site holds the target bytes (canned)\n"
            "== done, bytes written before this line: 0\n"
        )
        return text.encode("utf8"), "canned"
    cfg = BODY_CONFIG[CURRENT_BODY]
    label = CURRENT_EXPECTED["label"]
    text = (
        f"{cfg['reader']} {label} {CURRENT_WHICH} for {cfg['header_model']} {cfg['firmware']}; read-only\n"
        "== file /proc/version\n"
        "Linux (simulated)\n\n"
        "== end 18 bytes\n"
        "== summary\n"
        "VERDICT NOT READY (simulated transport only)\n"
        "== done\n"
    )
    return text.encode("utf8"), "canned"


def make_sim(lib: bytes, files: dict[str, bytes] | None = None, fault: str | None = None) -> Any:
    dev_info = (CURRENT_KIT_DIR / "DeviceInfo.xml").read_bytes()

    class Sim(ct1_sim.SimDriver):
        def __init__(self) -> None:
            super().__init__("senser", rules=R.rules(lib))
            self.fs: dict[str, bytes] = {"/usr/share/pmbp/DeviceInfo.xml": dev_info}
            self.fs.update(files or {})
            self.loads = 0
            self.how: str | None = None
            self.dead = False

        def write(self, data: bytes, ep: int = 0) -> Any:
            if self.dead:
                raise ct1_sim.SimUsbError("the simulated camera no longer answers")
            return super().write(data, ep)

        def _handle(self, pfunc: int, body: bytes) -> tuple[int, bytes]:
            import posixpath
            import struct

            try:
                name = c.classify_service_packet(pfunc, body, self.rules)
            except c.GuardRefusal as exc:
                self.unexpected.append(("service packet", pfunc, body[:16].hex(), str(exc)))
                return 0xEE, b""
            st = lambda v: struct.pack("<I", v)
            if name == "SET_FILE_PATH":
                p = body[5:].decode()
                self._path = p if p.startswith("/tmp/jiritsu") else posixpath.normpath("/tmp/jiritsu/" + p)
                return 0, st(R.ST_OK)
            path, self._path = self._path, None
            if path is None:
                return 0, st(0x10000201)
            if name == "GET_FILE2":
                return (0, st(R.ST_OK) + self.fs[path]) if path in self.fs else (0, st(R.ST_NO_FILE))
            if name == "SET_FILE2":
                if body[4:7] != b"\x00\xff\x00":
                    return 0, st(0x10000201)
                if path == R.LIB_PATH.decode() and "/tmp/jbusy" in self.fs:
                    return 0, st(R.ST_BUSY)
                if fault == "dead":
                    self.dead = True
                    self.fs[path] = body[7:]
                    raise ct1_sim.SimUsbError("the simulated camera died during the write")
                self.fs[path] = body[7:]
                if path != R.LIB_PATH.decode():
                    return 0, st(R.ST_OK)
                if fault == "load":
                    return 0, st(R.ST_LOAD_FAILED)
                self.loads += 1
                if "/tmp_wbshd/readcheck_result.txt" not in self.fs:
                    self.fs["/tmp_wbshd/readcheck_result.txt"], self.how = R.run_helper(body[7:])
                return 0, st(R.ST_OK)
            if name == "FILE_DELETE2":
                if fault == "sticky" or path not in self.fs:
                    return 0, st(R.ST_REMOVE_FAILED)
                del self.fs[path]
                return 0, st(R.ST_OK)
            raise AssertionError(name)

    return Sim()


def use(body_id: str, which: str) -> bytes:
    global CURRENT_BODY, CURRENT_WHICH, CURRENT_KIT_DIR, CURRENT_MANIFEST, CURRENT_EXPECTED, CURRENT_WRITE_STEPS
    kit_dir, manifest = load_body_manifest(body_id)
    expected = load_body_expected(body_id)
    pins, write_steps = step_pins(manifest)
    if which not in pins:
        raise SystemExit(f"{which!r} is not a valid step for {body_id}. Choices: {sorted(pins)}")

    CURRENT_BODY = body_id
    CURRENT_WHICH = which
    CURRENT_KIT_DIR = kit_dir
    CURRENT_MANIFEST = manifest
    CURRENT_EXPECTED = expected
    CURRENT_WRITE_STEPS = write_steps

    name, sha = pins[which]
    lib_path = kit_dir / name
    if not lib_path.is_file():
        raise SystemExit(f"{lib_path} is missing. Nothing was sent.")

    R.LEVEL = step_level(which)
    R.DESIGN = body_id
    R.LIB = lib_path
    R.LIB_SHA256 = sha
    R.check_result = check_result
    R.known_answer = known_answer
    R.run_helper = run_helper
    R.make_sim = make_sim
    c.EXPECTED_FIRMWARE = BODY_CONFIG[body_id]["firmware"]
    c.PRIVATE_ROOT = private_root()
    return R.library()


def selftest(lib: bytes) -> list[str]:
    done: list[str] = []

    def check(cond: bool, what: str) -> None:
        if not cond:
            raise AssertionError("self-test failed: " + what)
        done.append(what)

    w_cmd, d_cmd = "SET_FILE2", "FILE_DELETE2"
    s, sim, stopped = R.simulate(lib, R.body_run)
    r = s.results.get("ct6", {})
    check(
        not stopped and not sim.unexpected and R.sent(s).count(w_cmd) == 1 and R.sent(s).count(d_cmd) == 1,
        "normal run: one write, one delete, nothing off the list",
    )
    check(
        R.sent(s).index(d_cmd) < len(R.sent(s)) - 2 and R.sent(s)[-1] == "GET_FILE2",
        "normal run: the delete comes before the result is read",
    )
    check(
        R.LIB_PATH.decode() not in sim.fs and sim.loads == 1,
        "normal run: the library was loaded once and is gone afterwards",
    )
    f = r.get("result", {}).get("s3", {})
    if CURRENT_WHICH in CURRENT_WRITE_STEPS:
        check(bool(f.get("ok")) and bool(r["result"]["header_ok"]), "normal run: the step's result is read as DONE")
    else:
        check(not f.get("ready"), "canned transport result has no measured sites and cannot certify READY")

    s, sim, stopped = R.simulate(lib, R.body_run, files={R.LIB_PATH.decode(): b"someone else's"})
    check(stopped and w_cmd not in R.sent(s) and d_cmd not in R.sent(s), "foreign libJit.so: stops, nothing written or deleted")
    s, sim, stopped = R.simulate(lib, R.body_run, files={"/tmp_wbshd/readcheck_result.txt": b"old"})
    check(stopped and w_cmd not in R.sent(s), "existing result on RAM disk: stops, nothing written")
    s, sim, stopped = R.simulate(lib, R.body_run, files={"/tmp/jbusy": b""})
    check(stopped and w_cmd not in R.sent(s), "/tmp/jbusy present: stops, nothing written")
    s, sim, stopped = R.simulate(lib, R.body_run, files={"/usr/share/pmbp/DeviceInfo.xml": b"<other camera/>"})
    check(stopped and len(R.sent(s)) == 2, "wrong DeviceInfo.xml: stops after known-answer read")
    s, sim, stopped = R.simulate(lib, R.body_run, fault="load")
    check(stopped and R.sent(s).count(d_cmd) == 1 and R.LIB_PATH.decode() not in sim.fs, "load failure: library still deleted")
    refused = R.refusals(lib)
    check(len(refused) == 15, "guard refuses all 15 forbidden packet classes")
    return done


def report(session: Any, facts: dict[str, Any], which: str) -> None:
    cfg = BODY_CONFIG[CURRENT_BODY]
    f = facts["s3"]
    if which in CURRENT_WRITE_STEPS:
        lines = [
            f"{cfg['model']} {cfg['firmware']} step {which}: {f['what']}",
            f"OUTCOME: {f['outcome']}",
            str(f["outcome_line"]),
            *["  " + ln for ln in f["problem_lines"]],
        ]
    else:
        lines = [
            f"{cfg['model']} {cfg['firmware']} {which}, {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f["header"],
            f["verdict"],
            f"identity: {f['identity_same']} same, {f['identity_differs']} differ",
            f"kernel: {f['kernel_version']}",
            f"command line: {f['kernel_command_line']}",
            *[
                f"  coprocessor {s['name']:<16s} {s['address']} len {s['length']:<4d} {s['state']}"
                + ("" if s["shown"] is None else f"  ({s['shown']})")
                for s in f["coprocessor_sites"]
            ],
            *["  " + ln for ln in f["libmpr_sites"]],
            *["  " + ln for ln in f["avcam_guards"]],
            f"  av-cam.bin sites: {f['avcam_stock']} stock, {f['avcam_target']} target, {f['avcam_other']} other",
            *(["problem lines:", *["  " + ln for ln in f["problem_lines"]]] if f["problem_lines"] else ["no problem lines"]),
        ]
    session.save_bytes(cfg["report_name"], ("\n".join(lines) + "\n").encode("utf8"))
    for ln in lines[:8] + (lines[-6:] if len(lines) > 8 else []):
        session.say(ln)


def last_saved_sha() -> str | None:
    root = private_root()
    if not root.is_dir():
        return None
    for folder in sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith("CT6_")), reverse=True):
        try:
            return json.loads((folder / "manifest.json").read_text(encoding="utf8"))["results"]["ct6"]["result"]["sha256"]
        except (OSError, KeyError, TypeError, ValueError):
            continue
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--body", required=True, choices=tuple(BODY_CONFIG))
    ap.add_argument("which", help="check, dump, or a write step id from manifest.json (e.g. V19, H16, B19, I19, P29)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--remove-only", action="store_true")
    ap.add_argument("--clear-result", metavar="SHA256")
    ap.add_argument("--firmware-shown")
    ap.add_argument("--writes-memory", action="store_true")
    args = ap.parse_args(argv)

    cfg = BODY_CONFIG[args.body]
    lib = use(args.body, args.which)

    if args.which in CURRENT_WRITE_STEPS and args.go and not (args.dry_run or args.selftest) and not args.writes_memory:
        raise SystemExit(
            f"{args.which} is a write step ({CURRENT_WRITE_STEPS[args.which][2]}). "
            "It needs --writes-memory as well. Use studio_live_apply.py. Nothing was sent."
        )

    if args.dry_run or args.selftest:
        if args.selftest:
            for line in selftest(lib):
                print("PASS  " + line)
            print(f"all checks passed for {args.body} {args.which}; nothing was sent to any device")
        else:
            print("\n".join(R.dry_run_lines(lib)))
        return 0

    if not args.go or args.firmware_shown != cfg["firmware"]:
        raise SystemExit(
            f"A live run needs --go and --firmware-shown {cfg['firmware']} "
            "(the version shown on the camera's menu). Nothing was sent."
        )

    R.refusals(lib)
    selftest(lib)

    import ct1_stage2_service as service

    R.CLEAR_SHA = args.clear_result or last_saved_sha()
    body_fn = R.body_remove_only if args.remove_only else R.body_run
    stage_name = "remove_only" if args.remove_only else f"{cfg['prefix']}_{args.which}"
    with c.Session(stage_name, test="CT6", root=private_root()) as session:
        session.results.update(
            body_id=args.body,
            firmware_shown_on_camera=args.firmware_shown,
            model=cfg["model"],
            which=args.which,
            library_sha256=R.LIB_SHA256,
            pc={"platform": platform.platform(), "python": sys.version.split()[0]},
        )
        inner = service.connect(session)
        try:
            R.service_session(session, inner, lambda cam: body_fn(session, cam, lib), lib)
            facts = session.results.get("ct6", {}).get("result")
            if facts and not args.remove_only:
                pages = facts.pop("_pages", {})
                for addr, (name, blob) in sorted(pages.items()):
                    session.save_bytes(f"cp_{name}_{addr:08x}.bin", blob)
                report(session, facts, args.which)
        finally:
            time.sleep(3)
            c.print_pnp(session, "after the stop request")
            out = session.results.get("ct6", {})
            after_map = {
                False: "no (confirmed)",
                True: "YES",
                None: "not sent" if not out.get("library_sent") and not args.remove_only else "UNKNOWN",
            }
            print(
                f"Library sent: {'yes' if out.get('library_sent') else 'no'}. "
                f"On the camera now: {after_map[out.get('library_on_camera_after')]}."
            )
            if args.which in CURRENT_WRITE_STEPS:
                print(cfg["power_switch_note"])
            else:
                print(
                    "Nothing on the camera was changed. Unplug and replug the USB cable before another run; "
                    "a cold boot (battery out) clears the result file."
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
