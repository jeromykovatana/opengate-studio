# Pressure-Test, Reliability & Field Report Guide (`ZV-E1 2.02` · `a7S III 5.01` · `FX3 7.02`)

This guide is designed to produce **verifiable, pressure-tested reliability evidence** answering every practical question creators ask about Sony 3:2 Open Gate (`3840×2560`): thermal endurance, card sustained writes, H.264 / All-Intra vs. H.265 codecs, anamorphic autofocus via HDMI, field re-activation timing, and 100% battery-pull reversibility.

> [!CAUTION]
> **Hard Safety Rules (Read First):**
> 1. **100% Volatile RAM Only (`persistent_writes: false`):** Every patch lives strictly in volatile camera RAM (`/tmp/jiritsu/`). Zero bytes touch `nflasha*` eMMC flash, `boot0`/`boot1`, or `BK4` settings. **Pulling the battery for >= 10 seconds restores 100% stock state.**
> 2. **Read-Only Gate First:** Never click **Apply** until **Preflight** returns `VERDICT READY (stock preflight)` on your exact firmware (`ZV-E1 2.02`, `a7S III 5.01`, or `FX3 7.02` — **NOT `ILME-FX3A`**).
> 3. **Safe Frame Rates Only (`23.98p / 25p / 30p`):** Never switch to `50p`, `60p`, or `120p` while Open Gate is applied (`IMX510` 36 MHz readout ceiling causes distortion/crash).
> 4. **FX3 Playback Freeze Warning:** On stock FX3 `7.02`, pressing Playback on an open-gate clip displays `"Unable to display"`, and retrying freezes the camera until a battery pull. Do **not** press Playback on FX3 unless explicitly running the single-shot `fx3_playback` (`P29`) test.
> 5. **Never Upload Private Camera Dumps:** Never attach `sessions/camera_private/*.bin` or firmware binaries to public reports. Only share `FIELD_REPORT.md`, `field_report.json`, clip inspector outputs, screenshots, and sample clips/photos.

---

## 1. Camera Prep Checklist (Before Phase 0)

- **Slot 1 Card:** Formatted V60/V90 SD or CFexpress Type A card (recommended for `300M` and `XAVC S-I`). Leave **zero** hack files on the card.
- **USB & Power:** `USB Connection = Mass Storage`, `USB Power Supply = Off`, `Smartphone Connection / Cnct. while Power OFF = Off`.
- **Thermal Setting:** `Auto Power OFF Temp. = High`. On FX3, set `Cooling Fan = Auto` (or `Minimum` / `Off while Rec` — record which you used).
- **Audio & Stabilization:** Leave **audio ON** (for sync claps). Turn **SteadyShot = Off** for tripod framing & Gyroflow baseline takes (so Gyroflow gets clean `rtmd` telemetry), then test Active SteadyShot separately if desired.
- **Suggested Test Folder on Mac:** Create one clean folder (e.g., `~/Desktop/og_pressure_test_<body_id>/`) and copy untouched card `Cxxxx.MP4` + `CxxxxM01.XML` pairs, rear-LCD phone photos, and NLE/Gyroflow screenshots into it using the suggested filenames below.

---

## 2. Step-by-Step Pressure-Test Protocol

### Phase 0 — Cold-Boot Reversibility & Zero-Trace Proof
1. Pull battery for **>= 10 seconds**, boot into **Stills** mode, and run **Read-Only Preflight** (`VERDICT READY (stock preflight)`).
2. Apply your target preset (`Safe Daily 3:2` or `Cinema Full`).
3. **Power-Off Reversibility Check:** Power off, pull battery for **>= 10 seconds**, boot back into **Stills**, and run **Preflight** again. Confirm it returns **`VERDICT READY (stock preflight)`** — proving zero persistent writes.
4. *(Optional Warm Power-Switch Check)* If testing whether flipping only the power switch leaves `mixed_powerswitch`, run Preflight after a switch-off/on without pulling the battery, record the result, then pull the battery >= 10s before continuing.

