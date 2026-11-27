#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Clean-room Android OTG kit packager for OpenGate Studio.

Builds a deterministic, SHA-256-verified ``opengate_kit.zip`` + ``payload_manifest.json``
from pinned clean-room assets (kits, expected JSONs, CLI runners, CT1/CT6 transport,
MIT sony-pmca-re, and android_runtime/opengate_android).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verify_clean_room as vcr  # noqa: E402

DETERMINISTIC_ZIP_DT = (2026, 1, 1, 0, 0, 0)
BODY_IDS = ("zve1_202", "a7s3_501", "fx3_702", "a7c_203", "zve10_203")
CLI_FILES = (
    "studio_cli.py",
    "studio_live_apply.py",
    "studio_step_run.py",
    "studio_report.py",
    "bionz_clip_check.py",
    "studio_conformance.py",
    "studio_creator.py",
    "studio_gyro.py",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def collect_android_kit_entries(repo_root: Path = REPO_ROOT) -> list[tuple[str, Path]]:
    """Collect and validate every clean-room file included in ``opengate_kit.zip``."""
    clean_res = vcr.verify_clean_room(repo_root)
    if not clean_res["ok"]:
        raise RuntimeError("Clean-room verification failed: " + "; ".join(clean_res["errors"]))

    entries: dict[str, Path] = {}

    for body_id in BODY_IDS:
        kit_dir = repo_root / "kits" / body_id
        manifest_path = kit_dir / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Missing kit manifest: {manifest_path}")
        entries[f"kits/{body_id}/manifest.json"] = manifest_path

        man = json.loads(manifest_path.read_text(encoding="utf8"))
        for section in ("readonly", "steps"):
            for _, entry in sorted(man.get(section, {}).items()):
                fname, _ = vcr._extract_entry_file_sha(entry)
                if fname:
                    entries[f"kits/{body_id}/{fname}"] = kit_dir / fname

        dev_info = man.get("device_info")
        if isinstance(dev_info, dict):
            fname, _ = vcr._extract_entry_file_sha(dev_info)
            if fname:
                entries[f"kits/{body_id}/{fname}"] = kit_dir / fname

        src_dir = repo_root / "src" / body_id
        if src_dir.is_dir():
            for expected in sorted(src_dir.glob("*_expected.json")):
                entries[f"src/{body_id}/{expected.name}"] = expected

    for cli_name in CLI_FILES:
        cli_path = repo_root / "cli" / cli_name
        if not cli_path.is_file():
            raise FileNotFoundError(f"Missing CLI file: {cli_path}")
        entries[f"cli/{cli_name}"] = cli_path

    ct1_dir = repo_root / "transport" / "camera_tests" / "CT1_usb_first_contact"
    for p in sorted(ct1_dir.iterdir()):
        if p.is_file() and p.suffix in {".py", ".json"}:
            entries[f"transport/camera_tests/CT1_usb_first_contact/{p.name}"] = p

    ct6_runner = repo_root / "transport" / "camera_tests" / "CT6_memory_read_check" / "ct6_level1_run.py"
    if not ct6_runner.is_file():
        raise FileNotFoundError(f"Missing CT6 runner: {ct6_runner}")
    entries["transport/camera_tests/CT6_memory_read_check/ct6_level1_run.py"] = ct6_runner

    pmca_root = repo_root / "transport" / "third_party" / "sony-pmca-re"
    entries["transport/third_party/sony-pmca-re/LICENSE.txt"] = pmca_root / "LICENSE.txt"
    entries["transport/third_party/sony-pmca-re/PINNED.json"] = pmca_root / "PINNED.json"
    pinned = json.loads((pmca_root / "PINNED.json").read_text(encoding="utf8"))
    for rel_str in sorted(pinned.get("files", {})):
        entries[f"transport/third_party/sony-pmca-re/{rel_str}"] = pmca_root / rel_str

    android_py_dir = repo_root / "android" / "python" / "opengate_android"
    if android_py_dir.is_dir():
        for py_file in sorted(android_py_dir.glob("*.py")):
            entries[f"android_runtime/opengate_android/{py_file.name}"] = py_file

    missing = [arc for arc, src in entries.items() if not src.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing files for Android kit: {missing}")

    return sorted(entries.items(), key=lambda kv: kv[0])


def build_android_kit(
    *,
    out_dir: Path,
    repo_root: Path = REPO_ROOT,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Package ``opengate_kit.zip`` and ``payload_manifest.json`` into ``out_dir``."""
    entries = collect_android_kit_entries(repo_root)
    files_sha: dict[str, str] = {}
    total_bytes = 0
    for arc_path, src_path in entries:
        raw = src_path.read_bytes()
        files_sha[arc_path] = _sha256_bytes(raw)
        total_bytes += len(raw)

    manifest: dict[str, Any] = {
        "schema": "opengate_android_payload_v1",
        "license": "GPL-3.0-or-later",
        "persistent_writes": False,
        "bodies": list(BODY_IDS),
        "file_count": len(files_sha),
        "total_uncompressed_bytes": total_bytes,
        "files": files_sha,
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf8")

    zip_path = out_dir / "opengate_kit.zip"
    manifest_path = out_dir / "payload_manifest.json"
    zip_sha = ""

    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for arc_path, src_path in entries:
                zi = zipfile.ZipInfo(arc_path, date_time=DETERMINISTIC_ZIP_DT)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = (0o644 & 0xFFFF) << 16
                zf.writestr(zi, src_path.read_bytes())

            m_zi = zipfile.ZipInfo("payload_manifest.json", date_time=DETERMINISTIC_ZIP_DT)
            m_zi.compress_type = zipfile.ZIP_DEFLATED
            m_zi.external_attr = (0o644 & 0xFFFF) << 16
            zf.writestr(m_zi, manifest_bytes)

        manifest_path.write_bytes(manifest_bytes)
        zip_sha = _sha256_bytes(zip_path.read_bytes())

    return {
        "ok": True,
        "dry_run": dry_run,
        "out_dir": str(out_dir),
        "zip_path": str(zip_path),
        "manifest_path": str(manifest_path),
        "zip_sha256": zip_sha,
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "file_count": len(files_sha),
        "total_uncompressed_bytes": total_bytes,
    }


def verify_android_kit_zip(zip_path: Path) -> dict[str, Any]:
    """Verify every file inside ``opengate_kit.zip`` matches embedded ``payload_manifest.json``."""
    errors: list[str] = []
    if not zip_path.is_file():
        return {"ok": False, "checked_files": 0, "errors": [f"Missing archive: {zip_path}"]}

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())
        if "payload_manifest.json" not in names:
            return {"ok": False, "checked_files": 0, "errors": ["Missing payload_manifest.json inside zip"]}

        manifest = json.loads(zf.read("payload_manifest.json").decode("utf8"))
        pinned_files = manifest.get("files", {})
        if not isinstance(pinned_files, dict) or not pinned_files:
            return {"ok": False, "checked_files": 0, "errors": ["Empty files map in payload_manifest.json"]}

        extra = sorted((names - {"payload_manifest.json"}) - set(pinned_files))
        for item in extra:
            errors.append(f"Unpinned entry in zip: {item}")

        checked = 0
        for rel_path, want_sha in sorted(pinned_files.items()):
            checked += 1
            if rel_path not in names:
                errors.append(f"Missing pinned entry in zip: {rel_path}")
                continue
            got_sha = _sha256_bytes(zf.read(rel_path))
            if got_sha != want_sha:
                errors.append(f"SHA-256 mismatch for {rel_path}: {got_sha} != {want_sha}")

    return {
        "ok": len(errors) == 0,
        "checked_files": checked,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=REPO_ROOT / "android" / "app" / "src" / "main" / "assets",
        help="Destination directory for opengate_kit.zip and payload_manifest.json",
    )
    ap.add_argument("--dry-run", action="store_true", help="Validate clean-room entries without writing zip")
    ap.add_argument("--verify", type=Path, help="Verify an existing opengate_kit.zip archive")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.verify is not None:
        res = verify_android_kit_zip(args.verify)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            if res["ok"]:
                print(f"ANDROID KIT VERIFY PASS: {res['checked_files']} pinned entries verified.")
            else:
                print("ANDROID KIT VERIFY FAIL:")
                for err in res["errors"]:
                    print(f"  - {err}")
        return 0 if res["ok"] else 1

    res = build_android_kit(out_dir=args.out_dir, repo_root=REPO_ROOT, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        mode = "DRY-RUN" if res["dry_run"] else "BUILT"
        print(
            f"ANDROID KIT {mode}: {res['file_count']} files "
            f"({res['total_uncompressed_bytes']} bytes) -> {res['zip_path']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
