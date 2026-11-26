#!/usr/bin/env python3
"""Pure-Python ISOBMFF + NRT XML + rtmd gyro clip inspector for Sony BIONZ XR Open Gate.

Supports ZV-E1, a7S III, FX3 (3840x2560), and a7 IV (3840x2560 & 5760x3840)
across hvc1 (HEVC) and avc1 (AVC / XAVC S / XAVC S-I) at 23.976p and 25.000p.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

SONY_PROF_UUID = b"PROF!\xd2O\xce\xbb\x88i\\\xfa\xc9\xc7@"
IDENTITY_MATRIX = (65536, 0, 0, 0, 65536, 0, 0, 0, 1 << 30)
VALID_OPEN_GATE_SIZES = {(3840, 2560), (5760, 3840)}
VALID_STOCK_SIZES = {(3840, 2160), (4096, 2160)}


def iter_boxes(buf: bytes, start: int = 0, end: int | None = None):
    """Yield (tag, payload_start, box_end) for ISOBMFF boxes in buf[start:end]."""
    end = len(buf) if end is None else end
    pos = start
    while pos < end:
        if end - pos < 8:
            raise ValueError("Truncated MP4 box header")
        size, tag = struct.unpack_from(">I4s", buf, pos)
        header = 8
        if size == 1:
            if end - pos < 16:
                raise ValueError("Truncated extended MP4 box header")
            (size,) = struct.unpack_from(">Q", buf, pos + 8)
            header = 16
        elif size == 0:
            size = end - pos
        if not header <= size <= end - pos:
            raise ValueError(f"Invalid {tag!r} box length ({size})")
        yield tag, pos + header, pos + size
        pos += size


def find_boxes(buf: bytes, start: int, end: int, tag: bytes) -> list[tuple[int, int]]:
    return [(a, b) for t, a, b in iter_boxes(buf, start, end) if t == tag]


def find_one_box(buf: bytes, region: tuple[int, int], tag: bytes) -> tuple[int, int]:
    found = find_boxes(buf, region[0], region[1], tag)
    if len(found) != 1:
        raise ValueError(f"Expected one {tag!r} box, found {len(found)}")
    return found[0]


def read_moov_bytes(path: Path) -> tuple[int, bytes]:
    """Read the top-level 'moov' box payload without loading 'mdat'."""
    with path.open("rb") as f:
        length = os.fstat(f.fileno()).st_size
        while f.tell() < length:
            pos = f.tell()
            hdr = f.read(8)
            if len(hdr) < 8:
                raise ValueError("Truncated top-level MP4 box")
            size, tag = struct.unpack(">I4s", hdr)
            if size == 1:
                ext = f.read(8)
                if len(ext) < 8:
                    raise ValueError("Truncated top-level 64-bit box")
                (size,) = struct.unpack(">Q", ext)
            elif size == 0:
                size = length - pos
            payload_len = pos + size - f.tell()
            if payload_len < 0 or pos + size > length:
                raise ValueError("Invalid top-level MP4 box length")
            if tag == b"moov":
                if payload_len > 128 * 1024**2:
                    raise ValueError("moov box exceeds 128 MiB limit")
                return f.tell(), f.read(payload_len)
            f.seek(payload_len, os.SEEK_CUR)
    raise ValueError("Missing 'moov' box")


def _parse_tkhd(buf: bytes, a: int, b: int) -> dict[str, Any]:
    if b - a < 84:
        raise ValueError("Truncated 'tkhd' box")
    version = buf[a]
    if version == 0:
        (track_id,) = struct.unpack_from(">I", buf, a + 12)
    elif version == 1:
        if b - a < 96:
            raise ValueError("Truncated v1 'tkhd' box")
        (track_id,) = struct.unpack_from(">I", buf, a + 20)
    else:
        raise ValueError(f"Unsupported 'tkhd' version {version}")
    matrix = struct.unpack_from(">9i", buf, b - 44)
    w_fp, h_fp = struct.unpack_from(">II", buf, b - 8)
    return {
        "track_id": track_id,
        "width": w_fp / 65536.0,
        "height": h_fp / 65536.0,
        "identity_matrix": matrix == IDENTITY_MATRIX,
        "matrix": list(matrix),
    }


def _parse_mdhd_timescale(buf: bytes, a: int, b: int) -> int:
    if b - a < 24:
        raise ValueError("Truncated 'mdhd' box")
    version = buf[a]
    if version == 0:
        (timescale,) = struct.unpack_from(">I", buf, a + 12)
    elif version == 1:
        if b - a < 32:
            raise ValueError("Truncated v1 'mdhd' box")
        (timescale,) = struct.unpack_from(">I", buf, a + 20)
    else:
        raise ValueError(f"Unsupported 'mdhd' version {version}")
    return timescale


def _fps_label_from_values(timescale: int, sample_delta: int) -> tuple[str, str]:
    if timescale <= 0 or sample_delta <= 0:
        return "unknown", "0/1"
    fps_val = timescale / sample_delta
    g = math.gcd(timescale, sample_delta)
    frac = f"{timescale // g}/{sample_delta // g}"
    if abs(fps_val - 24000 / 1001) < 0.02:
        return "23.976p", "24000/1001"
    if abs(fps_val - 25.0) < 0.02:
        return "25.000p", "25/1"
    if abs(fps_val - 24.0) < 0.02:
        return "24.000p", "24/1"
    if abs(fps_val - 30000 / 1001) < 0.02:
        return "29.970p", "30000/1001"
    if abs(fps_val - 50.0) < 0.02:
        return "50.000p", "50/1"
    if abs(fps_val - 60000 / 1001) < 0.02:
        return "59.940p", "60000/1001"
    if abs(fps_val - 100.0) < 0.05:
        return "100.000p", "100/1"
    if abs(fps_val - 120000 / 1001) < 0.05:
        return "119.880p", "120000/1001"
    return f"{fps_val:.3f}p", frac


def _parse_stts_stats(buf: bytes, a: int, b: int, timescale: int) -> dict[str, Any]:
    if b - a < 8:
        raise ValueError("Truncated 'stts' box")
    (entry_count,) = struct.unpack_from(">I", buf, a + 4)
    if entry_count == 0 or b - a < 8 + 8:
        return {
            "fps": "unknown",
            "fps_exact": "0/1",
            "frame_count": 0,
            "duration_sec": 0.0,
            "cadence_constant": True,
        }
    available_entries = (b - a - 8) // 8
    count_to_read = min(entry_count, available_entries)
    total_frames = 0
    total_ticks = 0
    first_delta = 0
    deltas: set[int] = set()
    for idx in range(count_to_read):
        sample_count, sample_delta = struct.unpack_from(">II", buf, a + 8 + idx * 8)
        if idx == 0:
            first_delta = sample_delta
        total_frames += sample_count
        total_ticks += sample_count * sample_delta
        if sample_delta > 0 and sample_count > 0:
            deltas.add(sample_delta)

    fps_label, fps_exact = _fps_label_from_values(timescale, first_delta)
    duration_sec = round(total_ticks / timescale, 2) if timescale > 0 else 0.0
    return {
        "fps": fps_label,
        "fps_exact": fps_exact,
        "frame_count": total_frames,
        "duration_sec": duration_sec,
        "cadence_constant": len(deltas) <= 1,
    }


def _parse_stts_fps(buf: bytes, a: int, b: int, timescale: int) -> tuple[str, str]:
    stats = _parse_stts_stats(buf, a, b, timescale)
    return stats["fps"], stats["fps_exact"]


_AVC_PROFILES = {
    66: "Baseline",
    77: "Main",
    88: "Extended",
    100: "High",
    110: "High 10",
    122: "High 4:2:2",
    244: "High 4:4:4",
}

_HEVC_PROFILES = {
    1: "Main",
    2: "Main 10",
    3: "Main Still Picture",
    4: "Format Range Extensions",
}


def _parse_codec_config(
    codec_tag: bytes,
    children: list[tuple[bytes, int, int]],
    buf: bytes,
) -> dict[str, Any]:
    codec_str = codec_tag.decode("ascii", "replace")
    if codec_tag in (b"avc1", b"avc3"):
        for k, u, v in children:
            if k == b"avcC" and v - u >= 4:
                profile_idc = buf[u + 1]
                level_idc = buf[u + 3]
                prof_name = _AVC_PROFILES.get(profile_idc, f"Profile {profile_idc}")
                return {
                    "codec_profile_level": f"AVC {prof_name} L{level_idc / 10:.1f}",
                    "codec_level_idc": level_idc,
                }
    elif codec_tag in (b"hvc1", b"hev1"):
        for k, u, v in children:
            if k == b"hvcC" and v - u >= 13:
                profile_idc = buf[u + 1] & 0x1F
                level_idc = buf[u + 12]
                prof_name = _HEVC_PROFILES.get(profile_idc, f"Profile {profile_idc}")
                return {
                    "codec_profile_level": f"HEVC {prof_name} L{level_idc / 30:.1f}",
                    "codec_level_idc": level_idc,
                }
    return {
        "codec_profile_level": f"{codec_str} (no config box)",
        "codec_level_idc": None,
    }


def _parse_stsz(buf: bytes, a: int, b: int) -> int:
    if b - a < 12:
        raise ValueError("Truncated 'stsz' box")
    sample_size, sample_count = struct.unpack_from(">II", buf, a + 4)
    if sample_size == 0 and sample_count > 0:
        available = (b - a - 12) // 4
        if available < sample_count:
            return available
        sizes = struct.unpack_from(f">{sample_count}I", buf, a + 12)
        return sum(1 for s in sizes if s > 0)
    return sample_count


def _parse_vprf_boxes(buf: bytes, moov_end: int) -> dict[str, Any] | None:
    """Locate Sony 'uuid' (PROF) -> 'VPRF' (or direct 'PROF'/'VPRF') box in moov."""
    candidates: list[tuple[int, int]] = []

    def walk(start: int, end: int) -> None:
        for tag, a, b in iter_boxes(buf, start, end):
            if tag == b"VPRF":
                candidates.append((a, b))
            elif tag == b"PROF":
                for skip in (8, 4, 0):
                    if a + skip <= b:
                        try:
                            walk(a + skip, b)
                            break
                        except ValueError:
                            continue
            elif tag == b"uuid" and b - a >= 16 and buf[a : a + 16] == SONY_PROF_UUID:
                for skip in (24, 20, 16):
                    if a + skip <= b:
                        try:
                            walk(a + skip, b)
                            break
                        except ValueError:
                            continue
            elif tag in (b"udta", b"meta"):
                offset = 4 if tag == b"meta" else 0
                if a + offset <= b:
                    try:
                        walk(a + offset, b)
                    except ValueError:
                        pass

    walk(0, moov_end)
    if not candidates:
        return None
    a, b = candidates[0]
    payload = buf[a:b]
    # Sony FUN_0020afb4 + FUN_001b8db4 writes FullBox(4B) + 40B struct (width/height at +0x20/+0x22)
    if len(payload) >= 44:
        codec_bytes = payload[8:12]
        w, h, sar_n, sar_d = struct.unpack_from(">HHHH", payload, 36)
        return {
            "found": True,
            "codec": codec_bytes.decode("ascii", "replace"),
            "width": w,
            "height": h,
            "sar": [sar_n, sar_d],
        }
    if len(payload) >= 36:
        codec_bytes = payload[4:8]
        w, h = struct.unpack_from(">HH", payload, 32)
        return {
            "found": True,
            "codec": codec_bytes.decode("ascii", "replace"),
            "width": w,
            "height": h,
            "sar": [1, 1],
        }
    return {"found": True, "codec": "unknown", "width": 0, "height": 0, "sar": [0, 0]}


def _extract_embedded_xml(buf: bytes, moov_end: int) -> str | None:
    """Locate embedded Sony NRT XML inside moov ('meta'/'xml ' or 'uuid' XML)."""
    found_xml: list[str] = []

    def walk(start: int, end: int) -> None:
        for tag, a, b in iter_boxes(buf, start, end):
            if tag == b"xml " and b - a > 4:
                text = buf[a + 4 : b].decode("utf8", "replace").strip("\x00 \r\n\t")
                if "<" in text:
                    found_xml.append(text)
            elif tag == b"uuid" and b - a > 16:
                raw = buf[a + 16 : b]
                if b"NonRealTimeMeta" in raw or b"<VideoLayout" in raw:
                    idx = raw.find(b"<")
                    if idx >= 0:
                        found_xml.append(raw[idx:].decode("utf8", "replace").strip("\x00 \r\n\t"))
            elif tag in (b"trak", b"udta", b"meta"):
                off = 4 if tag == b"meta" else 0
                if a + off <= b:
                    try:
                        walk(a + off, b)
                    except ValueError:
                        pass

    walk(0, moov_end)
    return found_xml[0] if found_xml else None


def _inspect_xml_text(xml_text: str, exp_w: int, exp_h: int, expect_open_gate: bool) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    layouts = [e.attrib for e in root.iter() if e.tag.split("}")[-1] == "VideoLayout"]
    frames = [e.attrib for e in root.iter() if e.tag.split("}")[-1] == "VideoFrame"]
    codecs = [e.get("videoCodec") for e in root.iter() if e.get("videoCodec")]
    issues: list[str] = []

    if not layouts and not frames:
        issues.append("XML contains neither <VideoLayout> nor <VideoFrame>")
    for r in layouts:
        px = r.get("pixel")
        vl = r.get("numOfVerticalLine")
        ar = r.get("aspectRatio")
        if px != str(exp_w) or vl != str(exp_h):
            issues.append(f"XML VideoLayout pixel={px} numOfVerticalLine={vl} != {exp_w}x{exp_h}")
        if expect_open_gate:
            if ar == "16:9":
                issues.append("XML VideoLayout still carries aspectRatio='16:9' (breaks 3:2 Gyroflow/Catalyst framing)")
            elif ar not in (None, "3:2"):
                issues.append(f"XML VideoLayout unexpected aspectRatio={ar!r}")
        else:
            if ar not in (None, "16:9"):
                issues.append(f"XML VideoLayout unexpected stock aspectRatio={ar!r}")

    for f in frames:
        vc = f.get("videoCodec", "")
        for m in re.finditer(r"(\d{4})[_x](\d{4})", vc):
            if int(m.group(1)) != exp_w or int(m.group(2)) != exp_h:
                issues.append(f"XML VideoFrame videoCodec={vc!r} mismatches {exp_w}x{exp_h}")

    for c in codecs:
        for m in re.finditer(r"(\d{4})[_x](\d{4})", c):
            if int(m.group(1)) != exp_w or int(m.group(2)) != exp_h:
                issues.append(f"XML videoCodec={c!r} mismatches {exp_w}x{exp_h}")

    return {
        "ok": len(issues) == 0,
        "layouts": layouts,
        "frames": frames,
        "video_codec": codecs,
        "issues": issues,
    }


def detect_sidecar_xml(mp4_path: Path) -> Path | None:
    """Auto-detect matching Sony M01.XML sidecar beside an MP4 clip."""
    stem = mp4_path.stem
    parent = mp4_path.parent
    candidates = [
        parent / f"{stem}M01.XML",
        parent / f"{stem}M01.xml",
        parent / f"{stem}.XML",
        parent / f"{stem}.xml",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def inspect_clip(
    mp4_path: Path,
    xml_path: Path | None = None,
    expect: str = "open-gate",
    body: str | None = None,
    auto_xml: bool = True,
) -> tuple[dict[str, Any], list[tuple[int, bytes]]]:
    """Inspect a Sony MP4 clip + embedded/sidecar XML + rtmd track in pure Python."""
    base_off, buf = read_moov_bytes(mp4_path)
    moov_end = len(buf)
    issues: list[str] = []

    video_tracks: list[tuple[dict[str, Any], list[tuple[int, bytes]]]] = []
    rtmd_tracks: list[dict[str, Any]] = []
    audio_tracks = 0

    for tag, a, b in iter_boxes(buf, 0, moov_end):
        if tag != b"trak":
            continue
        tkhd_a, tkhd_b = find_one_box(buf, (a, b), b"tkhd")
        tkhd = _parse_tkhd(buf, tkhd_a, tkhd_b)
        mdia = find_one_box(buf, (a, b), b"mdia")
        hdlr_a, hdlr_b = find_one_box(buf, mdia, b"hdlr")
        if hdlr_b - hdlr_a < 12:
            raise ValueError("Truncated 'hdlr' box")
        handler_type = buf[hdlr_a + 8 : hdlr_a + 12]
        minf = find_one_box(buf, mdia, b"minf")
        stbl = find_one_box(buf, minf, b"stbl")
        stsd_a, stsd_b = find_one_box(buf, stbl, b"stsd")
        entries = list(iter_boxes(buf, stsd_a + 8, stsd_b))

        if handler_type == b"vide":
            if len(entries) != 1 or entries[0][0] not in (b"hvc1", b"hev1", b"avc1", b"avc3"):
                raise ValueError("Expected single hvc1/hev1/avc1/avc3 video sample entry")
            codec_tag, e, ee = entries[0]
            sw, sh = struct.unpack_from(">HH", buf, e + 24)
            children = list(iter_boxes(buf, e + 78, ee)) if ee - e >= 78 else []
            pasp = [struct.unpack_from(">II", buf, u) for k, u, v in children if k == b"pasp" and v - u == 8]
            if sum(k == b"pasp" for k, _, _ in children) != len(pasp) or len(pasp) > 1:
                raise ValueError("Ambiguous 'pasp' box")
            aperture = any(k == b"clap" for k, _, _ in children) or bool(find_boxes(buf, a, b, b"tapt"))
            mdhd_a, mdhd_b = find_one_box(buf, mdia, b"mdhd")
            timescale = _parse_mdhd_timescale(buf, mdhd_a, mdhd_b)
            stts_a, stts_b = find_one_box(buf, stbl, b"stts")
            stts_stats = _parse_stts_stats(buf, stts_a, stts_b, timescale)
            codec_cfg = _parse_codec_config(codec_tag, children, buf)
            info = {
                "track_id": tkhd["track_id"],
                "codec": codec_tag.decode("ascii"),
                "tkhd_width": tkhd["width"],
                "tkhd_height": tkhd["height"],
                "sample_width": sw,
                "sample_height": sh,
                "pixel_aspect": list(pasp[0]) if pasp else None,
                "identity_matrix": tkhd["identity_matrix"],
                "aperture_box": aperture,
                "fps": stts_stats["fps"],
                "fps_exact": stts_stats["fps_exact"],
                "frame_count": stts_stats["frame_count"],
                "duration_sec": stts_stats["duration_sec"],
                "cadence_constant": stts_stats["cadence_constant"],
                "codec_profile_level": codec_cfg["codec_profile_level"],
                "codec_level_idc": codec_cfg["codec_level_idc"],
            }
            edits = [
                (base_off + tkhd_b - 4, struct.pack(">I", 2560 << 16)),
                (base_off + e + 26, struct.pack(">H", 2560)),
            ]
            video_tracks.append((info, edits))
        elif handler_type == b"soun":
            audio_tracks += 1
        elif handler_type == b"meta" or any(t == b"rtmd" for t, _, _ in entries):
            has_rtmd = any(t == b"rtmd" for t, _, _ in entries)
            stsz_a, stsz_b = find_one_box(buf, stbl, b"stsz")
            samples = _parse_stsz(buf, stsz_a, stsz_b)
            cdsc_refs: list[int] = []
            for tref_a, tref_b in find_boxes(buf, a, b, b"tref"):
                for cd_a, cd_b in find_boxes(buf, tref_a, tref_b, b"cdsc"):
                    for off in range(cd_a, cd_b - 3, 4):
                        cdsc_refs.append(struct.unpack_from(">I", buf, off)[0])
            rtmd_tracks.append({
                "track_id": tkhd["track_id"],
                "has_rtmd": has_rtmd,
                "samples": samples,
                "cdsc_refs": cdsc_refs,
            })

    if len(video_tracks) != 1:
        raise ValueError(f"Expected 1 video track, found {len(video_tracks)}")

    vinfo, edits = video_tracks[0]
    w = int(round(vinfo["sample_width"]))
    h = int(round(vinfo["sample_height"]))
    tk_w = int(round(vinfo["tkhd_width"]))
    tk_h = int(round(vinfo["tkhd_height"]))

    expect_open_gate = expect == "open-gate"
    valid_sizes = VALID_OPEN_GATE_SIZES if expect_open_gate else VALID_STOCK_SIZES
    if body and body.lower().startswith("a7iv") and expect_open_gate:
        valid_sizes = {(3840, 2560), (5760, 3840)}

    if tk_w != w or tk_h != h or vinfo["tkhd_width"] != w or vinfo["tkhd_height"] != h:
        issues.append(f"tkhd ({vinfo['tkhd_width']}x{vinfo['tkhd_height']}) != sample entry ({w}x{h})")
    if (w, h) not in valid_sizes:
        issues.append(f"Unexpected dimensions {w}x{h} for mode {expect!r}")
    if not vinfo["identity_matrix"]:
        issues.append("Non-identity tkhd display matrix")
    if vinfo["aperture_box"]:
        issues.append("Aperture box (clap/tapt) present")
    pasp = vinfo["pixel_aspect"]
    if pasp is not None and not (pasp[0] == pasp[1] > 0):
        issues.append(f"Non-square pixel aspect ratio {pasp}")
    if expect_open_gate:
        allowed_fps = ("23.976p", "24.000p", "25.000p", "29.970p")
        if vinfo["fps"] not in allowed_fps:
            issues.append(
                f"Unexpected Open-Gate FPS {vinfo['fps']!r} (expected 23.976p, 24.000p, 25.000p, or 29.970p)"
            )
    else:
        allowed_stock_fps = ("23.976p", "24.000p", "25.000p", "29.970p", "50.000p", "59.940p", "100.000p", "119.880p")
        if vinfo["fps"] not in allowed_stock_fps:
            issues.append(f"Unexpected stock FPS {vinfo['fps']!r}")

    warnings: list[str] = []
    avc_l51_mb_warning = False
    level_idc = vinfo.get("codec_level_idc")
    if (
        vinfo["codec"] in ("avc1", "avc3")
        and (w, h) == (3840, 2560)
        and level_idc is not None
        and level_idc <= 51
    ):
        avc_l51_mb_warning = True
        warnings.append(
            f"AVC L{level_idc / 10:.1f} at 3840x2560 uses 38,400 macroblocks (strict L5.1 limit is 36,864); verify NLE/decoder acceptance."
        )
    if not vinfo.get("cadence_constant", True):
        warnings.append("Variable frame delta detected in stts table; inspect footage for dropped/held frames.")

    g = math.gcd(w, h) if w > 0 and h > 0 else 1
    display_aspect = f"{w // g}:{h // g}" if w > 0 and h > 0 else "unknown"
    if not vinfo["identity_matrix"] or (pasp is not None and pasp[0] != pasp[1]):
        display_aspect = "non-square"

    # Sony PROF / VPRF inspection
    vprf = _parse_vprf_boxes(buf, moov_end)
    if vprf is None:
        vprf_3x2 = False
        issues.append("Missing Sony PROF/VPRF box")
    else:
        vw, vh = vprf["width"], vprf["height"]
        sar = vprf.get("sar", [1, 1])
        vprf_3x2 = (
            (vw, vh) == (w, h)
            and vw * 2 == vh * 3
            and sar in ([1, 1], [0, 0])
        )
        if expect_open_gate and not vprf_3x2:
            issues.append(f"VPRF declares {vw}x{vh} SAR {sar} instead of 3:2 {w}x{h}")

    # NRT XML (embedded + sidecar)
    resolved_xml = xml_path
    if resolved_xml is None and auto_xml:
        resolved_xml = detect_sidecar_xml(mp4_path)

    xml_checks: list[bool] = []
    embedded_xml_text = _extract_embedded_xml(buf, moov_end)
    embedded_xml_info: dict[str, Any] | None = None
    sidecar_xml_info: dict[str, Any] | None = None
    if embedded_xml_text is not None:
        embedded_xml_info = _inspect_xml_text(embedded_xml_text, w, h, expect_open_gate)
        xml_checks.append(embedded_xml_info["ok"])
        issues.extend(f"embedded: {msg}" for msg in embedded_xml_info["issues"])

    if resolved_xml is not None:
        sidecar_xml_info = _inspect_xml_text(resolved_xml.read_text(encoding="utf8"), w, h, expect_open_gate)
        xml_checks.append(sidecar_xml_info["ok"])
        issues.extend(f"sidecar: {msg}" for msg in sidecar_xml_info["issues"])

    xml_3x2: bool | None = all(xml_checks) if xml_checks else None

    # rtmd timed metadata track
    matching_rtmd = [
        r for r in rtmd_tracks
        if r["has_rtmd"] and r["samples"] > 0 and vinfo["track_id"] in r["cdsc_refs"]
    ]
    rtmd_samples = sum(r["samples"] for r in matching_rtmd) if matching_rtmd else sum(r["samples"] for r in rtmd_tracks if r["has_rtmd"])
    rtmd_gyro_present = len(matching_rtmd) >= 1 and rtmd_samples > 0
    if not rtmd_tracks:
        issues.append("Missing rtmd timed-metadata track")
    elif not any(r["has_rtmd"] for r in rtmd_tracks):
        issues.append("Metadata track missing 'rtmd' sample entry")
    elif not any(vinfo["track_id"] in r["cdsc_refs"] for r in rtmd_tracks if r["has_rtmd"]):
        issues.append("rtmd track missing 'cdsc' reference to video track")
    elif rtmd_samples <= 0:
        issues.append("rtmd track has 0 samples in stsz")

    ok = (
        len(issues) == 0
        and (not expect_open_gate or vprf_3x2)
        and (xml_3x2 is not False)
        and rtmd_gyro_present
    )

    file_size_bytes = mp4_path.stat().st_size
    frame_count = int(vinfo.get("frame_count") or 0)
    duration_sec = float(vinfo.get("duration_sec") or 0.0)
    avg_bitrate_mbps = round((file_size_bytes * 8.0) / duration_sec / 1_000_000.0, 2) if duration_sec > 0 else 0.0
    rtmd_rate_ratio = round(rtmd_samples / frame_count, 3) if frame_count > 0 else 0.0

    report = {
        "ok": ok,
        "file": str(mp4_path),
        "body": body or "auto",
        "width": w,
        "height": h,
        "display_aspect": display_aspect,
        "codec": vinfo["codec"],
        "fps": vinfo["fps"],
        "fps_exact": vinfo["fps_exact"],
        "file_size_bytes": file_size_bytes,
        "frame_count": frame_count,
        "duration_sec": duration_sec,
        "avg_bitrate_mbps": avg_bitrate_mbps,
        "cadence_constant": bool(vinfo.get("cadence_constant", True)),
        "codec_profile_level": vinfo.get("codec_profile_level"),
        "codec_level_idc": level_idc,
        "avc_l51_mb_warning": avc_l51_mb_warning,
        "vprf_3x2": vprf_3x2,
        "xml_3x2": xml_3x2,
        "rtmd_gyro_present": rtmd_gyro_present,
        "rtmd_samples": rtmd_samples,
        "rtmd_rate_ratio": rtmd_rate_ratio,
        "audio_tracks": audio_tracks,
        "tkhd_identity_matrix": vinfo["identity_matrix"],
        "pasp": pasp,
        "vprf": vprf,
        "sidecar_xml": str(resolved_xml) if resolved_xml else None,
        "embedded_xml_present": embedded_xml_info is not None,
        "warnings": warnings,
        "issues": issues,
    }
    return report, edits


def inspect_directory(
    clips_dir: Path,
    expect: str = "auto",
    body: str | None = None,
) -> dict[str, Any]:
    """Scan root and immediate subdirectories of clips_dir for Sony MP4 clips."""
    root = clips_dir.resolve(strict=True)
    candidates: list[Path] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_file() and entry.suffix.lower() == ".mp4":
            candidates.append(entry)
        elif entry.is_dir():
            for child in sorted(entry.iterdir(), key=lambda p: p.name.lower()):
                if child.is_file() and child.suffix.lower() == ".mp4":
                    candidates.append(child)

    clips: list[dict[str, Any]] = []
    passed = 0
    failed = 0
    for mp4 in candidates:
        mode = expect
        try:
            if expect == "auto":
                rep, _ = inspect_clip(mp4, expect="open-gate", body=body)
                is_stock_hint = "stock" in mp4.parent.name.lower() or "stock" in mp4.stem.lower()
                if rep["height"] == 2160 or is_stock_hint:
                    mode = "stock"
                    rep, _ = inspect_clip(mp4, expect="stock", body=body)
                else:
                    mode = "open-gate"
            else:
                rep, _ = inspect_clip(mp4, expect=mode, body=body)
            rep_entry = {"expected_mode": mode, **rep}
            clips.append(rep_entry)
            if rep_entry["ok"]:
                passed += 1
            else:
                failed += 1
        except (ValueError, OSError, struct.error, KeyError, ET.ParseError) as err:
            failed += 1
            clips.append({
                "ok": False,
                "expected_mode": mode,
                "file": str(mp4),
                "issues": [str(err)],
                "warnings": [],
            })

    return {
        "ok": failed == 0 and len(clips) > 0,
        "clips_dir": str(root),
        "clips_scanned": len(clips),
        "clips_passed": passed,
        "clips_failed": failed,
        "clips": clips,
    }


# ------------------------------------------------------------ synthetic MP4 builder (for selftest & tests)

def _box(tag: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), tag) + payload


def _fullbox(tag: bytes, version: int, flags: int, payload: bytes) -> bytes:
    return _box(tag, struct.pack(">I", (version << 24) | (flags & 0xFFFFFF)) + payload)


def build_synthetic_xml(
    width: int = 3840,
    height: int = 2560,
    codec: str = "hvc1",
    fps: str = "23.976p",
    aspect_ratio: str | None = None,
) -> str:
    codec_name = "HEVC" if codec.startswith("hvc") else "AVC"
    ar_attr = f' aspectRatio="{aspect_ratio}"' if aspect_ratio is not None else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<NonRealTimeMeta xmlns="urn:schemas-professionalDisc:nonRealTimeMeta:ver.2.20">\n'
        f'  <VideoFormat>\n'
        f'    <VideoFrame videoCodec="{codec_name}_{width}_{height}_H420P@L51" captureFps="{fps}" formatFps="{fps}"/>\n'
        f'    <VideoLayout pixel="{width}" numOfVerticalLine="{height}"{ar_attr}/>\n'
        '  </VideoFormat>\n'
        '</NonRealTimeMeta>\n'
    )


def build_synthetic_mp4(
    width: int = 3840,
    height: int = 2560,
    codec: str = "hvc1",
    timescale: int = 24000,
    sample_delta: int = 1001,
    vprf_width: int | None = None,
    vprf_height: int | None = None,
    include_rtmd: bool = True,
    rtmd_samples: int = 24,
    rtmd_cdsc: bool = True,
    embedded_xml: str | None = None,
    tkhd_height: int | None = None,
    sample_height: int | None = None,
    frame_count: int = 24,
    avcc_level_idc: int | None = None,
    hvcc_level_idc: int | None = None,
    mdat_bytes: int = 64,
) -> bytes:
    """Build a minimal valid ISOBMFF MP4 container for clip checker tests."""
    vw = width if vprf_width is None else vprf_width
    vh = height if vprf_height is None else vprf_height
    tk_h = height if tkhd_height is None else tkhd_height
    sd_h = height if sample_height is None else sample_height

    # tkhd v0 (84 bytes payload)
    tkhd_payload = bytearray(80)
    struct.pack_into(">I", tkhd_payload, 8, 1)  # track_id = 1
    struct.pack_into(">I", tkhd_payload, 16, sample_delta * frame_count)  # duration
    struct.pack_into(">9i", tkhd_payload, 36, *IDENTITY_MATRIX)
    struct.pack_into(">II", tkhd_payload, 72, width << 16, tk_h << 16)
    tkhd = _fullbox(b"tkhd", 0, 3, bytes(tkhd_payload))

    mdhd_payload = struct.pack(">IIIIHH", 0, 0, timescale, sample_delta * frame_count, 0x55C4, 0)
    mdhd = _fullbox(b"mdhd", 0, 0, mdhd_payload)
    hdlr = _fullbox(b"hdlr", 0, 0, struct.pack(">4s4sIII", b"\x00\x00\x00\x00", b"vide", 0, 0, 0) + b"VideoHandler\x00")
    stts = _fullbox(b"stts", 0, 0, struct.pack(">III", 1, frame_count, sample_delta))
    stsz_v = _fullbox(b"stsz", 0, 0, struct.pack(">II", 1024, frame_count))

    # Visual sample entry: 78 bytes header + optional avcC/hvcC + pasp
    vis = bytearray(78)
    struct.pack_into(">H", vis, 14, 1)  # data_reference_index
    struct.pack_into(">HH", vis, 24, width, sd_h)
    struct.pack_into(">II", vis, 28, 0x00480000, 0x00480000)
    struct.pack_into(">H", vis, 40, 1)
    struct.pack_into(">H", vis, 74, 24)
    codec_cfg_box = b""
    if codec in ("avc1", "avc3") and avcc_level_idc is not None:
        avcc_payload = bytes([1, 122, 0, avcc_level_idc & 0xFF, 0xFF, 0xE0, 0])
        codec_cfg_box = _box(b"avcC", avcc_payload)
    elif codec in ("hvc1", "hev1") and hvcc_level_idc is not None:
        hvcc_payload = bytearray(23)
        hvcc_payload[0] = 1
        hvcc_payload[1] = 2  # Main 10
        hvcc_payload[12] = hvcc_level_idc & 0xFF
        codec_cfg_box = _box(b"hvcC", bytes(hvcc_payload))
    pasp = _box(b"pasp", struct.pack(">II", 1, 1))
    sample_entry = _box(codec.encode("ascii"), bytes(vis) + codec_cfg_box + pasp)
    stsd_v = _fullbox(b"stsd", 0, 0, struct.pack(">I", 1) + sample_entry)
    stbl_v = _box(b"stbl", stsd_v + stts + stsz_v)
    minf_v = _box(b"minf", stbl_v)
    mdia_v = _box(b"mdia", mdhd + hdlr + minf_v)
    trak_v = _box(b"trak", tkhd + mdia_v)

    traks = [trak_v]
    if include_rtmd:
        tkhd_m = bytearray(80)
        struct.pack_into(">I", tkhd_m, 8, 2)  # track_id = 2
        struct.pack_into(">9i", tkhd_m, 36, *IDENTITY_MATRIX)
        tkhd_m_box = _fullbox(b"tkhd", 0, 3, bytes(tkhd_m))
        tref_box = _box(b"tref", _box(b"cdsc", struct.pack(">I", 1))) if rtmd_cdsc else b""
        hdlr_m = _fullbox(b"hdlr", 0, 0, struct.pack(">4s4sIII", b"\x00\x00\x00\x00", b"meta", 0, 0, 0) + b"MetaHandler\x00")
        rtmd_entry = _box(b"rtmd", b"\x00" * 8)
        stsd_m = _fullbox(b"stsd", 0, 0, struct.pack(">I", 1) + rtmd_entry)
        stts_m = _fullbox(b"stts", 0, 0, struct.pack(">III", 1, max(rtmd_samples, 1), sample_delta))
        stsz_m = _fullbox(b"stsz", 0, 0, struct.pack(">II", 512, rtmd_samples))
        mdia_m = _box(b"mdia", mdhd + hdlr_m + _box(b"minf", _box(b"stbl", stsd_m + stts_m + stsz_m)))
        traks.append(_box(b"trak", tkhd_m_box + tref_box + mdia_m))

    # Sony uuid/PROF -> VPRF box (44B VPRF payload matching FUN_0020afb4 + FUN_001b8db4)
    vprf_struct = bytearray(40)
    vprf_struct[4:8] = codec.encode("ascii")
    struct.pack_into(">IIII", vprf_struct, 16, 50000000, 50000000, timescale, sample_delta)
    struct.pack_into(">HHHH", vprf_struct, 32, vw, vh, 1, 1)
    vprf_box = _fullbox(b"VPRF", 0, 0, bytes(vprf_struct))
    prof_uuid = _box(b"uuid", SONY_PROF_UUID + struct.pack(">II", 0, 1) + vprf_box)

    meta_box = b""
    if embedded_xml is not None:
        hdlr_xml = _fullbox(b"hdlr", 0, 0, struct.pack(">4s4sIII", b"\x00\x00\x00\x00", b"nrtm", 0, 0, 0) + b"\x00")
        xml_box = _fullbox(b"xml ", 0, 0, embedded_xml.encode("utf8"))
        meta_box = _fullbox(b"meta", 0, 0, hdlr_xml + xml_box)

    ftyp = _box(b"ftyp", b"XAVC\x00\x00\x00\x00XAVCmp42iso2")
    moov = _box(b"moov", b"".join(traks) + prof_uuid + meta_box)
    mdat = _box(b"mdat", b"\x00" * max(0, mdat_bytes))
    return ftyp + moov + mdat


def run_selftest(verbose: bool = True) -> bool:
    """Run in-memory synthetic positive and negative tests across codecs, rates, XML, and rtmd."""
    cases: list[tuple[str, bool, bytes, str | None, str | None]] = [
        (
            "valid_zve1_hvc1_23976p",
            True,
            build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001, embedded_xml=build_synthetic_xml(3840, 2560, "hvc1", "23.976p")),
            build_synthetic_xml(3840, 2560, "hvc1", "23.976p"),
            "zve1",
        ),
        (
            "valid_fx3_avc1_25000p",
            True,
            build_synthetic_mp4(3840, 2560, "avc1", 25000, 1000),
            build_synthetic_xml(3840, 2560, "avc1", "25.000p"),
            "fx3",
        ),
        (
            "valid_zve1_hvc1_29970p",
            True,
            build_synthetic_mp4(3840, 2560, "hvc1", 30000, 1001, hvcc_level_idc=153),
            build_synthetic_xml(3840, 2560, "hvc1", "29.970p"),
            "zve1",
        ),
        (
            "valid_fx3_xavcsi_avc1_l51_warning",
            True,
            build_synthetic_mp4(3840, 2560, "avc1", 24000, 1001, avcc_level_idc=51),
            build_synthetic_xml(3840, 2560, "avc1", "23.976p"),
            "fx3",
        ),
        (
            "valid_a7iv_5760x3840_hvc1",
            True,
            build_synthetic_mp4(5760, 3840, "hvc1", 24000, 1001),
            None,
            "a7iv",
        ),
        (
            "fail_3840x2160_container",
            False,
            build_synthetic_mp4(3840, 2160, "hvc1", 24000, 1001),
            build_synthetic_xml(3840, 2160, "hvc1", "23.976p", aspect_ratio="16:9"),
            "zve1",
        ),
        (
            "fail_squeezed_16_9_xml",
            False,
            build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001),
            build_synthetic_xml(3840, 2560, "hvc1", "23.976p", aspect_ratio="16:9"),
            "s3",
        ),
        (
            "fail_stripped_rtmd",
            False,
            build_synthetic_mp4(3840, 2560, "avc1", 24000, 1001, include_rtmd=False),
            build_synthetic_xml(3840, 2560, "avc1", "23.976p"),
            "fx3",
        ),
        (
            "fail_rtmd_zero_samples",
            False,
            build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001, rtmd_samples=0),
            None,
            "zve1",
        ),
        (
            "fail_vprf_2160_mismatch",
            False,
            build_synthetic_mp4(3840, 2560, "hvc1", 24000, 1001, vprf_width=3840, vprf_height=2160),
            None,
            "zve1",
        ),
    ]

    all_ok = True
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, expected_ok, mp4_bytes, xml_text, body in cases:
            mp4_p = root / f"{name}.MP4"
            mp4_p.write_bytes(mp4_bytes)
            xml_p = None
            if xml_text is not None:
                xml_p = root / f"{name}M01.XML"
                xml_p.write_text(xml_text, encoding="utf8")
            rep, _ = inspect_clip(mp4_p, xml_path=xml_p, expect="open-gate", body=body)
            passed = rep["ok"] is expected_ok
            if name == "valid_fx3_xavcsi_avc1_l51_warning":
                passed = passed and rep.get("avc_l51_mb_warning") is True
            if not passed:
                all_ok = False
            if verbose:
                status = "PASS" if passed else "FAIL"
                print(f"[{status}] {name}: ok={rep['ok']} (expected {expected_ok}) issues={rep['issues']} warnings={rep['warnings']}")
    return all_ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("clip", nargs="?", type=Path, help="Path to Sony MP4 clip (or directory with --batch)")
    ap.add_argument("--xml", type=Path, help="Matching Sony M01.XML sidecar (auto-detected if omitted)")
    ap.add_argument("--expect", choices=("open-gate", "stock", "auto"), default="open-gate")
    ap.add_argument("--batch", action="store_true", help="Scan a directory of MP4 clips")
    ap.add_argument("--body", help="Optional camera body hint (zve1, s3, fx3, a7iv)")
    ap.add_argument("--json", action="store_true", help="Emit clean JSON contract")
    ap.add_argument("--selftest", action="store_true", help="Run synthetic MP4+XML+rtmd self-test")
    args = ap.parse_args(argv)

    if args.selftest:
        ok = run_selftest(verbose=not args.json)
        if args.json:
            print(json.dumps({"ok": ok}))
        return 0 if ok else 1

    if args.clip is None:
        ap.error("clip path is required unless --selftest is specified")

    src = args.clip.resolve(strict=True)
    if args.batch or src.is_dir():
        batch_report = inspect_directory(src, expect=args.expect, body=args.body)
        print(json.dumps(batch_report, indent=2))
        return 0 if batch_report["ok"] else 1

    expect_single = "open-gate" if args.expect == "auto" else args.expect
    xml_path = args.xml.resolve(strict=True) if args.xml else None
    report, _ = inspect_clip(src, xml_path=xml_path, expect=expect_single, body=args.body)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, struct.error, KeyError, ET.ParseError) as err:
        print(json.dumps({"ok": False, "error": str(err)}), file=sys.stderr)
        sys.exit(2)
