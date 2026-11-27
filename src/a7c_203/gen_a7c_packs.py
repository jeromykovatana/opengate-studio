#!/usr/bin/env python3
"""Generate C headers and expected JSON for Sony a7C Mark I (ILCE-7C v2.03) in OpenGate Studio."""
from __future__ import annotations

import hashlib
import json
import os
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parents[1]
WORKSPACE_ROOT = STUDIO_ROOT.parent

FW_DIR = Path(os.environ.get("SONY_FW_DIR", str(WORKSPACE_ROOT / "firmwares/a7c/ghidra_targets")))

MODEL = "ILCE-7C"
FIRMWARE = "2.03"
BUILD = "a7c_203"
LABEL = "a7cread_v1"

AVCAM_PHYS = 0x035C6000
AVCAM_RESERVE = "@0x02E68000"

DUMP_RANGES = (
    ("boottime", 0x03585000, 4),
    ("klog", 0x035A5000, 4),
    ("alog", 0x03525000, 4),
    ("mode_ids", AVCAM_PHYS + 0x933000, 1),
    ("sensor_geom", AVCAM_PHYS + 0x8BE000, 2),
    ("outsz", AVCAM_PHYS + 0x892000, 1),
    ("clip_prof", AVCAM_PHYS + 0x8B2000, 2),
    ("desc", AVCAM_PHYS + 0x8E4000, 2),
)

ID_FILES = {
    "/libmpr.so": "libmpr.so",
    "/libsencore.so": "libsencore.so",
    "/libJiritsu.so": "libJiritsu.so",
}


def hx(b: bytes) -> str:
    return ", ".join(f"0x{x:02x}" for x in b)


def c_bytes(b: bytes) -> str:
    return "{" + ",".join(str(x) for x in b) + "}"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def build_ogsq_a7c(av: bytes):
    """Build ogsq_a7c_v1: expand vertical height (3392/3376 -> 4032/4000) in both split-half 4K24p records."""
    sites = []
    guards = [(0x8BF3D8, av[0x8BF3D8:0x8BF3E8])]
    for tag, b_off in (("rA", 0x8BEAA0), ("rB", 0x8BEFEC)):
        guards.append((b_off - 8, av[b_off - 8:b_off + 4]))
        guards.append((b_off + 0x20, av[b_off + 0x20:b_off + 0x24]))
        guards.append((b_off + 0x60, av[b_off + 0x60:b_off + 0x64]))
        guards.append((b_off + 0x6C, av[b_off + 0x6C:b_off + 0x74]))
        rows = [
            (b_off + 0x24, "400d1c00", "c00f1c00"),
            (b_off + 0x38, "400d0000", "c00f0000"),
            (b_off + 0x44, "400d0000", "c00f0000"),
            (b_off + 0x58, "400d0000", "c00f0000"),
            (b_off + 0x5C, "f0001c00", "18001c00"),
            (b_off + 0x64, "400d0800", "c00f1000"),
            (b_off + 0x68, "300d0c00", "a00f0c00"),
            (b_off + 0x78, "0000400d", "0000c00f"),
            (b_off + 0x80, "6d0d0000", "e30f0000"),
            (b_off + 0x88, "400d0800300d0000", "c00f1000a00f0000"),
            (b_off + 0x9C, "0000400d0000940c6d0d0000", "0000c00f0000940ce30f0000"),
        ]
        for off, old_hx, new_hx in rows:
            old, new = bytes.fromhex(old_hx), bytes.fromhex(new_hx)
            assert av[off:off + len(old)] == old, f"a7C {tag} mismatch @ {hex(off)}"
            sites.append((off, 1, old, new))
    return sites, guards


def build_outsz_a7c(av: bytes):
    """Build outsz2560_a7c_v1: movie output height 2160 -> 2560 at all 9 av-cam.bin sites."""
    offs = [0x89262C, 0x892634, 0x8926D4, 0x8926DC, 0x892C70, 0x892C7C, 0x10150D0, 0x10150D8, 0x10449F4]
    old = bytes.fromhex("70080000")
    new = bytes.fromhex("000a0000")
    sites, guards = [], []
    for off in offs:
        assert av[off - 4:off] == bytes.fromhex("000f0000"), f"a7C outsz guard mismatch @ {hex(off - 4)}"
        assert av[off:off + 4] == old, f"a7C outsz stock mismatch @ {hex(off)}"
        guards.append((off - 4, av[off - 4:off]))
        sites.append((off, 1, old, new))
    return sites, guards


