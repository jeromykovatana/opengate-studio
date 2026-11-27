# SPDX-License-Identifier: GPL-3.0-or-later
"""In-process Android companion execution bridge for Chaquopy & unit tests.

Exposes JSON-returning entrypoints used by ``ChaquopyRuntimeBridge.kt``:
  - ``bootstrap_kit(kit_zip_path, unpack_dir)``
  - ``query_companion_state(unpack_dir, sessions_dir, body_id, offline_mock)``
  - ``execute_companion_run(...)``
  - ``export_companion_bundle(sessions_dir, out_zip_path)``

All live USB runs execute in-process (never spawning Python subprocesses) with
``crypto_shim``, ``usb_bridge_shim``, a 30.0s service-device wait timeout, and
every Studio safety gate intact (SHA-256 pin verification, mock isolation,
``--require-result`` chaining, ``DeviceInfo.xml`` & serial SHA binding, and
fail-closed closing verification).
"""
from __future__ import annotations

import contextlib
import importlib
import json
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Iterator

HERE = Path(__file__).resolve().parent
ANDROID_PY_ROOT = HERE.parent
if str(ANDROID_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(ANDROID_PY_ROOT))

from opengate_android.crypto_shim import (  # noqa: E402
    install_cryptodome_sha256_fallback,
    uninstall_cryptodome_sha256_fallback,
)
from opengate_android.quick_reapply import plan_quick_reapply  # noqa: E402
from opengate_android.runtime import export_session_zip, verify_unpacked_payload  # noqa: E402
from opengate_android.usb_bridge_shim import install_usb_shim, uninstall_usb_shim  # noqa: E402

SERVICE_WAIT_TIMEOUT_SECONDS = 30.0
SERVICE_WAIT_POLL_SECONDS = 0.5
_UNPACKED_TOP_DIRS = ("kits", "src", "cli", "transport", "android_runtime")


def _dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _emit_event(on_event: Any, event: dict[str, Any]) -> None:
    if on_event is None:
        return
    if hasattr(on_event, "onEvent"):
        on_event.onEvent(_dumps(event))
    elif callable(on_event):
        on_event(event)