### Phase 1 — Field Re-Activation Stopwatch Test
Because volatile RAM resets on battery swaps / power-off, time how fast a field re-activation actually is:
1. Cold-boot in **Stills** mode, plug in USB-C, start a stopwatch when you click **Preflight -> Apply**, and stop when the closing Movie-mode verification completes.
2. Record seconds separately for:
   - **`Safe Daily 3:2`** (`mp4_3x2`, `screen_3x2`) — fewest USB steps for fast battery-swap recovery.
   - **`Cinema Full`** (`mp4_3x2`, `screen_3x2`, `hdmi32`, `high_bitrate`, `xavc_si`).

### Phase 2 — Codec & Frame-Rate Matrix (H.265, H.264, All-Intra)
Record 10–15 second clips across every combination your card supports (confirming it is **not** H.265-only):
- **XAVC HS 4K (H.265 10-bit):** `24p (23.98p)` stock bitrate + `high_bitrate` (`200M/300M`), plus `25p` (PAL) and `30p (29.97p)` if testing multi-rate.
- **XAVC S 4K (H.264 8-bit & 10-bit 4:2:2):** `24p (23.98p)` + `high_bitrate` (`200M/300M`), plus `25p`/`30p`.
- **XAVC S-I 4K (H.264 All-Intra, `xavc_si`):** `24p (23.98p)` / `25p` / `30p` on CFexpress Type A / V90. Note whether DaVinci Resolve, Premiere Pro, and QuickTime open the `3840×2560` AVC Level 5.1 stream cleanly (`bionz_clip_check.py` flags the 38,400 macroblock info notice automatically).

### Phase 3 — Native 3:2 Framing + `rtmd` Gyroflow / Catalyst Proof
1. **Locked Tripod Framing Pair (`10s` each):**
   - Put a circular object near center and tape markers just above and below the stock 16:9 frame edge on a wall.
   - Record **Stock 16:9** (`A1_stock.MP4`) before applying, then **Open Gate 3:2** (`B1_og_framing.MP4`) from the exact same tripod mark.
2. **Handheld Gyro Pair (`20s` each, SteadyShot OFF):**
   - Frame a vertical doorframe. Hold still **3s**, pan right and back **8s**, make two gentle wrist rolls **6s**, hold still **3s**.
   - Record **Stock (`A2_stock_gyro.MP4`)** and **Open Gate (`C2_og_gyro.MP4` + `C2_og_gyroM01.XML`)**.
   - Open the untouched card `C2` `.MP4` directly in **DaVinci Resolve / Premiere** (confirm `3840×2560`, `1:1` square pixels, round circle, zero `ffmpeg` remux) and in **Gyroflow / Sony Catalyst Browse** (confirm `rtmd` motion trace matches the still/pan/roll moves and stabilizes cleanly).

