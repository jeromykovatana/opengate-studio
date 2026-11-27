# OpenGate Studio — Android USB-OTG Field Companion

Clean-room Android 9+ (`minSdk 28`) USB-OTG companion implementing [`docs/ANDROID_COMPANION_SPEC.md`](../docs/ANDROID_COMPANION_SPEC.md) for `ZV-E1 2.02`, `a7S III 5.01`, and `FX3 7.02`.

## Components

- **`scripts/build_android_kit.py`** — Deterministic clean-room packager that validates `verify_clean_room.py` and bundles `kits/`, `src/*/*_expected.json`, `cli/`, `transport/`, vendored MIT `sony-pmca-re`, and `android/python/opengate_android/` into `opengate_kit.zip` + `payload_manifest.json`.
- **`android/python/opengate_android/`** — Clean-room Python runtime:
  - `quick_reapply.py` — Deterministic Safe Daily 3:2 planner mirroring `QuickReapplyPlanner.swift`
  - `usb_bridge_shim.py` — `pyusb`-compatible `usb.core` / `usb.util` shim backed by Android `UsbBridge`
  - `runtime.py` — Unpacked payload SHA-256 verifier, privacy-filtered session ZIP exporter (`camera_private/` & `.bin` excluded), and `--selftest` harness
- **`android/app/`** — Kotlin + Jetpack Compose scaffold (`UsbBridge.kt`, `OpenGateForegroundService.kt`, `QuickReapplyPlanner.kt`, `MainActivity.kt`, and JUnit tests).

## Verification & Kit Packaging

```bash
# 1. Run clean-room Android runtime + SimDriver selftest across all 3 bodies
python3 android/python/opengate_android/runtime.py --selftest --json

# 2. Dry-run or build clean-room opengate_kit.zip + payload_manifest.json
python3 scripts/build_android_kit.py --dry-run --json
python3 scripts/build_android_kit.py --out-dir /tmp/og_android_assets --json
```
