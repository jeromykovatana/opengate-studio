#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Interactive live USB orchestrator for OpenGate Studio (preflight, dump, apply, putback)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import secrets
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
    "a7c_203": "Stills mode (turn physical mode dial to M / A / S / P)",
    "zve10_203": "Stills mode (press Still/Movie/S&Q button until Stills)",
}

BODY_MOVIE_HINT = {
    "zve1_202": "MOVIE mode (press Still/Movie/S&Q button; XAVC HS 4K, XAVC S 4K, or XAVC S-I 4K at 24p/23.98p, 25p PAL, or 30p/29.97p)",
    "a7s3_501": "MOVIE mode (turn physical mode dial to Movie; XAVC HS 4K, XAVC S 4K, or XAVC S-I 4K at 24p/23.98p, 25p PAL, or 30p/29.97p)",
    "fx3_702": "Movie mode (press MODE -> Movie; XAVC HS 4K, XAVC S 4K, or XAVC S-I 4K at 24p/23.98p, 25p PAL, or 30p/29.97p)",
    "a7c_203": "MOVIE mode (turn physical mode dial to Movie; XAVC S 4K 24p/23.98p 100M)",
    "zve10_203": "MOVIE mode (press Still/Movie/S&Q button until Movie; XAVC S 4K 24p/23.98p 100M)",
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

    def __enter__(self) -> RunContext:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


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


_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def private_root() -> Path:
    return Path(os.environ.get("OPENGATE_CAMERA_PRIVATE") or c.PRIVATE_ROOT)


def snapshot_ct6_folders() -> set[str]:
    root = private_root()
    if not root.is_dir():
        return set()
    return {p.name for p in root.iterdir() if p.is_dir() and p.name.startswith("CT6_")}


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


def find_new_ct6_session(
    before_folders: set[str],
    expected_body_id: str,
    expected_which: str,
) -> tuple[Path | None, dict[str, Any] | None]:
    """Locate ONLY a newly created CT6_* session folder matching body_id and step."""
    root = private_root()
    if not root.is_dir():
        return None, None
    new_dirs = sorted(
        (p for p in root.iterdir() if p.is_dir() and p.name.startswith("CT6_") and p.name not in before_folders),
        reverse=True,
    )
    for folder in new_dirs:
        try:
            man = json.loads((folder / "manifest.json").read_text(encoding="utf8"))
        except (OSError, ValueError):
            continue
        if not isinstance(man, dict):
            continue
        if man.get("status") != "completed":
            continue
        res = man.get("results") or {}
        if res.get("body_id") == expected_body_id and res.get("which") == expected_which:
            return folder, man
    return None, None


def extract_ct6_result_facts(
    ct6_manifest: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(ct6_manifest, dict):
        return None, None
    res = ct6_manifest.get("results")
    if not isinstance(res, dict):
        return None, None
    ct6 = res.get("ct6")
    if not isinstance(ct6, dict):
        return None, None
    result_dict = ct6.get("result")
    if not isinstance(result_dict, dict):
        return None, None
    s3 = result_dict.get("s3")
    if not isinstance(s3, dict):
        return result_dict, None
    return result_dict, s3


def validate_readonly_verification(
    ct6_manifest: dict[str, Any] | None,
    *,
    expected_body_id: str,
    expected_which: str,
    expected_state: str,
    expected_verdict: str,
) -> tuple[bool, str, str, str | None]:
    """Fail-closed validation of a closing read-only dump/check CT6 manifest."""
    unverified_state = "unverified" if expected_state == "applied" else "stock_unverified"
    if not isinstance(ct6_manifest, dict) or ct6_manifest.get("status") != "completed":
        return False, unverified_state, "VERDICT UNVERIFIED (closing verification missing or did not complete)", "closing verification session missing or incomplete"

    res = ct6_manifest.get("results")
    if not isinstance(res, dict) or res.get("body_id") != expected_body_id or res.get("which") != expected_which:
        return False, unverified_state, "VERDICT UNVERIFIED (closing verification session mismatch)", "closing verification body/step mismatch"

    result_dict, s3 = extract_ct6_result_facts(ct6_manifest)
    if result_dict is None or s3 is None:
        return False, unverified_state, "VERDICT UNVERIFIED (malformed closing verification result)", "closing verification result payload missing or malformed"

    if result_dict.get("header_ok") is not True or result_dict.get("complete") is not True:
        return False, unverified_state, "VERDICT UNVERIFIED (truncated or invalid closing verification header)", "closing verification result header/complete check failed"

    if int(result_dict.get("problems") or 0) != 0:
        return False, "not_ready", "VERDICT NOT READY (closing verification reported problems)", "closing verification reported problem lines"

    sha = result_dict.get("sha256")
    if not isinstance(sha, str) or not _HEX64_RE.fullmatch(sha):
        return False, unverified_state, "VERDICT UNVERIFIED (missing closing verification result digest)", "closing verification result missing sha256"

    got_ready = s3.get("ready") is True
    got_state = str(s3.get("state") or "not_ready")
    got_verdict = str(s3.get("verdict") or "VERDICT NOT READY")
    id_diff = int(s3.get("identity_differs") or 0)
    prob_lines = list(s3.get("problem_lines") or [])

    if not got_ready or id_diff != 0 or prob_lines:
        return (
            False,
            got_state if got_state != expected_state else "not_ready",
            got_verdict if "NOT READY" in got_verdict else f"VERDICT NOT READY ({got_verdict})",
            f"closing verification not ready: {got_verdict}",
        )

    if got_state != expected_state or got_verdict != expected_verdict:
        return (
            False,
            "not_ready",
            f"VERDICT NOT READY (expected {expected_verdict}, got {got_verdict})",
            f"contradictory closing verification: expected state={expected_state!r} / {expected_verdict!r}, got state={got_state!r} / {got_verdict!r}",
        )

    return True, expected_state, expected_verdict, None


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


def left_behind(before_folders: set[str] | None = None) -> bool:
    sessions = ct6_sessions()
    if before_folders is not None:
        new_sessions = [(folder, man) for folder, man in sessions if folder.name not in before_folders]
        if not new_sessions:
            return False
        sessions = new_sessions
    for _, man in sessions:
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
    require_result_sha: str | None = None,
    expect_serial_sha256: str | None = None,
    expect_msc_usb_id: str | None = None,
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
    if require_result_sha:
        cmd.extend(["--require-result", require_result_sha])
    else:
        clear = last_result_sha()
        if clear:
            cmd.extend(["--clear-result", clear])
    if expect_serial_sha256:
        cmd.extend(["--expect-serial-sha256", expect_serial_sha256])
    if expect_msc_usb_id:
        cmd.extend(["--expect-msc-usb-id", expect_msc_usb_id])
    active_ctx = _active_ctx(ctx)
    if active_ctx.log_file is None:
        return subprocess.run(cmd).returncode
    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf8",
        errors="replace",
        bufsize=1,
    ) as proc:
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
    try:
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
        kit_dir = studio_cli.KITS_DIR / body_id
        manifest_sha = studio_cli.compute_kit_manifest_sha256(kit_dir)
        before_ct6 = snapshot_ct6_folders()
        rc = run_step_live(body_id, which, fw, writes_memory=False, ctx=active_ctx)
        ct6_folder, ct6_man = find_new_ct6_session(before_ct6, body_id, which)
        res_dict, facts = extract_ct6_result_facts(ct6_man)
        res_sha = res_dict.get("sha256") if isinstance(res_dict, dict) else None

        if (
            rc == 0
            and ct6_folder is not None
            and ct6_man is not None
            and res_dict is not None
            and facts is not None
            and res_dict.get("header_ok") is True
            and res_dict.get("complete") is True
            and isinstance(res_sha, str)
            and _HEX64_RE.fullmatch(res_sha)
        ):
            ready = bool(facts.get("ready", False))
            state = str(facts.get("state") or "not_ready")
            verdict = str(facts.get("verdict") or "VERDICT NOT READY")
            res_block = ct6_man.get("results") or {}
            usb_id = res_block.get("camera_usb_identity") or {}
            dev_info = man.get("device_info")
            dev_sha = dev_info.get("sha256") if isinstance(dev_info, dict) else None
            camera_identity = {
                "device_info_sha256": dev_sha,
                "msc_usb_id": usb_id.get("msc_usb_id") or res_block.get("msc_usb_id"),
                "service_usb_id": usb_id.get("service_usb_id") or res_block.get("service_usb_id"),
                "serial_sha256": usb_id.get("serial_sha256"),
                "msc_inquiry": usb_id.get("msc_inquiry") or res_block.get("msc_inquiry"),
                "kernel_version": facts.get("kernel_version"),
                "kernel_command_line": facts.get("kernel_command_line"),
            }
            now_ts = time.time()
            expires_at = now_ts + studio_cli.preflight_ttl_seconds()
            boot_nonce = secrets.token_hex(16)
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
                "verified": True,
                "state": state,
                "verdict": verdict,
                "manifest_sha256": manifest_sha,
                "boot_nonce": boot_nonce,
                "preflight_result_sha256": res_sha,
                "ct6_session": ct6_folder.name,
                "camera_identity": camera_identity,
                "expires_at": expires_at,
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
                verified=True,
                steps_run=[which],
                active_packs=[],
            )
            return 0

        studio_cli._write_session(session_dir, {
            "kind": action,
            "body_id": body_id,
            "mode": "live_usb",
            "ready": False,
            "verified": False,
            "state": "not_ready",
            "verdict": "VERDICT NOT READY (session failed or incomplete)",
            "manifest_sha256": manifest_sha,
            "pins_ok": True,
            "steps_run": [which],
            "active_packs": [],
        })
        return _fail(
            active_ctx,
            f"Read-only {action} ({which}) did not complete cleanly.",
            step_index=1,
            step_id=which,
            left_behind_flag=left_behind(before_ct6),
            exit_code=rc or 1,
        )
    finally:
        active_ctx.close()


