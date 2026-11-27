#!/usr/bin/env python3
"""OpenGate Studio CLI: multi-body pin check, 5-gate mock preflight, apply/putback & clip check."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
KITS_DIR = REPO_ROOT / "kits"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import bionz_clip_check as bcc  # noqa: E402
import studio_conformance  # noqa: E402
import studio_creator  # noqa: E402
import studio_report  # noqa: E402

try:
    import studio_gyro  # type: ignore[import-not-found]  # noqa: E402
except ImportError:
    studio_gyro = None  # type: ignore[assignment]

BODY_ORDER = ("zve1_202", "a7s3_501", "fx3_702", "a7c_203", "zve10_203")
OPTIONAL_PACK_ORDER = ("mp4_3x2", "raster_2560", "hdmi32", "high_bitrate", "xavc_si", "screen_3x2", "fx3_playback")
DEFAULT_SESSION_DIR = Path(tempfile.gettempdir()) / "opengate_studio_sessions"
LIVE_PREFLIGHT_TTL_SECONDS = 900
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def preflight_ttl_seconds() -> int:
    raw = os.environ.get("OPENGATE_PREFLIGHT_TTL_SECONDS", "").strip()
    if raw:
        try:
            val = int(raw)
            if val > 0:
                return val
        except ValueError:
            pass
    return LIVE_PREFLIGHT_TTL_SECONDS


def compute_kit_manifest_sha256(kit_dir: Path) -> str:
    return _sha256_file(kit_dir / "manifest.json")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifests() -> dict[str, tuple[Path, dict[str, Any]]]:
    if not KITS_DIR.is_dir():
        return {}
    found: dict[str, tuple[Path, dict[str, Any]]] = {}
    for sub in sorted(KITS_DIR.iterdir()):
        man_path = sub / "manifest.json"
        if sub.is_dir() and man_path.is_file():
            with man_path.open("r", encoding="utf8") as f:
                data = json.load(f)
            bid = data.get("body_id", sub.name)
            found[bid] = (sub, data)
    ordered: dict[str, tuple[Path, dict[str, Any]]] = {}
    for bid in BODY_ORDER:
        if bid in found:
            ordered[bid] = found.pop(bid)
    for bid in sorted(found):
        ordered[bid] = found[bid]
    return ordered


def _extract_entry_file_sha(entry: Any) -> tuple[str | None, str | None]:
    if isinstance(entry, dict):
        fname = entry.get("filename") or entry.get("file") or entry.get("so") or entry.get("name")
        sha = entry.get("sha256")
        return fname, sha
    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
        return str(entry[0]), str(entry[1])
    return None, None


def verify_body_pins(kit_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    checked = 0
    mismatches: list[str] = []
    expected_files: dict[str, str] = {}

    for group_key in ("readonly", "steps"):
        group = manifest.get(group_key, {})
        if isinstance(group, dict):
            for step_name, entry in group.items():
                fname, sha = _extract_entry_file_sha(entry)
                if not fname or not sha:
                    mismatches.append(f"{group_key}.{step_name}: missing filename/sha256")
                    continue
                expected_files[fname] = sha

    dev_info = manifest.get("device_info")
    if isinstance(dev_info, dict):
        fname, sha = _extract_entry_file_sha(dev_info)
        if fname and sha:
            expected_files[fname] = sha
    elif isinstance(dev_info, str):
        p = kit_dir / dev_info
        if not p.is_file():
            mismatches.append(f"missing {dev_info}")
        else:
            checked += 1

    for fname, want_sha in sorted(expected_files.items()):
        p = kit_dir / fname
        checked += 1
        if not p.is_file():
            mismatches.append(f"missing {fname}")
            continue
        got_sha = _sha256_file(p)
        if got_sha != want_sha:
            mismatches.append(f"{fname}: sha256 {got_sha} != {want_sha}")

    return {
        "ok": len(mismatches) == 0 and checked > 0,
        "checked_files": checked,
        "mismatches": mismatches,
    }


def cmd_list_bodies() -> tuple[int, dict[str, Any]]:
    manifests = _load_manifests()
    bodies: list[dict[str, Any]] = []
    for bid, (kit_dir, man) in manifests.items():
        pin_res = verify_body_pins(kit_dir, man)
        bodies.append({
            "body_id": bid,
            "camera": man.get("camera", bid),
            "firmware": man.get("firmware", ""),
            "version_txt": man.get("version_txt", ""),
            "toolchain": man.get("toolchain", ""),
            "pins_ok": pin_res["ok"],
            "packs": man.get("packs", {}),
        })
    return 0, {"bodies": bodies}


def cmd_verify_pins(body: str | None) -> tuple[int, dict[str, Any]]:
    manifests = _load_manifests()
    if body is not None:
        if body not in manifests:
            return 1, {"ok": False, "checked_files": 0, "error": f"Unknown body {body!r}", "bodies": {}}
        targets = {body: manifests[body]}
    else:
        targets = manifests

    if not targets:
        return 1, {"ok": False, "checked_files": 0, "error": "No kit manifests found", "bodies": {}}

    per_body: dict[str, Any] = {}
    total_checked = 0
    all_ok = True
    for bid, (kit_dir, man) in targets.items():
        res = verify_body_pins(kit_dir, man)
        per_body[bid] = res
        total_checked += res["checked_files"]
        if not res["ok"]:
            all_ok = False
    return (0 if all_ok else 1), {"ok": all_ok, "checked_files": total_checked, "bodies": per_body}


def _mock_state_path(session_dir: Path, body_id: str) -> Path:
    return session_dir / f"mock_state_{body_id}.json"


def _read_mock_state(session_dir: Path, body_id: str) -> dict[str, Any]:
    p = _mock_state_path(session_dir, body_id)
    if p.is_file():
        try:
            with p.open("r", encoding="utf8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {"state": "stock", "active_packs": []}


def _write_mock_state(session_dir: Path, body_id: str, state: str, active_packs: list[str]) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    _mock_state_path(session_dir, body_id).write_text(
        json.dumps({"body_id": body_id, "state": state, "active_packs": active_packs}, indent=2),
        encoding="utf8",
    )


def _write_session(session_dir: Path, payload: dict[str, Any]) -> str:
    session_dir.mkdir(parents=True, exist_ok=True)
    existing = [p for p in session_dir.glob("session_*.json")]
    seq = len(existing) + 1
    sid = f"session_{time.time_ns()}_{seq:04d}"
    record = {"session_id": sid, "timestamp": time.time(), **payload}
    (session_dir / f"{sid}.json").write_text(json.dumps(record, indent=2), encoding="utf8")
    return sid


def _session_mode(rec: dict[str, Any]) -> str:
    mode = rec.get("mode")
    if isinstance(mode, str) and mode:
        return mode
    return "mock"


def _load_sorted_sessions(session_dir: Path) -> list[tuple[float, str, dict[str, Any]]]:
    if not session_dir.is_dir():
        return []
    matches: list[tuple[float, str, dict[str, Any]]] = []
    for p in session_dir.glob("session_*.json"):
        try:
            with p.open("r", encoding="utf8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict):
            matches.append((float(rec.get("timestamp") or 0.0), p.name, rec))
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return matches


def _latest_session_record(
    session_dir: Path,
    body_id: str,
    *,
    mode_filter: str | None = None,
) -> dict[str, Any] | None:
    for _, _, rec in _load_sorted_sessions(session_dir):
        if rec.get("body_id") != body_id:
            continue
        if mode_filter in ("live_usb", "mock") and _session_mode(rec) != mode_filter:
            continue
        return rec
    return None


def _latest_preflight_session(
    session_dir: Path,
    body_id: str,
    *,
    mode_filter: str | None = "mock",
) -> dict[str, Any] | None:
    for _, _, rec in _load_sorted_sessions(session_dir):
        if rec.get("body_id") != body_id:
            continue
        if mode_filter in ("live_usb", "mock") and _session_mode(rec) != mode_filter:
            continue
        if rec.get("kind") == "putback":
            return None
        if rec.get("kind") in ("preflight", "dump", "closing_dump", "express_apply"):
            return rec
    return None


def validate_live_preflight_for_apply(
    session_dir: Path,
    body_id: str,
    kit_dir: Path,
    manifest: dict[str, Any],
    *,
    now: float | None = None,
) -> tuple[bool, dict[str, Any] | None, str]:
    """Fail-closed authorization gate for live USB apply."""
    records = _load_sorted_sessions(session_dir)
    target_idx: int | None = None
    latest_for_body: dict[str, Any] | None = None
    for idx, (_, _, rec) in enumerate(records):
        if rec.get("body_id") == body_id:
            target_idx = idx
            latest_for_body = rec
            break

    if latest_for_body is None or target_idx is None:
        return False, None, "no live preflight session found"

    # Global invalidation: any newer mock run or newer live session for another body invalidates authorization.
    for _, _, newer in records[:target_idx]:
        newer_mode = _session_mode(newer)
        if newer_mode == "mock":
            return (
                False,
                None,
                "live preflight authorization invalidated by a newer mock run; run fresh read-only preflight",
            )
        if newer_mode == "live_usb" and newer.get("body_id") != body_id:
            return (
                False,
                None,
                f"live preflight authorization invalidated by a newer live session for {newer.get('body_id')}; run fresh read-only preflight",
            )

    sid = latest_for_body.get("session_id") or "<unknown>"
    if _session_mode(latest_for_body) != "live_usb":
        return False, None, f"latest session ({sid}) is not a live_usb session (mode={_session_mode(latest_for_body)!r})"

    kind = latest_for_body.get("kind")
    if kind not in ("preflight", "dump"):
        return False, None, f"latest live session ({sid}) has kind={kind!r}; fresh stock preflight required"

    if latest_for_body.get("ready") is not True or latest_for_body.get("verified") is False:
        return False, None, f"latest preflight ({sid}) is not ready: {latest_for_body.get('verdict')}"

    if latest_for_body.get("state") != "stock":
        return False, None, f"latest preflight ({sid}) state is {latest_for_body.get('state')!r}, expected 'stock'"

    if latest_for_body.get("pins_ok") is not True:
        return False, None, f"latest preflight ({sid}) did not pass kit pin verification"

    want_manifest_sha = compute_kit_manifest_sha256(kit_dir)
    got_manifest_sha = latest_for_body.get("manifest_sha256")
    if not isinstance(got_manifest_sha, str) or got_manifest_sha != want_manifest_sha:
        return False, None, f"latest preflight ({sid}) kit manifest hash mismatch or missing; re-run preflight"

    boot_nonce = latest_for_body.get("boot_nonce")
    if not isinstance(boot_nonce, str) or not boot_nonce.strip():
        return False, None, f"latest preflight ({sid}) is missing boot_nonce"

    pre_sha = latest_for_body.get("preflight_result_sha256")
    if not isinstance(pre_sha, str) or not _HEX64_RE.fullmatch(pre_sha):
        return False, None, f"latest preflight ({sid}) is missing valid preflight_result_sha256"

    cam_id = latest_for_body.get("camera_identity")
    if not isinstance(cam_id, dict):
        return False, None, f"latest preflight ({sid}) is missing camera_identity"

    dev_info = manifest.get("device_info")
    want_dev_sha = dev_info.get("sha256") if isinstance(dev_info, dict) else None
    if not want_dev_sha or cam_id.get("device_info_sha256") != want_dev_sha:
        return False, None, f"latest preflight ({sid}) camera DeviceInfo.xml identity mismatch"

    has_usb_id = bool(cam_id.get("msc_usb_id") or cam_id.get("service_usb_id"))
    if not has_usb_id:
        return False, None, f"latest preflight ({sid}) is missing live USB camera identity"

    expires_at = latest_for_body.get("expires_at")
    if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
        return False, None, f"latest preflight ({sid}) is missing expires_at timestamp"

    ts = float(latest_for_body.get("timestamp") or 0.0)
    cur_now = time.time() if now is None else float(now)
    if cur_now > float(expires_at):
        return False, None, f"latest preflight ({sid}) has expired; run fresh read-only preflight"
    if cur_now < ts - 5.0:
        return False, None, f"latest preflight ({sid}) timestamp is in the future (clock skew); run fresh read-only preflight"

    return True, latest_for_body, "ok"


def resolve_fused_preset(
    manifest: dict[str, Any],
    kit_dir: Path,
    action: str,
    target_packs: list[str],
) -> tuple[str, str] | None:
    """Return (preset_name, step_id) if target_packs matches a fused preset whose .so is pinned and on disk."""
    fused = manifest.get("fused_presets")
    if not isinstance(fused, dict):
        return None
    step_key = "apply_step" if action in ("apply", "express-apply") else "putback_step"
    steps_map = manifest.get("steps", {})
    want_packs = sorted(set(target_packs))
    for preset_name, preset in fused.items():
        if not isinstance(preset, dict):
            continue
        preset_packs = preset.get("packs")
        if not isinstance(preset_packs, list) or sorted(set(preset_packs)) != want_packs:
            continue
        step_id = preset.get(step_key)
        if not isinstance(step_id, str) or step_id not in steps_map:
            continue
        entry = steps_map[step_id]
        fname, want_sha = _extract_entry_file_sha(entry)
        if not fname or not want_sha:
            continue
        so_path = kit_dir / fname
        if so_path.is_file() and _sha256_file(so_path) == want_sha:
            return str(preset_name), step_id
    return None


def resolve_pack_plan(
    manifest: dict[str, Any],
    action: str,
    packs_arg: str | None,
    saved_active_packs: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Resolve ordered steps and active_packs for apply or putback."""
    packs = manifest.get("packs", {})
    if action == "apply":
        selected = _parse_packs(packs_arg, packs)
        steps_run: list[str] = list(packs["core_open_gate"]["apply_steps"])
        active_packs = ["core_open_gate"]

        if "mp4_3x2" in packs:
            if "mp4_3x2" in selected:
                steps_run.extend(packs["mp4_3x2"]["apply_steps"])
                active_packs.append("mp4_3x2")
            else:
                steps_run.extend(packs["mp4_3x2"]["fallback_apply_steps"])

        for p in ("raster_2560", "hdmi32", "high_bitrate", "xavc_si", "screen_3x2", "fx3_playback"):
            if p in selected and p in packs:
                steps_run.extend(packs[p]["apply_steps"])
                active_packs.append(p)
        return steps_run, active_packs

    if action == "putback":
        if packs_arg is not None:
            selected = _parse_packs(packs_arg, packs)
        else:
            saved = saved_active_packs or []
            selected = [p for p in saved if p != "core_open_gate" and p in packs] or [
                p for p in OPTIONAL_PACK_ORDER if p in packs
            ]
        steps_run = []
        for p in ("fx3_playback", "screen_3x2", "xavc_si", "high_bitrate", "hdmi32", "raster_2560"):
            if p in selected and p in packs:
                steps_run.extend(packs[p]["putback_steps"])

        if "mp4_3x2" in packs:
            if "mp4_3x2" in selected:
                steps_run.extend(packs["mp4_3x2"]["putback_steps"])
            else:
                steps_run.extend(packs["mp4_3x2"].get("fallback_putback_steps", ["L20"]))

        steps_run.extend(packs["core_open_gate"]["putback_steps"])
        return steps_run, []

    raise ValueError(f"Unsupported pack-plan action: {action!r}")


