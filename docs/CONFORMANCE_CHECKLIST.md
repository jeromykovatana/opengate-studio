# OpenGate Studio — Field Conformance Checklist (`ZV-E1 2.02` · `a7S III 5.01` · `FX3 7.02`)

Printable field protocol for collecting **untouched camera originals** and verified `live_usb` session proofs to promote cells in [`docs/support_matrix.json`](support_matrix.json) and upgrade [`presets/gyroflow/calibration_profiles.json`](../presets/gyroflow/calibration_profiles.json) from `estimated_from_imx510_line_ratio` to `hardware_measured`.

> [!CAUTION]
> - **Volatile RAM Only:** Every patch runs in `/tmp/jiritsu/libJit.so`. Zero persistent writes to `nflasha*`, `boot0`/`boot1`, or `BK4`. **Pulling the battery >= 10 seconds always restores stock.**
> - **Never Re-Mux Originals:** Keep camera `Cxxxx.MP4` + `CxxxxM01.XML` files untouched. `ffmpeg` strips Sony `rtmd` gyro streams.
> - **Mock Sessions Never Count:** Only verified `live_usb` preflight + closing dump sessions qualify as hardware proof.
> - **50p / 60p / 120p Blocked:** Record strictly in `23.98p` (`24p`), `25p` (`PAL`), or `29.97p` (`30p`) while Open Gate is applied.

---

## Phase 0 — Camera Setup & Cold Boot

### Laptop & Kit Verification
- [ ] Run SHA-256 pin check: `.venv/bin/python -B cli/studio_cli.py verify-pins --json` (`"ok": true`).
- [ ] Close **Finder** windows showing cards, **Photos**, and **Image Capture**.
- [ ] Confirm exact body/firmware target:
  - [ ] `zve1_202`: **Sony ZV-E1** firmware **`2.02`**
  - [ ] `a7s3_501`: **Sony a7S III** (`ILCE-7SM3`) firmware **`5.01`**
  - [ ] `fx3_702`: **Sony FX3** (`ILME-FX3` only — **not** `ILME-FX3A`) firmware **`7.02`**

### Camera Menu Settings
- [ ] **Slot 1 Card:** Normal formatted V90 SD / CFexpress Type A card inserted (**zero** files copied onto card).
- [ ] **Setup > USB > USB Connection:** `Mass Storage` (not PC Remote, MTP, or Auto).
- [ ] **Setup > USB > USB LUN Setting:** `Multi` (or `Single`).
- [ ] **Network > Smartphone Conn / Cnct. while Power OFF:** `Off`.
- [ ] **Setup > USB > USB Power Supply:** `Off`.
- [ ] **Movie > Image Quality/Rec:** `XAVC HS 4K` / `XAVC S 4K` / `XAVC S-I 4K`, `24p` (`23.98p`), `25p` (`PAL`), or `30p` (`29.97p`), Full Frame (`APS-C`, `S&Q`, `Proxy`, `Auto Framing`, `Clear Image Zoom` = `Off`).

### Cold Boot
- [ ] **Pull battery >= 10 seconds**, re-insert charged battery, power **ON**.
- [ ] Put camera in **Stills mode** (`ZV-E1` Still button; `a7S III` mode dial `M`/`A`/`S`/`P`; `FX3` `MODE` -> Stills).

---

## Phase 1 — Safe Daily 3:2 Live USB Cycle

1. **Read-Only Preflight (Gate 2):**
   - Connect USB-C directly from Mac to camera.
   - Run **Read-Only Preflight** in `OpenGate Studio.app` (or `./macos/run_live_terminal.sh preflight --body <BODY_ID>`).
   - [ ] Confirm verdict: **`VERDICT READY (stock preflight)`** (`mode="live_usb"`, `verified=true`).
2. **Apply Safe Daily 3:2 (`core_open_gate`, `mp4_3x2`, `screen_3x2`):**
   - Select **`mp4_3x2,screen_3x2`** (add `hdmi32`, `high_bitrate`, `xavc_si`, or `fx3_playback` only if specifically testing experimental packs).
   - Run **Apply Selected Packs** (or `./macos/run_live_terminal.sh apply --body <BODY_ID> --packs mp4_3x2,screen_3x2`).
   - [ ] Keep camera switched **ON**; replug USB cable between steps when prompted.
   - [ ] When prompted for closing **Movie-mode `dump`**: unplug USB, switch to **Movie** mode, observe 5 seconds (if live view looks purple on a7S III, start/stop a 1s dummy clip), replug USB.
   - [ ] Confirm closing verdict: **`VERDICT READY (open gate applied)`** (`verified=true`).