def _simulate_write_flow(
    action: str,
    body_id: str,
    man: dict[str, Any],
    steps_run: list[str],
    active_packs: list[str],
    steps_meta: dict[str, Any],
    no_movie_session: bool,
    no_closing_check: bool,
    ctx: RunContext,
) -> int:
    fw = str(man["firmware"])
    applying = action == "apply"
    closing_dump = (not no_movie_session) if applying else (not no_closing_check)
    closing_kind = "movie_dump" if applying else "stock_check"
    plan_steps = [{"id": k, "summary": steps_meta[k]["summary"]} for k in steps_run]
    ctx.emit(
        "plan",
        action=action,
        body_id=body_id,
        camera=man["camera"],
        firmware=fw,
        steps=plan_steps,
        closing_dump=closing_dump,
        closing_kind=closing_kind if closing_dump else None,
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

    if not closing_dump:
        msg = (
            "Simulated closing verification skipped (--no-movie-session); failing closed."
            if applying
            else "Simulated closing stock check skipped (--no-closing-check); failing closed."
        )
        return _fail(
            ctx,
            msg,
            step_index=None,
            step_id="dump" if applying else "check",
            left_behind_flag=False,
            exit_code=1,
        )

    if applying:
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
        ctx.emit("closing_dump_start", closing_kind="movie_dump", step_id="dump")
        say("[simulated dry-run] Closing read-only session (dump in Movie mode)...")
        time.sleep(0.02)
        ctx.emit(
            "closing_dump_done",
            closing_kind="movie_dump",
            verdict="VERDICT READY (open gate applied)",
            ready=True,
            verified=True,
        )
        ctx.emit(
            "complete",
            ok=True,
            action="apply",
            body_id=body_id,
            session_id=f"simulated_apply_{body_id}",
            verdict="VERDICT READY (open gate applied)",
            state="applied",
            ready=True,
            verified=True,
            steps_run=list(steps_run),
            active_packs=list(active_packs),
        )
    else:
        cancel_msg = "Cancelled safely before closing read-only stock check."
        ctx.check_cancelled(cancel_msg, step_index=None, step_id="check")
        title, detail = _drive_prompt_copy(body_id, first=False)
        ctx.emit(
            "wait_drive",
            first=False,
            step_index=total + 1,
            total_steps=total + 1,
            step_id="check",
            title=title,
            detail=detail,
        )
        _sleep_cancelable(0.02, ctx, step_index=None, step_id="check", message=cancel_msg)
        ctx.check_cancelled(cancel_msg, step_index=None, step_id="check")
        ctx.emit("closing_dump_start", closing_kind="stock_check", step_id="check")
        say("[simulated dry-run] Closing read-only stock check (check in Stills mode)...")
        time.sleep(0.02)
        ctx.emit(
            "closing_dump_done",
            closing_kind="stock_check",
            verdict="VERDICT READY (stock preflight)",
            ready=True,
            verified=True,
        )
        ctx.emit(
            "complete",
            ok=True,
            action="putback",
            body_id=body_id,
            session_id=f"simulated_putback_{body_id}",
            verdict="VERDICT READY (stock preflight)",
            state="stock",
            ready=True,
            verified=True,
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
    no_closing_check: bool = False,
    *,
    ctx: RunContext | None = None,
) -> int:
    active_ctx = _active_ctx(ctx)
    try:
        return _run_write_flow_impl(
            action,
            body_id,
            man,
            packs_arg,
            session_dir,
            dry_run,
            no_movie_session,
            no_closing_check,
            active_ctx,
        )
    finally:
        active_ctx.close()


def _run_write_flow_impl(
    action: str,
    body_id: str,
    man: dict[str, Any],
    packs_arg: str | None,
    session_dir: Path,
    dry_run: bool,
    no_movie_session: bool,
    no_closing_check: bool,
    active_ctx: RunContext,
) -> int:
    fw = str(man["firmware"])
    saved_active: list[str] = []
    if action == "putback" and packs_arg is None:
        latest = studio_cli._latest_session_record(session_dir, body_id, mode_filter="live_usb")
        if latest:
            saved_active = list(latest.get("active_packs") or [])

    try:
        steps_run, active_packs = studio_cli.resolve_pack_plan(man, action, packs_arg, saved_active_packs=saved_active)
    except ValueError as err:
        return _fail(active_ctx, f"Invalid --packs: {err}")

    kit_dir = studio_cli.KITS_DIR / body_id
    manifest_sha = studio_cli.compute_kit_manifest_sha256(kit_dir)
    steps_meta = man.get("steps", {})
    for k in steps_run:
        if k not in steps_meta:
            return _fail(active_ctx, f"Step {k} missing from {body_id} manifest. Nothing was sent.")
        p = kit_dir / steps_meta[k]["file"]
        if not p.is_file() or studio_cli._sha256_file(p) != steps_meta[k]["sha256"]:
            return _fail(active_ctx, f"{p.name} missing or SHA-256 mismatch. Nothing was sent.")

    applying = action == "apply"
    closing_dump = (not no_movie_session) if applying else (not no_closing_check)
    closing_kind = "movie_dump" if applying else "stock_check"
    say(f"{man['camera']} ({body_id}) firmware {fw}, {action}: {len(steps_run)} step(s)")
    for n, k in enumerate(steps_run, 1):
        say(f"  {n}. {k}  {steps_meta[k]['summary']}  ({steps_meta[k]['sha256'][:16]}...)")
    if closing_dump:
        if applying:
            say("  then one closing read-only session (dump) in Movie mode.")
        else:
            say("  then one closing read-only stock verification (check) in Stills mode.")

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
                no_closing_check,
                active_ctx,
            )
        for k in steps_run:
            run_step_dry(body_id, k)
        say()
        say("Dry run only: nothing was sent to any device.")
        return 0

    expected_result_sha: str | None = None
    exp_serial: str | None = None
    exp_msc: str | None = None
    if applying:
        ok_pre, pre_rec, pre_err = studio_cli.validate_live_preflight_for_apply(session_dir, body_id, kit_dir, man)
        if not ok_pre or pre_rec is None:
            return _fail(active_ctx, f"Refusing live apply: {pre_err}. Run read-only preflight first.")
        expected_result_sha = pre_rec["preflight_result_sha256"]
        cam_id = pre_rec.get("camera_identity") or {}
        exp_serial = cam_id.get("serial_sha256")
        exp_msc = cam_id.get("msc_usb_id")

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
        closing_kind=closing_kind if closing_dump else None,
    )

    before_run = snapshot_ct6_folders()
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
                left_behind_flag=left_behind(before_run),
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
        before_ct6 = snapshot_ct6_folders()
        rc = run_step_live(
            body_id,
            k,
            fw,
            writes_memory=True,
            ctx=active_ctx,
            require_result_sha=expected_result_sha,
            expect_serial_sha256=exp_serial,
            expect_msc_usb_id=exp_msc,
        )
        _, ct6_man = find_new_ct6_session(before_ct6, body_id, k)
        res_dict, facts = extract_ct6_result_facts(ct6_man)
        if body_id == "zve1_202" and k == "L14" and facts and facts.get("outcome") == "NOTHING WRITTEN":
            say("Step L14 wrote nothing (movie buffer open); remaining steps are put back, cold boot clears rawbuf_size.")
            if isinstance(res_dict, dict) and isinstance(res_dict.get("sha256"), str):
                expected_result_sha = res_dict["sha256"]
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
        if rc != 0 or ct6_man is None or res_dict is None or not facts or not facts.get("ok"):
            if body_id == "zve1_202" and k == "L13" and facts and facts.get("outcome") == "NOTHING WRITTEN":
                err_msg = "STOPPED at step 1 (L13): movie buffer already open. Pull battery >= 10s, power on in Stills, and retry."
            else:
                reason = "session did not finish" if (rc != 0 or ct6_man is None or not facts) else f"outcome {facts.get('outcome')}"
                outcome = facts.get("outcome") if isinstance(facts, dict) else None
                safe_unchanged = outcome in ("NOTHING WRITTEN", "NOTHING TO DO", "NOT DONE (everything put back)")
                if n == 1 and safe_unchanged:
                    err_msg = f"STOPPED at step 1 ({k}): {reason}. Nothing was changed in camera RAM."
                else:
                    err_msg = f"STOPPED at step {n} ({k}): {reason}. Pull battery >= 10s to return to clean stock."
            say(err_msg)
            lb = left_behind(before_ct6)
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
        step_sha = res_dict.get("sha256")
        if isinstance(step_sha, str) and _HEX64_RE.fullmatch(step_sha):
            expected_result_sha = step_sha
        elif applying:
            return _fail(
                active_ctx,
                f"STOPPED at step {n} ({k}): missing valid result SHA-256 for same-boot chaining.",
                step_index=n,
                step_id=k,
                left_behind_flag=left_behind(before_ct6),
                exit_code=1,
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
        closing_verified = False
        closing_state = "applied_unverified"
        closing_verdict = "VERDICT UNVERIFIED (closing Movie-mode dump did not complete)"
        closing_err: str | None = None

        if not closing_dump:
            closing_verdict = "VERDICT UNVERIFIED (--no-movie-session skipped closing dump)"
            closing_err = "Closing Movie-mode verification was skipped (--no-movie-session); cannot certify open gate applied."
            say(closing_err)
        else:
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
            say("Waiting for unplug and replug (Ctrl+C to cancel) ...")
            if wait_for_replug(ctx=active_ctx):
                active_ctx.check_cancelled(cancel_msg, step_index=None, step_id="dump")
                active_ctx.emit("closing_dump_start", closing_kind="movie_dump", step_id="dump")
                before_dump = snapshot_ct6_folders()
                rc_dump = run_step_live(
                    body_id,
                    "dump",
                    fw,
                    writes_memory=False,
                    ctx=active_ctx,
                    require_result_sha=expected_result_sha,
                    expect_serial_sha256=exp_serial,
                    expect_msc_usb_id=exp_msc,
                )
                _, d_man = find_new_ct6_session(before_dump, body_id, "dump")
                if rc_dump != 0:
                    closing_state = "unverified"
                    closing_verdict = f"VERDICT UNVERIFIED (closing dump exited {rc_dump})"
                    closing_err = f"Closing Movie-mode dump failed with status {rc_dump}; failing closed."
                else:
                    closing_verified, closing_state, closing_verdict, closing_err = validate_readonly_verification(
                        d_man,
                        expected_body_id=body_id,
                        expected_which="dump",
                        expected_state="applied",
                        expected_verdict="VERDICT READY (open gate applied)",
                    )
                active_ctx.emit(
                    "closing_dump_done",
                    closing_kind="movie_dump",
                    verdict=closing_verdict,
                    ready=closing_verified,
                    verified=closing_verified,
                )
            else:
                closing_state = "unverified"
                closing_verdict = "VERDICT UNVERIFIED (timed out waiting for Movie-mode replug)"
                closing_err = "Timed out waiting for Movie-mode replug; closing verification did not run."
                say(closing_err)
                active_ctx.emit(
                    "closing_dump_done",
                    closing_kind="movie_dump",
                    verdict=closing_verdict,
                    ready=False,
                    verified=False,
                )

        sid = studio_cli._write_session(session_dir, {
            "kind": "closing_dump",
            "body_id": body_id,
            "mode": "live_usb",
            "ready": closing_verified,
            "verified": closing_verified,
            "state": closing_state,
            "verdict": closing_verdict,
            "manifest_sha256": manifest_sha,
            "active_packs": active_packs,
            "steps_run": completed_steps,
            "pins_ok": True,
        })
        say(f"Recorded apply session {sid} in {session_dir}: {closing_verdict}")
        if not closing_verified:
            return _fail(
                active_ctx,
                closing_err or closing_verdict,
                step_index=None,
                step_id="dump",
                left_behind_flag=left_behind(before_run),
                exit_code=1,
            )

        if body_id in ("a7c_203", "zve10_203"):
            if "raster_2560" in active_packs:
                say("Record in XAVC S 4K 24p (23.98p) 100M while applied (experimental 3840x2560 3:2 raster + squeezed fallback; 30p/S&Q untested).")
            else:
                say("Record ONLY in XAVC S 4K 24p (23.98p) 100M while applied (squeezed 6000x4000 3:2 inside 3840x2160 container — de-squeeze 1.185x vertically in post).")
        else:
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
            state="applied",
            ready=True,
            verified=True,
            steps_run=completed_steps,
            active_packs=active_packs,
        )
        return 0

    # Putback: run final read-only stock verification check (fail-closed)
    stock_verified = False
    stock_state = "stock_unverified"
    stock_verdict = "VERDICT UNVERIFIED (closing read-only stock check did not complete)"
    stock_err: str | None = None

    if not closing_dump:
        stock_verdict = "VERDICT UNVERIFIED (--no-closing-check skipped final stock check)"
        stock_err = "Closing read-only stock check was skipped (--no-closing-check); cannot certify stock RAM state."
        say(stock_err)
    else:
        cancel_msg = "Cancelled safely before closing read-only stock check."
        active_ctx.check_cancelled(cancel_msg, step_index=total + 1, step_id="check")
        if wait_for_drive(
            body_id,
            first=False,
            ctx=active_ctx,
            step_index=total + 1,
            total_steps=total + 1,
            step_id="check",
        ):
            active_ctx.check_cancelled(cancel_msg, step_index=total + 1, step_id="check")
            active_ctx.emit("closing_dump_start", closing_kind="stock_check", step_id="check")
            before_chk = snapshot_ct6_folders()
            rc_chk = run_step_live(
                body_id,
                "check",
                fw,
                writes_memory=False,
                ctx=active_ctx,
                require_result_sha=expected_result_sha,
            )
            _, chk_man = find_new_ct6_session(before_chk, body_id, "check")
            if rc_chk != 0:
                stock_state = "stock_unverified"
                stock_verdict = f"VERDICT UNVERIFIED (closing stock check exited {rc_chk})"
                stock_err = f"Closing read-only stock check failed with status {rc_chk}; failing closed."
            else:
                stock_verified, stock_state, stock_verdict, stock_err = validate_readonly_verification(
                    chk_man,
                    expected_body_id=body_id,
                    expected_which="check",
                    expected_state="stock",
                    expected_verdict="VERDICT READY (stock preflight)",
                )
            active_ctx.emit(
                "closing_dump_done",
                closing_kind="stock_check",
                verdict=stock_verdict,
                ready=stock_verified,
                verified=stock_verified,
            )
        else:
            stock_state = "stock_unverified"
            stock_verdict = "VERDICT UNVERIFIED (camera did not reconnect for closing stock check)"
            stock_err = "Camera did not appear as USB drive for closing read-only stock check."
            say(stock_err)
            active_ctx.emit(
                "closing_dump_done",
                closing_kind="stock_check",
                verdict=stock_verdict,
                ready=False,
                verified=False,
            )

    sid = studio_cli._write_session(session_dir, {
        "kind": "putback",
        "body_id": body_id,
        "mode": "live_usb",
        "ready": stock_verified,
        "verified": stock_verified,
        "state": stock_state,
        "verdict": stock_verdict,
        "manifest_sha256": manifest_sha,
        "active_packs": [] if stock_verified else saved_active,
        "steps_run": completed_steps,
        "pins_ok": True,
    })
    say(f"Recorded putback session {sid} in {session_dir}: state={stock_state} ({stock_verdict})")
    if not stock_verified:
        return _fail(
            active_ctx,
            stock_err or stock_verdict,
            step_index=None,
            step_id="check",
            left_behind_flag=left_behind(before_run),
            exit_code=1,
        )

    active_ctx.emit(
        "complete",
        ok=True,
        action="putback",
        body_id=body_id,
        session_id=sid,
        verdict=stock_verdict,
        state="stock",
        ready=True,
        verified=True,
        steps_run=completed_steps,
        active_packs=[],
    )
    return 0


