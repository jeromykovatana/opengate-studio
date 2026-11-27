# ZV-E1 2.02 · `V19` 3:2 Metadata, Non-Truncated NRT XML & Gyro Test

**Priority 1 Target (`studio_conformance_plan.py`).** Under `v0.1.3-alpha` (`a2c3cda8`), ZV-E1 `2.02` (`32000_08.2025101101`) hardware clips (`C6433`–`C6436`) proved native `3840x2560` MP4 geometry, `2000 Hz` `rtmd` (`0xe40e` readout `12.336 ms`), and Gyroflow `v1.7.1` stabilization using a non-destructive `repair-nrt-xml` copy, while trailing NRT XML truncated at `<NonRealTimeMeta>`. The updated `V19` helper ([`kits/zve1_202/manifest.json`](../kits/zve1_202/manifest.json): `libJit_zv_V19.so`, `ogfile2560_hs_s_zv_v3`, SHA-256 prefix `511e8afe`) moves `L3-nrt-vline` into `NrtMetaWrapper::Init` so fresh `23.98p` hardware clips write complete `<Device>`, `<VideoLayout>`, and `<VideoFrame>` metadata out-of-the-box — promoting `zve1_202` `mp4_3x2` `clip_xml_validated` from `🟡` (`partial`) to `✅` (`yes`).

Print the full ZV-E1 runbook or run the offline V19 self-test anytime:
```bash
.venv/bin/python -B cli/studio_conformance_plan.py --body zve1_202
.venv/bin/python -B cli/studio_conformance_plan.py --offline-selftest --json
```

> [!CAUTION]
> - **Volatile RAM Only:** Nothing is flashed to camera eMMC or written to the SD card. Pull the battery >= 10 seconds anytime to restore clean stock.
> - **Keep Camera ON During Apply / Putback:** Never flip the power switch between steps; always pull the battery >= 10s if a reset is needed.
> - **Never Re-Mux Originals:** Keep camera `Cxxxx.MP4` + `CxxxxM01.XML` files untouched.

---

## 1. Set Up Once (`OpenGate Studio.app` / Android Companion)

- Open **`OpenGate Studio.app`** -> **`Camera`** workspace, select **`ZV-E1 2.02`**, and click **`Setup Guide…`** (or open **`OpenGate Field Companion`** on Android and select **`ZV-E1 2.02`**).
- Confirm camera firmware **`2.02`** (`MENU > Setup > Setup Option > Version`).
- Set Movie mode to NTSC, **XAVC HS 4K, 24p (23.98p / 23.976p), 50M 4:2:0 10-bit**, Full Frame. Turn **Off** `APS-C / Super 35`, `S&Q`, `Proxy Recording`, `Auto Framing`, and `Clear Image Zoom`.
- Set **Setup > USB > USB Connection** = `Mass Storage`, **USB Power Supply** = `Off`, **Smartphone Conn / Cnct. while Power OFF** = `Off`, **Setup > Power Setting Option > Power Save Start Time** = `Off`, **Power Save by Monitor** = `Off`, **Auto Power OFF Temp.** = `High`, and keep a normal formatted SD card in **Slot 1** (zero files copied onto the card).
- Close **Finder** card windows, **Photos**, and **Image Capture** on Mac (or ensure **`Offline Simulation Mode`** is **OFF** so the toolbar pill shows **`Live USB`**).
- Shoot landscape with a Sony E-mount lens that reports focal length (e.g., `FE 24mm F1.4 GM`). Turn camera **SteadyShot** and lens **OSS** **Off** for baseline takes, lock focus/exposure/WB, and use steady light (`1/125 s` or `1/500+` for readout calibration).
- Mark a wall chart with a circular center target, left/right frame markers, and tape strips just above and below the stock `16:9` frame on a locked tripod.

---

## 2. Live USB / USB-OTG Apply (`Safe Daily 3:2` with `V19` `511e8afe`)

1. **Verify Kit Integrity:** Open **`Diagnostics`** (`Diagnostics & Field Tools` -> `Pins`) or run:
   ```bash
   .venv/bin/python -B cli/studio_cli.py verify-pins --body zve1_202 --json
   ```
   Confirm `"ok": true` and `V19` (`libJit_zv_V19.so`) SHA prefix `511e8afe`.
2. **Cold Boot in Stills Mode:** Pull the ZV-E1 battery for **>= 10 seconds**, re-insert, power ON, press the **Still** button (`Stills` mode), and tick both **`Before Connecting`** toggles in **`Camera`** workspace (or both checkboxes in **`OpenGate Field Companion`**).
3. **Read-Only Preflight:** Plug in USB-C (or USB-OTG) and click **`Check Camera (Read-Only)`**. Confirm **`VERDICT READY (stock preflight)`** (`mode="live_usb"`).
4. **Apply Safe Daily 3:2:** Confirm **`Open-Gate Profile`** is **`Safe Daily 3:2`** (`core_open_gate` + `mp4_3x2` + `screen_3x2`: `L13 -> L5 -> L16 -> V19 -> S16 -> C19`) and click **`Apply Open-Gate (3:2)`** (Android: **`Apply Safe Daily 3:2`**). Replug USB when prompted; switch to **Movie** mode for the closing `dump` (if standby looks purple, start/stop a 1s dummy clip before replugging) and confirm **`VERDICT READY (open gate applied)`**.

