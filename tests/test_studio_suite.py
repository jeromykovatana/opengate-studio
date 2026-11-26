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


class CleanRoomTests(unittest.TestCase):
    def test_clean_room_passes(self) -> None:
        res = vcr.verify_clean_room(REPO_ROOT)
        self.assertTrue(res["ok"], f"Clean-room errors: {res['errors']}")
        self.assertEqual(res["checked_manifests"], 3)
        self.assertEqual(res["checked_so"], 62)
        self.assertGreaterEqual(res["checked_pmca_files"], 15)


if __name__ == "__main__":
    unittest.main()
