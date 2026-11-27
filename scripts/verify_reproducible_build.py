#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Independently verify reproducible SHA-256 helper builds for all 62 committed .so artifacts.

Modes:
1. Default clean-room mode (zero Sony firmware required):
   Compiles a tiny clean-room stub libsencore.so exporting the 3 dynamic symbols
   imported by the DMM/sensor/reader helpers (_Z9dmm_allocjPj, _Z8dmm_freej,
   sen_dma_transfer), invokes the three per-body build scripts with SKIP_GEN=1
   and SKIP_EMIT_MANIFEST=1 into a temporary directory, and verifies that all
   62 rebuilt helpers match the SHA-256 hashes committed in kits/*/manifest.json.

2. Offline firmware mode (--fw-root <path>):
   Accepts an offline local firmware root containing:
     - <fw-root>/zve1/ghidra_targets
     - <fw-root>/a7siii/ghidra_targets
     - <fw-root>/fx3/ghidra_targets
   Copies src/ into a temporary workspace, re-runs the header generators against
   those offline Sony binaries, verifies the regenerated C headers match the
   committed headers in src/, builds all 62 helpers against the real offline
   libsencore.so files, and asserts 62/62 SHA-256 matches against manifests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

KITS = (
    ("zve1_202", "zve1", "src/zve1_202/build_zv_studio.sh", ("gen_zv_studio.py", "gen_zv_v4.py")),
    ("a7s3_501", "a7siii", "src/a7s3_501/build_s3_packs.sh", ("gen_s3_packs.py",)),
    ("fx3_702", "fx3", "src/fx3_702/build_fx3_packs.sh", ("gen_fx3_packs.py",)),
)

STUB_C = """
__asm__(
".globl _Z8dmm_freej\\n.type _Z8dmm_freej,%function\\n_Z8dmm_freej: ret\\n"
".globl _end\\n_end = 0\\n"
".globl _edata\\n_edata = 0\\n"
".globl _Z9dmm_allocjPj\\n.type _Z9dmm_allocjPj,%function\\n_Z9dmm_allocjPj: ret\\n"
".globl __bss_start\\n__bss_start = 0\\n"
".globl sen_dma_transfer\\n.type sen_dma_transfer,%function\\nsen_dma_transfer: ret\\n"
);
""".lstrip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def collect_expected_helpers(root: Path) -> dict[str, dict[str, dict[str, object]]]:
    expected: dict[str, dict[str, dict[str, object]]] = {}
    for kit_id, _, _, _ in KITS:
        man_path = root / "kits" / kit_id / "manifest.json"
        man = json.loads(man_path.read_text(encoding="utf-8"))
        files: dict[str, dict[str, object]] = {}
        if isinstance(man.get("helper_sha256"), dict) and all(
            isinstance(v, str) for v in man["helper_sha256"].values()
        ):
            for fname, digest in man["helper_sha256"].items():
                committed = root / "kits" / kit_id / fname
                files[fname] = {
                    "sha256": digest,
                    "committed_exists": committed.is_file(),
                    "committed_sha256": sha256_file(committed) if committed.is_file() else None,
                }
        else:
            # Fallback to helper_catalog or files list if schema differs
            for fname in sorted(p.name for p in (root / "kits" / kit_id).glob("*.so")):
                committed = root / "kits" / kit_id / fname
                files[fname] = {
                    "sha256": sha256_file(committed),
                    "committed_exists": True,
                    "committed_sha256": sha256_file(committed),
                }
        expected[kit_id] = files
    return expected


def check_ziglang_available(py_exe: str) -> None:
    proc = subprocess.run(
        [py_exe, "-m", "ziglang", "version"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ziglang is not runnable under {py_exe}: {proc.stderr.strip() or proc.stdout.strip()}"
        )


def build_stub_sencore(py_exe: str, out_dir: Path) -> Path:
    stub_c = out_dir / "sencore_stub.c"
    stub_so = out_dir / "libsencore.so"
    stub_c.write_bytes(STUB_C.encode("utf-8"))
    cmd = [
        py_exe,
        "-m",
        "ziglang",
        "cc",
        "-target",
        "aarch64-linux-gnu",
        "-std=gnu11",
        "-fPIC",
        "-shared",
        "-nostdlib",
        "-ffreestanding",
        "-Wl,-soname,libsencore.so",
        str(stub_c),
        "-o",
        str(stub_so),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to build stub libsencore.so:\n{proc.stderr or proc.stdout}")
    return stub_so


def verify_elf_comment_clang18(so_path: Path) -> bool:
    data = so_path.read_bytes()
    return b"clang version 18.1.6" in data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--fw-root",
        type=Path,
        default=None,
        help="Optional local offline firmware root containing {zve1,a7siii,fx3}/ghidra_targets",
    )
    ap.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable having ziglang==0.13.0 installed (defaults to current interpreter)",
    )
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args(argv)

    py_exe = os.path.abspath(args.python) if os.path.sep in args.python or args.python.startswith(".") else args.python
    check_ziglang_available(py_exe)
    expected = collect_expected_helpers(ROOT)

    total_expected = sum(len(v) for v in expected.values())
    mismatches: list[dict[str, object]] = []
    header_diffs: list[dict[str, object]] = []
    kit_reports: dict[str, object] = {}

    with tempfile.TemporaryDirectory(prefix="og_repro_") as tmp_str:
        tmp = Path(tmp_str)
        work_root = ROOT
        if args.fw_root is not None:
            fw_root = args.fw_root.resolve()
            work_root = tmp / "studio_work"
            shutil.copytree(ROOT / "src", work_root / "src")
            shutil.copytree(ROOT / "designs", work_root / "designs")
        else:
            stub_dir = tmp / "stub"
            stub_dir.mkdir(parents=True, exist_ok=True)
            stub_sen = build_stub_sencore(py_exe, stub_dir)

        for kit_id, fw_sub, build_rel, gen_scripts in KITS:
            kit_out = tmp / "kits" / kit_id
            kit_out.mkdir(parents=True, exist_ok=True)

            env = os.environ.copy()
            env["KIT_OUT_DIR"] = str(kit_out)
            env["SKIP_EMIT_MANIFEST"] = "1"
            env["ZIG_PYTHON"] = py_exe
            env["ZIG_PY"] = py_exe
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["STUDIO_DESIGNS_DIR"] = str(work_root / "designs")

            if args.fw_root is not None:
                fw_dir = args.fw_root.resolve() / fw_sub / "ghidra_targets"
                if not (fw_dir / "libsencore.so").is_file():
                    raise FileNotFoundError(f"Missing offline libsencore.so at {fw_dir / 'libsencore.so'}")
                env["SKIP_GEN"] = "0"
                env["SONY_FW_DIR"] = str(fw_dir)
                env["SEN_SO_PATH"] = str(fw_dir / "libsencore.so")
            else:
                env["SKIP_GEN"] = "1"
                env["SEN_SO_PATH"] = str(stub_sen)

            build_script = work_root / build_rel
            proc = subprocess.run(
                ["bash", str(build_script)],
                cwd=str(work_root),
                env=env,
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Build failed for {kit_id} ({build_script}):\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
                )

            if args.fw_root is not None:
                # Compare generated headers in work_root/src/<kit_id> against committed src/<kit_id>.
                src_sub = Path(build_rel).parent
                committed_src_dir = ROOT / src_sub
                rebuilt_src_dir = work_root / src_sub
                for committed_hdr in sorted(committed_src_dir.glob("*.h")):
                    rebuilt_hdr = rebuilt_src_dir / committed_hdr.name
                    if not rebuilt_hdr.is_file():
                        header_diffs.append({"kit": kit_id, "file": committed_hdr.name, "error": "missing_rebuilt"})
                    elif sha256_file(rebuilt_hdr) != sha256_file(committed_hdr):
                        header_diffs.append(
                            {
                                "kit": kit_id,
                                "file": committed_hdr.name,
                                "expected_sha256": sha256_file(committed_hdr),
                                "rebuilt_sha256": sha256_file(rebuilt_hdr),
                            }
                        )

            kit_expected = expected[kit_id]
            matched = 0
            clang_ok = 0
            for fname, exp_meta in sorted(kit_expected.items()):
                rebuilt = kit_out / fname
                if not rebuilt.is_file():
                    mismatches.append({"kit": kit_id, "file": fname, "error": "missing_rebuilt"})
                    continue
                got_sha = sha256_file(rebuilt)
                exp_sha = str(exp_meta["sha256"])
                if got_sha != exp_sha:
                    mismatches.append(
                        {
                            "kit": kit_id,
                            "file": fname,
                            "expected_sha256": exp_sha,
                            "rebuilt_sha256": got_sha,
                        }
                    )
                else:
                    matched += 1
                if verify_elf_comment_clang18(rebuilt):
                    clang_ok += 1

            kit_reports[kit_id] = {
                "expected": len(kit_expected),
                "matched": matched,
                "clang_18_1_6": clang_ok,
                "mode": "offline_firmware" if args.fw_root is not None else "clean_room_stub",
            }

    ok = not mismatches and not header_diffs and sum(r["matched"] for r in kit_reports.values()) == total_expected
    payload = {
        "ok": ok,
        "mode": "offline_firmware" if args.fw_root is not None else "clean_room_stub",
        "total_expected": total_expected,
        "total_matched": sum(r["matched"] for r in kit_reports.values()),
        "kits": kit_reports,
        "mismatches": mismatches,
        "header_diffs": header_diffs,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"Reproducible helper build verification ({payload['mode']}): "
            f"{payload['total_matched']}/{payload['total_expected']} SHA-256 exact matches"
        )
        for kit_id, r in kit_reports.items():
            print(f"  {kit_id}: {r['matched']}/{r['expected']} matched (clang 18.1.6: {r['clang_18_1_6']})")
        if header_diffs:
            print(f"Header diffs: {header_diffs}")
        if mismatches:
            print(f"SHA mismatches: {mismatches}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
