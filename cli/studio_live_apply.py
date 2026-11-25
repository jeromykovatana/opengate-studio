#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive live USB orchestrator for Sony OpenGate Studio (preflight, dump, apply, putback)."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
CT1_DIR = REPO_ROOT / "transport" / "camera_tests" / "CT1_usb_first_contact"
STEP_RUNNER = HERE / "studio_step_run.py"
LISTER = CT1_DIR / "ct1_stage2_service.py"

for _p in (HERE, CT1_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ct1_common as c  # noqa: E402
import studio_cli  # noqa: E402
import studio_step_run as ssr  # noqa: E402

BODY_STILLS_HINT = {
    "zve1_202": "Stills mode (press Still/Movie/S&Q button until Stills)",
    "a7s3_501": "Stills mode (turn physical mode dial to M / A / S / P)",
    "fx3_702": "a still-image mode (press MODE, choose Manual Exposure / Program Auto, press centre)",
}

BODY_MOVIE_HINT = {
    "zve1_202": "MOVIE mode (press Still/Movie/S&Q button; XAVC HS 4K or XAVC S 4K at 24p/23.98p)",
    "a7s3_501": "MOVIE mode (turn physical mode dial to Movie; XAVC HS 4K or XAVC S 4K at 24p/23.98p)",
    "fx3_702": "Movie mode (press MODE -> Movie; XAVC HS 4K or XAVC S 4K at 24p/23.98p)",
}


def say(text: str = "") -> None:
    print(text, flush=True)


def private_root() -> Path:
    return Path(os.environ.get("OPENGATE_CAMERA_PRIVATE") or c.PRIVATE_ROOT)


def ct6_sessions() -> list[tuple[Path, dict[str, Any]]]:
    root = private_root()
    out: list[tuple[Path, dict[str, Any]]] = []
    if root.is_dir():
        for folder in sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith("CT6_")), reverse=True):
            try:
                out.append((folder, json.loads((folder / "manifest.json").read_text(encoding="utf8"))))
            except (OSError, ValueError):
                continue
    return out


def last_result_sha() -> str | None:
    for _, man in ct6_sessions():
        try:
            return man["results"]["ct6"]["result"]["sha256"]
        except (KeyError, TypeError):
            continue
    return None


def latest_ct6_outcome() -> tuple[str | None, dict[str, Any] | None]:
    for _, man in ct6_sessions():
        res = man.get("results", {})
        f = (res.get("ct6", {}).get("result") or {}).get("s3")
        return (res.get("which"), f) if f else (res.get("which"), None)
    return None, None


def usb_state() -> str:
    r = subprocess.run(
        [sys.executable, "-I", "-B", str(LISTER), "--list"],
        capture_output=True,
        text=True,
        encoding="utf8",
        errors="replace",
        cwd=str(LISTER.parent),
    )
    m = re.search(r"libusb sees: (\d+) Sony mass-storage device\(s\).*?, (\d+) Sony service device\(s\)", r.stdout)
    if not m:
        return "other"
    msc, senser = int(m.group(1)), int(m.group(2))
    if msc == 1 and senser == 0:
        return "drive"
    if senser:
        return "service"
    return "other"


def wait_for_drive(body_id: str, first: bool, timeout: int = 600) -> bool:
    asked = False
    end = time.time() + timeout
    while usb_state() != "drive":
        if not asked:
            say()
            if first:
                say(
                    f"Camera is not showing as a USB drive. Power on in {BODY_STILLS_HINT[body_id]}, "
                    "connect USB (USB Connection = Mass Storage)."
                )
            else:
                say(">>> Unplug the USB cable from the camera and plug it in again.")
                say(">>> Do NOT power the camera off or pull the battery: that would leave the steps half done.")
            say("Waiting for the camera (Ctrl+C to stop) ...")
            asked = True
        if time.time() > end:
            return False
        time.sleep(2)
    return True


def wait_for_replug(timeout: int = 900) -> bool:
    end = time.time() + timeout
    while usb_state() != "other":
        if time.time() > end:
            return False
        time.sleep(1)
    while usb_state() != "drive":
        if time.time() > end:
            return False
        time.sleep(2)
    return True


