#!/usr/bin/env python3
"""Gyroflow & Sony Catalyst readiness diagnostics and 3:2 preset installer."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
PRESET_DIR = REPO_ROOT / "presets" / "gyroflow"
CALIBRATION_PROFILES_PATH = PRESET_DIR / "calibration_profiles.json"
DEFAULT_GYROFLOW_INSTALL_DIR = (
    Path.home() / "Library" / "Application Support" / "Gyroflow" / "lens_profiles" / "OpenGateStudio"
)

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import bionz_clip_check as bcc  # noqa: E402

_BODY_ALIASES: dict[str, str] = {
    "zve1": "zve1_202",
    "zve1_202": "zve1_202",
    "zv-e1": "zve1_202",
    "a7s3": "a7s3_501",
    "a7s3_501": "a7s3_501",
    "a7siii": "a7s3_501",
    "s3": "a7s3_501",
    "ilce-7sm3": "a7s3_501",
    "fx3": "fx3_702",
    "fx3_702": "fx3_702",
    "ilme-fx3": "fx3_702",
    "a7iv": "a7iv_602",
    "a7iv_602": "a7iv_602",
    "ilce-7m4": "a7iv_602",
}

_STANDARD_GYRO_FPS = {"23.976p", "24.000p", "25.000p", "29.970p", "50.000p", "59.940p"}
_DRIFT_ERROR_MS = 100.0


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_calibration_index() -> dict[str, Any]:
    if not CALIBRATION_PROFILES_PATH.is_file():
        return {"profiles": []}
    return json.loads(CALIBRATION_PROFILES_PATH.read_text(encoding="utf8"))


def _normalize_body_id(body: str | None) -> str | None:
    if body is None:
        return None
    cleaned = body.strip().lower()
    if not cleaned or cleaned == "auto":
        return None
    return _BODY_ALIASES.get(cleaned, body.strip())


def _inspect_optional_xml_hints(
    mp4_path: Path,
    xml_path: Path | None,
) -> dict[str, Any]:
    """Inspect embedded and sidecar XML for optional Device, Lens, and SteadyShot hints."""
    hints: dict[str, Any] = {
        "detected_model": None,
        "manual_zero_mm_lens": False,
        "active_steadyshot_detected": False,
        "lens_model": None,
        "focal_length": None,
    }
    xml_texts: list[str] = []
    try:
        _, buf, _, aux_boxes = bcc.read_mp4_metadata_boxes(mp4_path)
        meta_buf = buf + aux_boxes
        embedded = bcc._extract_embedded_xml(meta_buf, len(meta_buf))
        if embedded:
            xml_texts.append(embedded)
    except (ValueError, OSError, struct.error):
        pass

    resolved_xml = xml_path if xml_path is not None else bcc.detect_sidecar_xml(mp4_path)
    if resolved_xml is not None and resolved_xml.is_file():
        try:
            xml_texts.append(resolved_xml.read_text(encoding="utf8"))
        except OSError:
            pass

    for txt in xml_texts:
        try:
            root = ET.fromstring(txt)
        except ET.ParseError:
            continue
        for elem in root.iter():
            tag = elem.tag.split("}")[-1]
            if tag == "Device":
                model = elem.attrib.get("modelName") or elem.attrib.get("model")
                if model:
                    hints["detected_model"] = model
            elif tag == "Lens":
                lmodel = elem.attrib.get("modelName") or elem.attrib.get("model")
                if lmodel:
                    hints["lens_model"] = lmodel
                    if lmodel.strip().lower() in {"unknown", "manual", "none"}:
                        hints["manual_zero_mm_lens"] = True
                fl = elem.attrib.get("focalLength")
                if fl is not None:
                    hints["focal_length"] = fl
                    fl_num_str = fl.lower().replace("mm", "").strip()
                    try:
                        if float(fl_num_str) <= 0.0:
                            hints["manual_zero_mm_lens"] = True
                    except ValueError:
                        pass
            elif tag in ("SteadyShot", "ImageStabilization", "Stabilization"):
                mode = (
                    elem.attrib.get("mode")
                    or elem.attrib.get("value")
                    or elem.attrib.get("status")
                    or (elem.text or "")
                ).strip().lower()
                if "active" in mode:
                    hints["active_steadyshot_detected"] = True
            elif tag == "Item" and elem.attrib.get("name", "").lower() in ("steadyshot", "stabilization"):
                val = (elem.attrib.get("value") or "").strip().lower()
                if "active" in val:
                    hints["active_steadyshot_detected"] = True
    return hints


def list_gyroflow_presets() -> dict[str, Any]:
    """Return available starter Gyroflow 3:2 profiles with SHA-256 and evidence levels."""
    index = _load_calibration_index()
    presets: list[dict[str, Any]] = []
    all_exist = True
    for entry in index.get("profiles", []):
        fname = str(entry.get("filename", ""))
        fpath = PRESET_DIR / fname
        if not fpath.is_file():
            all_exist = False
            continue
        presets.append({
            "filename": fname,
            "body_id": entry["body_id"],
            "camera_model": entry["camera_model"],
            "dimension": entry["dimension"],
            "frame_readout_time_ms": float(entry["frame_readout_time_ms"]),
            "evidence_level": entry["evidence_level"],
            "sha256": _sha256_file(fpath),
        })
    return {
        "ok": len(presets) > 0 and all_exist,
        "preset_dir": str(PRESET_DIR),
        "presets": presets,
    }


def install_gyroflow_presets(
    target_dir: Path | None = None,
    body_id: str | None = None,
    overwrite: bool = True,
) -> dict[str, Any]:
    """Install starter Gyroflow 3:2 lens profiles into target_dir (default macOS Gyroflow folder)."""
    dest_dir = (
        Path(target_dir).expanduser()
        if target_dir is not None
        else DEFAULT_GYROFLOW_INSTALL_DIR
    )
    listing = list_gyroflow_presets()
    presets = listing.get("presets", [])
    norm_body = _normalize_body_id(body_id)
    if norm_body is not None:
        selected = [p for p in presets if p["body_id"] == norm_body]
        if not selected:
            return {
                "ok": False,
                "target_dir": str(dest_dir),
                "installed_count": 0,
                "installed_files": [],
                "error": f"No Gyroflow starter preset found for body_id={body_id!r}",
            }
    else:
        selected = presets

    dest_dir.mkdir(parents=True, exist_ok=True)
    installed_files: list[str] = []
    for preset in selected:
        src = PRESET_DIR / preset["filename"]
        dst = dest_dir / preset["filename"]
        if dst.exists() and not overwrite:
            installed_files.append(str(dst))
            continue
        shutil.copy2(src, dst)
        installed_files.append(str(dst))

    return {
        "ok": len(installed_files) > 0 and listing.get("ok", False),
        "target_dir": str(dest_dir),
        "installed_count": len(installed_files),
        "installed_files": installed_files,
    }


def _build_readout_calibration(
    body_id: str,
    width: int,
    height: int,
    rtmd_hardware_readout_ms: float | None = None,
) -> dict[str, Any]:
    index = _load_calibration_index()
    profiles = {p["body_id"]: p for p in index.get("profiles", [])}
    if body_id in profiles:
        p = profiles[body_id]
        return {
            "body_id": body_id,
            "sensor": p["sensor"],
            "frame_readout_time_ms": float(p["frame_readout_time_ms"]),
            "rtmd_hardware_readout_ms": rtmd_hardware_readout_ms,
            "evidence_level": p["evidence_level"],
            "source_basis": p["line_ratio_basis"],
            "preset_filename": p["filename"],
            "needs_per_lens_calibration": True,
        }
    if body_id == "auto" and (width, height) == (3840, 2560):
        return {
            "body_id": "auto",
            "sensor": "IMX510 (12.1MP Full-Frame shared platform)",
            "frame_readout_time_ms": 10.3,
            "rtmd_hardware_readout_ms": rtmd_hardware_readout_ms,
            "evidence_level": "estimated_from_imx510_line_ratio",
            "source_basis": "8.7 ms * (2832 / 2392 active lines) = 10.30 ms",
            "preset_filename": None,
            "needs_per_lens_calibration": True,
        }
    if body_id == "auto" and (width, height) == (5760, 3840):
        p = profiles.get("a7iv_602", {})
        return {
            "body_id": "a7iv_602",
            "sensor": p.get("sensor", "IMX710 (33MP Full-Frame)"),
            "frame_readout_time_ms": float(p.get("frame_readout_time_ms", 31.8)),
            "rtmd_hardware_readout_ms": rtmd_hardware_readout_ms,
            "evidence_level": p.get("evidence_level", "estimated_from_imx710_line_ratio"),
            "source_basis": p.get("line_ratio_basis", "26.8 ms * (4672 / 3942 active lines) = 31.76 ms"),
            "preset_filename": p.get("filename"),
            "needs_per_lens_calibration": True,
        }
    return {
        "body_id": body_id,
        "sensor": "unknown",
        "frame_readout_time_ms": None,
        "rtmd_hardware_readout_ms": rtmd_hardware_readout_ms,
        "evidence_level": "unverified",
        "source_basis": "No matching sensor readout preset for this body/resolution.",
        "preset_filename": None,
        "needs_per_lens_calibration": True,
    }


def _build_ibis_guidance(active_detected: bool) -> dict[str, Any]:
    return {
        "gyroflow_recommendation": "Set camera SteadyShot OFF and lens OSS OFF so rtmd body gyro has zero unmodeled electronic/IBIS warp.",
        "catalyst_recommendation": "Set camera SteadyShot OFF and lens OSS OFF, and keep native 3:2 MP4 + M01.XML intact (mp4_3x2 pack).",
        "active_steadyshot_warning": (
            "WARNING: Active/Dynamic Active SteadyShot metadata detected — electronic crop/warp fights post gyro solvers."
            if active_detected
            else "Always turn Active / Dynamic Active SteadyShot OFF before shooting clips intended for Gyroflow or Catalyst."
        ),
        "active_steadyshot_detected": active_detected,
        "third_party_lens_checklist": [
            "Confirm E-mount AF lens reports non-zero focal length in M01.XML (manual/0mm lenses require manual profile selection in Gyroflow and fail Catalyst).",
            "Disable lens OSS/VC/OS switch before rolling.",
            "Calibrate a dedicated 3:2 Gyroflow lens profile at your focal length (stock 16:9 profiles do not match 3840x2560 height).",
        ],
        "anamorphic_checklist": [
            "Shoot with mp4_3x2 active and SteadyShot OFF to avoid squeeze/IBIS axis mismatch.",
            "Set Gyroflow input_horizontal_stretch to match your squeeze factor (1.33x / 1.5x / 1.6x / 2.0x) when calibrating and stabilizing.",
            "On FX3, keep De-Squeeze Display off when external hdmi32 monitoring is used to preserve Sony AF.",
        ],
    }


def diagnose_clip_gyro(
    mp4_path: Path,
    xml_path: Path | None = None,
    body: str | None = None,
    expect: str = "open-gate",
) -> dict[str, Any]:
    """Diagnose a Sony MP4/XML clip for Gyroflow and Sony Catalyst 3:2 gyro readiness."""
    mp4 = Path(mp4_path)
    xml_p = Path(xml_path) if xml_path is not None else None

    try:
        clip_report, _ = bcc.inspect_clip(mp4, xml_path=xml_p, expect=expect, body=body)
    except (ValueError, OSError, struct.error, KeyError, ET.ParseError) as err:
        norm_body = _normalize_body_id(body) or "auto"
        return {
            "ok": False,
            "ready_for_gyroflow": False,
            "ready_for_catalyst": False,
            "body_id": norm_body,
            "file": str(mp4),
            "failure_category": "metadata",
            "summary": f"Failed to parse MP4/XML metadata: {err}",
            "checks": [
                {
                    "id": "container_parse",
                    "title": "ISOBMFF / XML Parse",
                    "passed": False,
                    "status": "fail",
                    "detail": str(err),
                }
            ],
            "readout_calibration": _build_readout_calibration(norm_body, 0, 0),
            "ibis_guidance": _build_ibis_guidance(False),
            "recommended_actions": [
                "Verify the file is an untouched Sony camera MP4 (not truncated or corrupted).",
            ],
            "clip_report": {"ok": False, "file": str(mp4), "issues": [str(err)], "warnings": []},
        }

    hints = _inspect_optional_xml_hints(mp4, xml_p)
    w = int(clip_report.get("width") or 0)
    h = int(clip_report.get("height") or 0)

    explicit_body = _normalize_body_id(body)
    inferred_from_xml = _normalize_body_id(hints["detected_model"])
    if explicit_body is not None:
        body_id = explicit_body
    elif inferred_from_xml is not None:
        body_id = inferred_from_xml
    elif (w, h) == (5760, 3840):
        body_id = "a7iv_602"
    else:
        body_id = "auto"

    known_bodies = {"zve1_202", "a7s3_501", "fx3_702", "a7iv_602"}
    unknown_explicit_body = explicit_body is not None and explicit_body not in known_bodies

    # Evaluate condition groups
    geom_issues: list[str] = []
    if clip_report.get("display_aspect") == "non-square" or not clip_report.get("tkhd_identity_matrix", True):
        geom_issues.append("Non-square pixel aspect or non-identity tkhd display matrix")
    if expect == "open-gate":
        if (w, h) not in bcc.VALID_OPEN_GATE_SIZES:
            geom_issues.append(f"Dimensions {w}x{h} are not valid 3:2 open gate")
        if not clip_report.get("vprf_3x2", False):
            geom_issues.append("Sony PROF/VPRF box does not declare 3:2 square-pixel dimensions")
        if clip_report.get("xml_3x2") is False:
            xml_specific = [
                iss
                for iss in clip_report.get("issues", [])
                if "XML" in iss or "VideoLayout" in iss or "VideoFrame" in iss or "Device" in iss
            ]
            if xml_specific:
                geom_issues.extend(xml_specific)
            else:
                geom_issues.append("NRT XML VideoLayout/VideoFrame has 16:9 or mismatched dimensions")
    else:
        if (w, h) not in bcc.VALID_STOCK_SIZES:
            geom_issues.append(f"Dimensions {w}x{h} are not valid stock dimensions")
        if clip_report.get("xml_3x2") is False:
            geom_issues.append("NRT XML mismatches stock dimensions")
    for iss in clip_report.get("issues", []):
        if any(tok in iss for tok in ("tkhd", "Aperture", "pixel aspect")):
            if iss not in geom_issues:
                geom_issues.append(iss)

    meta_issues: list[str] = []
    if not clip_report.get("rtmd_gyro_present", False) or int(clip_report.get("rtmd_samples") or 0) <= 0:
        meta_issues.append("rtmd timed-metadata track missing, unlinked (cdsc), or has 0 samples")
    elif int(clip_report.get("rtmd_timescale") or 0) <= 0:
        meta_issues.append("rtmd track missing valid mdhd timescale")
    if int(clip_report.get("rtmd_zero_size_samples") or 0) > 0:
        meta_issues.append(
            f"rtmd stsz contains {clip_report['rtmd_zero_size_samples']} zero-size sample(s)"
        )
    if clip_report.get("rtmd_gyro_present") and not clip_report.get("rtmd_payload_readable", False):
        meta_issues.append("rtmd stco/co64 offsets are unreadable or outside mdat")
    elif clip_report.get("rtmd_gyro_present") and not clip_report.get("rtmd_klv_detected", False):
        meta_issues.append("rtmd mdat payload missing SMPTE KLV header (06 0e 2b 34)")

    cadence_issues: list[str] = []
    if clip_report.get("rtmd_gyro_present"):
        if not clip_report.get("rtmd_cadence_constant", True):
            cadence_issues.append("Variable rtmd sample delta detected in stts")
        drift_ms = float(clip_report.get("rtmd_timestamp_drift_ms") or 0.0)
        if drift_ms > _DRIFT_ERROR_MS:
            cadence_issues.append(
                f"rtmd duration drifts {drift_ms:.1f} ms from video track (> {_DRIFT_ERROR_MS:.0f} ms)"
            )
        if float(clip_report.get("rtmd_duration_sec") or 0.0) <= 0.0:
            cadence_issues.append("rtmd track duration is 0.0s")
    if not clip_report.get("cadence_constant", True):
        cadence_issues.append("Variable video frame cadence in stts affects gyro alignment")

    lens_issues: list[str] = []
    if hints["manual_zero_mm_lens"]:
        lens_issues.append(
            "Manual or uncommunicative lens detected (0mm/unknown focal length); select/calibrate a Gyroflow lens profile manually"
        )
    if unknown_explicit_body:
        lens_issues.append(
            f"No starter 3:2 readout/lens calibration preset for body={body!r}"
        )

    compat_issues: list[str] = []
    if hints["active_steadyshot_detected"]:
        compat_issues.append(
            "Active/Dynamic Active SteadyShot metadata detected; electronic warp breaks Gyroflow/Catalyst stabilization"
        )
    fps_val = str(clip_report.get("fps") or "unknown")
    if fps_val not in _STANDARD_GYRO_FPS:
        compat_issues.append(f"Frame rate {fps_val!r} is outside supported Gyroflow/Catalyst open-gate rates")
    codec_val = str(clip_report.get("codec") or "")
    level_idc = clip_report.get("codec_level_idc")
    if codec_val in ("avc1", "avc3") and (w, h) == (3840, 2560) and level_idc is not None and level_idc < 51:
        compat_issues.append(f"AVC level {level_idc / 10:.1f} is below L5.1 for 3840x2560")

    # Classify priority: crop_geometry -> metadata -> rtmd_cadence -> lens_profile -> app_compatibility -> none
    if geom_issues:
        failure_category = "crop_geometry"
    elif meta_issues:
        failure_category = "metadata"
    elif cadence_issues:
        failure_category = "rtmd_cadence"
    elif lens_issues:
        failure_category = "lens_profile"
    elif compat_issues:
        failure_category = "app_compatibility"
    else:
        failure_category = "none"

    avc_l51_warn = bool(clip_report.get("avc_l51_mb_warning", False))
    xml_status = clip_report.get("xml_3x2")

    checks = [
        {
            "id": "crop_geometry",
            "title": "3:2 Container, VPRF & XML Geometry",
            "passed": len(geom_issues) == 0,
            "status": "pass" if not geom_issues else "fail",
            "detail": (
                f"{w}x{h} ({clip_report.get('display_aspect')}), vprf_3x2={clip_report.get('vprf_3x2')}, xml_3x2={xml_status}"
                if not geom_issues
                else "; ".join(geom_issues)
            ),
        },
        {
            "id": "rtmd_metadata",
            "title": "rtmd Track, stsz & KLV Payload",
            "passed": len(meta_issues) == 0,
            "status": "pass" if not meta_issues else "fail",
            "detail": (
                f"{clip_report.get('rtmd_samples', 0)} samples, {clip_report.get('rtmd_min_sample_bytes', 0)}-{clip_report.get('rtmd_max_sample_bytes', 0)} B, KLV readable"
                if not meta_issues
                else "; ".join(meta_issues)
            ),
        },
        {
            "id": "rtmd_cadence",
            "title": "rtmd Timescale & Video Sync Cadence",
            "passed": len(cadence_issues) == 0,
            "status": "pass" if not cadence_issues else "fail",
            "detail": (
                f"timescale={clip_report.get('rtmd_timescale', 0)}, fps={clip_report.get('rtmd_fps')}, drift={clip_report.get('rtmd_timestamp_drift_ms', 0.0)} ms"
                if not cadence_issues
                else "; ".join(cadence_issues)
            ),
        },
        {
            "id": "lens_profile",
            "title": "Body Readout & Lens Metadata",
            "passed": len(lens_issues) == 0,
            "status": "pass" if not lens_issues else "fail",
            "detail": (
                f"body={body_id} (starter readout template available; per-lens calibration recommended)"
                if not lens_issues
                else "; ".join(lens_issues)
            ),
        },
        {
            "id": "app_compatibility",
            "title": "Gyroflow & Catalyst App Compatibility",
            "passed": len(compat_issues) == 0,
            "status": "fail" if compat_issues else ("warn" if (avc_l51_warn or xml_status is None) else "pass"),
            "detail": (
                "; ".join(compat_issues)
                if compat_issues
                else (
                    "AVC L5.1 at 3840x2560 exceeds strict 36,864 MB limit (38,400 MBs); verify NLE/Catalyst acceptance."
                    if avc_l51_warn
                    else (
                        "Ready for Gyroflow; M01.XML sidecar missing/unverified for Catalyst Browse."
                        if xml_status is None
                        else f"Compatible ({clip_report.get('codec_profile_level')}, {fps_val})"
                    )
                )
            ),
        },
    ]

    ok = failure_category == "none" and bool(clip_report.get("ok", False))
    ready_for_gyroflow = len(geom_issues) == 0 and len(meta_issues) == 0 and len(cadence_issues) == 0 and len(lens_issues) == 0 and len(compat_issues) == 0
    ready_for_catalyst = (
        ready_for_gyroflow
        and (xml_status is True or expect == "stock")
        and not avc_l51_warn
    )

    actions: list[str] = []
    if geom_issues:
        if any("Device manufacturer='Sony'" in msg or "missing <VideoLayout>" in msg for msg in geom_issues):
            actions.append(
                f"For clips already shot with truncated NRT XML, run: studio_cli.py repair-nrt-xml {mp4.name} --out {mp4.stem}_gyroflow.MP4 --body {body_id} (non-destructive; keeps rtmd intact)."
            )
            actions.append(
                "For future in-camera recordings, apply the updated mp4_3x2 (V19) pack so NRT XML emits <Device manufacturer='Sony'> and <VideoLayout numOfVerticalLine='2560'> directly on-card."
            )
        else:
            actions.append("Re-apply the mp4_3x2 pack before shooting so tkhd/stsd/VPRF and NRT XML declare native 3:2 dimensions.")
    if meta_issues:
        actions.append("Use the untouched camera original .MP4 (ffmpeg remuxing strips the Sony rtmd track).")
    if cadence_issues:
        actions.append("Inspect card write health and verify gyro sync offset manually in Gyroflow.")
    if lens_issues:
        actions.append("Select or checkerboard-calibrate a 3:2 lens profile manually in Gyroflow and enter focal length.")
    if compat_issues:
        actions.append("Disable Active/Dynamic Active SteadyShot and stay within 23.98p / 25p / 29.97p.")
    if not actions:
        actions.append("Install OpenGate Studio starter profiles into Gyroflow and calibrate your specific lens.")
        if avc_l51_warn:
            actions.append("AVC L5.1 (38,400 macroblocks): verify decoder acceptance in Catalyst/NLE before bulk shooting.")
        if xml_status is None and expect == "open-gate":
            actions.append("Keep the matching *M01.XML sidecar beside the MP4 if opening in Sony Catalyst Browse.")

    if ok:
        summary = (
            f"Clip is ready for Gyroflow (3:2 {w}x{h}, {clip_report.get('rtmd_samples')} KLV rtmd samples, "
            f"drift {clip_report.get('rtmd_timestamp_drift_ms')} ms)."
        )
    else:
        primary_msgs = geom_issues or meta_issues or cadence_issues or lens_issues or compat_issues or clip_report.get("issues", [])
        summary = f"[{failure_category}] " + (primary_msgs[0] if primary_msgs else "Gyro readiness check failed.")

    return {
        "ok": ok,
        "ready_for_gyroflow": ready_for_gyroflow,
        "ready_for_catalyst": ready_for_catalyst,
        "body_id": body_id,
        "file": str(mp4),
        "failure_category": failure_category,
        "summary": summary,
        "checks": checks,
        "readout_calibration": _build_readout_calibration(
            body_id,
            w,
            h,
            rtmd_hardware_readout_ms=clip_report.get("rtmd_frame_readout_ms"),
        ),
        "ibis_guidance": _build_ibis_guidance(hints["active_steadyshot_detected"]),
        "recommended_actions": actions,
        "clip_report": clip_report,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_diag = sub.add_parser("diagnose", help="Diagnose clip gyro readiness")
    p_diag.add_argument("mp4_path", type=Path)
    p_diag.add_argument("--xml", type=Path, default=None)
    p_diag.add_argument("--body", default=None)
    p_diag.add_argument("--expect", choices=("open-gate", "stock"), default="open-gate")

    sub.add_parser("list-presets", help="List starter Gyroflow 3:2 lens profiles")

    p_inst = sub.add_parser("install-presets", help="Install starter Gyroflow 3:2 lens profiles")
    p_inst.add_argument("--target-dir", type=Path, default=None)
    p_inst.add_argument("--body", default=None)
    p_inst.add_argument("--no-overwrite", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "diagnose":
        res = diagnose_clip_gyro(args.mp4_path, xml_path=args.xml, body=args.body, expect=args.expect)
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1
    if args.cmd == "list-presets":
        res = list_gyroflow_presets()
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1
    if args.cmd == "install-presets":
        res = install_gyroflow_presets(
            target_dir=args.target_dir,
            body_id=args.body,
            overwrite=not args.no_overwrite,
        )
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