def _resolve_express_plan(
    action: str,
    body_id: str,
    man: dict[str, Any],
    kit_dir: Path,
    packs_arg: str | None,
    session_dir: Path,
) -> tuple[bool, list[str], list[str], list[str], list[dict[str, str]], str]:
    """Return (is_fused, batch_steps, recorded_steps, active_packs, plan_steps, closing_kind)."""
    steps_meta = man.get("steps", {})
    if action == "express-apply":
        steps_run, active_packs = studio_cli.resolve_pack_plan(man, "apply", packs_arg)
        fused = studio_cli.resolve_fused_preset(man, kit_dir, "apply", active_packs)
        if fused is not None:
            fused_step = fused[1]
            return (
                True,
                [fused_step],
                [fused_step],
                active_packs,
                [{"id": fused_step, "summary": str(steps_meta[fused_step]["summary"])}],
                "fused_readback",
            )
        plan_steps = (
            [{"id": "check", "summary": "Verify initial stock RAM state"}]
            + [{"id": k, "summary": str(steps_meta[k]["summary"])} for k in steps_run]
            + [{"id": "VERIFY", "summary": "Verify open-gate applied state in-place"}]
        )
        return False, ["check", *steps_run, "check"], list(steps_run), active_packs, plan_steps, "in_place_check"

    saved_active: list[str] = []
    if packs_arg is None:
        latest = studio_cli._latest_session_record(session_dir, body_id, mode_filter="live_usb")
        if latest:
            saved_active = list(latest.get("active_packs") or [])
    putback_steps, _ = studio_cli.resolve_pack_plan(man, "putback", packs_arg, saved_active_packs=saved_active)
    target_packs = studio_cli._resolve_putback_target_packs(man, packs_arg, saved_active_packs=saved_active)
    fused = studio_cli.resolve_fused_preset(man, kit_dir, "putback", target_packs)
    if fused is not None:
        fused_step = fused[1]
        return (
            True,
            [fused_step],
            [fused_step],
            [],
            [{"id": fused_step, "summary": str(steps_meta[fused_step]["summary"])}],
            "stock_check",
        )
    plan_steps = (
        [{"id": k, "summary": str(steps_meta[k]["summary"])} for k in putback_steps]
        + [{"id": "VERIFY", "summary": "Verify stock RAM state in-place"}]
    )
    return False, [*putback_steps, "check"], list(putback_steps), [], plan_steps, "stock_check"


