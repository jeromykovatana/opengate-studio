#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline unit tests for clean-room CT6 cineprobe parser, A/B differ, runner, and CLI."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_DIR = REPO_ROOT / "cli"
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

import studio_cineprobe  # noqa: E402
import studio_live_apply  # noqa: E402
import studio_step_run  # noqa: E402


def _make_synthetic_cineprobe_report(
    body_id: str,
    *,
    rw_page_hash: str = "1122334455667788",
    win_hex: str = "0100000002000000",
    xref_ram_hex: str = "1000000020000000",
    cp_shadow_hex: str = "aaaaaaaa01000000",
    kprint_ascii: str = "cineprobe_kprint_a",
    tamper_identity: bool = False,
    add_problem: bool = False,
) -> bytes:
    meta = studio_cineprobe.PROBE_BODY_META[body_id]
    spec = studio_cineprobe._load_expected_json(body_id)
    fw = meta["firmware"]
    win_name = "shadow"
    win_va = "0x20100000"

    lines = [
        f"{meta['reader']} cineprobe_v1 cineprobe for {meta['header_model']} {fw}; read-only",
        "== file /proc/cmdline",
        "console=ttyAMA0,115200",
        "== end",
        "== file /proc/version",
        "Linux version 4.19.0",
        "== end",
        f"== dir /proc/driver/pcie",
        "!! open failed -2",
        "== identity: files",
    ]
    app_sha = "0" * 64 if tamper_identity else meta["appfw_sha256"]
    app_status = f"DIFFERS from the {fw} update" if tamper_identity else f"SAME as the {fw} update"
    lines.append(f"/appFw.so sha256 {app_sha}  {app_status}")
    for path, sha in spec["id_files"].items():
        lines.append(f"{path} sha256 {sha}  SAME as the {fw} update")
    lines.append("== identity: pages")
    for p_name, sha in spec["id_pages"].items():
        lines.append(f"{p_name} sha256 {sha}  SAME as the {fw} update")

    kprint_padded = kprint_ascii.encode("ascii").ljust(16, b"\x00").hex()
    lines.extend([
        "== cineprobe: phdrs",
        "phdr idx 0 type 1 flags 0x5 off 0x0 va 0x0 filesz 0x5000000 memsz 0x5000000",
        "phdr idx 1 type 1 flags 0x6 off 0x5000000 va 0x5000000 filesz 0x1000000 memsz 0x3000000",
        "== cineprobe: vmas",
        "vma 0x5000000-0x8000000 rw-p foff 0x5000000 [anon]",
        "== cineprobe: dynsym",
        "sym 0x1234560 64 0x12 10 update_big6_item_iso_ei",
        "sym_code 0x1234560 fd7bbba9",
        "== cineprobe: rodata",
        "str 0x4100000 MENU_SHUTTER_ANGLE",
        "xref target=0x4100000 pc=0x2000100 win_va=0x20000f0 hex=00000090",
        f"xref_ram va=0x7f7d8f8 aligned=0x7f7d8f8 from_pc=0x26c9d90 hex={xref_ram_hex}",
        "== cineprobe: windows",
        f"win {win_name} {win_va} len 8 hex {win_hex}",
        "== cineprobe: rwpages",
        f"rwpage 0x5001000 {rw_page_hash}",
        "== coprocessor pages",
        f"cppage shadow 0x20100000 {cp_shadow_hex}",
        f"cppage kprint_tail 0x20002800 {kprint_padded}",
    ])
    if add_problem:
        lines.append("!! probe mmap error -12")
    lines.extend([
        "VERDICT CINEPROBE COMPLETE (read-only)",
        "== done",
        "",
    ])
    return "\n".join(lines).encode("utf8")


