#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware conformance bundle auditor and calibration patch exporter for OpenGate Studio."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
KITS_DIR = REPO_ROOT / "kits"
SUPPORT_MATRIX_PATH = REPO_ROOT / "docs" / "support_matrix.json"
CALIBRATION_PROFILES_PATH = REPO_ROOT / "presets" / "gyroflow" / "calibration_profiles.json"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import studio_creator  # noqa: E402
import studio_gyro  # noqa: E402

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

# Historical release kit manifest SHA-256 digests accepted when auditing live USB
# sessions captured prior to an incremental helper rebuild (for example v0.1.3-alpha
# 417b28a before L3-nrt-vline moved into NrtMetaWrapper::Init).
_HISTORICAL_STUDIO_MANIFEST_SHA256: dict[str, set[str]] = {
    "zve1_202": {
        "ad79834c3628d9ca3c42d3327968f8ae0b3c77ca29aca34bb2fd4a21dc3a1133",
    },
    "a7s3_501": {
        "d6ea99fedc6e35fa0868d1c924977085e883a97112726e0c118c844ec1fe18e9",
    },
    "fx3_702": {
        "4a4f1eeb51662dee8a2431eb7a07bd12a01757e4d1a80ac3051ee935e4e1d41f",
    },
}

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
    "a7c": "a7c_203",
    "a7c_203": "a7c_203",
    "ilce-7c": "a7c_203",
    "zve10": "zve10_203",
    "zve10_203": "zve10_203",
    "zv-e10": "zve10_203",
}

_FPS_TOKEN_MAP: dict[str, set[str]] = {
    "23.98p": {"23.976p", "24.000p"},
    "23.976p": {"23.976p", "24.000p"},
    "24p": {"23.976p", "24.000p"},
    "25p": {"25.000p"},
    "25p (pal)": {"25.000p"},
    "25.000p": {"25.000p"},
    "29.97p": {"29.970p"},
    "29.970p": {"29.970p"},
    "30p": {"29.970p"},
}

_SENSITIVE_SESSION_KEYS = {
    "serial",
    "serial_number",
    "serial_sha256",
    "boot_nonce",
    "ct6_session",
    "kernel_command_line",
}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_short_commit() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=3,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def _load_support_matrix() -> dict[str, Any]:
    return json.loads(SUPPORT_MATRIX_PATH.read_text(encoding="utf8"))


def _load_kit_manifest(body_id: str) -> tuple[Path | None, dict[str, Any] | None, str | None]:
    kit_dir = KITS_DIR / body_id
    man_path = kit_dir / "manifest.json"
    if not kit_dir.is_dir() or not man_path.is_file():
        return None, None, None
    man = json.loads(man_path.read_text(encoding="utf8"))
    return kit_dir, man, _sha256_file(man_path)


def normalize_body_id(body_id: str) -> str:
    cleaned = body_id.strip().lower()
    if not cleaned:
        raise ValueError("body_id cannot be empty")
    norm = _BODY_ALIASES.get(cleaned, body_id.strip())
    matrix = _load_support_matrix()
    known_bodies = set(matrix.get("bodies", {}).keys()) | {"a7iv_602"}
    if norm not in known_bodies:
        raise ValueError(f"Unknown body_id {body_id!r}; expected one of {sorted(known_bodies)}")
    return norm


def _redact_session_summary(rec: dict[str, Any], *, accepted: bool, reason: str) -> dict[str, Any]:
    cam_id = rec.get("camera_identity") if isinstance(rec.get("camera_identity"), dict) else {}
    redacted_cam = {
        "device_info_sha256": cam_id.get("device_info_sha256"),
        "msc_usb_id": cam_id.get("msc_usb_id"),
        "service_usb_id": cam_id.get("service_usb_id"),
        "serial_redacted": True,
    }
    return {
        "session_id": str(rec.get("session_id") or "<unknown>"),
        "kind": str(rec.get("kind") or "unknown"),
        "mode": str(rec.get("mode") or "mock"),
        "state": str(rec.get("state") or "unknown"),
        "ready": bool(rec.get("ready", False)),
        "verified": bool(rec.get("verified", False)),
        "pins_ok": bool(rec.get("pins_ok", False)),
        "active_packs": [str(p) for p in (rec.get("active_packs") or [])],
        "steps_run": [str(s) for s in (rec.get("steps_run") or [])],
        "accepted_as_hardware_proof": accepted,
        "validation_reason": reason,
        "camera_identity": redacted_cam if cam_id else None,
        "raw_ct6_excluded": True,
    }


