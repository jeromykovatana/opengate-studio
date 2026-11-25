# Sony OpenGate Studio

> [!WARNING]
> **READ BEFORE USE — AS-IS / VOLATILE RAM ONLY / VOIDS WARRANTY**
> - **PROVIDED AS-IS WITHOUT WARRANTY OF ANY KIND (GPL-3.0-or-later).**
> - **VOLATILE RAM ONLY:** Every patch targets running camera RAM only (`persistent_writes: false`). Nothing is written to eMMC flash (`nflasha*`), `boot0`/`boot1`, or `BK4` settings. **Pulling the battery for >= 10 seconds restores 100% stock firmware state.**
> - **EXPERIMENTAL MODIFICATION:** Running volatile RAM patches over USB service mode may void your warranty or cause temporary camera instability if battery power is lost mid-session. Always run the read-only preflight check first and keep the camera powered until `apply` / `putback` finishes.

**Sony OpenGate Studio** is a clean-room, multi-body macOS SwiftUI app, Python CLI, and Unicorn-verified volatile RAM patch studio for Sony's 12.1MP full-frame BIONZ XR cinema/hybrid cameras (`IMX510` + `CXD90057`).

---

## Supported Bodies & Firmware Pins

| Body | Firmware | `body_id` | Build ID (`version.txt`) | Status |
|---|---|---|---|---|
| **Sony ZV-E1** | `2.02` | `zve1_202` | `32000_08.2025101101` | Kit + Manifest + Unicorn Verified |
| **Sony a7S III** (`ILCE-7SM3`) | `5.01` | `a7s3_501` | `39183_16.2026041504` | Kit + Manifest + Unicorn Verified |
| **Sony FX3** (`ILME-FX3`) | `7.02` | `fx3_702` | `39180_21.2025122503` | Kit + Manifest + Unicorn Verified |

*(Clip Inspector `bionz_clip_check.py` also supports **a7 IV** `3840x2560` / `5760x3840` MP4 clips.)*

---

## Modular Feature Packs

Each body ships with orthogonal, stackable volatile RAM packs built with `ziglang 0.13.0` (`clang version 18.1.6`) and verified for zero cross-pack guard collisions:

| Pack | Description | Notes |
|---|---|---|
| `core_open_gate` *(required)* | `3840x2560` 3:2 23.98p sensor readout & output size (`ogsq` + `outsz2560`, plus `dmmwb` on ZV-E1) | Locked base pack |
| `mp4_3x2` | Native `3840x2560` MP4 `tkhd`/`stsd`/`VPRF` height, codec level fix, NRT XML `16:9` suppression, and in-camera playback (`V19`/`V20`) | Preserves Sony `rtmd` gyro telemetry; falls back to `L19`/`L20` if deselected |
| `screen_3x2` | Full-frame 3:2 LCD framing & preview aspect cycle (`lcdfill` + `lcdcycle` on ZV-E1/a7S III; `lcdfill` on FX3) | Optional |
| `hdmi32` | Clean 3:2 pillarboxed & uncropped anamorphic HDMI output (`H16`/`H17`) | Optional |
| `high_bitrate` | `200M` / `300M` Long-GOP XAVC HS & XAVC S bitrate overlay (`B19`/`B20`) | Optional |
| `xavc_si` | XAVC S-I 4K All-Intra `3840x2560` Open Gate + VPRF/playback (`I19`/`I20`) | Optional |
| `fx3_playback` | FX3 In-Camera 3:2 Playback Fix (`avdec8k_fx3_v1`, `P29`/`P30`) | Optional, **FX3 only** (`default_enabled: false`, **untested on hardware**) |

