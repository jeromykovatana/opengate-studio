# OpenGate Studio — Android USB-OTG Field Companion

Clean-room Android 9+ (`minSdk 28`, `targetSdk 35`) USB-OTG companion implementing [`docs/ANDROID_COMPANION_SPEC.md`](../docs/ANDROID_COMPANION_SPEC.md) for `ZV-E1 2.02`, `a7S III 5.01`, and `FX3 7.02`.

## Components

- **`scripts/build_android_kit.py`** — Deterministic clean-room packager invoked automatically by Gradle (`generateOpenGateKitAssets` -> `preBuild`) to generate `app/src/main/assets/opengate_kit.zip` and `payload_manifest.json` from `kits/`, `src/*/*_expected.json`, `cli/`, `transport/`, vendored MIT `sony-pmca-re`, and `android/python/opengate_android/`.
- **`android/python/opengate_android/`** — Clean-room Chaquopy Python runtime:
  - `crypto_shim.py` — Pure-stdlib `hashlib.sha256` fallback for `Cryptodome.Hash.SHA256` (`pmca/usb/sony.py`) with zero native wheel builds
  - `usb_bridge_shim.py` — `pyusb`-compatible `usb.core` / `usb.util` shim backed by Android `UsbBridge`
  - `quick_reapply.py` — Deterministic Safe Daily 3:2 planner mirroring `QuickReapplyPlanner.kt`
  - `runtime.py` — Unpacked payload SHA-256 verifier, privacy-filtered session ZIP exporter (`camera_private/` & `.bin` excluded), and `--selftest` harness
  - `live_runner.py` — In-process JSON bridge (`bootstrap_kit`, `query_companion_state`, `execute_companion_run`, `export_companion_bundle`) with 30s service-device wait timeout, `RunContext` event streaming, and full OpenGate Studio safety gates
- **`android/app/`** — Kotlin + Jetpack Compose app (`ChaquopyRuntimeBridge.kt`, `UsbBridge.kt`, `OpenGateForegroundService.kt`, `QuickReapplyPlanner.kt`, `MainActivity.kt`, `FileProvider`, and JUnit tests).

## Build & Verification

```bash
# 1. Run Python Android companion unit tests & SimDriver selftest
.venv/bin/python -B -m unittest tests/test_android_companion.py
.venv/bin/python android/python/opengate_android/runtime.py --selftest --json

# 2. Build debug APK & run Kotlin unit tests (requires Java 21 + Android SDK 35)
export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home
./android/gradlew -p android testDebugUnitTest assembleDebug --project-cache-dir /tmp/og_gradle_cache
```
