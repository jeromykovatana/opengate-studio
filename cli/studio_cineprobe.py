#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Parser and A/B diff analyzer for read-only CT6 cineprobe results."""
from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"

PROBE_BODY_META: dict[str, dict[str, str]] = {
    "zve1_202": {
        "reader": "zvread",
        "header_model": "ZV-E1",
        "firmware": "2.02",
        "expected_json": "zv_expected.json",
        "appfw_sha256": "88146fa5f5844b45de9f20ab5f1750aa6e821e10658af37f88ce7d4d76a833f8",
    },
    "fx3_702": {
        "reader": "fx3read",
        "header_model": "ILME-FX3",
        "firmware": "7.02",
        "expected_json": "fx3_expected.json",
        "appfw_sha256": "545c5053a74e04ffbf2bbaaf80f558092dd545ed2298b2395ca547dbba58290f",
    },
    "a7s3_501": {
        "reader": "s3read",
        "header_model": "ILCE-7SM3",
        "firmware": "5.01",
        "expected_json": "s3_expected.json",
        "appfw_sha256": "eba89299273542e9de89d64f3bd380114b2b9df67a246a6927cd7a83f2043781",
    },
}

_BENIGN_DIAG_SECTION_PREFIXES = (
    "== dir /proc/driver/pcie",
    "== file /proc/driver/pcie/",
    "== dir /sys/module/liro/parameters",
    "== file /sys/module/liro/parameters/",
    "== dir /log",
    "== file /log/",
)
_BENIGN_DIAG_BANG_RE = re.compile(
    r"^!! (?:read failed -21|open failed -\d+|truncated at \d+ bytes)$"
)


def _partition_problem_lines(lines: list[str]) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    diag_problems: list[str] = []
    current_section = ""
    in_action_area = False
    for ln in lines:
        if ln.startswith("== "):
            current_section = ln
            if ln.startswith((
                "== level ",
                "== identity:",
                "== coprocessor",
                "== main-processor",
                "== cineprobe:",
                "== summary",
            )):
                in_action_area = True
        elif ln.startswith("!!"):
            if (
                not in_action_area
                and current_section.startswith(_BENIGN_DIAG_SECTION_PREFIXES)
                and _BENIGN_DIAG_BANG_RE.match(ln)
            ):
                diag_problems.append(ln)
            else:
                problems.append(ln)
    return problems, diag_problems


def detect_cineprobe_body(data: bytes) -> str | None:
    head = data.split(b"\n", 1)[0].decode("utf8", "replace").strip()
    for bid, meta in PROBE_BODY_META.items():
        want = f"{meta['reader']} cineprobe_v1 cineprobe for {meta['header_model']} {meta['firmware']}; read-only"
        if head == want:
            return bid
    return None


def _load_expected_json(body_id: str) -> dict[str, Any]:
    import json

    meta = PROBE_BODY_META[body_id]
    p = SRC_DIR / body_id / meta["expected_json"]
    return json.loads(p.read_text(encoding="utf8"))