### Phase 4 — Anamorphic + Autofocus + Clean 3:2 HDMI (`hdmi32`)
1. Connect an external HDMI monitor (or capture card) with the **`hdmi32`** pack active.
2. **Keep camera internal De-Squeeze Display = OFF** (so Sony AF stays enabled!). Set anamorphic de-squeeze (`1.33x` / `1.5x` / `2.0x`) on the **external monitor** instead.
3. Half-press / tap-track a subject with Continuous AF (`AF-C`), and also test **Monitor & Control** or external monitor **False Color / Waveform**.
4. Record a short phone video showing the external monitor de-squeezed 3:2 feed + active AF tracking box, and compare against internal De-Squeeze Display ON (which Sony's firmware forces to MF).

### Phase 5 — 30–60 Minute Thermal & Sustained Card-Write Soak Test
1. Note **ambient room temp (°C)**, **card brand/speed**, **Auto Power OFF Temp = High**, and **FX3 fan setting**.
2. Clap on camera at the **start** and **end** of the take (for audio/sync drift check).
3. Record continuously for **30–60 minutes** at `23.976p` (ideally testing `200M/300M` or `XAVC S-I` if card capacity allows, or `XAVC S 100M` / `XAVC HS 100M`).
4. Log:
   - Whether a thermal warning icon appeared (and at what minute), or if it hit a thermal shutdown.
   - Whether recording dropped frames, stalled, or stopped cleanly.
   - Measured `duration_sec`, `avg_bitrate_mbps`, and `cadence_constant` from `bionz_clip_check.py`.

### Phase 6 — Known Edge Cases
- **Stills -> Movie Purple/Black Live-View Glitch:** Note whether entering Movie from Stills showed purple/black live view, and confirm whether a 1-second record start/stop cleared it cleanly.
- **FX3 In-Camera Playback:** Only test if `fx3_playback` (`P29`) is explicitly enabled — play **1 normal 16:9 clip first**, then **1 open-gate clip**, and **never retry** if `"Unable to display"` appears.

---

## 3. Recommended Image & Video Sample Shot List

Capture these **8 items** in one folder so the report has visual proof for every skeptic question:

| # | Sample Asset | Suggested Filename(s) | What It Proves in the Public Report |
|---|---|---|---|
| 1 | **Stock 16:9 Tripod Clip (10s)** | `A1_stock_framing.MP4` (+ `M01.XML`) | Baseline horizontal FOV & clipped top/bottom tape markers |
| 2 | **Open-Gate 3:2 Tripod Clip (10s)** | `B1_og_framing.MP4` (+ `M01.XML`) | Extra vertical sensor height revealed, round circle, zero stretch |
| 3 | **Handheld Gyro Pan+Roll Clip (20s)** | `C2_og_gyro.MP4` (+ `M01.XML`) | Untouched card MP4 proving native `3840×2560` + `rtmd` Gyroflow sync |
| 4 | **Codec Matrix Clips (10s each)** | `codec_xavcs_h264.MP4`, `codec_xavcsi.MP4`, `codec_2997p.MP4` | Proves H.264, All-Intra, `200M/300M`, and `25p`/`30p` work (not H.265 only) |
| 5 | **30–60 Min Thermal Soak Clip** | `soak_45m_300m.MP4` (+ `M01.XML`) | Real endurance, constant frame cadence, sustained card bitrate, thermal log |
| 6 | **Rear LCD / De-Squeeze Phone Photos** | `lcd_3x2.jpg`, `lcd_desqueeze_15x.jpg` | Shows true 3:2 framing, AF boxes, and De-Squeeze / C2/C3 aspect cycle |
| 7 | **HDMI + Active AF Phone Clip / Photo** | `hdmi_af_monitor.mov` / `hdmi_af.jpg` | Proves clean `hdmi32` output + False Color/scopes + AF working simultaneously |
| 8 | **Resolve & Gyroflow Screenshots** | `resolve_3840x2560.png`, `gyroflow_rtmd.png` | Shows NLE clip properties (`3840×2560`) and Gyroflow `rtmd` trace without `ffmpeg` |

---

## 4. How to Report Back (Builds `FIELD_REPORT.md` + `field_report.json`)

### Option A — Inside `OpenGate Studio.app` (Recommended)
1. Open **Diagnostics & Field Tools** (toolbar wrench icon or `Cmd+Option+D`) and select **Field Report**.
2. Click **Select Test Clips Folder…** and pick your folder of `.MP4` / `.XML` clips, photos, and screenshots.
3. Fill in **Media Card**, **Lens**, **Ambient °C**, **Soak Mins**, **Thermal Result**, **Re-Activation Secs**, and **AF + De-Squeeze / HDMI Notes**.
4. Click **Generate Report Bundle**, then click **Copy Markdown** (to paste straight into chat or a [GitHub Field Test Issue](https://github.com/jeromykovatana/opengate-studio/issues/new?template=field-test-report.yml)) or **Reveal in Finder**.

### Option B — Pure Python CLI
```bash
python3 cli/studio_cli.py build-report \
  --body fx3_702 \
  --clips-dir ~/Desktop/og_pressure_test_fx3 \
  --media-card "Sony CEA-G 160GB CFexpress Type A" \
  --lens "Sony FE 24mm f/1.4 GM" \
  --ambient-c "23C" \
  --soak-minutes "45" \
  --thermal-result "No thermal warning (Auto Power OFF Temp = High, Fan Auto)" \
  --reactivation-seconds "58" \
  --af-desqueeze-notes "hdmi32 + internal De-Squeeze OFF kept AF-C tracking active on Atomos Ninja" \
  --gyro-app "Gyroflow 1.6.x" \
  --editor-app "DaVinci Resolve 19" \
  --json
```

This writes three clean, safe files (`FIELD_REPORT.md`, `field_report.json`, and `sample_intake_manifest.json`) — never reading or copying anything from `camera_private/`.