def _require_offline_mode(live_usb: bool) -> dict[str, Any] | None:
    if live_usb:
        return {
            "ok": False,
            "error": "--live-usb requires explicit interactive user approval and an active Sony-PMCA-RE service-mode session; refusing unattended USB access.",
        }
    return None


def cmd_preflight(body_id: str, mock_state: str | None, session_dir: Path, live_usb: bool) -> tuple[int, dict[str, Any]]:
    usb_err = _require_offline_mode(live_usb)
    if usb_err:
        return 1, usb_err

    manifests = _load_manifests()
    if body_id not in manifests:
        return 1, {"ok": False, "ready": False, "state": "not_ready", "verdict": f"VERDICT NOT READY (unknown body {body_id})"}

    kit_dir, man = manifests[body_id]
    manifest_sha = compute_kit_manifest_sha256(kit_dir)
    pin_res = verify_body_pins(kit_dir, man)
    if not pin_res["ok"]:
        sid = _write_session(session_dir, {
            "kind": "preflight",
            "mode": "mock",
            "body_id": body_id,
            "ready": False,
            "verified": False,
            "state": "not_ready",
            "verdict": "VERDICT NOT READY (pin verification failed)",
            "manifest_sha256": manifest_sha,
            "pins_ok": False,
        })
        return 1, {
            "ok": False,
            "body_id": body_id,
            "ready": False,
            "state": "not_ready",
            "verdict": "VERDICT NOT READY (pin verification failed)",
            "session_id": sid,
            "mismatches": pin_res["mismatches"],
        }

    eff_state = mock_state if mock_state is not None else _read_mock_state(session_dir, body_id).get("state", "stock")
    if mock_state is not None:
        _write_mock_state(session_dir, body_id, eff_state, [])

    if eff_state == "stock":
        ready, out_state, verdict = True, "stock", "VERDICT READY (stock preflight)"
    elif eff_state == "applied":
        ready, out_state, verdict = True, "applied", "VERDICT READY (open gate applied)"
    else:
        ready, out_state, verdict = False, "not_ready", "VERDICT NOT READY (warm power-switch mixed state: pull battery >= 10s)"

    sid = _write_session(session_dir, {
        "kind": "preflight",
        "mode": "mock",
        "body_id": body_id,
        "ready": ready,
        "verified": bool(ready),
        "state": out_state,
        "verdict": verdict,
        "manifest_sha256": manifest_sha,
        "pins_ok": True,
    })
    return 0, {
        "ok": True,
        "body_id": body_id,
        "ready": ready,
        "state": out_state,
        "verdict": verdict,
        "session_id": sid,
    }


