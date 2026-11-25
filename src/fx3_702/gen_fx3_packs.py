#!/usr/bin/env python3
"""Generate C headers for FX3 7.02 (fx3_702) volatile RAM packs and fx3read_v2.

Generates:
  - expected_mp_ogfile2560_hs_s_fx3_v3.h  (V19/V20: v1 105 sites + mp4_3x2 8 libmpr sites = 113 sites)
  - expected_words_hdmi32_fx3_702.h       (H16/H17: 18 aligned 4-byte ram_word entries + 7 guards)
  - expected_mp_og_highbitrate_fx3_702.h  (B19/B20: 108 av-cam sites + 54 av guards + 1 libmpr ELF magic guard)
  - expected_mp_og_xavcsi_addon_fx3_702.h (I19/I20: 42 orthogonal XAVC S-I delta sites + non-overlapping guards)
  - fx3_expected.h, fx3_expected.json      (fx3read_v2: 55 cp_sites, 12 lm_sites, 101 av_sites)

Enforces cross-pack disjointness so no kind==0 guard in V19/B19/I19 overlaps any kind==1 site across V19/B19/I19.
"""
import hashlib
import json
import os
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDIO_ROOT = HERE.parents[1]
WORKSPACE_ROOT = STUDIO_ROOT.parent

FW_DIR = Path(os.environ.get("SONY_FW_DIR", str(WORKSPACE_ROOT / "firmwares/fx3/ghidra_targets")))
DESIGNS_DIR = Path(os.environ.get(
    "STUDIO_DESIGNS_DIR",
    str(STUDIO_ROOT / "designs" if (STUDIO_ROOT / "designs").is_dir() else WORKSPACE_ROOT / "docs/designs"),
))
UPSTREAM_DESIGNS_DIR = Path(os.environ.get(
    "UPSTREAM_FX3_DESIGNS_DIR",
    str(WORKSPACE_ROOT / "fx3-open-gate-test/windows/tools/modding/designs"),
))

BASE = 0x108000
LABEL = "fx3read_v2"
CP_LO, CP_HI = 0xC0000, 0x2100000
AVCAM_PHYS, AVCAM_RESERVE = 0x401000000, "@0x401000000"
ID_FILES = {
    "/libmpr.so": "libmpr.so",
    "/libsencore.so": "libsencore.so",
    "/libJiritsu.so": "libJiritsu.so",
}
ID_PAGES = (0x128000, 0x4A8000, 0x857000, 0xAEB000)
DUMP_RANGES = (
    ("shadow", 0xFF4000, 2),
    ("matrix", 0xF09000, 3),
    ("sizetable", 0x13C3000, 1),
    ("records", 0x1FDD000, 4),
    ("kprint", 0xE0000, 32),
    ("bootlog", 0xC0000, 8),
    ("context", 0x117B000, 5),
    ("resizework", 0x118E000, 1),
    ("resizestate", 0x13D5000, 5),
    ("wbuf", 0x1172000, 3),
    ("display", 0x1DF000, 1),
    ("crop", 0x5FA000, 1),
    ("frametab", 0xD2E000, 1),
    ("paneltype", 0x1490000, 1),
    ("desqueeze", 0x10A8000, 1),
)
UNIT, CLIP, DESC, COMB = 0x395068, 0x39335C, 0x395108, 0x2CB108


def hx(b: bytes) -> str:
    return ", ".join(f"0x{x:02x}" for x in b)


def c_bytes(b: bytes) -> str:
    return "{" + ",".join(str(x) for x in b) + "}"


def h16(b: bytes) -> str:
    return hx(b.ljust(16, b"\x00"))


