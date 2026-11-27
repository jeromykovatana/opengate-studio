#!/usr/bin/env python3
"""Unit tests for the clean-room Android USB-OTG companion runtime & packager."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
ANDROID_PY_ROOT = REPO_ROOT / "android" / "python"

for p in (SCRIPTS_DIR, ANDROID_PY_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import build_android_kit  # type: ignore[import-not-found]
from opengate_android.quick_reapply import QuickReapplyDecision, plan_quick_reapply  # type: ignore[import-not-found]
from opengate_android.runtime import export_session_zip, run_selftest, verify_unpacked_payload  # type: ignore[import-not-found]
from opengate_android.usb_bridge_shim import AndroidUsbError, install_usb_shim, uninstall_usb_shim  # type: ignore[import-not-found]


class AndroidCompanionTests(unittest.TestCase):
    def test_build_android_kit_dry_run_and_verify_zip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="og_android_kit_") as tmp:
            out_dir = Path(tmp)
            dry = build_android_kit.build_android_kit(out_dir=out_dir, repo_root=REPO_ROOT, dry_run=True)
            self.assertTrue(dry["ok"])
            self.assertTrue(dry["dry_run"])
            self.assertGreater(dry["file_count"], 80)
            self.assertFalse(Path(dry["zip_path"]).exists())

            built = build_android_kit.build_android_kit(out_dir=out_dir, repo_root=REPO_ROOT, dry_run=False)
            self.assertTrue(built["ok"])
            zip_path = Path(built["zip_path"])
            self.assertTrue(zip_path.is_file())

            verified = build_android_kit.verify_android_kit_zip(zip_path)
            self.assertTrue(verified["ok"], verified)
            self.assertEqual(verified["checked_files"], built["file_count"])

            # Unpack & verify fail-closed on unpinned .so injection
            unpack_dir = out_dir / "unpacked"
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(unpack_dir)
            ok_res = verify_unpacked_payload(unpack_dir)
            self.assertTrue(ok_res["ok"], ok_res)

            rogue_so = unpack_dir / "kits" / "zve1_202" / "rogue.so"
            rogue_so.write_bytes(b"rogue")
            bad_res = verify_unpacked_payload(unpack_dir)
            self.assertFalse(bad_res["ok"])
            self.assertTrue(any("Unpinned .so helper" in e for e in bad_res["errors"]))

    def test_quick_reapply_planner_parity(self) -> None:
        self.assertEqual(
            plan_quick_reapply(pins_verified=False, selected_body_id="zve1_202").decision,
            QuickReapplyDecision.BLOCKED_PINS_UNVERIFIED,
        )
        self.assertEqual(
            plan_quick_reapply(pins_verified=True, selected_body_id="fx3_702", left_behind_warning=True).decision,
            QuickReapplyDecision.RUN_RECOVERY_PREFLIGHT_FIRST,
        )
        # Mock READY never unlocks live apply
        self.assertEqual(
            plan_quick_reapply(
                pins_verified=True,
                selected_body_id="zve1_202",
                offline_mock_camera=False,
                preflight_result={"ok": True, "ready": True, "state": "stock", "body_id": "zve1_202"},
                latest_session={"found": True, "mode": "mock", "ok": True, "ready": True, "state": "stock", "body_id": "zve1_202"},
                result_source="mock",
            ).decision,
            QuickReapplyDecision.RUN_PREFLIGHT_THEN_SAFE_DAILY_APPLY,
        )
        # Verified live stock unlocks Safe Daily 3:2
        ready = plan_quick_reapply(
            pins_verified=True,
            selected_body_id="a7s3_501",
            offline_mock_camera=False,
            preflight_result={"ok": True, "ready": True, "state": "stock", "body_id": "a7s3_501"},
            latest_session={
                "found": True,
                "mode": "live_usb",
                "kind": "preflight",
                "ok": True,
                "ready": True,
                "verified": True,
                "state": "stock",
                "body_id": "a7s3_501",
            },
            result_source="android_usb",
        )
        self.assertEqual(ready.decision, QuickReapplyDecision.READY_FOR_SAFE_DAILY_APPLY)
        self.assertEqual(ready.packs, ("mp4_3x2", "screen_3x2"))

    def test_usb_bridge_shim_and_cancel(self) -> None:
        calls: list[str] = []
        cancelled = False

        class _MockBridge:
            def findDevices(self, vid):
                calls.append(f"find:{vid}")
                return [{
                    "deviceId": 7,
                    "idVendor": 0x054C,
                    "idProduct": 0x0336,
                    "interfaces": [{
                        "number": 0,
                        "interfaceClass": 255,
                        "interfaceProtocol": 0,
                        "endpoints": [
                            {"address": 0x81, "attributes": 2, "maxPacketSize": 512},
                            {"address": 0x02, "attributes": 2, "maxPacketSize": 512},
                        ],
                    }],
                }]

            def openAndClaim(self, dev_id, timeout_ms):
                calls.append(f"claim:{dev_id}:{timeout_ms}")
                return f"h{dev_id}"

            def bulkRead(self, handle, ep, length, timeout_ms):
                calls.append(f"read:{handle}:{ep}:{length}")
                return b"\xaa\xbb"

            def bulkWrite(self, handle, ep, data, timeout_ms):
                calls.append(f"write:{handle}:{ep}:{len(data)}")
                return len(data)

            def controlTransfer(self, handle, req_type, req, val, idx, data_or_len, timeout_ms):
                calls.append(f"ctrl:{handle}:{req}")
                return b"\x01" if isinstance(data_or_len, int) else len(data_or_len)

            def close(self, handle):
                calls.append(f"close:{handle}")

        try:
            install_usb_shim(_MockBridge(), cancel_check=lambda: cancelled)
            import usb.core  # type: ignore[import-not-found]
            import usb.util  # type: ignore[import-not-found]

            dev = usb.core.find(idVendor=0x054C)
            self.assertIsNotNone(dev)
            dev.detach_kernel_driver(0)
            self.assertEqual(dev.read(0x81, 64).tobytes(), b"\xaa\xbb")
            self.assertEqual(dev.write(0x02, b"1234"), 4)
            self.assertEqual(dev.ctrl_transfer(usb.util.CTRL_IN, 0x01, 0, 0, 1).tobytes(), b"\x01")
            usb.util.dispose_resources(dev)
            self.assertIn("claim:7:30000", calls)
            self.assertIn("close:h7", calls)

            cancelled = True
            self.assertEqual(usb.core.find(find_all=True, idVendor=0x054C), [])
            with self.assertRaises(AndroidUsbError):
                dev.read(0x81, 16)
        finally:
            uninstall_usb_shim()

    def test_runtime_selftest_and_export_privacy(self) -> None:
        res = run_selftest(REPO_ROOT)
        self.assertTrue(res["ok"], res)
        self.assertGreaterEqual(res["check_count"], 12)

        with tempfile.TemporaryDirectory(prefix="og_android_export_") as tmp:
            tmp_path = Path(tmp)
            sess_dir = tmp_path / "sessions"
            (sess_dir / "camera_private" / "CT6_test").mkdir(parents=True)
            (sess_dir / "camera_private" / "CT6_test" / "dump.bin").write_bytes(b"PRIVATE")
            (sess_dir / "session_1.json").write_text(json.dumps({"ok": True}), encoding="utf8")
            out_zip = tmp_path / "bundle.zip"
            exp = export_session_zip(sess_dir, out_zip)
            self.assertEqual(exp["exported_count"], 1)
            self.assertEqual(exp["skipped_private"], 1)
            with zipfile.ZipFile(out_zip, "r") as zf:
                self.assertEqual(zf.namelist(), ["session_1.json"])


if __name__ == "__main__":
    unittest.main()