def _parse_packs(packs_arg: str | None, available: dict[str, Any]) -> list[str]:
    if not packs_arg:
        return [
            p
            for p in OPTIONAL_PACK_ORDER
            if p in available and available[p].get("default_enabled", True) is not False
        ]
    requested = [p.strip() for p in packs_arg.split(",") if p.strip()]
    unknown = [p for p in requested if p != "core_open_gate" and p not in available]
    if unknown:
        raise ValueError(f"Unknown pack(s): {', '.join(unknown)}")
    return [p for p in requested if p != "core_open_gate"]


def cmd_apply(body_id: str, packs_arg: str | None, session_dir: Path, live_usb: bool) -> tuple[int, dict[str, Any]]:
    usb_err = _require_offline_mode(live_usb)
    if usb_err:
        return 1, usb_err

    manifests = _load_manifests()
    if body_id not in manifests:
        return 1, {"ok": False, "error": f"Unknown body {body_id!r}"}

    kit_dir, man = manifests[body_id]
    pin_res = verify_body_pins(kit_dir, man)
    if not pin_res["ok"]:
        return 1, {"ok": False, "error": "Pin verification failed", "mismatches": pin_res["mismatches"]}

    last = _latest_preflight_session(session_dir, body_id, mode_filter="mock")
    if last is None or last.get("ready") is not True:
        reason = "no preflight session found" if last is None else f"last preflight session ({last.get('session_id')}) is not ready: {last.get('verdict')}"
        return 1, {"ok": False, "error": f"Refusing apply: {reason}"}

    try:
        steps_run, active_packs = resolve_pack_plan(man, "apply", packs_arg)
    except ValueError as err:
        return 1, {"ok": False, "error": str(err)}

    # Confirm every step in steps_run is pinned in manifest
    steps_map = man.get("steps", {})
    missing = [s for s in steps_run if s not in steps_map]
    if missing:
        return 1, {"ok": False, "error": f"Steps missing from manifest: {missing}"}

    _write_mock_state(session_dir, body_id, "applied", active_packs)
    closing_verdict = "VERDICT READY (open gate applied)"
    _write_session(session_dir, {
        "kind": "closing_dump",
        "mode": "mock",
        "body_id": body_id,
        "ready": True,
        "verified": True,
        "state": "applied",
        "verdict": closing_verdict,
        "active_packs": active_packs,
        "steps_run": steps_run,
        "manifest_sha256": compute_kit_manifest_sha256(kit_dir),
        "pins_ok": True,
    })

    return 0, {
        "ok": True,
        "body_id": body_id,
        "steps_run": steps_run,
        "closing_dump_verdict": closing_verdict,
        "active_packs": active_packs,
    }


