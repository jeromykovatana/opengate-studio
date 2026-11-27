#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Creator workflow engine for OpenGate Studio: batch SD-card ingest, delivery crops, and relink-verified proxies."""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import bionz_clip_check as bcc  # noqa: E402

try:
    import studio_gyro  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - fallback when studio_gyro is absent
    studio_gyro = None  # type: ignore[assignment]


DELIVERY_TARGETS: tuple[tuple[str, str, float], ...] = (
    ("16:9", "16:9 Widescreen", 16.0 / 9.0),
    ("1:1", "1:1 Square", 1.0),
    ("9:16", "9:16 Vertical", 9.0 / 16.0),
    ("2.39:1", "2.39:1 Anamorphic Scope", 2.39),
)

PROXY_ASPECT_RATIOS: dict[str, float] = {
    "3:2": 3.0 / 2.0,
    "16:9": 16.0 / 9.0,
    "1:1": 1.0,
    "9:16": 9.0 / 16.0,
    "2.39:1": 2.39,
}

PROXY_RESOLUTION_BASE: dict[str, int] = {
    "720p": 720,
    "1080p": 1080,
    "2160p": 2160,
    "4k": 2160,
}

SUPPORTED_PROXY_CODECS = ("h264", "hevc", "h265", "prores", "prores_proxy", "prores_lt")


def _round_even(value: float, max_val: int) -> int:
    rounded = int(round(value))
    even = rounded - (rounded % 2)
    if even < 2:
        even = 2
    max_even = max_val - (max_val % 2)
    return min(even, max_even if max_even >= 2 else max_val)


def _safe_rect(width: int, height: int, x: int, y: int, scale: float, src_w: int, src_h: int) -> dict[str, Any]:
    sw = _round_even(width * scale, width)
    sh = _round_even(height * scale, height)
    sx = x + (width - sw) // 2
    sy = y + (height - sh) // 2
    return {
        "scale": scale,
        "width": sw,
        "height": sh,
        "x": sx,
        "y": sy,
        "norm_rect": {
            "x": round(sx / src_w, 6),
            "y": round(sy / src_h, 6),
            "width": round(sw / src_w, 6),
            "height": round(sh / src_h, 6),
        },
    }


def compute_delivery_crops(width: int, height: int) -> dict[str, Any]:
    """Compute centered even-pixel crops, normalized rects, and safe areas for a source frame."""
    if width <= 1 or height <= 1:
        raise ValueError(f"Frame dimensions must be >= 2x2, got {width}x{height}")

    src_ar = width / height
    g = math.gcd(width, height)
    crops: dict[str, dict[str, Any]] = {}

    for key, label, target_ar in DELIVERY_TARGETS:
        if src_ar >= target_ar:
            crop_h = height - (height % 2)
            crop_w = _round_even(crop_h * target_ar, width)
        else:
            crop_w = width - (width % 2)
            crop_h = _round_even(crop_w / target_ar, height)

        x = (width - crop_w) // 2
        y = (height - crop_h) // 2

        crops[key] = {
            "aspect": key,
            "label": label,
            "width": crop_w,
            "height": crop_h,
            "x": x,
            "y": y,
            "norm_rect": {
                "x": round(x / width, 6),
                "y": round(y / height, 6),
                "width": round(crop_w / width, 6),
                "height": round(crop_h / height, 6),
            },
            "ffmpeg_crop": f"crop={crop_w}:{crop_h}:{x}:{y}",
            "action_safe": _safe_rect(crop_w, crop_h, x, y, 0.90, width, height),
            "title_safe": _safe_rect(crop_w, crop_h, x, y, 0.80, width, height),
        }

    return {
        "ok": True,
        "source_width": width,
        "source_height": height,
        "source_aspect": f"{width // g}:{height // g}",
        "crops": crops,
        "safe_areas": {
            "action_safe_90": _safe_rect(width, height, 0, 0, 0.90, width, height),
            "title_safe_80": _safe_rect(width, height, 0, 0, 0.80, width, height),
        },
    }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_media_tool(name: str) -> str:
    homebrew = Path(f"/opt/homebrew/bin/{name}")
    if homebrew.is_file() and os.access(homebrew, os.X_OK):
        return str(homebrew)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"Required media tool '{name}' not found at /opt/homebrew/bin/{name} or on PATH")


