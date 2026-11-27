#!/usr/bin/env python3
"""Tests for hardware conformance bundle audit, live_usb verification, calibration export, and CLI round-trip."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_DIR = REPO_ROOT / "cli"
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

import bionz_clip_check as bcc  # noqa: E402
import studio_cli  # noqa: E402
import studio_conformance as sconf  # noqa: E402


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_synthetic_bundle(clips_dir: Path, *, include_25p: bool = False) -> dict[str, str]:
    """Create valid 3:2 open-gate + stock baseline clips with matching *M01.XML sidecars."""
    clip_root = clips_dir / "PRIVATE" / "M4ROOT" / "CLIP"
    clip_root.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}

    # 1. Open-gate 23.976p
    og_24 = clip_root / "C0001.MP4"
    og_24_xml = clip_root / "C0001M01.XML"
    xml_24 = bcc.build_synthetic_xml(3840, 2560, "hvc1", "23.976p", aspect_ratio="3:2")
    og_24.write_bytes(
        bcc.build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001, embedded_xml=xml_24)
    )
    og_24_xml.write_text(xml_24, encoding="utf8")
    hashes["C0001.MP4"] = _sha256_file(og_24)

    # 2. Optional 25.000p open-gate
    if include_25p:
        og_25 = clip_root / "C0002.MP4"
        og_25_xml = clip_root / "C0002M01.XML"
        xml_25 = bcc.build_synthetic_xml(3840, 2560, "hvc1", "25.000p", aspect_ratio="3:2")
        og_25.write_bytes(
            bcc.build_synthetic_mp4(3840, 2560, "hvc1", 25000, 1000, embedded_xml=xml_25)
        )
        og_25_xml.write_text(xml_25, encoding="utf8")
        hashes["C0002.MP4"] = _sha256_file(og_25)

    # 3. Stock 16:9 baseline
    stock_dir = clips_dir / "STOCK"
    stock_dir.mkdir(parents=True, exist_ok=True)
    st_mp4 = stock_dir / "C0007_stock.MP4"
    st_xml = stock_dir / "C0007_stockM01.XML"
    xml_st = bcc.build_synthetic_xml(3840, 2160, "hvc1", "23.976p", aspect_ratio="16:9")
    st_mp4.write_bytes(
        bcc.build_synthetic_mp4(3840, 2160, "hvc1", 24000, 1001, embedded_xml=xml_st)
    )
    st_xml.write_text(xml_st, encoding="utf8")
    hashes["C0007_stock.MP4"] = _sha256_file(st_mp4)
    return hashes


def _write_verified_live_sessions(
    session_dir: Path,
    body_id: str = "zve1_202",
    *,
    active_packs: list[str] | None = None,
    include_ct6_dump_trap: bool = False,
) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    kit_dir, man = studio_cli._load_manifests()[body_id]
    manifest_sha = studio_cli.compute_kit_manifest_sha256(kit_dir)
    dev_sha = man["device_info"]["sha256"]
    now = time.time()

    pre = {
        "session_id": "session_0001_live_preflight",
        "timestamp": now - 60.0,
        "expires_at": now + 840.0,
        "kind": "preflight",
        "mode": "live_usb",
        "body_id": body_id,
        "state": "stock",
        "ready": True,
        "verified": True,
        "pins_ok": True,
        "manifest_sha256": manifest_sha,
        "boot_nonce": "SECRET_BOOT_NONCE_VALUE_1234",
        "preflight_result_sha256": "a" * 64,
        "ct6_session": "CT6_PRIVATE_DUMP_TRAP_0001",
        "camera_identity": {
            "device_info_sha256": dev_sha,
            "msc_usb_id": "054c:0da8",
            "serial_sha256": "deadbeef" * 8,
            "kernel_command_line": "console=ttyAMA0 secret_cmdline",
        },
        "steps_run": ["check"],
        "active_packs": [],
    }
    (session_dir / "session_0001_live_preflight.json").write_text(
        json.dumps(pre, indent=2), encoding="utf8"
    )

    closing = {
        "session_id": "session_0002_live_closing",
        "timestamp": now - 30.0,
        "kind": "closing_dump",
        "mode": "live_usb",
        "body_id": body_id,
        "state": "applied",
        "ready": True,
        "verified": True,
        "pins_ok": True,
        "manifest_sha256": manifest_sha,
        "active_packs": active_packs or ["core_open_gate", "mp4_3x2", "screen_3x2"],
        "steps_run": ["L13", "L5", "L16", "V19", "H16", "B19", "I19", "S16", "C19"],
    }
    (session_dir / "session_0002_live_closing.json").write_text(
        json.dumps(closing, indent=2), encoding="utf8"
    )

    if include_ct6_dump_trap:
        trap_dir = session_dir / "camera_private" / "CT6_PRIVATE_DUMP_TRAP_0001"
        trap_dir.mkdir(parents=True, exist_ok=True)
        (trap_dir / "raw_ram_dump.bin").write_bytes(b"\x00\x01\x02SECRET_RAW_CT6_BYTES")


class ConformanceKitTests(unittest.TestCase):
    def test_mock_session_rejected_as_hardware_proof(self) -> None:
        matrix_before = _sha256_file(sconf.SUPPORT_MATRIX_PATH)
        with tempfile.TemporaryDirectory(prefix="og_conf_mock_") as tmp:
            root = Path(tmp)
            clips_dir = root / "clips"
            session_dir = root / "sessions"
            session_dir.mkdir(parents=True)
            _write_synthetic_bundle(clips_dir)

            # Write a READY mock session (must NEVER qualify as hardware proof)
            mock_rec = {
                "session_id": "session_0001_mock",
                "timestamp": time.time(),
                "kind": "closing_dump",
                "mode": "mock",
                "body_id": "zve1_202",
                "ready": True,
                "verified": True,
                "pins_ok": True,
                "state": "applied",
                "active_packs": ["core_open_gate", "mp4_3x2", "screen_3x2"],
            }
            (session_dir / "session_0001_mock.json").write_text(
                json.dumps(mock_rec, indent=2), encoding="utf8"
            )

            res = sconf.audit_conformance_bundle(
                clips_dir=clips_dir,
                body_id="zve1_202",
                session_dir=session_dir,
                gyroflow_ok=True,
                catalyst_ok=True,
                nle_ok=True,
            )
            self.assertTrue(res["ok"])
            self.assertFalse(res["hardware_proof_ok"])
            self.assertFalse(res["conformance_ready"])
            self.assertEqual(res["session_validation"]["mock_sessions_rejected"], 1)
            self.assertEqual(res["session_validation"]["verified_live_sessions_count"], 0)
            self.assertEqual(res["matrix_recommendations"]["eligible_promotions"], [])
            self.assertFalse(res["matrix_recommendations"]["matrix_mutated"])
            self.assertTrue(res["conformance_slots"]["open_gate_23_976p"]["passed"])
            self.assertTrue(res["conformance_slots"]["stock_baseline"]["passed"])
            self.assertTrue(res["conformance_slots"]["untouched_sha256"]["passed"])

        self.assertEqual(matrix_before, _sha256_file(sconf.SUPPORT_MATRIX_PATH))

    def test_invalid_live_usb_session_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="og_conf_badlive_") as tmp:
            root = Path(tmp)
            clips_dir = root / "clips"
            session_dir = root / "sessions"
            session_dir.mkdir(parents=True)
            _write_synthetic_bundle(clips_dir)

            # Live USB session missing boot_nonce / invalid device_info / verified=False
            bad_live = {
                "session_id": "session_0001_bad_live",
                "timestamp": time.time(),
                "kind": "preflight",
                "mode": "live_usb",
                "body_id": "fx3_702",
                "ready": True,
                "verified": False,
                "pins_ok": True,
                "state": "stock",
                "manifest_sha256": "0" * 64,
                "boot_nonce": "",
                "preflight_result_sha256": "not-hex",
                "camera_identity": {"device_info_sha256": "f" * 64},
            }
            (session_dir / "session_0001_bad_live.json").write_text(
                json.dumps(bad_live, indent=2), encoding="utf8"
            )

            res = sconf.audit_conformance_bundle(
                clips_dir=clips_dir,
                body_id="fx3_702",
                session_dir=session_dir,
            )
            self.assertFalse(res["hardware_proof_ok"])
            self.assertEqual(res["session_validation"]["invalid_live_sessions_rejected"], 1)
            self.assertEqual(res["matrix_recommendations"]["eligible_promotions"], [])

    def test_verified_live_usb_promotion_and_clean_room_report_redaction(self) -> None:
        matrix_before = _sha256_file(sconf.SUPPORT_MATRIX_PATH)
        with tempfile.TemporaryDirectory(prefix="og_conf_live_") as tmp:
            root = Path(tmp)
            clips_dir = root / "clips"
            session_dir = root / "sessions"
            out_dir = root / "out"
            hashes = _write_synthetic_bundle(clips_dir, include_25p=True)
            _write_verified_live_sessions(
                session_dir,
                body_id="zve1_202",
                active_packs=["core_open_gate", "mp4_3x2", "screen_3x2"],
                include_ct6_dump_trap=True,
            )

            res = sconf.audit_conformance_bundle(
                clips_dir=clips_dir,
                body_id="zve1_202",
                session_dir=session_dir,
                out_dir=out_dir,
                measured_readout_ms=10.45,
                gyroflow_ok=True,
                catalyst_ok=True,
                nle_ok=True,
                playback_ok=True,
                thermal_ok=True,
            )

            self.assertTrue(res["ok"])
            self.assertTrue(res["hardware_proof_ok"])
            self.assertTrue(res["required_slots_ok"])
            self.assertTrue(res["conformance_ready"])
            self.assertTrue(res["conformance_slots"]["open_gate_23_976p"]["passed"])
            self.assertTrue(res["conformance_slots"]["open_gate_25_000p"]["passed"])
            self.assertTrue(res["conformance_slots"]["stock_baseline"]["passed"])
            self.assertTrue(res["conformance_slots"]["rtmd_cadence"]["passed"])
            self.assertTrue(res["conformance_slots"]["vprf_and_xml"]["passed"])
            self.assertTrue(res["conformance_slots"]["untouched_sha256"]["passed"])

            # Untouched SHA-256 preserved
            by_name = {c["filename"]: c for c in res["clips"]}
            self.assertEqual(by_name["C0001.MP4"]["mp4_sha256"], hashes["C0001.MP4"])

            # Eligible promotions computed (dry-run only)
            promos = res["matrix_recommendations"]["eligible_promotions"]
            self.assertFalse(res["matrix_recommendations"]["matrix_mutated"])
            self.assertTrue(promos)
            promo_pairs = {(p["pack"], p["dimension"], p["to"]) for p in promos}
            self.assertIn(("mp4_3x2", "hardware_recorded", "yes"), promo_pairs)
            self.assertIn(("mp4_3x2", "clip_xml_validated", "yes"), promo_pairs)
            self.assertIn(("mp4_3x2", "gyroflow_verified", "yes"), promo_pairs)
            self.assertIn(("mp4_3x2", "catalyst_verified", "yes"), promo_pairs)
            self.assertIn(("mp4_3x2", "nle_verified", "yes"), promo_pairs)
            self.assertIn(("mp4_3x2", "field_ready", "yes"), promo_pairs)
            self.assertIn(("core_open_gate + mp4_3x2", "hardware_recorded", "yes"), promo_pairs)

            # Clean-room report files written and redacted
            md_path = out_dir / "CONFORMANCE_REPORT.md"
            man_path = out_dir / "conformance_manifest.json"
            self.assertTrue(md_path.is_file())
            self.assertTrue(man_path.is_file())
            self.assertEqual(len(list(out_dir.iterdir())), 2)

            md_text = md_path.read_text(encoding="utf8")
            man_text = man_path.read_text(encoding="utf8")
            for forbidden_secret in (
                "deadbeef" * 8,
                "SECRET_BOOT_NONCE_VALUE_1234",
                "CT6_PRIVATE_DUMP_TRAP_0001",
                "SECRET_RAW_CT6_BYTES",
                "secret_cmdline",
            ):
                self.assertNotIn(forbidden_secret, md_text)
                self.assertNotIn(forbidden_secret, man_text)

        self.assertEqual(matrix_before, _sha256_file(sconf.SUPPORT_MATRIX_PATH))

    def test_export_calibration_patch_without_mutating_repo(self) -> None:
        cal_before = _sha256_file(sconf.CALIBRATION_PROFILES_PATH)
        patch = sconf.export_calibration_patch(
            body_id="fx3",
            fps="23.976p",
            measured_readout_ms=10.42,
            evidence_note="Measured on untouched 3840x2560 fast pan test clip C0004.MP4",
        )
        self.assertTrue(patch["ok"])
        self.assertTrue(patch["dry_run_only"])
        self.assertEqual(patch["body_id"], "fx3_702")
        self.assertEqual(patch["previous_evidence_level"], "estimated_from_imx510_line_ratio")
        self.assertEqual(patch["previous_frame_readout_time_ms"], 10.3)
        self.assertEqual(patch["new_evidence_level"], "hardware_measured")
        self.assertEqual(patch["measured_frame_readout_time_ms"], 10.42)
        self.assertAlmostEqual(patch["delta_ms"], 0.12, places=3)
        self.assertEqual(patch["patch_entry"]["evidence_level"], "hardware_measured")
        self.assertEqual(patch["gyroflow_preset_patch"]["frame_readout_time"], 10.42)

        with self.assertRaises(ValueError):
            sconf.export_calibration_patch("zve1_202", "23.976p", -1.0, "bad")
        with self.assertRaises(ValueError):
            sconf.export_calibration_patch("unknown_cam", "23.976p", 10.4, "bad")

        self.assertEqual(cal_before, _sha256_file(sconf.CALIBRATION_PROFILES_PATH))

    def test_cli_conformance_audit_json_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="og_conf_cli_") as tmp:
            root = Path(tmp)
            clips_dir = root / "clips"
            session_dir = root / "sessions"
            out_dir = root / "report_out"
            _write_synthetic_bundle(clips_dir)
            _write_verified_live_sessions(session_dir, body_id="a7s3_501")

            cli_path = REPO_ROOT / "cli" / "studio_cli.py"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(cli_path),
                    "conformance-audit",
                    "--body",
                    "a7s3_501",
                    "--clips-dir",
                    str(clips_dir),
                    "--session-dir",
                    str(session_dir),
                    "--out-dir",
                    str(out_dir),
                    "--measured-readout-ms",
                    "10.38",
                    "--gyroflow-ok",
                    "--nle-ok",
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["ok"])
            self.assertTrue(data["hardware_proof_ok"])
            self.assertTrue(data["conformance_ready"])
            self.assertEqual(data["metadata"]["body_id"], "a7s3_501")
            self.assertEqual(data["calibration_patch"]["new_evidence_level"], "hardware_measured")
            self.assertTrue((out_dir / "CONFORMANCE_REPORT.md").is_file())
            self.assertTrue((out_dir / "conformance_manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
