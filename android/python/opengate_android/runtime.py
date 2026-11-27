# SPDX-License-Identifier: GPL-3.0-or-later
"""Android USB-OTG runtime entrypoint, payload verifier, session exporter & SimDriver selftest."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ANDROID_PY_ROOT = HERE.parent
DEFAULT_REPO_ROOT = HERE.parent.parent.parent
if str(ANDROID_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(ANDROID_PY_ROOT))

from opengate_android.quick_reapply import QuickReapplyDecision, plan_quick_reapply  # noqa: E402
from opengate_android.usb_bridge_shim import install_usb_shim, uninstall_usb_shim  # noqa: E402


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_unpacked_payload(root_dir: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    """Verify every file in an unpacked Android kit against ``payload_manifest.json`` & ``kits/*/manifest.json``."""
    eff_manifest = manifest_path or (root_dir / "payload_manifest.json")
    errors: list[str] = []

    if not eff_manifest.is_file():
        return {"ok": False, "checked_files": 0, "errors": [f"Missing manifest: {eff_manifest}"]}

    manifest = json.loads(eff_manifest.read_text(encoding="utf8"))
    pinned = manifest.get("files", {})
    if not isinstance(pinned, dict) or not pinned:
        return {"ok": False, "checked_files": 0, "errors": ["Empty files map in payload_manifest.json"]}

    checked = 0
    for rel_str, want_sha in sorted(pinned.items()):
        checked += 1
        target = root_dir / rel_str
        if not target.is_file():
            errors.append(f"Missing payload file: {rel_str}")
            continue
        got_sha = _sha256_file(target)
        if got_sha != want_sha:
            errors.append(f"Payload SHA-256 mismatch for {rel_str}: {got_sha} != {want_sha}")

    # Reject any unexpected .so or .py under kits/ or sony-pmca-re/
    kits_dir = root_dir / "kits"
    if kits_dir.is_dir():
        for so_file in sorted(kits_dir.rglob("*.so")):
            rel = so_file.relative_to(root_dir).as_posix()
            if rel not in pinned:
                errors.append(f"Unpinned .so helper in unpacked payload: {rel}")

    pmca_pkg = root_dir / "transport" / "third_party" / "sony-pmca-re" / "pmca"
    if pmca_pkg.is_dir():
        for py_file in sorted(pmca_pkg.rglob("*.py")):
            rel = py_file.relative_to(root_dir).as_posix()
            if rel not in pinned:
                errors.append(f"Unpinned pmca file in unpacked payload: {rel}")

    # Verify kits/*/manifest.json pins via studio_cli logic if cli/ is present
    cli_dir = root_dir / "cli"
    if cli_dir.is_dir() and (cli_dir / "studio_cli.py").is_file():
        if str(cli_dir) not in sys.path:
            sys.path.insert(0, str(cli_dir))
        import studio_cli  # type: ignore[import-not-found]

        orig_kits = studio_cli.KITS_DIR
        try:
            studio_cli.KITS_DIR = kits_dir
            code, pin_res = studio_cli.cmd_verify_pins(None)
            if code != 0 or not pin_res.get("ok"):
                errors.append(f"studio_cli verify-pins failed: {pin_res}")
        finally:
            studio_cli.KITS_DIR = orig_kits

    return {
        "ok": len(errors) == 0,
        "checked_files": checked,
        "errors": errors,
    }