def _discover_mp4_files(root: Path, recursive: bool) -> list[Path]:
    candidates: list[Path] = []
    if recursive:
        for cur_root, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for fname in sorted(filenames):
                if fname.startswith(".") or fname.startswith("._"):
                    continue
                if fname.lower().endswith(".mp4"):
                    candidates.append(Path(cur_root) / fname)
    else:
        for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith(".") or child.name.startswith("._"):
                continue
            if child.is_file() and child.suffix.lower() == ".mp4":
                candidates.append(child)
    candidates.sort(key=lambda p: p.as_posix().lower())
    return candidates


def _infer_expected_mode(mp4_path: Path, expect: str, body: str | None) -> tuple[str, dict[str, Any]]:
    if expect != "auto":
        rep, _ = bcc.inspect_clip(mp4_path, expect=expect, body=body)
        return expect, rep

    rep, _ = bcc.inspect_clip(mp4_path, expect="open-gate", body=body)
    is_stock_hint = "stock" in mp4_path.parent.name.lower() or "stock" in mp4_path.stem.lower()
    if rep.get("height") == 2160 or is_stock_hint:
        stock_rep, _ = bcc.inspect_clip(mp4_path, expect="stock", body=body)
        return "stock", stock_rep
    return "open-gate", rep


def _fallback_gyro_summary(clip_rep: dict[str, Any]) -> dict[str, Any]:
    rtmd_ok = bool(clip_rep.get("rtmd_gyro_present")) and int(clip_rep.get("rtmd_samples") or 0) > 0
    xml_ok = clip_rep.get("xml_3x2") is not False
    vprf_ok = bool(clip_rep.get("vprf_3x2"))
    ready = bool(clip_rep.get("ok")) and rtmd_ok and xml_ok and vprf_ok
    if not rtmd_ok:
        category = "rtmd_cadence"
    elif not xml_ok or not vprf_ok:
        category = "metadata"
    else:
        category = "none"
    return {
        "available": False,
        "ready_for_gyroflow": ready,
        "ready_for_catalyst": ready,
        "failure_category": category,
        "summary": (
            "Basic rtmd + XML checks passed (studio_gyro unavailable for deep diagnostic)."
            if ready
            else "Fallback gyro check flagged missing rtmd or 3:2 metadata."
        ),
        "readout_calibration": None,
        "recommended_actions": [],
    }


def _run_gyro_diagnostic_safe(
    mp4_path: Path,
    xml_path: Path | None,
    body: str | None,
    expect_mode: str,
    clip_rep: dict[str, Any],
) -> dict[str, Any]:
    diag_fn = getattr(studio_gyro, "diagnose_clip_gyro", None) if studio_gyro is not None else None
    if not callable(diag_fn):
        return _fallback_gyro_summary(clip_rep)

    try:
        diag = diag_fn(mp4_path, xml_path=xml_path, body=body, expect=expect_mode)
        return {
            "available": True,
            "ready_for_gyroflow": bool(diag.get("ready_for_gyroflow", False)),
            "ready_for_catalyst": bool(diag.get("ready_for_catalyst", False)),
            "failure_category": str(diag.get("failure_category") or "none"),
            "summary": str(diag.get("summary") or ""),
            "readout_calibration": diag.get("readout_calibration"),
            "recommended_actions": list(diag.get("recommended_actions") or []),
            "body_id": diag.get("body_id"),
        }
    except Exception as err:
        fallback = _fallback_gyro_summary(clip_rep)
        fallback["summary"] = f"Gyro diagnostic fallback ({err})"
        return fallback


