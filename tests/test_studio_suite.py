#!/usr/bin/env python3
"""Unit and integration test suite for opengate-studio."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_DIR = REPO_ROOT / "cli"
SCRIPTS_DIR = REPO_ROOT / "scripts"
CT1_DIR = REPO_ROOT / "transport" / "camera_tests" / "CT1_usb_first_contact"
for p in (CLI_DIR, SCRIPTS_DIR, CT1_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import bionz_clip_check as bcc  # noqa: E402
import verify_clean_room as vcr  # noqa: E402

STUDIO_CLI = CLI_DIR / "studio_cli.py"
STEP_RUN = CLI_DIR / "studio_step_run.py"
LIVE_APPLY = CLI_DIR / "studio_live_apply.py"
RUN_LIVE_SH = REPO_ROOT / "macos" / "run_live_terminal.sh"
RUN_LIVE_INAPP_SH = REPO_ROOT / "macos" / "run_live_inapp.sh"
SETUP_CMD = REPO_ROOT / "setup_and_open_mac.command"


def _find_transport_python() -> str:
    for cand in (
        Path(sys.executable),
        REPO_ROOT / ".venv" / "bin" / "python",
        REPO_ROOT.parent / ".venv" / "bin" / "python",
    ):
        if cand.is_file():
            chk = subprocess.run(
                [str(cand), "-B", "-c", "import Cryptodome"],
                capture_output=True,
                text=True,
            )
            if chk.returncode == 0:
                return str(cand)
    return sys.executable


TRANSPORT_PYTHON = _find_transport_python()


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

            # 5. 29.970p + AVC L5.1 MB warning + duration/bitrate/cadence telemetry
            p5 = root / "C0005.MP4"
            p5.write_bytes(
                bcc.build_synthetic_mp4(
                    3840, 2560, "avc1", 30000, 1001,
                    frame_count=30, avcc_level_idc=51, mdat_bytes=100000,
                )
            )
            rep5, _ = bcc.inspect_clip(p5, body="fx3")
            self.assertTrue(rep5["ok"])
            self.assertEqual(rep5["fps"], "29.970p")
            self.assertEqual(rep5["frame_count"], 30)
            self.assertGreater(rep5["duration_sec"], 0.9)
            self.assertGreater(rep5["avg_bitrate_mbps"], 0.0)
            self.assertTrue(rep5["cadence_constant"])
            self.assertTrue(rep5["avc_l51_mb_warning"])
            self.assertIn("L5.1", rep5["codec_profile_level"])

            # 6. Directory batch scan with stock + open-gate clips
            batch_dir = root / "batch"
            batch_dir.mkdir()
            (batch_dir / "A1_stock.MP4").write_bytes(bcc.build_synthetic_mp4(3840, 2160, "hvc1", 24000, 1001))
            (batch_dir / "B1_og.MP4").write_bytes(bcc.build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001))
            batch = bcc.inspect_directory(batch_dir, expect="auto", body="fx3")
            self.assertTrue(batch["ok"])
            self.assertEqual(batch["clips_scanned"], 2)
            self.assertEqual(batch["clips_passed"], 2)
            self.assertEqual(batch["clips_failed"], 0)

    def test_top_level_sony_uuid_prof_and_meta_xml_boxes(self) -> None:
        import struct
        import studio_gyro as sg

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = bytearray(bcc.build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001, hvcc_level_idc=150))
            # Move embedded uuid(SONY_PROF_UUID) out of moov to top level (replace inside moov with 'free')
            idx = raw.find(bcc.SONY_PROF_UUID)
            self.assertGreater(idx, 8)
            box_start = idx - 8
            (box_len,) = struct.unpack_from(">I", raw, box_start)
            top_uuid_prof = bytes(raw[box_start : box_start + box_len])
            raw[box_start + 4 : box_start + 8] = b"free"
            raw[box_start + 8 : box_start + box_len] = b"\x00" * (box_len - 8)

            hdlr_xml = bcc._fullbox(b"hdlr", 0, 0, struct.pack(">4s4sIII", b"\x00\x00\x00\x00", b"nrtm", 0, 0, 0) + b"\x00")

            # 1. Truncated XML (<VideoFrame/> without <VideoLayout> or <Device manufacturer='Sony'>) must fail
            trunc_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<NonRealTimeMeta xmlns="urn:schemas-professionalDisc:nonRealTimeMeta:ver.2.20">\n'
                '  <VideoFormat><VideoRecPort port="DIRECT"/><VideoFrame/></VideoFormat>\n'
                '  <Lens modelName="FE 24mm F1.4 GM"/>\n'
                '</NonRealTimeMeta>\n'
            )
            trunc_meta = bcc._fullbox(b"meta", 0, 0, hdlr_xml + bcc._fullbox(b"xml ", 0, 0, trunc_xml.encode("utf8")))
            mp4_trunc = root / "TRUNCATED_SONY.MP4"
            mp4_trunc.write_bytes(bytes(raw) + top_uuid_prof + trunc_meta)

            rep_bad, _ = bcc.inspect_clip(mp4_trunc, expect="open-gate", body="zve1_202")
            self.assertFalse(rep_bad["ok"], rep_bad)
            self.assertFalse(rep_bad["xml_3x2"], rep_bad)
            self.assertTrue(any("Device manufacturer='Sony'" in msg for msg in rep_bad["issues"]), rep_bad["issues"])

            gd_bad = sg.diagnose_clip_gyro(mp4_trunc, body="zve1_202", expect="open-gate")
            self.assertFalse(gd_bad["ready_for_gyroflow"], gd_bad)

            # 2. repair_nrt_xml_copy must produce a valid 3:2 copy with identical prefix & Device tag
            mp4_repaired = root / "repaired" / "REPAIRED_SONY.MP4"
            res_rep = bcc.repair_nrt_xml_copy(mp4_trunc, mp4_repaired, body="zve1_202")
            self.assertTrue(res_rep["ok"], res_rep)
            self.assertTrue(res_rep["prefix_identical"], res_rep)
            self.assertTrue(res_rep["device_tag_added"], res_rep)
            prefix_len = res_rep["meta_offset"]
            self.assertEqual(mp4_repaired.read_bytes()[:prefix_len], mp4_trunc.read_bytes()[:prefix_len])

            rep_ok, _ = bcc.inspect_clip(mp4_repaired, expect="open-gate", body="zve1_202")
            self.assertTrue(rep_ok["ok"], rep_ok)
            self.assertTrue(rep_ok["xml_3x2"], rep_ok)
            gd_rep = sg.diagnose_clip_gyro(mp4_repaired, body="zve1_202", expect="open-gate")
            self.assertTrue(gd_rep["ready_for_gyroflow"], gd_rep)
            self.assertTrue(gd_rep["ready_for_catalyst"], gd_rep)

            # 3. Native fixed V19 XML (videoCodec="HEVC_3840_2160_M10P@L5HT" + VideoLayout 3840x2560 + Device Sony) passes
            native_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<NonRealTimeMeta xmlns="urn:schemas-professionalDisc:nonRealTimeMeta:ver.2.20">\n'
                '  <VideoFormat>\n'
                '    <VideoRecPort port="DIRECT"/>\n'
                '    <VideoFrame videoCodec="HEVC_3840_2160_M10P@L5HT" captureFps="23.98p" formatFps="23.98p"/>\n'
                '    <VideoLayout pixel="3840" numOfVerticalLine="2560"/>\n'
                '  </VideoFormat>\n'
                '  <Device manufacturer="Sony" modelName="ZV-E1" serialNo="4294967295"/>\n'
                '  <Lens modelName="FE 24mm F1.4 GM"/>\n'
                '</NonRealTimeMeta>\n'
            )
            native_meta = bcc._fullbox(b"meta", 0, 0, hdlr_xml + bcc._fullbox(b"xml ", 0, 0, native_xml.encode("utf8")))
            mp4_native = root / "NATIVE_V19.MP4"
            mp4_native.write_bytes(bytes(raw) + top_uuid_prof + native_meta)

            rep_nat, _ = bcc.inspect_clip(mp4_native, expect="open-gate", body="zve1_202")
            self.assertTrue(rep_nat["ok"], rep_nat)
            self.assertTrue(rep_nat["vprf_3x2"], rep_nat)
            self.assertTrue(rep_nat["embedded_xml_present"], rep_nat)
            self.assertTrue(rep_nat["xml_3x2"], rep_nat)
            self.assertEqual(rep_nat["issues"], [])

            gd_nat = sg.diagnose_clip_gyro(mp4_native, body="zve1_202", expect="open-gate")
            self.assertTrue(gd_nat["ready_for_gyroflow"], gd_nat)
            self.assertTrue(gd_nat["ready_for_catalyst"], gd_nat)


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

    def test_fx3_playback_pack_apply_putback_and_default_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rc_pre, pre = run_cli(
                "preflight", "--body", "fx3_702", "--mock-camera", "--mock-state", "stock",
                "--session-dir", tmp, "--json",
            )
            self.assertEqual(rc_pre, 0)
            self.assertTrue(pre["ready"])

            # Default apply (no --packs) excludes fx3_playback because default_enabled=false
            rc_def, app_def = run_cli("apply", "--body", "fx3_702", "--mock-camera", "--session-dir", tmp, "--json")
            self.assertEqual(rc_def, 0)
            self.assertNotIn("fx3_playback", app_def["active_packs"])
            self.assertNotIn("P29", app_def["steps_run"])

            # Explicit fx3_playback applies P29 and puts back P30 before V20/core_open_gate
            rc_app, app = run_cli(
                "apply", "--body", "fx3_702", "--packs", "mp4_3x2,screen_3x2,fx3_playback",
                "--mock-camera", "--session-dir", tmp, "--json",
            )
            self.assertEqual(rc_app, 0)
            self.assertTrue(app["ok"])
            self.assertIn("fx3_playback", app["active_packs"])
            self.assertIn("P29", app["steps_run"])

            rc_put, put = run_cli("putback", "--body", "fx3_702", "--mock-camera", "--session-dir", tmp, "--json")
            self.assertEqual(rc_put, 0)
            self.assertTrue(put["ok"])
            self.assertEqual(put["state"], "stock")
            self.assertIn("P30", put["steps_run"])
            self.assertLess(put["steps_run"].index("P30"), put["steps_run"].index("V20"))
            self.assertLess(put["steps_run"].index("P30"), put["steps_run"].index("L17"))

        # Other bodies omit fx3_playback and still resolve default putback cleanly
        for other_body in ("zve1_202", "a7s3_501"):
            with tempfile.TemporaryDirectory() as tmp:
                rc_put_other, put_other = run_cli("putback", "--body", other_body, "--mock-camera", "--session-dir", tmp, "--json")
                self.assertEqual(rc_put_other, 0)
                self.assertNotIn("P30", put_other["steps_run"])

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

    def test_latest_session_and_prepare_live_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # 1. Empty session dir returns ok=True, found=False, exit 0
            rc_empty, empty = run_cli("latest-session", "--body", "zve1_202", "--session-dir", tmp, "--json")
            self.assertEqual(rc_empty, 0)
            self.assertTrue(empty["ok"])
            self.assertFalse(empty["found"])
            self.assertIsNone(empty["session_id"])
            self.assertIsNone(empty["kind"])
            self.assertFalse(empty["ready"])
            self.assertEqual(empty["state"], "unknown")
            self.assertEqual(empty["active_packs"], [])
            self.assertEqual(empty["steps_run"], [])

            # 2. After preflight -> latest-session reflects stock ready
            rc_pre, pre = run_cli(
                "preflight", "--body", "zve1_202", "--mock-camera", "--mock-state", "stock",
                "--session-dir", tmp, "--json",
            )
            self.assertEqual(rc_pre, 0)
            rc_ls1, ls1 = run_cli("latest-session", "--body", "zve1_202", "--session-dir", tmp, "--json")
            self.assertEqual(rc_ls1, 0)
            self.assertTrue(ls1["found"])
            self.assertEqual(ls1["session_id"], pre["session_id"])
            self.assertEqual(ls1["kind"], "preflight")
            self.assertTrue(ls1["ready"])
            self.assertEqual(ls1["state"], "stock")

            # 3. After apply -> latest-session reflects closing_dump applied + active_packs + steps_run
            rc_app, app = run_cli(
                "apply", "--body", "zve1_202", "--packs", "mp4_3x2,hdmi32",
                "--mock-camera", "--session-dir", tmp, "--json",
            )
            self.assertEqual(rc_app, 0)
            rc_ls2, ls2 = run_cli("latest-session", "--body", "zve1_202", "--session-dir", tmp, "--json")
            self.assertEqual(rc_ls2, 0)
            self.assertTrue(ls2["found"])
            self.assertEqual(ls2["kind"], "closing_dump")
            self.assertTrue(ls2["ready"])
            self.assertEqual(ls2["state"], "applied")
            self.assertEqual(ls2["active_packs"], app["active_packs"])
            self.assertEqual(ls2["steps_run"], app["steps_run"])

            # 4. After putback -> latest-session reflects putback stock
            rc_put, put = run_cli("putback", "--body", "zve1_202", "--mock-camera", "--session-dir", tmp, "--json")
            self.assertEqual(rc_put, 0)
            rc_ls3, ls3 = run_cli("latest-session", "--body", "zve1_202", "--session-dir", tmp, "--json")
            self.assertEqual(rc_ls3, 0)
            self.assertEqual(ls3["kind"], "putback")
            self.assertEqual(ls3["state"], "stock")
            self.assertEqual(ls3["steps_run"], put["steps_run"])

            # 5. prepare-live-command generates executable .command scripts without touching USB
            for action in ("preflight", "dump", "apply", "putback"):
                args = ["prepare-live-command", "--action", action, "--body", "a7s3_501", "--session-dir", tmp, "--json"]
                if action == "apply":
                    args.extend(["--packs", "mp4_3x2,screen_3x2,hdmi32"])
                rc_prep, prep = run_cli(*args)
                self.assertEqual(rc_prep, 0)
                self.assertTrue(prep["ok"])
                self.assertEqual(prep["action"], action)
                self.assertEqual(prep["body_id"], "a7s3_501")
                cmd_file = Path(prep["command_file"])
                self.assertTrue(cmd_file.is_file())
                self.assertTrue(bool(cmd_file.stat().st_mode & stat.S_IXUSR))
                self.assertIn("run_live_terminal.sh", prep["preview"])
                chk_sh = subprocess.run(["bash", "-n", str(cmd_file)], capture_output=True, text=True)
                self.assertEqual(chk_sh.returncode, 0, chk_sh.stderr)


class UsbTransportAndLiveOrchestratorTests(unittest.TestCase):
    @staticmethod
    def _build_synthetic_readonly_report(body_id: str, which: str, mode: str = "stock") -> bytes:
        import studio_step_run as ssr

        cfg = ssr.BODY_CONFIG[body_id]
        spec = ssr.load_body_expected(body_id)
        fw = cfg["firmware"]
        lines = [
            f"{cfg['reader']} {spec['label']} {which} for {cfg['header_model']} {fw}; read-only",
            "== file /proc/version",
            "Linux version 4.14.0",
            "== end 20 bytes",
            "== file /proc/cmdline",
            f"mem={spec['avcam_reserve']}",
            "== end 15 bytes",
            "== identity: files of this process",
        ]
        for fname, sha in spec["id_files"].items():
            lines.append(f"file {fname} path /usr/lib{fname} mapped 0x7f00000000")
            lines.append(f"  bytes 1024 sha256 {sha}  SAME as the {fw} update")
        lines.append("== identity: coprocessor code pages")
        for addr, sha in spec["id_pages"].items():
            lines.append(f"page {addr} sha256 {sha}  SAME as the {fw} update")
        lines.append("== coprocessor sites")
        for site in spec["cp_sites"]:
            name = site["name"]
            addr = site["address"]
            length = site["length"]
            if mode == "stock":
                state = "STOCK"
            elif site["soft"] and name in ("outsize_guard0", "outsize_guard1"):
                state = "STOCK"
            elif site["soft"] and name == "stored_record":
                state = "TARGET"
            elif body_id == "zve1_202" and name == "screen0":
                state = "STOCK"
            else:
                state = "TARGET"
            if length <= 16:
                lines.append(f"site {name} {addr} len {length} bytes {'00' * length}  {state}")
            else:
                lines.append(f"site {name} {addr} len {length} bytes differing from stock 0  {state}")
        lines.append("== main-processor sites: libmpr.so in this process")
        mp_state = "STOCK" if mode == "stock" else "TARGET"
        for i in range(spec["lm_sites"]):
            lines.append(f"lm {0x100000 + i * 4:#x} at {0x7f10000000 + i * 4:#x} bytes 00000000  {mp_state}")
        lines.append("== main-processor sites: av-cam.bin in kernel memory")
        for i, g in enumerate(spec["av_guards"]):
            lines.append(f"guard {g} {0x380000 + i * 0x100:#x} len 48  SAME")
        for i in range(spec["av_sites"]):
            lines.append(f"av {0x200000 + i * 4:#x} bytes 00000000  {mp_state}")
        lines.append("== summary")
        lines.append(
            "VERDICT READY (stock preflight)"
            if mode == "stock"
            else "VERDICT READY (open gate applied)"
        )
        lines.append("== done")
        lines.append("")
        return "\n".join(lines).encode("utf8")

    def test_ct1_common_resolves_pmca_from_any_cwd(self) -> None:
        env = dict(os.environ)
        env.pop("OPENGATE_CAMERA_PRIVATE", None)
        proc = subprocess.run(
            [
                TRANSPORT_PYTHON,
                "-B",
                "-c",
                (
                    f"import sys; sys.path.insert(0, {str(CT1_DIR)!r}); "
                    "import ct1_common as c; "
                    "assert c.check_pmca() == c.PMCA_COMMIT; "
                    "assert c.PMCA_ROOT.is_dir(); "
                    "assert c.PRIVATE_ROOT.name == 'camera_private' and c.PRIVATE_ROOT.parent.name == 'sessions'; "
                    "print('PMCA_OK')"
                ),
            ],
            cwd="/tmp",
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("PMCA_OK", proc.stdout)

    def test_step_run_selftests_all_bodies_and_steps(self) -> None:
        import studio_step_run as ssr

        self.assertEqual(ssr.step_level("check"), 101)
        self.assertEqual(ssr.step_level("dump"), 102)
        self.assertEqual(ssr.step_level("V19"), 619)
        self.assertEqual(ssr.step_level("H16"), 716)
        self.assertEqual(ssr.step_level("B19"), 819)
        self.assertEqual(ssr.step_level("I19"), 919)
        self.assertEqual(ssr.step_level("P29"), 1029)
        self.assertEqual(ssr.step_level("P30"), 1030)

        for body_id in ("zve1_202", "a7s3_501", "fx3_702"):
            steps = ["check", "dump", "V19", "H16", "B19", "I19"]
            if body_id == "fx3_702":
                steps.extend(["P29", "P30"])
            for which in steps:
                proc = subprocess.run(
                    [TRANSPORT_PYTHON, "-B", str(STEP_RUN), "--body", body_id, which, "--selftest"],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(proc.returncode, 0, f"{body_id} {which} failed:\n{proc.stderr}\n{proc.stdout}")
                self.assertIn("guard refuses all 15 forbidden packet classes", proc.stdout)

        for which in ("P29", "P30"):
            dry = subprocess.run(
                [TRANSPORT_PYTHON, "-B", str(STEP_RUN), "--body", "fx3_702", which, "--dry-run"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(dry.returncode, 0, f"fx3_702 {which} --dry-run failed:\n{dry.stderr}\n{dry.stdout}")
            self.assertIn("SET_FILE_PATH", dry.stdout)

        # Verify P29/P30 write-result parsing including level 29/30 UNDO INCOMPLETE format (no leading !!)
        done_res = ssr.parse_write_result(
            "P29",
            "avdec8k_fx3_v1",
            b"readcheck 1 level 29\neuid 0\n== level 29\nDONE: every site holds the target bytes (apply)\n== done, bytes written before this line: 0\n",
        )
        self.assertTrue(done_res["header_ok"])
        self.assertTrue(done_res["s3"]["ok"])
        self.assertEqual(done_res["s3"]["outcome"], "DONE")

        ntd_res = ssr.parse_write_result(
            "P30",
            "avdec8k_fx3_v1",
            b"readcheck 1 level 30\neuid 0\n== level 30\nNOTHING TO DO: every site already holds the target bytes (put back)\n== done, bytes written before this line: 0\n",
        )
        self.assertTrue(ntd_res["header_ok"])
        self.assertTrue(ntd_res["s3"]["ok"])
        self.assertEqual(ntd_res["s3"]["outcome"], "NOTHING TO DO")

        undo_res = ssr.parse_write_result(
            "P29",
            "avdec8k_fx3_v1",
            b"readcheck 1 level 29\neuid 0\n== level 29\nUNDO INCOMPLETE: main-processor memory may be partly changed; cold boot the camera before anything else\n== done, bytes written before this line: 0\n",
        )
        self.assertFalse(undo_res["s3"]["ok"])
        self.assertEqual(undo_res["s3"]["outcome"], "UNDO INCOMPLETE")

        # Benign diagnostic preamble notices (/proc/driver/pcie/* -EISDIR) must not fail valid writes,
        # while any '!!' inside action sections or non-EISDIR errors must fail closed.
        pcie_benign = ssr.parse_write_result(
            "L13",
            "dmmwb_zv_v1",
            (
                b"readcheck 1 level 13: dmmwb\n"
                b"euid 0\n"
                b"== dir /proc/driver/pcie\nentries 1\n"
                b"== file /proc/driver/pcie/0\n\n!! read failed -21\n\n== end 0 bytes\n"
                b"== level 13: apply the memory-manager word\n"
                b"DONE: the site holds the target bytes (apply)\n"
                b"== done, bytes written before this line: 100\n"
            ),
        )
        self.assertTrue(pcie_benign["s3"]["ok"])
        self.assertEqual(pcie_benign["problems"], 0)
        self.assertEqual(pcie_benign["s3"]["problem_lines"], [])
        self.assertEqual(pcie_benign["s3"]["diagnostic_problem_lines"], ["!! read failed -21"])

        in_level_err = ssr.parse_write_result(
            "L13",
            "dmmwb_zv_v1",
            (
                b"readcheck 1 level 13: dmmwb\n"
                b"euid 0\n"
                b"== level 13: apply the memory-manager word\n"
                b"!! read failed -21\n"
                b"DONE: the site holds the target bytes (apply)\n"
                b"== done, bytes written before this line: 100\n"
            ),
        )
        self.assertFalse(in_level_err["s3"]["ok"])
        self.assertEqual(in_level_err["problems"], 1)

        non_eisdir_pcie = ssr.parse_write_result(
            "L13",
            "dmmwb_zv_v1",
            (
                b"readcheck 1 level 13: dmmwb\n"
                b"euid 0\n"
                b"== file /proc/driver/pcie/0\n\n!! read failed -5\n\n== end 0 bytes\n"
                b"== level 13: apply the memory-manager word\n"
                b"DONE: the site holds the target bytes (apply)\n"
                b"== done, bytes written before this line: 100\n"
            ),
        )
        self.assertFalse(non_eisdir_pcie["s3"]["ok"])
        self.assertEqual(non_eisdir_pcie["problems"], 1)

    def test_readonly_report_parser_validates_and_rejects_tampering(self) -> None:
        import studio_step_run as ssr

        for body_id in ("zve1_202", "a7s3_501", "fx3_702"):
            stock_rep = self._build_synthetic_readonly_report(body_id, "check", mode="stock")
            parsed_stk = ssr.parse_readonly_result(body_id, "check", stock_rep)
            self.assertTrue(parsed_stk["header_ok"])
            self.assertTrue(parsed_stk["complete"])
            self.assertTrue(parsed_stk["s3"]["ready"])
            self.assertEqual(parsed_stk["s3"]["state"], "stock")
            self.assertEqual(parsed_stk["s3"]["verdict"], "VERDICT READY (stock preflight)")

            app_rep = self._build_synthetic_readonly_report(body_id, "dump", mode="applied")
            parsed_app = ssr.parse_readonly_result(body_id, "dump", app_rep)
            self.assertTrue(parsed_app["s3"]["ready"])
            self.assertEqual(parsed_app["s3"]["state"], "applied")
            self.assertEqual(parsed_app["s3"]["verdict"], "VERDICT READY (open gate applied)")

            # Benign diagnostic notices in /log before '== identity:' must not fail closing dump,
            # while '!!' inside verification sections must fail closed.
            if body_id == "zve1_202":
                diag_dump = app_rep.replace(
                    b"== identity:",
                    b"== dir /log\n!! read failed -21\n== file /log/boot\n!! truncated at 2048 bytes\n== identity:",
                    1,
                )
                res_diag = ssr.parse_readonly_result("zve1_202", "dump", diag_dump)
                self.assertTrue(res_diag["s3"]["ready"])
                self.assertEqual(res_diag["s3"]["state"], "applied")
                self.assertEqual(res_diag["problems"], 0)
                self.assertEqual(len(res_diag["s3"]["diagnostic_problem_lines"]), 2)

                cp_err = app_rep.replace(
                    b"== coprocessor sites",
                    b"== coprocessor memory, read-only\n!! read failed -21\n== coprocessor sites",
                    1,
                )
                res_cp = ssr.parse_readonly_result("zve1_202", "dump", cp_err)
                self.assertFalse(res_cp["s3"]["ready"])
                self.assertEqual(res_cp["problems"], 1)

            # Reject if identity differs or !! appears or guard differs
            bad_diff = stock_rep.replace(b"  SAME as the", b"  DIFFERS from the", 1)
            res_diff = ssr.parse_readonly_result(body_id, "check", bad_diff)
            self.assertFalse(res_diff["s3"]["ready"])
            self.assertEqual(res_diff["s3"]["verdict"], "VERDICT NOT READY")

            bad_guard = stock_rep.replace(b"len 48  SAME", b"len 48  DIFFERS", 1)
            res_guard = ssr.parse_readonly_result(body_id, "check", bad_guard)
            self.assertFalse(res_guard["s3"]["ready"])
            self.assertEqual(res_guard["s3"]["verdict"], "VERDICT NOT READY")

            bad_bang = stock_rep.replace(b"== summary", b"!! error injected\n== summary")
            res_bang = ssr.parse_readonly_result(body_id, "check", bad_bang)
            self.assertFalse(res_bang["s3"]["ready"])
            self.assertEqual(res_bang["s3"]["verdict"], "VERDICT NOT READY")

    def test_live_apply_dry_run_and_shell_scripts(self) -> None:
        for script in (RUN_LIVE_SH, SETUP_CMD):
            self.assertTrue(script.is_file())
            self.assertTrue(bool(script.stat().st_mode & stat.S_IXUSR), f"{script.name} not executable")
            chk = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
            self.assertEqual(chk.returncode, 0, chk.stderr)

        with tempfile.TemporaryDirectory() as tmp:
            for body_id in ("zve1_202", "a7s3_501", "fx3_702"):
                for action in ("preflight", "dump", "apply", "putback"):
                    args = [TRANSPORT_PYTHON, "-B", str(LIVE_APPLY), action, "--body", body_id, "--session-dir", tmp, "--dry-run"]
                    if action in ("apply", "putback"):
                        args.extend(["--packs", "mp4_3x2,screen_3x2,hdmi32,high_bitrate,xavc_si"])
                    proc = subprocess.run(args, capture_output=True, text=True)
                    self.assertEqual(proc.returncode, 0, f"{body_id} {action} dry-run failed:\n{proc.stderr}\n{proc.stdout}")
                    self.assertIn("Dry run only: nothing was sent to any device.", proc.stdout)

            # run_live_terminal.sh --dry-run bypasses sudo cleanly
            if TRANSPORT_PYTHON == str(REPO_ROOT / ".venv" / "bin" / "python") or (REPO_ROOT.parent / ".venv" / "bin" / "python").is_file():
                proc_sh = subprocess.run(
                    ["/bin/bash", str(RUN_LIVE_SH), "apply", "--body", "zve1_202", "--packs", "mp4_3x2", "--session-dir", tmp, "--dry-run"],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(proc_sh.returncode, 0, proc_sh.stderr + proc_sh.stdout)
                self.assertIn("Dry run only: nothing was sent to any device.", proc_sh.stdout)


class SyncAndRecoveryTests(unittest.TestCase):
    def test_known_libs_includes_manifests_earlier_and_extra(self) -> None:
        import studio_step_run as ssr

        known = ssr.known_libs()
        self.assertGreaterEqual(len(ssr.EARLIER_LIBS), 36)
        for sha in ssr.EARLIER_LIBS:
            self.assertIn(sha, known)
        for body_id in ("zve1_202", "a7s3_501", "fx3_702"):
            _, man = ssr.load_body_manifest(body_id)
            for entry in man["steps"].values():
                self.assertIn(entry["sha256"], known)

        test_sha = "a" * 64
        ssr.EXTRA_LIBS[test_sha] = "test extra"
        try:
            self.assertIn(test_sha, ssr.known_libs())
        finally:
            ssr.EXTRA_LIBS.pop(test_sha, None)

    def test_remove_library_cli_validation(self) -> None:
        bad = subprocess.run(
            [TRANSPORT_PYTHON, "-B", str(STEP_RUN), "--body", "fx3_702", "check", "--selftest", "--remove-library", "not-hex"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("Invalid --remove-library", bad.stderr + bad.stdout)

        good_sha = "0123456789abcdef" * 4
        good = subprocess.run(
            [TRANSPORT_PYTHON, "-B", str(STEP_RUN), "--body", "fx3_702", "check", "--selftest", "--remove-library", good_sha],
            capture_output=True,
            text=True,
        )
        self.assertEqual(good.returncode, 0, good.stderr + good.stdout)
        self.assertIn("leftover known libJit.so: auto-deleted first, then normal run completes", good.stdout)

    def test_live_apply_left_behind_and_frame_rate_hints(self) -> None:
        import studio_live_apply as sla

        for body_id in ("zve1_202", "a7s3_501", "fx3_702"):
            hint = sla.BODY_MOVIE_HINT[body_id]
            self.assertIn("24p/23.98p", hint)
            self.assertIn("25p PAL", hint)
            self.assertIn("30p/29.97p", hint)

        with tempfile.TemporaryDirectory() as tmp:
            old_env = os.environ.get("OPENGATE_CAMERA_PRIVATE")
            os.environ["OPENGATE_CAMERA_PRIVATE"] = tmp
            try:
                self.assertFalse(sla.left_behind())
                d = Path(tmp) / "CT6_20261126_000001"
                d.mkdir(parents=True)

                (d / "manifest.json").write_text(json.dumps({"results": {"ct6": {"library_on_camera_after": True}}}), encoding="utf8")
                self.assertTrue(sla.left_behind())

                (d / "manifest.json").write_text(json.dumps({"results": {"ct6": {"library_on_camera_after": None, "library_sent": True}}}), encoding="utf8")
                self.assertTrue(sla.left_behind())

                (d / "manifest.json").write_text(json.dumps({"results": {"ct6": {"library_on_camera_after": False, "library_sent": True}}}), encoding="utf8")
                self.assertFalse(sla.left_behind())
            finally:
                if old_env is None:
                    os.environ.pop("OPENGATE_CAMERA_PRIVATE", None)
                else:
                    os.environ["OPENGATE_CAMERA_PRIVATE"] = old_env

    def test_manifests_advertise_multirec_and_25p_30p_across_all_bodies(self) -> None:
        import studio_step_run as ssr

        for body_id in ("zve1_202", "a7s3_501", "fx3_702"):
            _, man = ssr.load_body_manifest(body_id)
            steps = man["steps"]
            self.assertIn("MULTI_REC", steps["L5"]["summary"])
            for k in ("L19", "L20", "V19", "V20", "I19", "I20"):
                self.assertIn("23.98p/25p/29.97p", steps[k]["summary"], f"{body_id} {k}")


class LiveInAppOrchestratorTests(unittest.TestCase):
    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf8").splitlines()
            if line.strip()
        ]

    @staticmethod
    def _extract_stdout_events(stdout: str) -> list[dict]:
        events = []
        for line in stdout.splitlines():
            if line.startswith("@OG_EVENT "):
                events.append(json.loads(line[len("@OG_EVENT "):]))
        return events

    def test_firmware_confirmed_mismatch_and_volatile_ram_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 1. Mismatched --firmware-confirmed refuses with error event
            ev_fw = root / "fw_err.jsonl"
            log_fw = root / "fw_err.log"
            proc_fw = subprocess.run(
                [
                    TRANSPORT_PYTHON, "-B", str(LIVE_APPLY),
                    "preflight", "--body", "zve1_202",
                    "--session-dir", str(root / "sess"),
                    "--firmware-confirmed", "1.00",
                    "--json-events",
                    "--events-file", str(ev_fw),
                    "--log-file", str(log_fw),
                    "--dry-run",
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc_fw.returncode, 0)
            self.assertIn("Not 2.02. Nothing was sent.", proc_fw.stderr)
            evs = self._read_jsonl(ev_fw)
            self.assertEqual(len(evs), 1)
            self.assertEqual(evs[0]["type"], "error")
            self.assertIn("Not 2.02. Nothing was sent.", evs[0]["message"])
            self.assertFalse(evs[0]["left_behind"])
            self.assertEqual(self._extract_stdout_events(proc_fw.stdout), evs)
            self.assertIn("Not 2.02. Nothing was sent.", log_fw.read_text(encoding="utf8"))

            # 2. apply & putback with --firmware-confirmed but without --confirm-volatile-ram refuse immediately
            for action in ("apply", "putback"):
                ev_ram = root / f"ram_err_{action}.jsonl"
                proc_ram = subprocess.run(
                    [
                        TRANSPORT_PYTHON, "-B", str(LIVE_APPLY),
                        action, "--body", "zve1_202",
                        "--session-dir", str(root / "sess"),
                        "--firmware-confirmed", "2.02",
                        "--events-file", str(ev_ram),
                        "--dry-run",
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(proc_ram.returncode, 0, f"{action} should refuse without --confirm-volatile-ram")
                evs_ram = self._read_jsonl(ev_ram)
                self.assertEqual(len(evs_ram), 1)
                self.assertEqual(evs_ram[0]["type"], "error")
                self.assertIn("--confirm-volatile-ram", evs_ram[0]["message"])
                self.assertFalse(evs_ram[0]["left_behind"])

            # 3. --simulate-events without --dry-run refuses immediately
            ev_sim = root / "sim_err.jsonl"
            proc_sim = subprocess.run(
                [
                    TRANSPORT_PYTHON, "-B", str(LIVE_APPLY),
                    "preflight", "--body", "zve1_202",
                    "--session-dir", str(root / "sess"),
                    "--firmware-confirmed", "2.02",
                    "--events-file", str(ev_sim),
                    "--simulate-events",
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc_sim.returncode, 0)
            evs_sim = self._read_jsonl(ev_sim)
            self.assertEqual(len(evs_sim), 1)
            self.assertEqual(evs_sim[0]["type"], "error")
            self.assertIn("--dry-run", evs_sim[0]["message"])

    def test_simulate_events_preflight_apply_putback_schemas_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 1. Preflight simulation
            ev_pre = root / "pre.jsonl"
            log_pre = root / "pre.log"
            proc_pre = subprocess.run(
                [
                    TRANSPORT_PYTHON, "-B", str(LIVE_APPLY),
                    "preflight", "--body", "zve1_202",
                    "--session-dir", str(root / "sess"),
                    "--firmware-confirmed", "2.02",
                    "--json-events",
                    "--events-file", str(ev_pre),
                    "--log-file", str(log_pre),
                    "--dry-run", "--simulate-events",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_pre.returncode, 0, proc_pre.stderr + proc_pre.stdout)
            evs_pre = self._read_jsonl(ev_pre)
            self.assertEqual(self._extract_stdout_events(proc_pre.stdout), evs_pre)
            self.assertEqual([e["type"] for e in evs_pre], ["plan", "wait_drive", "step_start", "step_done", "complete"])
            for e in evs_pre:
                self.assertTrue(str(e["ts"]).endswith("Z"))
            self.assertEqual(evs_pre[0]["action"], "preflight")
            self.assertEqual(evs_pre[0]["body_id"], "zve1_202")
            self.assertEqual(evs_pre[0]["firmware"], "2.02")
            self.assertFalse(evs_pre[0]["closing_dump"])
            self.assertEqual(evs_pre[0]["steps"][0]["id"], "check")
            self.assertTrue(evs_pre[1]["first"])
            self.assertEqual(evs_pre[3]["outcome"], "DONE")
            self.assertTrue(evs_pre[3]["ok"])
            self.assertTrue(evs_pre[4]["ok"])
            self.assertTrue(evs_pre[4]["ready"])
            self.assertEqual(evs_pre[4]["state"], "stock")
            self.assertEqual(evs_pre[4]["steps_run"], ["check"])
            log_pre_txt = log_pre.read_text(encoding="utf8")
            self.assertIn("Dry run only: nothing was sent to any device.", log_pre_txt)
            self.assertNotIn("@OG_EVENT ", log_pre_txt)

            # 2. Apply simulation with Movie-mode closing dump
            ev_app = root / "app.jsonl"
            log_app = root / "app.log"
            proc_app = subprocess.run(
                [
                    TRANSPORT_PYTHON, "-B", str(LIVE_APPLY),
                    "apply", "--body", "zve1_202",
                    "--packs", "mp4_3x2,hdmi32",
                    "--session-dir", str(root / "sess"),
                    "--firmware-confirmed", "2.02",
                    "--confirm-volatile-ram",
                    "--json-events",
                    "--events-file", str(ev_app),
                    "--log-file", str(log_app),
                    "--dry-run", "--simulate-events",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_app.returncode, 0, proc_app.stderr + proc_app.stdout)
            evs_app = self._read_jsonl(ev_app)
            types_app = [e["type"] for e in evs_app]
            self.assertEqual(types_app[0], "plan")
            self.assertTrue(evs_app[0]["closing_dump"])
            self.assertEqual(types_app[-4:], ["wait_movie_replug", "closing_dump_start", "closing_dump_done", "complete"])
            wait_drives = [e for e in evs_app if e["type"] == "wait_drive"]
            self.assertGreaterEqual(len(wait_drives), 4)
            self.assertTrue(wait_drives[0]["first"])
            self.assertTrue(all(not wd["first"] for wd in wait_drives[1:]))
            self.assertEqual(evs_app[-4]["title"], "Switch camera to Movie mode")
            self.assertTrue(evs_app[-2]["ready"])
            self.assertEqual(evs_app[-1]["state"], "applied")
            self.assertIn("mp4_3x2", evs_app[-1]["active_packs"])
            self.assertIn("hdmi32", evs_app[-1]["active_packs"])
            self.assertIn("V19", evs_app[-1]["steps_run"])
            self.assertIn("H16", evs_app[-1]["steps_run"])
            self.assertIn("Dry run only: nothing was sent to any device.", log_app.read_text(encoding="utf8"))

            # 3. Apply simulation with --no-movie-session omits movie replug / closing dump and fails closed
            ev_nomov = root / "app_nomov.jsonl"
            proc_nomov = subprocess.run(
                [
                    TRANSPORT_PYTHON, "-B", str(LIVE_APPLY),
                    "apply", "--body", "zve1_202",
                    "--packs", "mp4_3x2",
                    "--session-dir", str(root / "sess"),
                    "--firmware-confirmed", "2.02",
                    "--confirm-volatile-ram",
                    "--no-movie-session",
                    "--events-file", str(ev_nomov),
                    "--dry-run", "--simulate-events",
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc_nomov.returncode, 0, proc_nomov.stderr + proc_nomov.stdout)
            evs_nomov = self._read_jsonl(ev_nomov)
            self.assertFalse(evs_nomov[0]["closing_dump"])
            self.assertNotIn("wait_movie_replug", [e["type"] for e in evs_nomov])
            self.assertEqual(evs_nomov[-1]["type"], "error")

            # 4. Putback simulation runs closing stock_check and requires closing verification
            ev_put = root / "put.jsonl"
            log_put = root / "put.log"
            proc_put = subprocess.run(
                [
                    TRANSPORT_PYTHON, "-B", str(LIVE_APPLY),
                    "putback", "--body", "fx3_702",
                    "--packs", "mp4_3x2,fx3_playback",
                    "--session-dir", str(root / "sess"),
                    "--firmware-confirmed", "7.02",
                    "--confirm-volatile-ram",
                    "--events-file", str(ev_put),
                    "--log-file", str(log_put),
                    "--dry-run", "--simulate-events",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_put.returncode, 0, proc_put.stderr + proc_put.stdout)
            evs_put = self._read_jsonl(ev_put)
            self.assertEqual(evs_put[0]["type"], "plan")
            self.assertEqual(evs_put[0]["action"], "putback")
            self.assertTrue(evs_put[0]["closing_dump"])
            self.assertEqual(evs_put[0]["closing_kind"], "stock_check")
            self.assertIn("closing_dump_start", [e["type"] for e in evs_put])
            self.assertIn("closing_dump_done", [e["type"] for e in evs_put])
            self.assertEqual(evs_put[-1]["type"], "complete")
            self.assertTrue(evs_put[-1]["ok"])
            self.assertTrue(evs_put[-1]["ready"])
            self.assertTrue(evs_put[-1]["verified"])
            self.assertEqual(evs_put[-1]["state"], "stock")
            self.assertEqual(evs_put[-1]["active_packs"], [])
            self.assertIn("P30", evs_put[-1]["steps_run"])
            self.assertIn("Dry run only: nothing was sent to any device.", log_put.read_text(encoding="utf8"))

            ev_nocheck = root / "put_nocheck.jsonl"
            proc_nocheck = subprocess.run(
                [
                    TRANSPORT_PYTHON, "-B", str(LIVE_APPLY),
                    "putback", "--body", "fx3_702",
                    "--packs", "mp4_3x2,fx3_playback",
                    "--session-dir", str(root / "sess"),
                    "--firmware-confirmed", "7.02",
                    "--confirm-volatile-ram",
                    "--no-closing-check",
                    "--events-file", str(ev_nocheck),
                    "--dry-run", "--simulate-events",
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc_nocheck.returncode, 0, proc_nocheck.stderr + proc_nocheck.stdout)
            evs_nocheck = self._read_jsonl(ev_nocheck)
            self.assertEqual(evs_nocheck[-1]["type"], "error")

    def test_cancel_file_triggers_clean_cancelled_event_exit_130(self) -> None:
        import studio_live_apply as sla

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cancel_flag = root / "cancel.flag"
            cancel_flag.write_text("cancel\n", encoding="utf8")
            ev_path = root / "cancelled.jsonl"
            log_path = root / "cancelled.log"

            proc = subprocess.run(
                [
                    TRANSPORT_PYTHON, "-B", str(LIVE_APPLY),
                    "apply", "--body", "zve1_202",
                    "--packs", "mp4_3x2",
                    "--session-dir", str(root / "sess"),
                    "--firmware-confirmed", "2.02",
                    "--confirm-volatile-ram",
                    "--json-events",
                    "--events-file", str(ev_path),
                    "--log-file", str(log_path),
                    "--cancel-file", str(cancel_flag),
                    "--dry-run", "--simulate-events",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 130, proc.stderr + proc.stdout)
            evs = self._read_jsonl(ev_path)
            self.assertEqual([e["type"] for e in evs], ["plan", "cancelled"])
            self.assertEqual(evs[-1]["step_index"], 1)
            self.assertEqual(evs[-1]["step_id"], "L13")
            self.assertTrue(bool(evs[-1]["message"]))
            self.assertEqual(self._extract_stdout_events(proc.stdout), evs)

            # Also verify wait_for_drive and wait_for_replug check cancel_file cleanly without touching USB
            orig_usb_state = sla.usb_state
            sla.usb_state = lambda: "other"
            try:
                with sla.RunContext(cancel_file=cancel_flag) as ctx:
                    with self.assertRaises(sla.CancelledRun):
                        sla.wait_for_drive("zve1_202", first=True, timeout=5, ctx=ctx, step_index=1, total_steps=4, step_id="L13")
                    with self.assertRaises(sla.CancelledRun):
                        sla.wait_for_replug(timeout=5, ctx=ctx)
            finally:
                sla.usb_state = orig_usb_state

    def test_run_live_inapp_shell_wrapper(self) -> None:
        self.assertTrue(RUN_LIVE_INAPP_SH.is_file())
        self.assertTrue(bool(RUN_LIVE_INAPP_SH.stat().st_mode & stat.S_IXUSR), "run_live_inapp.sh not executable")
        chk = subprocess.run(["bash", "-n", str(RUN_LIVE_INAPP_SH)], capture_output=True, text=True)
        self.assertEqual(chk.returncode, 0, chk.stderr)

        # Wrapper must never invoke sudo itself, and should adopt the GUI user's bootstrap context for TCC
        wrapper_src = RUN_LIVE_INAPP_SH.read_text(encoding="utf8")
        self.assertIn('/bin/launchctl asuser "$OWNER_UID"', wrapper_src)
        self.assertIn('/bin/launchctl print "gui/$OWNER_UID"', wrapper_src)
        for line in wrapper_src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            self.assertNotRegex(stripped, r"(^|\s)sudo(\s|$)", f"run_live_inapp.sh must not invoke sudo: {line}")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ev_path = root / "inapp" / "events.jsonl"
            log_path = root / "inapp" / "output.log"
            proc = subprocess.run(
                [
                    "/bin/bash",
                    str(RUN_LIVE_INAPP_SH),
                    "--owner-uid", str(os.getuid()),
                    "--owner-gid", str(os.getgid()),
                    "apply",
                    "--body", "a7s3_501",
                    "--packs", "mp4_3x2",
                    "--session-dir", str(root / "sess"),
                    "--firmware-confirmed", "5.01",
                    "--confirm-volatile-ram",
                    "--events-file", str(ev_path),
                    "--log-file", str(log_path),
                    "--dry-run",
                    "--simulate-events",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertTrue(ev_path.is_file())
            self.assertTrue(log_path.is_file())
            evs = self._read_jsonl(ev_path)
            self.assertEqual(evs[0]["type"], "plan")
            self.assertEqual(evs[-1]["type"], "complete")
            self.assertEqual(evs[-1]["body_id"], "a7s3_501")
            self.assertEqual(self._extract_stdout_events(proc.stdout), evs)
            self.assertIn("Dry run only: nothing was sent to any device.", log_path.read_text(encoding="utf8"))

            # Verify exit code 130 propagates cleanly through run_live_inapp.sh on cancellation
            cancel_flag = root / "cancel.flag"
            cancel_flag.write_text("1", encoding="utf8")
            ev_can = root / "inapp_cancel.jsonl"
            proc_can = subprocess.run(
                [
                    "/bin/bash",
                    str(RUN_LIVE_INAPP_SH),
                    "--owner-uid", str(os.getuid()),
                    "--owner-gid", str(os.getgid()),
                    "preflight",
                    "--body", "zve1_202",
                    "--session-dir", str(root / "sess"),
                    "--firmware-confirmed", "2.02",
                    "--events-file", str(ev_can),
                    "--cancel-file", str(cancel_flag),
                    "--dry-run",
                    "--simulate-events",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_can.returncode, 130, proc_can.stderr + proc_can.stdout)
            evs_can = self._read_jsonl(ev_can)
            self.assertEqual(evs_can[-1]["type"], "cancelled")


class FieldReportTests(unittest.TestCase):
    def test_build_report_creates_bundle_and_excludes_camera_private(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sess_dir = root / "sessions"
            sess_dir.mkdir()
            priv_dir = sess_dir / "camera_private"
            priv_dir.mkdir()
            (priv_dir / "secret_dump.txt").write_text("PRIVATE_DUMP_TOKEN_DO_NOT_COPY", encoding="utf8")

            rc_pre, _ = run_cli(
                "preflight", "--body", "fx3_702", "--mock-camera", "--mock-state", "stock",
                "--session-dir", str(sess_dir), "--json",
            )
            self.assertEqual(rc_pre, 0)

            clips_dir = root / "clips"
            clips_dir.mkdir()
            (clips_dir / "A1_stock_framing.MP4").write_bytes(
                bcc.build_synthetic_mp4(3840, 2160, "hvc1", 24000, 1001)
            )
            (clips_dir / "B1_og_framing.MP4").write_bytes(
                bcc.build_synthetic_mp4(3840, 2560, "avc1", 24000, 1001, avcc_level_idc=51)
            )
            (clips_dir / "lcd_3x2.jpg").write_bytes(b"fakejpg")

            out_dir = root / "out_report"
            rc_rep, rep = run_cli(
                "build-report",
                "--body", "fx3_702",
                "--session-dir", str(sess_dir),
                "--clips-dir", str(clips_dir),
                "--out-dir", str(out_dir),
                "--media-card", "Sony CEA-G 160GB",
                "--lens", "24mm GM",
                "--ambient-c", "23C",
                "--soak-minutes", "45",
                "--thermal-result", "No warning",
                "--reactivation-seconds", "58",
                "--af-desqueeze-notes", "hdmi32 + De-Squeeze OFF kept AF active",
                "--json",
            )
            self.assertEqual(rc_rep, 0, rep)
            self.assertTrue(rep["ok"])
            self.assertEqual(rep["clips_scanned"], 2)
            self.assertEqual(rep["clips_passed"], 2)
            self.assertEqual(rep["clips_failed"], 0)
            self.assertTrue(Path(rep["markdown_path"]).is_file())
            self.assertTrue(Path(rep["json_path"]).is_file())
            self.assertTrue(Path(rep["manifest_path"]).is_file())

            md_text = Path(rep["markdown_path"]).read_text(encoding="utf8")
            self.assertIn("Sony CEA-G 160GB", md_text)
            self.assertIn("VERDICT READY", md_text)
            self.assertIn("3840x2560", md_text)
            self.assertNotIn("PRIVATE_DUMP_TOKEN_DO_NOT_COPY", md_text)
            self.assertNotIn("secret_dump", Path(rep["manifest_path"]).read_text(encoding="utf8"))


class CleanRoomTests(unittest.TestCase):
    def test_clean_room_passes(self) -> None:
        res = vcr.verify_clean_room(REPO_ROOT)
        self.assertTrue(res["ok"], f"Clean-room errors: {res['errors']}")
        self.assertEqual(res["checked_manifests"], 3)
        self.assertEqual(res["checked_so"], 62)
        self.assertGreaterEqual(res["checked_pmca_files"], 15)


class HardeningRegressionTests(unittest.TestCase):
    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _make_live_preflight_record(
        self,
        sdir: Path,
        *,
        body_id: str = "zve1_202",
        kind: str = "preflight",
        mode: str = "live_usb",
        state: str = "stock",
        ready: bool = True,
        verified: bool = True,
        ts: float | None = None,
        manifest_sha256: str | None = None,
        boot_nonce: str | None = "boot-nonce-1234",
        preflight_result_sha256: str | None = "a" * 64,
        device_info_sha256: str | None = None,
        serial_sha256: str = "b" * 64,
        msc_usb_id: str | None = "054c:0da8",
        session_name: str = "0001_preflight",
    ) -> Path:
        import time
        import studio_cli

        kit_dir, man = studio_cli._load_manifests()[body_id]
        if manifest_sha256 is None:
            manifest_sha256 = studio_cli.compute_kit_manifest_sha256(kit_dir)
        now_ts = time.time() if ts is None else float(ts)
        dev_sha = (
            man["device_info"]["sha256"]
            if device_info_sha256 is None
            else device_info_sha256
        )
        sid = f"session_{session_name}"
        cam_id: dict[str, str] = {"device_info_sha256": dev_sha, "serial_sha256": serial_sha256}
        if msc_usb_id:
            cam_id["msc_usb_id"] = msc_usb_id
        rec = {
            "session_id": sid,
            "timestamp": now_ts,
            "expires_at": now_ts + studio_cli.LIVE_PREFLIGHT_TTL_SECONDS,
            "kind": kind,
            "mode": mode,
            "body_id": body_id,
            "camera": man.get("camera"),
            "firmware": man.get("firmware"),
            "state": state,
            "which": "check",
            "verdict": "VERDICT READY (stock preflight)" if ready else "VERDICT NOT READY",
            "ready": ready,
            "verified": verified,
            "pins_ok": True,
            "manifest_sha256": manifest_sha256,
            "boot_nonce": boot_nonce,
            "preflight_result_sha256": preflight_result_sha256,
            "camera_identity": cam_id,
        }
        out = sdir / f"{sid}.json"
        out.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
        return out

    def test_live_preflight_gate_rejects_mock_stale_wrong_body_and_invalidated(self) -> None:
        import time
        import studio_cli

        kit_dir, man = studio_cli._load_manifests()["zve1_202"]
        with tempfile.TemporaryDirectory() as td:
            sdir = Path(td)
            # 1. Mock READY session must not unlock live apply
            self._make_live_preflight_record(sdir, mode="mock", session_name="0001_mock")
            ok, rec, reason = studio_cli.validate_live_preflight_for_apply(sdir, "zve1_202", kit_dir, man)
            self.assertFalse(ok)
            self.assertIn("mock", reason.lower())

        with tempfile.TemporaryDirectory() as td:
            sdir = Path(td)
            # 2. Wrong body READY session must not unlock zve1_202
            self._make_live_preflight_record(sdir, body_id="fx3_702", session_name="0001_fx3")
            ok, _, reason = studio_cli.validate_live_preflight_for_apply(sdir, "zve1_202", kit_dir, man)
            self.assertFalse(ok)

        with tempfile.TemporaryDirectory() as td:
            sdir = Path(td)
            # 3. Applied state cannot pass fresh-apply preflight
            self._make_live_preflight_record(sdir, state="applied", session_name="0001_applied")
            ok, _, reason = studio_cli.validate_live_preflight_for_apply(sdir, "zve1_202", kit_dir, man)
            self.assertFalse(ok)

        with tempfile.TemporaryDirectory() as td:
            sdir = Path(td)
            # 4. Expired TTL rejected
            self._make_live_preflight_record(sdir, ts=time.time() - 3600, session_name="0001_old")
            ok, _, reason = studio_cli.validate_live_preflight_for_apply(sdir, "zve1_202", kit_dir, man)
            self.assertFalse(ok)
            self.assertIn("expired", reason.lower())

        with tempfile.TemporaryDirectory() as td:
            sdir = Path(td)
            # 5. Manifest SHA-256 mismatch rejected
            self._make_live_preflight_record(sdir, manifest_sha256="0" * 64, session_name="0001_man")
            ok, _, reason = studio_cli.validate_live_preflight_for_apply(sdir, "zve1_202", kit_dir, man)
            self.assertFalse(ok)

        with tempfile.TemporaryDirectory() as td:
            sdir = Path(td)
            # 6. Missing boot_nonce / invalid preflight_result_sha256 / DeviceInfo mismatch rejected
            self._make_live_preflight_record(sdir, boot_nonce="", session_name="0001_nononce")
            ok, _, _ = studio_cli.validate_live_preflight_for_apply(sdir, "zve1_202", kit_dir, man)
            self.assertFalse(ok)

        with tempfile.TemporaryDirectory() as td:
            sdir = Path(td)
            self._make_live_preflight_record(sdir, preflight_result_sha256="bad", session_name="0001_badsha")
            ok, _, _ = studio_cli.validate_live_preflight_for_apply(sdir, "zve1_202", kit_dir, man)
            self.assertFalse(ok)

        with tempfile.TemporaryDirectory() as td:
            sdir = Path(td)
            self._make_live_preflight_record(sdir, device_info_sha256="f" * 64, session_name="0001_baddev")
            ok, _, _ = studio_cli.validate_live_preflight_for_apply(sdir, "zve1_202", kit_dir, man)
            self.assertFalse(ok)

        with tempfile.TemporaryDirectory() as td:
            sdir = Path(td)
            # 7. Newer putback or mock run invalidates earlier live READY
            now = time.time()
            self._make_live_preflight_record(sdir, ts=now - 10, session_name="0001_live")
            (sdir / "session_0002_putback.json").write_text(
                json.dumps({
                    "session_id": "session_0002_putback",
                    "body_id": "zve1_202",
                    "kind": "putback",
                    "mode": "live_usb",
                    "state": "stock_unverified",
                    "ready": False,
                    "timestamp": now - 5,
                }),
                encoding="utf-8",
            )
            ok, _, _ = studio_cli.validate_live_preflight_for_apply(sdir, "zve1_202", kit_dir, man, now=now)
            self.assertFalse(ok)

        with tempfile.TemporaryDirectory() as td:
            sdir = Path(td)
            now = time.time()
            self._make_live_preflight_record(sdir, ts=now - 10, session_name="0001_live")
            (sdir / "session_0002_mock.json").write_text(
                json.dumps({
                    "session_id": "session_0002_mock",
                    "body_id": "zve1_202",
                    "kind": "preflight",
                    "mode": "mock",
                    "state": "stock",
                    "ready": True,
                    "timestamp": now - 5,
                }),
                encoding="utf-8",
            )
            ok, _, _ = studio_cli.validate_live_preflight_for_apply(sdir, "zve1_202", kit_dir, man, now=now)
            self.assertFalse(ok)

            # 8. latest-session --mode live_usb skips mock runs
            code, payload = studio_cli.cmd_latest_session("zve1_202", sdir, mode_filter="live_usb")
            self.assertEqual(code, 0)
            self.assertTrue(payload["found"])
            self.assertEqual(payload["mode"], "live_usb")

        with tempfile.TemporaryDirectory() as td:
            sdir = Path(td)
            now = time.time()
            self._make_live_preflight_record(sdir, ts=now, session_name="0001_valid")
            ok, rec, reason = studio_cli.validate_live_preflight_for_apply(sdir, "zve1_202", kit_dir, man, now=now)
            self.assertTrue(ok, reason)
            self.assertIsNotNone(rec)

    def test_step_runner_identity_guard_and_result_hash_gate(self) -> None:
        import ct1_common
        import studio_step_run

        with self.assertRaises(ct1_common.StopTest):
            studio_step_run.verify_connected_camera_identity(
                {"camera_usb_identity": {"serial_sha256": "a" * 64, "msc_usb_id": "054c:0da8"}},
                expect_serial_sha256="c" * 64,
            )
        with self.assertRaises(ct1_common.StopTest):
            studio_step_run.verify_connected_camera_identity(
                {"camera_usb_identity": {"serial_sha256": "a" * 64, "msc_usb_id": "054c:0da8"}},
                expect_msc_usb_id="054c:9999",
            )
        studio_step_run.verify_connected_camera_identity(
            {"camera_usb_identity": {"serial_sha256": "a" * 64, "msc_usb_id": "054c:0da8"}},
            expect_serial_sha256="a" * 64,
            expect_msc_usb_id="054c:0da8",
        )

    def test_live_apply_and_putback_fail_closed_under_fault_injection(self) -> None:
        from unittest import mock
        import studio_cli
        import studio_live_apply

        _, man = studio_cli._load_manifests()["zve1_202"]
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)

            def write_ct6_manifest(
                folder: Path,
                *,
                which: str,
                state: str,
                verdict: str,
                ready: bool = True,
                sha256: str = "e" * 64,
                outcome: str = "DONE",
                step_ok: bool = True,
                malformed: bool = False,
            ) -> None:
                folder.mkdir(parents=True, exist_ok=True)
                if malformed:
                    (folder / "manifest.json").write_text("{not json", encoding="utf-8")
                    return
                if which in ("dump", "check"):
                    s3 = {
                        "ready": ready,
                        "state": state,
                        "verdict": verdict,
                        "identity_differs": 0,
                        "problem_lines": [],
                    }
                else:
                    s3 = {"ok": step_ok, "outcome": outcome}
                payload = {
                    "status": "completed",
                    "results": {
                        "body_id": "zve1_202",
                        "which": which,
                        "ct6": {
                            "library_on_camera_after": False,
                            "result": {
                                "header_ok": True,
                                "complete": True,
                                "problems": 0,
                                "sha256": sha256,
                                "s3": s3,
                            },
                        },
                    },
                }
                (folder / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

            def run_apply_case(scenario: str) -> tuple[int, list[dict], list[tuple]]:
                sdir = base / f"s_{scenario}"
                ct6_root = base / f"ct6_{scenario}"
                sdir.mkdir(parents=True, exist_ok=True)
                ct6_root.mkdir(parents=True, exist_ok=True)
                ev_path = base / f"ev_{scenario}.jsonl"
                self._make_live_preflight_record(sdir, session_name="0001_valid")
                # Pre-existing stale READY CT6 folder must NEVER count as closing verification
                write_ct6_manifest(
                    ct6_root / "CT6_20261126_115900_stale",
                    which="dump",
                    state="applied",
                    verdict="VERDICT READY (open gate applied)",
                    sha256="f" * 64,
                )

                calls: list[tuple] = []
                step_counter = {"n": 0}

                def fake_wait_replug(timeout=900, *, ctx=None):
                    return scenario != "movie_replug_timeout"

                def fake_run_step_live(
                    body_id,
                    which,
                    firmware,
                    writes_memory,
                    *,
                    ctx=None,
                    require_result_sha=None,
                    expect_serial_sha256=None,
                    expect_msc_usb_id=None,
                ):
                    step_counter["n"] += 1
                    calls.append((which, require_result_sha, expect_serial_sha256, expect_msc_usb_id))
                    folder = ct6_root / f"CT6_20261126_1205{step_counter['n']:02d}_{which}"
                    if which == "dump":
                        if scenario == "dump_fails":
                            return 2
                        if scenario == "stale_only_no_new_folder":
                            return 0
                        if scenario == "malformed_dump":
                            write_ct6_manifest(folder, which="dump", state="applied", verdict="VERDICT READY (open gate applied)", malformed=True)
                            return 0
                        if scenario == "contradictory_stock":
                            write_ct6_manifest(folder, which="dump", state="stock", verdict="VERDICT READY (stock preflight)")
                            return 0
                        write_ct6_manifest(
                            folder,
                            which="dump",
                            state="applied",
                            verdict="VERDICT READY (open gate applied)",
                            sha256=f"{step_counter['n']:064x}",
                        )
                        return 0

                    if scenario == "partial_patch_step2" and step_counter["n"] == 2:
                        write_ct6_manifest(folder, which=which, state="stock", verdict="", outcome="ABORT", step_ok=False)
                        return 2
                    write_ct6_manifest(
                        folder,
                        which=which,
                        state="stock",
                        verdict="",
                        sha256=f"{step_counter['n']:064x}",
                        outcome="DONE",
                        step_ok=True,
                    )
                    return 0

                with (
                    mock.patch.object(studio_live_apply, "private_root", return_value=ct6_root),
                    mock.patch.object(studio_live_apply, "wait_for_drive", return_value=True),
                    mock.patch.object(studio_live_apply, "wait_for_replug", side_effect=fake_wait_replug),
                    mock.patch.object(studio_live_apply, "run_step_live", side_effect=fake_run_step_live),
                    studio_live_apply.RunContext(
                        events_file=ev_path,
                        firmware_confirmed=str(man["firmware"]),
                        confirm_volatile_ram=True,
                    ) as ctx,
                ):
                    rc = studio_live_apply.run_write_flow(
                        "apply",
                        "zve1_202",
                        man,
                        "mp4_3x2",
                        sdir,
                        dry_run=False,
                        no_movie_session=False,
                        no_closing_check=False,
                        ctx=ctx,
                    )
                return rc, self._read_jsonl(ev_path), calls

            for bad in (
                "movie_replug_timeout",
                "dump_fails",
                "stale_only_no_new_folder",
                "malformed_dump",
                "contradictory_stock",
                "partial_patch_step2",
            ):
                rc, evs, _ = run_apply_case(bad)
                self.assertNotEqual(rc, 0, f"{bad} unexpectedly exited 0: {evs[-1]}")
                self.assertEqual(evs[-1]["type"], "error", bad)

            rc_ok, evs_ok, calls_ok = run_apply_case("valid_dump")
            self.assertEqual(rc_ok, 0, evs_ok)
            self.assertEqual(evs_ok[-1]["type"], "complete")
            self.assertTrue(evs_ok[-1]["ok"])
            self.assertTrue(evs_ok[-1]["ready"])
            self.assertTrue(evs_ok[-1]["verified"])
            self.assertEqual(evs_ok[-1]["state"], "applied")
            # Assert same-boot result SHA chaining and camera identity pinning
            self.assertEqual(calls_ok[0][1], "a" * 64)
            self.assertEqual(calls_ok[0][2], "b" * 64)
            self.assertEqual(calls_ok[0][3], "054c:0da8")
            self.assertEqual(calls_ok[1][1], f"{1:064x}")
            self.assertEqual(calls_ok[-1][0], "dump")
            self.assertEqual(calls_ok[-1][1], f"{len(calls_ok) - 1:064x}")

            # Verify live putback closing stock_check pass vs contradictory / timeout / skipped fail closed
            for put_case in ("put_valid", "put_contradictory", "put_check_timeout", "put_nocheck"):
                sdir = base / f"s_{put_case}"
                ct6_root = base / f"ct6_{put_case}"
                sdir.mkdir(parents=True, exist_ok=True)
                ct6_root.mkdir(parents=True, exist_ok=True)
                ev_path = base / f"ev_{put_case}.jsonl"
                n_step = {"n": 0}

                def fake_put_wait_drive(body_id, first, timeout=600, *, ctx=None, step_index=None, total_steps=None, step_id=None):
                    if put_case == "put_check_timeout" and step_id == "check":
                        return False
                    return True

                def fake_put_step(
                    body_id,
                    which,
                    firmware,
                    writes_memory,
                    *,
                    ctx=None,
                    require_result_sha=None,
                    expect_serial_sha256=None,
                    expect_msc_usb_id=None,
                ):
                    n_step["n"] += 1
                    folder = ct6_root / f"CT6_20261126_1208{n_step['n']:02d}_{which}"
                    if which == "check":
                        verdict = "VERDICT READY (open gate applied)" if put_case == "put_contradictory" else "VERDICT READY (stock preflight)"
                        state = "applied" if put_case == "put_contradictory" else "stock"
                        write_ct6_manifest(folder, which="check", state=state, verdict=verdict, sha256=f"{n_step['n']:064x}")
                    else:
                        write_ct6_manifest(folder, which=which, state="stock", verdict="", sha256=f"{n_step['n']:064x}", outcome="DONE", step_ok=True)
                    return 0

                with (
                    mock.patch.object(studio_live_apply, "private_root", return_value=ct6_root),
                    mock.patch.object(studio_live_apply, "wait_for_drive", side_effect=fake_put_wait_drive),
                    mock.patch.object(studio_live_apply, "run_step_live", side_effect=fake_put_step),
                    studio_live_apply.RunContext(
                        events_file=ev_path,
                        firmware_confirmed=str(man["firmware"]),
                        confirm_volatile_ram=True,
                    ) as ctx,
                ):
                    rc = studio_live_apply.run_write_flow(
                        "putback",
                        "zve1_202",
                        man,
                        "mp4_3x2",
                        sdir,
                        dry_run=False,
                        no_movie_session=False,
                        no_closing_check=(put_case == "put_nocheck"),
                        ctx=ctx,
                    )
                evs = self._read_jsonl(ev_path)
                if put_case == "put_valid":
                    self.assertEqual(rc, 0, evs)
                    self.assertEqual(evs[-1]["type"], "complete")
                    self.assertTrue(evs[-1]["verified"])
                    self.assertEqual(evs[-1]["state"], "stock")
                else:
                    self.assertNotEqual(rc, 0, f"{put_case} should fail closed: {evs}")
                    self.assertEqual(evs[-1]["type"], "error")

    def test_support_matrix_is_in_sync_with_docs(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "generate_support_matrix.py"), "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)

    def test_macos_takeover_waits_retries_and_serial_unwrap(self) -> None:
        import hashlib
        import types
        from unittest import mock

        import ct1_stage2_service as s2

        class FakeUSBError(Exception):
            pass

        class FakeSession:
            def __init__(self) -> None:
                self.results: dict = {}
                self.notes: list[str] = []
                self.says: list[str] = []

            def log(self, kind: str, **kw) -> None:
                self.notes.append(f"{kind}:{kw.get('text', '')}")

            def say(self, text: str) -> None:
                self.says.append(text)

        class FakeDev:
            def __init__(self, tag: str, serial: str = "SN-TEST-001") -> None:
                self.tag = tag
                self.iSerialNumber = 3
                self.serial = serial

        class FakeDriver:
            def __init__(self, dev: FakeDev) -> None:
                self.backend = types.SimpleNamespace(dev=dev)
                self.reset_calls = 0

            def reset(self) -> None:
                self.reset_calls += 1

        fake_usb_core = types.ModuleType("usb.core")
        fake_usb_core.USBError = FakeUSBError
        fake_usb_util = types.ModuleType("usb.util")
        fake_usb_util.get_string = lambda raw, idx: getattr(raw, "serial", None)
        fake_usb_pkg = types.ModuleType("usb")
        fake_usb_pkg.core = fake_usb_core
        fake_usb_pkg.util = fake_usb_util

        with mock.patch.dict(
            sys.modules,
            {"usb": fake_usb_pkg, "usb.core": fake_usb_core, "usb.util": fake_usb_util},
        ):
            # 1) _safe_usb_serial_sha256 unwraps .handle -> SHA-256
            dev_obj = FakeDev("h", serial="  ZV-E1-999  ")
            wrapped = types.SimpleNamespace(handle=dev_obj, idVendor=0x054C, idProduct=0x0E72)
            self.assertEqual(
                s2._safe_usb_serial_sha256(wrapped),
                hashlib.sha256(b"ZV-E1-999").hexdigest(),
            )

            # 2) Polls past IOUSBMassStorageInterfaceNub and retries transient claim_interface error
            ioreg_seq = iter([
                [{"service": "IOUSBMassStorageInterfaceNub"}],
                [{"service": "IOUSBMassStorageInterfaceNub"}],
                [{"service": "none"}],
            ])
            claim_attempts = {"n": 0}

            def claim_transient(dev, iface):
                claim_attempts["n"] += 1
                if claim_attempts["n"] < 3:
                    raise FakeUSBError("Other error")

            fake_usb_util.claim_interface = claim_transient
            fake_usb_util.dispose_resources = lambda dev: None

            sess1 = FakeSession()
            drv1 = FakeDriver(FakeDev("d1"))
            with (
                mock.patch("os.geteuid", return_value=0),
                mock.patch.object(s2.c, "unmount_sony_disks"),
                mock.patch.object(s2.c, "ioreg_sony_devices", side_effect=lambda: next(ioreg_seq)),
                mock.patch("time.sleep"),
            ):
                ret1 = s2.take_over_from_macos(sess1, drv1)
            self.assertIs(ret1, drv1)
            self.assertEqual(claim_attempts["n"], 3)
            self.assertEqual(drv1.reset_calls, 1)

            # 3) Disposes stale dev and re-opens via libusb_devices + MscContext().openDevice when stuck
            stale_dev = FakeDev("stale")
            fresh_dev = FakeDev("fresh", serial="REENUM-123")
            drv_stale = FakeDriver(stale_dev)
            drv_fresh = FakeDriver(fresh_dev)
            disposed: list[str] = []

            def claim_reopen(dev, iface):
                if dev is stale_dev:
                    raise FakeUSBError("Other error")

            fake_usb_util.claim_interface = claim_reopen
            fake_usb_util.dispose_resources = lambda dev: disposed.append(dev.tag)

            fake_msc_ctx = mock.MagicMock()
            fake_msc_ctx.openDevice.return_value = drv_fresh
            fake_pmca_libusb = types.ModuleType("pmca.usb.driver.generic.libusb")
            fake_pmca_libusb.MscContext = lambda: fake_msc_ctx
            fake_pmca_libusb.VendorSpecificContext = mock.MagicMock()
            fake_pmca_generic = types.ModuleType("pmca.usb.driver.generic")
            fake_pmca_generic.libusb = fake_pmca_libusb

            with (
                mock.patch.dict(
                    sys.modules,
                    {
                        "pmca.usb.driver.generic": fake_pmca_generic,
                        "pmca.usb.driver.generic.libusb": fake_pmca_libusb,
                    },
                ),
                mock.patch("os.geteuid", return_value=0),
                mock.patch.object(s2.c, "unmount_sony_disks"),
                mock.patch.object(s2.c, "ioreg_sony_devices", return_value=[{"service": "none"}]),
                mock.patch.object(s2, "libusb_devices", return_value=([wrapped], [])),
                mock.patch("time.sleep"),
            ):
                ret2 = s2.take_over_from_macos(FakeSession(), drv_stale)
            self.assertIs(ret2, drv_fresh)
            self.assertEqual(disposed, ["stale"])

            # 4) connect() reads serial only AFTER take_over_from_macos (not before)
            call_order: list[str] = []

            def record_takeover(session, inner):
                call_order.append("takeover")
                return drv_fresh

            def record_get_string(raw, idx):
                call_order.append("serial")
                return getattr(raw, "serial", None)

            fake_usb_util.get_string = record_get_string
            fake_pmca_usb = types.ModuleType("pmca.usb")
            fake_msc_dev = mock.MagicMock()
            fake_msc_dev.getDeviceInfo.return_value = types.SimpleNamespace(manufacturer="Sony", model="DSC")
            fake_pmca_usb.MscDevice = lambda inner: fake_msc_dev
            fake_pmca_sony = types.ModuleType("pmca.usb.sony")
            fake_pmca_sony.isSonyMscCamera = lambda info: True
            fake_msc_handle = types.SimpleNamespace(
                handle=FakeDev("msc0", serial="PRE-TAKEOVER"),
                idVendor=0x054C,
                idProduct=0x0E72,
            )
            fake_senser_handle = types.SimpleNamespace(
                handle=FakeDev("svc0", serial="REENUM-123"),
                idVendor=0x054C,
                idProduct=0x0E72,
            )
            sess_conn = FakeSession()
            with (
                mock.patch.dict(
                    sys.modules,
                    {
                        "pmca.usb": fake_pmca_usb,
                        "pmca.usb.sony": fake_pmca_sony,
                        "pmca.usb.driver.generic": fake_pmca_generic,
                        "pmca.usb.driver.generic.libusb": fake_pmca_libusb,
                    },
                ),
                mock.patch.object(sys, "platform", "darwin"),
                mock.patch.object(s2.c, "use_pmca"),
                mock.patch.object(s2.c, "print_pnp", return_value=[]),
                mock.patch.object(s2, "libusb_devices", return_value=([fake_msc_handle], [])),
                mock.patch.object(s2, "take_over_from_macos", side_effect=record_takeover),
                mock.patch.object(s2, "phase_a"),
                mock.patch.object(s2, "wait_for_service_device", return_value=fake_senser_handle),
            ):
                s2.connect(sess_conn)
            self.assertGreaterEqual(len(call_order), 2)
            self.assertEqual(call_order[:2], ["takeover", "serial"])
            self.assertEqual(
                sess_conn.results["camera_usb_identity"]["serial_sha256"],
                hashlib.sha256(b"REENUM-123").hexdigest(),
            )

            # 5) Persistent Other error on claim_interface includes Removable Volumes & Terminal fallback guidance
            def claim_always_other(dev, iface):
                raise FakeUSBError("[Errno None] Other error")

            fake_usb_util.claim_interface = claim_always_other
            fake_usb_util.dispose_resources = lambda dev: None
            drv_fail = FakeDriver(FakeDev("fail"))
            with (
                mock.patch("os.geteuid", return_value=0),
                mock.patch.object(s2.c, "unmount_sony_disks"),
                mock.patch.object(s2.c, "ioreg_sony_devices", return_value=[{"service": "none"}]),
                mock.patch.object(s2, "libusb_devices", return_value=([], [])),
                mock.patch("time.sleep"),
                self.assertRaises(s2.c.StopTest) as cm_fail,
            ):
                s2.take_over_from_macos(FakeSession(), drv_fail)
            self.assertIn("Removable Volumes", str(cm_fail.exception))
            self.assertIn("Use Terminal Instead", str(cm_fail.exception))


if __name__ == "__main__":
    unittest.main()