class TestCineprobe(unittest.TestCase):
    BODIES = ("zve1_202", "fx3_702", "a7s3_501")

    def test_parse_valid_and_ready_always_false(self) -> None:
        for body_id in self.BODIES:
            with self.subTest(body_id=body_id):
                raw = _make_synthetic_cineprobe_report(body_id)
                self.assertEqual(studio_cineprobe.detect_cineprobe_body(raw), body_id)
                parsed = studio_cineprobe.parse_cineprobe_report(None, raw)
                s3 = parsed["s3"]
                self.assertTrue(parsed["header_ok"])
                self.assertTrue(parsed["complete"])
                self.assertEqual(parsed["problems"], 0)
                self.assertTrue(s3["probe_ok"])
                self.assertFalse(s3["ready"])
                self.assertEqual(s3["state"], "cineprobe_complete")
                self.assertEqual(s3["verdict"], "VERDICT CINEPROBE COMPLETE (read-only)")
                self.assertEqual(s3["cineprobe"]["targeted_windows"], 1)
                self.assertEqual(s3["cineprobe"]["rw_nonzero_pages"], 1)

    def test_parse_rejects_identity_differs_and_action_problem(self) -> None:
        tampered = _make_synthetic_cineprobe_report("fx3_702", tamper_identity=True)
        p1 = studio_cineprobe.parse_cineprobe_report("fx3_702", tampered)
        self.assertFalse(p1["s3"]["probe_ok"])
        self.assertFalse(p1["s3"]["ready"])
        self.assertEqual(p1["s3"]["identity_differs"], 1)

        errored = _make_synthetic_cineprobe_report("zve1_202", add_problem=True)
        p2 = studio_cineprobe.parse_cineprobe_report("zve1_202", errored)
        self.assertFalse(p2["s3"]["probe_ok"])
        self.assertFalse(p2["s3"]["ready"])
        self.assertEqual(p2["problems"], 1)

    def test_diff_cineprobe_reports(self) -> None:
        raw_a = _make_synthetic_cineprobe_report(
            "fx3_702",
            rw_page_hash="1122334455667788",
            win_hex="0100000002000000",
            xref_ram_hex="1000000020000000",
            cp_shadow_hex="aaaaaaaa01000000",
            kprint_ascii="mode=speed_iso800",
        )
        raw_b = _make_synthetic_cineprobe_report(
            "fx3_702",
            rw_page_hash="99aabbccddeeff00",
            win_hex="01000000b4000000",
            xref_ram_hex="1000000002000000",
            cp_shadow_hex="aaaaaaaa02000000",
            kprint_ascii="mode=angle_180_ei",
        )
        diff = studio_cineprobe.diff_cineprobe_reports(raw_a, raw_b)
        self.assertTrue(diff["ok"])
        self.assertEqual(diff["body_id"], "fx3_702")
        self.assertEqual(diff["changed_rw_pages_count"], 1)
        self.assertEqual(diff["changed_rw_pages"][0]["rel_va"], "0x5001000")
        self.assertEqual(len(diff["targeted_window_diffs"]), 1)
        self.assertEqual(diff["targeted_window_diffs"][0]["word_diffs"][0]["new_u32"], "0x000000b4")
        self.assertEqual(len(diff["xref_ram_diffs"]), 1)
        self.assertEqual(diff["xref_ram_diffs"][0]["word_diffs"][0]["word_va"], "0x7f7d8fc")
        self.assertEqual(len(diff["coprocessor_diffs"]), 1)
        self.assertEqual(diff["coprocessor_diffs"][0]["name"], "shadow")
        self.assertEqual(diff["kprint_new_lines"], ["mode=angle_180_ei"])

        # Identical kprint_tail lines produce no new kprint_new_lines and no coprocessor_diffs noise
        diff_same_cp = studio_cineprobe.diff_cineprobe_reports(raw_a, raw_a)
        self.assertEqual(diff_same_cp["changed_rw_pages_count"], 0)
        self.assertEqual(diff_same_cp["coprocessor_diffs"], [])
        self.assertEqual(diff_same_cp["kprint_new_lines"], [])

    def test_step_run_selftest_cineprobe(self) -> None:
        for body_id in self.BODIES:
            with self.subTest(body_id=body_id):
                lib = studio_step_run.use(body_id, "cineprobe")
                done = studio_step_run.selftest(lib)
                self.assertGreater(len(done), 10)
                parsed = studio_step_run.parse_readonly_result(
                    body_id,
                    "cineprobe",
                    _make_synthetic_cineprobe_report(body_id),
                )
                self.assertTrue(parsed["header_ok"])
                self.assertFalse(parsed["s3"]["ready"])
                self.assertTrue(parsed["s3"]["probe_ok"])

    def test_live_apply_dry_run_and_simulate_events(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            sess_dir = Path(td)
            for body_id in self.BODIES:
                with self.subTest(body_id=body_id):
                    rc = studio_live_apply.main([
                        "cineprobe",
                        "--body",
                        body_id,
                        "--session-dir",
                        str(sess_dir),
                        "--dry-run",
                    ])
                    self.assertEqual(rc, 0)

            ev_file = sess_dir / "events.jsonl"
            rc_ev = studio_live_apply.main([
                "cineprobe",
                "--body",
                "fx3_702",
                "--session-dir",
                str(sess_dir),
                "--dry-run",
                "--simulate-events",
                "--events-file",
                str(ev_file),
            ])
            self.assertEqual(rc_ev, 0)
            events = [json.loads(ln) for ln in ev_file.read_text(encoding="utf8").splitlines() if ln.strip()]
            completes = [ev for ev in events if ev.get("type") == "complete"]
            self.assertEqual(len(completes), 1)
            self.assertTrue(completes[0]["ok"])
            self.assertFalse(completes[0]["ready"])
            self.assertEqual(completes[0]["action"], "cineprobe")

    def test_cli_inspect_and_diff_cineprobe(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p_a = Path(td) / "a.txt"
            p_b = Path(td) / "b.txt"
            p_a.write_bytes(_make_synthetic_cineprobe_report("zve1_202", rw_page_hash="1111111111111111"))
            p_b.write_bytes(_make_synthetic_cineprobe_report("zve1_202", rw_page_hash="2222222222222222"))

            r_ins = subprocess.run(
                [sys.executable, "-B", str(CLI_DIR / "studio_cli.py"), "inspect-cineprobe", str(p_a), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(r_ins.returncode, 0, r_ins.stderr or r_ins.stdout)
            ins_json = json.loads(r_ins.stdout)
            self.assertTrue(ins_json["ok"])
            self.assertFalse(ins_json["ready"])
            self.assertEqual(ins_json["body_id"], "zve1_202")

            r_diff = subprocess.run(
                [sys.executable, "-B", str(CLI_DIR / "studio_cli.py"), "diff-cineprobe", str(p_a), str(p_b), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(r_diff.returncode, 0, r_diff.stderr or r_diff.stdout)
            diff_json = json.loads(r_diff.stdout)
            self.assertTrue(diff_json["ok"])
            self.assertEqual(diff_json["changed_rw_pages_count"], 1)


if __name__ == "__main__":
    unittest.main()