def ingest_card_batch(
    root_dir: Path,
    expect: str = "auto",
    body: str | None = None,
    recursive: bool = True,
) -> dict[str, Any]:
    """Scan an SD-card or folder tree, pair *M01.XML sidecars, and run clip + gyro checks per clip."""
    root = Path(root_dir).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    candidates = _discover_mp4_files(root, recursive=recursive)
    clips: list[dict[str, Any]] = []
    passed = 0
    failed = 0
    gyroflow_ready_count = 0

    for mp4 in candidates:
        rel_path = mp4.relative_to(root).as_posix()
        resolved_xml = bcc.detect_sidecar_xml(mp4)
        mode = expect if expect != "auto" else "open-gate"
        try:
            mode, rep = _infer_expected_mode(mp4, expect, body)
            gyro = _run_gyro_diagnostic_safe(mp4, resolved_xml, body, mode, rep)
            w = int(rep.get("width") or 0)
            h = int(rep.get("height") or 0)
            crops_info = compute_delivery_crops(w, h) if w >= 2 and h >= 2 else None

            clip_ok = bool(rep.get("ok", False))
            if clip_ok:
                passed += 1
            else:
                failed += 1
            if gyro.get("ready_for_gyroflow"):
                gyroflow_ready_count += 1

            clips.append({
                "ok": clip_ok,
                "file": str(mp4),
                "filename": mp4.name,
                "relative_path": rel_path,
                "expected_mode": mode,
                "body": rep.get("body", body or "auto"),
                "sidecar_xml": str(resolved_xml) if resolved_xml else rep.get("sidecar_xml"),
                "width": w,
                "height": h,
                "display_aspect": rep.get("display_aspect", "unknown"),
                "codec": rep.get("codec", "unknown"),
                "codec_profile_level": rep.get("codec_profile_level"),
                "fps": rep.get("fps", "unknown"),
                "duration_sec": rep.get("duration_sec"),
                "avg_bitrate_mbps": rep.get("avg_bitrate_mbps"),
                "cadence_constant": rep.get("cadence_constant"),
                "vprf_3x2": bool(rep.get("vprf_3x2", False)),
                "xml_3x2": rep.get("xml_3x2"),
                "rtmd_gyro_present": bool(rep.get("rtmd_gyro_present", False)),
                "rtmd_samples": int(rep.get("rtmd_samples") or 0),
                "ready_for_gyroflow": gyro["ready_for_gyroflow"],
                "ready_for_catalyst": gyro["ready_for_catalyst"],
                "failure_category": gyro["failure_category"],
                "gyro_summary": gyro["summary"],
                "recommended_actions": gyro["recommended_actions"],
                "delivery_crops": crops_info["crops"] if crops_info else None,
                "warnings": list(rep.get("warnings") or []),
                "issues": list(rep.get("issues") or []),
            })
        except (ValueError, OSError, struct.error, KeyError, ET.ParseError) as err:
            failed += 1
            clips.append({
                "ok": False,
                "file": str(mp4),
                "filename": mp4.name,
                "relative_path": rel_path,
                "expected_mode": mode,
                "body": body or "auto",
                "sidecar_xml": str(resolved_xml) if resolved_xml else None,
                "width": 0,
                "height": 0,
                "display_aspect": "unknown",
                "codec": "unknown",
                "codec_profile_level": None,
                "fps": "unknown",
                "duration_sec": None,
                "avg_bitrate_mbps": None,
                "cadence_constant": None,
                "vprf_3x2": False,
                "xml_3x2": None,
                "rtmd_gyro_present": False,
                "rtmd_samples": 0,
                "ready_for_gyroflow": False,
                "ready_for_catalyst": False,
                "failure_category": "metadata",
                "gyro_summary": f"Failed to inspect clip: {err}",
                "recommended_actions": ["Re-check file integrity or SD card copy."],
                "delivery_crops": None,
                "warnings": [],
                "issues": [str(err)],
            })

    return {
        "ok": True,
        "all_clips_ok": failed == 0 and len(clips) > 0,
        "root_dir": str(root),
        "recursive": recursive,
        "expect": expect,
        "clips_scanned": len(clips),
        "clips_passed": passed,
        "clips_failed": failed,
        "gyroflow_ready_count": gyroflow_ready_count,
        "clips": clips,
    }


def _parse_rate(rate_str: str | None) -> float | None:
    if not rate_str or rate_str in ("0/0", "N/A"):
        return None
    if "/" in rate_str:
        num_s, den_s = rate_str.split("/", 1)
        try:
            num = float(num_s)
            den = float(den_s)
            if den > 0:
                return num / den
        except ValueError:
            return None
    try:
        val = float(rate_str)
        return val if val > 0 else None
    except ValueError:
        return None