def cmd_putback(body_id: str, packs_arg: str | None, session_dir: Path, live_usb: bool) -> tuple[int, dict[str, Any]]:
    usb_err = _require_offline_mode(live_usb)
    if usb_err:
        return 1, usb_err

    manifests = _load_manifests()
    if body_id not in manifests:
        return 1, {"ok": False, "error": f"Unknown body {body_id!r}"}

    kit_dir, man = manifests[body_id]
    pin_res = verify_body_pins(kit_dir, man)
    if not pin_res["ok"]:
        return 1, {"ok": False, "error": "Pin verification failed", "mismatches": pin_res["mismatches"]}

    try:
        saved = _read_mock_state(session_dir, body_id).get("active_packs", [])
        steps_run, _ = resolve_pack_plan(man, "putback", packs_arg, saved_active_packs=saved)
    except ValueError as err:
        return 1, {"ok": False, "error": str(err)}

    steps_map = man.get("steps", {})
    missing = [s for s in steps_run if s not in steps_map]
    if missing:
        return 1, {"ok": False, "error": f"Steps missing from manifest: {missing}"}

    _write_mock_state(session_dir, body_id, "stock", [])
    _write_session(session_dir, {
        "kind": "putback",
        "mode": "mock",
        "body_id": body_id,
        "ready": True,
        "verified": True,
        "state": "stock",
        "verdict": "VERDICT READY (stock preflight)",
        "active_packs": [],
        "steps_run": steps_run,
        "manifest_sha256": compute_kit_manifest_sha256(kit_dir),
        "pins_ok": True,
    })

    return 0, {
        "ok": True,
        "body_id": body_id,
        "steps_run": steps_run,
        "state": "stock",
    }


def _resolve_putback_target_packs(
    man: dict[str, Any],
    packs_arg: str | None,
    saved_active_packs: list[str] | None = None,
) -> list[str]:
    packs = man.get("packs", {})
    if packs_arg is not None:
        return ["core_open_gate", *_parse_packs(packs_arg, packs)]
    saved = saved_active_packs or []
    if saved:
        return list(saved)
    return ["core_open_gate", *[p for p in OPTIONAL_PACK_ORDER if p in packs]]


def cmd_express_apply(
    body_id: str,
    packs_arg: str | None,
    mock_state: str | None,
    session_dir: Path,
    live_usb: bool,
) -> tuple[int, dict[str, Any]]:
    usb_err = _require_offline_mode(live_usb)
    if usb_err:
        return 1, usb_err

    manifests = _load_manifests()
    if body_id not in manifests:
        return 1, {"ok": False, "error": f"Unknown body {body_id!r}"}

    kit_dir, man = manifests[body_id]
    manifest_sha = compute_kit_manifest_sha256(kit_dir)
    pin_res = verify_body_pins(kit_dir, man)
    if not pin_res["ok"]:
        return 1, {"ok": False, "error": "Pin verification failed", "mismatches": pin_res["mismatches"]}

    eff_state = mock_state if mock_state is not None else _read_mock_state(session_dir, body_id).get("state", "stock")
    if eff_state not in ("stock", "applied"):
        if mock_state is not None:
            _write_mock_state(session_dir, body_id, eff_state, [])
        bad_verdict = "VERDICT NOT READY (warm power-switch mixed state: pull battery >= 10s)"
        sid = _write_session(session_dir, {
            "kind": "express_apply",
            "mode": "mock",
            "body_id": body_id,
            "ready": False,
            "verified": False,
            "state": "not_ready",
            "verdict": bad_verdict,
            "manifest_sha256": manifest_sha,
            "pins_ok": True,
        })
        return 1, {
            "ok": False,
            "body_id": body_id,
            "session_id": sid,
            "ready": False,
            "verified": False,
            "state": "not_ready",
            "verdict": bad_verdict,
            "error": f"Refusing express-apply: {bad_verdict}",
        }

    try:
        steps_run, active_packs = resolve_pack_plan(man, "apply", packs_arg)
    except ValueError as err:
        return 1, {"ok": False, "error": str(err)}

    fused = resolve_fused_preset(man, kit_dir, "apply", active_packs)
    if fused is not None:
        steps_run = [fused[1]]
        closing_kind = "fused_readback"
    else:
        steps_map = man.get("steps", {})
        missing = [s for s in steps_run if s not in steps_map]
        if missing:
            return 1, {"ok": False, "error": f"Steps missing from manifest: {missing}"}
        closing_kind = "in_place_check"

    _write_mock_state(session_dir, body_id, "applied", active_packs)
    closing_verdict = "VERDICT READY (open gate applied)"
    sid = _write_session(session_dir, {
        "kind": "express_apply",
        "mode": "mock",
        "body_id": body_id,
        "ready": True,
        "verified": True,
        "state": "applied",
        "verdict": closing_verdict,
        "closing_kind": closing_kind,
        "active_packs": active_packs,
        "steps_run": steps_run,
        "manifest_sha256": manifest_sha,
        "pins_ok": True,
    })

    return 0, {
        "ok": True,
        "body_id": body_id,
        "session_id": sid,
        "steps_run": steps_run,
        "closing_dump_verdict": closing_verdict,
        "verdict": closing_verdict,
        "state": "applied",
        "ready": True,
        "verified": True,
        "closing_kind": closing_kind,
        "active_packs": active_packs,
    }