def parse_cineprobe_report(
    body_id: str | None,
    data: bytes,
    expected_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if body_id is None:
        body_id = detect_cineprobe_body(data)
    if body_id is None or body_id not in PROBE_BODY_META:
        raise ValueError(f"Unsupported or unrecognized cineprobe body_id: {body_id!r}")

    meta = PROBE_BODY_META[body_id]
    if expected_spec is None:
        expected_spec = _load_expected_json(body_id)

    fw = meta["firmware"]
    text = data.decode("utf8", "replace")
    lines = text.split("\n")
    head = lines[0] if lines else ""
    expected_header = f"{meta['reader']} cineprobe_v1 cineprobe for {meta['header_model']} {fw}; read-only"
    header_ok = head == expected_header
    complete = "== done" in lines[-3:] and lines[-3:].count("== done") == 1
    problem_lines, diag_problems = _partition_problem_lines(lines)

    same_pat = re.compile(rf" sha256 ([0-9a-f]{{64}})  SAME as the {re.escape(fw)} update$", re.M)
    diff_pat = re.compile(rf"DIFFERS from the {re.escape(fw)} update$")
    same_hashes = same_pat.findall(text)
    identity_differs = sum(1 for ln in lines if diff_pat.search(ln))

    expected_id_hashes = [
        meta["appfw_sha256"],
        *expected_spec["id_files"].values(),
        *expected_spec["id_pages"].values(),
    ]
    identity_ok = identity_differs == 0 and sorted(same_hashes) == sorted(expected_id_hashes)

    phdrs: list[dict[str, Any]] = []
    vmas: list[dict[str, Any]] = []
    dynsym_matches: list[dict[str, Any]] = []
    sym_code: dict[str, str] = {}
    ro_strings: list[dict[str, str]] = []
    xrefs: list[dict[str, str]] = []
    xref_ram: dict[str, dict[str, Any]] = {}
    targeted_windows: dict[str, dict[str, Any]] = {}
    rw_pages: dict[str, str] = {}
    cp_pages: dict[int, dict[str, Any]] = {}

    for ln in lines:
        if ln.startswith("phdr "):
            m = re.match(
                r"phdr idx (\d+) type (\d+) flags (0x[0-9a-f]+) off (0x[0-9a-f]+) va (0x[0-9a-f]+) filesz (0x[0-9a-f]+) memsz (0x[0-9a-f]+)$",
                ln,
            )
            if m:
                phdrs.append({
                    "idx": int(m.group(1)),
                    "type": int(m.group(2)),
                    "flags": m.group(3),
                    "off": m.group(4),
                    "va": m.group(5),
                    "filesz": m.group(6),
                    "memsz": m.group(7),
                })
        elif ln.startswith("vma "):
            m = re.match(r"vma (0x[0-9a-f]+)-(0x[0-9a-f]+) (\S{4}) foff (0x[0-9a-f]+) (.+)$", ln)
            if m:
                vmas.append({
                    "start": m.group(1),
                    "end": m.group(2),
                    "perms": m.group(3),
                    "foff": m.group(4),
                    "name": m.group(5),
                })
        elif ln.startswith("sym "):
            m = re.match(r"sym (0x[0-9a-f]+) (\d+) (0x[0-9a-f]+) (\d+) (.+)$", ln)
            if m:
                dynsym_matches.append({
                    "va": m.group(1),
                    "size": int(m.group(2)),
                    "info": m.group(3),
                    "shndx": int(m.group(4)),
                    "name": m.group(5),
                })
        elif ln.startswith("sym_code "):
            m = re.match(r"sym_code (0x[0-9a-f]+) ([0-9a-f]+)$", ln)
            if m:
                sym_code[m.group(1)] = m.group(2)
        elif ln.startswith("str "):
            m = re.match(r"str (0x[0-9a-f]+) (.+)$", ln)
            if m:
                ro_strings.append({"va": m.group(1), "text": m.group(2)})
        elif ln.startswith("xref "):
            m = re.match(r"xref target=(0x[0-9a-f]+) pc=(0x[0-9a-f]+) win_va=(0x[0-9a-f]+) hex=([0-9a-f]+)$", ln)
            if m:
                xrefs.append({
                    "target": m.group(1),
                    "pc": m.group(2),
                    "win_va": m.group(3),
                    "hex": m.group(4),
                })
        elif ln.startswith("xref_ram "):
            m = re.match(r"xref_ram va=(0x[0-9a-f]+) aligned=(0x[0-9a-f]+) from_pc=(0x[0-9a-f]+) hex=([0-9a-f]+)$", ln)
            if m:
                xref_ram[m.group(1)] = {
                    "va": m.group(1),
                    "aligned": m.group(2),
                    "from_pc": m.group(3),
                    "hex": m.group(4),
                }
            else:
                m2 = re.match(r"xref_ram va=(0x[0-9a-f]+) from_pc=(0x[0-9a-f]+) UNMAPPED$", ln)
                if m2:
                    xref_ram[m2.group(1)] = {
                        "va": m2.group(1),
                        "from_pc": m2.group(2),
                        "unmapped": True,
                    }
        elif ln.startswith("win "):
            m = re.match(r"win (\S+) (0x[0-9a-f]+) len (\d+) (?:hex ([0-9a-f]+)|UNMAPPED)$", ln)
            if m:
                targeted_windows[m.group(1)] = {
                    "name": m.group(1),
                    "va": m.group(2),
                    "len": int(m.group(3)),
                    "hex": m.group(4),
                    "unmapped": m.group(4) is None,
                }
        elif ln.startswith("rwpage "):
            m = re.match(r"rwpage (0x[0-9a-f]+) ([0-9a-f]{16})$", ln)
            if m:
                rw_pages[m.group(1)] = m.group(2)
        elif ln.startswith("cppage "):
            parts = ln.split(" ", 3)
            if len(parts) == 4:
                _, cname, caddr_str, chx = parts
                caddr = int(caddr_str, 16)
                cp_pages[caddr] = {"name": cname, "address": caddr_str, "hex": chx.strip()}

    verdicts = [ln for ln in lines if ln.startswith("VERDICT ")]
    probe_ok = (
        header_ok
        and complete
        and not problem_lines
        and identity_ok
        and verdicts == ["VERDICT CINEPROBE COMPLETE (read-only)"]
    )
    verdict = "VERDICT CINEPROBE COMPLETE (read-only)" if probe_ok else "VERDICT NOT READY"
    state = "cineprobe_complete" if probe_ok else "cineprobe_failed"

    cmd = re.search(r"== file /proc/cmdline\n(.*?)\n== end", text, re.S)
    ver = re.search(r"== file /proc/version\n(.*?)\n== end", text, re.S)

    probe_summary = {
        "body_id": body_id,
        "phdrs": len(phdrs),
        "vmas": len(vmas),
        "dynsym_matches": len(dynsym_matches),
        "sym_code_samples": len(sym_code),
        "ro_strings": len(ro_strings),
        "xrefs": len(xrefs),
        "xref_ram_blocks": len(xref_ram),
        "targeted_windows": len(targeted_windows),
        "rw_nonzero_pages": len(rw_pages),
        "cp_pages": len(cp_pages),
    }

    s3 = {
        "header": head,
        "verdict": verdict,
        "state": state,
        "ready": False,
        "probe_ok": probe_ok,
        "identity_same": len(same_hashes),
        "identity_differs": identity_differs,
        "problem_lines": problem_lines,
        "diagnostic_problem_lines": diag_problems,
        "pages": len(cp_pages),
        "kernel_command_line": cmd.group(1).strip() if cmd else None,
        "kernel_version": ver.group(1).strip() if ver else None,
        "cineprobe": probe_summary,
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
        "_cineprobe_data": {
            "body_id": body_id,
            "phdrs": phdrs,
            "vmas": vmas,
            "dynsym_matches": dynsym_matches,
            "sym_code": sym_code,
            "ro_strings": ro_strings,
            "xrefs": xrefs,
            "xref_ram": xref_ram,
            "targeted_windows": targeted_windows,
            "rw_pages": rw_pages,
            "cp_pages": cp_pages,
        },
    }


def _diff_hex_words(base_va: int, hex_a: str, hex_b: str) -> list[dict[str, Any]]:
    raw_a = bytes.fromhex(hex_a)
    raw_b = bytes.fromhex(hex_b)
    n = min(len(raw_a), len(raw_b))
    word_diffs: list[dict[str, Any]] = []
    for off in range(0, n - (n % 4), 4):
        wa = raw_a[off : off + 4]
        wb = raw_b[off : off + 4]
        if wa != wb:
            va = base_va + off
            word_diffs.append({
                "offset": f"0x{off:x}",
                "word_va": f"0x{va:x}",
                "old_u32": f"0x{struct.unpack('<I', wa)[0]:08x}",
                "new_u32": f"0x{struct.unpack('<I', wb)[0]:08x}",
                "old_hex": wa.hex(),
                "new_hex": wb.hex(),
            })
    if n % 4 != 0:
        tail_off = n - (n % 4)
        ta = raw_a[tail_off:n]
        tb = raw_b[tail_off:n]
        if ta != tb:
            word_diffs.append({
                "offset": f"0x{tail_off:x}",
                "word_va": f"0x{base_va + tail_off:x}",
                "old_hex": ta.hex(),
                "new_hex": tb.hex(),
            })
    return word_diffs


def _extract_kprint_lines(cp_pages: dict[int, dict[str, Any]]) -> list[str]:
    kpages = sorted((addr, info) for addr, info in cp_pages.items() if info.get("name") == "kprint_tail")
    if not kpages:
        return []
    blob = b"".join(bytes.fromhex(info["hex"]) for _, info in kpages)
    text = blob.replace(b"\x00", b"\n").decode("ascii", "replace")
    lines: list[str] = []
    for raw_ln in text.splitlines():
        cleaned = "".join(ch for ch in raw_ln if 0x20 <= ord(ch) < 0x7F).strip()
        if len(cleaned) >= 4:
            lines.append(cleaned)
    return lines


def diff_cineprobe_reports(
    data_a: bytes,
    data_b: bytes,
    body_id: str | None = None,
) -> dict[str, Any]:
    parsed_a = parse_cineprobe_report(body_id, data_a)
    parsed_b = parse_cineprobe_report(body_id, data_b)
    da = parsed_a["_cineprobe_data"]
    db = parsed_b["_cineprobe_data"]

    if da["body_id"] != db["body_id"]:
        raise ValueError(f"Cannot diff reports from different bodies: {da['body_id']} vs {db['body_id']}")

    bid = da["body_id"]

    # 1. RW page hash diffs
    rw_a: dict[str, str] = da["rw_pages"]
    rw_b: dict[str, str] = db["rw_pages"]
    all_rw = sorted(set(rw_a) | set(rw_b), key=lambda x: int(x, 16))
    changed_rw_pages: list[dict[str, Any]] = []
    for rel_va in all_rw:
        ha = rw_a.get(rel_va)
        hb = rw_b.get(rel_va)
        if ha != hb:
            status = "changed" if (ha is not None and hb is not None) else ("added" if ha is None else "removed")
            changed_rw_pages.append({
                "rel_va": rel_va,
                "hash_a": ha,
                "hash_b": hb,
                "status": status,
            })

    # 2. Targeted window diffs
    win_diffs: list[dict[str, Any]] = []
    for name, wa in da["targeted_windows"].items():
        wb = db["targeted_windows"].get(name)
        if not wb or wa.get("unmapped") or wb.get("unmapped"):
            continue
        if wa["hex"] != wb["hex"]:
            wdiffs = _diff_hex_words(int(wa["va"], 16), wa["hex"], wb["hex"])
            if wdiffs:
                win_diffs.append({
                    "name": name,
                    "va": wa["va"],
                    "word_diffs": wdiffs,
                })

    # 3. xref_ram block diffs
    ram_diffs: list[dict[str, Any]] = []
    for va_key, ra in da["xref_ram"].items():
        rb = db["xref_ram"].get(va_key)
        if not rb or ra.get("unmapped") or rb.get("unmapped"):
            continue
        if ra["hex"] != rb["hex"]:
            base = int(ra.get("aligned") or ra["va"], 16)
            wdiffs = _diff_hex_words(base, ra["hex"], rb["hex"])
            if wdiffs:
                ram_diffs.append({
                    "va": va_key,
                    "aligned": ra.get("aligned"),
                    "from_pc": ra.get("from_pc"),
                    "word_diffs": wdiffs,
                })

    # 4. Coprocessor state diffs (exclude noisy kprint_tail)
    cp_diffs: list[dict[str, Any]] = []
    for addr, ca in sorted(da["cp_pages"].items()):
        if ca.get("name") == "kprint_tail":
            continue
        cb = db["cp_pages"].get(addr)
        if not cb:
            continue
        if ca["hex"] != cb["hex"]:
            wdiffs = _diff_hex_words(addr, ca["hex"], cb["hex"])
            if wdiffs:
                cp_diffs.append({
                    "name": ca["name"],
                    "address": ca["address"],
                    "word_diffs": wdiffs,
                })

    # 5. kprint_tail new lines
    kp_a = set(_extract_kprint_lines(da["cp_pages"]))
    kp_b = _extract_kprint_lines(db["cp_pages"])
    kprint_new_lines = [ln for ln in kp_b if ln not in kp_a]

    return {
        "ok": parsed_a["s3"]["probe_ok"] and parsed_b["s3"]["probe_ok"],
        "body_id": bid,
        "report_a_probe_ok": parsed_a["s3"]["probe_ok"],
        "report_b_probe_ok": parsed_b["s3"]["probe_ok"],
        "changed_rw_pages_count": len(changed_rw_pages),
        "changed_rw_pages": changed_rw_pages,
        "targeted_window_diffs": win_diffs,
        "xref_ram_diffs": ram_diffs,
        "coprocessor_diffs": cp_diffs,
        "kprint_new_lines": kprint_new_lines,
    }


def summarize_cineprobe(parsed: dict[str, Any]) -> dict[str, Any]:
    s3 = parsed["s3"]
    data = parsed["_cineprobe_data"]
    return {
        "ok": s3["probe_ok"],
        "body_id": data["body_id"],
        "verdict": s3["verdict"],
        "state": s3["state"],
        "ready": s3["ready"],
        "summary": s3["cineprobe"],
        "phdrs": data["phdrs"],
        "ro_strings": data["ro_strings"],
        "dynsym_sample": data["dynsym_matches"][:50],
        "xrefs_count": len(data["xrefs"]),
        "xref_ram_blocks": list(data["xref_ram"].values()),
        "targeted_windows": {
            k: {
                "va": v["va"],
                "len": v["len"],
                "unmapped": v["unmapped"],
                "all_zero": (not v["unmapped"]) and set(v["hex"]) == {"0"},
            }
            for k, v in data["targeted_windows"].items()
        },
        "problems": s3["problem_lines"],
    }
