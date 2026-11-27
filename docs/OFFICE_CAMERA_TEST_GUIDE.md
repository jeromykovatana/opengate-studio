# Office Camera Test Guide (`ZV-E1 2.02` · `a7S III 5.01` · `FX3 7.02`)

> [!CAUTION]
> **Hard Safety Rules — Read Before Connecting Any Camera**
> 1. **Volatile RAM Only (`persistent_writes: false`):** Every patch runs strictly in camera RAM (`/tmp/jiritsu/libJit.so`). Nothing is written to `nflasha*` flash, `boot0`/`boot1`, or `BK4` settings. **Pulling the battery for >= 10 seconds restores 100% stock state.**
> 2. **No Files Go on Your SD Card:** Do **not** copy any files onto your SD/CFexpress card. Keep a normal formatted card in **Slot 1** so the camera mounts as USB Mass Storage (`nothing is erased`).
> 3. **Read-Only Gate First:** Never write to camera RAM without an explicit read-only verification gate on the exact firmware version. **1-Click Express Apply (`Q19`/`F19`)** executes the read-only stock RAM, firmware identity, and `mixed_powerswitch` check atomically inside the single pass before writing a single byte (returning `VERDICT NOT READY` with zero writes if any check fails), while standalone **`Check Camera (Read-Only)`** (`preflight`) remains available in **Advanced Tools**.
> 4. **24p (23.98p), 25p (PAL), or 30p (29.97p) Only While Applied:** Record **only** at `24p` (`23.98p`), `25p` (`PAL`, drive mode `0x820`), or `30p` (`29.97p`) in `XAVC HS 4K`, `XAVC S 4K`, or `XAVC S-I 4K` while Open Gate is applied. **`50p` / `60p` / `120p` distorts live view and crashes the camera** (pixel clock ceiling on `IMX510`).
> 5. **Leftover `/tmp/jiritsu/libJit.so` Auto-Recovery:** If an earlier aborted run left one of our own known `libJit.so` libraries in `/tmp/jiritsu/libJit.so`, the tool removes it automatically before running; foreign files still stop immediately without touching anything. You can also pass `--remove-library <SHA256>` to clear a specific known hash manually.
> 6. **Keep Camera Switched ON During `apply` / `putback`:** Do **not** toggle the power switch or pull the battery between steps. Both **`ZV-E1` (`2.02`)** and **`a7S III` (`5.01`)** (Issue #3) reset coprocessor RAM while retaining encoder patches on a power-switch cycle (`mixed_powerswitch`) — always **pull the battery for >= 10 seconds** to restore clean stock.
> 7. **FX3 `7.02` Playback Freeze Warning:** On stock FX3 `7.02`, playing an open-gate clip shows `"Unable to display"` and **retrying freezes the camera until battery pull**. Do **not** play back clips on FX3 unless testing the optional **`fx3_playback` (`P29`/`P30`)** pack (untested on hardware: test 1 normal 16:9 clip first, then 1 open-gate clip, and **never retry** if it errors).

---

## 1. Laptop Setup (One-Time on Your Mac)

Double-click **`setup_and_open_mac.command`** (or run from Terminal):

```bash
cd "/path/to/opengate-studio"
chmod +x setup_and_open_mac.command macos/run_live_inapp.sh macos/run_live_terminal.sh
./setup_and_open_mac.command
```

This creates `.venv` with `pyusb==1.3.1`, `pycryptodomex==3.24.2`, and `libusb-package==1.0.30.1` (bundled `libusb` — **no Homebrew or Zadig driver needed**), verifies all SHA-256 pins in `kits/`, builds `macos/OpenGateStudio/dist/OpenGate Studio.app` (if Swift is installed), and opens the app.

> [!NOTE]
> When running in **Live USB Mode**, macOS binds `iousbmassstorage` to the camera. Inside `OpenGate Studio.app`, the native in-app Live USB sheet runs `macos/run_live_inapp.sh` with a single macOS administrator prompt to unmount the SD/CFexpress card cleanly and release `iousbmassstorage`, then restores ownership of `sessions/` to your user account automatically (a **Use Terminal Instead** fallback to `macos/run_live_terminal.sh` is also available if you prefer CLI `sudo`).

---

## 2. Exact Camera USB & Shooting Settings (All 3 Bodies)

Set these **once** on each camera before starting:

| Menu Setting | Required Value | Why |
|---|---|---|
| **SD / CFexpress Card (Slot 1)** | **Normal formatted card inserted (NO files copied to it)** | Camera needs a card in Slot 1 to mount as USB Mass Storage; nothing on the card is modified or erased |
| **USB Connection** *(Setup > USB)* | **`Mass Storage`** *(NOT PC Remote, MTP, or Auto)* | Service-mode takeover starts on the MSC interface before switching to `054C:0336` |
| **USB LUN Setting** *(Setup > USB)* | **`Multi`** *(or `Single`)* | `unmount_sony_disks` unmounts all whole disks cleanly before takeover |
| **Smartphone Conn / Cnct. while Power OFF** *(Network)* | **`Off`** | Prevents background wireless/BT takeover conflicts over USB |
| **USB Power Supply** *(Setup > USB Power Supply)* | **`Off`** *(recommended)* | Prevents USB bus power confusion during power-switch / battery-pull checks |
| **File Format / Frame Rate** *(Movie)* | **`XAVC HS 4K` / `XAVC S 4K` / `XAVC S-I 4K`, `24p` (`23.98p`), `25p` (`PAL`), or `30p` (`29.97p`), Full Frame** | Matches the open-gate `0x8c0` (NTSC 24p/30p) and `0x820` (PAL 25p) readout modes (`3840x2560`) |
| **S&Q / APS-C / Proxy / Auto Framing / Clear Image Zoom** | **`Off`** | Keep full-frame sensor readout and clean gyro/framing geometry |
| **Camera Firmware** | `ZV-E1`: **`2.02`** · `a7S III`: **`5.01`** · `FX3`: **`7.02`** | Exact SHA-256 `DeviceInfo.xml` & memory-page identity check |

> [!TIP]
> Close **Finder** windows showing the camera card, **Photos**, and **Image Capture** before connecting USB so macOS can unmount the card cleanly.

---

## 3. Primary 1-Click Express Workflow (~6–8 Seconds, Zero Cable Replugs)

### 3A. 6-Second macOS Desk Smoke Test (`OpenGate Studio.app` v0.3.0-alpha)

1. **Cold-boot & Stills mode:** **Pull the battery for >= 10 seconds**, re-insert a charged battery, power the camera **ON**, and confirm it is in **Stills mode** (never enter Movie mode before applying):
   - **ZV-E1 (`zve1_202`):** Press the **Still / Movie / S&Q** button until **Stills** is active.
   - **a7S III (`a7s3_501`):** Turn the physical mode dial to a **Stills** position (`M` / `A` / `S` / `P`).
   - **FX3 (`fx3_702`):** Press **`MODE`**, select a still-image mode (e.g., **Manual Exposure** or **Program Auto**), and press the control wheel centre.
2. **Connect USB-C & auto-detect:** Plug USB-C directly from Mac to camera (card in Slot 1, `Mass Storage`). `OpenGate Studio.app` passively auto-detects **`ZV-E1`**, **`a7S III`**, or **`FX3`** (`ILME-FX3` passes; **`ILME-FX3A` is blocked** with a red warning).
3. **Select preset & click Apply:** Choose **Safe Daily 3:2** (`Q19`: `mp4_3x2,screen_3x2`) or **Cinema Full** (`F19`: `mp4_3x2,screen_3x2,hdmi32,high_bitrate,xavc_si`) and click **Apply Open-Gate (3:2)** (after a battery swap, the button updates to **Swapped Battery? Re-Apply (1-Click)** / **Pulled Battery >=10s — Check & Apply (1-Click)**).
4. **Approve single macOS admin prompt:** Toggle the confirmation switch if shown (volatile-RAM consent is remembered after the first run) and approve the single macOS administrator prompt (Touch ID or password).
5. **Wait ~6–8 seconds in one single USB session:** `Q19` / `F19` verifies firmware identity and stock RAM (aborting with zero writes on `mixed_powerswitch` or mismatch), applies all stages in order, and reads back every site in-place with **zero cable replugs** and **no Movie-mode replug**.
6. **Unplug & record:** When the sheet reports **`VERDICT READY (open gate applied)`**, unplug USB-C, switch to **Movie** (`24p` / `25p` / `30p` **only** — never `50p` / `60p` / `120p`), and record:
   - One **10s tripod framing clip** (e.g., circular target + top/bottom tape markers)
   - One **15s handheld gyro clip** (3s still -> slow pan -> two gentle wrist rolls -> 3s still)

### 3B. Android USB-OTG 1-Tap Field Companion (`OpenGate-Field-Companion-v0.3.0-alpha-debug.apk`)

1. **Sideload APK:**
   ```bash
   adb install -r dist/OpenGate-Field-Companion-v0.3.0-alpha-debug.apk
   ```
2. **Connect USB-C OTG cable:** Put the camera in **Stills** mode (`Mass Storage`, normal card in Slot 1), connect the USB-C OTG cable to your Android phone, and accept the Android USB permission prompt once.
3. **Confirm once per body:** Check the one-time firmware / volatile-RAM confirmation box (remembered per body across battery swaps).
4. **Tap & wait ~6–8s:** Tap **Apply Safe Daily 3:2 (~6s, 1-Tap)** (`Q19`) or **Cinema Full 3:2** (`F19`), wait ~6–8s for the single-session read-back verification (`VERDICT READY`), then unplug USB-C, switch to **Movie** (`24p` / `25p` / `30p` **only**), and shoot.

### 3C. CLI Equivalent & Dry-Run Readiness Commands

Run offline `--dry-run` previews anytime without `sudo` or a camera attached, or run live Express commands from Terminal:

```bash
# Offline dry-run preview (Safe Daily 3:2 -> Q19)
./macos/run_live_terminal.sh express-apply --body zve1_202 --packs mp4_3x2,screen_3x2 --dry-run

# Live 1-pass Express Apply (Safe Daily 3:2 -> Q19)
./macos/run_live_terminal.sh express-apply --body zve1_202 --packs mp4_3x2,screen_3x2

# Live 1-pass Express Apply (Cinema Full -> F19)
./macos/run_live_terminal.sh express-apply --body a7s3_501 --packs mp4_3x2,screen_3x2,hdmi32,high_bitrate,xavc_si

# Live 1-pass Express Restore Stock RAM (Q20 / F20)
./macos/run_live_terminal.sh express-putback --body zve1_202 --packs mp4_3x2,screen_3x2
```

*(Substitute `--body zve1_202`, `a7s3_501`, or `fx3_702`. Add `--simulate-events --json-events` alongside `--dry-run` to preview the exact JSON event stream.)*

### 3D. Advanced / Custom-Pack Multi-Step Workflow

For custom pack subsets that do not map to fused `Q19` / `F19` (such as adding optional **`fx3_playback`** `P29`/`P30` on `fx3_702`, or omitting `screen_3x2`), `express-apply` automatically batches `[check, ...apply_steps, check]` inside **one single USB session** (`run_batch_single_session`), still aborting with zero writes if the opening check is not stock.

Standalone diagnostics and legacy multi-replug commands also remain available in **Advanced Tools** (overflow menu in `OpenGate Studio.app`) or via CLI:
- **Standalone read-only preflight / Movie-mode panel dump:** `./macos/run_live_terminal.sh preflight --body <body_id>` and `./macos/run_live_terminal.sh dump --body <body_id>`
- **Legacy step-by-step replug apply + closing Movie-mode `dump`:** `./macos/run_live_terminal.sh apply --body <body_id> --packs <comma_list>` (requires prior `preflight`, prompts for USB replugs between individual `.so` helpers, and finishes with a Movie-mode `dump` such as capturing FX3 `paneltype` page `0x1490000`).

### 3E. Body-Specific Notes (`ZV-E1`, `a7S III`, `FX3`)

- **ZV-E1 (`zve1_202`):**
  - `23.98p` (`v2`, including SteadyShot Active / Dynamic Active) is hardware-confirmed; `25p` (PAL) and `29.97p` (`30p`, Long-GOP & XAVC S-I) are Unicorn-verified and ready for camera validation.
  - **C2 key** in Movie mode cycles preview aspect **`3:2 -> 2:1 (1.33x) -> 2.25:1 (1.5x) -> 2.4:1 (1.6x) -> 3:2`** (`S16` + `C19`). Cycle back to **`3:2`** before running `express-putback` / `putback` or a closing `dump`.
  - **Do NOT toggle the power switch** mid-test without pulling the battery: `av-cam.bin` / `libmpr.so` retain patches across a warm power cycle while coprocessor RAM resets.
- **a7S III (`a7s3_501`):**
  - `23.98p` is hardware-confirmed; `25p` (PAL via `0x820`) and `29.97p` (`30p`, Long-GOP & XAVC S-I) are Unicorn-verified and ready for camera validation.
  - **C3 key** in Movie mode cycles preview aspect **`3:2 -> 2:1 -> 2.25:1 -> 2.4:1 -> 3:2`** (`S16` + `C19`). Cycle back to **`3:2`** before running `express-putback` / `putback`.
  - Also test **3:2 HDMI output** (`hdmi32`), **200M/300M Long-GOP** (`high_bitrate`), and **XAVC S-I All-Intra 3840x2560** (`xavc_si`) on a V90 SD / CFexpress Type A card.
  - **Warm Power-Switch Partial Reset (Issue #3):** On `5.01`, flipping only the power switch resets coprocessor RAM (`ogsq` / `outsz2560`) while retaining main-processor encoder patches (`av-cam.bin` / `libmpr.so`), leaving the camera in `mixed_powerswitch` (`VERDICT NOT READY`). Always **pull the battery >= 10s** to restore clean stock.
  - Known workaround: if live view turns purple after switching Stills -> Movie, start/stop a 1-second recording to re-initialize the sensor readout cleanly.
- **FX3 (`fx3_702`):**
  - Verify the body is **`ILME-FX3`**, **not** `ILME-FX3A` (the app blocks `ILME-FX3A` automatically during passive USB detection).
  - `L5`/`L6` (`ogsq_fx3_v2`, fused inside `Q19`/`Q20`/`F19`/`F20`) include dual NTSC (`0x8c0`: `23.98p` / `29.97p`) + PAL (`0x820`: `25p`) `MULTI_REC` support (`23.98p`, PAL `25p`, and `4:3` panel capture confirmed in community testing; `29.97p` Long-GOP & XAVC S-I Unicorn-verified).
  - `S16` patches `lcd32dsq_fx3_v1`, keeping **`MENU > Setup > Display Option > De-Squeeze Display`** at `1.3x / 1.5x / 1.6x / 2.0x` calibrated for 3:2.
  - If you need the FX3 rear-panel `paneltype` (`0x1490000`) diagnostic capture (`sessions/camera_private/CT6_*/cp_*.bin`), run **`dump`** in Movie mode via Advanced Tools.
  - **Playback Freeze Warning & Optional `fx3_playback` (`P29`/`P30`):** Without `fx3_playback`, playing an open-gate clip on FX3 shows `"Unable to display"` and **retrying freezes the camera until battery pull**. Do **not** press Playback on FX3 unless explicitly testing optional `fx3_playback` (`P29`/`P30`, **untested on hardware**): if testing `P29`, play **1 normal 16:9 clip first**, then **1 open-gate clip**, and **never retry** if it errors.
  - Test `mp4_3x2`, `hdmi32` (external 16:9 monitor pillarboxed 3:2), `high_bitrate`, and `xavc_si` (`avc1` 3840x2560) recording stability.

---

## 4. Verify Recorded Clips & Gyro Telemetry (`bionz_clip_check.py`)

Copy the recorded `Cxxxx.MP4` and matching `CxxxxM01.XML` sidecar files to a folder on your Mac (keep card originals intact), then inspect via the **Clips** workspace (open a clip or SD card folder and view the right-side **Inspector**) in `OpenGate Studio.app` or CLI:

```bash
# Baseline stock clip (expects 3840x2160)
.venv/bin/python -B cli/bionz_clip_check.py /path/to/stock/C0001.MP4 --expect stock --xml /path/to/stock/C0001M01.XML --json

# Open-gate native 3:2 clip (expects 3840x2560 tkhd/stsd/VPRF + rtmd gyro packets)
.venv/bin/python -B cli/bionz_clip_check.py /path/to/opengate/C0002.MP4 --expect open-gate --xml /path/to/opengate/C0002M01.XML --json
```

**Success criteria:**
1. **`3840x2560` native geometry** (`display_aspect: "3:2"`, `vprf_3x2: true`) opens at 3:2 in DaVinci Resolve / Premiere without re-muxing.
2. **`rtmd_gyro_present: true`** with non-zero `rtmd_samples` — verify stabilization in **Gyroflow** or **Sony Catalyst Browse** using the original camera MP4 directly.
3. **In-camera playback** opens and plays back the `3840x2560` clip without error (where supported).

---

## 5. Returning to Stock (`Restore Stock RAM` `Q20`/`F20` or Battery Pull)

- **Software putback (same power-on, ~6–8s 1-click):** Switch back to **Stills** mode, cycle C2/C3 preview to **3:2** (ZV-E1 / a7S III), and click **Restore Stock RAM** (`Q20` / `F20`) in `OpenGate Studio.app` (or tap Restore Stock RAM in the Android app / run `./macos/run_live_terminal.sh express-putback --body <body_id> --packs <packs>`).
- **Hardware reset (always works):** Turn off the camera and **pull the battery for >= 10 seconds**. All volatile RAM patches vanish immediately.