def build_ogfile_a7c(av: bytes, lm: bytes):
    """Build ogfile2560_a7c_v1: A3-clip + A1-desc + A2-profile in av-cam.bin, L1-comb in libmpr.so."""
    av_sites, av_guards = [], []
    for off in (0x8B2412, 0x8B2422):
        assert av[off - 2:off] == bytes.fromhex("000f")
        assert av[off:off + 2] == bytes.fromhex("7008")
        av_guards.append((off - 2, av[off - 2:off]))
        av_sites.append((off, 1, bytes.fromhex("7008"), bytes.fromhex("000a")))
    assert struct.unpack_from("<HH", av, 0x8B2430) == (4096, 2160)
    av_guards.append((0x8B2430, av[0x8B2430:0x8B2438]))

    desc_rows = [
        0x8E4324, 0x8E434C, 0x8E4374, 0x8E439C, 0x8E43C4, 0x8E43EC,
        0x8E48EC, 0x8E4914, 0x8E493C, 0x8E4964, 0x8E498C, 0x8E49B4,
        0x8E51AC, 0x8E51D4,
    ]
    for row in desc_rows:
        off = row + 0x22
        assert av[off - 2:off] == bytes.fromhex("000f")
        assert av[off:off + 2] == bytes.fromhex("7008")
        av_guards.append((off - 2, av[off - 2:off]))
        av_sites.append((off, 1, bytes.fromhex("7008"), bytes.fromhex("000a")))

    for base in (0x8B29FC, 0x8B36C0):
        assert struct.unpack_from("<6I", av, base) == (1984, 2160, 1984, 540, 496, 135)
        av_guards.append((base, av[base:base + 4]))
        av_sites.append((base + 4, 1, bytes.fromhex("70080000"), bytes.fromhex("000a0000")))
        av_guards.append((base + 8, av[base + 8:base + 12]))
        av_sites.append((
            base + 12,
            1,
            bytes.fromhex("1c020000f001000087000000"),
            bytes.fromhex("80020000f0010000a0000000"),
        ))

    lm_sites, lm_guards = [], [(0x0, lm[:16])]
    comb_24 = [
        0xC43B4C, 0xC43BE4, 0xC43C7C, 0xC43D14, 0xC44B18, 0xC44BB0, 0xC44C48, 0xC44CE0,
        0xC45238, 0xC452D0, 0xC45368, 0xC45400, 0xC488D8, 0xC48970, 0xC49AA8, 0xC49B40,
        0xC4D508, 0xC4D5A0, 0xC4D638, 0xC4D6D0,
    ]
    comb_25 = [
        0xC435F4, 0xC4368C, 0xC43724, 0xC437BC, 0xC448B8, 0xC44950, 0xC449E8, 0xC44A80,
        0xC44FD8, 0xC45070, 0xC45108, 0xC451A0, 0xC487A8, 0xC48840, 0xC49978, 0xC49A10,
        0xC4D048, 0xC4D0E0, 0xC4D178, 0xC4D210,
    ]
    for off in sorted(comb_24 + comb_25):
        assert lm[off:off + 4] == bytes.fromhex("7008000f"), f"libmpr mismatch @ {hex(off)}"
        lm_sites.append((off, 1, bytes.fromhex("7008"), bytes.fromhex("000a")))
        lm_guards.append((off + 2, lm[off + 2:off + 4]))
    assert len(lm_sites) == 40
    return av_sites, av_guards, lm_sites, lm_guards