def _validate_live_usb_sessions(
    session_dir: Path | None,
    body_id: str,
    kit_manifest: dict[str, Any] | None,
    manifest_sha256: str | None,
) -> dict[str, Any]:
    if session_dir is None:
        return {
            "session_dir_provided": False,
            "has_verified_live_usb": False,
            "has_verified_live_apply": False,
            "live_usb_sessions_found": 0,
            "verified_live_sessions_count": 0,
            "mock_sessions_rejected": 0,
            "invalid_live_sessions_rejected": 0,
            "verified_active_packs": [],
            "verified_sessions": [],
            "rejected_sessions": [],
            "summary": "No session_dir provided; live USB hardware proof cannot be verified.",
        }

    sdir = Path(session_dir)
    if not sdir.is_dir():
        return {
            "session_dir_provided": True,
            "has_verified_live_usb": False,
            "has_verified_live_apply": False,
            "live_usb_sessions_found": 0,
            "verified_live_sessions_count": 0,
            "mock_sessions_rejected": 0,
            "invalid_live_sessions_rejected": 0,
            "verified_active_packs": [],
            "verified_sessions": [],
            "rejected_sessions": [],
            "summary": f"Session directory does not exist: {sdir}",
        }

    if kit_manifest is None or manifest_sha256 is None:
        return {
            "session_dir_provided": True,
            "has_verified_live_usb": False,
            "has_verified_live_apply": False,
            "live_usb_sessions_found": 0,
            "verified_live_sessions_count": 0,
            "mock_sessions_rejected": 0,
            "invalid_live_sessions_rejected": 0,
            "verified_active_packs": [],
            "verified_sessions": [],
            "rejected_sessions": [],
            "summary": f"No Studio kit manifest for {body_id}; live_usb session verification unavailable.",
        }

    dev_info = kit_manifest.get("device_info")
    want_dev_sha = dev_info.get("sha256") if isinstance(dev_info, dict) else None

    records: list[tuple[float, str, dict[str, Any]]] = []
    # Strictly read session_*.json metadata only; never inspect camera_private/ or CT6_* raw dumps.
    for path in sorted(sdir.glob("session_*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf8"))
        except (OSError, ValueError):
            continue
        if isinstance(raw, dict):
            records.append((float(raw.get("timestamp") or 0.0), path.name, raw))
    records.sort(key=lambda item: (item[0], item[1]), reverse=True)

    verified_sessions: list[dict[str, Any]] = []
    rejected_sessions: list[dict[str, Any]] = []
    verified_active_packs: set[str] = set()
    has_verified_live_apply = False
    live_found = 0
    mock_rejected = 0
    invalid_live_rejected = 0

    for _, _, rec in records:
        rec_body = rec.get("body_id")
        if rec_body != body_id:
            continue

        mode = rec.get("mode") if isinstance(rec.get("mode"), str) and rec.get("mode") else "mock"
        if mode != "live_usb":
            mock_rejected += 1
            rejected_sessions.append(
                _redact_session_summary(
                    rec,
                    accepted=False,
                    reason=f"Rejected mode={mode!r}: mock/non-live sessions are never accepted as hardware proof.",
                )
            )
            continue

        live_found += 1
        kind = rec.get("kind")
        reasons: list[str] = []

        if rec.get("ready") is not True:
            reasons.append("ready is not True")
        if rec.get("verified") is not True:
            reasons.append("verified is not True")
        if rec.get("pins_ok") is not True:
            reasons.append("pins_ok is not True")
        allowed_manifest_shas = {manifest_sha256} | _HISTORICAL_STUDIO_MANIFEST_SHA256.get(body_id, set())
        if rec.get("manifest_sha256") not in allowed_manifest_shas:
            reasons.append("kit manifest_sha256 mismatch or missing")

        if kind in ("preflight", "dump"):
            boot_nonce = rec.get("boot_nonce")
            if not isinstance(boot_nonce, str) or not boot_nonce.strip():
                reasons.append("missing boot_nonce")
            pre_sha = rec.get("preflight_result_sha256")
            if not isinstance(pre_sha, str) or not _HEX64_RE.fullmatch(pre_sha):
                reasons.append("missing or invalid preflight_result_sha256")
            cam_id = rec.get("camera_identity")
            if not isinstance(cam_id, dict):
                reasons.append("missing camera_identity")
            else:
                if not want_dev_sha or cam_id.get("device_info_sha256") != want_dev_sha:
                    reasons.append("camera DeviceInfo.xml SHA-256 mismatch")
                if not (cam_id.get("msc_usb_id") or cam_id.get("service_usb_id")):
                    reasons.append("missing live USB camera identity (msc_usb_id / service_usb_id)")
        elif kind == "closing_dump":
            if rec.get("state") != "applied":
                reasons.append(f"closing_dump state is {rec.get('state')!r}, expected 'applied'")
            if not rec.get("active_packs"):
                reasons.append("closing_dump missing active_packs")
        elif kind == "putback":
            if rec.get("state") != "stock":
                reasons.append(f"putback state is {rec.get('state')!r}, expected 'stock'")
        else:
            reasons.append(f"unsupported live_usb session kind {kind!r}")

        if reasons:
            invalid_live_rejected += 1
            rejected_sessions.append(
                _redact_session_summary(
                    rec,
                    accepted=False,
                    reason="Invalid live_usb session: " + "; ".join(reasons),
                )
            )
            continue

        # Verified live_usb session!
        if kind == "closing_dump":
            has_verified_live_apply = True
            for p in rec.get("active_packs") or []:
                verified_active_packs.add(str(p))

        verified_sessions.append(
            _redact_session_summary(
                rec,
                accepted=True,
                reason=f"Verified live_usb {kind} session ({rec.get('state')})",
            )
        )

    has_verified_live = any(
        s["kind"] in ("preflight", "dump", "closing_dump") for s in verified_sessions
    )

    if has_verified_live:
        summary = (
            f"Verified {len(verified_sessions)} live_usb session(s) for {body_id}"
            + (f" (mock rejected: {mock_rejected})" if mock_rejected else "")
            + "."
        )
    elif mock_rejected > 0:
        summary = (
            f"REJECTED: Found {mock_rejected} mock session(s) and 0 verified live_usb sessions for {body_id}. "
            "Mock sessions never qualify as hardware proof."
        )
    else:
        summary = f"No verified live_usb sessions found for {body_id}."

    return {
        "session_dir_provided": True,
        "has_verified_live_usb": has_verified_live,
        "has_verified_live_apply": has_verified_live_apply,
        "live_usb_sessions_found": live_found,
        "verified_live_sessions_count": len(verified_sessions),
        "mock_sessions_rejected": mock_rejected,
        "invalid_live_sessions_rejected": invalid_live_rejected,
        "verified_active_packs": sorted(verified_active_packs),
        "verified_sessions": verified_sessions,
        "rejected_sessions": rejected_sessions,
        "summary": summary,
    }


