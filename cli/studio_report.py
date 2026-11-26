#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Structured field-test and reliability report builder for OpenGate Studio."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import subprocess
from pathlib import Path
from typing import Any

import bionz_clip_check as bcc

REPO_ROOT = Path(__file__).resolve().parent.parent

EVIDENCE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".mov", ".xml", ".webp"}

RECOMMENDED_SAMPLES: list[dict[str, Any]] = [
    {
        "id": "stock_framing_clip",
        "category": "video",
        "title": "Stock 16:9 Framing Baseline (10s Tripod)",
        "purpose": "Proves horizontal FOV matches open gate while top/bottom tape markers sit outside stock 16:9.",
        "filename_hints": ["stock_framing", "A1_stock", "stock"],
    },
    {
        "id": "opengate_framing_clip",
        "category": "video",
        "title": "Open-Gate 3:2 Framing Match (10s Tripod)",
        "purpose": "Matched locked-tripod 3840x2560 take showing upper/lower tape markers and circular geometry.",
        "filename_hints": ["og_framing", "B1_opengate", "framing"],
    },
    {
        "id": "gyro_handheld_clip",
        "category": "video+xml",
        "title": "Handheld Gyro Pan + Wrist Roll (20s MP4 + M01.XML)",
        "purpose": "Untouched card original proving native 3:2 geometry AND preserved rtmd telemetry in Gyroflow/Catalyst.",
        "filename_hints": ["gyro", "A2", "B2", "C2", "rtmd"],
    },
    {
        "id": "codec_matrix_clips",
        "category": "video",
        "title": "Codec & Frame-Rate Matrix (H.265 / H.264 / All-Intra @ 24p/25p/30p)",
        "purpose": "Directly disproves 'H.265 only' by validating XAVC HS, XAVC S (H.264), and XAVC S-I (All-Intra) clips.",
        "filename_hints": ["xavcs", "xavcsi", "h264", "25p", "30p", "200m", "300m"],
    },
    {
        "id": "soak_pressure_clip",
        "category": "video",
        "title": "30-60 Min Thermal & Sustained Card-Write Soak",
        "purpose": "Answers reliability/overheating pushback with duration, card model, ambient temp, and constant cadence.",
        "filename_hints": ["soak", "thermal", "long"],
    },
    {
        "id": "lcd_desqueeze_photos",
        "category": "image",
        "title": "Rear LCD 3:2 & De-Squeeze / C-Key Photos",
        "purpose": "Phone photos of camera rear LCD showing 3:2 framing, focus boxes, and 1.3x/1.5x/1.6x/2.0x de-squeeze.",
        "filename_hints": ["lcd", "desqueeze", "c2", "c3", "screen"],
    },
    {
        "id": "hdmi_af_demo",
        "category": "video_or_image",
        "title": "Clean 3:2 HDMI + Active AF Demo",
        "purpose": "Shows external monitor receiving clean 3:2 via hdmi32 while Sony AF remains active (internal De-Squeeze OFF).",
        "filename_hints": ["hdmi", "af", "monitor"],
    },
    {
        "id": "editor_gyro_screenshots",
        "category": "image",
        "title": "Resolve / Premiere & Gyroflow Screenshots",
        "purpose": "Screenshots of NLE clip attributes (3840x2560 1:1) and Gyroflow motion trace without ffmpeg remuxing.",
        "filename_hints": ["resolve", "premiere", "gyroflow", "catalyst", "nle"],
    },
]


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


def _collect_sessions(session_dir: Path, body_id: str, limit: int = 12) -> list[dict[str, Any]]:
    if not session_dir.is_dir():
        return []
    found: list[tuple[float, str, dict[str, Any]]] = []
    # Only read session_*.json metadata; never touch camera_private/ or raw dumps.
    for path in session_dir.glob("session_*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf8"))
        except (OSError, ValueError):
            continue
        if raw.get("body_id") != body_id:
            continue
        summary = {
            "session_id": raw.get("session_id"),
            "kind": raw.get("kind"),
            "timestamp": raw.get("timestamp"),
            "ready": bool(raw.get("ready", False)),
            "state": raw.get("state"),
            "verdict": raw.get("verdict"),
            "active_packs": list(raw.get("active_packs") or []),
            "steps_run": list(raw.get("steps_run") or []),
            "pins_ok": raw.get("pins_ok"),
        }
        found.append((float(raw.get("timestamp") or 0.0), path.name, summary))
    found.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in found[:limit]]