def emit_mp_header(out_path: Path, design_name: str, av_sha: str, lm_sha: str, av_entries, lm_entries, av_len: int, lm_len: int):
    av_sorted = sorted(av_entries)
    lm_sorted = sorted(lm_entries)
    assert all(av_sorted[i][0] + len(av_sorted[i][2]) <= av_sorted[i + 1][0] for i in range(len(av_sorted) - 1)), "av overlap"
    assert all(lm_sorted[i][0] + len(lm_sorted[i][2]) <= lm_sorted[i + 1][0] for i in range(len(lm_sorted) - 1)), "lm overlap"
    av_first = av_sorted[0][0] & ~0xFFF
    av_last = max(off + len(old) for off, _, old, _ in av_sorted)
    av_bytes = ((av_last - av_first) + 0xFFF) & ~0xFFF
    assert av_first + av_bytes <= ((av_len + 0xFFF) & ~0xFFF)
    assert all(off + len(old) <= lm_len for off, _, old, _ in lm_sorted)

    h16 = lambda b: hx(b.ljust(16, b"\0"))
    longest = max(len(av_sorted), len(lm_sorted), 1)
    lines = [
        f"/* Generated by gen_a7c_packs.py for {MODEL} {FIRMWARE} ({design_name}). Do not edit. */",
        f"/* av-cam.bin {av_sha[:16]}..., libmpr.so {lm_sha[:16]}... */",
        f'#define MP_DESIGN "{design_name}"',
        f"#define AVCAM_PHYS {AVCAM_PHYS:#x}U",
        f'#define AVCAM_RESERVE "{AVCAM_RESERVE}"',
        f"#define MP_AV_FIRST {av_first:#x}U",
        f"#define MP_AV_BYTES {av_bytes:#x}U",
        f"#define MP_MAX {max(96, (longest + 31) & ~31)}",
        "struct mp_site { u32 off; u8 len; u8 kind; u8 stock[16]; u8 changed[16]; };",
        "static const struct mp_site mp_av[] = {",
    ]
    for off, kind, old, new in av_sorted:
        assert len(old) <= 16
        lines.append(f"    {{ {off:#x}U, {len(old)}, {kind}, {{ {h16(old)} }}, {{ {h16(new)} }} }},")
    lines.append("};")
    lines.append("static const struct mp_site mp_lm[] = {")
    for off, kind, old, new in lm_sorted:
        assert len(old) <= 16
        lines.append(f"    {{ {off:#x}U, {len(old)}, {kind}, {{ {h16(old)} }}, {{ {h16(new)} }} }},")
    lines.append("};")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf8", newline="\n")
    return {
        "design": design_name,
        "av_first": hex(av_first),
        "av_bytes": hex(av_bytes),
        "av_sites": sum(1 for e in av_sorted if e[1] == 1),
        "av_guards": sum(1 for e in av_sorted if e[1] == 0),
        "lm_sites": sum(1 for e in lm_sorted if e[1] == 1),
        "lm_guards": sum(1 for e in lm_sorted if e[1] == 0),
    }