def _parse_fps_tokens(fps_field: str) -> set[str]:
    out: set[str] = set()
    for part in fps_field.split("/"):
        tok = part.strip().lower()
        if tok in _FPS_TOKEN_MAP:
            out.update(_FPS_TOKEN_MAP[tok])
    return out


def _entry_matching_clips(
    entry: dict[str, Any],
    passing_og_clips: list[dict[str, Any]],
    verified_active_packs: list[str],
) -> list[dict[str, Any]]:
    row_fps = _parse_fps_tokens(str(entry.get("fps") or ""))
    fps_matches = [c for c in passing_og_clips if c.get("fps") in row_fps]
    if not fps_matches:
        return []

    pack = str(entry.get("pack") or "")
    packs_set = set(verified_active_packs)

    if pack in ("core_open_gate + screen_3x2", "mp4_3x2", "core_open_gate + mp4_3x2"):
        if packs_set:
            if "mp4_3x2" in pack and "mp4_3x2" not in packs_set:
                return []
            if "core_open_gate" in pack and "core_open_gate" not in packs_set:
                return []
        return fps_matches

    if pack == "high_bitrate":
        if packs_set and "high_bitrate" not in packs_set:
            return []
        if not packs_set:
            hb = [c for c in fps_matches if float(c.get("avg_bitrate_mbps") or 0.0) >= 180.0]
            return hb
        return fps_matches

    if pack == "xavc_si":
        if packs_set and "xavc_si" not in packs_set:
            return []
        si_clips = [c for c in fps_matches if str(c.get("codec") or "") in ("avc1", "avc3")]
        return si_clips

    if pack == "fx3_playback":
        if "fx3_playback" not in packs_set:
            return []
        return fps_matches

    # hdmi32 requires external monitor evidence beyond MP4 clip inspection
    return []