def _collect_evidence_files(clips_dir: Path | None) -> list[dict[str, Any]]:
    if clips_dir is None or not clips_dir.is_dir():
        return []
    root = clips_dir.resolve()
    files: list[dict[str, Any]] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        candidates = [entry] if entry.is_file() else (
            sorted(entry.iterdir(), key=lambda p: p.name.lower()) if entry.is_dir() else []
        )
        for item in candidates:
            if not item.is_file():
                continue
            ext = item.suffix.lower()
            if ext in EVIDENCE_EXTS or ext == ".mp4":
                files.append({
                    "relative_path": item.relative_to(root).as_posix(),
                    "ext": ext,
                    "size_bytes": item.stat().st_size,
                })
    return files


def _match_recommended_samples(evidence_files: list[dict[str, Any]], clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rel_names = [e["relative_path"].lower() for e in evidence_files]
    matched: list[dict[str, Any]] = []
    for slot in RECOMMENDED_SAMPLES:
        hits: list[str] = []
        hints = [h.lower() for h in slot["filename_hints"]]
        for rel in rel_names:
            if any(h in rel for h in hints):
                hits.append(rel)
        if slot["id"] == "stock_framing_clip":
            for c in clips:
                if c.get("expected_mode") == "stock" and c.get("ok"):
                    fname = Path(c["file"]).name
                    if fname.lower() not in [h.lower() for h in hits]:
                        hits.append(fname)
        elif slot["id"] == "opengate_framing_clip":
            for c in clips:
                if c.get("expected_mode") == "open-gate" and c.get("ok"):
                    fname = Path(c["file"]).name
                    if fname.lower() not in [h.lower() for h in hits]:
                        hits.append(fname)
        matched.append({
            "id": slot["id"],
            "category": slot["category"],
            "title": slot["title"],
            "purpose": slot["purpose"],
            "filename_hints": slot["filename_hints"],
            "detected_files": hits,
            "present": len(hits) > 0,
        })
    return matched


def _format_step_label(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("step") or item.get("name") or item.get("id") or "?")
    return str(item)


def _render_markdown(report: dict[str, Any]) -> str:
    meta = report["metadata"]
    pins = report["pins"]
    sessions = report["sessions"]
    batch = report["clips_summary"]
    env = report["environment"]
    samples = report["sample_checklist"]

    lines: list[str] = [
        f"# OpenGate Studio Field Test & Reliability Report — {meta['camera']} (`{meta['body_id']}`)",
        "",
        f"- **Generated (UTC):** `{meta['generated_utc']}`",
        f"- **Commit:** `{meta['git_commit']}`",
        f"- **Firmware Target:** `{meta['firmware']}` (`version.txt`: `{meta['version_txt']}`)",
        f"- **Kit SHA-256 Pins:** `{'PASS' if pins['ok'] else 'FAIL'}` ({pins['checked_files']} files verified)",
        "",
        "## 1. Test Environment & Reliability Metrics",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Media Card | {env['media_card'] or '_(not specified)_'} |",
        f"| Lens | {env['lens'] or '_(not specified)_'} |",
        f"| Ambient Temp (C) | {env['ambient_c'] or '_(not specified)_'} |",
        f"| Soak Duration (min) | {env['soak_minutes'] or '_(not specified)_'} |",
        f"| Thermal Result | {env['thermal_result'] or '_(not specified)_'} |",
        f"| Field Re-Activation Time (s) | {env['reactivation_seconds'] or '_(not specified)_'} |",
        f"| AF + De-Squeeze / HDMI Notes | {env['af_desqueeze_notes'] or '_(not specified)_'} |",
        f"| Gyro App Tested | {env['gyro_app'] or '_(not specified)_'} |",
        f"| Editor / NLE Tested | {env['editor_app'] or '_(not specified)_'} |",
        "",
        "## 2. Session & Preflight History",
        "",
    ]

    if sessions:
        latest = sessions[0]
        steps_str = ", ".join(_format_step_label(s) for s in latest.get("steps_run", [])) or "none"
        packs_str = ", ".join(latest.get("active_packs", [])) or "none"
        lines.extend([
            f"- **Latest Session:** `{latest.get('session_id')}` (`{latest.get('kind')}`)",
            f"- **Verdict:** `{latest.get('verdict')}` (`state={latest.get('state')}`, `ready={latest.get('ready')}`)",
            f"- **Active Packs:** `{packs_str}`",
            f"- **Steps:** `{steps_str}`",
            "",
        ])
    else:
        lines.extend(["- No saved sessions found for this body in `session_dir`.", ""])

    lines.extend([
        "## 3. Recorded Clip Inspection (`bionz_clip_check.py`)",
        "",
        f"- **Clips Scanned:** `{batch['clips_scanned']}` | **Passed:** `{batch['clips_passed']}` | **Failed:** `{batch['clips_failed']}`",
        "",
    ])

    all_warnings: list[str] = []
    if batch["clips"]:
        lines.extend([
            "| Clip | Mode | Res | Codec / Profile | FPS | Dur (s) | Avg Mbps | VPRF 3:2 | XML 3:2 | rtmd Samples | Cadence | Verdict |",
            "|---|---|---|---|---|---:|---:|---|---|---:|---|---|",
        ])
        for c in batch["clips"]:
            fname = Path(c["file"]).name
            mode = c.get("expected_mode", "?")
            if "width" in c and "height" in c:
                res = f"{c['width']}x{c['height']}"
            else:
                res = "ERR"
            codec_lbl = c.get("codec_profile_level") or c.get("codec") or "?"
            fps = c.get("fps", "?")
            dur = f"{c.get('duration_sec', 0.0):.2f}"
            mbps = f"{c.get('avg_bitrate_mbps', 0.0):.1f}"
            vprf = "YES" if c.get("vprf_3x2") else "NO"
            xml_val = c.get("xml_3x2")
            xml_str = "YES" if xml_val is True else ("NO" if xml_val is False else "none")
            rtmd = str(c.get("rtmd_samples", 0))
            cad = "const" if c.get("cadence_constant", True) else "VAR"
            verdict = "PASS" if c.get("ok") else f"FAIL ({'; '.join(c.get('issues', []))})"
            lines.append(
                f"| `{fname}` | {mode} | {res} | {codec_lbl} | {fps} | {dur} | {mbps} | {vprf} | {xml_str} | {rtmd} | {cad} | {verdict} |"
            )
            for w in c.get("warnings", []):
                all_warnings.append(f"`{fname}`: {w}")
        lines.append("")
    else:
        lines.extend(["- No `.MP4` clips were scanned (pass `--clips-dir` to include clip telemetry).", ""])

    if all_warnings:
        lines.extend(["### Informational Warnings", ""])
        for w in all_warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.extend([
        "## 4. Recommended Public-Report Sample Checklist",
        "",
        "| Sample Slot | Status | Detected Local Files |",
        "|---|---|---|",
    ])
    for s in samples:
        status = "READY" if s["present"] else "MISSING"
        detected = ", ".join(f"`{d}`" for d in s["detected_files"]) if s["detected_files"] else "—"
        lines.append(f"| **{s['title']}** | {status} | {detected} |")

    if env["notes"]:
        lines.extend(["", "## 5. Operator Notes", "", env["notes"], ""])

    return "\n".join(lines).rstrip() + "\n"


def build_field_report(
    *,
    body_id: str,
    manifests: dict[str, tuple[Path, dict[str, Any]]],
    verify_pins_fn: Any,
    session_dir: Path,
    clips_dir: Path | None = None,
    out_dir: Path | None = None,
    media_card: str = "",
    lens: str = "",
    ambient_c: str = "",
    soak_minutes: str = "",
    thermal_result: str = "",
    reactivation_seconds: str = "",
    af_desqueeze_notes: str = "",
    gyro_app: str = "",
    editor_app: str = "",
    notes: str = "",
) -> tuple[int, dict[str, Any]]:
    if body_id not in manifests:
        return 1, {"ok": False, "error": f"Unknown body {body_id!r}"}

    kit_dir, man = manifests[body_id]
    pin_res = verify_pins_fn(kit_dir, man)
    sessions = _collect_sessions(session_dir, body_id)

    if clips_dir is not None:
        if not clips_dir.is_dir():
            return 1, {"ok": False, "error": f"Clips directory not found: {clips_dir}"}
        batch = bcc.inspect_directory(clips_dir, expect="auto", body=body_id)
    else:
        batch = {
            "ok": True,
            "clips_dir": None,
            "clips_scanned": 0,
            "clips_passed": 0,
            "clips_failed": 0,
            "clips": [],
        }

    evidence_files = _collect_evidence_files(clips_dir)
    sample_checklist = _match_recommended_samples(evidence_files, batch["clips"])

    now_utc = datetime.now(timezone.utc)
    stamp = now_utc.strftime("%Y%m%d_%H%M%S")
    target_dir = (out_dir if out_dir is not None else session_dir / "reports" / f"{body_id}_{stamp}").resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    report_payload: dict[str, Any] = {
        "schema_version": 1,
        "metadata": {
            "body_id": body_id,
            "camera": man.get("camera", body_id),
            "firmware": man.get("firmware", ""),
            "version_txt": man.get("version_txt", ""),
            "git_commit": _git_short_commit(),
            "generated_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "persistent_writes": False,
        },
        "pins": pin_res,
        "sessions": sessions,
        "clips_summary": batch,
        "environment": {
            "media_card": media_card.strip(),
            "lens": lens.strip(),
            "ambient_c": ambient_c.strip(),
            "soak_minutes": soak_minutes.strip(),
            "thermal_result": thermal_result.strip(),
            "reactivation_seconds": reactivation_seconds.strip(),
            "af_desqueeze_notes": af_desqueeze_notes.strip(),
            "gyro_app": gyro_app.strip(),
            "editor_app": editor_app.strip(),
            "notes": notes.strip(),
        },
        "sample_checklist": sample_checklist,
    }

    manifest_payload = {
        "schema_version": 1,
        "body_id": body_id,
        "generated_utc": report_payload["metadata"]["generated_utc"],
        "clips_dir": str(clips_dir.resolve()) if clips_dir is not None else None,
        "evidence_files": evidence_files,
        "sample_checklist": sample_checklist,
    }

    markdown_text = _render_markdown(report_payload)

    json_path = target_dir / "field_report.json"
    md_path = target_dir / "FIELD_REPORT.md"
    manifest_path = target_dir / "sample_intake_manifest.json"

    json_path.write_text(json.dumps(report_payload, indent=2), encoding="utf8")
    md_path.write_text(markdown_text, encoding="utf8")
    manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf8")

    latest_verdict = sessions[0].get("verdict") if sessions else None
    return 0, {
        "ok": True,
        "body_id": body_id,
        "camera": man.get("camera", body_id),
        "firmware": man.get("firmware", ""),
        "report_dir": str(target_dir),
        "markdown_path": str(md_path),
        "json_path": str(json_path),
        "manifest_path": str(manifest_path),
        "clips_scanned": batch["clips_scanned"],
        "clips_passed": batch["clips_passed"],
        "clips_failed": batch["clips_failed"],
        "pins_ok": pin_res["ok"],
        "latest_session_verdict": latest_verdict,
        "markdown_preview": markdown_text,
    }
