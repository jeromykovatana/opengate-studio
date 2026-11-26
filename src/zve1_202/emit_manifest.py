#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Emit kits/zve1_202/manifest.json with exact SHA-256 hashes, levels, and packs."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parents[1] / "kits/zve1_202"


def file_meta(filename: str) -> tuple[str, int]:
    data = (KIT / filename).read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def main() -> None:
    step_specs = [
        ("L13", 13, "Apply DMM raw write buffer size dmmwb_zv_v1 (10.3MB -> 26.2MB, 1 word)"),
        ("L14", 14, "Put back DMM raw write buffer size dmmwb_zv_v1"),
        ("L5", 5, "Apply sensor-side open-gate ogsq_zv_v3 (0x8c0 + 0x820, NTSC/PAL MULTI_REC, 40 cells + 2 stored records)"),
        ("L6", 6, "Put back sensor-side open-gate ogsq_zv_v3"),
        ("L16", 16, "Apply coprocessor output size outsz2560_zv_v1 (3840x2160 -> 3840x2560)"),
        ("L17", 17, "Put back coprocessor output size outsz2560_zv_v1"),
        ("L19", 19, "Apply 23.98p/25p/29.97p data-only encoder tables ogfile2560_hs_s_zv_nometa (149 av-cam + 4 libmpr)"),
        ("L20", 20, "Put back 23.98p/25p/29.97p data-only encoder tables ogfile2560_hs_s_zv_nometa"),
        ("V19", 19, "Apply 23.98p/25p/29.97p encoder + native 3:2 MP4 container/NRT/playback ogfile2560_hs_s_zv_v3 (149 av-cam + 12 libmpr)"),
        ("V20", 20, "Put back 23.98p/25p/29.97p encoder + native 3:2 MP4 container/NRT/playback ogfile2560_hs_s_zv_v3"),
        ("S16", 16, "Apply rear LCD 3:2 fill & AF/tracking frame tables lcdfill_zv_v2 (5 words)"),
        ("S17", 17, "Put back rear LCD 3:2 fill & AF/tracking frame tables lcdfill_zv_v2"),
        ("C19", 19, "Apply C2 preview aspect cycling routine lcdcycle_zv_v1 (appFw.so)"),
        ("C20", 20, "Put back C2 preview aspect cycling routine lcdcycle_zv_v1"),
        ("H16", 16, "Apply 3:2 pillarboxed HDMI & anamorphic de-squeeze hdmi32_zv_202 (16 cpapp words)"),
        ("H17", 17, "Put back 3:2 pillarboxed HDMI & anamorphic de-squeeze hdmi32_zv_202"),
        ("B19", 19, "Apply 200M/300M high-bitrate Long-GOP overlay og_highbitrate_zv_202 (108 av-cam sites)"),
        ("B20", 20, "Put back 200M/300M high-bitrate Long-GOP overlay og_highbitrate_zv_202"),
        ("I19", 19, "Apply orthogonal XAVC S-I 3840x2560 (23.98p/25p/29.97p) delta og_xavcsi_addon_zv_202 (30 av-cam + 2 libmpr, incl. +0x56 dual-core split)"),
        ("I20", 20, "Put back orthogonal XAVC S-I 3840x2560 (23.98p/25p/29.97p) delta og_xavcsi_addon_zv_202"),
    ]

    steps = {}
    for code, level, summary in step_specs:
        fn = f"libJit_zv_{code}.so"
        sha, size = file_meta(fn)
        steps[code] = {
            "file": fn,
            "sha256": sha,
            "size": size,
            "level": level,
            "summary": summary,
        }

    ro_specs = [
        ("check", 101, "Coherent read-only preflight check (zvread_v4: 31 cp + 12 lm + 101 av sites)"),
        ("dump", 102, "Coherent read-only diagnostic dump + coprocessor pages (zvread_v4)"),
    ]
    readonly = {}
    for code, level, summary in ro_specs:
        fn = f"libJit_zv_{code}.so"
        sha, size = file_meta(fn)
        readonly[code] = {
            "file": fn,
            "sha256": sha,
            "size": size,
            "level": level,
            "summary": summary,
        }

    di_sha, di_size = file_meta("DeviceInfo.xml")
    manifest = {
        "schema_version": 1,
        "body_id": "zve1_202",
        "camera": "ZV-E1",
        "firmware": "2.02",
        "version_txt": "32000_08.2025101101",
        "toolchain": "ziglang 0.13.0 (clang 18.1.6)",
        "persistent_writes": False,
        "device_info": {
            "file": "DeviceInfo.xml",
            "sha256": di_sha,
            "size": di_size,
        },
        "readonly": readonly,
        "packs": {
            "core_open_gate": {
                "label": "Core 3:2 Open Gate (Sensor + DMM + Output Size)",
                "required": True,
                "apply_steps": ["L13", "L5", "L16"],
                "putback_steps": ["L17", "L6", "L14"],
                "summary": "Enables 3840x2560 sensor readout across 23.98p/24p/25p/29.97p (NTSC & PAL), raw write buffer resize, and output size class",
            },
            "mp4_3x2": {
                "label": "Native 3:2 MP4 Container & Playback",
                "required": False,
                "apply_steps": ["V19"],
                "putback_steps": ["V20"],
                "fallback_apply_steps": ["L19"],
                "fallback_putback_steps": ["L20"],
                "summary": "Patches 23.98p/25p/29.97p encoder tables + 8 libmpr.so sites for native 3:2 MP4/NRT/playback (falls back to L19/L20)",
            },
            "screen_3x2": {
                "label": "3:2 Rear LCD Fill & C2 Aspect Cycling",
                "required": False,
                "apply_steps": ["S16", "C19"],
                "putback_steps": ["C20", "S17"],
                "summary": "Full-height 3:2 rear LCD live view with focus frames and C2 aspect cycling",
            },
            "hdmi32": {
                "label": "Clean 3:2 Pillarboxed HDMI & De-Squeeze",
                "required": False,
                "apply_steps": ["H16"],
                "putback_steps": ["H17"],
                "summary": "Clean 3:2 pillarboxed HDMI output and uncropped 3:2 anamorphic de-squeeze",
            },
            "high_bitrate": {
                "label": "High-Bitrate Long-GOP (200M/300M)",
                "required": False,
                "apply_steps": ["B19"],
                "putback_steps": ["B20"],
                "summary": "Upgrades 27 XAVC HS/S Long-GOP 23.98p/25p profiles to 200M/300M",
            },
            "xavc_si": {
                "label": "XAVC S-I All-Intra 3840x2560",
                "required": False,
                "apply_steps": ["I19"],
                "putback_steps": ["I20"],
                "summary": "Orthogonal delta unlocking XAVC S-I All-Intra 3840x2560 at 23.98p/25p/29.97p",
            },
        },
        "steps": steps,
    }
    (KIT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf8", newline="\n")
    print(f"PASS kits/zve1_202/manifest.json: {len(steps)} steps, {len(readonly)} readonly, {len(manifest['packs'])} packs")


if __name__ == "__main__":
    main()