> [!IMPORTANT]
> **Essential Hardware & SD Card Notes**
> - **No files go on your SD card:** Leave a normal formatted SD/CFexpress card in **Slot 1** so the camera mounts as USB Mass Storage. Nothing on the card is modified or erased.
> - **FX3 `7.02` Playback Freeze Warning:** On stock FX3 `7.02`, playing an open-gate clip shows `"Unable to display"` and retrying freezes the camera until battery pull. Do **not** play back clips on FX3 unless testing optional `fx3_playback` (`P29`/`P30`, untested on hardware — test 1 normal 16:9 clip first, then 1 open-gate clip, and **never retry** if it errors).
> - **a7S III `5.01` & ZV-E1 `2.02` Warm Power-Switch Reset:** Toggling the power switch resets coprocessor RAM while retaining encoder patches (`mixed_powerswitch` — Issue #3 confirmed on `5.01`). Always **pull the battery for >= 10 seconds** to restore 100% stock.
> - **macOS USB Auto-Reconnect:** On macOS, consecutive USB steps may re-enumerate automatically ~5 seconds apart after the stop/reset request.

---

## Quickstart

### 1. CLI Quickstart (Safe Offline Mock Mode by Default)

All CLI commands use pure Python 3 standard library and default to `--mock-camera` simulation so you can verify pins, preflight gates, and pack stacking safely offline:

```bash
# List supported bodies and packs
python3 cli/studio_cli.py list-bodies --json

# Verify SHA-256 pins of every .so helper in kits/
python3 cli/studio_cli.py verify-pins --json

# Run read-only preflight (stock vs warm power-switch mixed state)
python3 cli/studio_cli.py preflight --body zve1_202 --mock-camera --mock-state stock --session-dir /tmp/og_sessions --json

# Apply modular packs (enforces newest preflight session ready == true)
python3 cli/studio_cli.py apply --body zve1_202 --packs mp4_3x2,screen_3x2,hdmi32,high_bitrate,xavc_si --mock-camera --session-dir /tmp/og_sessions --json

# Put back to stock RAM state
python3 cli/studio_cli.py putback --body zve1_202 --packs mp4_3x2,screen_3x2,hdmi32,high_bitrate,xavc_si --mock-camera --session-dir /tmp/og_sessions --json

# Inspect an MP4 clip + optional M01.XML sidecar for 3:2 framing & rtmd gyro data
python3 cli/studio_cli.py check-clip /path/to/C0001.MP4 --xml /path/to/C0001M01.XML --json

# Run built-in clip checker self-test and clean-room verification
python3 cli/bionz_clip_check.py --selftest
python3 scripts/verify_clean_room.py
python3 -B -m unittest discover -s tests -v
```

### 2. macOS One-Click Setup, Live USB Terminal & SwiftUI App (`OpenGate Studio.app`)

Requires macOS 14+ and Python 3.9+ (Swift 5.10+ on Apple Silicon `arm64` to rebuild `OpenGate Studio.app`):

```bash
# 1. One-time laptop setup: creates .venv, installs requirements.txt (pyusb, pycryptodomex, libusb-package),
#    verifies kit pins, builds OpenGate Studio.app (if swift is installed), and launches it:
./setup_and_open_mac.command

# 2. Preview any live USB flow safely offline (--dry-run sends nothing and skips sudo):
./macos/run_live_terminal.sh preflight --body zve1_202 --dry-run
./macos/run_live_terminal.sh apply --body a7s3_501 --packs mp4_3x2,screen_3x2,hdmi32,high_bitrate,xavc_si --dry-run

# 3. Live USB runs (prompts once for sudo to detach iousbmassstorage, then restores folder ownership):
./macos/run_live_terminal.sh preflight --body zve1_202
./macos/run_live_terminal.sh apply --body zve1_202 --packs mp4_3x2,screen_3x2,hdmi32,high_bitrate,xavc_si
./macos/run_live_terminal.sh putback --body zve1_202
```

> [!NOTE]
> Live USB transport is vendored cleanly in `transport/` (`sony-pmca-re` MIT + `CT1`/`CT6` GPL-3.0) with `cli/studio_step_run.py` and `cli/studio_live_apply.py`. In **Live Camera USB Mode** inside `OpenGate Studio.app`, clicking Preflight / Apply / Put Back prepares an executable `.command` wrapper (`studio_cli.py prepare-live-command`) and opens it in `Terminal.app`, then syncs the result back into the UI via `studio_cli.py latest-session`.

---

## Documentation

- [Office Camera Test Guide (ZV-E1 2.02 / a7S III 5.01 / FX3 7.02)](docs/OFFICE_CAMERA_TEST_GUIDE.md)
- [Safety & Clean-Room Architecture](docs/SAFETY_AND_CLEANROOM.md)
- [BIONZ XR 12.1MP Offset Audit & MP4 3:2 Muxer](docs/OFFSET_AUDIT.md)
- [Feature Unlock Ranking & Verified Designs](docs/FEATURE_UNLOCK_RANKING.md)
- [ZV-E1 2.02 Recording & Gyro Test Protocol](docs/ZVE1_RECORDING_TEST.md)

---

## Credits & License

- **Original Open-Gate Research & Volatile RAM Loader:** [ArcaneLantern](https://github.com/ArcaneLantern) (`a7iv-open-gate-test`, `a7siii-open-gate-test`, `fx3-open-gate-test`, `zve1-open-gate-test`)
- **Sony USB Service Protocol Tooling:** [ma1co/Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE)
- **License:** GNU General Public License v3.0 or later (`GPL-3.0-or-later`) — see [LICENSE](LICENSE).