def export_session_zip(session_dir: Path, out_zip: Path) -> dict[str, Any]:
    """Export safe session JSONs & CT6 metadata (strictly excluding ``camera_private/`` & raw dumps)."""
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    exported: list[str] = []
    skipped_private = 0

    if not session_dir.is_dir():
        with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED):
            pass
        return {"ok": True, "exported_count": 0, "skipped_private": 0, "zip_path": str(out_zip)}

    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(session_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(session_dir)
            parts_lower = {p.lower() for p in rel.parts}
            if "camera_private" in parts_lower or path.suffix.lower() in {".bin", ".dat", ".img", ".tar", ".elf"}:
                skipped_private += 1
                continue
            if path.suffix.lower() in {".json", ".txt", ".md", ".jsonl"}:
                zf.write(path, arcname=rel.as_posix())
                exported.append(rel.as_posix())

    return {
        "ok": True,
        "exported_count": len(exported),
        "skipped_private": skipped_private,
        "zip_path": str(out_zip),
        "exported_files": exported,
    }


def run_selftest(repo_root: Path = DEFAULT_REPO_ROOT) -> dict[str, Any]:
    """Run offline clean-room packaging, SimDriver verification, and planner parity selftests."""
    scripts_dir = repo_root / "scripts"
    cli_dir = repo_root / "cli"
    for p in (scripts_dir, cli_dir):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))

    import build_android_kit  # type: ignore[import-not-found]
    import studio_step_run as ssr  # type: ignore[import-not-found]
    import ct6_level1_run as R  # type: ignore[import-not-found]

    checks: list[str] = []
    with tempfile.TemporaryDirectory(prefix="og_android_selftest_") as tmp:
        tmp_path = Path(tmp)
        bundle_dir = tmp_path / "bundle"
        unpacked_dir = tmp_path / "unpacked"

        # 1. Deterministic clean-room kit packaging + unpack + tamper check
        build_res = build_android_kit.build_android_kit(out_dir=bundle_dir, repo_root=repo_root)
        assert build_res["ok"] and build_res["file_count"] > 80
        zip_path = Path(build_res["zip_path"])
        verify_zip = build_android_kit.verify_android_kit_zip(zip_path)
        assert verify_zip["ok"], f"zip verify failed: {verify_zip}"
        checks.append(f"kit_zip_verified:{verify_zip['checked_files']}")

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(unpacked_dir)

        unpacked_ok = verify_unpacked_payload(unpacked_dir)
        assert unpacked_ok["ok"], f"unpacked verify failed: {unpacked_ok}"
        checks.append(f"unpacked_payload_verified:{unpacked_ok['checked_files']}")

        # Tamper 1 byte in an unpacked file -> must fail closed
        tamper_target = unpacked_dir / "cli" / "studio_cli.py"
        tamper_target.write_bytes(tamper_target.read_bytes() + b"\n# tampered\n")
        tampered = verify_unpacked_payload(unpacked_dir)
        assert not tampered["ok"] and tampered["errors"], "Tampered unpacked payload must fail closed"
        checks.append("unpacked_tamper_rejected")

        # 2. SimDriver verification across all 3 bodies (DeviceInfo mismatch, --require-result, full selftest)
        for body_id in ("zve1_202", "a7s3_501", "fx3_702"):
            for which in ("check", "dump", "V19"):
                lib = ssr.use(body_id, which)
                done = ssr.selftest(lib)
                assert any("wrong DeviceInfo.xml" in item for item in done)
                assert any("--require-result" in item for item in done)
                checks.append(f"simdriver_{body_id}_{which}:{len(done)}")

        # Confirm R.refusals blocks forbidden packet classes
        assert len(R.refusals(ssr.use("zve1_202", "check"))) == 15
        checks.append("ct6_guard_refusals:15")

        # 3. QuickReapplyPlanner parity & mock isolation
        mock_plan = plan_quick_reapply(
            pins_verified=True,
            selected_body_id="zve1_202",
            offline_mock_camera=False,
            preflight_result={"ok": True, "ready": True, "state": "stock", "body_id": "zve1_202"},
            latest_session={"found": True, "mode": "mock", "ok": True, "ready": True, "state": "stock", "body_id": "zve1_202"},
            result_source="mock",
        )
        assert mock_plan.decision == QuickReapplyDecision.RUN_PREFLIGHT_THEN_SAFE_DAILY_APPLY
        live_ready_plan = plan_quick_reapply(
            pins_verified=True,
            selected_body_id="zve1_202",
            offline_mock_camera=False,
            preflight_result={"ok": True, "ready": True, "state": "stock", "body_id": "zve1_202"},
            latest_session={
                "found": True,
                "mode": "live_usb",
                "kind": "preflight",
                "ok": True,
                "ready": True,
                "verified": True,
                "state": "stock",
                "body_id": "zve1_202",
            },
            result_source="android_usb",
        )
        assert live_ready_plan.decision == QuickReapplyDecision.READY_FOR_SAFE_DAILY_APPLY
        assert live_ready_plan.packs == ("mp4_3x2", "screen_3x2")
        checks.append("quick_reapply_parity_verified")

        # 4. USB bridge shim smoke check
        class _DummyBridge:
            def findDevices(self, vid):
                return [{
                    "deviceId": 1,
                    "idVendor": 0x054C,
                    "idProduct": 0x0336,
                    "serialNumber": "TEST123",
                    "interfaces": [{
                        "number": 0,
                        "interfaceClass": 255,
                        "interfaceProtocol": 0,
                        "endpoints": [{"address": 0x81, "attributes": 2, "maxPacketSize": 512}],
                    }],
                }]

            def openAndClaim(self, dev_id, timeout_ms):
                return f"handle:{dev_id}:{timeout_ms}"

            def bulkRead(self, handle, ep, length, timeout_ms):
                return b"\x01\x02"

            def bulkWrite(self, handle, ep, data, timeout_ms):
                return len(data)

            def controlTransfer(self, handle, req_type, req, val, idx, data_or_len, timeout_ms):
                return b"\x00" if isinstance(data_or_len, int) else len(data_or_len)

            def close(self, handle):
                pass

        try:
            install_usb_shim(_DummyBridge())
            import usb.core  # type: ignore[import-not-found]

            found = list(usb.core.find(find_all=True, idVendor=0x054C))
            assert len(found) == 1
            assert found[0].read(0x81, 64).tobytes() == b"\x01\x02"
            assert found[0].write(0x02, b"ok") == 2
            found[0].dispose()
            checks.append("usb_shim_verified")
        finally:
            uninstall_usb_shim()

        # 5. Session export excludes camera_private/ and .bin files
        sess_dir = tmp_path / "sessions"
        (sess_dir / "camera_private" / "CT6_1").mkdir(parents=True)
        (sess_dir / "camera_private" / "CT6_1" / "secret_dump.bin").write_bytes(b"SECRET")
        (sess_dir / "session_live_1.json").write_text('{"ok": true}\n', encoding="utf8")
        export_zip = tmp_path / "export.zip"
        exp_res = export_session_zip(sess_dir, export_zip)
        assert exp_res["exported_count"] == 1 and exp_res["skipped_private"] == 1
        with zipfile.ZipFile(export_zip, "r") as ezf:
            assert ezf.namelist() == ["session_live_1.json"]
        checks.append("session_export_privacy_verified")

    return {
        "ok": True,
        "checks": checks,
        "check_count": len(checks),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        res = run_selftest()
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"ANDROID RUNTIME SELFTEST PASS: {res['check_count']} checks passed.")
        return 0 if res["ok"] else 1

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
