#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware Conformance & Matrix Promotion Runbook generator + offline selftest for OpenGate Studio."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
KITS_DIR = REPO_ROOT / "kits"
DOCS_DIR = REPO_ROOT / "docs"
SUPPORT_MATRIX_PATH = DOCS_DIR / "support_matrix.json"
FAILSAFE_RESEARCH_PATH = DOCS_DIR / "FAILSAFE_AND_OVERLAY_RESEARCH.md"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import bionz_clip_check as bcc  # noqa: E402
import studio_cli  # noqa: E402
import studio_report  # noqa: E402

BODY_ORDER = ("zve1_202", "a7s3_501", "fx3_702")

_BODY_UI_NAMES: dict[str, str] = {
    "zve1_202": "ZV-E1 2.02",
    "a7s3_501": "a7S III 5.01",
    "fx3_702": "FX3 7.02",
}

_CT6_FALLBACK_TARGETS: dict[str, list[dict[str, str]]] = {
    "zve1_202": [
        {
            "area": "OSD / Tracking Overlay",
            "target": "cpActTrackingFrame + VDF aspect tables",
            "address_or_expr": "0x129288 (0x129384 640x360 gate), 0x63b624/0x63b664, 0xcac010/0xcabfd0, [r0+0x12d]/[r0+0x12f]",
            "purpose": "Inspect stage-1 OSD index and stage-2 640x360 Y-remap rect (0x63b3da vs 0x63b448) in 3:2 Movie live view.",
        },
        {
            "area": "Stills -> Movie fullinit Gate",
            "target": "Mode-switch dispatcher & init guard wrapper",
            "address_or_expr": "0x96d21c (fullinit), 0x390994/0x3909c2 ([r4,#0x534]/[r4,#0x538]), 0x38d4b4/0x38d4ce ([r4,#0x1c]/[r4,#0x2c]==7)",
            "purpose": "Verify cached init state across cold-boot Stills -> Movie transition without write patches.",
        },
        {
            "area": "50p/60p/120p Option C Dispatch",
            "target": "picture_ratio & Size Class 3 consumer",
            "address_or_expr": "0x1f5e5c (picture_ratio r1=(w<<16)|h), 0x19964c4/0x199655c (Size Class 3)",
            "purpose": "Confirm live drive-mode / output height state before authoring rate-aware fallback hooks.",
        },
    ],
    "a7s3_501": [
        {
            "area": "OSD / Tracking Overlay",
            "target": "cpActTrackingFrame + VDF aspect tables",
            "address_or_expr": "0x129608 (0x129704 640x360 gate), 0x58c67c/0x58c6bc, 0x298824/0xb4fc80, 0x58c432/0x58c4a0",
            "purpose": "Inspect stage-1 OSD index and stage-2 640x360 Y-remap rect during 3:2 Movie live view.",
        },
        {
            "area": "Stills -> Movie fullinit Gate",
            "target": "Mode-switch dispatcher & init guard wrapper",
            "address_or_expr": "0x86cde6 (fullinit), 0x335a94/0x335ac2 ([r4,#0x530]/[r4,#0x534]), 0x332624/0x33263e ([r4,#0x1c]/[r4,#0x2c]==7)",
            "purpose": "Verify cached pipeline state causing recoverable purple/lower-black standby on Stills -> Movie.",
        },
        {
            "area": "50p/60p/120p Option C Dispatch",
            "target": "picture_ratio, Size Class 3 & libmpr HFR selectors",
            "address_or_expr": "0x1e4f64 (picture_ratio), 0x13ec260/0x13ec2e4 (Size Class 3), libmpr L2-mp4 [x1,#0x14] @0x223d34, L3-nrt-vline [x20,#0x138] @0x118684",
            "purpose": "Confirm runtime size-lookup and muxer rate selector state (read-only CT6 first).",
        },
    ],
    "fx3_702": [
        {
            "area": "OSD / Tracking Overlay",
            "target": "cpActTrackingFrame & VDF direct normalization",
            "address_or_expr": "0x129200 / 0x129370, 0x57b84e / 0x57fb54 / 0x57fbc2, 0xb365f0 / 0x2938e4",
            "purpose": "Verify direct VDF normalization and FX3 De-Squeeze Display rect table (0x1df680, 0xd2e510..0xd2e600).",
        },
        {
            "area": "Stills -> Movie fullinit Gate",
            "target": "Mode-switch dispatcher & init guard wrapper",
            "address_or_expr": "0x85750c (fullinit), 0x330d70/0x330d9e ([r4,#0x530]/[r4,#0x534]), 0x32d900/0x32d91a ([r4,#0x1c]/[r4,#0x2c]==7)",
            "purpose": "Verify cached init state across Stills -> Movie transition in read-only CT6 dump.",
        },
        {
            "area": "50p/60p/120p Option C Dispatch",
            "target": "picture_ratio & Size Class 3 consumer",
            "address_or_expr": "0x1df794 (picture_ratio), 0x13c3144/0x13c31c8 (Size Class 3)",
            "purpose": "Confirm live drive-mode and output height state before authoring rate-aware fallback hooks.",
        },
    ],
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf8") as fh:
        return json.load(fh)


def _read_text(path: Path) -> str:
    with path.open("r", encoding="utf8") as fh:
        return fh.read()


def _extract_section5_ct6_targets(research_md: str) -> list[dict[str, str]]:
    """Extract verified read-only CT6 struct pointer targets from §5.1 of FAILSAFE_AND_OVERLAY_RESEARCH.md."""
    sec51_match = re.search(r"^###\s+5\.1\s+(.+)$", research_md, flags=re.MULTILINE)
    if sec51_match:
        sec_start = sec51_match.start()
        next_sub = re.search(r"^###\s+5\.2\b|^##\s+6\b", research_md[sec51_match.end():], flags=re.MULTILINE)
        sec_body = (
            research_md[sec_start : sec51_match.end() + next_sub.start()]
            if next_sub
            else research_md[sec_start:]
        )
    else:
        sec5_match = re.search(r"^##\s+5\.\s+(.+)$", research_md, flags=re.MULTILINE)
        if not sec5_match:
            return []
        sec_start = sec5_match.start()
        next_sec = re.search(r"^##\s+6\.\s+", research_md[sec5_match.end():], flags=re.MULTILINE)
        sec_body = (
            research_md[sec_start : sec5_match.end() + next_sec.start()]
            if next_sec
            else research_md[sec_start:]
        )

    rows: list[dict[str, str]] = []
    for line in sec_body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("|---") or stripped.startswith("| :---"):
            continue
        cells = [
            c.replace("\\|", "|").strip().strip("`")
            for c in re.split(r"(?<!\\)\|", stripped.strip("|"))
        ]
        if len(cells) >= 5 and any("0x" in c for c in cells[1:4]):
            if "subsystem" in cells[0].lower() or "zve1_202" in cells[1].lower():
                continue
            rows.append({
                "subsystem": cells[0],
                "zve1_202": cells[1],
                "a7s3_501": cells[2],
                "fx3_702": cells[3],
                "expected_stock_state": cells[4],
                "columns": " | ".join(cells),
            })
    return rows


def _summarize_matrix_for_body(matrix: dict[str, Any], body_id: str) -> dict[str, Any]:
    dims: list[str] = list(matrix.get("dimensions") or [])
    counts: dict[str, int] = {"yes": 0, "partial": 0, "no": 0, "blocked": 0, "na": 0}
    open_promotions: list[dict[str, Any]] = []

    for entry in matrix.get("entries", []):
        if entry.get("body_id") != body_id:
            continue
        ev = entry.get("evidence") or {}
        pending_dims: list[str] = []
        partial_dims: list[str] = []
        for d in dims:
            val = str(ev.get(d, "no"))
            if val in counts:
                counts[val] += 1
            if val == "partial":
                partial_dims.append(d)
            elif val == "no":
                pending_dims.append(d)
        if partial_dims or pending_dims:
            open_promotions.append({
                "fps": entry.get("fps"),
                "codec": entry.get("codec"),
                "pack": entry.get("pack"),
                "tier": entry.get("tier"),
                "partial_dimensions": partial_dims,
                "pending_dimensions": pending_dims,
                "notes": entry.get("notes", ""),
            })

    return {
        "counts": counts,
        "open_entries": open_promotions,
    }


def _safe_daily_apply_steps(manifest: dict[str, Any]) -> list[str]:
    packs = manifest.get("packs") or {}
    ordered: list[str] = []
    for pack_id in ("core_open_gate", "mp4_3x2", "screen_3x2"):
        pinfo = packs.get(pack_id) or {}
        for step in pinfo.get("apply_steps") or []:
            if step not in ordered:
                ordered.append(str(step))
    return ordered


def _safe_daily_putback_steps(manifest: dict[str, Any]) -> list[str]:
    packs = manifest.get("packs") or {}
    ordered: list[str] = []
    for pack_id in ("screen_3x2", "mp4_3x2", "core_open_gate"):
        pinfo = packs.get(pack_id) or {}
        for step in pinfo.get("putback_steps") or []:
            if step not in ordered:
                ordered.append(str(step))
    return ordered


def _build_body_runbook(
    body_id: str,
    matrix: dict[str, Any],
    manifest: dict[str, Any],
    section5_rows: list[dict[str, str]],
) -> dict[str, Any]:
    body_meta = (matrix.get("bodies") or {}).get(body_id, {})
    packs = manifest.get("packs") or {}
    steps = manifest.get("steps") or {}
    v19 = steps.get("V19") or {}
    v19_sha = str(v19.get("sha256") or "")
    v19_prefix = v19_sha[:8]
    v19_summary = str(v19.get("summary") or "")
    safe_apply = _safe_daily_apply_steps(manifest)
    safe_putback = _safe_daily_putback_steps(manifest)
    matrix_summary = _summarize_matrix_for_body(matrix, body_id)

    ui_name = _BODY_UI_NAMES.get(body_id, body_id)

    priorities: list[dict[str, Any]] = []

    if body_id == "zve1_202":
        priorities.append({
            "priority": 1,
            "id": "zve1_v19_nrt_xml_promotion",
            "title": "ZV-E1 2.02 V19 NRT XML Verified on C6438.MP4 (Remaining: Catalyst / NLE / Playback / Soak -> field_ready)",
            "target_pack": "mp4_3x2",
            "target_step": "V19",
            "target_design": "ogfile2560_hs_s_zv_v3",
            "helper_file": v19.get("file"),
            "helper_sha256_prefix": v19_prefix,
            "helper_sha256": v19_sha,
            "matrix_promotion": {
                "entry": "zve1_202 / 23.98p / XAVC HS / S 4K / mp4_3x2",
                "dimension": "clip_xml_validated",
                "status": "verified_on_C6438",
                "from": "partial",
                "to": "yes",
                "additional_dimensions": [
                    "catalyst_verified",
                    "nle_verified",
                    "playback_verified",
                    "long_take_verified",
                    "field_ready",
                ],
            },
            "steps": [
                f"Hardware baseline already verified on C6438.MP4 + C6438M01.XML (`V19` `{v19_prefix}`, complete embedded + sidecar NRT XML without `repair-nrt-xml`, `clip_xml_validated = yes`, `0xe40e` readout `12.336 ms`).",
                f"Verify kit integrity before additional field runs: run `.venv/bin/python -B cli/studio_cli.py verify-pins --body {body_id} --json` (confirm V19 `{v19.get('file')}` prefix `{v19_prefix}` and `ok: true`).",
                f"In `OpenGate Studio.app` -> `Camera` workspace, select `{ui_name}` and click `Setup Guide…` to confirm 2.02 firmware, formatted Slot 1 card, `Mass Storage` USB mode, `USB Power Supply = Off`, `Smartphone Conn = Off`, and `XAVC HS 4K` / `24p (23.98p)` Full Frame.",
                "Pull camera battery >= 10s, boot straight into Stills mode, tick both `Before Connecting` toggles, then click `Check Camera (Read-Only)` (or tap `Check Camera (Read-Only)` in Android `OpenGate Field Companion`). Confirm `VERDICT READY (stock preflight)` (`mode=\"live_usb\"`).",
                f"Select `Safe Daily 3:2` (`{' -> '.join(safe_apply)}`, applying `V19` `{v19_prefix}`) and click `Apply Open-Gate (3:2)` (Android: `Apply Safe Daily 3:2`). Keep camera ON during replugs; switch to Movie mode for closing `dump` (`VERDICT READY (open gate applied)`).",
                "Capture extended Catalyst Browse / NLE / in-camera playback / `>= 30 min` thermal soak clips (`Cxxxx.MP4` + `CxxxxM01.XML`) plus a `Putback` (`Restore Stock RAM`) or `>= 10s` battery-pull `3840x2160` stock baseline clip.",
                f"Verify untouched clips with `.venv/bin/python -B cli/studio_cli.py check-clip <CLIP.MP4> --body {body_id} --json` (or `OpenGate Studio.app` -> `Clips` workspace), then confirm Sony Catalyst Browse, DaVinci Resolve/Premiere NLE import, in-camera playback, and `>= 30 min` thermal soak to unlock `field_ready`.",
            ],
        })
    elif body_id == "a7s3_501":
        priorities.append({
            "priority": 2,
            "id": "a7s3_safe_daily_conformance",
            "title": "Untouched Safe Daily 3:2 Capture, Gyroflow Readout Calibration & NLE Proof",
            "target_pack": "core_open_gate + mp4_3x2 + screen_3x2",
            "target_step": "V19",
            "target_design": "ogfile2560_hs_s_s3_v3",
            "helper_file": v19.get("file"),
            "helper_sha256_prefix": v19_prefix,
            "helper_sha256": v19_sha,
            "matrix_promotion": {
                "entry": "a7s3_501 / 23.98p / XAVC HS / S 4K / core_open_gate + screen_3x2 & mp4_3x2",
                "dimensions": [
                    "hardware_recorded",
                    "clip_xml_validated",
                    "gyroflow_verified",
                    "catalyst_verified",
                    "nle_verified",
                    "playback_verified",
                    "field_ready",
                ],
            },
            "steps": [
                f"Verify SHA-256 pins (`verify-pins --body {body_id}` -> V19 `{v19.get('file')}` prefix `{v19_prefix}`) and run `Setup Guide…` in `OpenGate Studio.app` (`Camera` workspace) for `{ui_name}` (`ILCE-7SM3`).",
                "Cold-boot (>= 10s battery pull) into Stills mode (`M`/`A`/`S`/`P`), run `Check Camera (Read-Only)` -> `VERDICT READY (stock preflight)`, then `Apply Open-Gate (3:2)` with `Safe Daily 3:2` (`" + " -> ".join(safe_apply) + "`).",
                "On closing Movie-mode `dump`, if live view shows purple/lower-black standby, start/stop a 1s dummy clip before replugging USB so `IMG INIT` completes cleanly.",
                "Capture the 7-clip untouched conformance bundle (locked 3:2 chart, IBIS OFF gyro, IBIS Standard gyro, fast shutter 1/500+ whip-pan for `frame_readout_time_ms` vs `10.3 ms` estimate, and post-`Restore Stock RAM` 16:9 stock baseline).",
                "Open untouched clips in `Clips` workspace (`Open Clip or Card…`), verify `bionz_clip_check` (`ok: true`, `VPRF` 3:2, non-truncated `<Device>`/`<VideoLayout>`/`<VideoFrame>` XML, `rtmd` KLV cadence), then test Gyroflow, Catalyst Browse, NLE, and in-camera playback.",
                f"Generate `FIELD_REPORT.md` + `CONFORMANCE_REPORT.md` via `Diagnostics & Field Tools` -> `Field Report` or `cli/studio_cli.py conformance-audit --body {body_id}` (dry-run matrix promotion check).",
            ],
        })
    elif body_id == "fx3_702":
        p29 = steps.get("P29") or {}
        p29_prefix = str(p29.get("sha256") or "")[:8]
        priorities.append({
            "priority": 2,
            "id": "fx3_safe_daily_and_playback",
            "title": "Untouched Safe Daily 3:2 Capture, Gyroflow Proof & Optional fx3_playback (P29/P30) Check",
            "target_pack": "core_open_gate + mp4_3x2 + screen_3x2 (+ optional fx3_playback)",
            "target_step": "V19",
            "target_design": "ogfile2560_hs_s_fx3_v3",
            "helper_file": v19.get("file"),
            "helper_sha256_prefix": v19_prefix,
            "helper_sha256": v19_sha,
            "optional_playback_pack": {
                "pack_id": "fx3_playback",
                "apply_steps": (packs.get("fx3_playback") or {}).get("apply_steps", ["P29"]),
                "putback_steps": (packs.get("fx3_playback") or {}).get("putback_steps", ["P30"]),
                "default_enabled": bool((packs.get("fx3_playback") or {}).get("default_enabled", False)),
                "p29_file": p29.get("file"),
                "p29_sha256_prefix": p29_prefix,
                "safety_rule": "Play 1 normal 16:9 stock clip FIRST, then 1 open-gate 3:2 clip. NEVER retry if 'Unable to display' appears (retrying freezes stock FX3 until >= 10s battery pull).",
            },
            "matrix_promotion": {
                "entry": "fx3_702 / 23.98p / 25p (PAL) / core_open_gate + screen_3x2, mp4_3x2 & fx3_playback",
                "dimensions": [
                    "hardware_recorded",
                    "clip_xml_validated",
                    "gyroflow_verified",
                    "catalyst_verified",
                    "nle_verified",
                    "playback_verified",
                    "field_ready",
                ],
            },
            "steps": [
                f"Confirm exact model is `ILME-FX3` (NOT `ILME-FX3A`), verify pins (`verify-pins --body {body_id}` -> V19 `{v19.get('file')}` prefix `{v19_prefix}`), and run `Setup Guide…` in `OpenGate Studio.app`.",
                "Cold-boot (>= 10s battery pull) into Stills mode (`MODE` -> Stills), run `Check Camera (Read-Only)`, then `Apply Open-Gate (3:2)` with `Safe Daily 3:2` (`" + " -> ".join(safe_apply) + "`).",
                "Capture untouched `23.98p` (and `25p` PAL `0x820`) framing, gyro, and whip-pan calibration clips plus a post-`Restore Stock RAM` 16:9 baseline; inspect in `Clips` workspace (`ok: true`, non-truncated XML, `rtmd`).",
                "Optional isolated `fx3_playback` (`P29/P30`, `avdec8k_fx3_v1`, prefix `" + p29_prefix + "`) session: enable `fx3_playback` in `Customize Feature Packs`, apply with `Safe Daily 3:2`, play ONE stock 16:9 clip first, then ONE open-gate 3:2 clip. Never retry on error; run `Restore Stock RAM` (`putback`) or pull battery >= 10s.",
            ],
        })

    # Priority 3 applies to every body
    exp_packs: list[dict[str, Any]] = []
    for pack_id in ("hdmi32", "high_bitrate", "xavc_si"):
        if pack_id in packs:
            p = packs[pack_id]
            exp_packs.append({
                "pack_id": pack_id,
                "label": p.get("label") or p.get("title") or pack_id,
                "apply_steps": p.get("apply_steps", []),
                "putback_steps": p.get("putback_steps", []),
                "summary": p.get("summary", ""),
            })

    ct6_targets = list(_CT6_FALLBACK_TARGETS.get(body_id, []))
    body_sec5_targets = [
        {
            "subsystem": row["subsystem"],
            "address_or_ptr": row.get(body_id, ""),
            "expected_stock_state": row["expected_stock_state"],
        }
        for row in section5_rows
        if body_id in row
    ]
    priorities.append({
        "priority": 3,
        "id": f"{body_id}_experimental_and_ct6_readonly",
        "title": "Experimental Packs (25p/29.97p, hdmi32, xavc_si, high_bitrate >=30m Soak) & Read-Only CT6 Targets",
        "experimental_packs": exp_packs,
        "fps_targets": ["25.000p (PAL 0x820)", "29.970p (NTSC rate-code-2)"],
        "thermal_soak_target": ">= 30 min continuous roll under high_bitrate (200M/300M Long-GOP); log card model, ambient C, cadence, thermal warnings",
        "read_only_ct6_targets": ct6_targets,
        "section5_verified_ct6_targets": body_sec5_targets,
        "safety_policy": "Read-only CT6 inspection ONLY (`libJit_*_check.so` / `libJit_*_dump.so`); zero write patches to OSD/fullinit/HFR until CT6 dumps verify pointers.",
        "steps": [
            "Test `25p` (`PAL`) and `29.97p` (`NTSC`) under `Safe Daily 3:2` and verify constant `stts` & `rtmd` cadence in `Clips` workspace (`bionz_clip_check.py`).",
            "Enable `hdmi32` (`H16/H17`) in `Customize Feature Packs` to verify clean 3:2 pillarboxed external HDMI monitor output (on FX3, keep internal De-Squeeze OFF so Sony AF stays active).",
            "Enable `xavc_si` (`I19/I20`) to verify All-Intra `3840x2560` capture at `23.98p/25p/29.97p` and confirm NLE acceptance of AVC L5.1 `38,400` MBs.",
            "Enable `high_bitrate` (`B19/B20`) for a >= 30-minute continuous thermal & card soak on V90 SD / CFexpress Type A; generate `FIELD_REPORT.md` via `Diagnostics & Field Tools` -> `Field Report`.",
            "Run read-only `CT6` inspection (`dump`) on `cpapp` / `libmpr` targets in `docs/FAILSAFE_AND_OVERLAY_RESEARCH.md` (OSD `cpActTrackingFrame`, `fullinit` cache flags, Option C `picture_ratio`/HFR selectors) without modifying camera memory.",
        ],
    })

    return {
        "body_id": body_id,
        "camera": body_meta.get("camera", manifest.get("camera", body_id)),
        "model_id": body_meta.get("model_id", body_id),
        "firmware": manifest.get("firmware", body_meta.get("firmware", "")),
        "version_txt": manifest.get("version_txt", body_meta.get("version_txt", "")),
        "persistent_writes": bool(manifest.get("persistent_writes", False)),
        "safe_daily_apply_steps": safe_apply,
        "safe_daily_putback_steps": safe_putback,
        "v19_helper": {
            "file": v19.get("file"),
            "sha256": v19_sha,
            "sha256_prefix": v19_prefix,
            "summary": v19_summary,
        },
        "matrix_status": matrix_summary,
        "priorities": priorities,
    }


def build_conformance_plan(body: str = "all", repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Parse docs/support_matrix.json, kits/*/manifest.json, and FAILSAFE_AND_OVERLAY_RESEARCH.md into a prioritized plan."""
    matrix_path = repo_root / "docs" / "support_matrix.json"
    research_path = repo_root / "docs" / "FAILSAFE_AND_OVERLAY_RESEARCH.md"
    kits_dir = repo_root / "kits"

    matrix = _read_json(matrix_path)
    research_md = _read_text(research_path) if research_path.is_file() else ""
    section5_rows = _extract_section5_ct6_targets(research_md)

    if body == "all":
        selected_bodies = list(BODY_ORDER)
    elif body in BODY_ORDER:
        selected_bodies = [body]
    else:
        raise ValueError(f"Unsupported --body {body!r}; expected one of {(*BODY_ORDER, 'all')}")

    body_plans: list[dict[str, Any]] = []
    for bid in selected_bodies:
        man_path = kits_dir / bid / "manifest.json"
        if not man_path.is_file():
            raise FileNotFoundError(f"Missing kit manifest: {man_path}")
        manifest = _read_json(man_path)
        body_plans.append(_build_body_runbook(bid, matrix, manifest, section5_rows))

    # Global priority ordering: Priority 1 (zve1_202), Priority 2 (a7s3_501, fx3_702), Priority 3 (experimental + CT6)
    priority_queue: list[dict[str, Any]] = []
    for bp in body_plans:
        for pr in bp["priorities"]:
            priority_queue.append({
                "priority": pr["priority"],
                "body_id": bp["body_id"],
                "camera": bp["camera"],
                "firmware": bp["firmware"],
                "id": pr["id"],
                "title": pr["title"],
            })
    priority_queue.sort(key=lambda item: (item["priority"], BODY_ORDER.index(item["body_id"])))

    return {
        "ok": True,
        "schema_version": 1,
        "release_maturity": matrix.get("release_maturity", ""),
        "body_filter": body,
        "persistent_writes": False,
        "ui_surfaces": {
            "macos_app": [
                "OpenGate Studio.app -> Camera workspace",
                "Setup Guide… (5-step hardware & menu checklist)",
                "Check Camera (Read-Only)",
                "Apply Open-Gate (3:2)",
                "Restore Stock RAM",
                "OpenGate Studio.app -> Clips workspace",
                "Diagnostics & Field Tools (Console / Pins / Field Report)",
            ],
            "android_app": [
                "OpenGate Field Companion (USB-OTG Host)",
                "Check Camera (Read-Only)",
                "Apply Safe Daily 3:2",
                "Swapped Battery? Re-Check",
                "Export Session Bundle (Excludes Private Dumps)",
            ],
            "cli": "cli/studio_conformance_plan.py / cli/studio_cli.py",
        },
        "priority_queue": priority_queue,
        "section5_ct6_targets_count": len(section5_rows),
        "section5_ct6_targets": section5_rows,
        "bodies": body_plans,
    }


def render_plan_markdown(plan: dict[str, Any]) -> str:
    """Render a human-readable Markdown Hardware Conformance & Matrix Promotion Runbook."""
    lines: list[str] = [
        f"# OpenGate Studio — Hardware Conformance & Matrix Promotion Runbook ({plan.get('release_maturity', '')})",
        "",
        "- **Volatile RAM Only:** `persistent_writes=false` (battery pull >= 10s restores stock).",
        f"- **Target Scope:** `{plan['body_filter']}`",
        "",
        "## Priority Queue",
        "",
        "| Priority | Body | Firmware | Objective |",
        "|---:|---|---|---|",
    ]
    for item in plan["priority_queue"]:
        lines.append(
            f"| **P{item['priority']}** | `{item['body_id']}` ({item['camera']}) | `{item['firmware']}` | {item['title']} |"
        )
    lines.append("")

    for bp in plan["bodies"]:
        counts = bp["matrix_status"]["counts"]
        v19 = bp["v19_helper"]
        lines.extend([
            f"## {bp['camera']} (`{bp['body_id']}`, FW `{bp['firmware']}`, `{bp['version_txt']}`)",
            "",
            f"- **Safe Daily 3:2 Apply Steps:** `{' -> '.join(bp['safe_daily_apply_steps'])}` (Putback: `{' -> '.join(bp['safe_daily_putback_steps'])}`)",
            f"- **V19 Native 3:2 Helper:** `{v19['file']}` (SHA prefix `{v19['sha256_prefix']}`)",
            f"- **Support Matrix Cells:** `yes={counts['yes']}`, `partial={counts['partial']}`, `no={counts['no']}`, `blocked={counts['blocked']}`",
            "",
        ])
        for pr in bp["priorities"]:
            lines.append(f"### Priority {pr['priority']}: {pr['title']}")
            lines.append("")
            for idx, step in enumerate(pr["steps"], start=1):
                lines.append(f"{idx}. {step}")
            if "optional_playback_pack" in pr:
                pb = pr["optional_playback_pack"]
                lines.extend([
                    "",
                    f"- **Optional `fx3_playback` (`{pb['apply_steps']}` / `{pb['p29_file']}` prefix `{pb['p29_sha256_prefix']}`):** {pb['safety_rule']}",
                ])
            if "read_only_ct6_targets" in pr:
                lines.extend([
                    "",
                    "#### Read-Only `CT6` RAM Inspection Targets",
                    "",
                    "| Area | Target | Address / Expression | Purpose |",
                    "|---|---|---|---|",
                ])
                for t in pr["read_only_ct6_targets"]:
                    lines.append(
                        f"| {t['area']} | {t['target']} | `{t['address_or_expr']}` | {t['purpose']} |"
                    )
                if pr.get("section5_verified_ct6_targets"):
                    lines.extend([
                        "",
                        "**Section 5.1 Verified `CT6` Struct Pointer Targets (`FAILSAFE_AND_OVERLAY_RESEARCH.md`):**",
                        "",
                        "| Subsystem / Check Target | Address / Pointer | Expected Stock State / Note |",
                        "|---|---|---|",
                    ])
                    for row in pr["section5_verified_ct6_targets"]:
                        lines.append(
                            f"| {row['subsystem']} | `{row['address_or_ptr']}` | {row['expected_stock_state']} |"
                        )
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _verify_nrt_xml_complete(xml_text: str, exp_w: int, exp_h: int) -> tuple[bool, list[str]]:
    """Confirm NRT XML is non-truncated and carries <Device>, <VideoLayout>, and <VideoFrame>."""
    parsed = bcc._inspect_xml_text(xml_text, exp_w, exp_h, expect_open_gate=True)
    has_device = any(d.get("manufacturer") == "Sony" for d in parsed["devices"])
    has_layout = len(parsed["layouts"]) > 0
    has_frame = len(parsed["frames"]) > 0 and all(bool(f) for f in parsed["frames"])
    present_tags = [
        name
        for name, ok in (("<Device>", has_device), ("<VideoLayout>", has_layout), ("<VideoFrame>", has_frame))
        if ok
    ]
    ok = bool(parsed["ok"] and has_device and has_layout and has_frame)
    return ok, present_tags


def run_offline_selftest(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Synthesize a V19 non-truncated 3840x2560 MP4 + M01.XML + rtmd bundle & simulated session across all 3 bodies."""
    plan = build_conformance_plan(body="all", repo_root=repo_root)
    orig_kits_dir = studio_cli.KITS_DIR
    try:
        studio_cli.KITS_DIR = repo_root / "kits"
        manifests = studio_cli._load_manifests()
        body_results: dict[str, Any] = {}
        all_ok = bool(plan.get("ok", False))

        with tempfile.TemporaryDirectory(prefix="og_conf_plan_selftest_") as tmp:
            root = Path(tmp)
            for body_id in BODY_ORDER:
                kit_dir, man = manifests[body_id]
                v19 = (man.get("steps") or {}).get("V19") or {}
                v19_sha = str(v19.get("sha256") or "")
                v19_prefix = v19_sha[:8]
                model_name = str(man.get("camera") or body_id).split(" ")[0]
                if body_id == "a7s3_501":
                    model_name = "ILCE-7SM3"
                elif body_id == "fx3_702":
                    model_name = "ILME-FX3"
                elif body_id == "zve1_202":
                    model_name = "ZV-E1"

                body_tmp = root / body_id
                clips_dir = body_tmp / "clips"
                clip_root = clips_dir / "OPEN_GATE"
                stock_root = clips_dir / "STOCK"
                session_dir = body_tmp / "sessions"
                report_out = body_tmp / "report_out"
                clip_root.mkdir(parents=True, exist_ok=True)
                stock_root.mkdir(parents=True, exist_ok=True)
                session_dir.mkdir(parents=True, exist_ok=True)

                # 1. V19 non-truncated 3840x2560 MP4 + M01.XML + rtmd
                xml_og = bcc.build_synthetic_xml(
                    3840, 2560, "hvc1", "23.976p", aspect_ratio="3:2", manufacturer="Sony", model_name=model_name
                )
                mp4_og_bytes = bcc.build_synthetic_mp4(
                    3840, 2560, "hvc1", 24000, 1001, include_rtmd=True, rtmd_samples=24, embedded_xml=xml_og
                )
                og_mp4_path = clip_root / "C0001.MP4"
                og_xml_path = clip_root / "C0001M01.XML"
                with og_mp4_path.open("wb") as fh:
                    fh.write(mp4_og_bytes)
                with og_xml_path.open("w", encoding="utf8") as fh:
                    fh.write(xml_og)

                # 2. Stock 3840x2160 baseline MP4 + M01.XML
                xml_st = bcc.build_synthetic_xml(
                    3840, 2160, "hvc1", "23.976p", aspect_ratio="16:9", manufacturer="Sony", model_name=model_name
                )
                mp4_st_bytes = bcc.build_synthetic_mp4(
                    3840, 2160, "hvc1", 24000, 1001, include_rtmd=True, rtmd_samples=24, embedded_xml=xml_st
                )
                st_mp4_path = stock_root / "C0007_stock.MP4"
                st_xml_path = stock_root / "C0007_stockM01.XML"
                with st_mp4_path.open("wb") as fh:
                    fh.write(mp4_st_bytes)
                with st_xml_path.open("w", encoding="utf8") as fh:
                    fh.write(xml_st)

                # 3. Simulated (mock) session reflecting V19 Safe Daily 3:2
                now = time.time()
                sim_preflight = {
                    "session_id": f"session_0001_sim_preflight_{body_id}",
                    "timestamp": now - 10.0,
                    "kind": "preflight",
                    "mode": "mock",
                    "body_id": body_id,
                    "state": "stock",
                    "ready": True,
                    "verified": True,
                    "pins_ok": True,
                    "verdict": "VERDICT READY (stock preflight)",
                    "steps_run": ["check"],
                    "active_packs": [],
                }
                sim_closing = {
                    "session_id": f"session_0002_sim_closing_{body_id}",
                    "timestamp": now - 5.0,
                    "kind": "closing_dump",
                    "mode": "mock",
                    "body_id": body_id,
                    "state": "applied",
                    "ready": True,
                    "verified": True,
                    "pins_ok": True,
                    "verdict": "VERDICT READY (open gate applied)",
                    "steps_run": _safe_daily_apply_steps(man),
                    "active_packs": ["core_open_gate", "mp4_3x2", "screen_3x2"],
                }
                with (session_dir / f"session_0001_sim_preflight_{body_id}.json").open("w", encoding="utf8") as fh:
                    json.dump(sim_preflight, fh, indent=2)
                with (session_dir / f"session_0002_sim_closing_{body_id}.json").open("w", encoding="utf8") as fh:
                    json.dump(sim_closing, fh, indent=2)

                # 4. Run bionz_clip_check.py on the V19 clip and directory
                clip_rep, _ = bcc.inspect_clip(og_mp4_path, xml_path=og_xml_path, expect="open-gate", body=body_id)
                embedded_xml = bcc._extract_embedded_xml(
                    bcc.read_mp4_metadata_boxes(og_mp4_path)[1] + bcc.read_mp4_metadata_boxes(og_mp4_path)[3],
                    len(bcc.read_mp4_metadata_boxes(og_mp4_path)[1] + bcc.read_mp4_metadata_boxes(og_mp4_path)[3]),
                )
                emb_ok, emb_tags = _verify_nrt_xml_complete(embedded_xml or "", 3840, 2560)
                side_ok, side_tags = _verify_nrt_xml_complete(_read_text(og_xml_path), 3840, 2560)
                nrt_xml_complete = bool(emb_ok and side_ok)

                # 5. Run studio_report.py (FIELD_REPORT.md + field_report.json)
                rep_rc, rep_payload = studio_report.build_field_report(
                    body_id=body_id,
                    manifests=manifests,
                    verify_pins_fn=studio_cli.verify_body_pins,
                    session_dir=session_dir,
                    clips_dir=clips_dir,
                    out_dir=report_out,
                    gyro_app="Gyroflow (offline selftest)",
                    notes=f"Offline V19 ({v19_prefix}) non-truncated NRT XML selftest.",
                )
                md_path = Path(rep_payload["markdown_path"])
                json_path = Path(rep_payload["json_path"])
                report_json_data = _read_json(json_path) if json_path.is_file() else {}
                md_text = _read_text(md_path) if md_path.is_file() else ""

                body_ok = bool(
                    clip_rep.get("ok")
                    and clip_rep.get("vprf_3x2")
                    and clip_rep.get("xml_3x2") is True
                    and clip_rep.get("embedded_xml_present")
                    and clip_rep.get("rtmd_gyro_present")
                    and clip_rep.get("rtmd_klv_detected")
                    and nrt_xml_complete
                    and rep_rc == 0
                    and rep_payload.get("ok")
                    and rep_payload.get("pins_ok")
                    and rep_payload.get("clips_scanned") == 2
                    and rep_payload.get("clips_passed") == 2
                    and rep_payload.get("clips_failed") == 0
                    and md_path.is_file()
                    and json_path.is_file()
                    and "3840x2560" in md_text
                    and report_json_data.get("clips_summary", {}).get("ok") is True
                )
                if not body_ok:
                    all_ok = False

                body_results[body_id] = {
                    "ok": body_ok,
                    "v19_file": v19.get("file"),
                    "v19_sha256_prefix": v19_prefix,
                    "clip_check_ok": bool(clip_rep.get("ok")),
                    "vprf_3x2": bool(clip_rep.get("vprf_3x2")),
                    "xml_3x2": clip_rep.get("xml_3x2"),
                    "embedded_xml_present": bool(clip_rep.get("embedded_xml_present")),
                    "rtmd_gyro_present": bool(clip_rep.get("rtmd_gyro_present")),
                    "rtmd_samples": clip_rep.get("rtmd_samples"),
                    "nrt_xml_complete": nrt_xml_complete,
                    "embedded_nrt_tags": emb_tags,
                    "sidecar_nrt_tags": side_tags,
                    "report_ok": bool(rep_rc == 0 and rep_payload.get("ok")),
                    "clips_scanned": rep_payload.get("clips_scanned"),
                    "clips_passed": rep_payload.get("clips_passed"),
                    "clips_failed": rep_payload.get("clips_failed"),
                    "pins_ok": bool(rep_payload.get("pins_ok")),
                    "field_report_md_sha256": hashlib.sha256(md_text.encode("utf8")).hexdigest()[:16],
                    "field_report_json_bytes": json_path.stat().st_size if json_path.is_file() else 0,
                }

        return {
            "ok": all_ok,
            "selftest": True,
            "simulated_session_mode": "mock",
            "bodies_checked": list(BODY_ORDER),
            "plan_ok": bool(plan.get("ok")),
            "results": body_results,
        }
    finally:
        studio_cli.KITS_DIR = orig_kits_dir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--body",
        choices=("zve1_202", "a7s3_501", "fx3_702", "all"),
        default="all",
        help="Target camera body or 'all' (default: all)",
    )
    ap.add_argument("--json", action="store_true", help="Emit JSON output")
    ap.add_argument(
        "--offline-selftest",
        action="store_true",
        help="Synthesize V19 3840x2560 MP4 + M01.XML + rtmd bundles & simulated sessions across all 3 bodies and verify bionz_clip_check + studio_report",
    )
    args = ap.parse_args(argv)

    if args.offline_selftest:
        res = run_offline_selftest()
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            status = "PASS" if res["ok"] else "FAIL"
            print(f"OFFLINE SELFTEST {status}: bodies={','.join(res['bodies_checked'])}")
            for bid, br in res["results"].items():
                print(
                    f"  - {bid}: ok={br['ok']} v19={br['v19_sha256_prefix']} "
                    f"nrt_xml_complete={br['nrt_xml_complete']} clips={br['clips_passed']}/{br['clips_scanned']} "
                    f"report_ok={br['report_ok']}"
                )
        return 0 if res["ok"] else 1

    plan = build_conformance_plan(body=args.body)
    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print(render_plan_markdown(plan), end="")
    return 0 if plan.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