def cmd_express_putback(
    body_id: str,
    packs_arg: str | None,
    mock_state: str | None,
    session_dir: Path,
    live_usb: bool,
) -> tuple[int, dict[str, Any]]:
    usb_err = _require_offline_mode(live_usb)
    if usb_err:
        return 1, usb_err

    manifests = _load_manifests()
    if body_id not in manifests:
        return 1, {"ok": False, "error": f"Unknown body {body_id!r}"}

    kit_dir, man = manifests[body_id]
    manifest_sha = compute_kit_manifest_sha256(kit_dir)
    pin_res = verify_body_pins(kit_dir, man)
    if not pin_res["ok"]:
        return 1, {"ok": False, "error": "Pin verification failed", "mismatches": pin_res["mismatches"]}

    if mock_state is not None and mock_state not in ("stock", "applied", "mixed_powerswitch"):
        return 1, {"ok": False, "error": f"Unsupported mock_state: {mock_state!r}"}

    try:
        saved = _read_mock_state(session_dir, body_id).get("active_packs", [])
        steps_run, _ = resolve_pack_plan(man, "putback", packs_arg, saved_active_packs=saved)
        target_packs = _resolve_putback_target_packs(man, packs_arg, saved_active_packs=saved)
    except ValueError as err:
        return 1, {"ok": False, "error": str(err)}

    fused = resolve_fused_preset(man, kit_dir, "putback", target_packs)
    if fused is not None:
        steps_run = [fused[1]]
    else:
        steps_map = man.get("steps", {})
        missing = [s for s in steps_run if s not in steps_map]
        if missing:
            return 1, {"ok": False, "error": f"Steps missing from manifest: {missing}"}

    _write_mock_state(session_dir, body_id, "stock", [])
    verdict = "VERDICT READY (stock preflight)"
    sid = _write_session(session_dir, {
        "kind": "putback",
        "mode": "mock",
        "body_id": body_id,
        "ready": True,
        "verified": True,
        "state": "stock",
        "verdict": verdict,
        "closing_kind": "stock_check",
        "active_packs": [],
        "steps_run": steps_run,
        "manifest_sha256": manifest_sha,
        "pins_ok": True,
    })

    return 0, {
        "ok": True,
        "body_id": body_id,
        "session_id": sid,
        "steps_run": steps_run,
        "state": "stock",
        "verdict": verdict,
        "ready": True,
        "verified": True,
        "closing_kind": "stock_check",
        "active_packs": [],
    }


def _map_sony_usb_product(product_name: str | None) -> tuple[str | None, bool, str | None]:
    if not product_name:
        return None, False, None
    p_upper = product_name.strip().upper()
    if "ILME-FX3A" in p_upper:
        return None, True, "ILME-FX3A is not supported by FX3 7.02 kits"
    if "ILME-FX3" in p_upper:
        return "fx3_702", False, None
    if "ZV-E10" in p_upper:
        return "zve10_203", False, None
    if p_upper == "ZV-E1" or re.search(r"(?<![A-Z0-9])ZV-E1(?![A-Z0-9])", p_upper):
        return "zve1_202", False, None
    if "ILCE-7SM3" in p_upper:
        return "a7s3_501", False, None
    if p_upper == "ILCE-7C" or re.search(r"(?<![A-Z0-9])ILCE-7C(?![A-Z0-9])", p_upper):
        return "a7c_203", False, None
    return None, False, None


def parse_ioreg_usb_text(ioreg_text: str) -> dict[str, Any]:
    """Parse passive `ioreg -p IOUSB -l -w 0` output for connected Sony cameras."""
    devices: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []

    node_re = re.compile(r"^([| ]*)\+-o\s+(.+)$")
    vid_re = re.compile(r'"idVendor"\s*=\s*(0x[0-9a-fA-F]+|\d+)')
    pid_re = re.compile(r'"idProduct"\s*=\s*(0x[0-9a-fA-F]+|\d+)')
    prod_re = re.compile(r'"(?:USB Product Name|kUSBProductString)"\s*=\s*"([^"]*)"')
    iface_re = re.compile(r'"bInterfaceClass"\s*=\s*(0x[0-9a-fA-F]+|\d+)')

    for line in ioreg_text.splitlines():
        m_node = node_re.match(line)
        if m_node:
            indent = len(m_node.group(1))
            rest = m_node.group(2)
            while stack and stack[-1]["indent"] >= indent:
                stack.pop()
            is_usb_device = (
                "<class IOUSBHostDevice" in rest
                or "<class AppleUSBHostDevice" in rest
                or "<class IOUSBDevice" in rest
                or (
                    "<class " not in rest
                    and "Interface" not in rest
                    and "MassStorage" not in rest
                    and "IOMedia" not in rest
                )
            )
            if is_usb_device:
                dev = {
                    "indent": indent,
                    "vendor": None,
                    "product": None,
                    "product_name": None,
                    "iface_classes": [],
                    "has_msc_driver": False,
                }
                devices.append(dev)
                stack.append(dev)
            elif stack and "IOUSBMassStorage" in rest:
                stack[-1]["has_msc_driver"] = True
            continue

        if not stack:
            continue
        cur = stack[-1]
        if m_vid := vid_re.search(line):
            if cur["vendor"] is None:
                cur["vendor"] = int(m_vid.group(1), 0)
        if m_pid := pid_re.search(line):
            if cur["product"] is None:
                cur["product"] = int(m_pid.group(1), 0)
        if m_prod := prod_re.search(line):
            if cur["product_name"] is None:
                cur["product_name"] = m_prod.group(1)
        if m_iface := iface_re.search(line):
            cur["iface_classes"].append(int(m_iface.group(1), 0))
        if "IOUSBMassStorage" in line:
            cur["has_msc_driver"] = True

    sony_devs = [d for d in devices if d.get("vendor") == 0x054C]
    if not sony_devs:
        return {
            "ok": True,
            "detected": False,
            "body_id": None,
            "usb_product_name": None,
            "usb_mode": None,
            "is_fx3a_blocked": False,
            "warning": None,
        }

    # Prefer a Sony device matching a known camera or in msc/service mode
    chosen = sony_devs[0]
    for cand in sony_devs:
        bid, blocked, _ = _map_sony_usb_product(cand.get("product_name"))
        if bid is not None or blocked:
            chosen = cand
            break

    pid = chosen.get("product")
    ifaces = chosen.get("iface_classes") or []
    if pid in (0x0336, 0x02A9) or 255 in ifaces:
        usb_mode = "service"
    elif 8 in ifaces or chosen.get("has_msc_driver"):
        usb_mode = "msc"
    else:
        usb_mode = "other"

    prod_name = chosen.get("product_name")
    body_id, is_fx3a_blocked, warning = _map_sony_usb_product(prod_name)
    return {
        "ok": True,
        "detected": True,
        "body_id": body_id,
        "usb_product_name": prod_name,
        "usb_mode": usb_mode,
        "is_fx3a_blocked": is_fx3a_blocked,
        "warning": warning,
    }


