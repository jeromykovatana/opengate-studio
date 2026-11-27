#!/usr/bin/env python3
"""Generate C headers and expected JSON for Sony ZV-E10 Mark I (ZV-E10 v2.03) in OpenGate Studio."""
from __future__ import annotations

import hashlib
import json
import os
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parents[1]
WORKSPACE_ROOT = STUDIO_ROOT.parent

FW_DIR = Path(os.environ.get("SONY_FW_DIR", str(WORKSPACE_ROOT / "firmwares/zve10/ghidra_targets")))

MODEL = "ZV-E10"
FIRMWARE = "2.03"
BUILD = "zve10_203"
LABEL = "zve10read_v1"

AVCAM_PHYS = 0x035C6000
AVCAM_RESERVE = "@0x02E68000"

DUMP_RANGES = (
    ("boottime", 0x03585000, 4),
    ("klog", 0x035A5000, 4),
    ("alog", 0x03525000, 4),
    ("mode_ids", AVCAM_PHYS + 0x91B000, 1),
    ("sensor_geom", AVCAM_PHYS + 0x8A6000, 2),
    ("outsz", AVCAM_PHYS + 0x87D000, 2),
    ("clip_prof", AVCAM_PHYS + 0x89D000, 2),
    ("desc", AVCAM_PHYS + 0x8C8000, 2),
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


def build_ogsq_zve10(av: bytes):
    """Build ogsq_zve10_v1: swap 4K24p record (0x8a6654..0x8a6713) geometry to full-height 3:2 (0x8a6594..0x8a6653)."""
    diffs = [
        (0x8A6654, "01000000", "00000000"),
        (0x8A665C, "0f000000", "11000000"),
        (0x8A667C, "00003400", "00003800"),
        (0x8A6680, "30009017", "50008c17"),
        (0x8A6684, "440d3400", "c00f3800"),
        (0x8A6688, "00009017", "00008c17"),
        (0x8A668C, "30000000", "4e000000"),
        (0x8A6694, "00000200", "00000400"),
        (0x8A6698, "400d0200", "b80f0400"),
        (0x8A66BC, "00002000", "00000000"),
        (0x8A66C0, "3000a017", "5000a017"),
        (0x8A66C4, "440d0a00", "c00f1000"),
        (0x8A66C8, "300d1000", "a00f0c00"),
        (0x8A66D8, "0200400d", "0400b80f"),
        (0x8A66DC, "04008817", "00008817"),
        (0x8A66E0, "770d0000", "20100000"),
    ]
    sites = []
    for off, old_hx, new_hx in diffs:
        old, new = bytes.fromhex(old_hx), bytes.fromhex(new_hx)
        assert av[off:off + len(old)] == old, f"ZV-E10 ogsq mismatch @ {hex(off)}"
        assert av[off - 0xC0:off - 0xC0 + len(new)] == new, f"ZV-E10 full3:2 ref mismatch @ {hex(off - 0xc0)}"
        sites.append((off, 1, old, new))
    guards = [
        (0x8A6594, av[0x8A6594:0x8A65A4]),
        (0x8A6658, av[0x8A6658:0x8A665C]),
        (0x8A6660, av[0x8A6660:0x8A6668]),
        (0x8A66CC, av[0x8A66CC:0x8A66D8]),
    ]
    return sites, guards


def build_outsz_zve10(av: bytes):
    """Build outsz2560_zve10_v1: movie output height 2160 -> 2560 at all 9 av-cam.bin sites."""
    offs = [0x87DCFC, 0x87DD04, 0x87DDA4, 0x87DDAC, 0x87E340, 0x87E34C, 0xFED3D8, 0xFED3E0, 0x1019C3C]
    old = bytes.fromhex("70080000")
    new = bytes.fromhex("000a0000")
    sites, guards = [], []
    for off in offs:
        assert av[off - 4:off] == bytes.fromhex("000f0000"), f"ZV-E10 outsz guard mismatch @ {hex(off - 4)}"
        assert av[off:off + 4] == old, f"ZV-E10 outsz stock mismatch @ {hex(off)}"
        guards.append((off - 4, av[off - 4:off]))
        sites.append((off, 1, old, new))
    return sites, guards


def build_ogfile_zve10(av: bytes, lm: bytes):
    """Build ogfile2560_zve10_v1: A3-clip + A1-desc + A2-profile in av-cam.bin, L1-comb in libmpr.so."""
    av_sites, av_guards = [], []
    for off in (0x89DAE2, 0x89DAF2):
        assert av[off - 2:off] == bytes.fromhex("000f")
        assert av[off:off + 2] == bytes.fromhex("7008")
        av_guards.append((off - 2, av[off - 2:off]))
        av_sites.append((off, 1, bytes.fromhex("7008"), bytes.fromhex("000a")))
    assert struct.unpack_from("<HH", av, 0x89DB00) == (4096, 2160)
    av_guards.append((0x89DB00, av[0x89DB00:0x89DB08]))

    desc_rows = [
        0x8C8F9C, 0x8C8FC4, 0x8C8FEC, 0x8C9014, 0x8C903C, 0x8C9064,
        0x8C9564, 0x8C958C, 0x8C95B4, 0x8C95DC, 0x8C9604, 0x8C962C,
        0x8C9E24, 0x8C9E4C,
    ]
    for row in desc_rows:
        off = row + 0x22
        assert av[off - 2:off] == bytes.fromhex("000f")
        assert av[off:off + 2] == bytes.fromhex("7008")
        av_guards.append((off - 2, av[off - 2:off]))
        av_sites.append((off, 1, bytes.fromhex("7008"), bytes.fromhex("000a")))

    for base in (0x89E0CC, 0x89ED90):
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
        0xC43C8C, 0xC43D24, 0xC43DBC, 0xC43E54, 0xC44C58, 0xC44CF0, 0xC44D88, 0xC44E20,
        0xC45378, 0xC45410, 0xC454A8, 0xC45540, 0xC48A18, 0xC48AB0, 0xC49BE8, 0xC49C80,
        0xC4D648, 0xC4D6E0, 0xC4D778, 0xC4D810,
    ]
    comb_25 = [
        0xC43734, 0xC437CC, 0xC43864, 0xC438FC, 0xC449F8, 0xC44A90, 0xC44B28, 0xC44BC0,
        0xC45118, 0xC451B0, 0xC45248, 0xC452E0, 0xC488E8, 0xC48980, 0xC49AB8, 0xC49B50,
        0xC4D188, 0xC4D220, 0xC4D2B8, 0xC4D350,
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
        f"/* Generated by gen_zve10_packs.py for {MODEL} {FIRMWARE} ({design_name}). Do not edit. */",
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

    og_sites, og_guards = build_ogsq_zve10(av)
    oz_sites, oz_guards = build_outsz_zve10(av)
    fl_av_sites, fl_av_guards, fl_lm_sites, fl_lm_guards = build_ogfile_zve10(av, lm)

    meta_og = emit_mp_header(
        HERE / "expected_mp_ogsq_zve10_v1.h",
        "ogsq_zve10_v1", av_sha, lm_sha,
        og_sites + [(a, 0, g, b"") for a, g in og_guards],
        [(0, 0, lm[:16], b"")],
        len(av), len(lm),
    )
    meta_oz = emit_mp_header(
        HERE / "expected_mp_outsz2560_zve10_v1.h",
        "outsz2560_zve10_v1", av_sha, lm_sha,
        oz_sites + [(a, 0, g, b"") for a, g in oz_guards],
        [(0, 0, lm[:16], b"")],
        len(av), len(lm),
    )
    meta_fl = emit_mp_header(
        HERE / "expected_mp_ogfile2560_zve10_v1.h",
        "ogfile2560_zve10_v1", av_sha, lm_sha,
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
        ("av_outsz0", 0x87D000, 0x600),
        ("av_sensor0", 0x8A6000, 0x500),
        ("av_desc0", 0x8C8000, 0x300),
    )
    lm_guard_pages = (
        ("lm_hdr", 0x0, 0x1000),
        ("lm_comb0", 0xC42000, 0x1000),
    )
    av_lo = min(s[0] for s in all_av_sites) & ~0xFFF
    av_hi = (max(s[0] + len(s[3]) for s in all_av_sites) + 0xFFF) & ~0xFFF

    h16 = lambda b: hx(b.ljust(16, b"\0"))
    out = [
        f"/* Generated by gen_zve10_packs.py from {MODEL} {FIRMWARE}. Do not edit. */",
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

    (HERE / "zve10_expected.h").write_text("\n".join(out) + "\n", encoding="utf8", newline="\n")

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
    (HERE / "zve10_expected.json").write_text(json.dumps(exp_json, indent=2) + "\n", encoding="utf8", newline="\n")
    print(f"ZV-E10 generated: av_sites={len(all_av_sites)}, lm_sites={len(all_lm_sites)}, meta={meta_og['av_sites']}+{meta_oz['av_sites']}+{meta_fl['av_sites']} av / {meta_fl['lm_sites']} lm")


if __name__ == "__main__":
    main()
