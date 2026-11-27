"""Clean-room pure-Python and Unicorn verification for Tracks 3A, 3B, and 3C.

Runs pure-Python mathematical/state-machine checks and documentation invariant
checks under every Python interpreter, and executes full ARM32 Thumb-2 + VFP
and AArch64 trampoline emulation when ``unicorn`` is available.
"""

from __future__ import annotations

import pathlib
import struct
import unittest

try:
    from unicorn import UC_ARCH_ARM, UC_ARCH_ARM64, UC_MODE_ARM, UC_MODE_THUMB, Uc
    from unicorn.arm64_const import (
        UC_ARM64_REG_LR,
        UC_ARM64_REG_SP,
        UC_ARM64_REG_W0,
        UC_ARM64_REG_X0,
        UC_ARM64_REG_X1,
        UC_ARM64_REG_X20,
        UC_ARM64_REG_X29,
    )
    from unicorn.arm_const import (
        UC_ARM_REG_C1_C0_2,
        UC_ARM_REG_FPEXC,
        UC_ARM_REG_LR,
        UC_ARM_REG_R0,
        UC_ARM_REG_R1,
        UC_ARM_REG_R2,
        UC_ARM_REG_R3,
        UC_ARM_REG_R4,
        UC_ARM_REG_SB,
        UC_ARM_REG_SL,
        UC_ARM_REG_SP,
    )

    HAS_UNICORN = True
except ImportError:
    HAS_UNICORN = False

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
RESEARCH_DOC = REPO_ROOT / "docs" / "FAILSAFE_AND_OVERLAY_RESEARCH.md"

OPEN_GATE_LOW13_MODES = frozenset({0x08C0, 0x0820})

VERIFIED_TARGETS = {
    "zve1_202": {
        "drv_global": 0x11D70D0,
        "r4_outer": 0x17F21F4,
        "r4_inner": 0x17F26E0,
        "r4_offset": 0x4EC,
        "size_class_3": 0x199655C,
        "l2_mp4": 0x207D14,
        "nrt_meta_init": 0x237F5C,
        "tail_cave_64": 0x2C7EE4,
    },
    "a7s3_501": {
        "drv_global": 0x1032940,
        "r4_outer": 0x12A4678,
        "r4_inner": 0x12A4B60,
        "r4_offset": 0x4E8,
        "size_class_3": 0x13EC2E4,
        "l2_mp4": 0x223C4C,
        "nrt_meta_init": 0x253F64,
        "tail_cave_64": 0x2EAFA4,
    },
    "fx3_702": {
        "drv_global": 0x100D740,
        "r4_outer": 0x127AFF0,
        "r4_inner": 0x127B4D8,
        "r4_offset": 0x4E8,
        "size_class_3": 0x13C31C8,
        "l2_mp4": 0x21FEC4,
        "nrt_meta_init": 0x2500D0,
        "tail_cave_64": 0x2E192C,
    },
}


# ---------------------------------------------------------------------------
# Pure-Python Reference Models
# ---------------------------------------------------------------------------


def model_tracking_osd_y_remap(
    y_in: int,
    h_in: int,
    raw_h: int,
    disp_y: int,
    disp_h: int,
    mode: str,
    patched: bool,
) -> tuple[int, int]:
    """Reference arithmetic for Track 3A vertical tracking-box projection."""
    # Stage 1 stretches 360-grid boxes onto the 480-grid sensor box when raw_h == 360.
    if raw_h == 360:
        y_stage1 = (y_in * 480) / 360.0
        h_stage1 = (h_in * 480) / 360.0
    else:
        y_stage1 = float(y_in)
        h_stage1 = float(h_in)

    # Stage 2 maps the 480-grid box into disp_h, matching ARM VFP vcvt.s32.f32 truncation.
    y_s = int(disp_y + (y_stage1 * disp_h) / 480.0)
    h_s = int((h_stage1 * disp_h) / 480.0)
    if not patched:
        return y_s, h_s

    if mode == "zve1_par98" and raw_h == 360 and disp_h == 480:
        # 720x480 panel (PAR 9/8): restore physical 1:1 height (h_in * 9 + 4) >> 3.
        h_new = (h_in * 9 + 4) >> 3
        y_new = y_s + ((h_s - h_new) >> 1)
        return y_new, h_new

    if mode == "a7s3_par11" and disp_h == 428:
        # 800x600 panel (PAR 1:1): restore original OSD box height directly.
        h_new = h_in
        y_new = y_s + ((h_s - h_new) >> 1)
        return y_new, h_new

    return y_s, h_s


