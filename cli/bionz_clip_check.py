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


def read_mp4_metadata_boxes(path: Path) -> tuple[int, bytes, list[tuple[int, int]], bytes]:
    """Read 'moov' payload, record 'mdat' ranges, and capture top-level metadata boxes without loading 'mdat'."""
    moov_offset: int | None = None
    moov_bytes: bytes | None = None
    mdat_ranges: list[tuple[int, int]] = []
    aux_boxes = bytearray()
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
            payload_start = f.tell()
            payload_len = pos + size - payload_start
            if payload_len < 0 or pos + size > length:
                raise ValueError("Invalid top-level MP4 box length")
            if tag == b"moov":
                if payload_len > 128 * 1024**2:
                    raise ValueError("moov box exceeds 128 MiB limit")
                moov_offset = payload_start
                moov_bytes = f.read(payload_len)
            elif tag in (b"uuid", b"PROF", b"VPRF", b"meta", b"udta", b"xml ") and size <= 32 * 1024**2:
                f.seek(pos, os.SEEK_SET)
                aux_boxes.extend(f.read(size))
            else:
                if tag == b"mdat":
                    mdat_ranges.append((payload_start, pos + size))
                f.seek(payload_len, os.SEEK_CUR)
    if moov_offset is None or moov_bytes is None:
        raise ValueError("Missing 'moov' box")
    return moov_offset, moov_bytes, mdat_ranges, bytes(aux_boxes)


def scan_top_level_boxes(path: Path) -> tuple[int, bytes, list[tuple[int, int]]]:
    """Read 'moov' payload and record top-level 'mdat' payload ranges without loading 'mdat'."""
    moov_offset, moov_bytes, mdat_ranges, _ = read_mp4_metadata_boxes(path)
    return moov_offset, moov_bytes, mdat_ranges