def main() -> None:
    av = (FW_DIR / "av-cam.bin").resolve().read_bytes()
    lm = (FW_DIR / "libmpr.so").resolve().read_bytes()
    av_sha, lm_sha = sha256_bytes(av), sha256_bytes(lm)

    og_sites, og_guards = build_ogsq_a7c(av)
    oz_sites, oz_guards = build_outsz_a7c(av)
    fl_av_sites, fl_av_guards, fl_lm_sites, fl_lm_guards = build_ogfile_a7c(av, lm)

    meta_og = emit_mp_header(
        HERE / "expected_mp_ogsq_a7c_v1.h",
        "ogsq_a7c_v1", av_sha, lm_sha,
        og_sites + [(a, 0, g, b"") for a, g in og_guards],
        [(0, 0, lm[:16], b"")],
        len(av), len(lm),
    )
    meta_oz = emit_mp_header(
        HERE / "expected_mp_outsz2560_a7c_v1.h",
        "outsz2560_a7c_v1", av_sha, lm_sha,
        oz_sites + [(a, 0, g, b"") for a, g in oz_guards],
        [(0, 0, lm[:16], b"")],
        len(av), len(lm),
    )
    meta_fl = emit_mp_header(
        HERE / "expected_mp_ogfile2560_a7c_v1.h",
        "ogfile2560_a7c_v1", av_sha, lm_sha,
        fl_av_sites + [(a, 0, g, b"") for a, g in fl_av_guards],
        fl_lm_sites + [(a, 0, g, b"") for a, g in fl_lm_guards],
        len(av), len(lm),
    )

    all_av_sites = sorted(
        [(off, f"ogsq_{i}", 1, old, new) for i, (off, _, old, new) in enumerate(og_sites)]
        + [(off, f"outsz_{i}", 2, old, new) for i, (off, _, old, new) in enumerate(oz_sites)]
        + [(off, f"ogfile_{i}", 3, old, new) for i, (off, _, old, new) in enumerate(fl_av_sites)]
    )
    assert all(all_av_sites[i][0] + len(all_av_sites[i][3]) <= all_av_sites[i + 1][0] for i in range(len(all_av_sites) - 1))
    all_lm_sites = sorted([(off, f"comb_{i}", 3, old, new) for i, (off, _, old, new) in enumerate(fl_lm_sites)])

    av_guard_pages = (
        ("av_hdr", 0x0, 0x1000),
        ("av_outsz0", 0x892000, 0x600),
        ("av_sensor0", 0x8BE000, 0x800),
        ("av_desc0", 0x8E4000, 0x300),
    )
    lm_guard_pages = (
        ("lm_hdr", 0x0, 0x1000),
        ("lm_comb0", 0xC42000, 0x1000),
    )
    av_lo = min(s[0] for s in all_av_sites) & ~0xFFF
    av_hi = (max(s[0] + len(s[3]) for s in all_av_sites) + 0xFFF) & ~0xFFF

    h16 = lambda b: hx(b.ljust(16, b"\0"))
    out = [
        f"/* Generated by gen_a7c_packs.py from {MODEL} {FIRMWARE}. Do not edit. */",
        "#ifndef DUMP",
        "#define DUMP 0",
        "#endif",
        f'#define MODEL_LABEL "{LABEL}"',
        f"#define AVCAM_PHYS {AVCAM_PHYS:#x}U",
        f'#define AVCAM_RESERVE "{AVCAM_RESERVE}"',
        f"#define AV_LO {av_lo:#x}U",
        f"#define AV_HI {av_hi:#x}U",
        f"#define OGSQ_AV_SITES {len(og_sites)}U",
        "static const struct id_file id_files[] = {",
    ]
    id_hashes = {}
    for name, fn in ID_FILES.items():
        dig = hashlib.sha256((FW_DIR / fn).resolve().read_bytes()).digest()
        id_hashes[name] = dig.hex()
        out.append(f'    {{ "{name}", {c_bytes(dig)} }},')
    out.append("};")

    out.append("static const struct page_guard av_guards[] = {")
    for gname, goff, glen in av_guard_pages:
        dig = hashlib.sha256(av[goff:goff + glen]).digest()
        out.append(f'    {{ "{gname}", {goff:#x}U, {glen:#x}U, {c_bytes(dig)} }},')
    out.append("};")

    out.append("static const struct page_guard lm_guards[] = {")
    for gname, goff, glen in lm_guard_pages:
        dig = hashlib.sha256(lm[goff:goff + glen]).digest()
        out.append(f'    {{ "{gname}", {goff:#x}U, {glen:#x}U, {c_bytes(dig)} }},')
    out.append("};")

    out.append("static const struct mp_ro_site av_sites[] = {")
    for off, sname, grp, old, new in all_av_sites:
        out.append(f'    {{ "{sname}", {off:#x}U, {len(old)}, {grp}, {{ {h16(old)} }}, {{ {h16(new)} }} }},')
    out.append("};")

    out.append("static const struct mp_ro_site lm_sites[] = {")
    for off, sname, grp, old, new in all_lm_sites:
        out.append(f'    {{ "{sname}", {off:#x}U, {len(old)}, {grp}, {{ {h16(old)} }}, {{ {h16(new)} }} }},')
    out.append("};")

    out.append("#if DUMP")
    out.append("static const struct dump_range dump_ranges[] = {")
    for dname, dphys, dpages in DUMP_RANGES:
        out.append(f'    {{ "{dname}", {dphys:#x}U, {dpages}U }},')
    out.append("};")
    out.append("#endif")

    (HERE / "a7c_expected.h").write_text("\n".join(out) + "\n", encoding="utf8", newline="\n")

    # Note: Studio's parse_readonly_result validates all emitted `guard <name>` lines against `av_guards`
    exp_json = {
        "model": MODEL,
        "firmware": FIRMWARE,
        "build": BUILD,
        "label": LABEL,
        "avcam_phys": hex(AVCAM_PHYS),
        "avcam_reserve": AVCAM_RESERVE,
        "id_files": id_hashes,
        "id_pages": {},
        "cp_sites": [],
        "av_sites": len(all_av_sites),
        "lm_sites": len(all_lm_sites),
        "av_guards": [g[0] for g in lm_guard_pages] + [g[0] for g in av_guard_pages],
        "dump_ranges": [[n, hex(a), k] for n, a, k in DUMP_RANGES],
        "designs": {"ogsq": meta_og, "outsz2560": meta_oz, "ogfile2560": meta_fl},
    }
    (HERE / "a7c_expected.json").write_text(json.dumps(exp_json, indent=2) + "\n", encoding="utf8", newline="\n")
    print(f"a7C generated: av_sites={len(all_av_sites)}, lm_sites={len(all_lm_sites)}, meta={meta_og['av_sites']}+{meta_oz['av_sites']}+{meta_fl['av_sites']} av / {meta_fl['lm_sites']} lm")


if __name__ == "__main__":
    main()