def _simulate_express_flow(
    action: str,
    body_id: str,
    man: dict[str, Any],
    plan_steps: list[dict[str, str]],
    recorded_steps: list[str],
    active_packs: list[str],
    closing_kind: str,
    ctx: RunContext,
) -> int:
    fw = str(man["firmware"])
    applying = action == "express-apply"
    ctx.emit(
        "plan",
        action=action,
        body_id=body_id,
        camera=man["camera"],
        firmware=fw,
        steps=plan_steps,
        closing_dump=False,
        closing_kind=closing_kind,
    )
    total = len(plan_steps)
    first_step_id = plan_steps[0]["id"]
    cancel_msg = f"Cancelled safely before step 1 ({first_step_id})."
    ctx.check_cancelled(cancel_msg, step_index=1, step_id=first_step_id)
    title, detail = _drive_prompt_copy(body_id, first=True)
    ctx.emit(
        "wait_drive",
        first=True,
        step_index=1,
        total_steps=total,
        step_id=first_step_id,
        title=title,
        detail=detail,
    )
    _sleep_cancelable(0.02, ctx, step_index=1, step_id=first_step_id, message=cancel_msg)

    step_delay = min(0.015, 0.10 / max(total, 1))
    for idx, pstep in enumerate(plan_steps, 1):
        sid = pstep["id"]
        summary = pstep["summary"]
        cancel_step_msg = f"Cancelled safely before step {idx} ({sid})."
        ctx.check_cancelled(cancel_step_msg, step_index=idx, step_id=sid)
        ctx.emit(
            "step_start",
            step_index=idx,
            total_steps=total,
            step_id=sid,
            summary=summary,
        )
        say(f"[simulated express dry-run] Step {idx} of {total}: {sid} — {summary}")
        time.sleep(step_delay)
        outcome = (
            ("VERDICT READY (open gate applied)" if applying else "VERDICT READY (stock preflight)")
            if sid in ("check", "VERIFY")
            else "DONE"
        )
        ctx.emit(
            "step_done",
            step_index=idx,
            total_steps=total,
            step_id=sid,
            outcome=outcome,
            ok=True,
        )

    verdict = "VERDICT READY (open gate applied)" if applying else "VERDICT READY (stock preflight)"
    state = "applied" if applying else "stock"
    ctx.emit(
        "complete",
        ok=True,
        action=action,
        body_id=body_id,
        session_id=f"simulated_{action.replace('-', '_')}_{body_id}",
        verdict=verdict,
        state=state,
        ready=True,
        verified=True,
        closing_kind=closing_kind,
        steps_run=list(recorded_steps),
        active_packs=list(active_packs) if applying else [],
    )
    say()
    say("Dry run only: nothing was sent to any device.")
    return 0