def _compute_matrix_recommendations(
    *,
    body_id: str,
    clips: list[dict[str, Any]],
    slots: dict[str, Any],
    session_validation: dict[str, Any],
    gyroflow_ok: bool | None,
    catalyst_ok: bool | None,
    nle_ok: bool | None,
    playback_ok: bool | None,
    thermal_ok: bool | None,
) -> dict[str, Any]:
    matrix = _load_support_matrix()
    entries = [e for e in matrix.get("entries", []) if e.get("body_id") == body_id]

    eligible_promotions: list[dict[str, Any]] = []
    blocked_reasons: list[str] = []

    has_live = bool(session_validation.get("has_verified_live_usb"))
    passing_og = [c for c in clips if c.get("expected_mode") == "open-gate" and c.get("ok")]

    if not has_live:
        blocked_reasons.append(
            "No verified live_usb session for this body (mock sessions are strictly rejected); zero support_matrix.json promotions eligible."
        )
        return {
            "dry_run_only": True,
            "matrix_mutated": False,
            "eligible_promotions": [],
            "blocked_reasons": blocked_reasons,
        }

    if not passing_og:
        blocked_reasons.append(
            "No passing 3:2 open-gate clips in bundle; zero support_matrix.json promotions eligible."
        )
        return {
            "dry_run_only": True,
            "matrix_mutated": False,
            "eligible_promotions": [],
            "blocked_reasons": blocked_reasons,
        }

    verified_packs = list(session_validation.get("verified_active_packs") or [])

    for entry in entries:
        tier = entry.get("tier")
        if tier in ("blocked", "external"):
            continue
        matched = _entry_matching_clips(entry, passing_og, verified_packs)
        if not matched:
            continue

        ev = dict(entry.get("evidence") or {})
        pack = str(entry.get("pack") or "")
        fps_label = str(entry.get("fps") or "")
        codec_label = str(entry.get("codec") or "")

        all_matched_vprf_xml = all(
            c.get("vprf_3x2") is True
            and c.get("xml_3x2") is True
            and c.get("rtmd_gyro_present") is True
            and c.get("rtmd_cadence_constant") is True
            and c.get("rtmd_klv_detected") is True
            and float(c.get("rtmd_timestamp_drift_ms") or 0.0) <= 100.0
            and c.get("untouched_sha256_verified") is True
            for c in matched
        )
        all_matched_gyroflow_ready = all(c.get("ready_for_gyroflow") is True for c in matched)
        all_matched_catalyst_ready = all(c.get("ready_for_catalyst") is True for c in matched)

        proposed_ev = dict(ev)
        row_promos: list[tuple[str, str, str, str]] = []

        def _propose(dim: str, reason: str) -> None:
            cur = ev.get(dim)
            if cur in ("no", "partial"):
                proposed_ev[dim] = "yes"
                row_promos.append((dim, str(cur), "yes", reason))

        if pack != "fx3_playback":
            _propose(
                "hardware_recorded",
                f"Verified live_usb session + {len(matched)} passing open-gate clip(s) at {fps_label}.",
            )
            if all_matched_vprf_xml:
                _propose(
                    "clip_xml_validated",
                    "Untouched MP4 + M01.XML + VPRF 3:2 + rtmd KLV cadence validated.",
                )
            if gyroflow_ok is True and all_matched_gyroflow_ready:
                _propose(
                    "gyroflow_verified",
                    "Operator confirmed Gyroflow stabilization pass on gyro-ready original clip(s).",
                )
            if catalyst_ok is True and all_matched_catalyst_ready:
                _propose(
                    "catalyst_verified",
                    "Operator confirmed Sony Catalyst stabilization pass on MP4 + M01.XML clip(s).",
                )
            if nle_ok is True and all(c.get("vprf_3x2") is True for c in matched):
                _propose(
                    "nle_verified",
                    "Operator confirmed native 3:2 NLE import without ffmpeg remuxing.",
                )

        if playback_ok is True:
            _propose(
                "playback_verified",
                "Operator confirmed clean in-camera playback check.",
            )
        if thermal_ok is True and slots.get("long_take_soak", {}).get("passed") is True:
            _propose(
                "long_take_verified",
                "Operator confirmed sustained thermal/card soak pass.",
            )

        # Check field_ready only when every applicable non-'na' dimension is now 'yes'
        applicable_dims = [
            "byte_verified",
            "emulator_verified",
            "hardware_recorded",
            "clip_xml_validated",
            "gyroflow_verified",
            "catalyst_verified",
            "nle_verified",
            "playback_verified",
            "long_take_verified",
        ]
        if all(proposed_ev.get(d) in ("yes", "na") for d in applicable_dims):
            _propose(
                "field_ready",
                "All applicable conformance dimensions verified on real hardware.",
            )

        for dim, old_v, new_v, reason in row_promos:
            eligible_promotions.append({
                "body_id": body_id,
                "fps": fps_label,
                "codec": codec_label,
                "pack": pack,
                "tier": tier,
                "dimension": dim,
                "from": old_v,
                "to": new_v,
                "reason": reason,
            })

    if not eligible_promotions and not blocked_reasons:
        blocked_reasons.append(
            "No matrix cells changed (matched cells are already 'yes' or pending operator Gyroflow/Catalyst/NLE/Playback/Soak flags)."
        )

    return {
        "dry_run_only": True,
        "matrix_mutated": False,
        "eligible_promotions": eligible_promotions,
        "blocked_reasons": blocked_reasons,
    }