def _probe_media(ffprobe_bin: str, media_path: Path) -> dict[str, Any]:
    cmd = [
        ffprobe_bin,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(media_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {media_path}: {proc.stderr.strip() or proc.stdout.strip()}")
    data = json.loads(proc.stdout)
    streams = data.get("streams") or []
    fmt = data.get("format") or {}

    vstream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if vstream is None:
        raise ValueError(f"No video stream found in {media_path}")
    astreams = [s for s in streams if s.get("codec_type") == "audio"]
    dstreams = [s for s in streams if s.get("codec_type") == "data"]

    fps_raw = vstream.get("r_frame_rate") or vstream.get("avg_frame_rate") or "0/0"
    fps_float = _parse_rate(fps_raw)
    dur_raw = vstream.get("duration") or fmt.get("duration")
    duration_sec = float(dur_raw) if dur_raw is not None else None

    vtags = vstream.get("tags") or {}
    ftags = fmt.get("tags") or {}
    timecode = vtags.get("timecode") or ftags.get("timecode")

    audio_channels = sum(int(a.get("channels") or 0) for a in astreams)
    audio_codecs = [str(a.get("codec_name") or "") for a in astreams]

    has_rtmd_stream = any(
        str(d.get("codec_tag_string") or "").lower() == "rtmd"
        or "rtmd" in str(d.get("codec_name") or "").lower()
        for d in dstreams
    )

    return {
        "width": int(vstream.get("width") or 0),
        "height": int(vstream.get("height") or 0),
        "fps_raw": str(fps_raw),
        "fps_float": fps_float,
        "duration_sec": duration_sec,
        "timecode": str(timecode) if timecode else None,
        "audio_stream_count": len(astreams),
        "audio_channels": audio_channels,
        "audio_codecs": audio_codecs,
        "has_rtmd_stream": has_rtmd_stream,
    }


def _compute_proxy_dimensions(aspect: str, resolution: str) -> tuple[int, int]:
    norm_aspect = aspect.strip()
    if norm_aspect not in PROXY_ASPECT_RATIOS:
        raise ValueError(f"Unsupported proxy aspect {aspect!r}; expected one of {sorted(PROXY_ASPECT_RATIOS)}")
    norm_res = resolution.strip().lower()
    if norm_res not in PROXY_RESOLUTION_BASE:
        raise ValueError(f"Unsupported proxy resolution {resolution!r}; expected one of {sorted(PROXY_RESOLUTION_BASE)}")

    base = PROXY_RESOLUTION_BASE[norm_res]
    ar = PROXY_ASPECT_RATIOS[norm_aspect]
    if norm_aspect == "9:16":
        w = base
        h = int(round(w / ar))
    elif norm_aspect == "2.39:1":
        # Treat 720p/1080p/2160p tiers as 1280/1920/3840 wide scope deliverables
        w = {720: 1280, 1080: 1920, 2160: 3840}[base]
        h = int(round(w / ar))
    else:
        h = base
        w = int(round(h * ar))

    w = max(2, w - (w % 2))
    h = max(2, h - (h % 2))
    return w, h


def _build_ffmpeg_command(
    ffmpeg_bin: str,
    src_path: Path,
    dst_path: Path,
    src_probe: dict[str, Any],
    aspect: str,
    out_w: int,
    out_h: int,
    codec: str,
) -> list[str]:
    src_w = src_probe["width"]
    src_h = src_probe["height"]
    vf_parts: list[str] = []
    if aspect != "3:2":
        crop_data = compute_delivery_crops(src_w, src_h)
        vf_parts.append(crop_data["crops"][aspect]["ffmpeg_crop"])
    vf_parts.append(f"scale={out_w}:{out_h}:flags=lanczos")
    vf_parts.append("setsar=1")

    cmd: list[str] = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src_path),
        "-map",
        "0:v:0",
        "-vf",
        ",".join(vf_parts),
    ]

    norm_codec = codec.strip().lower()
    if norm_codec == "h264":
        cmd.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "20"])
    elif norm_codec in ("hevc", "h265"):
        cmd.extend(["-c:v", "libx265", "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-preset", "fast", "-crf", "22"])
    elif norm_codec in ("prores", "prores_proxy"):
        cmd.extend(["-c:v", "prores_ks", "-profile:v", "0", "-pix_fmt", "yuv422p10le"])
    elif norm_codec == "prores_lt":
        cmd.extend(["-c:v", "prores_ks", "-profile:v", "1", "-pix_fmt", "yuv422p10le"])
    else:
        raise ValueError(f"Unsupported proxy codec {codec!r}; expected one of {SUPPORTED_PROXY_CODECS}")

    if src_probe["audio_stream_count"] > 0:
        cmd.extend(["-map", "0:a"])
        is_mov = dst_path.suffix.lower() == ".mov"
        all_aac = all(c == "aac" for c in src_probe["audio_codecs"])
        if is_mov or all_aac:
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])

    cmd.extend(["-map_metadata", "0"])
    if src_probe.get("timecode"):
        tc = src_probe["timecode"]
        cmd.extend(["-timecode", tc, "-metadata", f"timecode={tc}"])

    if dst_path.suffix.lower() == ".mp4":
        cmd.extend(["-movflags", "+faststart"])

    cmd.append(str(dst_path))
    return cmd


