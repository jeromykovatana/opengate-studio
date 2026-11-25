#!/usr/bin/env python3
"""Sony OpenGate Studio CLI: multi-body pin check, 5-gate mock preflight, apply/putback & clip check."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
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

BODY_ORDER = ("zve1_202", "a7s3_501", "fx3_702")
OPTIONAL_PACK_ORDER = ("mp4_3x2", "hdmi32", "high_bitrate", "xavc_si", "screen_3x2", "fx3_playback")
DEFAULT_SESSION_DIR = Path(tempfile.gettempdir()) / "opengate_studio_sessions"


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
            data = json.loads(man_path.read_text(encoding="utf8"))
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
            return json.loads(p.read_text(encoding="utf8"))
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


def _latest_session_record(session_dir: Path, body_id: str) -> dict[str, Any] | None:
    if not session_dir.is_dir():
        return None
    matches: list[tuple[float, str, dict[str, Any]]] = []
    for p in session_dir.glob("session_*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf8"))
        except (OSError, ValueError):
            continue
        if rec.get("body_id") == body_id:
            matches.append((float(rec.get("timestamp") or 0.0), p.name, rec))
    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return matches[0][2]


def _latest_preflight_session(session_dir: Path, body_id: str) -> dict[str, Any] | None:
    if not session_dir.is_dir():
        return None
    matches: list[tuple[float, str, dict[str, Any]]] = []
    for p in session_dir.glob("session_*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf8"))
        except (OSError, ValueError):
            continue
        if rec.get("body_id") == body_id:
            matches.append((float(rec.get("timestamp") or 0.0), p.name, rec))
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for _, _, rec in matches:
        if rec.get("kind") == "putback":
            return None
        if rec.get("kind") in ("preflight", "dump", "closing_dump"):
            return rec
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

        if "mp4_3x2" in selected:
            steps_run.extend(packs["mp4_3x2"]["apply_steps"])
            active_packs.append("mp4_3x2")
        else:
            steps_run.extend(packs["mp4_3x2"]["fallback_apply_steps"])

        for p in ("hdmi32", "high_bitrate", "xavc_si", "screen_3x2", "fx3_playback"):
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
        for p in ("fx3_playback", "screen_3x2", "xavc_si", "high_bitrate", "hdmi32"):
            if p in selected and p in packs:
                steps_run.extend(packs[p]["putback_steps"])

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
    pin_res = verify_body_pins(kit_dir, man)
    if not pin_res["ok"]:
        sid = _write_session(session_dir, {
            "kind": "preflight",
            "body_id": body_id,
            "ready": False,
            "state": "not_ready",
            "verdict": "VERDICT NOT READY (pin verification failed)",
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
        "body_id": body_id,
        "ready": ready,
        "state": out_state,
        "verdict": verdict,
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

    last = _latest_preflight_session(session_dir, body_id)
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
        "body_id": body_id,
        "ready": True,
        "state": "applied",
        "verdict": closing_verdict,
        "active_packs": active_packs,
        "steps_run": steps_run,
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
        "body_id": body_id,
        "ready": True,
        "state": "stock",
        "verdict": "VERDICT READY (stock preflight)",
        "active_packs": [],
        "steps_run": steps_run,
        "pins_ok": True,
    })

    return 0, {
        "ok": True,
        "body_id": body_id,
        "steps_run": steps_run,
        "state": "stock",
    }


def cmd_latest_session(body_id: str, session_dir: Path) -> tuple[int, dict[str, Any]]:
    manifests = _load_manifests()
    if body_id not in manifests:
        return 1, {"ok": False, "error": f"Unknown body {body_id!r}"}

    rec = _latest_session_record(session_dir, body_id)
    if rec is None:
        return 0, {
            "ok": True,
            "found": False,
            "body_id": body_id,
            "session_id": None,
            "kind": None,
            "ready": False,
            "state": "unknown",
            "verdict": "",
            "active_packs": [],
            "steps_run": [],
        }

    return 0, {
        "ok": True,
        "found": True,
        "body_id": body_id,
        "session_id": rec.get("session_id"),
        "kind": rec.get("kind"),
        "ready": bool(rec.get("ready", False)),
        "state": str(rec.get("state") or "unknown"),
        "verdict": str(rec.get("verdict") or ""),
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

    p_latest = sub.add_parser("latest-session", help="Read newest session state for a body")
    p_latest.add_argument("--body", required=True)
    p_latest.add_argument("--session-dir", type=Path, default=DEFAULT_SESSION_DIR)
    p_latest.add_argument("--json", action="store_true")

    p_prep = sub.add_parser("prepare-live-command", help="Write executable Terminal .command wrapper without touching USB")
    p_prep.add_argument("--action", required=True, choices=("preflight", "dump", "apply", "putback"))
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
    elif args.cmd == "latest-session":
        rc, payload = cmd_latest_session(args.body, args.session_dir)
    elif args.cmd == "prepare-live-command":
        rc, payload = cmd_prepare_live_command(args.action, args.body, args.packs, args.session_dir)
    elif args.cmd == "check-clip":
        rc, payload = cmd_check_clip(args.mp4_path, args.xml, args.body, args.expect)
    else:
        rc, payload = 2, {"ok": False, "error": f"Unsupported command {args.cmd}"}

    print(json.dumps(payload, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main())