def model_slvsec_fullinit_guard(
    p1_1: int, p2_1: int, new_drv: int, patched: bool
) -> bool:
    """Reference predicate for Track 3B Stills-to-Movie fullinit guard."""
    if patched and (new_drv & 0x1FFF) in OPEN_GATE_LOW13_MODES:
        return True
    return not (p1_1 == 7 and p2_1 == 7)


def model_option_c_decision(
    fps_code: int, drv_mode: int
) -> dict[str, int | str]:
    """Coupled AArch32 + AArch64 Option C resolution and aspect rule."""
    is_og_rate = (drv_mode & 0x1FFF) in OPEN_GATE_LOW13_MODES and fps_code <= 3
    if is_og_rate:
        # 23.98p / 24p / 25p / 29.97p -> native 3840x2560 (3:2)
        rect_w = 640
        rect_h = (((rect_w + 3) << 8) // 3 * 2 >> 8) & 0xFFFE
        return {
            "cp_w": 3840,
            "cp_h": 2560,
            "mp4_w": 3840,
            "mp4_h": 2560,
            "nrt_vline": 2560,
            "b_aspectValid": 0,
            "disp_rect": (0, (480 - rect_h) // 2, rect_w, rect_h),
            "aspect": "3:2",
        }
    return {
        "cp_w": 3840,
        "cp_h": 2160,
        "mp4_w": 3840,
        "mp4_h": 2160,
        "nrt_vline": 2160,
        "b_aspectValid": 1,
        "disp_rect": (0, 60, 640, 360),
        "aspect": "16:9",
    }


# ---------------------------------------------------------------------------
# Clean-Room Assemblers for Trampoline Emulation
# ---------------------------------------------------------------------------


def _movw(rd: int, imm16: int) -> bytes:
    return struct.pack(
        "<HH",
        0xF240 | (((imm16 >> 11) & 1) << 10) | ((imm16 >> 12) & 0xF),
        (((imm16 >> 8) & 0x7) << 12) | (rd << 8) | (imm16 & 0xFF),
    )


def _movt(rd: int, imm16: int) -> bytes:
    return struct.pack(
        "<HH",
        0xF2C0 | (((imm16 >> 11) & 1) << 10) | ((imm16 >> 12) & 0xF),
        (((imm16 >> 8) & 0x7) << 12) | (rd << 8) | (imm16 & 0xFF),
    )


def _b_w(src: int, dst: int) -> bytes:
    off = dst - (src + 4)
    s_bit = (off >> 24) & 1
    i1 = (~((off >> 23) ^ s_bit)) & 1
    i2 = (~((off >> 22) ^ s_bit)) & 1
    imm10 = (off >> 12) & 0x3FF
    imm11 = (off >> 1) & 0x7FF
    return struct.pack(
        "<HH",
        0xF000 | (s_bit << 10) | imm10,
        0x9000 | (i1 << 13) | (1 << 12) | (i2 << 11) | imm11,
    )


def _arm64_b(src: int, dst: int) -> bytes:
    off = (dst - src) >> 2
    return struct.pack("<I", 0x14000000 | (off & 0x3FFFFFF))


def _patch_t2_beq(buf: bytearray, idx: int, target: int) -> None:
    disp = (target - (idx + 4)) >> 1
    buf[idx : idx + 2] = struct.pack("<H", 0xD000 | (disp & 0xFF))


def _patch_t2_bne(buf: bytearray, idx: int, target: int) -> None:
    disp = (target - (idx + 4)) >> 1
    buf[idx : idx + 2] = struct.pack("<H", 0xD100 | (disp & 0xFF))


# ---------------------------------------------------------------------------
# Pure-Python Test Suite (runs everywhere)
# ---------------------------------------------------------------------------


class TestFirmwareResearchModels(unittest.TestCase):
    """Pure-Python checks for Track 3A/3B/3C math and verified address tables."""

    def test_track3a_zve1_y_remap_positions_and_square(self) -> None:
        # 10% / 50% / 90% in 640x360 tracking grid on ZV-E1 (720x480 panel, PAR 9:8)
        positions = [
            (18, 36, (58, 40), (24, 48), (27, 41)),
            (162, 36, (219, 40), (216, 48), (219, 41)),
            (306, 36, (381, 40), (408, 48), (411, 41)),
        ]
        for y_in, h_in, exp_stock, exp_unpatched, exp_patched in positions:
            self.assertEqual(
                model_tracking_osd_y_remap(y_in, h_in, 360, 38, 404, "zve1_par98", False),
                exp_stock,
            )
            self.assertEqual(
                model_tracking_osd_y_remap(y_in, h_in, 360, 0, 480, "zve1_par98", False),
                exp_unpatched,
            )
            self.assertEqual(
                model_tracking_osd_y_remap(y_in, h_in, 360, 0, 480, "zve1_par98", True),
                exp_patched,
            )
        # 64x64 sensor square at 50%: physical width = 64*(720/640)=72 px -> height 72 px
        self.assertEqual(
            model_tracking_osd_y_remap(148, 64, 360, 0, 480, "zve1_par98", True),
            (203, 72),
        )

    def test_track3a_a7s3_y_remap_positions_and_square(self) -> None:
        # 10% / 50% / 90% in 640x360 tracking grid on a7S III (800x600 panel, PAR 1:1)
        positions = [
            (18, 36, (78, 36), (47, 42), (50, 36)),
            (162, 36, (222, 36), (218, 42), (221, 36)),
            (306, 36, (366, 36), (389, 42), (392, 36)),
        ]
        for y_in, h_in, exp_stock, exp_unpatched, exp_patched in positions:
            self.assertEqual(
                model_tracking_osd_y_remap(y_in, h_in, 360, 60, 360, "a7s3_par11", False),
                exp_stock,
            )
            self.assertEqual(
                model_tracking_osd_y_remap(y_in, h_in, 360, 26, 428, "a7s3_par11", False),
                exp_unpatched,
            )
            self.assertEqual(
                model_tracking_osd_y_remap(y_in, h_in, 360, 26, 428, "a7s3_par11", True),
                exp_patched,
            )
        # 64x64 sensor square at 50%: height restored from 76 to 64
        self.assertEqual(
            model_tracking_osd_y_remap(148, 64, 360, 26, 428, "a7s3_par11", True),
            (207, 64),
        )

    def test_track3b_fullinit_cache_guard_truth_table(self) -> None:
        # Stock skips fullinit on open-gate entry when cached Stills flags (7, 7) persist
        self.assertFalse(model_slvsec_fullinit_guard(7, 7, 0x08C0, patched=False))
        # Guarded open-gate modes (including PAL 0x28c0 / 0x2820) force fullinit
        for drv in (0x08C0, 0x0820, 0x28C0, 0x2820):
            self.assertTrue(model_slvsec_fullinit_guard(7, 7, drv, patched=True))
        # Stills modes keep cached (7, 7) skip while cold (0, 0) runs fullinit
        for stills in (0xE011, 0xA002):
            self.assertFalse(model_slvsec_fullinit_guard(7, 7, stills, patched=True))
            self.assertTrue(model_slvsec_fullinit_guard(0, 0, stills, patched=True))

    def test_track3c_option_c_rate_matrix(self) -> None:
        low_rates = [(0, 0x08C0), (1, 0x28C0), (2, 0x2820), (3, 0x0820)]
        hfr_rates = [(4, 0x27E0), (6, 0x0AE0), (8, 0x2AA0), (9, 0x0AA0)]
        for fps_code, drv in low_rates:
            out = model_option_c_decision(fps_code, drv)
            self.assertEqual((out["cp_w"], out["cp_h"]), (3840, 2560))
            self.assertEqual((out["mp4_w"], out["mp4_h"]), (3840, 2560))
            self.assertEqual(out["nrt_vline"], 2560)
            self.assertEqual(out["b_aspectValid"], 0)
            self.assertEqual(out["disp_rect"], (0, 26, 640, 428))
        for fps_code, drv in hfr_rates:
            out = model_option_c_decision(fps_code, drv)
            self.assertEqual((out["cp_w"], out["cp_h"]), (3840, 2160))
            self.assertEqual((out["mp4_w"], out["mp4_h"]), (3840, 2160))
            self.assertEqual(out["nrt_vline"], 2160)
            self.assertEqual(out["b_aspectValid"], 1)
            self.assertEqual(out["disp_rect"], (0, 60, 640, 360))

    def test_verified_targets_and_section5_documented(self) -> None:
        text = RESEARCH_DOC.read_text(encoding="utf-8")
        self.assertIn("## 5. Unicorn Emulation & Candidate Volatile-RAM Prototypes", text)
        for model, cfg in VERIFIED_TARGETS.items():
            self.assertEqual(cfg["r4_inner"] - cfg["r4_outer"], cfg["r4_offset"])
            self.assertIn(model, text)
            for key in ("drv_global", "r4_inner", "size_class_3", "l2_mp4", "tail_cave_64"):
                self.assertIn(f"0x{cfg[key]:x}", text)


# ---------------------------------------------------------------------------
# Clean-Room Unicorn Machine-Code Emulation Tests
# ---------------------------------------------------------------------------


def _new_arm32_vfp_uc(code_addr: int, code: bytes, data_addr: int = 0x00400000) -> Uc:
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    uc.mem_map(code_addr & ~0xFFF, 0x20000)
    uc.mem_map(data_addr, 0x20000)
    uc.mem_map(0x00800000, 0x20000)  # stack + return page
    uc.mem_write(code_addr, code)
    # Enable full VFP/NEON access (CP10/CP11) + FPEXC.EN
    cpacr = uc.reg_read(UC_ARM_REG_C1_C0_2)
    uc.reg_write(UC_ARM_REG_C1_C0_2, cpacr | 0x00F00000)
    uc.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
    uc.reg_write(UC_ARM_REG_SP, 0x00810000)
    return uc


@unittest.skipUnless(HAS_UNICORN, "unicorn not installed")
class TestUnicornCleanRoomTrampolines(unittest.TestCase):
    """Unicorn execution of Track 3A (VFP), Track 3B (Thumb-2), and Track 3C (Thumb-2 + AArch64)."""

    def test_unicorn_track3a_vfp_y_unstretch_zve1_and_a7s3(self) -> None:
        # Clean-room Thumb-2 + VFP routine matching the Stage-1 / Stage-2 float
        # projection pipeline and the exact candidate un-stretch trampolines:
        #   Inputs: r0=y_in, [sp+4]=h_in, [sp+8]=disp_y, [sp+12]=disp_end_y, r4=&out_y, sb=&out_h
        #   VFP computes float stage-2 h into s0, converts to [sb], then runs candidate hook.
        base = 0x00100000
        cave = 0x00101000
        stub = bytearray()
        # Save r0(y_in) & compute VFP h_s = round(h_in * (480/360) * (disp_h/480))
        # Here we inject pre-stage2 VFP arithmetic on s0..s3:
        #   vmov s0, r0 (h_in in r12? Keep clean: r0=h_in via [sp+4], r1=disp_h)
        #   EE00 0A10 -> vmov s0, r0 ; EEB8 0AC0 -> vcvt.f32.s32 s0, s0
        #   EE01 1A10 -> vmov s2, r1 ; EEB8 1AC0 -> vcvt.f32.s32 s2, s2
        #   vmov.f32 s3, #480 -> load from r2 (0x43b40000=360.0f) passed in r2
        #   EE60 0A21 -> vmul.f32 s1, s0, s2  (h_in * disp_h)
        #   EE02 2A10 -> vmov s4, r2 (360.0f)
        #   EEC0 0A82 -> vdiv.f32 s0, s1, s4  (h_in * disp_h / 360.0f)
        #   EEB0 0A40 -> vrintr/vcvtr? Let's use vmov s5, r3 (0.5f) + vadd + vcvt.s32.f32!
        stub += struct.pack(
            "<HHHHHHHHHHHH",
            0x9801,        # ldr r0, [sp, #4]  (h_in)
            0x9903,        # ldr r1, [sp, #12] (disp_end_y)
            0x9A02,        # ldr r2, [sp, #8]  (disp_y)
            0x1A89,        # subs r1, r1, r2   (disp_h)
            0xEE00, 0x0A10,  # vmov s0, r0
            0xEEB8, 0x0AC0,  # vcvt.f32.s32 s0, s0
            0xEE01, 0x1A10,  # vmov s2, r1
            0xEEB8, 0x1AC1,  # vcvt.f32.s32 s2, s2
        )
        # r2 = 360.0f (0x43b40000)
        stub += _movw(2, 0x0000) + _movt(2, 0x43B4)
        stub += struct.pack(
            "<HHHHHHHH",
            0xEE60, 0x0A01,  # vmul.f32 s1, s0, s2  (h_in * disp_h)
            0xEE02, 0x2A10,  # vmov s4, r2 (360.0f)
            0xEE80, 0x0A82,  # vdiv.f32 s0, s1, s4
            0xEEBD, 0x0AC0,  # vcvt.s32.f32 s0, s0 (truncates toward zero)
        )
        hook_off = len(stub)
        stub += struct.pack("<HH", 0xED89, 0x0A00)  # vstr s0, [sb] (4 bytes: hook target!)
        ret_addr = base + len(stub)
        stub += struct.pack("<H", 0x4770)           # bx lr

        # Test both ZV-E1 (PAR 9/8, disp_h=480) and a7S III (PAR 1:1, disp_h=428) trampolines
        for disp_h_target, scale_9_8, h_in, disp_y, disp_end, raw_y_s, exp_y, exp_h in [
            (480, True, 36, 0, 480, 216, 219, 41),    # ZV-E1 50% 36px -> 41px
            (480, True, 64, 0, 480, 197, 203, 72),    # ZV-E1 50% 64x64 square -> 72px
            (428, False, 36, 26, 454, 218, 221, 36),  # a7S III 50% 36px -> 36px
            (428, False, 64, 26, 454, 201, 207, 64),  # a7S III 50% 64x64 square -> 64px
        ]:
            tramp = bytearray()
            tramp += struct.pack("<HH", 0xED89, 0x0A00)  # vstr s0, [sb]
            tramp += struct.pack("<HHH", 0x9A03, 0x9902, 0x1A52)  # ldr r2,[sp,#12]; ldr r1,[sp,#8]; subs r2,r2,r1
            tramp += _movw(0, disp_h_target)
            tramp += struct.pack("<H", 0x4282)  # cmp r2, r0
            beq_idx = len(tramp)
            tramp += struct.pack("<H", 0xD000)
            tramp += _b_w(cave + len(tramp), ret_addr)
            adj_off = len(tramp)
            _patch_t2_beq(tramp, beq_idx, cave + adj_off)
            tramp += struct.pack("<H", 0x9801)  # ldr r0, [sp, #4] (h_in)
            if scale_9_8:
                tramp += struct.pack("<HHH", 0xEB00, 0x00C0, 0x3004)  # add r0,r0,lsl#3; adds #4
                tramp += struct.pack("<H", 0x10C0)                    # asrs r0, r0, #3
            tramp += struct.pack("<HH", 0xF8D9, 0x1000)  # ldr.w r1, [sb]
            tramp += struct.pack("<HH", 0x1A09, 0x1049)  # subs r1, r1, r0; asrs r1, r1, #1
            tramp += struct.pack("<HHH", 0x6822, 0x1852, 0x6022)  # ldr r2,[r4]; adds r2,r2,r1; str r2,[r4]
            tramp += struct.pack("<HH", 0xF8C9, 0x0000)           # str.w r0, [sb]
            tramp += _b_w(cave + len(tramp), ret_addr)

            image = bytearray(0x2000)
            image[0 : len(stub)] = stub
            image[hook_off : hook_off + 4] = _b_w(base + hook_off, cave)
            image[cave - base : cave - base + len(tramp)] = tramp

            uc = _new_arm32_vfp_uc(base, bytes(image))
            data = 0x00400000
            sp = 0x00810000 - 16
            uc.mem_write(sp, struct.pack("<IIII", 0, h_in, disp_y, disp_end))
            uc.mem_write(data, struct.pack("<II", raw_y_s, 0))
            uc.reg_write(UC_ARM_REG_SP, sp)
            uc.reg_write(UC_ARM_REG_R4, data)
            uc.reg_write(UC_ARM_REG_SB, data + 4)
            uc.reg_write(UC_ARM_REG_LR, 0x00818001)
            uc.emu_start(base | 1, 0x00818000, count=200)
            got_y, got_h = struct.unpack("<II", uc.mem_read(data, 8))
            self.assertEqual((got_y, got_h), (exp_y, exp_h))

    def test_unicorn_track3b_fullinit_guard_trampoline(self) -> None:
        # Clean-room Thumb-2 CetusSlvsecDriver::start wrapper:
        #   r4 = struct { +0x1c: p1_1, +0x2c: p2_1, +0x48: new_drv }
        #   r5 = counter address incremented iff fullinit path executes.
        base = 0x00200000
        cave = 0x00201000
        fn = bytearray()
        fn += struct.pack("<HH", 0x69E1, 0x6AE2)  # ldr r1,[r4,#0x1c]; ldr r2,[r4,#0x2c]
        cmp_off = len(fn)
        fn += struct.pack("<HHHH", 0x2907, 0xBF08, 0x2A07, 0xD000)  # cmp r1,#7; it eq; cmpeq r2,#7; beq skip
        fullinit_addr = base + len(fn)
        fn += struct.pack("<HHH", 0x682B, 0x3301, 0x602B)  # ldr r3,[r5]; adds r3,#1; str r3,[r5]
        skip_addr = base + len(fn)
        fn += struct.pack("<H", 0x4770)  # bx lr
        # Patch stock beq target to skip_addr before installing hook
        _patch_t2_beq(fn, cmp_off + 6, skip_addr)

        # Build Track 3B guard trampoline in cave
        tramp = bytearray()
        tramp += struct.pack("<H", 0x6CA0)              # ldr r0, [r4, #0x48]
        tramp += struct.pack("<HH", 0xF3C0, 0x000C)     # ubfx r0, r0, #0, #13
        tramp += _movw(3, 0x08C0) + struct.pack("<H", 0x4298)  # cmp r0, r3
        b1 = len(tramp); tramp += struct.pack("<H", 0xD000)
        tramp += _movw(3, 0x0820) + struct.pack("<H", 0x4298)  # cmp r0, r3
        b2 = len(tramp); tramp += struct.pack("<H", 0xD000)
        tramp += struct.pack("<HHHH", 0x2907, 0xBF08, 0x2A07, 0xD100)  # cmp r1,#7; it eq; cmpeq r2,#7; bne fullinit
        bne_idx = len(tramp) - 2
        tramp += _b_w(cave + len(tramp), skip_addr)
        fi_off = len(tramp)
        tramp += _b_w(cave + fi_off, fullinit_addr)
        _patch_t2_beq(tramp, b1, cave + fi_off)
        _patch_t2_beq(tramp, b2, cave + fi_off)
        _patch_t2_bne(tramp, bne_idx, cave + fi_off)

        stock_img = bytearray(0x2000)
        stock_img[0 : len(fn)] = fn

        patched_img = bytearray(stock_img)
        patched_img[cmp_off : cmp_off + 4] = _b_w(base + cmp_off, cave)
        patched_img[cave - base : cave - base + len(tramp)] = tramp

        cases = [
            (stock_img, 7, 7, 0x08C0, 0),
            (patched_img, 7, 7, 0x08C0, 1),
            (patched_img, 7, 7, 0x0820, 1),
            (patched_img, 7, 7, 0x28C0, 1),
            (patched_img, 7, 7, 0x2820, 1),
            (patched_img, 7, 7, 0xE011, 0),
            (patched_img, 7, 7, 0xA002, 0),
            (patched_img, 0, 0, 0xE011, 1),
        ]
        for img, p1_1, p2_1, new_drv, exp_calls in cases:
            uc = _new_arm32_vfp_uc(base, bytes(img))
            r4_mem = 0x00400000
            cnt_mem = 0x00401000
            uc.mem_write(r4_mem + 0x1C, struct.pack("<I", p1_1))
            uc.mem_write(r4_mem + 0x2C, struct.pack("<I", p2_1))
            uc.mem_write(r4_mem + 0x48, struct.pack("<I", new_drv))
            uc.mem_write(cnt_mem, struct.pack("<I", 0))
            uc.reg_write(UC_ARM_REG_R4, r4_mem)
            from unicorn.arm_const import UC_ARM_REG_R5

            uc.reg_write(UC_ARM_REG_R5, cnt_mem)
            uc.reg_write(UC_ARM_REG_LR, 0x00818001)
            uc.emu_start(base | 1, 0x00818000, count=200)
            calls = struct.unpack("<I", uc.mem_read(cnt_mem, 4))[0]
            self.assertEqual(calls, exp_calls)

    def test_unicorn_track3c_coupled_arm32_and_arm64_option_c(self) -> None:
        # 1) AArch32 Thumb-2 Size Class 3 selector + picture_ratio hook
        drv_addr = 0x00402000
        base32 = 0x00300000
        # Size selector subroutine (returns packed (h<<16)|w in r0):
        #   if (drv & 0x1fff) in {0x8c0, 0x820} -> 0x0a000f00 else 0x08700f00
        sz = bytearray()
        sz += _movw(1, drv_addr & 0xFFFF) + _movt(1, drv_addr >> 16)
        sz += struct.pack("<H", 0x8809)               # ldrh r1, [r1]
        sz += struct.pack("<HH", 0xF3C1, 0x010C)      # ubfx r1, r1, #0, #13
        sz += _movw(2, 0x08C0) + struct.pack("<H", 0x4291)
        b1 = len(sz); sz += struct.pack("<H", 0xD000)
        sz += _movw(2, 0x0820) + struct.pack("<H", 0x4291)
        b2 = len(sz); sz += struct.pack("<H", 0xD000)
        sz += _movw(0, 0x0F00) + _movt(0, 0x0870) + struct.pack("<H", 0x4770)
        og_off = len(sz)
        sz += _movw(0, 0x0F00) + _movt(0, 0x0A00) + struct.pack("<H", 0x4770)
        _patch_t2_beq(sz, b1, og_off)
        _patch_t2_beq(sz, b2, og_off)

        # Aspect numerator/denominator selector (r2=num, r3=den matching picture_ratio)
        pr_off = (len(sz) + 3) & ~3
        pr = bytearray()
        pr += _movw(1, drv_addr & 0xFFFF) + _movt(1, drv_addr >> 16)
        pr += struct.pack("<H", 0x8809)               # ldrh r1, [r1]
        pr += struct.pack("<HH", 0xF3C1, 0x010C)      # ubfx r1, r1, #0, #13
        pr += _movw(0, 0x08C0) + struct.pack("<H", 0x4281)
        p1 = len(pr); pr += struct.pack("<H", 0xD000)
        pr += _movw(0, 0x0820) + struct.pack("<H", 0x4281)
        p2 = len(pr); pr += struct.pack("<H", 0xD000)
        pr += struct.pack("<HHH", 0x2209, 0x2310, 0x4770)  # movs r2,#9; movs r3,#16; bx lr
        pr_og = len(pr)
        pr += struct.pack("<HHH", 0x2202, 0x2303, 0x4770)  # movs r2,#2; movs r3,#3; bx lr
        _patch_t2_beq(pr, p1, pr_og)
        _patch_t2_beq(pr, p2, pr_og)

        img32 = bytearray(0x2000)
        img32[0 : len(sz)] = sz
        img32[pr_off : pr_off + len(pr)] = pr

        # 2) AArch64 leaf-safe L2-mp4 (32B) + NrtMetaWrapper (16B) trampolines
        base64 = 0x00000000
        l2_fn = 0x1000
        l2_strh = l2_fn + 8
        nrt_fn = 0x1200
        nrt_noasp = nrt_fn + 4
        cave_l2 = 0x2000
        cave_nrt = cave_l2 + 32

        # L2-mp4 host stub (leaf function: lr must be preserved!)
        #   x0 = OUT_ATTR, x1 = IN_PARAM ([x1,#0x18]=fps_code)
        #   mov w6, #0x870; mov w7, #0xf00
        #   b cave_l2   (replaces strh w6, [x0, #0x40])
        #   strh w7, [x0, #0x42]; ret
        l2_stub = [
            0x52810E06,  # mov w6, #0x870
            0x5281E007,  # mov w7, #0xf00
            struct.unpack("<I", _arm64_b(l2_strh, cave_l2))[0],
            0x79008407,  # strh w7, [x0, #0x42]
            0xD65F03C0,  # ret
        ]
        # Candidate 32-byte L2-mp4 trampoline (identical binary layout verified in offline firmware)
        l2_tramp = [
            0x7121C0DF,  # cmp w6, #0x870
            0x540000A1,  # b.ne +0x14 (strh)
            0xB9401829,  # ldr w9, [x1, #0x18]
            0x71000D3F,  # cmp w9, #3
            0x54000048,  # b.hi +0x8 (strh)
            0x52814006,  # mov w6, #0xa00
            0x79008006,  # strh w6, [x0, #0x40]
            struct.unpack("<I", _arm64_b(cave_l2 + 28, l2_strh + 4))[0],
        ]
        # NrtMetaWrapper host stub:
        #   ldrh w0, [x20, #0x5e]; b cave_nrt; strb w0, [x29, #0x78]; ret
        nrt_stub = [
            0x7940BE80,  # ldrh w0, [x20, #0x5e]  (we also write w0 -> [x29, #0x74] before jumping)
            struct.unpack("<I", _arm64_b(nrt_noasp, cave_nrt))[0],
            0x3901E3A0,  # strb w0, [x29, #0x78]
            0xD65F03C0,  # ret
        ]
        #Wait: write w0 into [x29, #0x74] before nrt_noasp: shift nrt_stub by 1 insn!
        nrt_noasp = nrt_fn + 8
        nrt_stub = [
            0x7940BE80,  # ldrh w0, [x20, #0x5e]
            0xB90077A0,  # str w0, [x29, #0x74]
            struct.unpack("<I", _arm64_b(nrt_noasp, cave_nrt))[0],
            0x3901E3A0,  # strb w0, [x29, #0x78]
            0xD65F03C0,  # ret
        ]
        # Candidate 16-byte NrtMetaWrapper trampoline
        nrt_tramp = [
            0xB94077A9,  # ldr w9, [x29, #0x74]
            0x7128013F,  # cmp w9, #0xa00
            0x1A9F07E0,  # cset w0, ne
            struct.unpack("<I", _arm64_b(cave_nrt + 12, nrt_noasp + 4))[0],
        ]

        uc32 = _new_arm32_vfp_uc(base32, bytes(img32))
        uc64 = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        uc64.mem_map(base64, 0x20000)
        uc64.mem_map(0x00700000, 0x20000)
        uc64.mem_write(l2_fn, b"".join(struct.pack("<I", w) for w in l2_stub))
        uc64.mem_write(nrt_fn, b"".join(struct.pack("<I", w) for w in nrt_stub))
        uc64.mem_write(cave_l2, b"".join(struct.pack("<I", w) for w in l2_tramp))
        uc64.mem_write(cave_nrt, b"".join(struct.pack("<I", w) for w in nrt_tramp))

        rates = [
            (0, 0x08C0, 3840, 2560, 2, 3, 0),
            (1, 0x28C0, 3840, 2560, 2, 3, 0),
            (2, 0x2820, 3840, 2560, 2, 3, 0),
            (3, 0x0820, 3840, 2560, 2, 3, 0),
            (4, 0x27E0, 3840, 2160, 9, 16, 1),
            (6, 0x0AE0, 3840, 2160, 9, 16, 1),
            (8, 0x2AA0, 3840, 2160, 9, 16, 1),
            (9, 0x0AA0, 3840, 2160, 9, 16, 1),
        ]
        for fps_code, drv, exp_w, exp_h, exp_num, exp_den, exp_bvalid in rates:
            uc32.mem_write(drv_addr, struct.pack("<H", drv))
            uc32.reg_write(UC_ARM_REG_LR, 0x00818001)
            uc32.emu_start(base32 | 1, 0x00818000, count=200)
            packed_sz = uc32.reg_read(UC_ARM_REG_R0)
            self.assertEqual((packed_sz & 0xFFFF, packed_sz >> 16), (exp_w, exp_h))

            uc32.reg_write(UC_ARM_REG_LR, 0x00818001)
            uc32.emu_start((base32 + pr_off) | 1, 0x00818000, count=200)
            self.assertEqual((uc32.reg_read(UC_ARM_REG_R2), uc32.reg_read(UC_ARM_REG_R3)), (exp_num, exp_den))

            out_attr = 0x00700000
            in_param = 0x00701000
            x20_attr = 0x00702000
            x29_frm = 0x00703000
            uc64.mem_write(in_param + 0x18, struct.pack("<I", fps_code))
            uc64.reg_write(UC_ARM64_REG_SP, 0x00718000)
            uc64.reg_write(UC_ARM64_REG_X0, out_attr)
            uc64.reg_write(UC_ARM64_REG_X1, in_param)
            uc64.reg_write(UC_ARM64_REG_LR, 0x00719000)
            uc64.emu_start(l2_fn, 0x00719000, count=200)
            mp4_h, mp4_w = struct.unpack("<HH", uc64.mem_read(out_attr + 0x40, 4))
            self.assertEqual((mp4_w, mp4_h), (exp_w, exp_h))

            uc64.mem_write(x20_attr + 0x5C, struct.pack("<HH", mp4_w, mp4_h))
            uc64.reg_write(UC_ARM64_REG_X20, x20_attr)
            uc64.reg_write(UC_ARM64_REG_X29, x29_frm)
            uc64.reg_write(UC_ARM64_REG_LR, 0x00719000)
            uc64.emu_start(nrt_fn, 0x00719000, count=200)
            nrt_vline = struct.unpack("<I", uc64.mem_read(x29_frm + 0x74, 4))[0]
            b_aspect_valid = uc64.mem_read(x29_frm + 0x78, 1)[0]
            self.assertEqual((nrt_vline, b_aspect_valid), (exp_h, exp_bvalid))


if __name__ == "__main__":
    unittest.main()