def _proxy_filename(src_path: Path, aspect: str, resolution: str, codec: str) -> str:
    aspect_tag = aspect.replace(":", "x").replace(".", "_")
    norm_codec = codec.strip().lower()
    ext = ".mov" if norm_codec.startswith("prores") else ".mp4"
    return f"{src_path.stem}_proxy_{aspect_tag}_{resolution.lower()}{ext}"


def generate_proxies(
    inputs: list[Path],
    out_dir: Path,
    aspect: str = "3:2",
    resolution: str = "1080p",
    codec: str = "h264",
    preserve_gyro_sidecar: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generate relink-safe editing proxies without modifying original camera media."""
    if not inputs:
        raise ValueError("At least one input clip path is required")
    norm_codec = codec.strip().lower()
    if norm_codec not in SUPPORTED_PROXY_CODECS:
        raise ValueError(f"Unsupported proxy codec {codec!r}; expected one of {SUPPORTED_PROXY_CODECS}")

    out_w, out_h = _compute_proxy_dimensions(aspect, resolution)
    ffmpeg_bin = _find_media_tool("ffmpeg")
    ffprobe_bin = _find_media_tool("ffprobe")
    target_dir = Path(out_dir).resolve()
    manifest_path = target_dir / "proxy_manifest.json"

    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0

    for raw_in in inputs:
        src = Path(raw_in).resolve(strict=True)
        out_name = _proxy_filename(src, aspect, resolution, norm_codec)
        dst = (target_dir / out_name).resolve()
        if dst == src:
            raise ValueError(f"Refusing to overwrite original clip: {src}")

        orig_sha_before = _sha256_file(src)
        src_probe = _probe_media(ffprobe_bin, src)
        src_xml = bcc.detect_sidecar_xml(src)
        cmd = _build_ffmpeg_command(ffmpeg_bin, src, dst, src_probe, aspect, out_w, out_h, norm_codec)

        planned_sidecar: Path | None = None
        sidecar_copied = False
        sidecar_note: str | None = None
        if preserve_gyro_sidecar and src_xml is not None:
            if aspect == "3:2":
                planned_sidecar = target_dir / f"{dst.stem}M01.XML"
            else:
                sidecar_note = (
                    f"Skipped copying *M01.XML onto {aspect} cropped proxy to prevent Gyroflow geometry mismatch; "
                    "relink to camera original for stabilization."
                )

        if dry_run:
            succeeded += 1
            items.append({
                "ok": True,
                "dry_run": True,
                "input_file": str(src),
                "output_file": str(dst),
                "target_width": out_w,
                "target_height": out_h,
                "aspect": aspect,
                "resolution": resolution,
                "codec": norm_codec,
                "source_fps": src_probe["fps_raw"],
                "source_timecode": src_probe["timecode"],
                "source_audio_channels": src_probe["audio_channels"],
                "original_sha256": orig_sha_before,
                "sidecar_source": str(src_xml) if src_xml else None,
                "sidecar_copied": False,
                "sidecar_output": str(planned_sidecar) if planned_sidecar else None,
                "sidecar_note": sidecar_note,
                "rtmd_preserved_in_proxy": False,
                "relink_to_original_for_gyro": True,
                "relink_verification": {
                    "fps_match": None,
                    "duration_delta_sec": None,
                    "timecode_match": None,
                    "audio_channels_match": None,
                    "original_sha256_unchanged": True,
                    "relink_ok": None,
                },
                "ffmpeg_cmd": cmd,
            })
            continue

        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        orig_sha_after = _sha256_file(src)
        orig_unchanged = orig_sha_before == orig_sha_after

        if proc.returncode != 0 or not dst.is_file():
            failed += 1
            items.append({
                "ok": False,
                "dry_run": False,
                "input_file": str(src),
                "output_file": str(dst),
                "error": proc.stderr.strip() or proc.stdout.strip() or f"ffmpeg exited with {proc.returncode}",
                "original_sha256": orig_sha_before,
                "rtmd_preserved_in_proxy": False,
                "relink_to_original_for_gyro": True,
                "relink_verification": {
                    "fps_match": False,
                    "duration_delta_sec": None,
                    "timecode_match": False,
                    "audio_channels_match": False,
                    "original_sha256_unchanged": orig_unchanged,
                    "relink_ok": False,
                },
                "ffmpeg_cmd": cmd,
            })
            continue

        if planned_sidecar is not None and src_xml is not None:
            shutil.copy2(src_xml, planned_sidecar)
            sidecar_copied = True

        dst_probe = _probe_media(ffprobe_bin, dst)
        src_fps = src_probe["fps_float"]
        dst_fps = dst_probe["fps_float"]
        fps_match = (
            src_fps is not None
            and dst_fps is not None
            and abs(src_fps - dst_fps) < 0.01
        )

        src_dur = src_probe["duration_sec"]
        dst_dur = dst_probe["duration_sec"]
        if src_dur is not None and dst_dur is not None:
            dur_delta: float | None = round(abs(dst_dur - src_dur), 4)
            dur_ok = dur_delta <= 0.15
        else:
            dur_delta = None
            dur_ok = False

        tc_match = src_probe["timecode"] == dst_probe["timecode"]
        audio_match = src_probe["audio_channels"] == dst_probe["audio_channels"]
        relink_ok = bool(fps_match and dur_ok and tc_match and audio_match and orig_unchanged)

        rtmd_in_proxy = bool(dst_probe["has_rtmd_stream"])
        relink_for_gyro = not rtmd_in_proxy

        item_ok = relink_ok and dst_probe["width"] == out_w and dst_probe["height"] == out_h
        if item_ok:
            succeeded += 1
        else:
            failed += 1

        items.append({
            "ok": item_ok,
            "dry_run": False,
            "input_file": str(src),
            "output_file": str(dst),
            "target_width": dst_probe["width"],
            "target_height": dst_probe["height"],
            "aspect": aspect,
            "resolution": resolution,
            "codec": norm_codec,
            "source_fps": src_probe["fps_raw"],
            "proxy_fps": dst_probe["fps_raw"],
            "source_timecode": src_probe["timecode"],
            "proxy_timecode": dst_probe["timecode"],
            "source_audio_channels": src_probe["audio_channels"],
            "proxy_audio_channels": dst_probe["audio_channels"],
            "original_sha256": orig_sha_before,
            "sidecar_source": str(src_xml) if src_xml else None,
            "sidecar_copied": sidecar_copied,
            "sidecar_output": str(planned_sidecar) if sidecar_copied and planned_sidecar else None,
            "sidecar_note": sidecar_note,
            "rtmd_preserved_in_proxy": rtmd_in_proxy,
            "relink_to_original_for_gyro": relink_for_gyro,
            "relink_verification": {
                "fps_match": fps_match,
                "duration_delta_sec": dur_delta,
                "timecode_match": tc_match,
                "audio_channels_match": audio_match,
                "original_sha256_unchanged": orig_unchanged,
                "relink_ok": relink_ok,
            },
            "ffmpeg_cmd": cmd,
        })

    payload: dict[str, Any] = {
        "ok": failed == 0 and succeeded > 0,
        "dry_run": dry_run,
        "out_dir": str(target_dir),
        "manifest_path": str(manifest_path),
        "aspect": aspect,
        "resolution": resolution,
        "codec": norm_codec,
        "target_width": out_w,
        "target_height": out_h,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_inputs": len(inputs),
        "succeeded_count": succeeded,
        "failed_count": failed,
        "proxies": items,
    }

    if not dry_run:
        manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf8")

    return payload