def check_libmpr_pt_load0(lm: bytes, entries: list[tuple[int, int, bytes, bytes]]) -> None:
    phoff = struct.unpack_from("<Q", lm, 0x20)[0]
    phentsize, phnum = struct.unpack_from("<HH", lm, 0x36)
    load0 = next(
        struct.unpack_from("<IIQQQQQQ", lm, phoff + k * phentsize)
        for k in range(phnum)
        if struct.unpack_from("<I", lm, phoff + k * phentsize)[0] == 1
    )
    assert load0[2] == 0 and load0[3] == 0
    max_end = max(a + len(o) for a, _, o, _ in entries)
    assert max_end <= load0[5], f"libmpr.so entry 0x{max_end:x} exceeds PT_LOAD[0] filesz 0x{load0[5]:x}"


def load_mp_pack_v19(av: bytes, lm: bytes) -> dict:
    v1 = json.loads((UPSTREAM_DESIGNS_DIR / "ogfile2560_hs_s_fx3_v1.json").read_text(encoding="utf8"))
    mp4 = json.loads((DESIGNS_DIR / "mp4_3x2_fx3_702.json").read_text(encoding="utf8"))
    assert v1["artifact_sha256"] == {"libmpr.so": hashlib.sha256(lm).hexdigest(), "av-cam.bin": hashlib.sha256(av).hexdigest()}
    assert mp4["artifact_sha256"]["libmpr.so"] == hashlib.sha256(lm).hexdigest()
    assert not any(p["code"] for p in v1["patches"])

    sites: dict[str, list[tuple[int, bytes, bytes]]] = {"av-cam.bin": [], "libmpr.so": []}
    for p in v1["patches"]:
        off, old, new = int(p["file_off"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        src = av if p["binary"] == "av-cam.bin" else lm
        assert len(old) == len(new) <= 16 and old != new and src[off:off + len(old)] == old
        sites[p["binary"]].append((off, old, new))

    v1_lm_offs = {off for off, _, _ in sites["libmpr.so"]}
    for p in mp4["patches"]:
        assert p["binary"] == "libmpr.so"
        off, old, new = int(p["file_off"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        assert off not in v1_lm_offs
        assert len(old) == len(new) <= 16 and old != new and lm[off:off + len(old)] == old
        sites["libmpr.so"].append((off, old, new))

    assert len(sites["libmpr.so"]) == 12 and len(sites["av-cam.bin"]) == 101

    g_av: list[tuple[int, bytes]] = [
        (UNIT + 0x20, av[UNIT + 0x20:UNIT + 0x30]),
        (CLIP + 0x50, av[CLIP + 0x50:CLIP + 0x60]),
    ]
    assert struct.unpack("<4I", g_av[0][1]) == (0x486, 0x474, 0x477, 0x47A)
    assert struct.unpack("<4I", g_av[1][1]) == (1, 3840, 2160, 23)
    for x in v1["descriptors"]:
        o = DESC + x["descriptor"] * 0x90 + 0x28
        assert struct.unpack_from("<I", av, o)[0] == x["profile_key"]
        g_av.append((o, av[o:o + 4]))

    g_lm: list[tuple[int, bytes]] = []
    seen_lm_guards: set[int] = set()
    for g in mp4["guards"]:
        assert g["binary"] == "libmpr.so"
        off, bs = int(g["file_off"], 16), bytes.fromhex(g["bytes"])
        assert 0 < len(bs) <= 16 and lm[off:off + len(bs)] == bs
        if off not in seen_lm_guards:
            g_lm.append((off, bs))
            seen_lm_guards.add(off)
    for p in v1["patches"]:
        if p["binary"] == "libmpr.so":
            off = int(p["file_off"], 16)
            assert (off - 6 - COMB) % 0x18 == 0 and struct.unpack_from("<H", lm, off - 2)[0] == 3840
            g_off = off - 6
            if g_off not in seen_lm_guards:
                g_lm.append((g_off, lm[g_off:off]))
                seen_lm_guards.add(g_off)

    return {
        "name": "ogfile2560_hs_s_fx3_v3",
        "header": "expected_mp_ogfile2560_hs_s_fx3_v3.h",
        "sites": sites,
        "guards": {"av-cam.bin": g_av, "libmpr.so": g_lm},
        "comment": "Union of ogfile2560_hs_s_fx3_v1 (4 L1-comb + 101 av-cam) and mp4_3x2_fx3_702 (8 libmpr).",
    }


def load_mp_pack_b19(av: bytes, lm: bytes) -> dict:
    hb = json.loads((DESIGNS_DIR / "og_highbitrate_fx3_702.json").read_text(encoding="utf8"))
    assert hb["artifact_sha256"]["av-cam.bin"] == hashlib.sha256(av).hexdigest()
    sites: dict[str, list[tuple[int, bytes, bytes]]] = {"av-cam.bin": [], "libmpr.so": []}
    for p in hb["patches"]:
        assert p["binary"] == "av-cam.bin"
        off, old, new = int(p["file_off"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        assert len(old) == len(new) <= 16 and old != new and av[off:off + len(old)] == old
        sites["av-cam.bin"].append((off, old, new))
    assert len(sites["av-cam.bin"]) == 108

    g_av: list[tuple[int, bytes]] = []
    for g in hb["guards"]:
        assert g["binary"] == "av-cam.bin"
        off, bs = int(g["file_off"], 16), bytes.fromhex(g["bytes"])
        assert 0 < len(bs) <= 16 and av[off:off + len(bs)] == bs
        g_av.append((off, bs))

    g_lm = [(0, lm[:16])]
    return {
        "name": "og_highbitrate_fx3_702",
        "header": "expected_mp_og_highbitrate_fx3_702.h",
        "sites": sites,
        "guards": {"av-cam.bin": g_av, "libmpr.so": g_lm},
        "comment": "High-bitrate Long-GOP (200M/300M) av-cam overlay (108 sites).",
    }


def load_mp_pack_i19(av: bytes, lm: bytes, v19_site_keys: set[tuple[str, int]]) -> dict:
    si = json.loads((DESIGNS_DIR / "og_xavcsi_fx3_702.json").read_text(encoding="utf8"))
    assert si["artifact_sha256"] == {"libmpr.so": hashlib.sha256(lm).hexdigest(), "av-cam.bin": hashlib.sha256(av).hexdigest()}
    sites: dict[str, list[tuple[int, bytes, bytes]]] = {"av-cam.bin": [], "libmpr.so": []}
    for p in si["patches"]:
        b = p["binary"]
        off = int(p["file_off"], 16)
        if (b, off) in v19_site_keys:
            continue
        old, new = bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        src = av if b == "av-cam.bin" else lm
        assert len(old) == len(new) <= 16 and old != new and src[off:off + len(old)] == old
        sites[b].append((off, old, new))
    assert len(sites["libmpr.so"]) + len(sites["av-cam.bin"]) == 42

    g_av: list[tuple[int, bytes]] = []
    g_lm: list[tuple[int, bytes]] = []
    seen_av: set[int] = set()
    seen_lm: set[int] = set()
    for g in si["guards"]:
        b = g["binary"]
        off, bs = int(g["file_off"], 16), bytes.fromhex(g["bytes"])
        src = av if b == "av-cam.bin" else lm
        assert 0 < len(bs) <= 16 and src[off:off + len(bs)] == bs
        if b == "av-cam.bin":
            if off not in seen_av:
                g_av.append((off, bs))
                seen_av.add(off)
        else:
            if off not in seen_lm:
                g_lm.append((off, bs))
                seen_lm.add(off)
    if 0 not in seen_lm:
        g_lm.append((0, lm[:16]))

    return {
        "name": "og_xavcsi_addon_fx3_702",
        "header": "expected_mp_og_xavcsi_addon_fx3_702.h",
        "sites": sites,
        "guards": {"av-cam.bin": g_av, "libmpr.so": g_lm},
        "comment": "Orthogonal XAVC S-I 4K All-Intra delta excluding V19 sites (42 sites).",
    }


def trim_cross_pack_guards(packs: list[dict]) -> list[str]:
    """Ensure no kind==0 guard in any pack overlaps any kind==1 site across all MP packs."""
    all_sites: list[tuple[str, str, int, int]] = []
    for pk in packs:
        for b in ("av-cam.bin", "libmpr.so"):
            for off, old, _ in pk["sites"][b]:
                all_sites.append((pk["name"], b, off, off + len(old)))

    notes: list[str] = []
    for pk in packs:
        for b in ("av-cam.bin", "libmpr.so"):
            kept: list[tuple[int, bytes]] = []
            for goff, gbytes in pk["guards"][b]:
                gend = goff + len(gbytes)
                hits = [
                    (sn, so, se)
                    for sn, sb, so, se in all_sites
                    if sb == b and goff < se and so < gend
                ]
                if not hits:
                    kept.append((goff, gbytes))
                    continue
                intervals = [(goff, gend)]
                for _, so, se in hits:
                    next_iv = []
                    for a, z in intervals:
                        if se <= a or z <= so:
                            next_iv.append((a, z))
                        else:
                            if a < so:
                                next_iv.append((a, so))
                            if se < z:
                                next_iv.append((se, z))
                    intervals = next_iv
                kept_pieces = [(a, gbytes[a - goff:z - goff]) for a, z in intervals if z - a >= 4]
                kept.extend(kept_pieces)
                notes.append(
                    f"Filtered/trimmed {pk['name']} {b} guard 0x{goff:x}+{len(gbytes)} overlapping {hits}; kept {len(kept_pieces)} slice(s)"
                )
            pk["guards"][b] = kept

    for pk in packs:
        for b in ("av-cam.bin", "libmpr.so"):
            for goff, gbytes in pk["guards"][b]:
                gend = goff + len(gbytes)
                for sn, sb, so, se in all_sites:
                    assert not (sb == b and goff < se and so < gend), (
                        f"Cross-pack guard collision: {pk['name']} {b} 0x{goff:x}..0x{gend:x} vs {sn} 0x{so:x}..0x{se:x}"
                    )
    return notes


def write_utf8_lf(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf8", newline="\n") as f:
        f.write(text)


def emit_mp_pack(pk: dict, av: bytes, lm: bytes, cross_notes: list[str]) -> tuple[str, dict]:
    tabs: dict[str, list[tuple[int, int, bytes, bytes]]] = {}
    for b in ("av-cam.bin", "libmpr.so"):
        entries = [(off, 1, old, new) for off, old, new in pk["sites"][b]] + [
            (goff, 0, gbytes, b"") for goff, gbytes in pk["guards"][b]
        ]
        entries.sort(key=lambda e: (e[0], e[1]))
        for k in range(len(entries) - 1):
            a0, _, o0, _ = entries[k]
            a1, _, _, _ = entries[k + 1]
            assert a0 + len(o0) <= a1, f"{pk['name']} {b} overlap at 0x{a0:x}..0x{a0+len(o0):x} vs 0x{a1:x}"
        tabs[b] = entries

    first = tabs["av-cam.bin"][0][0] & ~0xFFF
    last = max(a + len(o) for a, _, o, _ in tabs["av-cam.bin"])
    span = ((last - first) + 0xFFF) & ~0xFFF
    assert 0x392000 <= first and first + span <= 0x3DB000, f"{pk['name']} av-cam.bin span out of bounds"
    check_libmpr_pt_load0(lm, tabs["libmpr.so"])

    longest = max(len(tabs["av-cam.bin"]), len(tabs["libmpr.so"]))
    mp_max = max(160, (longest + 31) & ~31) if pk["name"].startswith("og_highbitrate") else ((longest + 31) & ~31)
    av_sha = hashlib.sha256(av).hexdigest()
    lm_sha = hashlib.sha256(lm).hexdigest()

    out = [
        "/* Generated by src/fx3_702/gen_fx3_packs.py (FX3 7.02). Do not edit. */",
        f"/* {pk['comment']} */",
        f"/* av-cam.bin {av_sha[:16]}..., libmpr.so {lm_sha[:16]}... */",
    ]
    for note in cross_notes:
        out.append(f"/* Cross-pack check: {note} */")
    out += [
        f'#define MP_DESIGN "{pk["name"]}"',
        f"#define MP_AV_FIRST 0x{first:x}UL",
        f"#define MP_AV_BYTES 0x{span:x}UL",
    ]
    if mp_max > 96:
        out.append(f"#define MP_MAX {mp_max}")
    out.append("struct mp_site { u32 off; u8 len; u8 kind; u8 stock[16]; u8 changed[16]; };")
    for b, var in (("av-cam.bin", "mp_av"), ("libmpr.so", "mp_lm")):
        out.append(f"static const struct mp_site {var}[] = {{")
        for a, kind, o, n in tabs[b]:
            out.append(f"    {{ 0x{a:x}, {len(o)}, {kind}, {{ {h16(o)} }}, {{ {h16(n)} }} }},")
        out.append("};")
    write_utf8_lf(HERE / pk["header"], "\n".join(out) + "\n")
    stats = {b: {"sites": sum(1 for e in t if e[1] == 1), "guards": sum(1 for e in t if e[1] == 0)} for b, t in tabs.items()}
    return pk["header"], stats


def emit_hdmi32_words(cp: bytes) -> tuple[str, int, int]:
    d = json.loads((DESIGNS_DIR / "hdmi32_fx3_702.json").read_text(encoding="utf8"))
    assert d["artifact_sha256"]["cpapp-b.bin"] == hashlib.sha256(cp).hexdigest()

    patched = bytearray(cp)
    touched: set[int] = set()
    for p in d["patches"]:
        ram = int(p["ram_address"], 16)
        old, new = bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        assert len(old) == len(new) == p["length"] and old != new
        assert cp[ram - BASE:ram - BASE + len(old)] == old
        for idx in range(len(old)):
            assert (ram + idx) not in touched, f"Overlapping hdmi32 patch byte at 0x{ram + idx:x}"
            touched.add(ram + idx)
            patched[ram - BASE + idx] = new[idx]

    word_addrs = sorted({a & ~3 for a in touched})
    assert len(word_addrs) == 18, f"Expected 18 aligned words on fx3_702, got {len(word_addrs)}"
    words: list[tuple[int, bytes, bytes]] = []
    for w in word_addrs:
        st = cp[w - BASE:w - BASE + 4]
        ch = bytes(patched[w - BASE:w - BASE + 4])
        assert st != ch
        words.append((w, st, ch))

    guards: list[tuple[int, bytes]] = []
    for g in d["guards"]:
        ga = int(g["ram_address"], 16)
        gb = bytes.fromhex(g["bytes"])
        assert 0 < len(gb) <= 16 and cp[ga - BASE:ga - BASE + len(gb)] == gb
        assert not any(ga < w + 4 and w < ga + len(gb) for w, _, _ in words), f"Guard 0x{ga:x} overlaps aligned word"
        guards.append((ga, gb))

    for other_name in ("lcd32dsq_fx3_v1.json", "outsz2560_fx3_v1.json"):
        od = json.loads((UPSTREAM_DESIGNS_DIR / other_name).read_text(encoding="utf8"))
        for s in od["sites"]:
            oa = int(s["ram_address"], 16)
            assert not any(w < oa + 4 and oa < w + 4 for w, _, _ in words), f"Overlap with {other_name} site 0x{oa:x}"
            assert not any(ga < oa + 4 and oa < ga + len(gb) for ga, gb in guards), f"Guard overlap with {other_name} site 0x{oa:x}"

    out = [
        "/* Generated by src/fx3_702/gen_fx3_packs.py from designs/hdmi32_fx3_702.json (FX3 7.02). Do not edit. */",
        f"/* {len(words)} aligned 4-byte words, {len(guards)} guards. */",
        '#define WORDS_DESIGN "hdmi32_fx3_702"',
        "struct ram_word { u32 address; u8 stock[4]; u8 changed[4]; };",
        "static const struct ram_word ram_words[] = {",
    ]
    out += [f"    {{ 0x{w:x}, {{ {hx(st)} }}, {{ {hx(ch)} }} }}," for w, st, ch in words]
    out += [
        "};",
        "struct ram_guard { u32 address; u32 len; u8 bytes[16]; };",
        "static const struct ram_guard ram_guards[] = {",
    ]
    out += [f"    {{ 0x{ga:x}, {len(gb)}, {{ {h16(gb)} }} }}," for ga, gb in guards]
    out += ["};"]
    write_utf8_lf(HERE / "expected_words_hdmi32_fx3_702.h", "\n".join(out) + "\n")
    return "expected_words_hdmi32_fx3_702.h", len(words), len(guards)


def emit_fx3_expected(cp: bytes, av: bytes, lm: bytes, v19_pack: dict) -> None:
    og = json.loads((UPSTREAM_DESIGNS_DIR / "ogsq_fx3_v1.json").read_text(encoding="utf8"))
    oz = json.loads((UPSTREAM_DESIGNS_DIR / "outsz2560_fx3_v1.json").read_text(encoding="utf8"))
    fl = json.loads((UPSTREAM_DESIGNS_DIR / "ogfile2560_hs_s_fx3_v1.json").read_text(encoding="utf8"))
    sc = json.loads((UPSTREAM_DESIGNS_DIR / "lcd32dsq_fx3_v1.json").read_text(encoding="utf8"))
    mp4 = json.loads((DESIGNS_DIR / "mp4_3x2_fx3_702.json").read_text(encoding="utf8"))

    assert og["artifact_sha256"] == sc["artifact_sha256"] == oz["emulated_image_sha256"] == hashlib.sha256(cp).hexdigest()
    assert fl["artifact_sha256"] == {"libmpr.so": hashlib.sha256(lm).hexdigest(), "av-cam.bin": hashlib.sha256(av).hexdigest()}
    assert mp4["artifact_sha256"]["libmpr.so"] == hashlib.sha256(lm).hexdigest()

    out, blobs = [], []

    def blob(b: bytes) -> str:
        blobs.append(f"static const unsigned char B{len(blobs)}[] = {c_bytes(b)};")
        return f"B{len(blobs) - 1}"

    mp4_hdr_offs = sorted(int(p["file_off"], 16) for p in mp4["patches"] if p["binary"] == "libmpr.so")
    assert len(mp4_hdr_offs) == 8
    hdr_expr = " || ".join(f"(off) == {o:#x}UL" for o in mp4_hdr_offs)

    out.append(
        f'#define FX3_LABEL "{LABEL}"\n'
        f"#define CP_LO {CP_LO:#x}U\n"
        f"#define CP_HI {CP_HI:#x}U\n"
        f"#define AVCAM_PHYS {AVCAM_PHYS:#x}UL\n"
        f'#define AVCAM_RESERVE "{AVCAM_RESERVE}"\n'
        f"#define IS_MP4_HDR(off) ({hdr_expr})"
    )
    out.append(
        "struct id_file { const char *name; unsigned char sha256[32]; };\n"
        "struct id_page { unsigned int address; unsigned char sha256[32]; };\n"
        "struct cp_site { const char *name; unsigned int address, length; const unsigned char *stock, *target; int soft; };\n"
        "struct mp_site { unsigned long offset; unsigned int length; const unsigned char *stock, *target; };\n"
        "struct av_guard { const char *name; unsigned long offset; unsigned int length; unsigned char sha256[32]; };\n"
        "struct dump_range { const char *name; unsigned int address, pages; };"
    )
    rows = [f'    {{"{n}", {c_bytes(hashlib.sha256((FW_DIR / p).read_bytes()).digest())}}},' for n, p in ID_FILES.items()]
    out.append("static const struct id_file id_files[] = {\n" + "\n".join(rows) + "\n};")
    rows = [f"    {{{a:#x}, {c_bytes(hashlib.sha256(cp[a - BASE:a - BASE + 4096]).digest())}}}," for a in ID_PAGES]
    out.append("static const struct id_page id_pages[] = {\n" + "\n".join(rows) + "\n};")

    sites = []
    for p in og["patches"]:
        a, old, new = int(p["addr"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        assert cp[a - BASE:a - BASE + len(old)] == old and len(old) == len(new)
        name = p["note"].split(" ")[0] if p["kind"] == "S" else ("record_left" if "left" in p["note"] else "record_right")
        sites.append((name, a, old, new, 0))
    sr = og["stored_record"]
    sites.append(("stored_record", int(sr["address"], 16), bytes.fromhex(sr["stock"]), bytes.fromhex(sr["design"]), 1))
    for s in oz["sites"]:
        sites.append(("outsize", int(s["ram_address"], 16), bytes.fromhex(s["old"]), bytes.fromhex(s["new"]), 1))
    for k, g in enumerate(oz["guards"]):
        sites.append((f"outsize_guard{k}", int(g["ram_address"], 16), bytes.fromhex(g["bytes"]), None, 1))
    for k, s in enumerate(sc["sites"]):
        a = int(s["ram_address"], 16)
        assert cp[a - BASE:a - BASE + 4] == bytes.fromhex(s["old"])
        sites.append((f"screen{k}", a, bytes.fromhex(s["old"]), bytes.fromhex(s["new"]), 1))

    rows = []
    for name, a, old, new, soft in sites:
        assert CP_LO <= a and a + len(old) <= CP_HI and len(old) <= 3072
        rows.append(f'    {{"{name}", {a:#x}, {len(old)}, {blob(old)}, {blob(new) if new is not None else "0"}, {soft}}},')
    out.append("static const struct cp_site cp_sites[] = {\n" + "\n".join(rows) + "\n};")

    lmr, avr, av_hi = [], [], 0
    for off, old, new in sorted(v19_pack["sites"]["libmpr.so"], key=lambda x: x[0]):
        assert lm[off:off + len(old)] == old
        lmr.append(f"    {{{off:#x}UL, {len(old)}, {blob(old)}, {blob(new)}}},")
    for off, old, new in v19_pack["sites"]["av-cam.bin"]:
        assert av[off:off + len(old)] == old
        avr.append(f"    {{{off:#x}UL, {len(old)}, {blob(old)}, {blob(new)}}},")
        av_hi = max(av_hi, off + len(old))
    assert len(lmr) == 12 and len(avr) == 101

    out.append("static const struct mp_site lm_sites[] = {\n" + "\n".join(lmr) + "\n};")
    out.append("static const struct mp_site av_sites[] = {\n" + "\n".join(avr) + "\n};")

    guards = (
        ("unit_rows_0_2", UNIT, 0x30),
        ("clip_rows_2_7", CLIP + 0x20, 0x60),
        ("descriptors_0_3", DESC, 4 * 0x90),
    )
    spans = [(off, len(old)) for off, old, _ in v19_pack["sites"]["av-cam.bin"]]
    rows = []
    for name, o, n in guards:
        assert all(o + n <= so or so + sn <= o for so, sn in spans), name
        rows.append(f'    {{"{name}", {o:#x}UL, {n}, {c_bytes(hashlib.sha256(av[o:o + n]).digest())}}},')
        av_hi = max(av_hi, o + n)
    out.append("static const struct av_guard av_guards[] = {\n" + "\n".join(rows) + "\n};")
    av_lo = min([so for so, _ in spans] + [o for _, o, _ in guards]) & ~0xFFF
    out.append(f"#define AV_LO {av_lo:#x}UL\n#define AV_HI {av_hi:#x}UL")

    rows = [f'    {{"{n}", {a:#x}, {k}}},' for n, a, k in DUMP_RANGES]
    assert all(CP_LO <= a and a + 4096 * k <= CP_HI for _, a, k in DUMP_RANGES)
    out.append("#if DUMP\nstatic const struct dump_range dump_ranges[] = {\n" + "\n".join(rows) + "\n};\n#endif")

    text = (
        "/* Generated by src/fx3_702/gen_fx3_packs.py from FX3 7.02 files and designs. Do not edit. */\n"
        "#ifndef DUMP\n#define DUMP 0\n#endif\n"
        + "\n".join(blobs) + "\n" + "\n".join(out) + "\n"
    )
    write_utf8_lf(HERE / "fx3_expected.h", text)

    facts = {
        "label": LABEL,
        "cp_lo": CP_LO,
        "cp_hi": CP_HI,
        "avcam_phys": AVCAM_PHYS,
        "avcam_reserve": AVCAM_RESERVE,
        "id_files": {n: hashlib.sha256((FW_DIR / p).read_bytes()).hexdigest() for n, p in ID_FILES.items()},
        "id_pages": {hex(a): hashlib.sha256(cp[a - BASE:a - BASE + 4096]).hexdigest() for a in ID_PAGES},
        "cp_sites": [{"name": n, "address": hex(a), "length": len(o), "soft": s} for n, a, o, _, s in sites],
        "lm_sites": len(lmr),
        "av_sites": len(avr),
        "mp4_hdr_offsets": [hex(o) for o in mp4_hdr_offs],
        "av_guards": [g[0] for g in guards],
        "dump_ranges": [[n, hex(a), k] for n, a, k in DUMP_RANGES],
        "designs": {
            "ogsq_fx3_v1": hashlib.sha256((UPSTREAM_DESIGNS_DIR / "ogsq_fx3_v1.json").read_bytes()).hexdigest(),
            "outsz2560_fx3_v1": hashlib.sha256((UPSTREAM_DESIGNS_DIR / "outsz2560_fx3_v1.json").read_bytes()).hexdigest(),
            "ogfile2560_hs_s_fx3_v1": hashlib.sha256((UPSTREAM_DESIGNS_DIR / "ogfile2560_hs_s_fx3_v1.json").read_bytes()).hexdigest(),
            "lcd32dsq_fx3_v1": hashlib.sha256((UPSTREAM_DESIGNS_DIR / "lcd32dsq_fx3_v1.json").read_bytes()).hexdigest(),
            "mp4_3x2_fx3_702": hashlib.sha256((DESIGNS_DIR / "mp4_3x2_fx3_702.json").read_bytes()).hexdigest(),
        },
    }
    write_utf8_lf(HERE / "fx3_expected.json", json.dumps(facts, indent=1) + "\n")


def main() -> None:
    cp = (FW_DIR / "cpapp-b.bin").read_bytes()
    av = (FW_DIR / "av-cam.bin").read_bytes()
    lm = (FW_DIR / "libmpr.so").read_bytes()

    v19 = load_mp_pack_v19(av, lm)
    v19_keys = {(b, off) for b in ("av-cam.bin", "libmpr.so") for off, _, _ in v19["sites"][b]}
    b19 = load_mp_pack_b19(av, lm)
    i19 = load_mp_pack_i19(av, lm, v19_keys)

    notes = trim_cross_pack_guards([v19, b19, i19])
    for pk in (v19, b19, i19):
        hdr, stats = emit_mp_pack(pk, av, lm, notes)
        print(f"wrote {hdr}: {stats}")

    h_hdr, n_words, n_guards = emit_hdmi32_words(cp)
    print(f"wrote {h_hdr}: {n_words} words, {n_guards} guards")

    emit_fx3_expected(cp, av, lm, v19)
    print("wrote fx3_expected.h and fx3_expected.json (fx3read_v2: 55 cp_sites, 12 lm_sites, 101 av_sites)")


if __name__ == "__main__":
    main()