def export_calibration_patch(
    body_id: str,
    fps: str,
    measured_readout_ms: float,
    evidence_note: str,
) -> dict[str, Any]:
    """Build a dry-run calibration patch upgrading calibration_profiles.json to hardware_measured."""
    norm_body = normalize_body_id(body_id)
    fps_clean = fps.strip()
    note_clean = evidence_note.strip()
    if not fps_clean:
        raise ValueError("fps must be non-empty (e.g. '23.976p')")
    if not note_clean:
        raise ValueError("evidence_note must be non-empty")
    ms = float(measured_readout_ms)
    if ms <= 0.0 or ms >= 100.0:
        raise ValueError(f"measured_readout_ms={ms} out of plausible sensor readout bounds (0, 100) ms")

    index = json.loads(CALIBRATION_PROFILES_PATH.read_text(encoding="utf8"))
    profiles = index.get("profiles", [])
    profile = next((p for p in profiles if p.get("body_id") == norm_body), None)
    if profile is None:
        raise ValueError(f"No calibration profile found for body_id={norm_body!r}")

    prev_ms = float(profile["frame_readout_time_ms"])
    prev_level = str(profile["evidence_level"])
    measured_rounded = round(ms, 3)
    delta_ms = round(measured_rounded - prev_ms, 3)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    updated_profile = dict(profile)
    updated_profile["frame_readout_time_ms"] = measured_rounded
    updated_profile["evidence_level"] = "hardware_measured"
    updated_profile["measured_fps"] = fps_clean
    updated_profile["measurement_evidence_note"] = note_clean
    updated_profile["measured_utc"] = now_utc

    preset_patch = {
        "filename": profile["filename"],
        "frame_readout_time": measured_rounded,
        "note": (
            f"HARDWARE_MEASURED readout time ({measured_rounded} ms at {fps_clean}; "
            f"{note_clean}). Zero-distortion starter geometry — pair with per-lens checkerboard calibration."
        ),
        "date": now_utc[:10],
    }

    return {
        "ok": True,
        "schema_version": 1,
        "dry_run_only": True,
        "target_file": "presets/gyroflow/calibration_profiles.json",
        "preset_filename": profile["filename"],
        "body_id": norm_body,
        "camera_model": profile["camera_model"],
        "fps": fps_clean,
        "previous_evidence_level": prev_level,
        "previous_frame_readout_time_ms": prev_ms,
        "new_evidence_level": "hardware_measured",
        "measured_frame_readout_time_ms": measured_rounded,
        "delta_ms": delta_ms,
        "evidence_note": note_clean,
        "measured_utc": now_utc,
        "patch_entry": updated_profile,
        "gyroflow_preset_patch": preset_patch,
    }


