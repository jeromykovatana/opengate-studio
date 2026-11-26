#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive live USB orchestrator for OpenGate Studio (preflight, dump, apply, putback)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
    "zve1_202": "MOVIE mode (press Still/Movie/S&Q button; XAVC HS 4K, XAVC S 4K, or XAVC S-I 4K at 24p/23.98p, 25p PAL, or 30p/29.97p)",
    "a7s3_501": "MOVIE mode (turn physical mode dial to Movie; XAVC HS 4K, XAVC S 4K, or XAVC S-I 4K at 24p/23.98p, 25p PAL, or 30p/29.97p)",
    "fx3_702": "Movie mode (press MODE -> Movie; XAVC HS 4K, XAVC S 4K, or XAVC S-I 4K at 24p/23.98p, 25p PAL, or 30p/29.97p)",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class CancelledRun(Exception):
    """Raised when the user requests safe cancellation via --cancel-file."""

    def __init__(self, message: str, *, step_index: int | None = None, step_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.step_index = step_index
        self.step_id = step_id


class RunContext:
    """Holds optional event streaming, log teeing, cancellation, and non-interactive confirmation settings."""

    def __init__(
        self,
        *,
        json_events: bool = False,
        events_file: Path | None = None,
        log_file: Path | None = None,
        cancel_file: Path | None = None,
        firmware_confirmed: str | None = None,
        confirm_volatile_ram: bool = False,
        simulate_events: bool = False,
    ) -> None:
        self.json_events = json_events
        self.events_file = events_file
        self.log_file = log_file
        self.cancel_file = cancel_file
        self.firmware_confirmed = firmware_confirmed
        self.confirm_volatile_ram = confirm_volatile_ram
        self.simulate_events = simulate_events
        self._events_fh: Any = None
        self._log_fh: Any = None

    def _ensure_events_fh(self) -> Any:
        if self.events_file is None:
            return None
        if self._events_fh is None:
            self.events_file.parent.mkdir(parents=True, exist_ok=True)
            self._events_fh = self.events_file.open("a", encoding="utf8")
        return self._events_fh

    def _ensure_log_fh(self) -> Any:
        if self.log_file is None:
            return None
        if self._log_fh is None:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_fh = self.log_file.open("a", encoding="utf8")
        return self._log_fh

    def log_line(self, text: str) -> None:
        fh = self._ensure_log_fh()
        if fh is not None:
            fh.write(text + "\n")
            fh.flush()

    def log_raw(self, text: str) -> None:
        fh = self._ensure_log_fh()
        if fh is not None:
            fh.write(text)
            fh.flush()

    def emit(self, event_type: str, **fields: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {"ts": _utc_now_iso(), "type": event_type}
        payload.update(fields)
        if self.json_events or self.events_file is not None:
            encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
            if self.json_events:
                print(f"@OG_EVENT {encoded}", flush=True)
            fh = self._ensure_events_fh()
            if fh is not None:
                fh.write(encoded + "\n")
                fh.flush()
        return payload

    def emit_error(
        self,
        message: str,
        *,
        step_index: int | None = None,
        step_id: str | None = None,
        left_behind_flag: bool = False,
    ) -> dict[str, Any]:
        return self.emit(
            "error",
            step_index=step_index,
            step_id=step_id,
            message=message,
            left_behind=left_behind_flag,
        )

    def is_cancelled(self) -> bool:
        return self.cancel_file is not None and self.cancel_file.exists()

    def check_cancelled(
        self,
        message: str,
        *,
        step_index: int | None = None,
        step_id: str | None = None,
    ) -> None:
        if self.is_cancelled():
            raise CancelledRun(message, step_index=step_index, step_id=step_id)

    def close(self) -> None:
        for fh in (self._events_fh, self._log_fh):
            if fh is not None:
                try:
                    fh.flush()
                    fh.close()
                except OSError:
                    pass
        self._events_fh = None
        self._log_fh = None


_CTX: RunContext | None = None


def _active_ctx(ctx: RunContext | None = None) -> RunContext:
    if ctx is not None:
        return ctx
    if _CTX is not None:
        return _CTX
    return RunContext()


def say(text: str = "") -> None:
    print(text, flush=True)
    if _CTX is not None:
        _CTX.log_line(text)


def _fail(
    ctx: RunContext,
    message: str,
    *,
    step_index: int | None = None,
    step_id: str | None = None,
    left_behind_flag: bool = False,
    exit_code: int = 1,
    already_printed: bool = False,
) -> int:
    ctx.emit_error(
        message,
        step_index=step_index,
        step_id=step_id,
        left_behind_flag=left_behind_flag,
    )
    if not already_printed:
        print(message, file=sys.stderr, flush=True)
        ctx.log_line(message)
    return exit_code


def _drive_prompt_copy(body_id: str, first: bool) -> tuple[str, str]:
    if first:
        return (
            "Connect camera in Stills mode (Mass Storage)",
            f"Power on in {BODY_STILLS_HINT[body_id]}, connect USB-C (USB Connection = Mass Storage).",
        )
    return (
        "Unplug USB-C and plug right back in",
        "Unplug the USB cable from the camera and plug it back in. Do NOT power the camera off or pull the battery.",
    )


def _movie_replug_detail(body_id: str) -> str:
    return (
        f"1. Unplug USB-C. 2. Switch camera to {BODY_MOVIE_HINT[body_id]}. "
        "3. Plug USB-C back in while in Movie mode."
    )


def _sleep_cancelable(
    seconds: float,
    ctx: RunContext,
    *,
    step_index: int | None = None,
    step_id: str | None = None,
    message: str = "Cancelled safely.",
) -> None:
    deadline = time.time() + seconds
    while True:
        ctx.check_cancelled(message, step_index=step_index, step_id=step_id)
        remaining = deadline - time.time()
        if remaining <= 0:
            return
        time.sleep(min(0.25, remaining))


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


def left_behind() -> bool:
    for _, man in ct6_sessions():
        ct6 = man.get("results", {}).get("ct6") or {}
        on_cam = ct6.get("library_on_camera_after")
        return on_cam is True or (on_cam is None and bool(ct6.get("library_sent")))
    return False


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


def wait_for_drive(
    body_id: str,
    first: bool,
    timeout: int = 600,
    *,
    ctx: RunContext | None = None,
    step_index: int | None = None,
    total_steps: int | None = None,
    step_id: str | None = None,
) -> bool:
    active_ctx = _active_ctx(ctx)
    cancel_msg = (
        f"Cancelled safely while waiting for camera before step {step_index} ({step_id})."
        if step_index is not None and step_id is not None
        else "Cancelled safely while waiting for camera."
    )
    asked = False
    end = time.time() + timeout
    while True:
        active_ctx.check_cancelled(cancel_msg, step_index=step_index, step_id=step_id)
        if usb_state() == "drive":
            return True
        if not asked:
            title, detail = _drive_prompt_copy(body_id, first)
            active_ctx.emit(
                "wait_drive",
                first=first,
                step_index=step_index if step_index is not None else 1,
                total_steps=total_steps if total_steps is not None else 1,
                step_id=step_id or "",
                title=title,
                detail=detail,
            )
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
        _sleep_cancelable(2.0, active_ctx, step_index=step_index, step_id=step_id, message=cancel_msg)


def wait_for_replug(timeout: int = 900, *, ctx: RunContext | None = None) -> bool:
    active_ctx = _active_ctx(ctx)
    cancel_msg = "Cancelled safely while waiting for Movie-mode replug (applied patches remain in camera RAM)."
    end = time.time() + timeout
    while True:
        active_ctx.check_cancelled(cancel_msg, step_index=None, step_id="dump")
        if usb_state() == "other":
            break
        if time.time() > end:
            return False
        _sleep_cancelable(1.0, active_ctx, step_index=None, step_id="dump", message=cancel_msg)
    while True:
        active_ctx.check_cancelled(cancel_msg, step_index=None, step_id="dump")
        if usb_state() == "drive":
            return True
        if time.time() > end:
            return False
        _sleep_cancelable(2.0, active_ctx, step_index=None, step_id="dump", message=cancel_msg)


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


def run_step_live(
    body_id: str,
    which: str,
    firmware: str,
    writes_memory: bool,
    *,
    ctx: RunContext | None = None,
) -> int:
    cmd = [
        sys.executable,
        "-u",
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
    active_ctx = _active_ctx(ctx)
    if active_ctx.log_file is None:
        return subprocess.run(cmd).returncode
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        active_ctx.log_raw(line)
    return proc.wait()


def confirm_firmware(fw: str, *, ctx: RunContext | None = None) -> None:
    if input(f"Firmware version shown in camera menu ({fw}): ").strip() != fw:
        msg = f"Not {fw}. Nothing was sent."
        active_ctx = _active_ctx(ctx)
        active_ctx.emit_error(msg, step_index=None, step_id=None, left_behind_flag=False)
        active_ctx.log_line(msg)
        raise SystemExit(msg)


def _simulate_readonly(
    action: str,
    body_id: str,
    man: dict[str, Any],
    which: str,
    summary: str,
    ctx: RunContext,
) -> int:
    fw = str(man["firmware"])
    ctx.emit(
        "plan",
        action=action,
        body_id=body_id,
        camera=man["camera"],
        firmware=fw,
        steps=[{"id": which, "summary": summary}],
        closing_dump=False,
    )
    cancel_msg = f"Cancelled safely before step 1 ({which})."
    ctx.check_cancelled(cancel_msg, step_index=1, step_id=which)
    title, detail = _drive_prompt_copy(body_id, first=True)
    ctx.emit(
        "wait_drive",
        first=True,
        step_index=1,
        total_steps=1,
        step_id=which,
        title=title,
        detail=detail,
    )
    _sleep_cancelable(0.03, ctx, step_index=1, step_id=which, message=cancel_msg)
    ctx.check_cancelled(cancel_msg, step_index=1, step_id=which)
    ctx.emit(
        "step_start",
        step_index=1,
        total_steps=1,
        step_id=which,
        summary=summary,
    )
    say(f"[simulated dry-run] Step 1 of 1: {which} — {summary}")
    time.sleep(0.03)
    ctx.emit(
        "step_done",
        step_index=1,
        total_steps=1,
        step_id=which,
        outcome="DONE",
        ok=True,
    )
    verdict = "VERDICT READY (stock preflight)" if action == "preflight" else "VERDICT READY (simulated dump)"
    sid = f"simulated_{action}_{body_id}"
    ctx.emit(
        "complete",
        ok=True,
        action=action,
        body_id=body_id,
        session_id=sid,
        verdict=verdict,
        state="stock",
        ready=True,
        steps_run=[which],
        active_packs=[],
    )
    say()
    say("Dry run only: nothing was sent to any device.")
    return 0


def run_readonly(
    action: str,
    body_id: str,
    man: dict[str, Any],
    session_dir: Path,
    dry_run: bool,
    *,
    ctx: RunContext | None = None,
) -> int:
    active_ctx = _active_ctx(ctx)
    which = "check" if action == "preflight" else "dump"
    fw = str(man["firmware"])
    entry = man["readonly"][which]
    summary = str(entry.get("summary") or f"Read-only {action} ({which})")
    say(f"{man['camera']} ({body_id}) firmware {fw} — read-only {action} ({which}: {entry['file']}, sha256 {entry['sha256'][:16]}...)")

    if dry_run:
        if active_ctx.simulate_events:
            return _simulate_readonly(action, body_id, man, which, summary, active_ctx)
        run_step_dry(body_id, which)
        say()
        say("Dry run only: nothing was sent to any device.")
        return 0

    if active_ctx.firmware_confirmed is None:
        confirm_firmware(fw, ctx=active_ctx)

    active_ctx.emit(
        "plan",
        action=action,
        body_id=body_id,
        camera=man["camera"],
        firmware=fw,
        steps=[{"id": which, "summary": summary}],
        closing_dump=False,
    )
    cancel_msg = f"Cancelled safely before step 1 ({which})."
    active_ctx.check_cancelled(cancel_msg, step_index=1, step_id=which)

    if not wait_for_drive(body_id, first=True, ctx=active_ctx, step_index=1, total_steps=1, step_id=which):
        return _fail(
            active_ctx,
            "The camera did not show up as a USB drive. Nothing was sent.",
            step_index=1,
            step_id=which,
            left_behind_flag=False,
        )

    active_ctx.check_cancelled(cancel_msg, step_index=1, step_id=which)
    active_ctx.emit(
        "step_start",
        step_index=1,
        total_steps=1,
        step_id=which,
        summary=summary,
    )
    rc = run_step_live(body_id, which, fw, writes_memory=False, ctx=active_ctx)
    got_which, facts = latest_ct6_outcome()
    if rc == 0 and got_which == which and facts:
        ready = bool(facts.get("ready", False))
        state = str(facts.get("state") or "not_ready")
        verdict = str(facts.get("verdict") or "VERDICT NOT READY")
        active_ctx.emit(
            "step_done",
            step_index=1,
            total_steps=1,
            step_id=which,
            outcome="DONE",
            ok=True,
        )
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
        active_ctx.emit(
            "complete",
            ok=True,
            action=action,
            body_id=body_id,
            session_id=sid,
            verdict=verdict,
            state=state,
            ready=ready,
            steps_run=[which],
            active_packs=[],
        )
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
    return _fail(
        active_ctx,
        f"Read-only {action} ({which}) did not complete cleanly.",
        step_index=1,
        step_id=which,
        left_behind_flag=left_behind(),
        exit_code=rc or 1,
    )


def _simulate_write_flow(
    action: str,
    body_id: str,
    man: dict[str, Any],
    steps_run: list[str],
    active_packs: list[str],
    steps_meta: dict[str, Any],
    no_movie_session: bool,
    ctx: RunContext,
) -> int:
    fw = str(man["firmware"])
    applying = action == "apply"
    closing_dump = applying and not no_movie_session
    plan_steps = [{"id": k, "summary": steps_meta[k]["summary"]} for k in steps_run]
    ctx.emit(
        "plan",
        action=action,
        body_id=body_id,
        camera=man["camera"],
        firmware=fw,
        steps=plan_steps,
        closing_dump=closing_dump,
    )
    total = len(steps_run)
    # Keep total simulated runtime comfortably under 0.5s while remaining streamable/cancelable.
    half_delay = min(0.015, 0.11 / max(total, 1))
    for n, k in enumerate(steps_run, 1):
        cancel_msg = f"Cancelled safely before step {n} ({k})."
        ctx.check_cancelled(cancel_msg, step_index=n, step_id=k)
        title, detail = _drive_prompt_copy(body_id, first=(n == 1))
        ctx.emit(
            "wait_drive",
            first=(n == 1),
            step_index=n,
            total_steps=total,
            step_id=k,
            title=title,
            detail=detail,
        )
        _sleep_cancelable(half_delay, ctx, step_index=n, step_id=k, message=cancel_msg)
        ctx.check_cancelled(cancel_msg, step_index=n, step_id=k)
        ctx.emit(
            "step_start",
            step_index=n,
            total_steps=total,
            step_id=k,
            summary=steps_meta[k]["summary"],
        )
        say(f"[simulated dry-run] Step {n} of {total}: {k} — {steps_meta[k]['summary']}")
        time.sleep(half_delay)
        ctx.emit(
            "step_done",
            step_index=n,
            total_steps=total,
            step_id=k,
            outcome="DONE",
            ok=True,
        )

    if closing_dump:
        cancel_msg = "Cancelled safely before Movie-mode closing dump."
        ctx.check_cancelled(cancel_msg, step_index=None, step_id="dump")
        ctx.emit(
            "wait_movie_replug",
            hint=BODY_MOVIE_HINT[body_id],
            title="Switch camera to Movie mode",
            detail=_movie_replug_detail(body_id),
        )
        _sleep_cancelable(0.02, ctx, step_index=None, step_id="dump", message=cancel_msg)
        ctx.check_cancelled(cancel_msg, step_index=None, step_id="dump")
        ctx.emit("closing_dump_start")
        say("[simulated dry-run] Closing read-only session (dump in Movie mode)...")
        time.sleep(0.02)
        ctx.emit(
            "closing_dump_done",
            verdict="VERDICT READY (open gate applied)",
            ready=True,
        )

    if applying:
        ctx.emit(
            "complete",
            ok=True,
            action="apply",
            body_id=body_id,
            session_id=f"simulated_apply_{body_id}",
            verdict="VERDICT READY (open gate applied)",
            state="applied",
            ready=True,
            steps_run=list(steps_run),
            active_packs=list(active_packs),
        )
    else:
        ctx.emit(
            "complete",
            ok=True,
            action="putback",
            body_id=body_id,
            session_id=f"simulated_putback_{body_id}",
            verdict="VERDICT READY (stock preflight)",
            state="stock",
            ready=True,
            steps_run=list(steps_run),
            active_packs=[],
        )
    say()
    say("Dry run only: nothing was sent to any device.")
    return 0


def run_write_flow(
    action: str,
    body_id: str,
    man: dict[str, Any],
    packs_arg: str | None,
    session_dir: Path,
    dry_run: bool,
    no_movie_session: bool,
    *,
    ctx: RunContext | None = None,
) -> int:
    active_ctx = _active_ctx(ctx)
    fw = str(man["firmware"])
    saved_active: list[str] = []
    if action == "putback" and packs_arg is None:
        latest = studio_cli._latest_session_record(session_dir, body_id)
        if latest:
            saved_active = list(latest.get("active_packs") or [])

    try:
        steps_run, active_packs = studio_cli.resolve_pack_plan(man, action, packs_arg, saved_active_packs=saved_active)
    except ValueError as err:
        return _fail(active_ctx, f"Invalid --packs: {err}")

    kit_dir = studio_cli.KITS_DIR / body_id
    steps_meta = man.get("steps", {})
    for k in steps_run:
        if k not in steps_meta:
            return _fail(active_ctx, f"Step {k} missing from {body_id} manifest. Nothing was sent.")
        p = kit_dir / steps_meta[k]["file"]
        if not p.is_file() or studio_cli._sha256_file(p) != steps_meta[k]["sha256"]:
            return _fail(active_ctx, f"{p.name} missing or SHA-256 mismatch. Nothing was sent.")

    applying = action == "apply"
    closing_dump = applying and not no_movie_session
    say(f"{man['camera']} ({body_id}) firmware {fw}, {action}: {len(steps_run)} step(s)")
    for n, k in enumerate(steps_run, 1):
        say(f"  {n}. {k}  {steps_meta[k]['summary']}  ({steps_meta[k]['sha256'][:16]}...)")
    if closing_dump:
        say("  then one closing read-only session (dump) in Movie mode.")

    if dry_run:
        if active_ctx.simulate_events:
            return _simulate_write_flow(
                action,
                body_id,
                man,
                steps_run,
                active_packs,
                steps_meta,
                no_movie_session,
                active_ctx,
            )
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
            return _fail(active_ctx, f"Refusing apply: {detail}. Run read-only preflight first.")

    say()
    say("This WRITES into running camera RAM ONLY (volatile; battery pull >= 10s restores stock).")
    say("KEEP THE CAMERA SWITCHED ON from step 1 until the script finishes.")
    if applying:
        say(f"Camera must be cold-booted (battery pulled >= 10s), powered on in {BODY_STILLS_HINT[body_id]}, and not yet switched to Movie mode.")
    else:
        say(f"Camera must be powered on in {BODY_STILLS_HINT[body_id]} (if C2/C3 aspect cycle is applied, cycle preview back to 3:2 first).")

    if active_ctx.firmware_confirmed is None:
        confirm_firmware(fw, ctx=active_ctx)
        if input("Type YES to write to the camera's volatile RAM: ").strip() != "YES":
            return _fail(active_ctx, "Not confirmed. Nothing was sent.")

    plan_steps = [{"id": k, "summary": steps_meta[k]["summary"]} for k in steps_run]
    active_ctx.emit(
        "plan",
        action=action,
        body_id=body_id,
        camera=man["camera"],
        firmware=fw,
        steps=plan_steps,
        closing_dump=closing_dump,
    )

    completed_steps: list[str] = []
    total = len(steps_run)
    for n, k in enumerate(steps_run, 1):
        cancel_msg = f"Cancelled safely before step {n} ({k})."
        active_ctx.check_cancelled(cancel_msg, step_index=n, step_id=k)
        if not wait_for_drive(
            body_id,
            first=(n == 1),
            ctx=active_ctx,
            step_index=n,
            total_steps=total,
            step_id=k,
        ):
            return _fail(
                active_ctx,
                f"Camera did not appear as USB drive before step {n} ({k}).",
                step_index=n,
                step_id=k,
                left_behind_flag=left_behind(),
            )
        active_ctx.check_cancelled(cancel_msg, step_index=n, step_id=k)
        say()
        say("=" * 78)
        say(f"Step {n} of {total}: {k} — {steps_meta[k]['summary']}")
        active_ctx.emit(
            "step_start",
            step_index=n,
            total_steps=total,
            step_id=k,
            summary=steps_meta[k]["summary"],
        )
        rc = run_step_live(body_id, k, fw, writes_memory=True, ctx=active_ctx)
        which, facts = latest_ct6_outcome()
        if body_id == "zve1_202" and k == "L14" and which == k and facts and facts.get("outcome") == "NOTHING WRITTEN":
            say("Step L14 wrote nothing (movie buffer open); remaining steps are put back, cold boot clears rawbuf_size.")
            active_ctx.emit(
                "step_done",
                step_index=n,
                total_steps=total,
                step_id=k,
                outcome="NOTHING WRITTEN",
                ok=True,
            )
            completed_steps.append(k)
            continue
        if rc != 0 or which != k or not facts or not facts.get("ok"):
            if body_id == "zve1_202" and k == "L13" and which == k and facts and facts.get("outcome") == "NOTHING WRITTEN":
                err_msg = "STOPPED at step 1 (L13): movie buffer already open. Pull battery >= 10s, power on in Stills, and retry."
            else:
                reason = "session did not finish" if (rc != 0 or which != k or not facts) else f"outcome {facts.get('outcome')}"
                if n == 1:
                    err_msg = f"STOPPED at step 1 ({k}): {reason}. Nothing was changed in camera RAM."
                else:
                    err_msg = f"STOPPED at step {n} ({k}): {reason}. Pull battery >= 10s to return to clean stock."
            say(err_msg)
            lb = left_behind()
            if lb:
                say(
                    "Note: /tmp/jiritsu/libJit.so may still remain on the service partition; "
                    "it is NOT auto-loaded at boot, and the next run of OpenGate Studio will delete it automatically."
                )
            return _fail(
                active_ctx,
                err_msg,
                step_index=n,
                step_id=k,
                left_behind_flag=lb,
                exit_code=1,
                already_printed=True,
            )
        outcome = str(facts.get("outcome") or "DONE")
        active_ctx.emit(
            "step_done",
            step_index=n,
            total_steps=total,
            step_id=k,
            outcome=outcome,
            ok=True,
        )
        completed_steps.append(k)

    say()
    say(f"All {len(completed_steps)} step(s) passed ({action}).")

    if applying:
        closing_verdict = "VERDICT READY (open gate applied)"
        closing_ready = True
        if closing_dump:
            cancel_msg = "Cancelled safely before Movie-mode closing dump (applied patches remain in camera RAM)."
            active_ctx.check_cancelled(cancel_msg, step_index=None, step_id="dump")
            active_ctx.emit(
                "wait_movie_replug",
                hint=BODY_MOVIE_HINT[body_id],
                title="Switch camera to Movie mode",
                detail=_movie_replug_detail(body_id),
            )
            say()
            say("=" * 78)
            say("Closing read-only session (dump in Movie mode):")
            say(">>> 1. Unplug the USB cable.")
            say(f">>> 2. Switch camera to {BODY_MOVIE_HINT[body_id]}.")
            say(">>> 3. Plug the USB cable back in while in Movie mode.")
            say("Waiting for unplug and replug (Ctrl+C to skip; patches remain applied) ...")
            if wait_for_replug(ctx=active_ctx):
                active_ctx.check_cancelled(cancel_msg, step_index=None, step_id="dump")
                active_ctx.emit("closing_dump_start")
                rc_dump = run_step_live(body_id, "dump", fw, writes_memory=False, ctx=active_ctx)
                d_which, d_facts = latest_ct6_outcome()
                if rc_dump == 0 and d_which == "dump" and d_facts:
                    closing_verdict = str(d_facts.get("verdict") or closing_verdict)
                    closing_ready = bool(d_facts.get("ready", True))
                else:
                    say("Closing dump did not complete; patches remain applied.")
                active_ctx.emit(
                    "closing_dump_done",
                    verdict=closing_verdict,
                    ready=closing_ready,
                )
            else:
                say("Timed out waiting for replug; patches remain applied.")
                active_ctx.emit(
                    "closing_dump_done",
                    verdict=closing_verdict,
                    ready=closing_ready,
                )

        state_str = "applied" if closing_ready else "not_ready"
        sid = studio_cli._write_session(session_dir, {
            "kind": "closing_dump",
            "body_id": body_id,
            "mode": "live_usb",
            "ready": closing_ready,
            "state": state_str,
            "verdict": closing_verdict,
            "active_packs": active_packs,
            "steps_run": completed_steps,
            "pins_ok": True,
        })
        say(f"Recorded apply session {sid} in {session_dir}: {closing_verdict}")
        say("Record ONLY in XAVC HS 4K / XAVC S 4K / XAVC S-I 4K at 24p (23.98p), 25p (PAL), or 30p (29.97p) while applied (50p/60p/120p crash or refuse).")
        if body_id == "fx3_702":
            if "fx3_playback" in active_packs:
                say("FX3 playback fix (P29) is applied (untested on hardware): test 1 normal 16:9 clip first, then 1 open-gate clip; if it errors, NEVER retry (retrying freezes until battery pull).")
            else:
                say("WARNING (FX3 7.02): Do NOT play back open-gate clips in-camera without fx3_playback (P29) — retrying 'Unable to display' freezes the camera until battery pull.")
        say("To restore 100% stock: pull battery for >= 10 seconds (or run putback).")
        active_ctx.emit(
            "complete",
            ok=True,
            action="apply",
            body_id=body_id,
            session_id=sid,
            verdict=closing_verdict,
            state=state_str,
            ready=closing_ready,
            steps_run=completed_steps,
            active_packs=active_packs,
        )
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
    active_ctx.emit(
        "complete",
        ok=True,
        action="putback",
        body_id=body_id,
        session_id=sid,
        verdict="VERDICT READY (stock preflight)",
        state="stock",
        ready=True,
        steps_run=completed_steps,
        active_packs=[],
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    global _CTX
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("preflight", "dump", "apply", "putback"))
    ap.add_argument("--body", required=True, choices=tuple(ssr.BODY_CONFIG))
    ap.add_argument("--packs", default=None, help="Comma-separated packs for apply/putback")
    ap.add_argument("--session-dir", type=Path, default=studio_cli.DEFAULT_SESSION_DIR)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-movie-session", action="store_true")
    ap.add_argument(
        "--firmware-confirmed",
        default=None,
        help="Non-interactive firmware confirmation (must match manifest firmware exactly)",
    )
    ap.add_argument(
        "--confirm-volatile-ram",
        action="store_true",
        help="Required alongside --firmware-confirmed for apply/putback",
    )
    ap.add_argument(
        "--json-events",
        action="store_true",
        help="Emit newline-delimited JSON events prefixed with '@OG_EVENT ' on stdout",
    )
    ap.add_argument(
        "--events-file",
        type=Path,
        default=None,
        help="Append raw newline-delimited JSON event objects to PATH",
    )
    ap.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Tee all say() lines and subprocess stdout/stderr to PATH",
    )
    ap.add_argument(
        "--cancel-file",
        type=Path,
        default=None,
        help="If PATH exists while waiting or before a step, emit cancelled event and exit 130",
    )
    ap.add_argument(
        "--simulate-events",
        action="store_true",
        help="Only allowed with --dry-run; emits realistic offline event sequence without USB/sudo",
    )
    args = ap.parse_args(argv)

    ctx = RunContext(
        json_events=args.json_events,
        events_file=args.events_file,
        log_file=args.log_file,
        cancel_file=args.cancel_file,
        firmware_confirmed=args.firmware_confirmed,
        confirm_volatile_ram=args.confirm_volatile_ram,
        simulate_events=args.simulate_events,
    )
    _CTX = ctx
    try:
        if args.simulate_events and not args.dry_run:
            return _fail(ctx, "Refusing --simulate-events without --dry-run. Nothing was sent.")

        kit_dir, man = ssr.load_body_manifest(args.body)
        pin_res = studio_cli.verify_body_pins(kit_dir, man)
        if not pin_res["ok"]:
            return _fail(ctx, f"Kit pin verification failed for {args.body}: {pin_res['mismatches']}")

        fw = str(man["firmware"])
        if args.firmware_confirmed is not None:
            if args.firmware_confirmed != fw:
                return _fail(ctx, f"Not {fw}. Nothing was sent.")
            if args.action in ("apply", "putback") and not args.confirm_volatile_ram:
                return _fail(
                    ctx,
                    f"Refusing {args.action}: --firmware-confirmed requires --confirm-volatile-ram. Nothing was sent.",
                )

        if args.action in ("preflight", "dump"):
            return run_readonly(args.action, args.body, man, args.session_dir, args.dry_run, ctx=ctx)
        return run_write_flow(
            args.action,
            args.body,
            man,
            args.packs,
            args.session_dir,
            args.dry_run,
            args.no_movie_session,
            ctx=ctx,
        )
    except CancelledRun as exc:
        ctx.emit(
            "cancelled",
            step_index=exc.step_index,
            step_id=exc.step_id,
            message=exc.message,
        )
        say(exc.message)
        return 130
    except KeyboardInterrupt:
        msg = "Interrupted by user."
        ctx.emit("cancelled", step_index=None, step_id=None, message=msg)
        say(msg)
        return 130
    finally:
        ctx.close()
        _CTX = None


if __name__ == "__main__":
    sys.exit(main())
