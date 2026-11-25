"""Build `avdec8k_fx3_v1`: in-camera playback of the FX3 kit's 3840 x 2560 clips, in the A7 IV's form.

  C:/Python313/python.exe -B build/build_avdec_fx3.py

Why (static trace of 2026-11-25, evidence/fx3/playback_trace_2026-11-25/): FX3 7.02's av-cam.bin opens every movie playback decoder
of the ordinary kind with row 0 of its decode size table, 4096 x 2160, and the 4K memory ids 0x47d / 0x47f. A 3840 x 2560 clip does not
fit that channel, so playback start fails ("Unable to display"). The A7 IV 6.02, which plays the same clips, opens that kind of decoder
with row 3, 7690 x 4320, and the 8K ids 0x47c / 0x47e; only clips whose type is 14 get its 4K row and ids, and the FX3's caller
never makes type 14 (its 0x26 / 0x27 branch is gone). So on the FX3 the A7 IV's choice is always the 8K one, and this design makes it:

  av-cam.bin code (kernel text, file offset = address - 0xffffffc001000000), the decode-memory allocation 0x218a84:
    0x218ab4  mov w2,  #0x47d  ->  mov w2,  #0x47c     the id asked for (first allocation)
    0x218ac0  mov w20, #0x47d  ->  mov w20, #0x47c     its copy for the failure log line
    0x218b30  mov w2,  #0x47f  ->  mov w2,  #0x47e     the id asked for (second allocation)
    0x218b3c  mov w21, #0x47f  ->  mov w21, #0x47e     its copy for the failure log line
  av-cam.bin data, the decode size table 0xbf8e70 (20-byte rows; read only by create-ch at 0x218e50):
    0xbf8e70  row 0 width, height 4096 x 2160 -> 7690 x 4320; the rest of the row is the A7 IV's row 3 already

The code words are a new kind of write for this kit (kernel text): the helper level that writes them (readcheck.c levels 29 / 30)
makes every processor fetch them afresh, and orders the writes so that no state between them is worse than stock: apply writes the
ids first and the row last, put back the row first and the ids last (a 4K row with 8K memory is harmless; an 8K row with 4K memory
is not). Everything here is checked against the 7.02 and 6.02 files; nothing is run on a camera.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

import parse_dmmcfg as P

ROOT = Path(__file__).resolve().parent.parent
BUILD, REF, SIB = "fx3_702", "a7iv_602", "a7s3_501"
NAME = "avdec8k_fx3_v1"
KVA = 0xFFFFFFC001000000                  # av-cam.bin's link and run address (liro.ko loads it at physical 0x401000000, memrsv ...:ex)
AVCAM_PHYS = 0x401000000
CODE_PAGE, DATA_PAGE = 0x218000, 0xBF8000
TABLE, ROW = 0xBF8E70, 20
ALLOC, CREATE, CALLER = 0x218A84, 0x218CC4, 0x22A18C
md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
md.detail = True


def avcam(build):
    return (ROOT / f"work/extracted/{build}/0700_part_image/dev/nflasha3/av-cam.bin").read_bytes()


def word(d, off):
    return struct.unpack_from("<I", d, off)[0]


def asm(d, off, n=1):
    """n instructions from file offset off, as 'mnemonic op_str' with branch targets as file offsets."""
    out = []
    for i in md.disasm(d[off:off + 4 * n], KVA + off):
        s = f"{i.mnemonic} {i.op_str}".strip()
        if i.mnemonic in ("bl", "b", "cbz", "cbnz", "tbz", "tbnz") or i.mnemonic.startswith("b."):
            t = i.operands[-1].imm & 0xFFFFFFFFFFFFFFFF                  # capstone gives the target signed
            s = s.replace("#0x%x" % t, "@%x" % (t - KVA))
        out.append(s)
    assert len(out) == n, "undecodable instruction near %#x" % off
    return out


def movz_w(rd, imm):
    assert 0 <= imm < 0x10000 and 0 <= rd < 31
    return 0x52800000 | imm << 5 | rd


def adrp_refs(d, page_va, lo, hi, code_end):
    """(instruction offset, target) for every ADRP of `page_va` followed within 12 instructions by an ADD/LDR/STR on that register
    whose target lies in [lo, hi)."""
    out = []
    n = code_end // 4
    w = struct.unpack_from("<%dI" % n, d, 0)
    for i in range(n):
        x = w[i]
        if x & 0x9F000000 != 0x90000000:
            continue
        imm = ((x >> 5) & 0x7FFFF) << 2 | (x >> 29) & 3
        imm = (imm - (1 << 21) if imm & (1 << 20) else imm) << 12
        if ((KVA + 4 * i) & ~0xFFF) + imm != page_va:
            continue
        rd = x & 31
        for j in range(i + 1, min(i + 13, n)):
            y = w[j]
            if (y >> 5) & 31 != rd:
                continue
            if y & 0xFF800000 == 0x91000000:                        # add xd, xn, #imm
                t = page_va + ((y >> 10) & 0xFFF << (12 if y >> 22 & 1 else 0))
            elif y & 0x3B000000 == 0x39000000:                      # ldr/str (unsigned offset), any size
                t = page_va + ((y >> 10) & 0xFFF) * (1 << (y >> 30))
            else:
                continue
            if lo <= t - KVA < hi:
                out.append((4 * j, t - KVA))
    return out


def main():
    fx, a4, s3 = avcam(BUILD), avcam(REF), avcam(SIB)
    og = json.loads((ROOT / "modding/designs/ogfile2560_hs_s_fx3_v2.json").read_text(encoding="utf8"))
    sha = hashlib.sha256(fx).hexdigest()
    assert sha == og["artifact_sha256"]["av-cam.bin"], "not the av-cam.bin of the FX3 kit's other designs"

    # 1. the allocation: two calls of the same allocator with fixed ids; the ids are used for nothing else (the handles go to +0x1070 / +0x1090)
    want = {0x218AA0: ["mov w8, #0x1070", "ldr x0, [x19, #0x10a0]", "add x4, x19, x8", "mov w1, #0x610000", "movk w1, #0x3c",
                       "mov w2, #0x47d", "mov w3, #-0x7f980000", "movk w3, #0xf3", "mov w20, #0x47d", "bl @22d394", "tbz w0, #0, @218ad4"],
            0x218B1C: ["mov w8, #0x1090", "ldr x0, [x19, #0x10a0]", "add x4, x19, x8", "mov w1, #0x610000", "movk w1, #0x3c",
                       "mov w2, #0x47f", "mov w3, #-0x7f980000", "movk w3, #0xf3", "mov w21, #0x47f", "bl @22d394", "tbnz w0, #0, @218b84"]}
    for at, seq in want.items():
        assert asm(fx, at, len(seq)) == seq, "the FX3's decode allocation at %#x is not as traced" % at
    assert asm(fx, ALLOC, 4) == ["sub sp, sp, #0x30", "stp x21, x20, [sp, #0x10]", "stp x19, x30, [sp, #0x20]", "mov x19, x0"]
    assert asm(fx, 0x218AF8, 1) == ["str w20, [sp, #8]"] and asm(fx, 0x218B6C, 1) == ["str w21, [sp, #8]"]   # the log copies' only use
    # the A7 IV's allocation: the same allocator call, the id 0x47c / 0x47e unless the clip type (+0x54) is 14
    assert asm(a4, 0x20E3F8, 13) == ["ldr w8, [x20, #0x54]", "mov w9, #0x1070", "add x4, x19, x9", "cmp w8, #0xe", "mov w8, #0x47c",
                                     "ldr x0, [x19, #0x10a0]", "cinc w21, w8, eq", "mov w1, #0x610000", "movk w1, #0x3c",
                                     "mov w3, #-0x7f980000", "movk w3, #0xf3", "mov w2, w21", "bl @222bd0"]
    assert asm(a4, 0x20E480, 11) == ["ldr w8, [x20, #0x54]", "mov w9, #0x1090", "add x4, x19, x9", "cmp w8, #0xe", "mov w8, #0x47e",
                                     "ldr x0, [x19, #0x10a0]", "cinc w20, w8, eq", "mov w1, #0x610000", "movk w1, #0x3c",
                                     "mov w3, #-0x7f980000", "movk w3, #0xf3"]
    # the allocator called is the same function in both (relocated: compare its first 24 instructions with branch targets left out)
    norm = lambda d, a: [s.split(" @")[0] for s in asm(d, a, 24)]
    assert norm(fx, 0x22D394) == norm(a4, 0x222BD0), "the allocators differ"

    # 2. the clip type: the FX3's caller makes 11, 12, 13 or 10, never 14 (the A7 IV's 14 is for its formats 0x26 / 0x27)
    fx_caller = asm(fx, 0x22A198, 14)
    assert fx_caller == ["ldr w8, [x21, #0xc]", "mov x19, x0", "cmp w8, #0xf", "b.ne @22a1b0", "mov w22, #0xb", "b @22a1d0",
                         "ldr w0, [x21, #0x10]", "bl @27cf68", "tbz w0, #0, @22a1cc", "tst w20, #0xff", "mov w8, #0xc",
                         "cinc w22, w8, ne", "b @22a1d0", "mov w22, #0xa"]
    assert asm(fx, 0x22A1FC, 1) == ["stp w22, w23, [sp, #0xf4]"]          # the type is +0x54 of the parameter copy at sp + 0xa0
    a4_caller = asm(a4, 0x21F9AC, 19)
    strip = lambda seq: [s.split(" @")[0].rstrip(",") for s in seq]       # branch targets differ between the builds
    assert strip(a4_caller[:6]) == strip(fx_caller[:6]) and strip(a4_caller[11:]) == strip(fx_caller[6:])
    assert a4_caller[6:11] == ["orr w8, w8, #1", "cmp w8, #0x27", "b.ne @21f9d8", "mov w22, #0xe", "b @21f9f8"]
    assert asm(a4, 0x21FA24, 1) == ["stp w22, w23, [sp, #0xf4]"]

    # 3. the row: the FX3 takes row 0 whenever the A7 IV takes row 0 or 3 (its row 3 unless the type is 14)
    assert asm(fx, 0x218DEC, 11) == ["tbz w0, #0, @218e10", "ldrh w8, [x20, #0x48]", "ldrh w9, [x20, #0x4a]", "mul w8, w9, w8",
                                     "cmp w8, #0x1fe, lsl #12", "mov w8, #1", "mov w22, #1", "cinc x23, x8, ls", "b @218e18",
                                     "mov w22, wzr", "mov x23, xzr"]
    assert asm(a4, 0x20E784, 5) == ["mov w22, wzr", "ldr w8, [x20, #0x54]", "mov w9, #3", "cmp w8, #0xe", "csel x23, xzr, x9, eq"]
    assert asm(fx, 0x218E50, 2) == ["adrp x9, #0xffffffc001bf8000", "add x9, x9, #0xe70"] and asm(fx, 0x218E64, 1) == ["mov w8, #0x14"]
    assert asm(fx, 0x218E78, 1) == ["madd x8, x23, x8, x9"]
    assert asm(a4, 0x20E7D0, 2) == ["adrp x9, #0xffffffc001bac000", "add x9, x9, #0xeb0"] and asm(a4, 0x20E7F8, 1) == ["madd x8, x23, x8, x9"]
    fx_rows = [fx[TABLE + ROW * k:TABLE + ROW * (k + 1)] for k in range(3)]
    a4_rows = [a4[0xBACEB0 + ROW * k:0xBACEB0 + ROW * (k + 1)] for k in range(4)]
    assert fx_rows == a4_rows[:3], "the FX3's three rows are not the A7 IV's rows 0 to 2"
    assert struct.unpack_from("<HH", fx_rows[0]) == (4096, 2160) and struct.unpack_from("<HH", a4_rows[3]) == (7690, 4320)
    assert a4_rows[3][4:] == fx_rows[0][4:], "the A7 IV's 8K row differs from the FX3's row 0 in more than the size"
    s3_at = s3.find(a4_rows[0] + a4_rows[1] + a4_rows[2] + a4_rows[3])
    assert s3_at > 0, "the A7S III's table is not the A7 IV's"
    refs = adrp_refs(fx, KVA + DATA_PAGE, TABLE, TABLE + 3 * ROW, 0xA00000)
    assert refs == [(0x218E54, TABLE)], "the table is read elsewhere too: %s" % refs

    # 4. memory: the ids exist in the FX3's main-processor DmmCfg with the A7 IV's sizes
    mem = {}
    for b in (BUILD, REF):
        cfg = P.Config(P.find_file(b, "setting"), b)
        assert cfg.exact()
        row = {}
        for i in (0x47C, 0x47D, 0x47E, 0x47F):
            (k,) = cfg.id_rows[i]["keys"]
            row[i] = [(u["group"]["parent"], u["size"]) for u in cfg.units_by_key[k]]
        mem[b] = row
    assert mem[BUILD] == mem[REF], "the decode memory differs from the A7 IV's"
    assert mem[BUILD][0x47C] == [(0x6C4, 536182784)] and mem[BUILD][0x47E] == [(0x6DD, 135036928)]

    # 5. no other code of the FX3 asks for these ids: every other `mov wN, #0x47c..0x47f` is a source line number of a log or assert call
    others = []
    for off in range(0, 0xA00000, 4):
        x = word(fx, off)
        if x & 0xFFE00000 == 0x52800000 and (x >> 5) & 0xFFFF in (0x47C, 0x47D, 0x47E, 0x47F) and not (ALLOC <= off < ALLOC + 0xC0):
            nxt = asm(fx, off + 4, 3)
            if x & 31 == 7:
                role = "line number of a log call (w7)"
            elif any(s in ("bl @20e824", "bl @27b228") for s in nxt[:2]):
                role = "line number of an assert call (w2; 0x20e824 / 0x27b228 take format or condition, file, line)"
            elif off in (0x4CC4C, 0x4CCB8, 0x4CD18):
                twin = {0x4CC4C: 0x4C7DC, 0x4CCB8: 0x4C848, 0x4CD18: 0x4C8A8}[off]
                assert strip(asm(a4, twin, 4)) == strip(asm(fx, off, 4)), "the A7 IV's twin of %#x differs" % off
                role = "w3 of a log call; the same at the A7 IV's %#x" % twin
            else:
                raise AssertionError("an id-like immediate at %#x that is not a line number: %s" % (off, asm(fx, off, 1)))
            others.append((off, asm(fx, off, 1)[0], role))

    # the sites
    code = [(0x218AB4, 2, 0x47D, 0x47C, "the id of the first decode-memory allocation (0x47d: 4K decode, 2 units of 152.3 MB in 0x6c4 -> 0x47c: 8K decode, the whole 536.2 MB of 0x6c4)"),
            (0x218AC0, 20, 0x47D, 0x47C, "its copy for the failure log line (str w20, [sp, #8] at 0x218af8)"),
            (0x218B30, 2, 0x47F, 0x47E, "the id of the second allocation (0x47f: 2 units of 38.6 MB -> 0x47e: 135.0 MB in 0x6dd)"),
            (0x218B3C, 21, 0x47F, 0x47E, "its copy for the failure log line (str w21, [sp, #8] at 0x218b6c)")]
    code_sites = []
    for off, rd, old, new, what in code:
        assert word(fx, off) == movz_w(rd, old) and off & ~0xFFF == CODE_PAGE
        code_sites.append({"file_off": hex(off), "kernel_address": hex(KVA + off), "old": struct.pack("<I", movz_w(rd, old)).hex(),
                           "new": struct.pack("<I", movz_w(rd, new)).hex(), "asm_old": "mov w%d, #%#x" % (rd, old),
                           "asm_new": "mov w%d, #%#x" % (rd, new), "what": what})
    for s in code_sites:
        assert next(md.disasm(bytes.fromhex(s["new"]), 0)).op_str.replace(" ", "") == s["asm_new"].split(" ", 1)[1].replace(" ", "")
    data_sites = [{"file_off": hex(TABLE), "kernel_address": hex(KVA + TABLE), "old": struct.pack("<HH", 4096, 2160).hex(),
                   "new": struct.pack("<HH", 7690, 4320).hex(), "what": "decode size table row 0: width, height (the A7 IV's row 3)"}]
    data_guards = [{"file_off": hex(TABLE + 4), "bytes": fx[TABLE + 4:TABLE + 16].hex(), "what": "row 0 after the size"},
                   {"file_off": hex(TABLE + 16), "bytes": fx[TABLE + 16:TABLE + 32].hex(), "what": "row 0 end, row 1"},
                   {"file_off": hex(TABLE + 32), "bytes": fx[TABLE + 32:TABLE + 48].hex(), "what": "row 1, row 2"},
                   {"file_off": hex(TABLE + 48), "bytes": fx[TABLE + 48:TABLE + 60].hex(), "what": "row 2"}]
    assert sum(len(g["bytes"]) // 2 for g in data_guards) == 3 * ROW - 4
    out = {"design": NAME, "build": BUILD, "camera": "ILME-FX3 (FX3), firmware 7.02", "kind": "avcam_code_data",
           "title": "In-camera playback of 3840 x 2560 clips: the A7 IV's 8K decode channel (7690 x 4320, memory ids 0x47c / 0x47e)",
           "status": "built from the 7.02 and 6.02 files; never read or written on an FX3. The A7 IV plays its own 3840 x 2560 clips with this "
                     "channel; whether the FX3 then plays them is the camera test",
           "artifact": "av-cam.bin", "artifact_sha256": sha, "kernel_va_base": hex(KVA), "avcam_phys": hex(AVCAM_PHYS),
           "generated_by": "build/build_avdec_fx3.py", "ported_from": "A7 IV 6.02 av-cam.bin: allocation 0x20e3d8 (ids 0x20e408 / 0x20e490), row choice 0x20e788, table 0xbaceb0 row 3",
           "code_page": hex(CODE_PAGE), "code_sites": code_sites,
           "code_guard": "the whole code page 0x218000-0x218fff apart from the four sites must be as in the file, in the mapping and in the kernel's own view "
                         "(it holds the allocation 0x218a84, the start of create-ch 0x218cc4 and its row choice 0x218e14)",
           "data_page": hex(DATA_PAGE), "data_sites": data_sites, "data_guards": data_guards,
           "order": {"apply": ["the four code words, each one aligned 32-bit store", "data cache clean and instruction cache invalidate at each, all processors; isb",
                               "the row's size, one aligned 32-bit store"],
                     "put_back": ["the row's size", "the four code words", "data cache clean and instruction cache invalidate at each; isb"],
                     "why": "a 4K row with the 8K memory is a smaller channel in larger memory (harmless); an 8K row with the 4K memory is not, so the row is "
                            "changed only while the 8K ids are in place"},
           "icache": {"processors": "4 x Cortex-A35 (update/0800_appli/setting/cxd90057.dtb); kernel 4.9.337 (SCTLR_EL1.UCI and UCT set: EL0 may clean and invalidate by address)",
                      "alias": "the code page is mapped at a user address with the kernel's offset from a 2 MB boundary (%#x), so a virtually indexed instruction "
                               "cache is invalidated at the same index as the kernel's fetches" % ((KVA + CODE_PAGE) & 0x1FFFFF),
                      "refuse": "an instruction cache that CTR_EL0 says is neither PIPT nor VIPT"},
           "checked": {"fx3_type_never_14": "the FX3 caller 0x22a198 makes types 11 / 12 / 13 / 10; the A7 IV's 0x21f9c4 adds 14 for formats 0x26 / 0x27",
                       "rows_equal_a7iv": "FX3 rows 0-2 = A7 IV rows 0-2; A7 IV row 3 = FX3 row 0 with 7690 x 4320; the A7S III 5.01 has the A7 IV's four rows at %#x" % s3_at,
                       "table_readers": ["0x218e54 (create-ch)"],
                       "allocator": "FX3 0x22d394 = A7 IV 0x222bd0 (24 instructions, branch targets aside); arguments w1 0x61003c, w3 0x806800f3 the same",
                       "dmm": {hex(k): [[hex(p), s] for p, s in v] for k, v in mem[BUILD].items()},
                       "other_id_immediates": [[hex(o), a, r] for o, a, r in others]},
           "restore": "readcheck.c level 30 (put back), or a cold boot: av-cam.bin is loaded again from flash",
           "not_shown": ["anything on an FX3", "that the FX3 then plays 3840 x 2560 clips (the A7 IV does)",
                         "that 0x47e's group can be had during playback on the FX3 (its 0x6dd has a third group, 0x6f {0x473, 0x476}, the A7 IV's has not)",
                         "the A7 IV's other limits (its 5.7K clips do not play in camera)"]}
    dst = ROOT / "modding" / "designs" / f"{NAME}.json"
    dst.write_text(json.dumps(out, indent=1) + "\n", encoding="utf8", newline="\n")
    print("av-cam.bin", sha[:16], "| code sites", [s["file_off"] for s in code_sites], "| row", data_sites[0]["file_off"])
    print("other id immediates (not changed):")
    for o, a, r in others:
        print("   %#x %s: %s" % (o, a, r))
    print("A7S III table at %#x; table readers %s" % (s3_at, refs))
    print("wrote", dst)


if __name__ == "__main__":
    sys.exit(main())