3. **Verify `latest-session`:**
   ```bash
   .venv/bin/python -B cli/studio_cli.py latest-session --body <BODY_ID> --mode live_usb --json
   ```

---

## Phase 2 — 7-Clip (+ Optional Thermal Soak) Shot List

Keep a single locked scene/chart for Clips 1 & 7 so horizontal FOV and vertical top/bottom headroom are directly comparable.

| # | Slot Name | Mode / Packs | SteadyShot / Lens | Camera Move & Duration | What It Proves |
|---|---|---|---|---|---|
| **1** | **Framing Chart (3:2 Open Gate)** | `open-gate`, `23.976p` | SteadyShot **OFF**, OSS **OFF** | **10s locked tripod** on circular target + top/bottom tape markers at `3:2` edge | Full `3840x2560` sensor height captured without crop or distortion |
| **2** | **IBIS OFF Gyro Reference** | `open-gate`, `23.976p` | SteadyShot **OFF**, OSS **OFF** | **20s handheld**: 3s static -> slow pan -> 2 gentle wrist rolls -> 3s static | Clean `rtmd` body gyro baseline for **Gyroflow** & **Catalyst Browse** |
| **3** | **IBIS Standard Gyro Test** | `open-gate`, `23.976p` | SteadyShot **Standard** *(NOT Active)* | **20s handheld** matching Clip 2 move | Evaluates Standard IBIS behavior vs OFF in post gyro solvers |
| **4** | **Readout Calibration Pan / Strobe** | `open-gate`, `23.976p` | SteadyShot **OFF**, fast shutter (`1/500+`) | **10s fast horizontal whip-pan** across a plumb vertical pole/doorframe (or LED strobe) | Measures real `frame_readout_time_ms` (vs estimated `10.3 ms` IMX510) |
| **5** | **25p PAL & 29.97p NTSC Matrix** | `open-gate`, `25.000p` & `29.970p` | SteadyShot **OFF** | **10s each** at `25p` (`0x820`) and `29.97p` (`0x8c0`); optional `XAVC S` / `S-I` | Verifies NTSC/PAL `MULTI_REC` & rate-code-2 container/gyro cadence |
| **6** | **Third-Party / Anamorphic Lens** | `open-gate`, `23.976p` | SteadyShot **OFF** (or OSS **OFF**) | **15s** E-mount 3rd-party AF lens or manual/anamorphic (`C2`/`C3` or `De-Squeeze` / `hdmi32`) | Confirms `M01.XML` focal-length logging or manual/anamorphic workflow |
| **7** | **Post-Putback Stock 16:9 Baseline** | **Run `putback` or battery pull >= 10s first!** `stock`, `23.976p` | SteadyShot **OFF** | **10s locked tripod** on exact same Clip 1 framing chart (`3840x2160`) | Clean return to stock + exact 16:9 vs 3:2 framing comparison |
| **8** | *(Optional)* **Thermal & Card Soak** | `open-gate`, `23.976p` | SteadyShot **Standard** or **OFF** | **30–60 min continuous roll** on V90 / CFexpress Type A; log ambient C & card | Sustained card write, constant frame cadence, and thermal stability |

> [!WARNING]
> **FX3 `7.02` In-Camera Playback:** Do **NOT** press Playback on open-gate clips unless `fx3_playback` (`P29/P30`) is explicitly active; retrying `"Unable to display"` freezes stock FX3 until battery pull. If testing `fx3_playback`, play **1 stock 16:9 clip first**, then **1 open-gate clip**, and **never retry** on error.

---

## Phase 3 — CLI Verification, Pass Rubric & `support_matrix.json` Promotion