def cmd_detect_usb_camera() -> tuple[int, dict[str, Any]]:
    mock_path = os.environ.get("OPENGATE_MOCK_IOREG_FILE", "").strip()
    ioreg_text = ""
    if mock_path:
        p = Path(mock_path)
        if p.is_file():
            ioreg_text = p.read_text(encoding="utf8", errors="replace")
    elif sys.platform == "darwin":
        try:
            proc = subprocess.run(
                ["ioreg", "-p", "IOUSB", "-l", "-w", "0"],
                capture_output=True,
                text=True,
                encoding="utf8",
                errors="replace",
                timeout=5,
            )
            if proc.returncode == 0:
                ioreg_text = proc.stdout
        except (OSError, subprocess.SubprocessError):
            ioreg_text = ""
    return 0, parse_ioreg_usb_text(ioreg_text)


def cmd_latest_session(
    body_id: str,
    session_dir: Path,
    mode_filter: str | None = None,
) -> tuple[int, dict[str, Any]]:
    manifests = _load_manifests()
    if body_id not in manifests:
        return 1, {"ok": False, "error": f"Unknown body {body_id!r}"}

    eff_filter = None if mode_filter in (None, "all") else mode_filter
    rec = _latest_session_record(session_dir, body_id, mode_filter=eff_filter)
    if rec is None:
        return 0, {
            "ok": True,
            "found": False,
            "body_id": body_id,
            "session_id": None,
            "kind": None,
            "mode": None,
            "ready": False,
            "verified": False,
            "state": "unknown",
            "verdict": "",
            "manifest_sha256": None,
            "active_packs": [],
            "steps_run": [],
        }

    return 0, {
        "ok": True,
        "found": True,
        "body_id": body_id,
        "session_id": rec.get("session_id"),
        "kind": rec.get("kind"),
        "mode": _session_mode(rec),
        "ready": bool(rec.get("ready", False)),
        "verified": bool(rec.get("verified", rec.get("ready", False))),
        "state": str(rec.get("state") or "unknown"),
        "verdict": str(rec.get("verdict") or ""),
        "manifest_sha256": rec.get("manifest_sha256"),
        "active_packs": list(rec.get("active_packs") or []),
        "steps_run": list(rec.get("steps_run") or []),
    }


def cmd_prepare_live_command(
    action: str,
    body_id: str,
    packs_arg: str | None,
    session_dir: Path,
) -> tuple[int, dict[str, Any]]:
    manifests = _load_manifests()
    if body_id not in manifests:
        return 1, {"ok": False, "error": f"Unknown body {body_id!r}"}

    _, man = manifests[body_id]
    if packs_arg is not None:
        try:
            _parse_packs(packs_arg, man.get("packs", {}))
        except ValueError as err:
            return 1, {"ok": False, "error": str(err)}

    session_dir_abs = session_dir.resolve()
    session_dir_abs.mkdir(parents=True, exist_ok=True)

    runner_sh = (REPO_ROOT / "macos" / "run_live_terminal.sh").resolve()
    cmd_parts = ["/bin/bash", str(runner_sh), action, "--body", body_id]
    if packs_arg is not None and packs_arg.strip():
        normalized = ",".join(p.strip() for p in packs_arg.split(",") if p.strip())
        if normalized:
            cmd_parts.extend(["--packs", normalized])
    cmd_parts.extend(["--session-dir", str(session_dir_abs)])

    preview = " ".join(shlex.quote(part) for part in cmd_parts)
    cmd_file = (session_dir_abs / f"run_live_{action}_{body_id}.command").resolve()
    script_body = (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        f"cd {shlex.quote(str(REPO_ROOT.resolve()))}\n"
        f"exec {preview}\n"
    )
    cmd_file.write_bytes(script_body.encode("utf8"))
    os.chmod(cmd_file, 0o755)

    return 0, {
        "ok": True,
        "action": action,
        "body_id": body_id,
        "command_file": str(cmd_file),
        "preview": preview,
    }


def cmd_check_clip(mp4_path: Path, xml_path: Path | None, body: str | None, expect: str) -> tuple[int, dict[str, Any]]:
    try:
        src = mp4_path.resolve(strict=True)
        xml_p = xml_path.resolve(strict=True) if xml_path else None
        report, _ = bcc.inspect_clip(src, xml_path=xml_p, expect=expect, body=body)
        return (0 if report["ok"] else 1), report
    except Exception as err:
        return 2, {"ok": False, "error": str(err)}


