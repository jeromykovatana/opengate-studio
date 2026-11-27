#!/usr/bin/env python3
"""Tests for express single-session workflow, MultiStepGuard batching, and USB detection."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_DIR = REPO_ROOT / "cli"
CT1_DIR = REPO_ROOT / "transport" / "camera_tests" / "CT1_usb_first_contact"
CT6_DIR = REPO_ROOT / "transport" / "camera_tests" / "CT6_memory_read_check"

for p in (CLI_DIR, CT1_DIR, CT6_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ct1_common as c  # noqa: E402
import ct6_level1_run as R  # noqa: E402
import studio_cli  # noqa: E402
import studio_live_apply as sla  # noqa: E402
import studio_step_run as ssr  # noqa: E402

STUDIO_CLI = CLI_DIR / "studio_cli.py"
LIVE_APPLY = CLI_DIR / "studio_live_apply.py"


def _build_readonly_result_bytes(body_id: str, which: str, mode: str) -> bytes:
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
            st = "STOCK"
        elif mode == "applied":
            if site["soft"] and name in ("outsize_guard0", "outsize_guard1"):
                st = "STOCK"
            elif site["soft"] and name == "stored_record":
                st = "TARGET"
            elif body_id == "zve1_202" and name == "screen0":
                st = "STOCK"
            else:
                st = "TARGET"
        else:
            st = "OTHER"
        if length <= 16:
            lines.append(f"site {name} {addr} len {length} bytes {'00' * length}  {st}")
        else:
            lines.append(f"site {name} {addr} len {length} bytes differing from stock 0  {st}")
    lines.append("== main-processor sites: libmpr.so in this process")
    mp_st = "STOCK" if mode == "stock" else "TARGET"
    for i in range(spec["lm_sites"]):
        lines.append(f"lm {0x100000 + i * 4:#x} at {0x7f10000000 + i * 4:#x} bytes 00000000  {mp_st}")
    lines.append("== main-processor sites: av-cam.bin in kernel memory")
    for i, g in enumerate(spec["av_guards"]):
        lines.append(f"guard {g} {0x380000 + i * 0x100:#x} len 48  SAME")
    for i in range(spec["av_sites"]):
        lines.append(f"av {0x200000 + i * 4:#x} bytes 00000000  {mp_st}")
    lines.append("== summary")
    if mode == "stock":
        lines.append("VERDICT READY (stock preflight)")
    elif mode == "applied":
        lines.append("VERDICT READY (open gate applied)")
    else:
        lines.append("VERDICT NOT READY (warm power-switch mixed state)")
    lines.append("== done")
    lines.append("")
    return "\n".join(lines).encode("utf8")


class ExpressStepAndGuardTests(unittest.TestCase):
    def test_step_level_and_fused_write_result_parsing(self) -> None:
        self.assertEqual(ssr.step_level("Q19"), 1119)
        self.assertEqual(ssr.step_level("Q20"), 1120)
        self.assertEqual(ssr.step_level("F19"), 1219)
        self.assertEqual(ssr.step_level("F20"), 1220)

        q19_done = ssr.parse_write_result(
            "Q19",
            "fused safe_daily",
            b"readcheck 1 level 19\neuid 0\n== level 19: fused safe_daily\nDONE: every site holds the target bytes (fused safe_daily)\n== done, bytes written before this line: 120\n",
        )
        self.assertTrue(q19_done["header_ok"])
        self.assertTrue(q19_done["complete"])
        self.assertTrue(q19_done["s3"]["ok"])
        self.assertEqual(q19_done["s3"]["outcome"], "DONE")

        f20_ntd = ssr.parse_write_result(
            "F20",
            "fused cinema_full putback",
            b"readcheck 1 level 20\neuid 0\n== level 20: fused cinema_full\nNOTHING TO DO: every site already holds the target bytes (fused cinema_full)\n== done, bytes written before this line: 120\n",
        )
        self.assertTrue(f20_ntd["header_ok"])
        self.assertTrue(f20_ntd["s3"]["ok"])
        self.assertEqual(f20_ntd["s3"]["outcome"], "NOTHING TO DO")

        q19_mixed = ssr.parse_write_result(
            "Q19",
            "fused safe_daily",
            b"readcheck 1 level 19\neuid 0\n== level 19: fused safe_daily\n!! warm power-switch mixed state (coprocessor stock, encoder patched); pull battery >= 10s; nothing is written\n== done, bytes written before this line: 120\n",
        )
        self.assertFalse(q19_mixed["s3"]["ok"])
        self.assertEqual(q19_mixed["problems"], 1)

    def test_valid_toolkit_header_check(self) -> None:
        self.assertTrue(ssr.has_valid_toolkit_result_header(b"readcheck 1 level 19\neuid 0\n", "zve1_202"))
        self.assertTrue(ssr.has_valid_toolkit_result_header(b"zvread zvread_v4 check for ZV-E1 2.02; read-only\n", "zve1_202"))
        self.assertTrue(ssr.has_valid_toolkit_result_header(b"s3read s3read_v9 check\n", "a7s3_501"))
        self.assertTrue(ssr.has_valid_toolkit_result_header(b"fx3read fx3read_v2 check\n", "fx3_702"))
        self.assertTrue(ssr.has_valid_toolkit_result_header(b"a7cread a7cread_v1 check\n", "a7c_203"))
        self.assertTrue(ssr.has_valid_toolkit_result_header(b"zve10read zve10read_v1 check\n", "zve10_203"))
        self.assertFalse(ssr.has_valid_toolkit_result_header(b"old unknown result\n", "zve1_202"))
        self.assertFalse(ssr.has_valid_toolkit_result_header(b"", "zve1_202"))

    def test_multistep_guard_batch_transport_and_refusals(self) -> None:
        kit_dir, man = ssr.load_body_manifest("zve1_202")
        pins, _ = ssr.step_pins(man)
        steps = ["check", "L13", "L5", "check"]
        libs = {sid: (kit_dir / pins[sid][0]).read_bytes() for sid in set(steps)}
        sha_to_sid = {c.sha256(blob): sid for sid, blob in libs.items()}
        seen_calls: list[str] = []

        def _result_fn(blob: bytes) -> tuple[bytes, str]:
            sid = sha_to_sid[c.sha256(blob)]
            seen_calls.append(sid)
            if sid == "check":
                mode = "stock" if seen_calls.count("check") == 1 else "applied"
                return _build_readonly_result_bytes("zve1_202", "check", mode), "synthetic"
            lvl = sid[1:]
            return (
                f"readcheck 1 level {lvl}\neuid 0\n== level {lvl}\nDONE: every site holds the target bytes\n== done, bytes written before this line: 0\n".encode("utf8"),
                "synthetic",
            )

        with tempfile.TemporaryDirectory() as td:
            priv_root = Path(td) / "camera_private"
            # 1. Batch succeeds in 1 session, cleans leftover known lib + valid prior result, invokes callbacks
            sim = ssr.make_sim_multi(
                libs,
                body_id="zve1_202",
                files={
                    R.LIB_PATH.decode(): libs["L13"],
                    "/tmp_wbshd/readcheck_result.txt": b"readcheck 1 level 5\neuid 0\n",
                },
                result_fn=_result_fn,
            )
            cb_starts: list[str] = []
            cb_results: list[tuple[str, str]] = []
            with contextlib.redirect_stdout(io.StringIO()):
                res = ssr.run_batch_single_session(
                    "zve1_202",
                    steps,
                    "2.02",
                    writes_memory=True,
                    express=True,
                    on_step_start=lambda idx, tot, sid, _sum: cb_starts.append(f"{idx}/{tot}:{sid}"),
                    on_step_result=lambda _idx, _tot, sid, facts, _out: cb_results.append(
                        (sid, facts["s3"].get("state") or facts["s3"].get("outcome"))
                    )
                    is None,
                    sim_driver=sim,
                    settle_seconds=0.0,
                    session_root=priv_root,
                )
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["steps_run"], steps)
            self.assertEqual(cb_starts, ["1/4:check", "2/4:L13", "3/4:L5", "4/4:check"])
            self.assertEqual(cb_results, [("check", "stock"), ("L13", "DONE"), ("L5", "DONE"), ("check", "applied")])
            self.assertEqual(sim.loads, 4)
            self.assertEqual(sim.unexpected, [])
            self.assertNotIn(R.LIB_PATH.decode(), sim.fs)
            # auth.stop() vendor request sent ONCE at end
            stop_reqs = [vr for vr in sim.vendor_requests if vr[:3] == (1, 0xC800, 0x2855)]
            self.assertEqual(len(stop_reqs), 1)
            # CT6 session directory recorded
            self.assertTrue((priv_root / res["ct6_session"] / "manifest.json").is_file())

            # 2. Unrecognized existing result file must fail closed with 0 writes
            sim_bad_res = ssr.make_sim_multi(
                libs,
                body_id="zve1_202",
                files={"/tmp_wbshd/readcheck_result.txt": b"unrecognized foreign header\n"},
                result_fn=_result_fn,
            )
            with contextlib.redirect_stdout(io.StringIO()):
                bad_res = ssr.run_batch_single_session(
                    "zve1_202",
                    ["L13"],
                    "2.02",
                    writes_memory=True,
                    express=True,
                    sim_driver=sim_bad_res,
                    settle_seconds=0.0,
                )
            self.assertFalse(bad_res["ok"])
            self.assertEqual(sim_bad_res.loads, 0)

            # 3. Single-step Guard still refuses second write in body_run
            ssr.use("zve1_202", "V19")
            lib_v19 = (kit_dir / pins["V19"][0]).read_bytes()
            s_dup, _sim_dup, stopped_dup = R.simulate(
                lib_v19,
                lambda _s, cam, _l: (
                    R.select(cam, R.LIB_PATH),
                    R.command(cam, R.SET_FILE2, b"\x00\xff\x00" + lib_v19),
                    R.select(cam, R.LIB_PATH),
                    R.command(cam, R.SET_FILE2, b"\x00\xff\x00" + lib_v19),
                ),
            )
            self.assertTrue(stopped_dup and "second file write" in stopped_dup)
            self.assertEqual(R.sent(s_dup).count("SET_FILE2"), 1)


class ExpressLiveApplyOrchestratorTests(unittest.TestCase):
    def test_simulate_express_flow_all_bodies_and_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for body_id, fw, packs in (
                ("zve1_202", "2.02", "mp4_3x2,screen_3x2"),
                ("a7s3_501", "5.01", "mp4_3x2,screen_3x2,hdmi32,high_bitrate,xavc_si"),
                ("fx3_702", "7.02", "mp4_3x2,fx3_playback"),
                ("a7c_203", "2.03", "core_open_gate"),
                ("zve10_203", "2.03", "raster_2560"),
            ):
                ev_app = root / f"{body_id}_app.jsonl"
                proc = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(LIVE_APPLY),
                        "express-apply",
                        "--body",
                        body_id,
                        "--packs",
                        packs,
                        "--session-dir",
                        str(root / "sess"),
                        "--firmware-confirmed",
                        fw,
                        "--confirm-volatile-ram",
                        "--events-file",
                        str(ev_app),
                        "--dry-run",
                        "--simulate-events",
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
                evs = [json.loads(ln) for ln in ev_app.read_text(encoding="utf8").splitlines() if ln.strip()]
                types = [e["type"] for e in evs]
                self.assertEqual(types[0], "plan")
                self.assertFalse(evs[0]["closing_dump"])
                self.assertNotIn("wait_movie_replug", types)
                self.assertEqual(types.count("wait_drive"), 1)
                self.assertEqual(types[-1], "complete")
                self.assertEqual(evs[-1]["action"], "express-apply")
                self.assertTrue(evs[-1]["ok"])
                self.assertTrue(evs[-1]["ready"])
                self.assertTrue(evs[-1]["verified"])
                self.assertEqual(evs[-1]["state"], "applied")

                ev_put = root / f"{body_id}_put.jsonl"
                proc_put = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(LIVE_APPLY),
                        "express-putback",
                        "--body",
                        body_id,
                        "--packs",
                        packs,
                        "--session-dir",
                        str(root / "sess"),
                        "--firmware-confirmed",
                        fw,
                        "--confirm-volatile-ram",
                        "--events-file",
                        str(ev_put),
                        "--dry-run",
                        "--simulate-events",
                    ],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(proc_put.returncode, 0, proc_put.stderr + proc_put.stdout)
                evs_put = [json.loads(ln) for ln in ev_put.read_text(encoding="utf8").splitlines() if ln.strip()]
                self.assertEqual(evs_put[-1]["action"], "express-putback")
                self.assertEqual(evs_put[-1]["state"], "stock")
                self.assertEqual(evs_put[-1]["closing_kind"], "stock_check")

            # Missing --confirm-volatile-ram must refuse
            proc_refuse = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(LIVE_APPLY),
                    "express-apply",
                    "--body",
                    "zve1_202",
                    "--firmware-confirmed",
                    "2.02",
                    "--dry-run",
                    "--simulate-events",
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc_refuse.returncode, 0)

            # Cancel file exits 130 cleanly
            cflag = root / "cancel.flag"
            cflag.write_text("1", encoding="utf8")
            ev_can = root / "cancel.jsonl"
            proc_can = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(LIVE_APPLY),
                    "express-apply",
                    "--body",
                    "zve1_202",
                    "--firmware-confirmed",
                    "2.02",
                    "--confirm-volatile-ram",
                    "--events-file",
                    str(ev_can),
                    "--cancel-file",
                    str(cflag),
                    "--dry-run",
                    "--simulate-events",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_can.returncode, 130)
            evs_can = [json.loads(ln) for ln in ev_can.read_text(encoding="utf8").splitlines() if ln.strip()]
            self.assertEqual(evs_can[-1]["type"], "cancelled")

    def test_express_live_batch_and_fused_flows_with_sim_driver(self) -> None:
        kit_dir, man = ssr.load_body_manifest("zve1_202")
        pins, _ = ssr.step_pins(man)

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            # 1. Custom packs (non-fused) express-apply -> ["check", L13, L5, L16, V19, "check"] in 1 session
            sdir = base / "sess_batch"
            priv = base / "priv_batch"
            ev_path = base / "ev_batch.jsonl"
            steps_needed = ["check", "L13", "L5", "L16", "V19"]
            libs = {sid: (kit_dir / pins[sid][0]).read_bytes() for sid in steps_needed}
            sha_to_sid = {c.sha256(b): sid for sid, b in libs.items()}
            chk_calls = {"n": 0}

            def res_batch(blob: bytes) -> tuple[bytes, str]:
                sid = sha_to_sid[c.sha256(blob)]
                if sid == "check":
                    chk_calls["n"] += 1
                    mode = "stock" if chk_calls["n"] == 1 else "applied"
                    return _build_readonly_result_bytes("zve1_202", "check", mode), "synthetic"
                lvl = sid[1:]
                return (
                    f"readcheck 1 level {lvl}\neuid 0\n== level {lvl}\nDONE: every site holds the target bytes\n== done, bytes written before this line: 0\n".encode("utf8"),
                    "synthetic",
                )

            sim = ssr.make_sim_multi(libs, body_id="zve1_202", result_fn=res_batch)
            with (
                mock.patch.object(sla, "private_root", return_value=priv),
                sla.RunContext(events_file=ev_path, firmware_confirmed="2.02", confirm_volatile_ram=True) as ctx,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                rc = sla.run_express_flow(
                    "express-apply",
                    "zve1_202",
                    man,
                    "mp4_3x2",
                    sdir,
                    dry_run=False,
                    ctx=ctx,
                    sim_driver=sim,
                    settle_seconds=0.0,
                )
            self.assertEqual(rc, 0)
            evs = [json.loads(ln) for ln in ev_path.read_text(encoding="utf8").splitlines() if ln.strip()]
            self.assertEqual(evs[0]["closing_dump"], False)
            self.assertNotIn("wait_movie_replug", [e["type"] for e in evs])
            self.assertEqual([e["type"] for e in evs].count("wait_drive"), 1)
            self.assertEqual(evs[-1]["type"], "complete")
            self.assertEqual(evs[-1]["state"], "applied")
            self.assertEqual(evs[-1]["steps_run"], ["L13", "L5", "L16", "V19"])
            self.assertTrue(evs[-1]["verified"])
            _, latest = studio_cli.cmd_latest_session("zve1_202", sdir, mode_filter="live_usb")
            self.assertEqual(latest["kind"], "express_apply")
            self.assertEqual(latest["state"], "applied")

            # 2. Initial check NOT READY (mixed_powerswitch) must abort with 0 write loads
            sdir_mix = base / "sess_mix"
            ev_mix = base / "ev_mix.jsonl"
            sim_mix = ssr.make_sim_multi(
                libs,
                body_id="zve1_202",
                result_fn=lambda _b: (_build_readonly_result_bytes("zve1_202", "check", "mixed"), "synthetic"),
            )
            with (
                mock.patch.object(sla, "private_root", return_value=base / "priv_mix"),
                sla.RunContext(events_file=ev_mix, firmware_confirmed="2.02", confirm_volatile_ram=True) as ctx,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                rc_mix = sla.run_express_flow(
                    "express-apply",
                    "zve1_202",
                    man,
                    "mp4_3x2",
                    sdir_mix,
                    dry_run=False,
                    ctx=ctx,
                    sim_driver=sim_mix,
                    settle_seconds=0.0,
                )
            self.assertEqual(rc_mix, 1)
            self.assertEqual(sim_mix.loads, 1)  # ONLY initial check loaded, 0 write steps
            evs_mix = [json.loads(ln) for ln in ev_mix.read_text(encoding="utf8").splitlines() if ln.strip()]
            self.assertEqual(evs_mix[-1]["type"], "error")

            # 3. Fused 1-step flow (Q19/Q20) using temporary kit copy with fused_presets
            fake_kits = base / "kits"
            fake_kit_zv = fake_kits / "zve1_202"
            shutil.copytree(kit_dir, fake_kit_zv)
            # Reuse pinned V19/V20 binaries as stand-ins for Q19/Q20 in isolated temp kit dir
            q19_so = fake_kit_zv / "libJit_zv_Q19.so"
            q20_so = fake_kit_zv / "libJit_zv_Q20.so"
            shutil.copy2(fake_kit_zv / pins["V19"][0], q19_so)
            shutil.copy2(fake_kit_zv / pins["V20"][0], q20_so)
            man_fused = json.loads((fake_kit_zv / "manifest.json").read_text(encoding="utf8"))
            man_fused["steps"]["Q19"] = {
                "file": q19_so.name,
                "sha256": hashlib.sha256(q19_so.read_bytes()).hexdigest(),
                "size": q19_so.stat().st_size,
                "level": 19,
                "summary": "Fused Safe Daily 3:2 apply",
            }
            man_fused["steps"]["Q20"] = {
                "file": q20_so.name,
                "sha256": hashlib.sha256(q20_so.read_bytes()).hexdigest(),
                "size": q20_so.stat().st_size,
                "level": 20,
                "summary": "Fused Safe Daily 3:2 putback",
            }
            man_fused["fused_presets"] = {
                "safe_daily": {
                    "packs": ["core_open_gate", "mp4_3x2", "screen_3x2"],
                    "apply_step": "Q19",
                    "putback_step": "Q20",
                }
            }
            (fake_kit_zv / "manifest.json").write_text(json.dumps(man_fused, indent=2), encoding="utf8")

            sdir_f = base / "sess_fused"
            ev_f = base / "ev_fused.jsonl"
            sim_f = ssr.make_sim_multi(
                {"Q19": q19_so.read_bytes(), "Q20": q20_so.read_bytes()},
                body_id="zve1_202",
                result_fn=lambda b: (
                    (
                        b"readcheck 1 level 19\neuid 0\n== level 19: fused safe_daily\nDONE: every site holds the target bytes (fused safe_daily)\n== done, bytes written before this line: 0\n"
                        if hashlib.sha256(b).hexdigest() == man_fused["steps"]["Q19"]["sha256"]
                        else b"readcheck 1 level 20\neuid 0\n== level 20: fused safe_daily\nDONE: every site holds the target bytes (fused safe_daily)\n== done, bytes written before this line: 0\n"
                    ),
                    "synthetic",
                ),
            )
            with (
                mock.patch.object(studio_cli, "KITS_DIR", fake_kits),
                mock.patch.object(ssr, "KITS_DIR", fake_kits),
                mock.patch.object(sla, "private_root", return_value=base / "priv_fused"),
                sla.RunContext(events_file=ev_f, firmware_confirmed="2.02", confirm_volatile_ram=True) as ctx,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                rc_f = sla.run_express_flow(
                    "express-apply",
                    "zve1_202",
                    man_fused,
                    "mp4_3x2,screen_3x2",
                    sdir_f,
                    dry_run=False,
                    ctx=ctx,
                    sim_driver=sim_f,
                    settle_seconds=0.0,
                )
            self.assertEqual(rc_f, 0)
            self.assertEqual(sim_f.loads, 1)
            evs_f = [json.loads(ln) for ln in ev_f.read_text(encoding="utf8").splitlines() if ln.strip()]
            self.assertEqual(evs_f[0]["closing_kind"], "fused_readback")
            self.assertEqual(evs_f[-1]["steps_run"], ["Q19"])
            self.assertEqual(evs_f[-1]["closing_kind"], "fused_readback")
            self.assertEqual(evs_f[-1]["state"], "applied")

            # Fused express-putback runs Q20 in 1 step (new USB session -> fresh SimDriver)
            ev_fp = base / "ev_fused_put.jsonl"
            sim_fp = ssr.make_sim_multi(
                {"Q19": q19_so.read_bytes(), "Q20": q20_so.read_bytes()},
                body_id="zve1_202",
                result_fn=lambda _b: (
                    b"readcheck 1 level 20\neuid 0\n== level 20: fused safe_daily\nDONE: every site holds the target bytes (fused safe_daily)\n== done, bytes written before this line: 0\n",
                    "synthetic",
                ),
            )
            with (
                mock.patch.object(studio_cli, "KITS_DIR", fake_kits),
                mock.patch.object(ssr, "KITS_DIR", fake_kits),
                mock.patch.object(sla, "private_root", return_value=base / "priv_fused_put"),
                sla.RunContext(events_file=ev_fp, firmware_confirmed="2.02", confirm_volatile_ram=True) as ctx,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                rc_fp = sla.run_express_flow(
                    "express-putback",
                    "zve1_202",
                    man_fused,
                    None,
                    sdir_f,
                    dry_run=False,
                    ctx=ctx,
                    sim_driver=sim_fp,
                    settle_seconds=0.0,
                )
            self.assertEqual(rc_fp, 0)
            self.assertEqual(sim_fp.loads, 1)
            evs_fp = [json.loads(ln) for ln in ev_fp.read_text(encoding="utf8").splitlines() if ln.strip()]
            self.assertEqual(evs_fp[-1]["action"], "express-putback")
            self.assertEqual(evs_fp[-1]["steps_run"], ["Q20"])
            self.assertEqual(evs_fp[-1]["state"], "stock")
            self.assertEqual(evs_fp[-1]["closing_kind"], "stock_check")


class StudioCliExpressAndUsbDetectTests(unittest.TestCase):
    @staticmethod
    def _run_cli(*args: str, env: dict[str, str] | None = None) -> tuple[int, dict]:
        proc_env = dict(os.environ)
        if env:
            proc_env.update(env)
        proc = subprocess.run(
            [sys.executable, "-B", str(STUDIO_CLI), *args],
            capture_output=True,
            text=True,
            encoding="utf8",
            env=proc_env,
        )
        return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else {})

    def test_detect_usb_camera_ioreg_parsing(self) -> None:
        sample_tpl = (
            "+-o Root  <class IORegistryEntry>\n"
            "  +-o AppleUSBXHCI@01000000  <class AppleUSBHostController>\n"
            "    +-o {prod}@01100000  <class IOUSBHostDevice, id 0x100000100, registered, matched, active, retain 10>\n"
            "      | {{\n"
            "      |   \"idVendor\" = 1356\n"
            "      |   \"idProduct\" = {pid}\n"
            "      |   \"USB Product Name\" = \"{prod}\"\n"
            "      | }}\n"
            "      +-o IOUSBHostInterface@0  <class IOUSBHostInterface>\n"
            "        | {{\n"
            "        |   \"bInterfaceClass\" = {iface_cls}\n"
            "        | }}\n"
        )
        with tempfile.TemporaryDirectory() as td:
            mock_file = Path(td) / "ioreg.txt"

            cases = [
                ("ZV-E1", 3704, 8, True, "zve1_202", "msc", False, None),
                ("ZV-E10", 3520, 8, True, "zve10_203", "msc", False, None),
                ("ILCE-7SM3", 3360, 8, True, "a7s3_501", "msc", False, None),
                ("ILME-FX3A", 3705, 8, True, None, "msc", True, "ILME-FX3A is not supported by FX3 7.02 kits"),
                ("ILME-FX3", 822, 255, True, "fx3_702", "service", False, None),
                ("ILCE-7C", 3400, 8, True, "a7c_203", "msc", False, None),
            ]
            for prod, pid, iface_cls, det, want_bid, want_mode, blocked, warn in cases:
                mock_file.write_text(sample_tpl.format(prod=prod, pid=pid, iface_cls=iface_cls), encoding="utf8")
                rc, res = self._run_cli("detect-usb-camera", "--json", env={"OPENGATE_MOCK_IOREG_FILE": str(mock_file)})
                self.assertEqual(rc, 0, res)
                self.assertTrue(res["ok"])
                self.assertEqual(res["detected"], det)
                self.assertEqual(res["body_id"], want_bid, prod)
                self.assertEqual(res["usb_product_name"], prod)
                self.assertEqual(res["usb_mode"], want_mode)
                self.assertEqual(res["is_fx3a_blocked"], blocked)
                self.assertEqual(res["warning"], warn)

            # Empty / non-Sony output returns detected=False
            mock_file.write_text("+-o Hub@01000000  <class IOUSBHostDevice>\n  \"idVendor\" = 1452\n", encoding="utf8")
            rc_none, res_none = self._run_cli("detect-usb-camera", "--json", env={"OPENGATE_MOCK_IOREG_FILE": str(mock_file)})
            self.assertEqual(rc_none, 0)
            self.assertFalse(res_none["detected"])
            self.assertIsNone(res_none["body_id"])
            self.assertIsNone(res_none["usb_mode"])
            self.assertFalse(res_none["is_fx3a_blocked"])

    def test_express_cli_mock_and_prepare_live_command(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            # 1. mixed_powerswitch fails closed with exit 1
            rc_mix, mix = self._run_cli(
                "express-apply",
                "--body",
                "zve1_202",
                "--packs",
                "mp4_3x2,screen_3x2",
                "--mock-camera",
                "--mock-state",
                "mixed_powerswitch",
                "--session-dir",
                td,
                "--json",
            )
            self.assertEqual(rc_mix, 1)
            self.assertFalse(mix["ok"])

            # 2. express-apply succeeds without prior preflight and produces ApplyResult-compatible JSON
            rc_app, app = self._run_cli(
                "express-apply",
                "--body",
                "zve1_202",
                "--packs",
                "mp4_3x2,screen_3x2",
                "--mock-camera",
                "--mock-state",
                "stock",
                "--session-dir",
                td,
                "--json",
            )
            self.assertEqual(rc_app, 0, app)
            self.assertTrue(app["ok"])
            self.assertEqual(app["state"], "applied")
            self.assertEqual(app["closing_dump_verdict"], "VERDICT READY (open gate applied)")
            self.assertIn("mp4_3x2", app["active_packs"])

            rc_ls, ls = self._run_cli("latest-session", "--body", "zve1_202", "--session-dir", td, "--json")
            self.assertEqual(rc_ls, 0)
            self.assertEqual(ls["kind"], "express_apply")
            self.assertEqual(ls["state"], "applied")

            # 3. Build report recognizes express_apply cleanly
            rep_dir = Path(td) / "report_out"
            rc_rep, rep = self._run_cli("build-report", "--body", "zve1_202", "--session-dir", td, "--out-dir", str(rep_dir), "--json")
            self.assertEqual(rc_rep, 0, rep)
            self.assertIn("express_apply", Path(rep["markdown_path"]).read_text(encoding="utf8"))

            # 4. express-putback restores stock
            rc_put, put = self._run_cli("express-putback", "--body", "zve1_202", "--mock-camera", "--session-dir", td, "--json")
            self.assertEqual(rc_put, 0, put)
            self.assertTrue(put["ok"])
            self.assertEqual(put["state"], "stock")

            # 5. prepare-live-command accepts express-apply and express-putback
            for action in ("express-apply", "express-putback"):
                rc_prep, prep = self._run_cli(
                    "prepare-live-command",
                    "--action",
                    action,
                    "--body",
                    "fx3_702",
                    "--session-dir",
                    td,
                    "--json",
                )
                self.assertEqual(rc_prep, 0, prep)
                cmd_file = Path(prep["command_file"])
                self.assertTrue(cmd_file.is_file())
                self.assertTrue(bool(cmd_file.stat().st_mode & stat.S_IXUSR))
                chk = subprocess.run(["bash", "-n", str(cmd_file)], capture_output=True, text=True)
                self.assertEqual(chk.returncode, 0, chk.stderr)


if __name__ == "__main__":
    unittest.main()