def read_moov_bytes(path: Path) -> tuple[int, bytes]:
    """Read the top-level 'moov' box payload without loading 'mdat'."""
    moov_offset, moov_bytes, _ = scan_top_level_boxes(path)
    return moov_offset, moov_bytes


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
            "exact_duration_sec": 0.0,
            "total_ticks": 0,
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
    exact_duration = (total_ticks / timescale) if timescale > 0 else 0.0
    duration_sec = round(exact_duration, 2)
    return {
        "fps": fps_label,
        "fps_exact": fps_exact,
        "frame_count": total_frames,
        "duration_sec": duration_sec,
        "exact_duration_sec": exact_duration,
        "total_ticks": total_ticks,
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


def _parse_stsz_stats(buf: bytes, a: int, b: int) -> dict[str, Any]:
    if b - a < 12:
        raise ValueError("Truncated 'stsz' box")
    sample_size, sample_count = struct.unpack_from(">II", buf, a + 4)
    if sample_count == 0:
        return {
            "sample_count": 0,
            "nonzero_samples": 0,
            "zero_size_samples": 0,
            "min_sample_bytes": 0,
            "max_sample_bytes": 0,
            "first_nonzero_bytes": 0,
            "sample_sizes": [],
            "truncated": False,
        }
    if sample_size > 0:
        return {
            "sample_count": sample_count,
            "nonzero_samples": sample_count,
            "zero_size_samples": 0,
            "min_sample_bytes": sample_size,
            "max_sample_bytes": sample_size,
            "first_nonzero_bytes": sample_size,
            "sample_sizes": [],
            "truncated": False,
        }
    available = (b - a - 12) // 4
    count_to_read = min(sample_count, available)
    sizes = list(struct.unpack_from(f">{count_to_read}I", buf, a + 12)) if count_to_read > 0 else []
    nonzero = [s for s in sizes if s > 0]
    zero_count = sum(1 for s in sizes if s == 0)
    return {
        "sample_count": sample_count,
        "nonzero_samples": len(nonzero),
        "zero_size_samples": zero_count,
        "min_sample_bytes": min(sizes) if sizes else 0,
        "max_sample_bytes": max(sizes) if sizes else 0,
        "first_nonzero_bytes": nonzero[0] if nonzero else 0,
        "sample_sizes": sizes,
        "truncated": available < sample_count,
    }


def _parse_stsz(buf: bytes, a: int, b: int) -> int:
    return _parse_stsz_stats(buf, a, b)["nonzero_samples"]


def _parse_chunk_offsets(buf: bytes, stbl: tuple[int, int]) -> list[int]:
    """Parse chunk offsets from 'stco' or 'co64' inside 'stbl'."""
    stco_boxes = find_boxes(buf, stbl[0], stbl[1], b"stco")
    if stco_boxes:
        a, b = stco_boxes[0]
        if b - a < 8:
            return []
        (entry_count,) = struct.unpack_from(">I", buf, a + 4)
        avail = (b - a - 8) // 4
        n = min(entry_count, avail)
        return list(struct.unpack_from(f">{n}I", buf, a + 8)) if n > 0 else []
    co64_boxes = find_boxes(buf, stbl[0], stbl[1], b"co64")
    if co64_boxes:
        a, b = co64_boxes[0]
        if b - a < 8:
            return []
        (entry_count,) = struct.unpack_from(">I", buf, a + 4)
        avail = (b - a - 8) // 8
        n = min(entry_count, avail)
        return list(struct.unpack_from(f">{n}Q", buf, a + 8)) if n > 0 else []
    return []


def _parse_stsc_entries(buf: bytes, stbl: tuple[int, int]) -> list[tuple[int, int, int]]:
    stsc_boxes = find_boxes(buf, stbl[0], stbl[1], b"stsc")
    if not stsc_boxes:
        return []
    a, b = stsc_boxes[0]
    if b - a < 8:
        return []
    (entry_count,) = struct.unpack_from(">I", buf, a + 4)
    avail = (b - a - 8) // 12
    n = min(entry_count, avail)
    return [struct.unpack_from(">III", buf, a + 8 + i * 12) for i in range(n)]


def _chunk_first_sample_index(stsc_entries: list[tuple[int, int, int]], chunk_idx_0: int) -> int:
    """Return 0-based sample index for the first sample of 0-based chunk_idx_0."""
    if not stsc_entries:
        return chunk_idx_0
    target_chunk_1 = chunk_idx_0 + 1
    sample_idx = 0
    for i, (first_chunk, samples_per_chunk, _) in enumerate(stsc_entries):
        next_first = stsc_entries[i + 1][0] if i + 1 < len(stsc_entries) else target_chunk_1 + 1
        if target_chunk_1 < next_first:
            sample_idx += max(0, target_chunk_1 - first_chunk) * samples_per_chunk
            return sample_idx
        sample_idx += max(0, next_first - first_chunk) * samples_per_chunk
    return sample_idx


_SMPTE_KLV_PREFIX = b"\x06\x0e\x2b\x34"


def _extract_rtmd_frame_readout_ms(sample0: bytes) -> float | None:
    """Parse Sony rtmd tag 0xe40e (FrameReadoutTime in microseconds -> ms) from sample 0."""
    n = len(sample0)
    pos = sample0.find(_SMPTE_KLV_PREFIX)
    while pos >= 0 and pos + 17 <= n:
        if sample0[pos : pos + 4] != _SMPTE_KLV_PREFIX:
            pos = sample0.find(_SMPTE_KLV_PREFIX, pos + 1)
            continue
        ber = sample0[pos + 16]
        if ber < 0x80:
            ln = ber
            hdr = 17
        else:
            nb = ber & 0x7F
            if nb == 0 or nb > 4 or pos + 17 + nb > n:
                break
            ln = int.from_bytes(sample0[pos + 17 : pos + 17 + nb], "big")
            hdr = 17 + nb
        val_start = pos + hdr
        val_end = min(n, val_start + ln)
        p2 = val_start
        while p2 + 4 <= val_end:
            t, tl = struct.unpack_from(">HH", sample0, p2)
            if tl == 0 or p2 + 4 + tl > val_end:
                break
            if t == 0xE40E and tl == 4:
                (us_val,) = struct.unpack_from(">i", sample0, p2 + 4)
                if us_val > 0:
                    return round(us_val / 1000.0, 3)
            p2 += 4 + tl
        if pos + hdr + ln > n or ln <= 0:
            break
        pos = pos + hdr + ln
    return None


def _probe_rtmd_mdat_packets(
    mp4_path: Path,
    mdat_ranges: list[tuple[int, int]],
    chunk_offsets: list[int],
    stsc_entries: list[tuple[int, int, int]],
    stsz_stats: dict[str, Any],
) -> tuple[bool, bool, float | None]:
    """Bounded-seek probe of up to 5 rtmd chunks inside 'mdat' for readability, KLV, and 0xe40e readout."""
    if not mdat_ranges or not chunk_offsets or stsz_stats["nonzero_samples"] <= 0:
        return False, False, None

    num_chunks = len(chunk_offsets)
    probe_indices = sorted({0, num_chunks // 4, num_chunks // 2, (3 * num_chunks) // 4, num_chunks - 1})
    sample_sizes = stsz_stats["sample_sizes"]
    fallback_size = stsz_stats["first_nonzero_bytes"] or 64

    readable_count = 0
    klv_count = 0
    checked_count = 0
    frame_readout_ms: float | None = None

    with mp4_path.open("rb") as f:
        for cidx in probe_indices:
            offset = chunk_offsets[cidx]
            sidx = _chunk_first_sample_index(stsc_entries, cidx)
            if sample_sizes:
                pkt_size = sample_sizes[sidx] if sidx < len(sample_sizes) else fallback_size
            else:
                pkt_size = fallback_size
            if pkt_size <= 0:
                continue
            checked_count += 1
            read_len = min(pkt_size, 2048 if cidx == 0 else 256)
            min_len = min(pkt_size, 256)
            in_mdat = any(start <= offset and offset + min_len <= end for start, end in mdat_ranges)
            if not in_mdat:
                continue
            f.seek(offset, os.SEEK_SET)
            raw = f.read(read_len)
            if len(raw) < min(pkt_size, 16):
                continue
            readable_count += 1
            # Sony rtmd packets contain SMPTE UL 06 0e 2b 34 (at offset 0 or after a small packet header)
            if _SMPTE_KLV_PREFIX in raw[:128]:
                klv_count += 1
            if cidx == 0 and frame_readout_ms is None:
                frame_readout_ms = _extract_rtmd_frame_readout_ms(raw)

    if checked_count == 0:
        return False, False, None
    return readable_count == checked_count, klv_count > 0, frame_readout_ms


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
    devices = [e.attrib for e in root.iter() if e.tag.split("}")[-1] == "Device"]
    codecs = [e.get("videoCodec") for e in root.iter() if e.get("videoCodec")]
    issues: list[str] = []

    if not layouts:
        issues.append("XML missing <VideoLayout> (NrtMetaWrapper::Init truncated before VideoLayout/Device)")
    if not any(d.get("manufacturer") == "Sony" for d in devices):
        issues.append("XML missing <Device manufacturer='Sony'/> (breaks Gyroflow Sony telemetry auto-detection)")

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

    if frames and all(not f for f in frames):
        issues.append("XML <VideoFrame/> has empty attributes (SetVideoFrame failed)")

    allowed_codec_dims = {(exp_w, exp_h)}
    if expect_open_gate and (exp_w, exp_h) == (3840, 2560):
        allowed_codec_dims.add((3840, 2160))

    for f in frames:
        vc = f.get("videoCodec", "")
        for m in re.finditer(r"(\d{4})[_x](\d{4})", vc):
            if (int(m.group(1)), int(m.group(2))) not in allowed_codec_dims:
                issues.append(f"XML VideoFrame videoCodec={vc!r} mismatches {exp_w}x{exp_h}")

    for c in codecs:
        for m in re.finditer(r"(\d{4})[_x](\d{4})", c):
            if (int(m.group(1)), int(m.group(2))) not in allowed_codec_dims:
                issues.append(f"XML videoCodec={c!r} mismatches {exp_w}x{exp_h}")

    return {
        "ok": len(issues) == 0,
        "layouts": layouts,
        "frames": frames,
        "devices": devices,
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
    base_off, buf, mdat_ranges, aux_boxes = read_mp4_metadata_boxes(mp4_path)
    moov_end = len(buf)
    meta_buf = buf + aux_boxes
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
                "timescale": timescale,
                "fps": stts_stats["fps"],
                "fps_exact": stts_stats["fps_exact"],
                "frame_count": stts_stats["frame_count"],
                "duration_sec": stts_stats["duration_sec"],
                "exact_duration_sec": stts_stats["exact_duration_sec"],
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
            mdhd_boxes = find_boxes(buf, mdia[0], mdia[1], b"mdhd")
            rtmd_timescale = _parse_mdhd_timescale(buf, mdhd_boxes[0][0], mdhd_boxes[0][1]) if mdhd_boxes else 0
            stts_boxes = find_boxes(buf, stbl[0], stbl[1], b"stts")
            rtmd_stts = (
                _parse_stts_stats(buf, stts_boxes[0][0], stts_boxes[0][1], rtmd_timescale)
                if stts_boxes
                else {
                    "fps": "unknown",
                    "fps_exact": "0/1",
                    "frame_count": 0,
                    "duration_sec": 0.0,
                    "exact_duration_sec": 0.0,
                    "total_ticks": 0,
                    "cadence_constant": False,
                }
            )
            stsz_a, stsz_b = find_one_box(buf, stbl, b"stsz")
            stsz_stats = _parse_stsz_stats(buf, stsz_a, stsz_b)
            chunk_offsets = _parse_chunk_offsets(buf, stbl)
            stsc_entries = _parse_stsc_entries(buf, stbl)
            cdsc_refs: list[int] = []
            for tref_a, tref_b in find_boxes(buf, a, b, b"tref"):
                for cd_a, cd_b in find_boxes(buf, tref_a, tref_b, b"cdsc"):
                    for off in range(cd_a, cd_b - 3, 4):
                        cdsc_refs.append(struct.unpack_from(">I", buf, off)[0])
            rtmd_tracks.append({
                "track_id": tkhd["track_id"],
                "has_rtmd": has_rtmd,
                "samples": stsz_stats["nonzero_samples"],
                "stsz_stats": stsz_stats,
                "timescale": rtmd_timescale,
                "stts": rtmd_stts,
                "chunk_offsets": chunk_offsets,
                "stsc_entries": stsc_entries,
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
    vprf = _parse_vprf_boxes(meta_buf, len(meta_buf))
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
    embedded_xml_text = _extract_embedded_xml(meta_buf, len(meta_buf))
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
    rtmd_fallback = [r for r in rtmd_tracks if r["has_rtmd"]]
    primary_rtmd = matching_rtmd[0] if matching_rtmd else (rtmd_fallback[0] if rtmd_fallback else None)

    rtmd_samples = sum(r["samples"] for r in matching_rtmd) if matching_rtmd else sum(r["samples"] for r in rtmd_fallback)
    rtmd_gyro_present = len(matching_rtmd) >= 1 and rtmd_samples > 0

    rtmd_timescale = 0
    rtmd_cadence_constant = False
    rtmd_duration_sec = 0.0
    rtmd_fps = "unknown"
    rtmd_timestamp_drift_ms = 0.0
    rtmd_min_sample_bytes = 0
    rtmd_max_sample_bytes = 0
    rtmd_zero_size_samples = 0
    rtmd_payload_readable = False
    rtmd_klv_detected = False
    rtmd_frame_readout_ms: float | None = None

    if primary_rtmd is not None:
        rtmd_timescale = int(primary_rtmd["timescale"])
        rtmd_stts = primary_rtmd["stts"]
        rtmd_cadence_constant = bool(rtmd_stts["cadence_constant"])
        rtmd_duration_sec = float(rtmd_stts["duration_sec"])
        rtmd_fps = str(rtmd_stts["fps"])
        rtmd_exact_dur = float(rtmd_stts.get("exact_duration_sec") or 0.0)
        video_exact_dur = float(vinfo.get("exact_duration_sec") or 0.0)
        rtmd_timestamp_drift_ms = round(abs(rtmd_exact_dur - video_exact_dur) * 1000.0, 2)
        stsz_s = primary_rtmd["stsz_stats"]
        rtmd_min_sample_bytes = int(stsz_s["min_sample_bytes"])
        rtmd_max_sample_bytes = int(stsz_s["max_sample_bytes"])
        rtmd_zero_size_samples = int(stsz_s["zero_size_samples"])
        if rtmd_samples > 0:
            rtmd_payload_readable, rtmd_klv_detected, rtmd_frame_readout_ms = _probe_rtmd_mdat_packets(
                mp4_path,
                mdat_ranges,
                primary_rtmd["chunk_offsets"],
                primary_rtmd["stsc_entries"],
                stsz_s,
            )

    if not rtmd_tracks:
        issues.append("Missing rtmd timed-metadata track")
    elif not any(r["has_rtmd"] for r in rtmd_tracks):
        issues.append("Metadata track missing 'rtmd' sample entry")
    elif not any(vinfo["track_id"] in r["cdsc_refs"] for r in rtmd_tracks if r["has_rtmd"]):
        issues.append("rtmd track missing 'cdsc' reference to video track")
    elif rtmd_samples <= 0:
        issues.append("rtmd track has 0 samples in stsz")
    else:
        if rtmd_timescale <= 0:
            issues.append("rtmd track has invalid or missing mdhd timescale")
        if rtmd_zero_size_samples > 0:
            issues.append(f"rtmd track has {rtmd_zero_size_samples} zero-size sample(s) in stsz")
        if not rtmd_payload_readable:
            issues.append("rtmd payload offsets in stco/co64 are unreadable or outside mdat")
        elif not rtmd_klv_detected:
            issues.append("rtmd mdat payload missing SMPTE KLV header (06 0e 2b 34)")
        if rtmd_timestamp_drift_ms > 100.0:
            issues.append(f"rtmd duration drifts {rtmd_timestamp_drift_ms:.1f} ms from video duration")
        if not rtmd_cadence_constant:
            warnings.append("Variable rtmd sample delta detected in stts table; verify gyro sync.")

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
        "rtmd_timescale": rtmd_timescale,
        "rtmd_cadence_constant": rtmd_cadence_constant,
        "rtmd_duration_sec": rtmd_duration_sec,
        "rtmd_fps": rtmd_fps,
        "rtmd_timestamp_drift_ms": rtmd_timestamp_drift_ms,
        "rtmd_min_sample_bytes": rtmd_min_sample_bytes,
        "rtmd_max_sample_bytes": rtmd_max_sample_bytes,
        "rtmd_zero_size_samples": rtmd_zero_size_samples,
        "rtmd_payload_readable": rtmd_payload_readable,
        "rtmd_klv_detected": rtmd_klv_detected,
        "rtmd_frame_readout_ms": rtmd_frame_readout_ms,
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


_REPAIR_BODY_MODEL_NAMES = {
    "zve1": "ZV-E1",
    "zve1_202": "ZV-E1",
    "zv-e1": "ZV-E1",
    "a7s3": "ILCE-7SM3",
    "a7s3_501": "ILCE-7SM3",
    "a7siii": "ILCE-7SM3",
    "s3": "ILCE-7SM3",
    "ilce-7sm3": "ILCE-7SM3",
    "fx3": "ILME-FX3",
    "fx3_702": "ILME-FX3",
    "ilme-fx3": "ILME-FX3",
    "a7iv": "ILCE-7M4",
    "a7iv_602": "ILCE-7M4",
    "ilce-7m4": "ILCE-7M4",
    "a7c": "ILCE-7C",
    "a7c_203": "ILCE-7C",
    "ilce-7c": "ILCE-7C",
    "zve10": "ZV-E10",
    "zve10_203": "ZV-E10",
    "zv-e10": "ZV-E10",
}

_SONY_NRT_FPS_MAP = {
    "23.976p": "23.98p",
    "24.000p": "24p",
    "25.000p": "25p",
    "29.970p": "29.97p",
    "50.000p": "50p",
    "59.940p": "59.94p",
}


def _reconstruct_sony_nrt_xml(
    xml_text: str,
    *,
    width: int,
    height: int,
    codec: str,
    fps_label: str,
    model_name: str,
    expect_open_gate: bool = True,
) -> str:
    """Repair truncated Sony NonRealTimeMeta XML while keeping exact XML namespaces."""
    updated = xml_text.strip("\x00\r\n\t ") + "\n"
    nrt_fps = _SONY_NRT_FPS_MAP.get(fps_label, "23.98p")
    codec_tag = (
        f"HEVC_{width}_2160_M10P@L5HT"
        if codec in ("hvc1", "hev1")
        else f"AVC_{width}_2160_H422P@L51"
    )
    vframe_tag = f'<VideoFrame videoCodec="{codec_tag}" captureFps="{nrt_fps}" formatFps="{nrt_fps}"/>'

    if re.search(r"<VideoFrame\s*/>", updated):
        updated = re.sub(r"<VideoFrame\s*/>", vframe_tag, updated, count=1)

    has_layout = "<VideoLayout" in updated
    vlayout_tag = (
        f'<VideoLayout pixel="{width}" numOfVerticalLine="{height}"/>'
        if expect_open_gate
        else f'<VideoLayout pixel="{width}" numOfVerticalLine="{height}" aspectRatio="16:9"/>'
    )
    if has_layout:
        updated = re.sub(
            r"<VideoLayout\b[^>]*/>",
            vlayout_tag,
            updated,
            count=1,
        )
    elif "</VideoFormat>" in updated:
        updated = updated.replace(
            "</VideoFormat>",
            f"\t{vlayout_tag}\n\t</VideoFormat>",
            1,
        )

    if 'manufacturer="Sony"' not in updated:
        dev_tag = f'<Device manufacturer="Sony" modelName="{model_name}" serialNo="4294967295"/>'
        if "<Lens " in updated:
            updated = updated.replace("<Lens ", f"{dev_tag}\n\t<Lens ", 1)
        elif "<AcquisitionRecord>" in updated:
            updated = updated.replace("<AcquisitionRecord>", f"{dev_tag}\n\t<AcquisitionRecord>", 1)
        elif "</NonRealTimeMeta>" in updated:
            updated = updated.replace("</NonRealTimeMeta>", f"\t{dev_tag}\n</NonRealTimeMeta>", 1)

    return updated


def repair_nrt_xml_copy(
    mp4_path: Path,
    out_mp4_path: Path,
    *,
    body: str | None = None,
    out_xml_path: Path | None = None,
) -> dict[str, Any]:
    """Create a non-destructive copy with repaired trailing meta->xml and sidecar M01.XML."""
    src = Path(mp4_path).resolve(strict=True)
    dst = Path(out_mp4_path).resolve()
    if src == dst:
        raise ValueError("Refusing to overwrite original camera MP4 in place; choose a separate output path.")

    # Inspect video parameters (tolerate truncated XML on input clip)
    _, moov_buf, _, aux_boxes = read_mp4_metadata_boxes(src)
    meta_buf = moov_buf + aux_boxes
    w, h, codec, fps_label = 3840, 2560, "hvc1", "23.976p"
    for tag, a, b in iter_boxes(moov_buf, 0, len(moov_buf)):
        if tag != b"trak":
            continue
        mdia = find_one_box(moov_buf, (a, b), b"mdia")
        hdlr_a, hdlr_b = find_one_box(moov_buf, mdia, b"hdlr")
        if moov_buf[hdlr_a + 8 : hdlr_a + 12] != b"vide":
            continue
        minf = find_one_box(moov_buf, mdia, b"minf")
        stbl = find_one_box(moov_buf, minf, b"stbl")
        stsd_a, stsd_b = find_one_box(moov_buf, stbl, b"stsd")
        entries = list(iter_boxes(moov_buf, stsd_a + 8, stsd_b))
        if entries:
            codec_tag, e, _ = entries[0]
            codec = codec_tag.decode("ascii", "replace")
            w, h = struct.unpack_from(">HH", moov_buf, e + 24)
        mdhd_a, mdhd_b = find_one_box(moov_buf, mdia, b"mdhd")
        timescale = _parse_mdhd_timescale(moov_buf, mdhd_a, mdhd_b)
        stts_a, stts_b = find_one_box(moov_buf, stbl, b"stts")
        fps_label = _parse_stts_stats(moov_buf, stts_a, stts_b, timescale)["fps"]
        break

    # Walk top-level boxes on disk without buffering mdat in RAM
    top_boxes: list[tuple[bytes, int, int]] = []
    with src.open("rb") as f:
        total_len = os.fstat(f.fileno()).st_size
        while f.tell() < total_len:
            pos = f.tell()
            hdr = f.read(8)
            if len(hdr) < 8:
                raise ValueError("Truncated top-level MP4 box")
            sz, typ = struct.unpack(">I4s", hdr)
            if sz == 1:
                (sz,) = struct.unpack(">Q", f.read(8))
            elif sz == 0:
                sz = total_len - pos
            if sz < 8 or pos + sz > total_len:
                raise ValueError(f"Invalid top-level {typ!r} box length ({sz})")
            top_boxes.append((typ, pos, sz))
            f.seek(pos + sz, os.SEEK_SET)

    if not top_boxes or top_boxes[-1][0] != b"meta":
        last_tag = top_boxes[-1][0] if top_boxes else None
        raise ValueError(f"Expected final top-level box to be 'meta', found {last_tag!r}")

    _, meta_off, meta_size = top_boxes[-1]
    with src.open("rb") as f:
        f.seek(meta_off, os.SEEK_SET)
        meta_bytes = f.read(meta_size)

    if len(meta_bytes) < 12:
        raise ValueError("Truncated 'meta' FullBox")
    meta_hdr = meta_bytes[8:12]  # version + flags of 'meta'
    sub_boxes: list[tuple[bytes, int, int]] = []
    pos = 12
    while pos < len(meta_bytes):
        if len(meta_bytes) - pos < 8:
            raise ValueError("Truncated child box inside 'meta'")
        bsz, btyp = struct.unpack_from(">I4s", meta_bytes, pos)
        if bsz < 8 or pos + bsz > len(meta_bytes):
            raise ValueError(f"Invalid child box {btyp!r} inside 'meta'")
        sub_boxes.append((btyp, pos, pos + bsz))
        pos += bsz

    if not sub_boxes or sub_boxes[-1][0] != b"xml ":
        last_sub = sub_boxes[-1][0] if sub_boxes else None
        raise ValueError(f"Expected final sub-box inside 'meta' to be 'xml ', found {last_sub!r}")

    _, xml_start, xml_end = sub_boxes[-1]
    xml_flags = struct.unpack_from(">I", meta_bytes, xml_start + 8)[0]
    embedded_xml = meta_bytes[xml_start + 12 : xml_end].decode("utf8", "replace")

    model_name: str | None = None
    if body:
        model_name = _REPAIR_BODY_MODEL_NAMES.get(body.strip().lower())
    if model_name is None:
        try:
            root_xml = ET.fromstring(embedded_xml.strip("\x00\r\n\t "))
            for el in root_xml.iter():
                if el.tag.split("}")[-1] == "Device":
                    m = el.attrib.get("modelName") or el.attrib.get("model")
                    if m:
                        model_name = m
                        break
        except ET.ParseError:
            pass
    if model_name is None:
        model_name = "ZV-E1"

    expect_open_gate = (w, h) in VALID_OPEN_GATE_SIZES
    repaired_xml = _reconstruct_sony_nrt_xml(
        embedded_xml,
        width=w,
        height=h,
        codec=codec,
        fps_label=fps_label,
        model_name=model_name,
        expect_open_gate=expect_open_gate,
    )
    repaired_xml_bytes = repaired_xml.encode("utf8")
    new_xml_box = struct.pack(">I4sI", 12 + len(repaired_xml_bytes), b"xml ", xml_flags) + repaired_xml_bytes
    new_meta_inner = meta_hdr + meta_bytes[12:xml_start] + new_xml_box
    new_meta_box = struct.pack(">I4s", 8 + len(new_meta_inner), b"meta") + new_meta_inner

    dst.parent.mkdir(parents=True, exist_ok=True)
    src_prefix_hash = hashlib.sha256()
    with src.open("rb") as f_in, dst.open("wb") as f_out:
        remaining = meta_off
        while remaining > 0:
            chunk = f_in.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("Unexpected EOF reading source MP4 prefix")
            src_prefix_hash.update(chunk)
            f_out.write(chunk)
            remaining -= len(chunk)
        f_out.write(new_meta_box)

    # Verify byte-for-byte prefix equality between source and copy up to meta_off
    dst_prefix_hash = hashlib.sha256()
    with dst.open("rb") as f_chk:
        remaining = meta_off
        while remaining > 0:
            chunk = f_chk.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("Unexpected EOF verifying repaired MP4 prefix")
            dst_prefix_hash.update(chunk)
            remaining -= len(chunk)

    prefix_identical = src_prefix_hash.hexdigest() == dst_prefix_hash.hexdigest()
    if not prefix_identical:
        raise ValueError("Prefix verification failed after writing repaired MP4 copy")

    # Sidecar XML (write next to dst by default)
    resolved_out_xml = Path(out_xml_path).resolve() if out_xml_path is not None else (dst.parent / f"{dst.stem}M01.XML")
    resolved_out_xml.parent.mkdir(parents=True, exist_ok=True)
    sidecar_src = detect_sidecar_xml(src)
    if sidecar_src is not None and sidecar_src.is_file():
        sidecar_base = sidecar_src.read_text(encoding="utf8")
    else:
        sidecar_base = repaired_xml
    repaired_sidecar = _reconstruct_sony_nrt_xml(
        sidecar_base,
        width=w,
        height=h,
        codec=codec,
        fps_label=fps_label,
        model_name=model_name,
        expect_open_gate=expect_open_gate,
    )
    resolved_out_xml.write_text(repaired_sidecar, encoding="utf8", newline="\n")

    return {
        "ok": True,
        "source_mp4": str(src),
        "output_mp4": str(dst),
        "output_xml": str(resolved_out_xml),
        "model_name": model_name,
        "dimensions": f"{w}x{h}",
        "meta_offset": meta_off,
        "prefix_bytes": meta_off,
        "prefix_sha256": src_prefix_hash.hexdigest(),
        "prefix_identical": True,
        "device_tag_added": 'manufacturer="Sony"' not in embedded_xml,
        "repaired_xml_bytes": len(repaired_xml_bytes),
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
    manufacturer: str | None = "Sony",
    model_name: str = "ZV-E1",
) -> str:
    codec_name = "HEVC" if codec.startswith("hvc") else "AVC"
    ar_attr = f' aspectRatio="{aspect_ratio}"' if aspect_ratio is not None else ""
    dev_line = (
        f'  <Device manufacturer="{manufacturer}" modelName="{model_name}" serialNo="4294967295"/>\n'
        if manufacturer is not None
        else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<NonRealTimeMeta xmlns="urn:schemas-professionalDisc:nonRealTimeMeta:ver.2.20">\n'
        f'  <VideoFormat>\n'
        f'    <VideoFrame videoCodec="{codec_name}_{width}_{height}_H420P@L51" captureFps="{fps}" formatFps="{fps}"/>\n'
        f'    <VideoLayout pixel="{width}" numOfVerticalLine="{height}"{ar_attr}/>\n'
        '  </VideoFormat>\n'
        f'{dev_line}'
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
    rtmd_sample_bytes: int = 512,
    rtmd_drift_ms: float = 0.0,
    rtmd_variable_cadence: bool = False,
    rtmd_zero_size_samples: int = 0,
    corrupt_rtmd: bool = False,
    rtmd_bad_stco: bool = False,
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
    stsc_v = _fullbox(b"stsc", 0, 0, struct.pack(">IIII", 1, 1, frame_count, 1))

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
    video_mdat = b"\x00" * max(0, mdat_bytes)

    # Build rtmd track metadata & payloads (stco offsets patched once moov size is known)
    rtmd_payload_chunks: list[bytes] = []
    rtmd_rel_offsets: list[int] = []
    if include_rtmd:
        total_video_ticks = max(1, frame_count) * max(1, sample_delta)
        if rtmd_samples > 0:
            g = math.gcd(total_video_ticks, rtmd_samples)
            mul = rtmd_samples // g
            rtmd_timescale = timescale * mul
            rtmd_delta = total_video_ticks // g
            if rtmd_drift_ms != 0.0:
                target_dur = max(0.001, (total_video_ticks / max(timescale, 1)) + (rtmd_drift_ms / 1000.0))
                rtmd_delta = max(1, int(round(target_dur * rtmd_timescale / rtmd_samples)))
            if rtmd_variable_cadence and rtmd_samples >= 2:
                d1 = max(1, rtmd_delta // 2)
                d2 = max(1, rtmd_delta + max(1, (rtmd_delta - d1) // (rtmd_samples - 1)))
                if d1 == d2:
                    d2 = d1 + 100
                stts_m = _fullbox(b"stts", 0, 0, struct.pack(">IIIII", 2, 1, d1, rtmd_samples - 1, d2))
            else:
                stts_m = _fullbox(b"stts", 0, 0, struct.pack(">III", 1, rtmd_samples, rtmd_delta))
            rtmd_dur_ticks = rtmd_samples * rtmd_delta
        else:
            rtmd_timescale = timescale
            rtmd_dur_ticks = 0
            stts_m = _fullbox(b"stts", 0, 0, struct.pack(">I", 0))

        mdhd_m = _fullbox(
            b"mdhd", 0, 0,
            struct.pack(">IIIIHH", 0, 0, rtmd_timescale, rtmd_dur_ticks, 0x55C4, 0),
        )
        tkhd_m = bytearray(80)
        struct.pack_into(">I", tkhd_m, 8, 2)  # track_id = 2
        struct.pack_into(">I", tkhd_m, 16, rtmd_dur_ticks)
        struct.pack_into(">9i", tkhd_m, 36, *IDENTITY_MATRIX)
        tkhd_m_box = _fullbox(b"tkhd", 0, 3, bytes(tkhd_m))
        tref_box = _box(b"tref", _box(b"cdsc", struct.pack(">I", 1))) if rtmd_cdsc else b""
        hdlr_m = _fullbox(b"hdlr", 0, 0, struct.pack(">4s4sIII", b"\x00\x00\x00\x00", b"meta", 0, 0, 0) + b"MetaHandler\x00")
        rtmd_entry = _box(b"rtmd", b"\x00" * 8)
        stsd_m = _fullbox(b"stsd", 0, 0, struct.pack(">I", 1) + rtmd_entry)

        if rtmd_samples > 0 and rtmd_zero_size_samples > 0:
            zero_n = min(rtmd_zero_size_samples, rtmd_samples)
            sample_sizes = [0] * zero_n + [max(0, rtmd_sample_bytes)] * (rtmd_samples - zero_n)
            stsz_m = _fullbox(
                b"stsz", 0, 0,
                struct.pack(f">II{len(sample_sizes)}I", 0, len(sample_sizes), *sample_sizes),
            )
        else:
            sample_sizes = [max(0, rtmd_sample_bytes)] * max(0, rtmd_samples)
            stsz_m = _fullbox(b"stsz", 0, 0, struct.pack(">II", max(0, rtmd_sample_bytes), rtmd_samples))

        cursor = len(video_mdat)
        for sz in sample_sizes:
            rtmd_rel_offsets.append(cursor)
            if sz <= 0:
                continue
            if corrupt_rtmd:
                pkt = (b"\xde\xad\xbe\xef" * ((sz + 3) // 4))[:sz]
            else:
                klv_hdr = _SMPTE_KLV_PREFIX + b"\x02\x53\x01\x01\x0c\x02\x01\x01\x01\x01\x00\x00"
                body_len = max(0, sz - 20)
                pkt = (klv_hdr + struct.pack(">I", body_len) + (b"\x55" * body_len))[:sz]
            rtmd_payload_chunks.append(pkt)
            cursor += len(pkt)

        stsc_m = (
            _fullbox(b"stsc", 0, 0, struct.pack(">IIII", 1, 1, 1, 1))
            if rtmd_samples > 0
            else _fullbox(b"stsc", 0, 0, struct.pack(">I", 0))
        )

    def _assemble_moov(mdat_payload_start: int) -> bytes:
        stco_v = _fullbox(b"stco", 0, 0, struct.pack(">II", 1, mdat_payload_start))
        stbl_v = _box(b"stbl", stsd_v + stts + stsz_v + stsc_v + stco_v)
        minf_v = _box(b"minf", stbl_v)
        mdia_v = _box(b"mdia", mdhd + hdlr + minf_v)
        trak_v = _box(b"trak", tkhd + mdia_v)
        traks = [trak_v]
        if include_rtmd:
            if rtmd_samples > 0:
                abs_offsets = [
                    0x7FFFFFFF if rtmd_bad_stco else (mdat_payload_start + rel_off)
                    for rel_off in rtmd_rel_offsets
                ]
                stco_m = _fullbox(
                    b"stco", 0, 0,
                    struct.pack(f">I{len(abs_offsets)}I", len(abs_offsets), *abs_offsets),
                )
            else:
                stco_m = _fullbox(b"stco", 0, 0, struct.pack(">I", 0))
            stbl_m = _box(b"stbl", stsd_m + stts_m + stsz_m + stsc_m + stco_m)
            mdia_m = _box(b"mdia", mdhd_m + hdlr_m + _box(b"minf", stbl_m))
            traks.append(_box(b"trak", tkhd_m_box + tref_box + mdia_m))
        return _box(b"moov", b"".join(traks) + prof_uuid + meta_box)

    moov_placeholder = _assemble_moov(0)
    mdat_payload_start = len(ftyp) + len(moov_placeholder) + 8
    moov = _assemble_moov(mdat_payload_start)
    mdat = _box(b"mdat", video_mdat + b"".join(rtmd_payload_chunks))
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