def _safe_extract_zip(zip_path: Path, dest_dir: Path) -> None:
    dest_resolved = dest_dir.resolve()
    dest_resolved.mkdir(parents=True, exist_ok=True)
    for sub_name in _UNPACKED_TOP_DIRS:
        sub = dest_resolved / sub_name
        if sub.exists():
            shutil.rmtree(sub)
    man = dest_resolved / "payload_manifest.json"
    if man.is_file():
        man.unlink()

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            rel = Path(member.filename)
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError(f"Unsafe archive entry path: {member.filename}")
            target = (dest_resolved / rel).resolve()
            if dest_resolved != target and dest_resolved not in target.parents:
                raise ValueError(f"Zip slip attempt rejected: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member, "r") as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)


_ISOLATED_MODULES = (
    "ct1_common",
    "ct1_compare",
    "ct1_predict",
    "ct1_sim",
    "ct1_stage2_service",
    "ct6_level1_run",
    "studio_cli",
    "studio_step_run",
    "studio_live_apply",
    "studio_report",
    "bionz_clip_check",
    "studio_conformance",
    "studio_creator",
    "studio_gyro",
)


def _ensure_sys_path(unpack_dir: Path) -> tuple[Path, Path, Path, Path]:
    cli_dir = unpack_dir / "cli"
    ct1_dir = unpack_dir / "transport" / "camera_tests" / "CT1_usb_first_contact"
    ct6_dir = unpack_dir / "transport" / "camera_tests" / "CT6_memory_read_check"
    pmca_dir = unpack_dir / "transport" / "third_party" / "sony-pmca-re"
    for p in (pmca_dir, ct6_dir, ct1_dir, cli_dir):
        s = str(p)
        if s in sys.path:
            sys.path.remove(s)
        sys.path.insert(0, s)
    return cli_dir, ct1_dir, ct6_dir, pmca_dir


def _load_module_from_dir(mod_name: str, expected_dir: Path) -> Any:
    expected_file = (expected_dir / f"{mod_name}.py").resolve()
    existing = sys.modules.get(mod_name)
    if existing is not None:
        existing_file = getattr(existing, "__file__", None)
        if existing_file and Path(existing_file).resolve() != expected_file:
            sys.modules.pop(mod_name, None)
    return importlib.import_module(mod_name)


@contextlib.contextmanager
def _activated_context(unpack_dir: Path, sessions_dir: Path) -> Iterator[dict[str, Any]]:
    saved_path = sys.path[:]
    saved_env = os.environ.get("OPENGATE_CAMERA_PRIVATE")
    saved_mods = {name: sys.modules.get(name) for name in _ISOLATED_MODULES}

    try:
        cli_dir, ct1_dir, ct6_dir, pmca_dir = _ensure_sys_path(unpack_dir)
        private_dir = sessions_dir / "camera_private"
        os.environ["OPENGATE_CAMERA_PRIVATE"] = str(private_dir)

        for name in _ISOLATED_MODULES:
            sys.modules.pop(name, None)

        ct1_common = _load_module_from_dir("ct1_common", ct1_dir)
        ct1_compare = _load_module_from_dir("ct1_compare", ct1_dir)
        ct1_stage2_service = _load_module_from_dir("ct1_stage2_service", ct1_dir)
        ct6_level1_run = _load_module_from_dir("ct6_level1_run", ct6_dir)
        studio_cli = _load_module_from_dir("studio_cli", cli_dir)
        studio_step_run = _load_module_from_dir("studio_step_run", cli_dir)
        studio_live_apply = _load_module_from_dir("studio_live_apply", cli_dir)

        ct1_common.HERE = ct1_dir
        ct1_common.MAP_ROOT = unpack_dir / "transport"
        ct1_common.REPO = unpack_dir
        ct1_common.PMCA_ROOT = pmca_dir
        ct1_common.PRIVATE_ROOT = private_dir
        ct1_common.PREDICTIONS = ct1_dir / "predictions.json"

        ct6_level1_run.PRIVATE_ROOT = private_dir

        studio_cli.REPO_ROOT = unpack_dir
        studio_cli.KITS_DIR = unpack_dir / "kits"

        studio_step_run.REPO_ROOT = unpack_dir
        studio_step_run.KITS_DIR = unpack_dir / "kits"
        studio_step_run.SRC_DIR = unpack_dir / "src"
        studio_step_run.CT1_DIR = ct1_dir
        studio_step_run.CT6_DIR = ct6_dir

        studio_live_apply.REPO_ROOT = unpack_dir
        studio_live_apply.CT1_DIR = ct1_dir
        studio_live_apply.STEP_RUNNER = cli_dir / "studio_step_run.py"
        studio_live_apply.LISTER = ct1_dir / "ct1_stage2_service.py"

        yield {
            "ct1_common": ct1_common,
            "ct1_compare": ct1_compare,
            "ct1_stage2_service": ct1_stage2_service,
            "ct6_level1_run": ct6_level1_run,
            "studio_cli": studio_cli,
            "studio_step_run": studio_step_run,
            "studio_live_apply": studio_live_apply,
        }
    finally:
        sys.path[:] = saved_path
        if saved_env is None:
            os.environ.pop("OPENGATE_CAMERA_PRIVATE", None)
        else:
            os.environ["OPENGATE_CAMERA_PRIVATE"] = saved_env
        for name in _ISOLATED_MODULES:
            prev = saved_mods.get(name)
            if prev is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prev


def bootstrap_kit(kit_zip_path: str | Path, unpack_dir: str | Path) -> str:
    """Extract ``opengate_kit.zip`` into ``unpack_dir`` and verify all SHA-256 pins."""
    zip_p = Path(kit_zip_path)
    out_p = Path(unpack_dir)
    try:
        if not zip_p.is_file():
            return _dumps({
                "ok": False,
                "checked_files": 0,
                "errors": [f"Missing kit archive: {zip_p}"],
            })
        _safe_extract_zip(zip_p, out_p)
        res = verify_unpacked_payload(out_p)
        return _dumps({
            "ok": bool(res.get("ok")),
            "checked_files": int(res.get("checked_files", 0)),
            "errors": list(res.get("errors", [])),
        })
    except Exception as exc:
        return _dumps({
            "ok": False,
            "checked_files": 0,
            "errors": [str(exc)],
        })


def query_companion_state(
    unpack_dir: str | Path,
    sessions_dir: str | Path,
    body_id: str,
    offline_mock: bool = False,
) -> str:
    """Read latest session via ``studio_cli`` and return ``plan_quick_reapply`` decision."""
    unpack_p = Path(unpack_dir)
    sessions_p = Path(sessions_dir)
    pin_res = verify_unpacked_payload(unpack_p)
    pins_verified = bool(pin_res.get("ok"))

    if not pins_verified:
        plan = plan_quick_reapply(
            pins_verified=False,
            selected_body_id=body_id,
            offline_mock_camera=bool(offline_mock),
        )
        return _dumps({
            "ok": True,
            "pins_verified": False,
            "checked_files": int(pin_res.get("checked_files", 0)),
            "pin_errors": list(pin_res.get("errors", [])),
            "body_id": body_id,
            "offline_mock": bool(offline_mock),
            "decision": plan.decision.value,
            "packs": list(plan.packs),
            "latest_session": {"found": False, "body_id": body_id, "mode": None, "state": "unknown"},
            "live_preflight_valid": False,
            "live_preflight_reason": "kit pin verification failed",
        })

    with _activated_context(unpack_p, sessions_p) as mods:
        studio_cli = mods["studio_cli"]
        studio_live_apply = mods["studio_live_apply"]

        rc, latest = studio_cli.cmd_latest_session(body_id, sessions_p, mode_filter=None)
        if rc != 0:
            return _dumps({
                "ok": False,
                "pins_verified": True,
                "pin_errors": [],
                "body_id": body_id,
                "offline_mock": bool(offline_mock),
                "error": latest.get("error", f"Unknown body {body_id!r}"),
            })

        latest_mode = latest.get("mode") if latest.get("found") else None
        result_source: str | None = None
        if latest_mode == "live_usb":
            result_source = "android_usb"
        elif latest_mode == "mock":
            result_source = "mock"

        left_behind_flag = False
        if not offline_mock and latest_mode == "live_usb":
            left_behind_flag = bool(studio_live_apply.left_behind())

        plan = plan_quick_reapply(
            pins_verified=True,
            selected_body_id=body_id,
            offline_mock_camera=bool(offline_mock),
            left_behind_warning=left_behind_flag,
            latest_session=latest if latest.get("found") else None,
            result_source=result_source,
        )

        manifests = studio_cli._load_manifests()
        live_valid = False
        live_reason = "no live preflight session found"
        if body_id in manifests:
            kit_dir, man = manifests[body_id]
            live_valid, _, live_reason = studio_cli.validate_live_preflight_for_apply(
                sessions_p,
                body_id,
                kit_dir,
                man,
            )

    return _dumps({
        "ok": True,
        "pins_verified": True,
        "checked_files": int(pin_res.get("checked_files", 0)),
        "pin_errors": [],
        "body_id": body_id,
        "offline_mock": bool(offline_mock),
        "decision": plan.decision.value,
        "packs": list(plan.packs),
        "latest_session": latest,
        "left_behind": left_behind_flag,
        "live_preflight_valid": bool(live_valid),
        "live_preflight_reason": live_reason,
    })


def _make_run_context_cls(base_cls: Any, on_event: Any, captured_events: list[dict[str, Any]]) -> type:
    class _AndroidRunContext(base_cls):  # type: ignore[valid-type, misc]
        def emit(self, event_type: str, **fields: Any) -> dict[str, Any]:
            payload = super().emit(event_type, **fields)
            captured_events.append(payload)
            _emit_event(on_event, payload)
            return payload

    return _AndroidRunContext


def _run_offline_mock(
    *,
    mods: dict[str, Any],
    sessions_p: Path,
    action: str,
    body_id: str,
    packs: str | None,
    firmware_confirmed: str | None,
    confirm_volatile_ram: bool,
    cancel_path: Path | None,
    on_event: Any,
    mock_state: str | None,
) -> dict[str, Any]:
    studio_cli = mods["studio_cli"]
    studio_step_run = mods["studio_step_run"]
    studio_live_apply = mods["studio_live_apply"]

    kit_dir, man = studio_step_run.load_body_manifest(body_id)
    fw = str(man["firmware"])
    if firmware_confirmed is not None:
        if firmware_confirmed != fw:
            msg = f"Not {fw}. Nothing was sent."
            _emit_event(on_event, {"type": "error", "message": msg, "left_behind": False})
            return {"ok": False, "mode": "mock", "action": action, "body_id": body_id, "error": msg}
        if action in ("apply", "putback") and not confirm_volatile_ram:
            msg = f"Refusing {action}: firmware_confirmed requires confirm_volatile_ram. Nothing was sent."
            _emit_event(on_event, {"type": "error", "message": msg, "left_behind": False})
            return {"ok": False, "mode": "mock", "action": action, "body_id": body_id, "error": msg}

    if cancel_path is not None and cancel_path.exists():
        msg = "Cancelled safely before mock simulation."
        _emit_event(on_event, {"type": "cancelled", "message": msg})
        return {"ok": False, "cancelled": True, "mode": "mock", "action": action, "body_id": body_id, "error": msg}

    if action == "preflight":
        rc, res = studio_cli.cmd_preflight(body_id, mock_state=mock_state, session_dir=sessions_p, live_usb=False)
    elif action == "apply":
        rc, res = studio_cli.cmd_apply(body_id, packs_arg=packs, session_dir=sessions_p, live_usb=False)
    elif action == "putback":
        rc, res = studio_cli.cmd_putback(body_id, packs_arg=packs, session_dir=sessions_p, live_usb=False)
    elif action == "dump":
        captured: list[dict[str, Any]] = []
        ctx_cls = _make_run_context_cls(studio_live_apply.RunContext, on_event, captured)
        with ctx_cls(
            cancel_file=cancel_path,
            firmware_confirmed=firmware_confirmed,
            confirm_volatile_ram=confirm_volatile_ram,
            simulate_events=True,
        ) as ctx:
            rc = studio_live_apply.run_readonly("dump", body_id, man, sessions_p, dry_run=True, ctx=ctx)
        sid = studio_cli._write_session(sessions_p, {
            "kind": "dump",
            "mode": "mock",
            "body_id": body_id,
            "ready": rc == 0,
            "verified": rc == 0,
            "state": "stock" if rc == 0 else "not_ready",
            "verdict": "VERDICT READY (simulated dump)" if rc == 0 else "VERDICT NOT READY",
            "manifest_sha256": studio_cli.compute_kit_manifest_sha256(kit_dir),
            "pins_ok": True,
            "steps_run": ["dump"],
            "active_packs": [],
        })
        return {
            "ok": rc == 0,
            "mode": "mock",
            "action": "dump",
            "body_id": body_id,
            "session_id": sid,
            "ready": rc == 0,
            "state": "stock" if rc == 0 else "not_ready",
            "verdict": "VERDICT READY (simulated dump)" if rc == 0 else "VERDICT NOT READY",
        }
    else:
        return {"ok": False, "mode": "mock", "action": action, "body_id": body_id, "error": f"Unsupported action {action!r}"}

    ok = rc == 0 and bool(res.get("ok"))
    if ok:
        _emit_event(on_event, {
            "type": "complete",
            "ok": True,
            "mode": "mock",
            "action": action,
            "body_id": body_id,
            "session_id": res.get("session_id"),
            "verdict": res.get("verdict") or res.get("closing_dump_verdict") or "",
            "state": res.get("state", "applied" if action == "apply" else "stock"),
            "ready": bool(res.get("ready", True)),
            "steps_run": list(res.get("steps_run") or []),
            "active_packs": list(res.get("active_packs") or []),
        })
    else:
        err_msg = str(res.get("error") or res.get("verdict") or "Mock operation failed")
        _emit_event(on_event, {"type": "error", "mode": "mock", "action": action, "message": err_msg, "left_behind": False})

    return {
        "ok": ok,
        "mode": "mock",
        "action": action,
        **res,
    }


def execute_companion_run(
    unpack_dir: str | Path,
    sessions_dir: str | Path,
    action: str,
    body_id: str,
    offline_mock: bool = False,
    usb_bridge: Any = None,
    firmware_confirmed: str | None = None,
    confirm_volatile_ram: bool = False,
    cancel_file: str | Path | None = None,
    on_event: Any = None,
    *,
    packs: str | None = None,
    mock_state: str | None = None,
) -> str:
    """Execute ``preflight``, ``apply``, ``putback``, or ``dump`` in-process.

    Enforces SHA-256 pin verification before execution, preserves all OpenGate
    Studio safety gates, and returns a JSON object describing the run outcome.
    """
    unpack_p = Path(unpack_dir)
    sessions_p = Path(sessions_dir)
    cancel_p = Path(cancel_file) if cancel_file else None

    if action not in ("preflight", "dump", "apply", "putback"):
        msg = f"Unsupported companion action: {action!r}"
        _emit_event(on_event, {"type": "error", "message": msg, "left_behind": False})
        return _dumps({"ok": False, "action": action, "body_id": body_id, "error": msg})

    pin_res = verify_unpacked_payload(unpack_p)
    if not pin_res.get("ok"):
        msg = "Kit SHA-256 verification failed: " + "; ".join(pin_res.get("errors", []))
        _emit_event(on_event, {"type": "error", "message": msg, "left_behind": False})
        return _dumps({
            "ok": False,
            "action": action,
            "body_id": body_id,
            "pins_verified": False,
            "error": msg,
            "errors": list(pin_res.get("errors", [])),
        })

    with _activated_context(unpack_p, sessions_p) as mods:
        studio_cli = mods["studio_cli"]
        studio_step_run = mods["studio_step_run"]
        studio_live_apply = mods["studio_live_apply"]
        ct1_common = mods["ct1_common"]
        ct1_stage2_service = mods["ct1_stage2_service"]

        if body_id not in studio_step_run.BODY_CONFIG:
            msg = f"Unknown body_id: {body_id!r}"
            _emit_event(on_event, {"type": "error", "message": msg, "left_behind": False})
            return _dumps({"ok": False, "action": action, "body_id": body_id, "error": msg})

        if offline_mock:
            res = _run_offline_mock(
                mods=mods,
                sessions_p=sessions_p,
                action=action,
                body_id=body_id,
                packs=packs,
                firmware_confirmed=firmware_confirmed,
                confirm_volatile_ram=confirm_volatile_ram,
                cancel_path=cancel_p,
                on_event=on_event,
                mock_state=mock_state,
            )
            return _dumps(res)

        if usb_bridge is None:
            msg = "Live USB mode requires an active Android UsbBridge."
            _emit_event(on_event, {"type": "error", "message": msg, "left_behind": False})
            return _dumps({"ok": False, "mode": "live_usb", "action": action, "body_id": body_id, "error": msg})

        kit_dir, man = studio_step_run.load_body_manifest(body_id)
        fw = str(man["firmware"])
        body_pins = studio_cli.verify_body_pins(kit_dir, man)
        if not body_pins.get("ok"):
            msg = f"Kit pin verification failed for {body_id}: {body_pins.get('mismatches')}"
            _emit_event(on_event, {"type": "error", "message": msg, "left_behind": False})
            return _dumps({"ok": False, "mode": "live_usb", "action": action, "body_id": body_id, "error": msg})

        if firmware_confirmed != fw:
            msg = f"Not {fw}. Nothing was sent."
            _emit_event(on_event, {"type": "error", "message": msg, "left_behind": False})
            return _dumps({"ok": False, "mode": "live_usb", "action": action, "body_id": body_id, "error": msg})

        if action in ("apply", "putback") and not confirm_volatile_ram:
            msg = f"Refusing {action}: --firmware-confirmed requires --confirm-volatile-ram. Nothing was sent."
            _emit_event(on_event, {"type": "error", "message": msg, "left_behind": False})
            return _dumps({"ok": False, "mode": "live_usb", "action": action, "body_id": body_id, "error": msg})

        def _is_cancelled() -> bool:
            return cancel_p is not None and cancel_p.exists()

        captured_events: list[dict[str, Any]] = []
        ctx_cls = _make_run_context_cls(studio_live_apply.RunContext, on_event, captured_events)

        orig_wait_for_service = ct1_stage2_service.wait_for_service_device
        orig_usb_state = studio_live_apply.usb_state
        orig_run_step_live = studio_live_apply.run_step_live
        orig_pnp_sony = ct1_common.pnp_sony_devices
        orig_ctx_global = studio_live_apply._CTX

        installed_crypto = install_cryptodome_sha256_fallback()
        install_usb_shim(
            usb_bridge,
            default_timeout_ms=int(SERVICE_WAIT_TIMEOUT_SECONDS * 1000),
            cancel_check=_is_cancelled,
        )

        def _android_wait_for_service_device(session: Any) -> Any:
            del session
            deadline = time.monotonic() + SERVICE_WAIT_TIMEOUT_SECONDS
            while True:
                if _is_cancelled():
                    return None
                try:
                    _msc, senser = ct1_stage2_service.libusb_devices()
                    if len(senser) == 1:
                        return senser[0]
                except Exception:
                    pass
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                time.sleep(min(SERVICE_WAIT_POLL_SECONDS, remaining))

        def _android_usb_state() -> str:
            try:
                ct1_common.use_pmca()
                msc, senser = ct1_stage2_service.libusb_devices()
            except Exception:
                return "other"
            if len(msc) == 1 and len(senser) == 0:
                return "drive"
            if senser:
                return "service"
            return "other"

        def _android_pnp_sony_devices() -> list[dict[str, Any]]:
            try:
                import usb.core  # type: ignore[import-not-found]

                devs = list(usb.core.find(find_all=True, idVendor=ct1_common.SONY_VID) or [])
                rows: list[dict[str, Any]] = []
                for d in devs:
                    ifaces = [str(iface.bInterfaceClass) for cfg in d for iface in cfg]
                    rows.append({
                        "instance_id": f"USB {d.idVendor:04X}:{d.idProduct:04X} dev={getattr(d, 'device_id', '?')}",
                        "class": ",".join(ifaces) or None,
                        "service": "android_usb_host",
                        "name": "Sony Camera (USB-OTG)",
                    })
                return rows
            except Exception as exc:
                return [{"error": str(exc)}]

        def _android_run_step_live(
            step_body_id: str,
            which: str,
            step_fw: str,
            writes_memory: bool,
            *,
            ctx: Any = None,
            require_result_sha: str | None = None,
            expect_serial_sha256: str | None = None,
            expect_msc_usb_id: str | None = None,
        ) -> int:
            del ctx
            argv = [
                "--body",
                step_body_id,
                which,
                "--go",
                "--firmware-shown",
                step_fw,
            ]
            if writes_memory:
                argv.append("--writes-memory")
            if require_result_sha:
                argv.extend(["--require-result", require_result_sha])
            else:
                clear = studio_live_apply.last_result_sha()
                if clear:
                    argv.extend(["--clear-result", clear])
            if expect_serial_sha256:
                argv.extend(["--expect-serial-sha256", expect_serial_sha256])
            if expect_msc_usb_id:
                argv.extend(["--expect-msc-usb-id", expect_msc_usb_id])
            try:
                rc = studio_step_run.main(argv)
                return int(rc or 0)
            except SystemExit as exc:
                code = exc.code
                if isinstance(code, int):
                    return code
                if code:
                    studio_live_apply.say(str(code))
                return 1

        ct1_stage2_service.wait_for_service_device = _android_wait_for_service_device
        studio_live_apply.usb_state = _android_usb_state
        studio_live_apply.run_step_live = _android_run_step_live
        ct1_common.pnp_sony_devices = _android_pnp_sony_devices

        try:
            with ctx_cls(
                cancel_file=cancel_p,
                firmware_confirmed=firmware_confirmed,
                confirm_volatile_ram=confirm_volatile_ram,
                simulate_events=False,
            ) as ctx:
                studio_live_apply._CTX = ctx
                try:
                    if action in ("preflight", "dump"):
                        rc = studio_live_apply.run_readonly(
                            action,
                            body_id,
                            man,
                            sessions_p,
                            dry_run=False,
                            ctx=ctx,
                        )
                    else:
                        rc = studio_live_apply.run_write_flow(
                            action,
                            body_id,
                            man,
                            packs,
                            sessions_p,
                            dry_run=False,
                            no_movie_session=False,
                            no_closing_check=False,
                            ctx=ctx,
                        )
                except studio_live_apply.CancelledRun as exc:
                    ctx.emit(
                        "cancelled",
                        step_index=exc.step_index,
                        step_id=exc.step_id,
                        message=exc.message,
                    )
                    return _dumps({
                        "ok": False,
                        "cancelled": True,
                        "mode": "live_usb",
                        "action": action,
                        "body_id": body_id,
                        "error": exc.message,
                        "events": captured_events,
                    })
                except Exception as exc:
                    ctx.emit_error(str(exc), left_behind_flag=bool(studio_live_apply.left_behind()))
                    return _dumps({
                        "ok": False,
                        "mode": "live_usb",
                        "action": action,
                        "body_id": body_id,
                        "error": str(exc),
                        "events": captured_events,
                    })
        finally:
            studio_live_apply._CTX = orig_ctx_global
            ct1_stage2_service.wait_for_service_device = orig_wait_for_service
            studio_live_apply.usb_state = orig_usb_state
            studio_live_apply.run_step_live = orig_run_step_live
            ct1_common.pnp_sony_devices = orig_pnp_sony
            uninstall_usb_shim()
            if installed_crypto:
                uninstall_cryptodome_sha256_fallback()

        complete_ev = next((ev for ev in reversed(captured_events) if ev.get("type") == "complete"), None)
        error_ev = next((ev for ev in reversed(captured_events) if ev.get("type") == "error"), None)
        _, latest_rec = studio_cli.cmd_latest_session(body_id, sessions_p, mode_filter="live_usb")
        return _dumps({
            "ok": rc == 0,
            "mode": "live_usb",
            "action": action,
            "body_id": body_id,
            "session_id": (complete_ev or {}).get("session_id") or latest_rec.get("session_id"),
            "verdict": (complete_ev or {}).get("verdict") or latest_rec.get("verdict") or "",
            "state": (complete_ev or {}).get("state") or latest_rec.get("state") or "unknown",
            "ready": bool((complete_ev or {}).get("ready", latest_rec.get("ready", False))),
            "verified": bool((complete_ev or {}).get("verified", latest_rec.get("verified", False))),
            "error": (error_ev or {}).get("message") if rc != 0 else None,
            "left_behind": bool((error_ev or {}).get("left_behind", False)),
            "latest_session": latest_rec,
            "events": captured_events,
        })


def export_companion_bundle(sessions_dir: str | Path, out_zip_path: str | Path) -> str:
    """Export safe session JSONs & metadata (excluding ``camera_private/`` & ``.bin``)."""
    res = export_session_zip(Path(sessions_dir), Path(out_zip_path))
    return _dumps(res)
