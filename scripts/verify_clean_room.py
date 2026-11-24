#!/usr/bin/env python3
"""Clean-room, toolchain, SHA-256 pin, and ELF symbol verifier for sony-opengate-studio."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_EXTS = {".dat", ".bin", ".img", ".tar", ".elf"}
FORBIDDEN_DIR_NAMES = {"fx30_fw", "firmwares", "camera_private"}
FORBIDDEN_NAME_TOKENS = (
    "bodydata",
    "nflasha",
    "cpapp",
    "av-cam",
    "appfw",
    "libmpr",
    "libsencore",
    "libjiritsu",
    "dmmcfg",
    "fx30_fw",
)
CODE_EXTS = {".py", ".c", ".h", ".sh", ".swift"}

# Split tokens so this script never triggers on its own literals
FORBIDDEN_CODE_PATTERNS = [
    ("CC BY-NC-SA license text", re.compile(r"CC\s*BY-" + r"NC-SA", re.IGNORECASE)),
    ("fx30_fw reference", re.compile(r"\bfx30_" + r"fw\b", re.IGNORECASE)),
    ("CXD90057_k8 key label", re.compile(r"CXD90057_" + r"k8", re.IGNORECASE)),
]

ALLOWED_UNDEFINED_SYMBOLS = {
    "_Z9dmm_allocjPj",
    "_Z8dmm_freej",
    "sen_dma_transfer",
}
ALLOWED_DEFINED_SYMBOLS = {
    "",
    "__bss_start",
    "__bss_start__",
    "_edata",
    "_end",
    "__end__",
    "__init_array_start",
    "__init_array_end",
    "__fini_array_start",
    "__fini_array_end",
    "__TMC_END__",
    "_GLOBAL_OFFSET_TABLE_",
    "JNI_OnLoad",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_elf64_aarch64_dynsym(data: bytes) -> tuple[list[str], list[str]]:
    """Return (undefined_symbols, defined_symbols) from an ELF64 AArch64 .so."""
    if len(data) < 64 or data[:4] != b"\x7fELF":
        raise ValueError("Not an ELF binary")
    if data[4] != 2 or data[5] != 1:
        raise ValueError("Not ELF64 little-endian")
    e_type, e_machine = struct.unpack_from("<HH", data, 16)
    if e_type != 3 or e_machine != 183:
        raise ValueError(f"Expected ET_DYN(3)/EM_AARCH64(183), got ({e_type}, {e_machine})")
    e_shoff, _, e_ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<QIHHHHHH", data, 40)
    if e_shoff == 0 or e_shnum == 0:
        return [], []

    sections = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        sh = struct.unpack_from("<IIQQQQIIQQ", data, off)
        sections.append({
            "name_off": sh[0],
            "type": sh[1],
            "offset": sh[4],
            "size": sh[5],
            "link": sh[6],
            "entsize": sh[9],
        })

    undef: list[str] = []
    defined: list[str] = []
    for sec in sections:
        if sec["type"] != 11:  # SHT_DYNSYM
            continue
        str_sec = sections[sec["link"]]
        strtab = data[str_sec["offset"] : str_sec["offset"] + str_sec["size"]]
        entsize = sec["entsize"] or 24
        count = sec["size"] // entsize
        for idx in range(count):
            sym_off = sec["offset"] + idx * entsize
            st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from("<IBBHQQ", data, sym_off)
            if idx == 0 and st_name == 0:
                continue
            end_null = strtab.find(b"\x00", st_name)
            name = strtab[st_name : end_null if end_null != -1 else len(strtab)].decode("utf8", "replace")
            if st_shndx == 0:
                undef.append(name)
            else:
                defined.append(name)
    return undef, defined


def _extract_entry_file_sha(entry: Any) -> tuple[str | None, str | None]:
    if isinstance(entry, dict):
        fname = entry.get("filename") or entry.get("file") or entry.get("so") or entry.get("name")
        return fname, entry.get("sha256")
    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
        return str(entry[0]), str(entry[1])
    return None, None


def verify_clean_room(root: Path = REPO_ROOT) -> dict[str, Any]:
    errors: list[str] = []
    checked_so = 0
    checked_code_files = 0
    checked_manifests = 0

    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        parts_lower = {p.lower() for p in rel.parts}
        if ".git" in parts_lower or ".build" in parts_lower:
            continue

        if path.is_dir():
            if path.name.lower() in FORBIDDEN_DIR_NAMES:
                errors.append(f"Forbidden directory present: {rel}")
            continue

        name_lower = path.name.lower()
        if path.suffix.lower() in FORBIDDEN_EXTS:
            errors.append(f"Forbidden binary/archive file extension: {rel}")
        if any(tok in name_lower for tok in FORBIDDEN_NAME_TOKENS) and not name_lower.startswith("libjit_"):
            errors.append(f"Forbidden Sony/unpacker artifact name: {rel}")

        if path.suffix.lower() in CODE_EXTS and path.resolve() != Path(__file__).resolve():
            checked_code_files += 1
            text = path.read_text(encoding="utf8", errors="replace")
            for label, pat in FORBIDDEN_CODE_PATTERNS:
                if pat.search(text):
                    errors.append(f"{rel}: forbidden clean-room pattern ({label})")

    kits_dir = root / "kits"
    if not kits_dir.is_dir():
        errors.append("Missing kits/ directory")
    else:
        for kit in sorted(p for p in kits_dir.iterdir() if p.is_dir()):
            man_path = kit / "manifest.json"
            if not man_path.is_file():
                errors.append(f"Missing manifest.json in kits/{kit.name}")
                continue
            checked_manifests += 1
            man = json.loads(man_path.read_text(encoding="utf8"))
            pinned_so: dict[str, str] = {}
            for section in ("readonly", "steps"):
                for k, entry in man.get(section, {}).items():
                    fname, want_sha = _extract_entry_file_sha(entry)
                    if not fname or not want_sha:
                        errors.append(f"kits/{kit.name}/manifest.json {section}.{k}: missing filename/sha256")
                        continue
                    pinned_so[fname] = want_sha
            dev_info = man.get("device_info")
            if isinstance(dev_info, dict):
                fname, want_sha = _extract_entry_file_sha(dev_info)
                if fname and want_sha:
                    p = kit / fname
                    if not p.is_file() or sha256_file(p) != want_sha:
                        errors.append(f"kits/{kit.name}/{fname}: missing or SHA-256 mismatch")

            disk_so = {p.name for p in kit.glob("*.so")}
            for extra in sorted(disk_so - set(pinned_so)):
                errors.append(f"kits/{kit.name}/{extra}: unpinned .so not in manifest.json")

            for fname, want_sha in sorted(pinned_so.items()):
                so_path = kit / fname
                if not so_path.is_file():
                    errors.append(f"kits/{kit.name}/{fname}: missing")
                    continue
                checked_so += 1
                got_sha = sha256_file(so_path)
                if got_sha != want_sha:
                    errors.append(f"kits/{kit.name}/{fname}: SHA-256 {got_sha} != {want_sha}")
                raw = so_path.read_bytes()
                if b"clang version 18.1.6" not in raw:
                    errors.append(f"kits/{kit.name}/{fname}: missing 'clang version 18.1.6' toolchain marker")
                try:
                    undef, defined = parse_elf64_aarch64_dynsym(raw)
                    bad_undef = [s for s in undef if s not in ALLOWED_UNDEFINED_SYMBOLS]
                    bad_def = [s for s in defined if s not in ALLOWED_DEFINED_SYMBOLS]
                    if bad_undef:
                        errors.append(f"kits/{kit.name}/{fname}: unexpected undefined ELF imports {bad_undef}")
                    if bad_def:
                        errors.append(f"kits/{kit.name}/{fname}: unexpected exported ELF symbols {bad_def}")
                except ValueError as err:
                    errors.append(f"kits/{kit.name}/{fname}: ELF parse error: {err}")

    return {
        "ok": len(errors) == 0,
        "checked_manifests": checked_manifests,
        "checked_so": checked_so,
        "checked_code_files": checked_code_files,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    res = verify_clean_room(REPO_ROOT)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        if res["ok"]:
            print(
                f"CLEAN-ROOM PASS: {res['checked_manifests']} manifests, "
                f"{res['checked_so']} .so helpers (clang 18.1.6, zero unexpected symbols), "
                f"{res['checked_code_files']} code files checked, 0 violations."
            )
        else:
            print("CLEAN-ROOM FAIL:")
            for e in res["errors"]:
                print(f"  - {e}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