def _render_conformance_markdown(manifest: dict[str, Any]) -> str:
    meta = manifest["metadata"]
    sess = manifest["session_validation"]
    slots = manifest["conformance_slots"]
    clips = manifest["clips"]
    matrix_rec = manifest["matrix_recommendations"]
    op_checks = manifest["operator_checks"]

    lines: list[str] = [
        f"# OpenGate Studio Clean-Room Conformance Report — {meta['camera']} (`{meta['body_id']}`)",
        "",
        f"- **Generated (UTC):** `{meta['generated_utc']}`",
        f"- **Commit:** `{meta['git_commit']}`",
        f"- **Firmware Target:** `{meta['firmware']}`",
        f"- **Clean-Room Safeguards:** `serials_redacted={meta['serials_redacted']}`, `raw_ct6_dumps_excluded={meta['raw_ct6_dumps_excluded']}`",
        f"- **Hardware Proof Status:** `{'VERIFIED (live_usb)' if sess['has_verified_live_usb'] else 'UNVERIFIED / MOCK REJECTED'}`",
        "",
        "## 1. Live USB Session Validation",
        "",
        f"- **Summary:** {sess['summary']}",
        f"- **Verified `live_usb` Sessions:** `{sess['verified_live_sessions_count']}` (apply verified: `{sess['has_verified_live_apply']}`)",
        f"- **Mock Sessions Rejected:** `{sess['mock_sessions_rejected']}` | **Invalid `live_usb` Rejected:** `{sess['invalid_live_sessions_rejected']}`",
        "",
    ]

    if sess["verified_sessions"]:
        lines.extend([
            "| Session ID | Kind | Mode | State | Active Packs | Validation |",
            "|---|---|---|---|---|---|",
        ])
        for s in sess["verified_sessions"]:
            packs = ", ".join(s["active_packs"]) or "none"
            lines.append(
                f"| `{s['session_id']}` | `{s['kind']}` | `{s['mode']}` | `{s['state']}` | `{packs}` | {s['validation_reason']} |"
            )
        lines.append("")

    if sess["rejected_sessions"]:
        lines.extend([
            "### Rejected Sessions",
            "",
        ])
        for s in sess["rejected_sessions"]:
            lines.append(f"- `{s['session_id']}` (`{s['mode']}` / `{s['kind']}`): {s['validation_reason']}")
        lines.append("")

    lines.extend([
        "## 2. Conformance Slot Checklist",
        "",
        "| Slot | Status | Detail |",
        "|---|---|---|",
    ])
    for slot_key, slot_val in slots.items():
        status = "PASS" if slot_val["passed"] else ("OPTIONAL/MISSING" if slot_val.get("optional") else "MISSING/FAIL")
        lines.append(f"| `{slot_key}` | **{status}** | {slot_val['detail']} |")
    lines.append("")

    lines.extend([
        "## 3. Untouched Clip & `rtmd` Audit",
        "",
        f"- **Clips Scanned:** `{manifest['clips_scanned']}` | **Passed:** `{manifest['clips_passed']}` | **Failed:** `{manifest['clips_failed']}`",
        "",
    ])
    if clips:
        lines.extend([
            "| Relative Path | Mode | Res | Codec | FPS | VPRF 3:2 | XML 3:2 | rtmd Samples | Drift (ms) | KLV | Gyroflow | Catalyst | MP4 SHA-256 (prefix) | Status |",
            "|---|---|---|---|---|---|---|---:|---:|---|---|---|---|---|",
        ])
        for c in clips:
            sha_short = (c["mp4_sha256"][:16] + "...") if c.get("mp4_sha256") else "none"
            lines.append(
                f"| `{c['relative_path']}` | {c['expected_mode']} | {c['width']}x{c['height']} | "
                f"{c['codec']} | {c['fps']} | {'YES' if c['vprf_3x2'] else 'NO'} | "
                f"{'YES' if c['xml_3x2'] is True else ('NO' if c['xml_3x2'] is False else 'none')} | "
                f"{c['rtmd_samples']} | {c['rtmd_timestamp_drift_ms']} | "
                f"{'YES' if c['rtmd_klv_detected'] else 'NO'} | "
                f"{'READY' if c['ready_for_gyroflow'] else 'NO'} | "
                f"{'READY' if c['ready_for_catalyst'] else 'NO'} | "
                f"`{sha_short}` | {'PASS' if c['ok'] else 'FAIL'} |"
            )
        lines.append("")

    lines.extend([
        "## 4. Operator Verification & Readout Calibration",
        "",
        "| Check | Value |",
        "|---|---|",
        f"| Gyroflow OK | `{op_checks['gyroflow_ok']}` |",
        f"| Catalyst OK | `{op_checks['catalyst_ok']}` |",
        f"| NLE Import OK | `{op_checks['nle_ok']}` |",
        f"| In-Camera Playback OK | `{op_checks['playback_ok']}` |",
        f"| Thermal / Long-Take OK | `{op_checks['thermal_ok']}` |",
        f"| Measured Readout (ms) | `{op_checks['measured_readout_ms']}` |",
        "",
    ])

    cal_patch = manifest.get("calibration_patch")
    if cal_patch:
        lines.extend([
            "### Calibration Patch Export (Dry-Run)",
            "",
            f"- Upgrade `{cal_patch['target_file']}` (`{cal_patch['body_id']}`): "
            f"`{cal_patch['previous_frame_readout_time_ms']} ms` (`{cal_patch['previous_evidence_level']}`) -> "
            f"**`{cal_patch['measured_frame_readout_time_ms']} ms`** (`{cal_patch['new_evidence_level']}`)",
            f"- Note: {cal_patch['evidence_note']}",
            "",
        ])

    lines.extend([
        "## 5. Eligible `docs/support_matrix.json` Promotions (Dry-Run Only)",
        "",
        f"- **Matrix Mutated:** `{matrix_rec['matrix_mutated']}` (dry-run recommendation only)",
        "",
    ])
    if matrix_rec["eligible_promotions"]:
        lines.extend([
            "| FPS | Codec | Pack | Dimension | From | To | Reason |",
            "|---|---|---|---|---|---|---|",
        ])
        for p in matrix_rec["eligible_promotions"]:
            lines.append(
                f"| `{p['fps']}` | {p['codec']} | `{p['pack']}` | `{p['dimension']}` | `{p['from']}` | **`{p['to']}`** | {p['reason']} |"
            )
        lines.append("")
    else:
        lines.append("- No eligible promotions.")
        for reason in matrix_rec["blocked_reasons"]:
            lines.append(f"  - {reason}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def audit_conformance_bundle(
    clips_dir: Path,
    body_id: str,
    session_dir: Path | None = None,
    out_dir: Path | None = None,
    measured_readout_ms: float | None = None,
    gyroflow_ok: bool | None = None,
    catalyst_ok: bool | None = None,
    nle_ok: bool | None = None,
    playback_ok: bool | None = None,
    thermal_ok: bool | None = None,
) -> dict[str, Any]:
    """Audit an untouched camera conformance bundle, validate live_usb sessions, and recommend matrix promotions."""
    norm_body = normalize_body_id(body_id)
    clips_root = Path(clips_dir).resolve(strict=True)
    if not clips_root.is_dir():
        raise NotADirectoryError(f"Not a directory: {clips_root}")

    matrix = _load_support_matrix()
    body_meta = matrix.get("bodies", {}).get(norm_body, {
        "camera": "Sony a7 IV" if norm_body == "a7iv_602" else norm_body,
        "firmware": "6.02" if norm_body == "a7iv_602" else "",
    })
    _, kit_manifest, kit_manifest_sha = _load_kit_manifest(norm_body)

    batch = studio_creator.ingest_card_batch(clips_root, expect="auto", body=norm_body, recursive=True)

    audited_clips: list[dict[str, Any]] = []
    for item in batch.get("clips", []):
        mp4_path = Path(item["file"])
        xml_path = Path(item["sidecar_xml"]) if item.get("sidecar_xml") else None
        expect_mode = str(item.get("expected_mode") or "open-gate")

        sha_before = _sha256_file(mp4_path)
        xml_sha = _sha256_file(xml_path) if (xml_path is not None and xml_path.is_file()) else None
        diag = studio_gyro.diagnose_clip_gyro(mp4_path, xml_path=xml_path, body=norm_body, expect=expect_mode)
        sha_after = _sha256_file(mp4_path)
        untouched_ok = sha_before == sha_after and len(sha_before) == 64

        clip_rep = diag.get("clip_report") or {}
        audited_clips.append({
            "ok": bool(item.get("ok")) and bool(clip_rep.get("ok", False)) and untouched_ok,
            "filename": item["filename"],
            "relative_path": item["relative_path"],
            "expected_mode": expect_mode,
            "width": int(clip_rep.get("width") or item.get("width") or 0),
            "height": int(clip_rep.get("height") or item.get("height") or 0),
            "codec": str(clip_rep.get("codec") or item.get("codec") or "unknown"),
            "codec_profile_level": clip_rep.get("codec_profile_level") or item.get("codec_profile_level"),
            "fps": str(clip_rep.get("fps") or item.get("fps") or "unknown"),
            "duration_sec": float(clip_rep.get("duration_sec") or item.get("duration_sec") or 0.0),
            "avg_bitrate_mbps": float(clip_rep.get("avg_bitrate_mbps") or item.get("avg_bitrate_mbps") or 0.0),
            "cadence_constant": bool(clip_rep.get("cadence_constant", True)),
            "vprf_3x2": bool(clip_rep.get("vprf_3x2", False)),
            "xml_3x2": clip_rep.get("xml_3x2"),
            "sidecar_xml_present": xml_path is not None and xml_path.is_file(),
            "rtmd_gyro_present": bool(clip_rep.get("rtmd_gyro_present", False)),
            "rtmd_samples": int(clip_rep.get("rtmd_samples") or 0),
            "rtmd_timescale": int(clip_rep.get("rtmd_timescale") or 0),
            "rtmd_cadence_constant": bool(clip_rep.get("rtmd_cadence_constant", False)),
            "rtmd_timestamp_drift_ms": float(clip_rep.get("rtmd_timestamp_drift_ms") or 0.0),
            "rtmd_payload_readable": bool(clip_rep.get("rtmd_payload_readable", False)),
            "rtmd_klv_detected": bool(clip_rep.get("rtmd_klv_detected", False)),
            "rtmd_zero_size_samples": int(clip_rep.get("rtmd_zero_size_samples") or 0),
            "ready_for_gyroflow": bool(diag.get("ready_for_gyroflow", False)),
            "ready_for_catalyst": bool(diag.get("ready_for_catalyst", False)),
            "failure_category": str(diag.get("failure_category") or "none"),
            "mp4_sha256": sha_before,
            "sidecar_xml_sha256": xml_sha,
            "untouched_sha256_verified": untouched_ok,
            "issues": list(clip_rep.get("issues") or item.get("issues") or []),
            "warnings": list(clip_rep.get("warnings") or item.get("warnings") or []),
        })

    passing_og = [c for c in audited_clips if c["expected_mode"] == "open-gate" and c["ok"]]
    passing_stock = [c for c in audited_clips if c["expected_mode"] == "stock" and c["ok"]]
    og_2398 = [c for c in passing_og if c["fps"] in ("23.976p", "24.000p")]
    og_2500 = [c for c in passing_og if c["fps"] == "25.000p"]
    og_2997 = [c for c in passing_og if c["fps"] == "29.970p"]

    rtmd_ok = bool(audited_clips) and all(
        c["rtmd_gyro_present"]
        and c["rtmd_cadence_constant"]
        and c["rtmd_payload_readable"]
        and c["rtmd_klv_detected"]
        and c["rtmd_zero_size_samples"] == 0
        and c["rtmd_timestamp_drift_ms"] <= 100.0
        for c in audited_clips
    )
    vprf_xml_ok = bool(passing_og) and all(
        c["vprf_3x2"] and c["sidecar_xml_present"] and c["xml_3x2"] is True
        for c in passing_og
    )
    sha_ok = bool(audited_clips) and all(c["untouched_sha256_verified"] for c in audited_clips)

    soak_clips = [
        c for c in passing_og
        if c["duration_sec"] >= 1800.0 or any(tok in c["relative_path"].lower() for tok in ("soak", "thermal"))
    ]
    soak_passed = bool(thermal_ok is True and (soak_clips or passing_og))

    slots: dict[str, dict[str, Any]] = {
        "open_gate_23_976p": {
            "passed": len(og_2398) > 0,
            "optional": False,
            "count": len(og_2398),
            "detail": f"{len(og_2398)} passing 3:2 clip(s) at 23.976p/24p" if og_2398 else "No passing 23.976p 3:2 open-gate clip",
        },
        "open_gate_25_000p": {
            "passed": len(og_2500) > 0,
            "optional": True,
            "count": len(og_2500),
            "detail": f"{len(og_2500)} passing 3:2 clip(s) at 25.000p" if og_2500 else "No 25.000p open-gate clip in bundle",
        },
        "open_gate_29_970p": {
            "passed": len(og_2997) > 0,
            "optional": True,
            "count": len(og_2997),
            "detail": f"{len(og_2997)} passing 3:2 clip(s) at 29.970p" if og_2997 else "No 29.970p open-gate clip in bundle",
        },
        "stock_baseline": {
            "passed": len(passing_stock) > 0,
            "optional": False,
            "count": len(passing_stock),
            "detail": f"{len(passing_stock)} passing stock 16:9 baseline clip(s)" if passing_stock else "No passing stock 16:9 baseline clip",
        },
        "rtmd_cadence": {
            "passed": rtmd_ok,
            "optional": False,
            "count": sum(1 for c in audited_clips if c["rtmd_klv_detected"]),
            "detail": "All clips have constant rtmd cadence, readable KLV payload, <=100ms drift" if rtmd_ok else "One or more clips missing/invalid rtmd cadence or KLV",
        },
        "vprf_and_xml": {
            "passed": vprf_xml_ok,
            "optional": False,
            "count": sum(1 for c in passing_og if c["vprf_3x2"] and c["xml_3x2"] is True),
            "detail": "All open-gate clips have 3:2 VPRF + paired M01.XML" if vprf_xml_ok else "Missing VPRF 3:2 or paired M01.XML on open-gate clip(s)",
        },
        "untouched_sha256": {
            "passed": sha_ok,
            "optional": False,
            "count": sum(1 for c in audited_clips if c["untouched_sha256_verified"]),
            "detail": f"{len(audited_clips)}/{len(audited_clips)} MP4 SHA-256 hashes verified untouched" if sha_ok else "No clips or SHA-256 verification failed",
        },
        "long_take_soak": {
            "passed": soak_passed,
            "optional": True,
            "count": len(soak_clips),
            "detail": (
                "Thermal/soak confirmed" if soak_passed else "Optional >=30 min thermal soak not yet confirmed"
            ),
        },
    }

    session_validation = _validate_live_usb_sessions(
        session_dir=session_dir,
        body_id=norm_body,
        kit_manifest=kit_manifest,
        manifest_sha256=kit_manifest_sha,
    )

    matrix_recommendations = _compute_matrix_recommendations(
        body_id=norm_body,
        clips=audited_clips,
        slots=slots,
        session_validation=session_validation,
        gyroflow_ok=gyroflow_ok,
        catalyst_ok=catalyst_ok,
        nle_ok=nle_ok,
        playback_ok=playback_ok,
        thermal_ok=thermal_ok,
    )

    calibration_patch: dict[str, Any] | None = None
    if measured_readout_ms is not None:
        fps_for_patch = (
            og_2398[0]["fps"]
            if og_2398
            else (passing_og[0]["fps"] if passing_og else "23.976p")
        )
        calibration_patch = export_calibration_patch(
            body_id=norm_body,
            fps=fps_for_patch,
            measured_readout_ms=measured_readout_ms,
            evidence_note=(
                f"Measured from conformance bundle ({len(passing_og)} passing open-gate clip(s); "
                f"live_usb_verified={session_validation['has_verified_live_usb']})."
            ),
        )

    clips_passed = sum(1 for c in audited_clips if c["ok"])
    clips_failed = len(audited_clips) - clips_passed
    required_slots_ok = all(
        v["passed"] for v in slots.values() if not v.get("optional", False)
    )
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    manifest: dict[str, Any] = {
        "ok": True,
        "schema_version": 1,
        "clean_room": True,
        "metadata": {
            "body_id": norm_body,
            "camera": body_meta.get("camera", norm_body),
            "firmware": body_meta.get("firmware", ""),
            "git_commit": _git_short_commit(),
            "generated_utc": now_utc,
            "serials_redacted": True,
            "raw_ct6_dumps_excluded": True,
        },
        "hardware_proof_ok": bool(session_validation["has_verified_live_usb"]),
        "required_slots_ok": required_slots_ok,
        "conformance_ready": bool(
            session_validation["has_verified_live_usb"]
            and required_slots_ok
            and clips_failed == 0
            and len(audited_clips) > 0
        ),
        "clips_scanned": len(audited_clips),
        "clips_passed": clips_passed,
        "clips_failed": clips_failed,
        "conformance_slots": slots,
        "session_validation": session_validation,
        "operator_checks": {
            "gyroflow_ok": gyroflow_ok,
            "catalyst_ok": catalyst_ok,
            "nle_ok": nle_ok,
            "playback_ok": playback_ok,
            "thermal_ok": thermal_ok,
            "measured_readout_ms": measured_readout_ms,
        },
        "calibration_patch": calibration_patch,
        "matrix_recommendations": matrix_recommendations,
        "clips": audited_clips,
        "report_paths": None,
    }

    if out_dir is not None:
        target_dir = Path(out_dir).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        md_path = target_dir / "CONFORMANCE_REPORT.md"
        manifest_path = target_dir / "conformance_manifest.json"
        def _display_report_path(path: Path) -> str:
            if path.is_relative_to(REPO_ROOT):
                return path.relative_to(REPO_ROOT).as_posix()
            return str(path)

        manifest["report_paths"] = {
            "out_dir": _display_report_path(target_dir),
            "markdown_path": _display_report_path(md_path),
            "manifest_path": _display_report_path(manifest_path),
        }
        md_text = _render_conformance_markdown(manifest)
        md_path.write_text(md_text, encoding="utf8")
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf8")

    return manifest
