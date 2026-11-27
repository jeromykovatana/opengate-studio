# OpenGate Studio — Android USB-OTG Field Companion (`v0.3.0-alpha`)

Clean-room Android 9+ (`minSdk 28`, `targetSdk 35`) USB-OTG companion implementing [`docs/ANDROID_COMPANION_SPEC.md`](../docs/ANDROID_COMPANION_SPEC.md) for `ZV-E1 2.02`, `a7S III 5.01`, and `FX3 7.02`.

## What's New in `v0.3.0-alpha`

- **1-Tap Express Apply (`express-apply` / `express-putback`)** — Uses the fused single-pass `Q19`/`Q20` (Safe Daily 3:2: `mp4_3x2,screen_3x2`) and `F19`/`F20` (Cinema Full 3:2: `mp4_3x2,screen_3x2,hdmi32,high_bitrate,xavc_si`) helpers to verify firmware + stock RAM + `mixed_powerswitch` atomically, write, and read back in ~6–8s with zero cable replugs and no Movie-mode replug.
- **Passive USB-OTG Body Auto-Detect & `ILME-FX3A` Block** — `UsbBridge.findDevices` passively reads USB `productName` metadata to auto-select `ZV-E1`, `ILCE-7SM3`, or `ILME-FX3` and blocks `ILME-FX3A` before any live USB action.
- **Per-Body Persistent RAM Consent** — One-time firmware & volatile-RAM acknowledgment is persisted per `(bodyId, firmware)` in `SharedPreferences` across battery swaps; `Advanced & Diagnostics` preserves read-only `preflight` / `dump`, legacy multi-step `apply` / `putback`, and session ZIP export.

## Components

- **`scripts/build_android_kit.py`** — Deterministic clean-room packager invoked automatically by Gradle (`generateOpenGateKitAssets` -> `preBuild`) to generate `app/src/main/assets/opengate_kit.zip` and `payload_manifest.json` from `kits/`, `src/*/*_expected.json`, `cli/`, `transport/`, vendored MIT `sony-pmca-re`, and `android/python/opengate_android/`.
- **`android/python/opengate_android/`** — Clean-room Chaquopy Python runtime:
  - `crypto_shim.py` — Pure-stdlib `hashlib.sha256` fallback for `Cryptodome.Hash.SHA256` (`pmca/usb/sony.py`) with zero native wheel builds
  - `usb_bridge_shim.py` — `pyusb`-compatible `usb.core` / `usb.util` shim backed by Android `UsbBridge`
  - `quick_reapply.py` — Deterministic Safe Daily 3:2 / Express Apply planner mirroring `QuickReapplyPlanner.kt`
  - `runtime.py` — Unpacked payload SHA-256 verifier, privacy-filtered session ZIP exporter (`camera_private/` & `.bin` excluded), and `--selftest` harness
  - `live_runner.py` — In-process JSON bridge (`bootstrap_kit`, `query_companion_state`, `execute_companion_run`, `export_companion_bundle`) supporting `express-apply`, `express-putback`, `preflight`, `dump`, `apply`, and `putback` with 30s service-device wait timeout, `RunContext` event streaming, and full OpenGate Studio safety gates
- **`android/app/`** — Kotlin + Jetpack Compose app (`ChaquopyRuntimeBridge.kt`, `UsbBridge.kt`, `OpenGateForegroundService.kt`, `QuickReapplyPlanner.kt`, `MainActivity.kt`, `FileProvider`, and JUnit tests).

## Build & Install

```bash
# 1. Run Python Android companion unit tests & SimDriver selftest
.venv/bin/python -B -m unittest tests/test_android_companion.py
.venv/bin/python android/python/opengate_android/runtime.py --selftest --json

# 2. Build debug APK & run Kotlin unit tests (requires Java 21 + Android SDK 35)
export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
./android/gradlew -p android testDebugUnitTest assembleDebug --project-cache-dir /tmp/og_gradle_cache

# 3. Sideload onto an Android 9+ device via ADB
adb install -r android/app/build/outputs/apk/debug/app-debug.apk
```
