#!/usr/bin/env python3
"""Unit and integration test suite for sony-opengate-studio."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_DIR = REPO_ROOT / "cli"
SCRIPTS_DIR = REPO_ROOT / "scripts"
for p in (CLI_DIR, SCRIPTS_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import bionz_clip_check as bcc  # noqa: E402
import verify_clean_room as vcr  # noqa: E402

STUDIO_CLI = CLI_DIR / "studio_cli.py"


def run_cli(*args: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, "-B", str(STUDIO_CLI), *args],
        capture_output=True,
        text=True,
        encoding="utf8",
    )
    data = json.loads(proc.stdout) if proc.stdout.strip() else {}
    return proc.returncode, data


class ClipCheckTests(unittest.TestCase):
    def test_selftest_all_cases(self) -> None:
        self.assertTrue(bcc.run_selftest(verbose=False))

    def test_codecs_fps_xml_and_rtmd_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 1. ZV-E1 hvc1 23.976p + embedded XML + M01.XML + rtmd
            p1 = root / "C0001.MP4"
            x1 = root / "C0001M01.XML"
            xml1 = bcc.build_synthetic_xml(3840, 2560, "hvc1", "23.976p")
            p1.write_bytes(bcc.build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001, embedded_xml=xml1))
            x1.write_text(xml1, encoding="utf8")
            rep1, _ = bcc.inspect_clip(p1, body="zve1")
            self.assertTrue(rep1["ok"])
            self.assertEqual(rep1["display_aspect"], "3:2")
            self.assertEqual(rep1["codec"], "hvc1")
            self.assertEqual(rep1["fps"], "23.976p")
            self.assertTrue(rep1["vprf_3x2"])
            self.assertTrue(rep1["xml_3x2"])
            self.assertTrue(rep1["rtmd_gyro_present"])
            self.assertEqual(rep1["rtmd_samples"], 24)

            # 2. FX3 avc1 (XAVC S-I) 25.000p
            p2 = root / "C0002.MP4"
            p2.write_bytes(bcc.build_synthetic_mp4(3840, 2560, "avc1", 25000, 1000))
            rep2, _ = bcc.inspect_clip(p2, body="fx3")
            self.assertTrue(rep2["ok"])
            self.assertEqual(rep2["codec"], "avc1")
            self.assertEqual(rep2["fps"], "25.000p")
            self.assertIsNone(rep2["xml_3x2"])

            # 3. Squeezed 16:9 XML must fail
            p3 = root / "C0003.MP4"
            x3 = root / "C0003M01.XML"
            p3.write_bytes(bcc.build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001))
            x3.write_text(bcc.build_synthetic_xml(3840, 2560, "hvc1", "23.976p", aspect_ratio="16:9"), encoding="utf8")
            rep3, _ = bcc.inspect_clip(p3, xml_path=x3, body="s3")
            self.assertFalse(rep3["ok"])
            self.assertFalse(rep3["xml_3x2"])

            # 4. Stripped rtmd (cdsc missing) must fail
            p4 = root / "C0004.MP4"
            p4.write_bytes(bcc.build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001, rtmd_cdsc=False))
            rep4, _ = bcc.inspect_clip(p4, body="zve1")
            self.assertFalse(rep4["ok"])
            self.assertFalse(rep4["rtmd_gyro_present"])


class StudioCliTests(unittest.TestCase):
    def test_list_bodies_and_verify_pins(self) -> None:
        rc, bodies = run_cli("list-bodies", "--json")
        self.assertEqual(rc, 0)
        ids = {b["body_id"] for b in bodies["bodies"]}
        self.assertEqual(ids, {"zve1_202", "a7s3_501", "fx3_702"})
        for b in bodies["bodies"]:
            self.assertTrue(b["pins_ok"], f"Pins failed for {b['body_id']}")

        rc2, pins = run_cli("verify-pins", "--json")
        self.assertEqual(rc2, 0)
        self.assertTrue(pins["ok"])
        self.assertGreaterEqual(pins["checked_files"], 40)

    def test_preflight_gate_apply_fallback_and_putback(self) -> None:
        for body_id in ("zve1_202", "a7s3_501", "fx3_702"):
            with tempfile.TemporaryDirectory() as tmp:
                # 1. Applying without preflight must fail
                rc_no, _ = run_cli("apply", "--body", body_id, "--packs", "mp4_3x2", "--mock-camera", "--session-dir", tmp, "--json")
                self.assertNotEqual(rc_no, 0)

                # 2. mixed_powerswitch preflight returns ready=False and blocks apply
                rc_mix, pre_mix = run_cli(
                    "preflight", "--body", body_id, "--mock-camera", "--mock-state", "mixed_powerswitch",
                    "--session-dir", tmp, "--json",
                )
                self.assertEqual(rc_mix, 0)
                self.assertFalse(pre_mix["ready"])
                self.assertEqual(pre_mix["state"], "not_ready")
                rc_blk, _ = run_cli("apply", "--body", body_id, "--packs", "mp4_3x2", "--mock-camera", "--session-dir", tmp, "--json")
                self.assertNotEqual(rc_blk, 0)

                # 3. Stock preflight unlocks apply
                rc_stk, pre_stk = run_cli(
                    "preflight", "--body", body_id, "--mock-camera", "--mock-state", "stock",
                    "--session-dir", tmp, "--json",
                )
                self.assertEqual(rc_stk, 0)
                self.assertTrue(pre_stk["ready"])
                self.assertEqual(pre_stk["state"], "stock")

                # 4. Apply all packs
                rc_app, app = run_cli(
                    "apply", "--body", body_id, "--packs", "mp4_3x2,screen_3x2,hdmi32,high_bitrate,xavc_si",
                    "--mock-camera", "--session-dir", tmp, "--json",
                )
                self.assertEqual(rc_app, 0)
                self.assertTrue(app["ok"])
                self.assertIn("V19", app["steps_run"])
                self.assertIn("H16", app["steps_run"])
                self.assertIn("B19", app["steps_run"])
                self.assertIn("I19", app["steps_run"])
                self.assertEqual(app["closing_dump_verdict"], "VERDICT READY (open gate applied)")

                # 5. Apply without mp4_3x2 substitutes fallback L19
                rc_fb, fb = run_cli(
                    "apply", "--body", body_id, "--packs", "hdmi32",
                    "--mock-camera", "--session-dir", tmp, "--json",
                )
                self.assertEqual(rc_fb, 0)
                self.assertIn("L19", fb["steps_run"])
                self.assertNotIn("V19", fb["steps_run"])

                # 6. Putback resets mock state to stock
                rc_put, put = run_cli(
                    "putback", "--body", body_id, "--packs", "mp4_3x2,screen_3x2,hdmi32,high_bitrate,xavc_si",
                    "--mock-camera", "--session-dir", tmp, "--json",
                )
                self.assertEqual(rc_put, 0)
                self.assertTrue(put["ok"])
                self.assertEqual(put["state"], "stock")
                self.assertIn("V20", put["steps_run"])

    def test_check_clip_via_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mp4 = root / "CLIP01.MP4"
            xml = root / "CLIP01M01.XML"
            xml_txt = bcc.build_synthetic_xml(3840, 2560, "hvc1", "23.976p")
            mp4.write_bytes(bcc.build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001, embedded_xml=xml_txt))
            xml.write_text(xml_txt, encoding="utf8")
            rc, res = run_cli("check-clip", str(mp4), "--xml", str(xml), "--json")
            self.assertEqual(rc, 0)
            self.assertTrue(res["ok"])
            self.assertEqual(res["width"], 3840)
            self.assertEqual(res["height"], 2560)

    def test_live_usb_refused_without_approval(self) -> None:
        rc, res = run_cli("preflight", "--body", "zve1_202", "--live-usb", "--json")
        self.assertNotEqual(rc, 0)
        self.assertFalse(res["ok"])


class CleanRoomTests(unittest.TestCase):
    def test_clean_room_passes(self) -> None:
        res = vcr.verify_clean_room(REPO_ROOT)
        self.assertTrue(res["ok"], f"Clean-room errors: {res['errors']}")
        self.assertEqual(res["checked_manifests"], 3)


if __name__ == "__main__":
    unittest.main()
