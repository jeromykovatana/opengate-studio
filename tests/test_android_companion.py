#!/usr/bin/env python3
"""Unit tests for the clean-room Android USB-OTG companion runtime & packager."""
from __future__ import annotations

import hashlib
import importlib
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
from opengate_android.crypto_shim import (  # type: ignore[import-not-found]
    install_cryptodome_sha256_fallback,
    uninstall_cryptodome_sha256_fallback,
)
from opengate_android.live_runner import (  # type: ignore[import-not-found]
    SERVICE_WAIT_TIMEOUT_SECONDS,
    bootstrap_kit,
    execute_companion_run,
    export_companion_bundle,
    query_companion_state,
)
from opengate_android.quick_reapply import QuickReapplyDecision, plan_quick_reapply  # type: ignore[import-not-found]
from opengate_android.runtime import export_session_zip, run_selftest, verify_unpacked_payload  # type: ignore[import-not-found]
from opengate_android.usb_bridge_shim import AndroidUsbError, install_usb_shim, uninstall_usb_shim  # type: ignore[import-not-found]


class _DummyBridge:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def findDevices(self, vid: int | None) -> list[dict]:
        self.calls.append(f"find:{vid}")
        return [{
            "deviceId": 7,
            "idVendor": 0x054C,
            "idProduct": 0x0336,
            "serialNumber": "TESTSERIAL",
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

    def openAndClaim(self, dev_id: int, timeout_ms: int) -> str:
        self.calls.append(f"claim:{dev_id}:{timeout_ms}")
        return f"h{dev_id}"

    def bulkRead(self, handle: str, ep: int, length: int, timeout_ms: int) -> bytes:
        self.calls.append(f"read:{handle}:{ep}:{length}")
        return b"\xaa\xbb"

    def bulkWrite(self, handle: str, ep: int, data: bytes, timeout_ms: int) -> int:
        self.calls.append(f"write:{handle}:{ep}:{len(data)}")
        return len(data)

    def controlTransfer(self, handle: str, req_type: int, req: int, val: int, idx: int, data_or_len: object, timeout_ms: int) -> object:
        self.calls.append(f"ctrl:{handle}:{req}")
        return b"\x01" if isinstance(data_or_len, int) else len(data_or_len)  # type: ignore[arg-type]

    def close(self, handle: str) -> None:
        self.calls.append(f"close:{handle}")


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
        bridge = _DummyBridge()
        cancelled = False

        try:
            install_usb_shim(bridge, cancel_check=lambda: cancelled)
            import usb.core  # type: ignore[import-not-found]
            import usb.util  # type: ignore[import-not-found]

            dev = usb.core.find(idVendor=0x054C)
            self.assertIsNotNone(dev)
            dev.detach_kernel_driver(0)
            self.assertEqual(usb.util.get_string(dev, dev.iSerialNumber), "TESTSERIAL")
            self.assertEqual(dev.read(0x81, 64).tobytes(), b"\xaa\xbb")
            self.assertEqual(dev.write(0x02, b"1234"), 4)
            self.assertEqual(dev.ctrl_transfer(usb.util.CTRL_IN, 0x01, 0, 0, 1).tobytes(), b"\x01")
            usb.util.dispose_resources(dev)
            self.assertIn("claim:7:30000", bridge.calls)
            self.assertIn("close:h7", bridge.calls)

            cancelled = True
            self.assertEqual(usb.core.find(find_all=True, idVendor=0x054C), [])
            with self.assertRaises(AndroidUsbError):
                dev.read(0x81, 16)
        finally:
            uninstall_usb_shim()

    def test_crypto_shim_fallback_powers_sony_pmca(self) -> None:
        pmca_root = REPO_ROOT / "transport" / "third_party" / "sony-pmca-re"
        saved_pmca = str(pmca_root) in sys.path
        if not saved_pmca:
            sys.path.insert(0, str(pmca_root))

        # Clear any pre-existing Cryptodome/sony module so fallback is exercised cleanly
        removed = {k: sys.modules.pop(k) for k in list(sys.modules) if k == "Cryptodome" or k.startswith("Cryptodome.")}
        sys.modules.pop("pmca.usb.sony", None)
        try:
            installed = install_cryptodome_sha256_fallback(force=True)
            self.assertTrue(installed)

            from Cryptodome.Hash import SHA256  # type: ignore[import-not-found]

            h1 = SHA256.new(b"opengate")
            h1.update(b"-studio")
            h2 = h1.copy()
            want = hashlib.sha256(b"opengate-studio").digest()
            self.assertEqual(h1.digest(), want)
            self.assertEqual(h2.hexdigest(), hashlib.sha256(b"opengate-studio").hexdigest())

            sony_mod = importlib.import_module("pmca.usb.sony")
            self.assertEqual(sony_mod.SHA256.new(b"sony-auth").digest(), hashlib.sha256(b"sony-auth").digest())
        finally:
            sys.modules.pop("pmca.usb.sony", None)
            uninstall_cryptodome_sha256_fallback()
            sys.modules.update(removed)
            if not saved_pmca and str(pmca_root) in sys.path:
                sys.path.remove(str(pmca_root))

    def test_live_runner_bootstrap_mock_isolation_and_gates(self) -> None:
        self.assertEqual(SERVICE_WAIT_TIMEOUT_SECONDS, 30.0)
        with tempfile.TemporaryDirectory(prefix="og_live_runner_") as tmp:
            tmp_path = Path(tmp)
            kit_dir = tmp_path / "assets"
            unpack_dir = tmp_path / "unpacked"
            sessions_dir = tmp_path / "sessions"
            built = build_android_kit.build_android_kit(out_dir=kit_dir, repo_root=REPO_ROOT)

            boot = json.loads(bootstrap_kit(built["zip_path"], unpack_dir))
            self.assertTrue(boot["ok"], boot)
            self.assertEqual(boot["checked_files"], built["file_count"])

            # Initial state requires preflight
            state0 = json.loads(query_companion_state(unpack_dir, sessions_dir, "zve1_202", offline_mock=False))
            self.assertTrue(state0["ok"])
            self.assertTrue(state0["pins_verified"])
            self.assertEqual(state0["decision"], QuickReapplyDecision.RUN_PREFLIGHT_THEN_SAFE_DAILY_APPLY.value)

            # Offline mock preflight -> apply -> dump -> putback
            mock_events: list[dict] = []
            pre = json.loads(execute_companion_run(
                unpack_dir,
                sessions_dir,
                "preflight",
                "zve1_202",
                offline_mock=True,
                usb_bridge=None,
                firmware_confirmed="2.02",
                confirm_volatile_ram=False,
                cancel_file=None,
                on_event=mock_events.append,
            ))
            self.assertTrue(pre["ok"], pre)
            self.assertEqual(pre["mode"], "mock")
            self.assertEqual(pre["state"], "stock")
            self.assertTrue(any(ev.get("type") == "complete" for ev in mock_events))

            app = json.loads(execute_companion_run(
                unpack_dir,
                sessions_dir,
                "apply",
                "zve1_202",
                offline_mock=True,
                usb_bridge=None,
                firmware_confirmed="2.02",
                confirm_volatile_ram=True,
                cancel_file=None,
                on_event=mock_events.append,
                packs="mp4_3x2,screen_3x2",
            ))
            self.assertTrue(app["ok"], app)
            self.assertEqual(app["mode"], "mock")

            # Mock session MUST NEVER unlock live USB apply
            state_live = json.loads(query_companion_state(unpack_dir, sessions_dir, "zve1_202", offline_mock=False))
            self.assertFalse(state_live["live_preflight_valid"])
            self.assertEqual(state_live["decision"], QuickReapplyDecision.RUN_PREFLIGHT_THEN_SAFE_DAILY_APPLY.value)

            refused_apply = json.loads(execute_companion_run(
                unpack_dir,
                sessions_dir,
                "apply",
                "zve1_202",
                offline_mock=False,
                usb_bridge=_DummyBridge(),
                firmware_confirmed="2.02",
                confirm_volatile_ram=True,
                cancel_file=None,
                on_event=None,
            ))
            self.assertFalse(refused_apply["ok"])
            self.assertIn("Refusing live apply", refused_apply["error"])

            # Safety gate checks: missing usb_bridge, wrong firmware, missing volatile-ram confirm
            no_usb = json.loads(execute_companion_run(
                unpack_dir, sessions_dir, "preflight", "zve1_202", False, None, "2.02", False, None, None
            ))
            self.assertFalse(no_usb["ok"])

            bad_fw = json.loads(execute_companion_run(
                unpack_dir, sessions_dir, "preflight", "zve1_202", False, _DummyBridge(), "9.99", False, None, None
            ))
            self.assertFalse(bad_fw["ok"])
            self.assertIn("Not 2.02", bad_fw["error"])

            no_confirm = json.loads(execute_companion_run(
                unpack_dir, sessions_dir, "putback", "zve1_202", False, _DummyBridge(), "2.02", False, None, None
            ))
            self.assertFalse(no_confirm["ok"])
            self.assertIn("confirm-volatile-ram", no_confirm["error"])

            # Cooperative cancellation via cancel_file before USB packets
            cancel_flag = tmp_path / "cancel.flag"
            cancel_flag.write_text("cancel\n", encoding="utf8")
            live_events: list[dict] = []
            bridge = _DummyBridge()
            cancelled_run = json.loads(execute_companion_run(
                unpack_dir,
                sessions_dir,
                "preflight",
                "zve1_202",
                offline_mock=False,
                usb_bridge=bridge,
                firmware_confirmed="2.02",
                confirm_volatile_ram=False,
                cancel_file=cancel_flag,
                on_event=live_events.append,
            ))
            self.assertFalse(cancelled_run["ok"])
            self.assertTrue(cancelled_run["cancelled"])
            self.assertEqual(bridge.calls, [])
            self.assertTrue(any(ev.get("type") == "cancelled" for ev in live_events))

            # Mock dump + putback + privacy-filtered export
            dmp = json.loads(execute_companion_run(
                unpack_dir, sessions_dir, "dump", "zve1_202", True, None, "2.02", False, None, None
            ))
            self.assertTrue(dmp["ok"], dmp)
            put = json.loads(execute_companion_run(
                unpack_dir, sessions_dir, "putback", "zve1_202", True, None, "2.02", True, None, None
            ))
            self.assertTrue(put["ok"], put)

            (sessions_dir / "camera_private" / "CT6_mock").mkdir(parents=True, exist_ok=True)
            (sessions_dir / "camera_private" / "CT6_mock" / "raw.bin").write_bytes(b"SECRET")
            out_zip = tmp_path / "exported_bundle.zip"
            exp = json.loads(export_companion_bundle(sessions_dir, out_zip))
            self.assertTrue(exp["ok"])
            self.assertGreaterEqual(exp["exported_count"], 3)
            self.assertEqual(exp["skipped_private"], 1)
            with zipfile.ZipFile(out_zip, "r") as ezf:
                names = ezf.namelist()
                self.assertFalse(any("camera_private" in n or n.endswith(".bin") for n in names))

            # Tamper 1 byte -> query & execute fail closed
            (unpack_dir / "cli" / "studio_cli.py").write_bytes(b"# tampered\n")
            tampered_state = json.loads(query_companion_state(unpack_dir, sessions_dir, "zve1_202", offline_mock=False))
            self.assertFalse(tampered_state["pins_verified"])
            self.assertEqual(tampered_state["decision"], QuickReapplyDecision.BLOCKED_PINS_UNVERIFIED.value)
            tampered_run = json.loads(execute_companion_run(
                unpack_dir, sessions_dir, "preflight", "zve1_202", True, None, "2.02", False, None, None
            ))
            self.assertFalse(tampered_run["ok"])

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