def cmd_repair_nrt_xml(
    mp4_path: Path,
    out_mp4: Path,
    body: str | None,
    out_xml: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    try:
        payload = bcc.repair_nrt_xml_copy(
            mp4_path,
            out_mp4,
            body=body,
            out_xml_path=out_xml,
        )
        return (0 if payload.get("ok", False) else 1), payload
    except Exception as err:
        return 2, {"ok": False, "error": str(err)}


def cmd_gyro_diagnose(mp4_path: Path, xml_path: Path | None, body: str | None, expect: str) -> tuple[int, dict[str, Any]]:
    if studio_gyro is None:
        return 2, {"ok": False, "error": "studio_gyro module is not available"}
    try:
        src = mp4_path.resolve(strict=True)
        xml_p = xml_path.resolve(strict=True) if xml_path else None
        report = studio_gyro.diagnose_clip_gyro(src, xml_path=xml_p, body=body, expect=expect)
        return 0, report
    except Exception as err:
        return 2, {"ok": False, "error": str(err)}


def cmd_install_gyroflow_presets(list_only: bool, target_dir: Path | None, body: str | None) -> tuple[int, dict[str, Any]]:
    if studio_gyro is None:
        return 2, {"ok": False, "error": "studio_gyro module is not available"}
    try:
        if list_only:
            payload = studio_gyro.list_gyroflow_presets()
            if body:
                filtered = [p for p in payload.get("presets", []) if p.get("body_id") == body]
                payload = {**payload, "presets": filtered}
            return (0 if payload.get("ok", True) else 1), payload
        payload = studio_gyro.install_gyroflow_presets(target_dir=target_dir, body_id=body)
        return (0 if payload.get("ok", True) else 1), payload
    except Exception as err:
        return 2, {"ok": False, "error": str(err)}


def cmd_ingest_batch(root_dir: Path, expect: str, body: str | None, recursive: bool) -> tuple[int, dict[str, Any]]:
    try:
        payload = studio_creator.ingest_card_batch(root_dir, expect=expect, body=body, recursive=recursive)
        return (0 if payload.get("ok", False) else 1), payload
    except Exception as err:
        return 2, {"ok": False, "error": str(err)}


def cmd_generate_proxies(
    inputs: list[Path],
    out_dir: Path,
    aspect: str,
    resolution: str,
    codec: str,
    preserve_gyro_sidecar: bool,
    dry_run: bool,
) -> tuple[int, dict[str, Any]]:
    try:
        payload = studio_creator.generate_proxies(
            inputs=inputs,
            out_dir=out_dir,
            aspect=aspect,
            resolution=resolution,
            codec=codec,
            preserve_gyro_sidecar=preserve_gyro_sidecar,
            dry_run=dry_run,
        )
        return (0 if payload.get("ok", False) else 1), payload
    except Exception as err:
        return 2, {"ok": False, "error": str(err)}


def cmd_build_report(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    manifests = _load_manifests()
    return studio_report.build_field_report(
        body_id=args.body,
        manifests=manifests,
        verify_pins_fn=verify_body_pins,
        session_dir=args.session_dir,
        clips_dir=args.clips_dir,
        out_dir=args.out_dir,
        media_card=args.media_card,
        lens=args.lens,
        ambient_c=args.ambient_c,
        soak_minutes=args.soak_minutes,
        thermal_result=args.thermal_result,
        reactivation_seconds=args.reactivation_seconds,
        af_desqueeze_notes=args.af_desqueeze_notes,
        gyro_app=args.gyro_app,
        editor_app=args.editor_app,
        notes=args.notes,
    )


def cmd_conformance_audit(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    try:
        payload = studio_conformance.audit_conformance_bundle(
            clips_dir=args.clips_dir,
            body_id=args.body,
            session_dir=args.session_dir,
            out_dir=args.out_dir,
            measured_readout_ms=args.measured_readout_ms,
            gyroflow_ok=args.gyroflow_ok,
            catalyst_ok=args.catalyst_ok,
            nle_ok=args.nle_ok,
            playback_ok=args.playback_ok,
            thermal_ok=args.thermal_ok,
        )
        return (0 if payload.get("ok", False) else 1), payload
    except Exception as err:
        return 2, {"ok": False, "error": str(err)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="Output JSON")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list-bodies", help="List supported bodies, pins status, and packs")
    p_list.add_argument("--json", action="store_true")

    p_pins = sub.add_parser("verify-pins", help="Verify SHA-256 pins of kit artifacts")
    p_pins.add_argument("--body", help="Optional body_id filter")
    p_pins.add_argument("--json", action="store_true")

    p_pre = sub.add_parser("preflight", help="Run read-only preflight gate (mock by default)")
    p_pre.add_argument("--body", required=True)
    p_pre.add_argument("--mock-camera", action="store_true")
    p_pre.add_argument("--mock-state", choices=("stock", "applied", "mixed_powerswitch"), default=None)
    p_pre.add_argument("--session-dir", type=Path, default=DEFAULT_SESSION_DIR)
    p_pre.add_argument("--live-usb", action="store_true")
    p_pre.add_argument("--json", action="store_true")

    p_app = sub.add_parser("apply", help="Apply selected modular volatile RAM packs")
    p_app.add_argument("--body", required=True)
    p_app.add_argument("--packs", default=None, help="Comma-separated packs (e.g. mp4_3x2,screen_3x2,hdmi32)")
    p_app.add_argument("--mock-camera", action="store_true")
    p_app.add_argument("--session-dir", type=Path, default=DEFAULT_SESSION_DIR)
    p_app.add_argument("--live-usb", action="store_true")
    p_app.add_argument("--json", action="store_true")

    p_put = sub.add_parser("putback", help="Put back volatile RAM patches to stock")
    p_put.add_argument("--body", required=True)
    p_put.add_argument("--packs", default=None)
    p_put.add_argument("--mock-camera", action="store_true")
    p_put.add_argument("--session-dir", type=Path, default=DEFAULT_SESSION_DIR)
    p_put.add_argument("--live-usb", action="store_true")
    p_put.add_argument("--json", action="store_true")

    p_exp_app = sub.add_parser("express-apply", help="Single-session express apply (mock by default)")
    p_exp_app.add_argument("--body", required=True)
    p_exp_app.add_argument("--packs", default=None)
    p_exp_app.add_argument("--mock-camera", action="store_true")
    p_exp_app.add_argument("--mock-state", choices=("stock", "applied", "mixed_powerswitch"), default=None)
    p_exp_app.add_argument("--session-dir", type=Path, default=DEFAULT_SESSION_DIR)
    p_exp_app.add_argument("--live-usb", action="store_true")
    p_exp_app.add_argument("--json", action="store_true")

    p_exp_put = sub.add_parser("express-putback", help="Single-session express putback (mock by default)")
    p_exp_put.add_argument("--body", required=True)
    p_exp_put.add_argument("--packs", default=None)
    p_exp_put.add_argument("--mock-camera", action="store_true")
    p_exp_put.add_argument("--mock-state", choices=("stock", "applied", "mixed_powerswitch"), default=None)
    p_exp_put.add_argument("--session-dir", type=Path, default=DEFAULT_SESSION_DIR)
    p_exp_put.add_argument("--live-usb", action="store_true")
    p_exp_put.add_argument("--json", action="store_true")

    p_det = sub.add_parser("detect-usb-camera", help="Passively detect connected Sony USB camera via ioreg")
    p_det.add_argument("--json", action="store_true")

    p_latest = sub.add_parser("latest-session", help="Read newest session state for a body")
    p_latest.add_argument("--body", required=True)
    p_latest.add_argument("--session-dir", type=Path, default=DEFAULT_SESSION_DIR)
    p_latest.add_argument("--mode", choices=("all", "live_usb", "mock"), default="all")
    p_latest.add_argument("--json", action="store_true")

    p_prep = sub.add_parser("prepare-live-command", help="Write executable Terminal .command wrapper without touching USB")
    p_prep.add_argument("--action", required=True, choices=("preflight", "dump", "apply", "putback", "express-apply", "express-putback"))
    p_prep.add_argument("--body", required=True)
    p_prep.add_argument("--packs", default=None)
    p_prep.add_argument("--session-dir", type=Path, default=DEFAULT_SESSION_DIR)
    p_prep.add_argument("--json", action="store_true")

    p_clip = sub.add_parser("check-clip", help="Inspect MP4 + XML + rtmd clip via bionz_clip_check")
    p_clip.add_argument("mp4_path", type=Path)
    p_clip.add_argument("--xml", type=Path, default=None)
    p_clip.add_argument("--body", default=None)
    p_clip.add_argument("--expect", choices=("open-gate", "stock"), default="open-gate")
    p_clip.add_argument("--json", action="store_true")

    p_rep_xml = sub.add_parser("repair-nrt-xml", help="Write non-destructive MP4 copy with repaired trailing NRT XML for Gyroflow/Catalyst")
    p_rep_xml.add_argument("mp4_path", type=Path)
    p_rep_xml.add_argument("--out", type=Path, required=True)
    p_rep_xml.add_argument("--out-xml", type=Path, default=None)
    p_rep_xml.add_argument("--body", default=None)
    p_rep_xml.add_argument("--json", action="store_true")

    p_rep = sub.add_parser("build-report", help="Generate Markdown + JSON field-test & reliability report")
    p_rep.add_argument("--body", required=True)
    p_rep.add_argument("--session-dir", type=Path, default=DEFAULT_SESSION_DIR)
    p_rep.add_argument("--clips-dir", type=Path, default=None)
    p_rep.add_argument("--out-dir", type=Path, default=None)
    p_rep.add_argument("--media-card", default="")
    p_rep.add_argument("--lens", default="")
    p_rep.add_argument("--ambient-c", default="")
    p_rep.add_argument("--soak-minutes", default="")
    p_rep.add_argument("--thermal-result", default="")
    p_rep.add_argument("--reactivation-seconds", default="")
    p_rep.add_argument("--af-desqueeze-notes", default="")
    p_rep.add_argument("--gyro-app", default="")
    p_rep.add_argument("--editor-app", default="")
    p_rep.add_argument("--notes", default="")
    p_rep.add_argument("--json", action="store_true")

    p_gyro = sub.add_parser("gyro-diagnose", help="Diagnose Gyroflow & Catalyst readiness for an MP4 + XML clip")
    p_gyro.add_argument("mp4_path", type=Path)
    p_gyro.add_argument("--xml", type=Path, default=None)
    p_gyro.add_argument("--body", default=None)
    p_gyro.add_argument("--expect", choices=("open-gate", "stock"), default="open-gate")
    p_gyro.add_argument("--json", action="store_true")

    p_presets = sub.add_parser("install-gyroflow-presets", help="List or install starter 3:2 Gyroflow lens profiles")
    p_presets.add_argument("--list-only", action="store_true")
    p_presets.add_argument("--target-dir", type=Path, default=None)
    p_presets.add_argument("--body", default=None)
    p_presets.add_argument("--json", action="store_true")

    p_ingest = sub.add_parser("ingest-batch", help="Batch-scan SD card folder for Sony clips and gyro readiness")
    p_ingest.add_argument("root_dir", type=Path)
    p_ingest.add_argument("--expect", choices=("auto", "open-gate", "stock"), default="auto")
    p_ingest.add_argument("--body", default=None)
    p_ingest.add_argument("--no-recursive", action="store_true")
    p_ingest.add_argument("--json", action="store_true")

    p_proxy = sub.add_parser("generate-proxies", help="Generate relink-verified editing proxies without altering originals")
    p_proxy.add_argument("inputs", nargs="+", type=Path)
    p_proxy.add_argument("--out-dir", type=Path, required=True)
    p_proxy.add_argument("--aspect", choices=("3:2", "16:9", "1:1", "9:16", "2.39:1"), default="3:2")
    p_proxy.add_argument("--resolution", choices=("720p", "1080p", "2160p", "4k"), default="1080p")
    p_proxy.add_argument("--codec", choices=("h264", "hevc", "h265", "prores", "prores_proxy", "prores_lt"), default="h264")
    p_proxy.add_argument("--dry-run", action="store_true")
    p_proxy.add_argument("--no-sidecar", action="store_true")
    p_proxy.add_argument("--json", action="store_true")

    p_conf = sub.add_parser("conformance-audit", help="Audit conformance bundle, validate live_usb sessions, and recommend matrix promotions")
    p_conf.add_argument("--body", required=True)
    p_conf.add_argument("--clips-dir", type=Path, required=True)
    p_conf.add_argument("--session-dir", type=Path, default=None)
    p_conf.add_argument("--out-dir", type=Path, default=None)
    p_conf.add_argument("--measured-readout-ms", type=float, default=None)
    p_conf.add_argument("--gyroflow-ok", action=argparse.BooleanOptionalAction, default=None)
    p_conf.add_argument("--catalyst-ok", action=argparse.BooleanOptionalAction, default=None)
    p_conf.add_argument("--nle-ok", action=argparse.BooleanOptionalAction, default=None)
    p_conf.add_argument("--playback-ok", action=argparse.BooleanOptionalAction, default=None)
    p_conf.add_argument("--thermal-ok", action=argparse.BooleanOptionalAction, default=None)
    p_conf.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)
    if args.cmd == "list-bodies":
        rc, payload = cmd_list_bodies()
    elif args.cmd == "verify-pins":
        rc, payload = cmd_verify_pins(args.body)
    elif args.cmd == "preflight":
        rc, payload = cmd_preflight(args.body, args.mock_state, args.session_dir, args.live_usb)
    elif args.cmd == "apply":
        rc, payload = cmd_apply(args.body, args.packs, args.session_dir, args.live_usb)
    elif args.cmd == "putback":
        rc, payload = cmd_putback(args.body, args.packs, args.session_dir, args.live_usb)
    elif args.cmd == "express-apply":
        rc, payload = cmd_express_apply(args.body, args.packs, args.mock_state, args.session_dir, args.live_usb)
    elif args.cmd == "express-putback":
        rc, payload = cmd_express_putback(args.body, args.packs, args.mock_state, args.session_dir, args.live_usb)
    elif args.cmd == "detect-usb-camera":
        rc, payload = cmd_detect_usb_camera()
    elif args.cmd == "latest-session":
        rc, payload = cmd_latest_session(args.body, args.session_dir, mode_filter=args.mode)
    elif args.cmd == "prepare-live-command":
        rc, payload = cmd_prepare_live_command(args.action, args.body, args.packs, args.session_dir)
    elif args.cmd == "check-clip":
        rc, payload = cmd_check_clip(args.mp4_path, args.xml, args.body, args.expect)
    elif args.cmd == "repair-nrt-xml":
        rc, payload = cmd_repair_nrt_xml(args.mp4_path, args.out, args.body, args.out_xml)
    elif args.cmd == "build-report":
        rc, payload = cmd_build_report(args)
    elif args.cmd == "gyro-diagnose":
        rc, payload = cmd_gyro_diagnose(args.mp4_path, args.xml, args.body, args.expect)
    elif args.cmd == "install-gyroflow-presets":
        rc, payload = cmd_install_gyroflow_presets(args.list_only, args.target_dir, args.body)
    elif args.cmd == "ingest-batch":
        rc, payload = cmd_ingest_batch(args.root_dir, args.expect, args.body, not args.no_recursive)
    elif args.cmd == "generate-proxies":
        rc, payload = cmd_generate_proxies(
            args.inputs,
            args.out_dir,
            args.aspect,
            args.resolution,
            args.codec,
            not args.no_sidecar,
            args.dry_run,
        )
    elif args.cmd == "conformance-audit":
        rc, payload = cmd_conformance_audit(args)
    else:
        rc, payload = 2, {"ok": False, "error": f"Unsupported command {args.cmd}"}

    print(json.dumps(payload, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main())