---

## 3. Six Short Clips (+ Stock Putback Baseline)

| State | Framing Take | Gyro Take |
|---|---|---|
| **A · Stock (`16:9`)** | **A1.** Record the locked wall chart for **10 seconds** at `3840x2160`. | **A2.** Record the **20-second** handheld doorframe move below (`SteadyShot OFF`). |
| **B · Prior Baseline** *(Reference)* | Existing `v0.1.3-alpha` (`a2c3cda8`) clips `C6433`–`C6436` already archived in `docs/conformance/zve1_202/`. | Re-use archived `repair-nrt-xml` baseline only as reference comparison. |
| **C · Fresh `V19` (`511e8afe`)** | **C1.** Under `Safe Daily 3:2` (`V19` `511e8afe`), record the exact locked tripod chart for **10 seconds**. Both top/bottom tape markers must enter frame cleanly. | **C2.** Repeat the **20-second** handheld move (`SteadyShot OFF`), then play **C1** and **C2** back in-camera and note playback status. |
| **D · Post-Putback Stock** | Run **`Restore Stock RAM`** in **`Camera`** workspace (or pull battery **>= 10s**), verify stock `3840x2160` framing on the same locked chart. | Optional: export Android session bundle via **`Export Session Bundle (Excludes Private Dumps)`**. |

**20-second handheld gyro move:** Aim at a detailed scene with a vertical doorframe. Hold still **3s**, pan right and back **8s**, make two gentle wrist rolls **6s**, and hold still **3s**.

---

## 4. Inspect Untouched Originals (`Clips` Workspace & CLI)

Copy untouched `Cxxxx.MP4` + `CxxxxM01.XML` pairs into clean local folders (`A/`, `C/`, `STOCK/`).

1. **In `OpenGate Studio.app`:** Switch to the **`Clips`** workspace, click **`Open Clip or Card…`** (or drop the folder), and verify:
   - Native `3840x2560` (`3:2`), `VPRF 3:2 = YES`, `XML 3:2 = YES` (without running `repair-nrt-xml`), `rtmd` gyro stream present, and `Inspector` (`Clip Inspector`) shows complete metadata.
   - Open **`Diagnostics`** (`Diagnostics & Field Tools` -> **`Field Report`**) to generate `FIELD_REPORT.md` + `field_report.json`.
2. **Equivalent CLI Commands (run on untouched originals without `repair-nrt-xml`):**
   ```bash
   # Stock A1/A2 check
   .venv/bin/python -B cli/studio_cli.py check-clip A/C0001.MP4 --expect stock --xml A/C0001M01.XML --body zve1_202 --json

   # Fresh V19 C1/C2 check (must pass ok=true with ZERO NRT XML truncation)
   .venv/bin/python -B cli/studio_cli.py check-clip C/C0005.MP4 --expect open-gate --xml C/C0005M01.XML --body zve1_202 --json

   # Batch + Gyroflow readiness + dry-run matrix promotion audit
   .venv/bin/python -B cli/studio_cli.py ingest-batch <CLIPS_DIR> --body zve1_202 --json
   .venv/bin/python -B cli/studio_cli.py gyro-diagnose C/C0006.MP4 --xml C/C0006M01.XML --body zve1_202 --json
   .venv/bin/python -B cli/studio_cli.py conformance-audit \
     --body zve1_202 \
     --clips-dir <CLIPS_DIR> \
     --session-dir /tmp/opengate_studio_sessions \
     --out-dir <OUT_DIR> \
     --measured-readout-ms 12.336 \
     --gyroflow-ok --catalyst-ok --nle-ok --playback-ok \
     --json
   ```

---

## 5. What Counts as Matrix Promotion Success (`🟡` -> `✅`)

1. **Non-Truncated NRT XML (`V19` `511e8afe`):** Untouched `C1`/`C2` MP4 + `M01.XML` pass `check-clip` (`ok: true`, `vprf_3x2: true`, `xml_3x2: true`, `embedded_xml_present: true`) with complete `<Device manufacturer="Sony" modelName="ZV-E1"/>`, `<VideoLayout pixel="3840" numOfVerticalLine="2560" aspectRatio="3:2"/>`, and `<VideoFrame .../>` — **zero** `repair-nrt-xml` needed.
2. **Framing:** `A1` reads `3840x2160`; `C1` reads `3840x2560` square pixels (`1:1`) in DaVinci Resolve / Premiere, circle is round, and top/bottom tape markers enter frame with identical horizontal coverage to `A1`.
3. **Gyro & Catalyst:** `C2` opens directly in Gyroflow and Sony Catalyst Browse using only the untouched camera original, aligns still/pan/roll intervals with `~12.336 ms` readout calibration, and stabilizes cleanly without drift or corner warping.
4. **Promote `docs/support_matrix.json`:** Confirm `conformance-audit` recommends promoting `zve1_202` `23.98p` `mp4_3x2` `clip_xml_validated` (`partial` -> `yes`) plus `catalyst_verified`, `nle_verified`, `playback_verified`, and `field_ready`, update `docs/support_matrix.json`, and run `python3 scripts/generate_support_matrix.py && python3 scripts/generate_support_matrix.py --check`.