def run_step_dry(body_id: str, which: str) -> None:
    say()
    say(f"--- {body_id} {which}, what the session would send:")
    r = subprocess.run(
        [sys.executable, "-I", "-B", str(STEP_RUNNER), "--body", body_id, which, "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf8",
        errors="replace",
    )
    say((r.stdout or r.stderr).rstrip())
    if r.returncode != 0:
        raise SystemExit(r.returncode)


def run_step_live(body_id: str, which: str, firmware: str, writes_memory: bool) -> int:
    cmd = [
        sys.executable,
        "-I",
        "-B",
        str(STEP_RUNNER),
        "--body",
        body_id,
        which,
        "--go",
        "--firmware-shown",
        firmware,
    ]
    if writes_memory:
        cmd.append("--writes-memory")
    clear = last_result_sha()
    if clear:
        cmd.extend(["--clear-result", clear])
    return subprocess.run(cmd).returncode


def confirm_firmware(fw: str) -> None:
    if input(f"Firmware version shown in camera menu ({fw}): ").strip() != fw:
        raise SystemExit(f"Not {fw}. Nothing was sent.")


def run_readonly(action: str, body_id: str, man: dict[str, Any], session_dir: Path, dry_run: bool) -> int:
    which = "check" if action == "preflight" else "dump"
    fw = str(man["firmware"])
    entry = man["readonly"][which]
    say(f"{man['camera']} ({body_id}) firmware {fw} — read-only {action} ({which}: {entry['file']}, sha256 {entry['sha256'][:16]}...)")

    if dry_run:
        run_step_dry(body_id, which)
        say()
        say("Dry run only: nothing was sent to any device.")
        return 0

    confirm_firmware(fw)
    if not wait_for_drive(body_id, first=True):
        raise SystemExit("The camera did not show up as a USB drive. Nothing was sent.")

    rc = run_step_live(body_id, which, fw, writes_memory=False)
    got_which, facts = latest_ct6_outcome()
    if rc == 0 and got_which == which and facts:
        ready = bool(facts.get("ready", False))
        state = str(facts.get("state") or "not_ready")
        verdict = str(facts.get("verdict") or "VERDICT NOT READY")
        sid = studio_cli._write_session(session_dir, {
            "kind": action,
            "body_id": body_id,
            "mode": "live_usb",
            "ready": ready,
            "state": state,
            "verdict": verdict,
            "pins_ok": True,
            "steps_run": [which],
            "active_packs": [],
        })
        say()
        say(f"Recorded {action} session {sid} in {session_dir}: {verdict} (state={state}, ready={ready})")
        return 0

    studio_cli._write_session(session_dir, {
        "kind": action,
        "body_id": body_id,
        "mode": "live_usb",
        "ready": False,
        "state": "not_ready",
        "verdict": "VERDICT NOT READY (session failed or incomplete)",
        "pins_ok": True,
        "steps_run": [which],
        "active_packs": [],
    })
    return rc or 1


def run_write_flow(
    action: str,
    body_id: str,
    man: dict[str, Any],
    packs_arg: str | None,
    session_dir: Path,
    dry_run: bool,
    no_movie_session: bool,
) -> int:
    fw = str(man["firmware"])
    saved_active: list[str] = []
    if action == "putback" and packs_arg is None:
        latest = studio_cli._latest_session_record(session_dir, body_id)
        if latest:
            saved_active = list(latest.get("active_packs") or [])

    try:
        steps_run, active_packs = studio_cli.resolve_pack_plan(man, action, packs_arg, saved_active_packs=saved_active)
    except ValueError as err:
        raise SystemExit(f"Invalid --packs: {err}")

    kit_dir = studio_cli.KITS_DIR / body_id
    steps_meta = man.get("steps", {})
    for k in steps_run:
        if k not in steps_meta:
            raise SystemExit(f"Step {k} missing from {body_id} manifest. Nothing was sent.")
        p = kit_dir / steps_meta[k]["file"]
        if not p.is_file() or studio_cli._sha256_file(p) != steps_meta[k]["sha256"]:
            raise SystemExit(f"{p.name} missing or SHA-256 mismatch. Nothing was sent.")

    applying = action == "apply"
    say(f"{man['camera']} ({body_id}) firmware {fw}, {action}: {len(steps_run)} step(s)")
    for n, k in enumerate(steps_run, 1):
        say(f"  {n}. {k}  {steps_meta[k]['summary']}  ({steps_meta[k]['sha256'][:16]}...)")
    if applying and not no_movie_session:
        say("  then one closing read-only session (dump) in Movie mode.")

    if dry_run:
        for k in steps_run:
            run_step_dry(body_id, k)
        say()
        say("Dry run only: nothing was sent to any device.")
        return 0

    if applying:
        last_pre = studio_cli._latest_preflight_session(session_dir, body_id)
        if last_pre is None or last_pre.get("ready") is not True:
            detail = (
                "no preflight session found"
                if last_pre is None
                else f"newest preflight ({last_pre.get('session_id')}) is not ready: {last_pre.get('verdict')}"
            )
            raise SystemExit(f"Refusing apply: {detail}. Run read-only preflight first.")

    say()
    say("This WRITES into running camera RAM ONLY (volatile; battery pull >= 10s restores stock).")
    say("KEEP THE CAMERA SWITCHED ON from step 1 until the script finishes.")
    if applying:
        say(f"Camera must be cold-booted (battery pulled >= 10s), powered on in {BODY_STILLS_HINT[body_id]}, and not yet switched to Movie mode.")
    else:
        say(f"Camera must be powered on in {BODY_STILLS_HINT[body_id]} (if C2/C3 aspect cycle is applied, cycle preview back to 3:2 first).")

    confirm_firmware(fw)
    if input("Type YES to write to the camera's volatile RAM: ").strip() != "YES":
        raise SystemExit("Not confirmed. Nothing was sent.")

    completed_steps: list[str] = []
    for n, k in enumerate(steps_run, 1):
        if not wait_for_drive(body_id, first=(n == 1)):
            raise SystemExit(f"Camera did not appear as USB drive before step {n} ({k}).")
        say()
        say("=" * 78)
        say(f"Step {n} of {len(steps_run)}: {k} — {steps_meta[k]['summary']}")
        rc = run_step_live(body_id, k, fw, writes_memory=True)
        which, facts = latest_ct6_outcome()
        if body_id == "zve1_202" and k == "L14" and which == k and facts and facts.get("outcome") == "NOTHING WRITTEN":
            say("Step L14 wrote nothing (movie buffer open); remaining steps are put back, cold boot clears rawbuf_size.")
            completed_steps.append(k)
            continue
        if rc != 0 or which != k or not facts or not facts.get("ok"):
            if body_id == "zve1_202" and k == "L13" and which == k and facts and facts.get("outcome") == "NOTHING WRITTEN":
                say("STOPPED at step 1 (L13): movie buffer already open. Pull battery >= 10s, power on in Stills, and retry.")
            else:
                reason = "session did not finish" if (rc != 0 or which != k or not facts) else f"outcome {facts.get('outcome')}"
                say(f"STOPPED at step {n} ({k}): {reason}. Pull battery >= 10s to return to clean stock.")
            raise SystemExit(1)
        completed_steps.append(k)

    say()
    say(f"All {len(completed_steps)} step(s) passed ({action}).")

    if applying:
        closing_verdict = "VERDICT READY (open gate applied)"
        closing_ready = True
        if not no_movie_session:
            say()
            say("=" * 78)
            say("Closing read-only session (dump in Movie mode):")
            say(">>> 1. Unplug the USB cable.")
            say(f">>> 2. Switch camera to {BODY_MOVIE_HINT[body_id]}.")
            say(">>> 3. Plug the USB cable back in while in Movie mode.")
            say("Waiting for unplug and replug (Ctrl+C to skip; patches remain applied) ...")
            if wait_for_replug():
                rc_dump = run_step_live(body_id, "dump", fw, writes_memory=False)
                d_which, d_facts = latest_ct6_outcome()
                if rc_dump == 0 and d_which == "dump" and d_facts:
                    closing_verdict = str(d_facts.get("verdict") or closing_verdict)
                    closing_ready = bool(d_facts.get("ready", True))
                else:
                    say("Closing dump did not complete; patches remain applied.")
            else:
                say("Timed out waiting for replug; patches remain applied.")

        sid = studio_cli._write_session(session_dir, {
            "kind": "closing_dump",
            "body_id": body_id,
            "mode": "live_usb",
            "ready": closing_ready,
            "state": "applied" if closing_ready else "not_ready",
            "verdict": closing_verdict,
            "active_packs": active_packs,
            "steps_run": completed_steps,
            "pins_ok": True,
        })
        say(f"Recorded apply session {sid} in {session_dir}: {closing_verdict}")
        say("Record ONLY in XAVC HS 4K / XAVC S 4K / XAVC S-I 4K at 24p (23.98p) while applied (60p crashes).")
        if body_id == "fx3_702":
            if "fx3_playback" in active_packs:
                say("FX3 playback fix (P29) is applied (untested on hardware): test 1 normal 16:9 clip first, then 1 open-gate clip; if it errors, NEVER retry (retrying freezes until battery pull).")
            else:
                say("WARNING (FX3 7.02): Do NOT play back open-gate clips in-camera without fx3_playback (P29) — retrying 'Unable to display' freezes the camera until battery pull.")
        say("To restore 100% stock: pull battery for >= 10 seconds (or run putback).")
        return 0

    sid = studio_cli._write_session(session_dir, {
        "kind": "putback",
        "body_id": body_id,
        "mode": "live_usb",
        "ready": True,
        "state": "stock",
        "verdict": "VERDICT READY (stock preflight)",
        "active_packs": [],
        "steps_run": completed_steps,
        "pins_ok": True,
    })
    say(f"Recorded putback session {sid} in {session_dir}: state=stock")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("preflight", "dump", "apply", "putback"))
    ap.add_argument("--body", required=True, choices=tuple(ssr.BODY_CONFIG))
    ap.add_argument("--packs", default=None, help="Comma-separated packs for apply/putback")
    ap.add_argument("--session-dir", type=Path, default=studio_cli.DEFAULT_SESSION_DIR)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-movie-session", action="store_true")
    args = ap.parse_args(argv)

    kit_dir, man = ssr.load_body_manifest(args.body)
    pin_res = studio_cli.verify_body_pins(kit_dir, man)
    if not pin_res["ok"]:
        raise SystemExit(f"Kit pin verification failed for {args.body}: {pin_res['mismatches']}")

    if args.action in ("preflight", "dump"):
        return run_readonly(args.action, args.body, man, args.session_dir, args.dry_run)
    return run_write_flow(args.action, args.body, man, args.packs, args.session_dir, args.dry_run, args.no_movie_session)


if __name__ == "__main__":
    sys.exit(main())