def run_express_flow(
    action: str,
    body_id: str,
    man: dict[str, Any],
    packs_arg: str | None,
    session_dir: Path,
    dry_run: bool,
    *,
    ctx: RunContext | None = None,
    sim_driver: Any = None,
    connect_fn: Any = None,
    settle_seconds: float = 0.5,
) -> int:
    active_ctx = _active_ctx(ctx)
    try:
        return _run_express_flow_impl(
            action,
            body_id,
            man,
            packs_arg,
            session_dir,
            dry_run,
            active_ctx,
            sim_driver=sim_driver,
            connect_fn=connect_fn,
            settle_seconds=settle_seconds,
        )
    finally:
        active_ctx.close()


def _run_express_flow_impl(
    action: str,
    body_id: str,
    man: dict[str, Any],
    packs_arg: str | None,
    session_dir: Path,
    dry_run: bool,
    active_ctx: RunContext,
    *,
    sim_driver: Any = None,
    connect_fn: Any = None,
    settle_seconds: float = 0.5,
) -> int:
    fw = str(man["firmware"])
    kit_dir = studio_cli.KITS_DIR / body_id
    manifest_sha = studio_cli.compute_kit_manifest_sha256(kit_dir)

    try:
        is_fused, batch_steps, recorded_steps, active_packs, plan_steps, closing_kind = _resolve_express_plan(
            action, body_id, man, kit_dir, packs_arg, session_dir
        )
    except ValueError as err:
        return _fail(active_ctx, f"Invalid --packs: {err}")

    steps_meta = man.get("steps", {})
    readonly_meta = man.get("readonly", {})
    for k in batch_steps:
        entry = readonly_meta.get(k) if k in ("check", "dump") else steps_meta.get(k)
        if not isinstance(entry, dict):
            return _fail(active_ctx, f"Step {k} missing from {body_id} manifest. Nothing was sent.")
        p = kit_dir / entry["file"]
        if not p.is_file() or studio_cli._sha256_file(p) != entry["sha256"]:
            return _fail(active_ctx, f"{p.name} missing or SHA-256 mismatch. Nothing was sent.")

    applying = action == "express-apply"
    say(f"{man['camera']} ({body_id}) firmware {fw}, {action} (single USB session): {len(plan_steps)} step(s)")
    for idx, ps in enumerate(plan_steps, 1):
        say(f"  {idx}. {ps['id']}  {ps['summary']}")

    if dry_run:
        if active_ctx.simulate_events:
            return _simulate_express_flow(
                action,
                body_id,
                man,
                plan_steps,
                recorded_steps,
                active_packs,
                closing_kind,
                active_ctx,
            )
        for k in batch_steps:
            run_step_dry(body_id, k)
        say()
        say("Dry run only: nothing was sent to any device.")
        return 0

    if active_ctx.firmware_confirmed is None:
        confirm_firmware(fw, ctx=active_ctx)
        if input("Type YES to write to the camera's volatile RAM: ").strip() != "YES":
            return _fail(active_ctx, "Not confirmed. Nothing was sent.")

    active_ctx.emit(
        "plan",
        action=action,
        body_id=body_id,
        camera=man["camera"],
        firmware=fw,
        steps=plan_steps,
        closing_dump=False,
        closing_kind=closing_kind,
    )
    first_step_id = plan_steps[0]["id"]
    total = len(plan_steps)
    cancel_msg = f"Cancelled safely before step 1 ({first_step_id})."
    active_ctx.check_cancelled(cancel_msg, step_index=1, step_id=first_step_id)

    if sim_driver is None:
        if not wait_for_drive(
            body_id,
            first=True,
            ctx=active_ctx,
            step_index=1,
            total_steps=total,
            step_id=first_step_id,
        ):
            return _fail(
                active_ctx,
                f"Camera did not appear as USB drive before step 1 ({first_step_id}).",
                step_index=1,
                step_id=first_step_id,
                left_behind_flag=False,
            )
    else:
        title, detail = _drive_prompt_copy(body_id, first=True)
        active_ctx.emit(
            "wait_drive",
            first=True,
            step_index=1,
            total_steps=total,
            step_id=first_step_id,
            title=title,
            detail=detail,
        )

    active_ctx.check_cancelled(cancel_msg, step_index=1, step_id=first_step_id)

    before_run = snapshot_ct6_folders()
    failure_state: dict[str, Any] = {
        "message": None,
        "step_index": None,
        "step_id": None,
        "wrote_any": False,
    }

    def _on_step_start(idx: int, tot: int, _sid: str, _summary: str) -> None:
        ev = plan_steps[idx - 1]
        active_ctx.emit(
            "step_start",
            step_index=idx,
            total_steps=tot,
            step_id=ev["id"],
            summary=ev["summary"],
        )

    def _on_step_result(idx: int, tot: int, sid: str, facts: dict[str, Any], _out: dict[str, Any]) -> bool:
        ev = plan_steps[idx - 1]
        ev_id = ev["id"]
        s3 = facts.get("s3") or {}
        header_ok = facts.get("header_ok") is True
        complete_ok = facts.get("complete") is True
        problems_cnt = int(facts.get("problems") or 0)

        if is_fused:
            ok = header_ok and complete_ok and problems_cnt == 0 and s3.get("ok") is True
            outcome = str(s3.get("outcome") or ("DONE" if ok else "FAILED"))
            active_ctx.emit(
                "step_done",
                step_index=idx,
                total_steps=tot,
                step_id=ev_id,
                outcome=outcome,
                ok=ok,
            )
            if not ok:
                probs = list(s3.get("problem_lines") or [])
                detail = probs[0] if probs else f"outcome {outcome}"
                failure_state["message"] = f"STOPPED at {ev_id}: {detail}"
                failure_state["step_index"] = idx
                failure_state["step_id"] = ev_id
                return False
            failure_state["wrote_any"] = True
            return True

        if applying and idx == 1 and sid == "check":
            ready_ok = header_ok and complete_ok and problems_cnt == 0 and s3.get("ready") is True
            verdict = str(s3.get("verdict") or "VERDICT NOT READY")
            active_ctx.emit(
                "step_done",
                step_index=idx,
                total_steps=tot,
                step_id=ev_id,
                outcome=verdict,
                ok=ready_ok,
            )
            if not ready_ok:
                failure_state["message"] = (
                    "STOPPED at initial check: camera RAM is not ready "
                    "(warm power-switch mixed state or non-stock RAM); pull battery >= 10s. Nothing was written."
                )
                failure_state["step_index"] = idx
                failure_state["step_id"] = ev_id
                return False
            return True

        if ev_id == "VERIFY" and sid == "check":
            want_state = "applied" if applying else "stock"
            want_verdict = "VERDICT READY (open gate applied)" if applying else "VERDICT READY (stock preflight)"
            got_state = str(s3.get("state") or "not_ready")
            got_verdict = str(s3.get("verdict") or "VERDICT NOT READY")
            ver_ok = (
                header_ok
                and complete_ok
                and problems_cnt == 0
                and s3.get("ready") is True
                and int(s3.get("identity_differs") or 0) == 0
                and not s3.get("problem_lines")
                and got_state == want_state
                and got_verdict == want_verdict
            )
            active_ctx.emit(
                "step_done",
                step_index=idx,
                total_steps=tot,
                step_id=ev_id,
                outcome=got_verdict,
                ok=ver_ok,
            )
            if not ver_ok:
                failure_state["message"] = f"In-place verification failed: expected {want_verdict}, got {got_verdict}"
                failure_state["step_index"] = idx
                failure_state["step_id"] = ev_id
                return False
            return True

        if not applying and body_id == "zve1_202" and sid == "L14" and s3.get("outcome") == "NOTHING WRITTEN":
            active_ctx.emit(
                "step_done",
                step_index=idx,
                total_steps=tot,
                step_id=ev_id,
                outcome="NOTHING WRITTEN",
                ok=True,
            )
            return True

        step_ok = header_ok and complete_ok and problems_cnt == 0 and s3.get("ok") is True
        outcome = str(s3.get("outcome") or ("DONE" if step_ok else "FAILED"))
        active_ctx.emit(
            "step_done",
            step_index=idx,
            total_steps=tot,
            step_id=ev_id,
            outcome=outcome,
            ok=step_ok,
        )
        if not step_ok:
            failure_state["message"] = f"STOPPED at step {idx} ({ev_id}): outcome {outcome}. Pull battery >= 10s to return to clean stock."
            failure_state["step_index"] = idx
            failure_state["step_id"] = ev_id
            return False
        failure_state["wrote_any"] = True
        return True

    batch_res = ssr.run_batch_single_session(
        body_id,
        batch_steps,
        fw,
        writes_memory=True,
        express=True,
        on_step_start=_on_step_start,
        on_step_result=_on_step_result,
        cancel_check=active_ctx.is_cancelled,
        sim_driver=sim_driver,
        connect_fn=connect_fn,
        settle_seconds=settle_seconds,
        session_root=private_root(),
    )

    if batch_res.get("cancelled"):
        c_idx = batch_res.get("cancelled_step_index")
        c_sid = batch_res.get("cancelled_step_id")
        raise CancelledRun(
            f"Cancelled safely before step {c_idx} ({c_sid}).",
            step_index=c_idx,
            step_id=c_sid,
        )

    lb = bool(batch_res.get("library_on_camera_after")) or left_behind(before_run)
    if not batch_res.get("ok"):
        err_msg = failure_state["message"] or batch_res.get("stopped") or f"{action} failed."
        fail_state = "not_ready" if not failure_state["wrote_any"] else ("unverified" if applying else "stock_unverified")
        studio_cli._write_session(session_dir, {
            "kind": "express_apply" if applying else "putback",
            "body_id": body_id,
            "mode": "live_usb",
            "ready": False,
            "verified": False,
            "state": fail_state,
            "verdict": f"VERDICT NOT READY ({err_msg})",
            "closing_kind": closing_kind,
            "manifest_sha256": manifest_sha,
            "active_packs": [],
            "steps_run": recorded_steps,
            "pins_ok": True,
        })
        return _fail(
            active_ctx,
            err_msg,
            step_index=failure_state["step_index"],
            step_id=failure_state["step_id"],
            left_behind_flag=lb,
            exit_code=1,
        )

    want_state = "applied" if applying else "stock"
    want_verdict = "VERDICT READY (open gate applied)" if applying else "VERDICT READY (stock preflight)"
    sid = studio_cli._write_session(session_dir, {
        "kind": "express_apply" if applying else "putback",
        "body_id": body_id,
        "mode": "live_usb",
        "ready": True,
        "verified": True,
        "state": want_state,
        "verdict": want_verdict,
        "closing_kind": closing_kind,
        "manifest_sha256": manifest_sha,
        "active_packs": list(active_packs) if applying else [],
        "steps_run": recorded_steps,
        "ct6_session": batch_res.get("ct6_session"),
        "camera_identity": batch_res.get("camera_usb_identity") or {},
        "pins_ok": True,
    })
    say()
    say(f"Recorded {action} session {sid} in {session_dir}: {want_verdict} (state={want_state}, verified=True)")
    active_ctx.emit(
        "complete",
        ok=True,
        action=action,
        body_id=body_id,
        session_id=sid,
        verdict=want_verdict,
        state=want_state,
        ready=True,
        verified=True,
        closing_kind=closing_kind,
        steps_run=recorded_steps,
        active_packs=list(active_packs) if applying else [],
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    global _CTX
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("preflight", "dump", "apply", "putback", "express-apply", "express-putback"))
    ap.add_argument("--body", required=True, choices=tuple(ssr.BODY_CONFIG))
    ap.add_argument("--packs", default=None, help="Comma-separated packs for apply/putback")
    ap.add_argument("--session-dir", type=Path, default=studio_cli.DEFAULT_SESSION_DIR)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-movie-session", action="store_true")
    ap.add_argument("--no-closing-check", action="store_true", help="Skip final read-only stock check after putback (fails closed)")
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
            if args.action in ("apply", "putback", "express-apply", "express-putback") and not args.confirm_volatile_ram:
                return _fail(
                    ctx,
                    f"Refusing {args.action}: --firmware-confirmed requires --confirm-volatile-ram. Nothing was sent.",
                )

        if args.action in ("preflight", "dump"):
            return run_readonly(args.action, args.body, man, args.session_dir, args.dry_run, ctx=ctx)
        if args.action in ("express-apply", "express-putback"):
            return run_express_flow(
                args.action,
                args.body,
                man,
                args.packs,
                args.session_dir,
                args.dry_run,
                ctx=ctx,
            )
        return run_write_flow(
            args.action,
            args.body,
            man,
            args.packs,
            args.session_dir,
            args.dry_run,
            args.no_movie_session,
            args.no_closing_check,
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