Copy all untouched `Cxxxx.MP4` + `CxxxxM01.XML` files from the SD/CFexpress card into a clean Mac folder `<CLIPS_DIR>` (keep folder structure or include `stock` in Clip 7's filename/subfolder so auto-detection classifies it as `stock`).

### 1. Copy-Paste CLI Commands
```bash
# A. Batch ingest & container/rtmd/delivery crop check
.venv/bin/python -B cli/studio_cli.py ingest-batch <CLIPS_DIR> --body <BODY_ID> --json

# B. Single-clip deep Gyroflow & Catalyst diagnostic (Clip 2 example)
.venv/bin/python -B cli/studio_cli.py gyro-diagnose <CLIPS_DIR>/C0002.MP4 --xml <CLIPS_DIR>/C0002M01.XML --body <BODY_ID> --json

# C. Conformance Audit (verifies live_usb sessions, rejects mock, writes clean-room report)
.venv/bin/python -B cli/studio_cli.py conformance-audit \
  --body <BODY_ID> \
  --clips-dir <CLIPS_DIR> \
  --session-dir /tmp/opengate_studio_sessions \
  --out-dir <OUT_DIR> \
  --json

# D. Full Field Report (optional environment & thermal metadata)
.venv/bin/python -B cli/studio_cli.py build-report \
  --body <BODY_ID> \
  --session-dir /tmp/opengate_studio_sessions \
  --clips-dir <CLIPS_DIR> \
  --out-dir <OUT_DIR> \
  --media-card "Sony CEA-G 160GB" \
  --lens "FE 24mm F1.4 GM" \
  --ambient-c "22C" \
  --gyro-app "Gyroflow 1.6.x" \
  --editor-app "DaVinci Resolve 19" \
  --json
```

### 2. Gyroflow / Catalyst / NLE Pass Rubric

| Tool / Gate | Pass Criteria | Fail / Reject Condition |
|---|---|---|
| **Gyroflow (`rtmd`)** | Loads untouched `3840x2560` MP4 directly; `rtmd` trace aligns without manual drift; horizon/pan stabilizes cleanly with Clip 2 (`SteadyShot OFF`) and measured readout time removes vertical skew on Clip 4 | Missing gyro stream, `>100 ms` drift, corner swimming from Active SteadyShot, or ffmpeg-remuxed file |
| **Sony Catalyst Browse** | Opens untouched `Cxxxx.MP4` + `CxxxxM01.XML` at native `3840x2560` (`3:2`), enables gyro stabilization on Clip 2 (`SteadyShot OFF`), exports stabilized frame without `16:9` crop distortion | Aspect stuck at `16:9`, stabilization greyed out on AF lens, or XML mismatch |
| **NLE (Resolve / Premiere)** | Native timeline attributes show `3840x2560`, pixel aspect `1:1` (Square), constant FPS (`23.976` / `25.000` / `29.970`), audio synced, **zero** ffmpeg pre-remuxing | Displays `16:9` squeeze, dropped frames, or decoder error on `avc1` L5.1 (`38,400` MBs) |
| **In-Camera Playback** | Plays back Clip 1/2/5 cleanly in camera without freeze (`fx3_playback` tested on FX3 only per safety rule) | `"Unable to display"` error or freeze |

### 3. `docs/support_matrix.json` Promotion & Calibration Upgrade Workflow

1. Re-run `conformance-audit` passing the verified operator flags and measured rolling-shutter readout time (from Clip 4 in Gyroflow):
   ```bash
   .venv/bin/python -B cli/studio_cli.py conformance-audit \
     --body <BODY_ID> \
     --clips-dir <CLIPS_DIR> \
     --session-dir /tmp/opengate_studio_sessions \
     --out-dir <OUT_DIR> \
     --measured-readout-ms <MEASURED_MS> \
     --evidence-note "Measured via vertical-pan calibration on untouched <BODY_ID> open-gate clip" \
     --gyroflow-ok --catalyst-ok --nle-ok --playback-ok \
     --json
   ```
   *(Add `--thermal-ok` if Clip 8 sustained soak passed.)*
2. Inspect `matrix_recommendations.eligible_promotions` and `calibration_patch` in `<OUT_DIR>/conformance_manifest.json` (and `<OUT_DIR>/CONFORMANCE_REPORT.md`).
   - `conformance-audit` is strictly **dry-run**: it never mutates `docs/support_matrix.json` or `presets/gyroflow/calibration_profiles.json` automatically.
   - Confirm `<OUT_DIR>/CONFORMANCE_REPORT.md` and `<OUT_DIR>/conformance_manifest.json` contain **no raw serial numbers** and **no `CT6` memory dumps**.
3. Apply the approved promotions in `docs/support_matrix.json` (and `calibration_patch` in `presets/gyroflow/calibration_profiles.json`), then regenerate and verify:
   ```bash
   python3 scripts/generate_support_matrix.py
   python3 scripts/generate_support_matrix.py --check
   python3 scripts/verify_clean_room.py
   ```
4. Attach `<OUT_DIR>/CONFORMANCE_REPORT.md`, `<OUT_DIR>/conformance_manifest.json`, and screenshots to the GitHub **Field Test Report** issue.
