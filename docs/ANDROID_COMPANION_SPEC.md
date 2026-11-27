# Unified Android USB-OTG Companion Specification

> **Status:** Clean-Room Chaquopy APK Build & Offline/USB-OTG Runtime Implemented (`android/`, `scripts/build_android_kit.py`, `tests/test_android_companion.py`)  
> **Target Platforms:** Android 9+ (`minSdkVersion 28`, `targetSdkVersion 35`, USB Host `android.hardware.usb.host`, `arm64-v8a` & `x86_64`) supporting `zve1_202` (ZV-E1 2.02), `a7s3_501` (a7S III 5.01), and `fx3_702` (FX3 7.02).

---

## 1. Purpose & Sibling Prototype Audit

Inspection of the four legacy prototype APKs in the sibling repositories (`zve1-open-gate-test/android/ZVE1-OpenGate.apk`, `a7siii-open-gate-test/android/A7SIII-OpenGate.apk`, `fx3-open-gate-test/android/FX3-OpenGate.apk`, and `a7iv-open-gate-test/android/A7IV-OpenGate.apk`) established how the current Android wrappers operate:

- **Runtime packaging:** Each legacy APK embeds a separate Chaquopy Python 3.10 runtime (`libchaquopy_java.so`, `libpython3.10.so`, `assets/chaquopy/app.imy`, `assets/chaquopy/stdlib-*.imy` for `arm64-v8a` and `x86_64`) plus a body-specific `assets/payload.zip` verified against `payload_manifest.json` (`73` files for ZV-E1, `68` for a7S III, `68` for FX3, `84` for a7 IV).
- **USB-OTG transport shim:** A minimal `pyusb` shim (`usb/__init__.py`, `usb/core.py`, `usb/util.py`) delegates `find`, bulk `read`/`write`, `ctrl_transfer`, and forceful interface claiming (detaching Android's kernel mass-storage driver) to an Android `UsbBridge` class backed by `android.hardware.usb.UsbManager` and `UsbDeviceConnection`.
- **Android behavioral overrides (`og_android.py` + body-specific `og_zv.py` / `og_s3.py` / `og_fx3.py`):**
  - Replaces PC subprocess execution with in-process Python invocations using fresh module imports per step.
  - Extends Sony service-mode re-enumeration timeout (`wait_for_service_device`) from `5s` to `30s` to accommodate Android USB host permission prompts and OTG bus re-enumeration.
  - Redirects session artifacts (`CT6_*`) to app external storage with ZIP export.

### Gaps in the Legacy Per-Body APKs Addressed by This Spec

1. **Fragmented per-camera APKs:** Duplicated runtimes and separate body scripts instead of one unified companion driven by `kits/<body_id>/manifest.json`.
2. **Missing Studio Hardening Controls:** The legacy APKs predate OpenGate Studio's `v0.2.0-alpha` hardening pass and lack:
   - Unified `kits/*/manifest.json` SHA-256 verification across `zve1_202`, `a7s3_501`, and `fx3_702`
   - Modular pack selection (`core_open_gate`, `mp4_3x2`, `screen_3x2`, `hdmi32`, `high_bitrate`, `xavc_si`, `fx3_playback`)
   - Live preflight session binding (`boot_nonce`, `expires_at`, USB identity binding, mock-isolation)
   - Same-boot RAM-disk result-hash chaining (`--require-result` / `--clear-result`)
   - Fail-closed closing verification (`movie_dump` for `apply`, `stock_check` for `putback`)
   - Quick Field Re-Apply (Safe Daily 3:2) after battery swap & interrupted-session recovery UX

---

## 2. Clean-Room & Safety Guardrails

The Android companion MUST enforce every rule in [`docs/SAFETY_AND_CLEANROOM.md`](SAFETY_AND_CLEANROOM.md):

1. **Volatile RAM Only (`persistent_writes: false`):** Every helper loaded onto the camera runs strictly under `/tmp/jiritsu/` and modifies volatile RAM only. Zero writes to `nflasha*`, `boot0`/`boot1`, or `BK4`/`BACKUP.BIN`.
2. **Zero Sony Binaries or Forbidden Artifacts:** Only clean-room GPL-3.0-or-later Python/Kotlin code, vendored MIT `transport/third_party/sony-pmca-re` (verified against `PINNED.json`), `src/*/*_expected.json`, and the reproducible `clang version 18.1.6` `.so` helpers and `DeviceInfo.xml` inside `kits/` are packaged.
3. **Never Bypass Live Preflight:** Mock simulation (`--mock-camera`) is strictly isolated from live USB authorization; mock `READY` must never unlock live `apply`.
4. **Fail Closed on Ambiguity:** Any missing/corrupt SHA-256, `DeviceInfo.xml` mismatch, USB identity mismatch, result-hash chain break, or failed/skipped closing dump aborts and marks the session unverified.

---

## 3. Unified Asset Layout & `kits/*/manifest.json` Pinning

Instead of per-camera `payload.zip` trees, the unified APK bundles a single clean-room payload (`assets/opengate_kit.zip`) mirrored directly from OpenGate Studio:

- `kits/zve1_202/{manifest.json, DeviceInfo.xml, *.so}`
- `kits/a7s3_501/{manifest.json, DeviceInfo.xml, *.so}`
- `kits/fx3_702/{manifest.json, DeviceInfo.xml, *.so}`
- `src/{zve1_202,a7s3_501,fx3_702}/*_expected.json`
- `cli/{studio_cli.py, studio_live_apply.py, studio_step_run.py, studio_report.py}`
- `transport/camera_tests/CT1_usb_first_contact/*`
- `transport/camera_tests/CT6_memory_read_check/ct6_level1_run.py`
- `transport/third_party/sony-pmca-re/{LICENSE.txt, PINNED.json, pmca/**}`
- `assets/payload_manifest.json` (SHA-256 over every packaged file)

### Startup & Pre-Step Pin Verification

1. On APK launch (and whenever unpacked to `context.filesDir`), verify `assets/payload_manifest.json` SHA-256 for every file before importing runner modules.
2. Compute `manifest_sha256 = sha256(kits/<body_id>/manifest.json)` and run the exact equivalent of `studio_cli.py verify-pins --body <body_id>`:
   - Verify `readonly.check`, `readonly.dump`, every `steps.<ID>` `.so` file, and `device_info.file` (`DeviceInfo.xml`) against their pinned SHA-256 digests.
   - Verify vendored `sony-pmca-re` files against `PINNED.json` (no extra unpinned `.py` files).
3. If any check fails, transition the Quick Re-Apply planner to `blockedPinsUnverified` and disable all live USB operations.

---

## 4. Android USB-OTG Transport & Lifecycle Resilience

### 4.1 USB Host Permissions & Device Attachment
- **Manifest requirements:** `<uses-feature android:name="android.hardware.usb.host" android:required="true" />` and `<uses-permission android:name="android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE" />`.
- **Sony VID Filter:** `0x054c` (`1356`). Match Mass Storage (interface class `8`) and Sony Service Mode devices via `ct1_stage2_service`.
- **Permission across USB replugs:** Every unplug/replug step and the Movie-mode switch creates a new Android `UsbDevice` instance. The `UsbBridge` must:
  1. Check `usbManager.hasPermission(device)` before opening.
  2. If ungranted, request permission via an explicit `PendingIntent` (`FLAG_MUTABLE` / `FLAG_IMMUTABLE` per API level) and block up to `30s` (with cancel support) for user approval.
  3. Guide the user on first connect to tick *"Always open OpenGate Studio when Sony Camera is connected"* to reduce friction across multi-step replugs.
  4. On open, call `connection.claimInterface(iface, /* force = */ true)` on every interface to detach Android's built-in USB Mass Storage driver.

### 4.2 Background Execution During Replugs
- Run the active live session inside an Android **Foreground Service** (`connectedDevice` type) holding a partial `WakeLock` (`SCREEN_BRIGHT_WAKE_LOCK` or `KeepScreenOn` in the active activity) so Doze/screen-off never suspends USB polling while the user switches the camera dial or replugs the OTG cable.
- Expose a thread-safe `cancel.flag` checked between steps and during `wait_drive` / `wait_replug` polling loops — **never** kill the transfer mid-`SET_FILE2` or mid-DMA write.

---

## 5. Security & Verification Protocol

### 5.1 `DeviceInfo.xml` Verification & Camera Identity Binding
Before any helper library is sent in a service session:
1. Send `SET_FILE_PATH` (`/usr/share/pmbp/DeviceInfo.xml`) and `GET_FILE2` to read the camera's `DeviceInfo.xml`.
2. Compare bytes and SHA-256 against `kits/<body_id>/DeviceInfo.xml` (`manifest.json["device_info"]["sha256"]`). On mismatch, raise `StopTest` immediately and send nothing else.
3. Extract USB identity (`msc_usb_id` VID:PID, `service_usb_id`, `msc_inquiry`, and SHA-256 of USB serial number `serial_sha256`). Store in `camera_identity` on the preflight session record.
4. During `apply` steps and closing verification, pass `--expect-serial-sha256` and `--expect-msc-usb-id` so swapping to a different camera mid-session fails closed before any write.

### 5.2 Live Preflight Binding & Same-Boot Result-Hash Chaining
Live `apply` MUST fail closed unless all of the following hold (mirroring `studio_cli.validate_live_preflight_for_apply`):
1. Latest session for `body_id` has `mode == "live_usb"`, `kind in ("preflight", "dump")`, `ok == true`, `ready == true`, `verified != false`, `state == "stock"`, `pins_ok == true`, and matching `manifest_sha256`.
2. Session has a valid `boot_nonce`, a 64-hex `preflight_result_sha256`, valid `camera_identity` (`device_info_sha256` + USB ID), and `now <= expires_at` (`900s` default TTL).
3. Any newer `mock` session or newer `live_usb` session for a different `body_id` invalidates the preflight.
4. **Same-Boot Result-Hash Chaining (`--require-result` / `--clear-result`):**
   - Step 1 receives `--require-result <preflight_result_sha256>`. On camera, `/tmp_wbshd/readcheck_result.txt` must exist and match `<preflight_result_sha256>` before it is cleared and Step 1 executes. (If the user pulled the battery or rebooted after preflight, `/tmp_wbshd/readcheck_result.txt` is gone, so Step 1 aborts before writing a single byte.)
   - Each completed step `n` extracts `res_dict["sha256"]` (validated 64-hex) and passes it as `--require-result` to step `n + 1`, chaining all the way into the closing verification `dump`.

### 5.3 Fail-Closed Closing Verification
- **Live `apply`:** After the final write step, prompt the user to unplug USB-C, switch to Movie mode (`24p / 25p / 30p`), and replug USB-C. Run `dump` (`writes_memory=False`, chained with `--require-result`). Validate with `validate_readonly_verification`:
  - `ct6_manifest["status"] == "completed"`, matching `body_id` and `which == "dump"`
  - `header_ok == true`, `complete == true`, `problems == 0`, 64-hex `sha256`
  - `s3.ready == true`, `s3.identity_differs == 0`, empty `s3.problem_lines`
  - `s3.state == "applied"` and `s3.verdict == "VERDICT READY (open gate applied)"`
  - Any failure, timeout, skip, or contradiction records `ready = false`, `verified = false`, `state = "unverified"` (or `"not_ready"`), checks `left_behind()` on `/tmp/jiritsu/libJit.so`, and instructs a `>= 10s` battery pull.
- **Live `putback`:** After putback steps, prompt Stills-mode replug and run read-only `check`, validating `s3.state == "stock"` and `s3.verdict == "VERDICT READY (stock preflight)"`, otherwise recording `stock_unverified` (`ready = false`).

---

## 6. Mobile Field UX: Quick Re-Apply & Session Export

1. **Quick Field Re-Apply (Safe Daily 3:2):** Mirrors `QuickReapplyPlanner` (`core_open_gate` + `mp4_3x2` + `screen_3x2`) with five deterministic states:
   - `blockedPinsUnverified` -> block all live USB operations
   - `runRecoveryPreflightFirst` -> interrupted session / `left_behind` / unverified state banner prompting `>= 10s` battery pull + recovery preflight
   - `runPreflightThenSafeDailyApply` -> post-battery-swap default; launches live Read-Only Preflight first (never bypasses preflight)
   - `readyForSafeDailyApply(["mp4_3x2", "screen_3x2"])` -> single tap enters firmware/volatile-RAM confirmation and executes Safe Daily 3:2 apply
   - `alreadyApplied` -> indicates verified applied state with a "Swapped Battery? Re-Verify" action
2. **Desktop Interoperability:** Store `CT6_*` folders and `session_*.json` records in an exportable ZIP bundle matching desktop `sessions/` schema so field sessions can be ingested directly by `cli/studio_cli.py build-report` on macOS.

---

## 7. Verification Criteria for Future Android Implementation

Before any Android build artifact is marked ready:
1. `python3 scripts/verify_clean_room.py` passes on the Android module/asset tree (zero forbidden binaries/tokens, all `kits/*` hashes intact).
2. In-app `--selftest` passes against `ct1_sim.SimDriver` for all 3 bodies (`zve1_202`, `a7s3_501`, `fx3_702`), verifying `DeviceInfo.xml` rejection, `--require-result` chaining failure on missing/mismatched RAM-disk digest, and fail-closed closing verification.
3. Unit tests verify `QuickReapplyPlanner` equivalence (mock `READY` never unlocks live `apply`).
4. Hardware field test confirms OTG USB replug loop (`Stills` steps -> `Movie` closing `dump`) on a physical Android device and records `FIELD_REPORT.md` via `studio_cli.py build-report`.
