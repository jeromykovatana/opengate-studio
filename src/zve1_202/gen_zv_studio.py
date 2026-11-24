#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate ZV-E1 2.02 volatile RAM patch headers for Open Gate Studio.

Generates in the current source directory:
  - expected_mp_ogfile2560_hs_s_zv_v3.h     (V19/V20: ogfile2560_hs_s_zv_v1 + mp4_3x2_zv_202)
  - expected_words_hdmi32_zv_202.h          (H16/H17: hdmi32_zv_202 Thumb-2 -> 4-byte ram_word)
  - expected_mp_og_highbitrate_zv_202.h     (B19/B20: og_highbitrate_zv_202)
  - expected_mp_og_xavcsi_addon_zv_202.h    (I19/I20: orthogonal delta of og_xavcsi_zv_202)

Enforces ELF64 PT_LOAD[0] bounds, cpapp-b.bin 0x108000 RAM bounds, av-cam.bin bounds,
internal non-overlap, and CRITICAL cross-pack guard-vs-site disjointness across V19, B19, I19.
"""
import argparse
import hashlib
import json
import os
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parents[1]
WS_ROOT = STUDIO_ROOT.parent
DEFAULT_FW_DIR = Path(
    os.environ.get("SONY_FW_DIR", str(WS_ROOT / "firmwares/zve1/ghidra_targets"))
)
VDES = WS_ROOT / "zve1-pr2-preflight/windows/tools/modding/designs"
DOCS_DES = WS_ROOT / "docs/designs"
STUDIO_DES = STUDIO_ROOT / "designs"

# av-cam.bin / libmpr.so constants for ZV-E1 2.02 (from ogfile2560_hs_s_zv_v1)
AV_DESC, AV_DSIZE, AV_UNIT, AV_CLIP = 0x38F8E8, 0x88, 0x38F848, 0x38D7EC
AV_PROFILE_END = 0x3BAEA0 + 299 * 0x100
LIBMPR_COMB = 0x2D32B8 - 0x205C0
CPAPP_BASE = 0x108000


def resolve_design(name: str, prefer_vdes: bool = False) -> Path:
    candidates = (
        [VDES / f"{name}.json", STUDIO_DES / f"{name}.json", DOCS_DES / f"{name}.json"]
        if prefer_vdes
        else [STUDIO_DES / f"{name}.json", DOCS_DES / f"{name}.json", VDES / f"{name}.json"]
    )
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError(f"Design JSON not found for {name}: tried {candidates}")


def hx(b: bytes) -> str:
    return ", ".join(f"0x{x:02x}" for x in b)


def h16(b: bytes) -> str:
    return hx(b.ljust(16, b"\0"))


def first_pt_load(elf: bytes) -> tuple[int, int, int]:
    phoff = struct.unpack_from("<Q", elf, 0x20)[0]
    phentsize, phnum = struct.unpack_from("<HH", elf, 0x36)
    for k in range(phnum):
        p_type, _flags, p_off, p_vaddr, _paddr, p_filesz, p_memsz, _align = struct.unpack_from(
            "<IIQQQQQQ", elf, phoff + k * phentsize
        )
        if p_type == 1:
            assert p_off == 0 and p_vaddr == 0, "unexpected PT_LOAD[0] base"
            return p_off, p_vaddr, p_filesz
    raise RuntimeError("No PT_LOAD segment found")


def av_base_guards(av: bytes) -> list[tuple[int, bytes]]:
    g = [(AV_UNIT + 0x20, av[AV_UNIT + 0x20 : AV_UNIT + 0x30]),
         (AV_CLIP + 0x50, av[AV_CLIP + 0x50 : AV_CLIP + 0x60])]
    assert struct.unpack("<4I", g[0][1]) == (0x486, 0x474, 0x477, 0x47A)
    assert struct.unpack("<4I", g[1][1]) == (1, 3840, 2160, 23)
    return g


def build_v19(av: bytes, lm: bytes, lm_filesz: int) -> dict:
    v1 = json.loads(resolve_design("ogfile2560_hs_s_zv_v1", prefer_vdes=True).read_text(encoding="utf8"))
    mp4 = json.loads(resolve_design("mp4_3x2_zv_202").read_text(encoding="utf8"))
    av_sha = hashlib.sha256(av).hexdigest()
    lm_sha = hashlib.sha256(lm).hexdigest()
    assert v1["build"] == "zve1_202" and mp4["build"] == "zve1_202"
    assert v1["artifact_sha256"] == {"libmpr.so": lm_sha, "av-cam.bin": av_sha}
    assert mp4["artifact_sha256"] == {"libmpr.so": lm_sha}

    sites_av: list[tuple[int, bytes, bytes]] = []
    sites_lm: list[tuple[int, bytes, bytes]] = []
    seen = set()

    for p in v1["patches"]:
        off, old, new = int(p["file_off"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        src = av if p["binary"] == "av-cam.bin" else lm
        assert len(old) == len(new) <= 16 and old != new and src[off : off + len(old)] == old
        key = (p["binary"], off)
        assert key not in seen
        seen.add(key)
        (sites_av if p["binary"] == "av-cam.bin" else sites_lm).append((off, old, new))

    for p in mp4["patches"]:
        assert p["binary"] == "libmpr.so"
        off, old, new = int(p["file_off"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        assert len(old) == len(new) <= 16 and old != new and lm[off : off + len(old)] == old
        assert off + len(old) <= lm_filesz
        key = ("libmpr.so", off)
        assert key not in seen
        seen.add(key)
        sites_lm.append((off, old, new))

    assert len(sites_av) == 101 and len(sites_lm) == 12

    guards_av = av_base_guards(av)
    for x in v1["descriptors"]:
        o = AV_DESC + x["descriptor"] * AV_DSIZE + 0x28
        assert struct.unpack_from("<I", av, o)[0] == x["profile_key"]
        guards_av.append((o, av[o : o + 4]))

    guards_lm: list[tuple[int, bytes]] = []
    for g in mp4["guards"]:
        off = int(g["file_off"], 16)
        b = bytes.fromhex(g["bytes"])
        assert lm[off : off + len(b)] == b and off + len(b) <= lm_filesz
        guards_lm.append((off, b))
    for p in v1["patches"]:
        if p["binary"] == "libmpr.so":
            off = int(p["file_off"], 16)
            assert (off - 6 - LIBMPR_COMB) % 0x18 == 0
            assert struct.unpack_from("<H", lm, off - 2)[0] == 3840
            guards_lm.append((off - 6, lm[off - 6 : off]))

    return {
        "name": "ogfile2560_hs_s_zv_v3",
        "header": "expected_mp_ogfile2560_hs_s_zv_v3.h",
        "av_sites": sites_av,
        "lm_sites": sites_lm,
        "av_guards": guards_av,
        "lm_guards": guards_lm,
        "av_sha": av_sha,
        "lm_sha": lm_sha,
        "lm_filesz": lm_filesz,
        "av_page_bounds": (AV_CLIP & ~0xFFF, (AV_PROFILE_END + 0xFFF) & ~0xFFF),
    }


def build_b19(av: bytes, lm: bytes, lm_filesz: int) -> dict:
    hb = json.loads(resolve_design("og_highbitrate_zv_202").read_text(encoding="utf8"))
    av_sha = hashlib.sha256(av).hexdigest()
    assert hb["build"] == "zve1_202" and hb["persistent_writes"] is False
    assert hb["artifact_sha256"]["av-cam.bin"] == av_sha

    sites_av: list[tuple[int, bytes, bytes]] = []
    for p in hb["patches"]:
        assert p["binary"] == "av-cam.bin"
        off, old, new = int(p["file_off"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        assert len(old) == len(new) <= 16 and old != new and av[off : off + len(old)] == old
        sites_av.append((off, old, new))

    guards_av: list[tuple[int, bytes]] = []
    for g in hb["guards"]:
        assert g["binary"] == "av-cam.bin"
        off, b = int(g["file_off"], 16), bytes.fromhex(g["bytes"])
        assert 0 < len(b) <= 16 and av[off : off + len(b)] == b
        guards_av.append((off, b))

    guards_lm = [(0, lm[:16])]
    assert len(sites_av) == 108 and len(guards_av) == 54
    return {
        "name": "og_highbitrate_zv_202",
        "header": "expected_mp_og_highbitrate_zv_202.h",
        "av_sites": sites_av,
        "lm_sites": [],
        "av_guards": guards_av,
        "lm_guards": guards_lm,
        "av_sha": av_sha,
        "lm_sha": hashlib.sha256(lm).hexdigest(),
        "lm_filesz": lm_filesz,
        "av_page_bounds": None,
    }


def build_i19(av: bytes, lm: bytes, lm_filesz: int, v19_keys: set[tuple[str, int]]) -> dict:
    xsi = json.loads(resolve_design("og_xavcsi_zv_202").read_text(encoding="utf8"))
    av_sha = hashlib.sha256(av).hexdigest()
    lm_sha = hashlib.sha256(lm).hexdigest()
    assert xsi["build"] == "zve1_202" and xsi["persistent_writes"] is False
    assert xsi["artifact_sha256"] == {"libmpr.so": lm_sha, "av-cam.bin": av_sha}

    sites_av: list[tuple[int, bytes, bytes]] = []
    sites_lm: list[tuple[int, bytes, bytes]] = []
    for p in xsi["patches"]:
        off = int(p["file_off"], 16)
        if (p["binary"], off) in v19_keys:
            continue
        old, new = bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        src = av if p["binary"] == "av-cam.bin" else lm
        assert len(old) == len(new) <= 16 and old != new and src[off : off + len(old)] == old
        if p["binary"] == "libmpr.so":
            assert off + len(old) <= lm_filesz
            sites_lm.append((off, old, new))
        else:
            sites_av.append((off, old, new))

    assert len(sites_av) == 16 and len(sites_lm) == 2

    guards_av: list[tuple[int, bytes]] = []
    guards_lm: list[tuple[int, bytes]] = []
    for g in xsi["guards"]:
        off, b = int(g["file_off"], 16), bytes.fromhex(g["bytes"])
        src = av if g["binary"] == "av-cam.bin" else lm
        assert 0 < len(b) <= 16 and src[off : off + len(b)] == b
        if g["binary"] == "libmpr.so":
            assert off + len(b) <= lm_filesz
            guards_lm.append((off, b))
        else:
            guards_av.append((off, b))

    return {
        "name": "og_xavcsi_addon_zv_202",
        "header": "expected_mp_og_xavcsi_addon_zv_202.h",
        "av_sites": sites_av,
        "lm_sites": sites_lm,
        "av_guards": guards_av,
        "lm_guards": guards_lm,
        "av_sha": av_sha,
        "lm_sha": lm_sha,
        "lm_filesz": lm_filesz,
        "av_page_bounds": None,
    }


def check_and_emit_mp_packs(packs: list[dict]) -> None:
    # Global cross-pack site-vs-site and guard-vs-site disjointness check
    all_sites: list[tuple[str, str, int, int]] = []
    for pk in packs:
        for bname, key in (("av-cam.bin", "av_sites"), ("libmpr.so", "lm_sites")):
            for off, old, _ in pk[key]:
                all_sites.append((pk["name"], bname, off, off + len(old)))

    # Assert no site overlaps any site of another pack
    for i in range(len(all_sites)):
        n1, b1, s1, e1 = all_sites[i]
        for j in range(i + 1, len(all_sites)):
            n2, b2, s2, e2 = all_sites[j]
            if b1 == b2 and s1 < e2 and s2 < e1:
                raise AssertionError(
                    f"Site overlap between {n1} {b1} {s1:#x}..{e1:#x} and {n2} {s2:#x}..{e2:#x}"
                )

    for pk in packs:
        filtered_notes = []
        for bname, gkey in (("av-cam.bin", "av_guards"), ("libmpr.so", "lm_guards")):
            kept = []
            for goff, gb in pk[gkey]:
                gend = goff + len(gb)
                coll = [
                    (sn, sb, ss, se)
                    for sn, sb, ss, se in all_sites
                    if sb == bname and goff < se and ss < gend
                ]
                if coll:
                    raise AssertionError(
                        f"Cross-pack guard collision in {pk['name']} {bname} {goff:#x}..{gend:#x} vs {coll}"
                    )
                kept.append((goff, gb))
            pk[gkey] = kept

        tabs = {}
        for bname, skey, gkey in (
            ("av-cam.bin", "av_sites", "av_guards"),
            ("libmpr.so", "lm_sites", "lm_guards"),
        ):
            entries = [(o, 1, old, new) for o, old, new in pk[skey]] + [
                (o, 0, b, b"") for o, b in pk[gkey]
            ]
            entries.sort(key=lambda r: (r[0], r[1]))
            for k in range(len(entries) - 1):
                a_end = entries[k][0] + len(entries[k][2])
                b_start = entries[k + 1][0]
                assert a_end <= b_start, (
                    f"Overlapping entries in {pk['name']} {bname}: {entries[k][0]:#x}..{a_end:#x} vs {b_start:#x}"
                )
            tabs[bname] = entries

        av_tab = tabs["av-cam.bin"]
        lm_tab = tabs["libmpr.so"]
        first = av_tab[0][0] & ~0xFFF
        last = max(o + len(old) for o, _, old, _ in av_tab)
        span = ((last - first) + 0xFFF) & ~0xFFF
        if pk["av_page_bounds"] is not None:
            lo_b, hi_b = pk["av_page_bounds"]
            assert lo_b <= first and first + span <= hi_b
        assert max(o + len(old) for o, _, old, _ in lm_tab) <= pk["lm_filesz"]

        longest = max(len(av_tab), len(lm_tab))
        mp_max = max(96, (longest + 31) & ~31)
        out = [
            f"/* Generated by gen_zv_studio.py for {pk['name']} (ZV-E1 2.02). Do not edit. */",
            f"/* av-cam.bin {pk['av_sha'][:16]}..., libmpr.so {pk['lm_sha'][:16]}... */",
            f"/* Cross-pack disjointness verified against V19/B19/I19: 0 guard-vs-site collisions. {'; '.join(filtered_notes)} */",
            f'#define MP_DESIGN "{pk["name"]}"',
            f"#define MP_AV_FIRST 0x{first:x}UL                 /* file offset of the first page read of av-cam.bin */",
            f"#define MP_AV_BYTES 0x{span:x}UL                  /* whole pages: every entry of mp_av lies inside */",
            f"#define MP_MAX {mp_max}                          /* room for {longest} entries (levels 19 and 20) */",
            "struct mp_site { u32 off; u8 len; u8 kind; u8 stock[16]; u8 changed[16]; };",
        ]
        for bname, var in (("av-cam.bin", "mp_av"), ("libmpr.so", "mp_lm")):
            out.append(f"static const struct mp_site {var}[] = {{      /* {bname}: file offsets */")
            out += [
                f"    {{ 0x{o:x}, {len(old)}, {kind}, {{ {h16(old)} }}, {{ {h16(new)} }} }},"
                for o, kind, old, new in tabs[bname]
            ]
            out.append("};")
        (HERE / pk["header"]).write_text("\n".join(out) + "\n", encoding="utf8", newline="\n")
        print(
            f"PASS {pk['header']}: av={len(pk['av_sites'])}s/{len(pk['av_guards'])}g, "
            f"lm={len(pk['lm_sites'])}s/{len(pk['lm_guards'])}g, MP_MAX={mp_max}"
        )


def build_h16(cp: bytes) -> None:
    hd = json.loads(resolve_design("hdmi32_zv_202").read_text(encoding="utf8"))
    cp_sha = hashlib.sha256(cp).hexdigest()
    assert hd["build"] == "zve1_202" and hd["persistent_writes"] is False
    assert hd["artifact_sha256"]["cpapp-b.bin"] == cp_sha
    cp_end = CPAPP_BASE + len(cp)

    word_map: dict[int, tuple[bytes, bytearray]] = {}
    for p in hd["patches"]:
        assert p["binary"] == "cpapp-b.bin"
        ra = int(p["ram_address"], 16)
        old = bytes.fromhex(p["old"])
        new = bytes.fromhex(p["new"])
        assert len(old) == len(new) and old != new
        assert CPAPP_BASE <= ra and ra + len(old) <= cp_end
        assert cp[ra - CPAPP_BASE : ra - CPAPP_BASE + len(old)] == old
        for i in range(len(old)):
            addr = ra + i
            w = addr & ~3
            if w not in word_map:
                st = cp[w - CPAPP_BASE : w - CPAPP_BASE + 4]
                word_map[w] = (st, bytearray(st))
            word_map[w][1][addr & 3] = new[i]

    words = [(w, word_map[w][0], bytes(word_map[w][1])) for w in sorted(word_map)]
    assert len(words) == 16
    for w, st, ch in words:
        assert w % 4 == 0 and st != ch
        assert cp[w - CPAPP_BASE : w - CPAPP_BASE + 4] == st

    guards = []
    for g in hd["guards"]:
        assert g["binary"] == "cpapp-b.bin"
        ga = int(g["ram_address"], 16)
        b = bytes.fromhex(g["bytes"])
        assert 0 < len(b) <= 16 and CPAPP_BASE <= ga and ga + len(b) <= cp_end
        assert cp[ga - CPAPP_BASE : ga - CPAPP_BASE + len(b)] == b
        guards.append((ga, b))
    guards.sort(key=lambda x: x[0])

    for ga, gb in guards:
        for w, _, _ in words:
            assert not (ga < w + 4 and w < ga + len(gb)), f"H16 guard {ga:#x} overlaps word {w:#x}"
    for k in range(len(guards) - 1):
        assert guards[k][0] + len(guards[k][1]) <= guards[k + 1][0], "H16 guards overlap"

    out = [
        "/* Generated by gen_zv_studio.py from hdmi32_zv_202.json (ZV-E1 2.02). Do not edit. */",
        f"/* cpapp-b.bin {cp_sha[:16]}...: {len(words)} aligned 4B words, {len(guards)} guards. */",
        '#define WORDS_DESIGN "hdmi32_zv_202"',
        "struct ram_word { u32 address; u8 stock[4]; u8 changed[4]; };",
        "static const struct ram_word ram_words[] = {",
    ]
    out += [f"    {{ 0x{w:x}, {{ {hx(st)} }}, {{ {hx(ch)} }} }}," for w, st, ch in words]
    out += [
        "};",
        "/* bytes beside the sites that must be as listed before anything is written */",
        "struct ram_guard { u32 address; u32 len; u8 bytes[16]; };",
        "static const struct ram_guard ram_guards[] = {",
    ]
    out += [f"    {{ 0x{ga:x}, {len(gb)}, {{ {h16(gb)} }} }}," for ga, gb in guards]
    out.append("};")
    (HERE / "expected_words_hdmi32_zv_202.h").write_text("\n".join(out) + "\n", encoding="utf8", newline="\n")
    print(f"PASS expected_words_hdmi32_zv_202.h: words={len(words)}, guards={len(guards)}, 0 overlaps")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate ZV-E1 2.02 studio patch headers")
    ap.add_argument("--fw-dir", type=Path, default=DEFAULT_FW_DIR)
    args = ap.parse_args()

    fw = args.fw_dir
    av = (fw / "av-cam.bin").read_bytes()
    lm = (fw / "libmpr.so").read_bytes()
    cp = (fw / "cpapp-b.bin").read_bytes()
    _, _, lm_filesz = first_pt_load(lm)

    v19 = build_v19(av, lm, lm_filesz)
    v19_keys = {("av-cam.bin", o) for o, _, _ in v19["av_sites"]} | {
        ("libmpr.so", o) for o, _, _ in v19["lm_sites"]
    }
    b19 = build_b19(av, lm, lm_filesz)
    i19 = build_i19(av, lm, lm_filesz, v19_keys)

    check_and_emit_mp_packs([v19, b19, i19])
    build_h16(cp)


if __name__ == "__main__":
    main()
