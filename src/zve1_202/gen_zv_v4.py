#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate zv_expected.h and zv_expected.json for zvread_v4 (ZV-E1 2.02).

Extends zvread_v3 to observe baseline sites + all 8 mp4_3x2 libmpr.so sites
(12 lm_sites + 101 av_sites).
"""
import argparse
import hashlib
import json
import os
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

BASE = 0x108000
LABEL = "zvread_v4"
CP_LO, CP_HI = 0xC0000, 0x2700000
AVCAM_PHYS, AVCAM_RESERVE = 0x401000000, "@0x401000000"
ID_FILES = {
    "/libmpr.so": "libmpr.so",
    "/libsencore.so": "libsencore.so",
    "/libJiritsu.so": "libJiritsu.so",
}
ID_PAGES = (0x128000, 0x4AA000, 0x96D000, 0x788000)
DUMP_RANGES = (
    ("shadow", 0x11BD000, 2),
    ("matrix", 0x10CD000, 3),
    ("sizetable", 0x1996000, 1),
    ("records", 0x25D9000, 5),
    ("kprint", 0xE0000, 32),
    ("bootlog", 0xC0000, 8),
    ("context", 0x168B000, 4),
    ("resizework", 0x169D000, 1),
    ("resizestate", 0x19AC000, 4),
    ("wbuf", 0x10E1000, 2),
    ("display", 0x1F5000, 1),
    ("frametab", 0xE9B000, 1),
    ("paneltype", 0x1A71000, 1),
    ("dmmglobals", 0x19CF000, 1),
    ("dmmrecs", 0x2580000, 1),
)
UNIT, CLIP, DESC, DSIZE = 0x38F848, 0x38D7EC, 0x38F8E8, 0x88


def resolve_design(name: str, prefer_vdes: bool = False) -> Path:
    candidates = (
        [VDES / f"{name}.json", STUDIO_DES / f"{name}.json", DOCS_DES / f"{name}.json"]
        if prefer_vdes
        else [STUDIO_DES / f"{name}.json", DOCS_DES / f"{name}.json", VDES / f"{name}.json"]
    )
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError(f"Design JSON not found for {name}")


def c_bytes(b: bytes) -> str:
    return "{" + ",".join(str(x) for x in b) + "}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate zv_expected.h for zvread_v4")
    ap.add_argument("--fw-dir", type=Path, default=DEFAULT_FW_DIR)
    args = ap.parse_args()
    fw = args.fw_dir

    cp = (fw / "cpapp-b.bin").read_bytes()
    av = (fw / "av-cam.bin").read_bytes()
    lm = (fw / "libmpr.so").read_bytes()

    og = json.loads(resolve_design("ogsq_zv_v2", prefer_vdes=True).read_text(encoding="utf8"))
    oz = json.loads(resolve_design("outsz2560_zv_v1", prefer_vdes=True).read_text(encoding="utf8"))
    fl = json.loads(resolve_design("ogfile2560_hs_s_zv_v1", prefer_vdes=True).read_text(encoding="utf8"))
    mp4 = json.loads(resolve_design("mp4_3x2_zv_202").read_text(encoding="utf8"))
    lf = json.loads(resolve_design("lcdfill_zv_v2", prefer_vdes=True).read_text(encoding="utf8"))
    dm = json.loads(resolve_design("dmmwb_zv_v1", prefer_vdes=True).read_text(encoding="utf8"))

    assert og["artifact_sha256"] == hashlib.sha256(cp).hexdigest() == lf["artifact_sha256"]
    assert fl["artifact_sha256"] == {
        "libmpr.so": hashlib.sha256(lm).hexdigest(),
        "av-cam.bin": hashlib.sha256(av).hexdigest(),
    }
    assert mp4["artifact_sha256"] == {"libmpr.so": hashlib.sha256(lm).hexdigest()}

    out, blobs = [], []

    def blob(b: bytes) -> str:
        blobs.append(f"static const unsigned char B{len(blobs)}[] = {c_bytes(b)};")
        return f"B{len(blobs) - 1}"

    out.append(
        f'#define ZV_LABEL "{LABEL}"\n#define CP_LO {CP_LO:#x}U\n#define CP_HI {CP_HI:#x}U\n'
        f'#define AVCAM_PHYS {AVCAM_PHYS:#x}UL\n#define AVCAM_RESERVE "{AVCAM_RESERVE}"'
    )
    out.append(
        "struct id_file { const char *name; unsigned char sha256[32]; };\n"
        "struct id_page { unsigned int address; unsigned char sha256[32]; };\n"
        "struct cp_site { const char *name; unsigned int address, length; const unsigned char *stock, *target; int soft; };\n"
        "struct mp_site { unsigned long offset; unsigned int length; const unsigned char *stock, *target; };\n"
        "struct av_guard { const char *name; unsigned long offset; unsigned int length; unsigned char sha256[32]; };\n"
        "struct dump_range { const char *name; unsigned int address, pages; };"
    )
    rows = [
        f'    {{"{n}", {c_bytes(hashlib.sha256((fw / p).read_bytes()).digest())}}},'
        for n, p in ID_FILES.items()
    ]
    out.append("static const struct id_file id_files[] = {\n" + "\n".join(rows) + "\n};")

    sites = []
    for p in og["patches"]:
        a, old, new = int(p["addr"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        assert cp[a - BASE : a - BASE + len(old)] == old and len(old) == len(new)
        name = p["note"].split(" ")[0] if p["kind"] == "S" else ("record_left" if "left" in p["note"] else "record_right")
        sites.append((name, a, old, new, 0))
    sr = og["stored_record"]
    sites.append(("stored_record", int(sr["address"], 16), bytes.fromhex(sr["stock"]), bytes.fromhex(sr["design"]), 1))
    for s in oz["sites"]:
        sites.append(("outsize", int(s["ram_address"], 16), bytes.fromhex(s["old"]), bytes.fromhex(s["new"]), 1))
    for k, g in enumerate(oz["guards"]):
        sites.append((f"outsize_guard{k}", int(g["ram_address"], 16), bytes.fromhex(g["bytes"]), None, 1))
    for k, s in enumerate(lf["sites"]):
        a, old = int(s["ram_address"], 16), bytes.fromhex(s["old"])
        assert cp[a - BASE : a - BASE + 4] == old
        sites.append((f"screen{k}", a, old, bytes.fromhex(s["new"]), 0))
    for s in dm["sites"]:
        sites.append(("rawbuf_size", int(s["ram_address"], 16), bytes.fromhex(s["old"]), bytes.fromhex(s["new"]), 0))

    pages = {a & ~0xFFF for _, a, o, _, _ in sites for a in (a, a + len(o) - 1) if a < BASE + len(cp)}
    assert not any(p in pages for p in ID_PAGES), "an identity page holds a design site"
    rows = [f"    {{{a:#x}, {c_bytes(hashlib.sha256(cp[a - BASE:a - BASE + 4096]).digest())}}}," for a in ID_PAGES]
    out.append("static const struct id_page id_pages[] = {\n" + "\n".join(rows) + "\n};")

    rows = []
    for name, a, old, new, soft in sites:
        assert CP_LO <= a and a + len(old) <= CP_HI and len(old) <= 3072
        rows.append(
            f'    {{"{name}", {a:#x}, {len(old)}, {blob(old)}, {blob(new) if new is not None else "0"}, {soft}}},'
        )
    out.append("static const struct cp_site cp_sites[] = {\n" + "\n".join(rows) + "\n};")

    lm_entries = []
    avr, av_hi = [], 0
    for p in fl["patches"]:
        o, old, new = int(p["file_off"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        src = lm if p["binary"] == "libmpr.so" else av
        assert src[o : o + len(old)] == old
        if p["binary"] == "libmpr.so":
            lm_entries.append((o, old, new))
        else:
            avr.append(f"    {{{o:#x}UL, {len(old)}, {blob(old)}, {blob(new)}}},")
            av_hi = max(av_hi, o + len(old))
    for p in mp4["patches"]:
        assert p["binary"] == "libmpr.so"
        o, old, new = int(p["file_off"], 16), bytes.fromhex(p["old"]), bytes.fromhex(p["new"])
        assert lm[o : o + len(old)] == old
        lm_entries.append((o, old, new))
    lm_entries.sort(key=lambda x: x[0])
    assert len(lm_entries) == 12 and len(avr) == 101
    lmr = [f"    {{{o:#x}UL, {len(old)}, {blob(old)}, {blob(new)}}}," for o, old, new in lm_entries]
    out.append("static const struct mp_site lm_sites[] = {\n" + "\n".join(lmr) + "\n};")
    out.append("static const struct mp_site av_sites[] = {\n" + "\n".join(avr) + "\n};")

    guards = (
        ("unit_rows_0_2", UNIT, 0x30),
        ("clip_rows_2_7", CLIP + 0x20, 0x60),
        ("descriptors_0_3", DESC, 4 * DSIZE),
    )
    spans = [(int(p["file_off"], 16), len(p["old"]) // 2) for p in fl["patches"] if p["binary"] == "av-cam.bin"]
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
        "/* Generated by gen_zv_v4.py from ZV-E1 2.02 files and designs. Do not edit. */\n"
        "#ifndef DUMP\n#define DUMP 0\n#endif\n"
        + "\n".join(blobs)
        + "\n"
        + "\n".join(out)
        + "\n"
    )
    (HERE / "zv_expected.h").write_text(text, encoding="utf8", newline="\n")

    facts = {
        "label": LABEL,
        "cp_lo": CP_LO,
        "cp_hi": CP_HI,
        "avcam_phys": AVCAM_PHYS,
        "avcam_reserve": AVCAM_RESERVE,
        "id_files": {n: hashlib.sha256((fw / p).read_bytes()).hexdigest() for n, p in ID_FILES.items()},
        "id_pages": {hex(a): hashlib.sha256(cp[a - BASE : a - BASE + 4096]).hexdigest() for a in ID_PAGES},
        "cp_sites": [{"name": n, "address": hex(a), "length": len(o), "soft": s} for n, a, o, _, s in sites],
        "lm_sites": len(lmr),
        "av_sites": len(avr),
        "av_guards": [g[0] for g in guards],
        "dump_ranges": [[n, hex(a), k] for n, a, k in DUMP_RANGES],
        "designs": {
            d["design"]: hashlib.sha256(resolve_design(d["design"], prefer_vdes=(d is not mp4)).read_bytes()).hexdigest()
            for d in (og, oz, fl, mp4, lf, dm)
        },
    }
    (HERE / "zv_expected.json").write_text(json.dumps(facts, indent=1) + "\n", encoding="utf8", newline="\n")
    print(f"PASS zv_expected.h ({LABEL}): {len(sites)} cp_sites, {len(lmr)} lm_sites, {len(avr)} av_sites")


if __name__ == "__main__":
    main()
