# Sony BIONZ XR Feature Unlock & Marketplace Roadmap (`a7S III` / `FX3` / `ZV-E1` / `a7 IV`)

**Audit Date:** 2026-11-24  
**Scope & Verification Basis:** Synthesized from 100% offline reverse-engineering across [OFFSET_AUDIT.md](OFFSET_AUDIT.md) and offline feature track audits (`UPGRADE_PRIORITIES.md`, `01_og_codecs_and_rasters.md` through `05_falsecolor_and_discovery_scan.md`), checked offline by `verify_swarm_designs.py`.

> [!CAUTION]
> **Hard Safety & Legal Guardrails:**
> - **100% Volatile RAM Only (`"persistent_writes": false`):** Every emitted design targets `/proc/self/mem` (`libmpr.so` / `appFw.so` strictly inside `PT_LOAD[0]` `file_off == va <= p_filesz`), `/dev/mem` (`av-cam.bin`), or coprocessor RAM (`cpapp-b.bin` at `0x108000` / `DmmCfg.bin` RAM). A cold boot (battery pull >= 10s) restores 100% stock state.
> - **Zero Persistent Flashing & Zero Paid DRM Bypasses:** Zero scripts touch `nflasha*`, `boot0`/`boot1`, `BK4`, or `BACKUP.BIN`. Paid Sony license checks (`CUSTOM_GRID`, `C2PA`, `DIGITAL_SIGNATURE`, paid `LICENSE_TYPE_DCI4K_24P` / `LICENSE_TYPE_4K120P`) are explicitly excluded (**Score `0`**).
> - **Read-Only `CT6` Gate Required Before Hardware Trials:** Never invoke live USB / `sudo` / `--go` without explicit user approval and an identity-verified `CT6_memory_read_check` (`VERDICT READY`) run on the exact target firmware.

---

## What to use or test first

1. **Use the stock monitoring tools.** The a7S III 5.01 and ZV-E1 2.02 already support focus magnification in manual focus during Bright Monitoring. The a7S III also imports 16 user LUTs. Cine EI remains a separate research question. Sony documents Flexible ISO for the ZV-E1 too. [a7S III firmware](https://www.sony.com/electronics/support/e-mount-body-ilce-7-series/ilce-7sm3/software/00345071) · [ZV-E1 firmware](https://www.sony.com/electronics/support/e-mount-body-zv-e-series/zv-e1/software/00296227) · [a7S III LUT guide](https://helpguide.sony.net/ilc/2410/v1/en/contents/211h_manage_lut.html) · [ZV-E1 Log modes](https://helpguide.sony.net/ilc/2310/v1/en/contents/211h_log_shoot_setting.html)
   The ZV-E1 also has Focus Map for movies and electronic flash sync at 1/30 s full-frame or 1/60 s APS-C. [Sony Focus Map](https://www.sony.com/electronics/support/articles/00291305) · [Sony ZV-E1 specifications](https://www.sony.com/electronics/support/e-mount-body-zv-e-series/zv-e1/specifications)
2. **Add false color, waveform and vectorscope to the field workflow.** Sony Monitor & Control displays them on a compatible phone or tablet for all four open-gate target models. Test framing and latency with your capture mode before relying on the mobile preview. This addresses the monitoring need immediately. [Sony camera and function matrix](https://helpguide.sony.net/promobile/mc/v1/en/contents/supported_camera.html)
3. **Collect one matched set of originals.** Start with a stationary camera and a moving subject on the ZV-E1. Keep a stock clip, an open-gate clip, their Sony XML sidecars and, if available, a simultaneous HDMI capture. Record the body firmware, kit revision, codec, frame rate, lens and stabilization setting. Verify added field of view, editor framing, usable gyro stabilization and HDMI edge visibility separately. The first physical FX3 baseline is still outstanding. See [ZVE1_RECORDING_TEST.md](ZVE1_RECORDING_TEST.md).
4. **Keep design validation and availability visible.** Fourteen design files pass the offline checks. I found no reference to these new design families in the three ports’ checked-in desktop launchers or Python runners. Each candidate needs a documented kit revision that delivers it and an original clip or display capture before listing it as available on a body. For a7 IV 5.7K, validate the upstream cadence and metadata fixes first. In-camera playback remains a separate issue. [a7 IV kit revision](https://github.com/ArcaneLantern/a7iv-open-gate-test/blob/2f2a02190808797a01b31a27d5eb17cfea3d4820/README.md)

## 1. Scoring Methodology & Audited Baselines

Every original baseline capability, emitted volatile design, and newly discovered hidden or blocked feature is scored from **#1 downward** using:

$$\text{Composite Score} = \text{Market Demand}_{(1\text{–}10)} \times \text{Binary Readiness}_{(0\text{–}10)} \times \text{Safety/Reversibility}_{(0\text{–}10)} \quad (\max = 1{,}000)$$

- **Market Demand (`1–10`):** Real-world filmmaker/creator willingness to adopt or pay (`10` = flagship workflow unlocks like 3:2 Open Gate + Gyro, clean 3:2 HDMI, All-Intra, Shutter Angle, Cine EI; `7–9` = high-bitrate codecs, de-squeeze, DCI 4K, False Color/Waveform; `4–6` = ergonomic/monitoring assists; `1–3` = niche single-setting toggles).
- **Binary Readiness (`0–10`):**
  - `10`: Live camera recording reported or native retail ground truth + verified offset table.
  - `9`: **Offline JSON Emitted** — 100% offline SHA-256, `PT_LOAD[0]`/`cpapp`/`av-cam`, Capstone, and zero-overlap 16B guard verification passed (`verify_swarm_designs.py` `exit 0`).
  - `7–8`: **Grade B** — Complete backend + IPC + isolated `PT_LOAD[0]` or `cpapp` candidate exists; needs short read-only `CT6` runtime dump or upstream firmware extraction.
  - `4–6`: **Grade C** — Compiled backend/IPC exists, but multi-layer `PT_LOAD[1]` / `.bss` HAITA/PRM snapshots, DMM pool bounds, or stripped `205xxx` / `.text` handlers block safe static `PT_LOAD[0]` emission.
  - `1–2`: **Grade D / E** — Hardware-blocked (`IMX510` 36 MHz ceiling, missing AI NPU/e-ND/mechanical shutter) or compile-time stub / strings-only (`str wzr, [x1]; ret`, dead writer, stripped code).
  - `0`: **Hard Policy Exclusion** — Paid DRM / license infrastructure.
- **Safety / Reversibility (`0–10`):**
  - `10`: Volatile single-module `/proc/self/mem` (`PT_LOAD[0]`) or isolated `cpapp` RAM patch, battery-pull reversible, zero persistent writes, zero side-effect blast radius.
  - `8–9`: Multi-binary volatile RAM stack (`cpapp` + `av-cam` + `libmpr`) with zero guard collisions; requires card speed, decoder compatibility (e.g., AVC Level 5.1 macroblocks), or mode-transition testing.
  - `5–7`: Requires DMM memory-pool reallocation, `.bss` snapshot state coordination, or exhibits known recoverable runtime quirks (Stills->Movie glitch).
  - `1–4`: Global selector blast radius (`87/116` HAITA flags flipped) or known crash trigger (`60p` under `ogsq`).

### Verified 12.1MP Firmware Baselines (`MANIFEST.json` SHA-256 Pinned)

| Body | Firmware (`version.txt`) | Build ID | Runtime `PRODUCT_MODEL` (`appFw.so`) | `appFw.so` `PT_LOAD[0]` | `libmpr.so` `PT_LOAD[0]` | `cpapp-b.bin` (`0x108000+`) |
|---|---|---|---|---|---|---|
| **ILCE-7SM3 (a7S III)** | `5.01` (`39183_16.2026041504`) | `a7s3_501` | `PRODUCT_MODEL_OT_UUD` (`20`, `fm_idx=6`, col `6`) | `<= 0x502835f` | `<= 0x2eafa4` | `len 0xf627e0` |
| **ILME-FX3 (FX3)** | `7.02` (`39180_21.2025122503`) | `fx3_702` | `PRODUCT_MODEL_ALCIN_UUD` (`4`, `fm_idx=6`, col `1`) | `<= 0x3d0f79d` | `<= 0x2e192c` | `len 0xf3d818` |
| **ZV-E1** | `2.02` (`32000_08.2025101101`) | `zve1_202` | `PRODUCT_MODEL_SA` (`5`, `fm_idx=19`, col `0`) | `<= 0x4afa87d` | `<= 0x2c7ee4` | `len 0x11065a0` |

*(Reference 33MP baseline: `ILCE-7M4` `6.02` `a7iv_602` in `a7iv-open-gate-test`; `firmwares/a7iv/` has no `BODYDATA.DAT` unpacked in this workspace.)*

---

## 2. Master Ranked Feature & Discovery Roadmap (#1 Downward)

| Rank | Feature / Capability | Target Models | Tier / Grade | Demand | Readiness | Safety | **Composite** | Status / Action |
|---:|---|---|---|---:|---:|---:|---:|---|
| **1** | **3:2 Open Gate `3840x2560` 23.98p Baseline + LCD Preview & Cycle** | a7S III `5.01`, ZV-E1 `2.02`, FX3 `7.02`, a7 IV `6.02` | **Field reports vary by body** | 10 | 10 | 9 | **900** | Live-recorded on S3/ZV-E1/a7 IV; FX3 emulated (`ogsq`/`outsz`/`ogfile2560_hs_s`/`dmmwb`/`lcd*`) |
| **2** | **Native 3:2 MP4 Container, Gyro (`rtmd`) Preservation & In-Camera Playback** | a7S III `5.01`, FX3 `7.02`, ZV-E1 `2.02` | **Offline design** (Emitted JSON x3) | 10 | 9 | 10 | **900** | [mp4_3x2_s3_501.json](../designs/mp4_3x2_s3_501.json), [mp4_3x2_fx3_702.json](../designs/mp4_3x2_fx3_702.json), [mp4_3x2_zv_202.json](../designs/mp4_3x2_zv_202.json) |
| **3** | **Clean 3:2 Pillarboxed & Uncropped Anamorphic HDMI Output** | a7S III `5.01`, FX3 `7.02`, ZV-E1 `2.02` | **Offline design** (Grade A JSON x3) | 9 | 9 | 10 | **810** | [hdmi32_s3_501.json](../designs/hdmi32_s3_501.json), [hdmi32_fx3_702.json](../designs/hdmi32_fx3_702.json), [hdmi32_zv_202.json](../designs/hdmi32_zv_202.json) |
| **4** | **High-Bitrate `200M / 300M` Long-GOP Overlay (`XAVC HS` & `XAVC S`)** | a7S III `5.01`, FX3 `7.02`, ZV-E1 `2.02` | **Offline design** (Grade A JSON x3) | 9 | 9 | 9 | **729** | [og_highbitrate_s3_501.json](../designs/og_highbitrate_s3_501.json), [og_highbitrate_fx3_702.json](../designs/og_highbitrate_fx3_702.json), [og_highbitrate_zv_202.json](../designs/og_highbitrate_zv_202.json) |
| **5** | **XAVC S-I 4K All-Intra `3840x2560` Open Gate + Native MP4/Playback** | a7S III `5.01`, FX3 `7.02`, ZV-E1 `2.02` | **Offline design** (Grade A JSON x3) | 9 | 9 | 8 | **648** | [og_xavcsi_s3_501.json](../designs/og_xavcsi_s3_501.json), [og_xavcsi_fx3_702.json](../designs/og_xavcsi_fx3_702.json), [og_xavcsi_zv_202.json](../designs/og_xavcsi_zv_202.json) *(verify AVC L5.1 MB limit on-clip)* |
| **6** | **Focus Magnifier during Bright Monitoring** | a7S III 5.01, ZV-E1 2.02 | **Stock feature** | — | — | — | — | Use manual focus in stills mode. Sony documents this combination on both builds. |
| **7** | **Digital / Clear-Image Zoom Monitoring & AF Exclusion Removal (`FM-digzoom-excl`)** | a7S III `5.01` *(ZV-E1 Retail)* | **Offline design** (Grade A JSON x1) | 5 | 9 | 10 | **450** | Included in [monitoring_assist_s3_501.json](../designs/monitoring_assist_s3_501.json) |
| **8** | **a7 IV 5.7K playback in camera** | a7 IV 6.02 | **Playback unverified** | 10 | 7 | 9 | **630** | Upstream reports fixes for held frames and editor import. Validate the upstream kit before new development. |
| **9** | **Stills -> Movie Open-Gate Live-View Glitch Fix (Full Sensor Re-Init)** | a7S III `5.01`, ZV-E1 `2.02` | **Next-Wave** (suspected cause) | 8 | 7 | 8 | **448** | Route `0x86cb60`/`0x86d608` mode switch -> `0x86cde6` `fullinit` (workaround: press Rec / `IMG INIT`) |
| **10** | **Custom Memory Recall During S1/S2 Half-Press (`custom_mr_during_s1s2`)** | a7S III `5.01`, ZV-E1 `2.02` | **Next-Wave** (Grade B) | 6 | 8 | 9 | **432** | `0x371f260 = 1 -> 0` (S3) / `0x35734fc` (ZV); needs short S1/S2 shutter-hold `CT6` test |
| **11** | **Cine EI / Cine EI Quick / Dual Base ISO (`800/12800`)** | a7S III `5.01` *(FX3 retail Cine EI)* | **Next-Wave** (Grade C) | 10 | 5 | 7 | **350** | Backend compiled; needs `CT6` `.bss` (`0x7f7d8f8`/`0x7f7d8d8`) + `PT_LOAD[1]` HAITA resolution |
| **12** | **True Adjustable Shutter Angle (`MODE_SHUTTER` + `SHUTTER_ANGLE`)** | a7S III `5.01` *(FX3 Retail)* | **Next-Wave** (Grade C) | 10 | 5 | 7 | **350** | Backend compiled; `CT6` probe needed on `.bss` PRM (`57/119`) & HAITA (`79` callers) |
| **13** | **29.97p (`NTSC 30p`) & 25.000p (`PAL`) Open Gate `3840x2560`** | a7S III `5.01`, FX3 `7.02`, ZV-E1 `2.02` | **Next-Wave** (Math Valid) | 7 | 6 | 8 | **336** | 54 candidates at 25p and 52 at 29.97p fit the observed stock timing pattern within the verifier’s search. Camera capture remains unverified. |
| **14** | **Standalone Anamorphic De-Squeeze (`1.3x`/`2.0x` UI) on a7S III `5.01`** | a7S III `5.01` *(ZV/FX3 Retail)* | **Next-Wave** (Grade C) | 8 | 5 | 8 | **320** | `cmd 0x147` + `cpapp` exist (`1.5x/1.8x` absent); needs `CT6` check on `BKID 0x815`/`0x83b` |
| **15** | **OneMount Image Size Switch (`image_size_switch_onemount`)** | a7S III `5.01`, FX3 `7.02` *(ZV Retail)* | **Next-Wave** (Grade B) | 4 | 8 | 9 | **288** | `0x371fdc0 = 1 -> 0` (S3) / `0x2f9a180` (FX3); verify `cpapp` IPC `0x402d` `set_still_format` |
| **16** | **Cross `24.00p` UI / Screen Indicator Flag (`0x17f88d0`)** | a7S III `5.01` *(ZV Enabled)* | **Next-Wave** (Grade B) | 4 | 7 | 9 | **252** | `0x371f420 = 0 -> 1` (23 callers); verify True-24.00p UI integration with `ogsq` |
| **17** | **Soft Skin Effect (`0x4049`)** | a7S III `5.01`, FX3 `7.02` *(ZV Retail)* | **Next-Wave** (Grade B/C) | 4 | 7 | 9 | **252** | Identical `0x4049` IPC + `cpapp` table across all 3 models; gated in `.uxc`/`menu_item` |
| **18** | **True DCI 4K (`4096x2160` `24.00p` / `XAVC S-I DCI 4K`)** | ZV-E1 `2.02` *(S3 Free/FX3 Retail)* | **Next-Wave** (Grade C) | 8 | 4 | 7 | **224** | `cpapp` + `libmpr` + primary `105230..105241` present; `205xxx` + `.text` handlers + `ARGO` HAITA stripped |
| **19** | **Preset Focus / Zoom (`0x414f`/`0x414d`)** | a7S III `5.01`, ZV-E1 `2.02` *(FX3 Retail)* | **Next-Wave** (Grade C) | 6 | 5 | 7 | **210** | Real `sequence_set_preset_focus_zoom` IPC + `cpapp` strings; hidden in S3/ZV `.uxc` menu |
| **20** | **Framing Stabilizer (`FIXED_CAMERA_FRAMING`)** | a7S III `5.01` *(FX3/ZV Retail)* | **Next-Wave** (Grade C) | 6 | 5 | 7 | **210** | `sequence_set_eframing` + `20` unique `cpapp` strings + `BK4=1` exist; menu `.uxc` gated |
| **21** | **Dynamic Active SteadyShot (`MOVIE_STEADYSHOT_ACTIVE_PLUS`)** | a7S III `5.01` *(ZV Retail; FX3 Absent)* | **Next-Wave** (Grade C) | 7 | 4 | 6 | **168** | `0x400c`/`0x407d` IPC + `BK4=3` exist, but `0x354a494` != ZV `0x33fd464`; needs live IBIS check |
| **22** | **Step Crop Shooting (`CROP_SHOOTING`) & Vertical Display** | a7S III `5.01` *(ZV Retail; FX3 Absent)* | **Next-Wave** (Grade C) | 5 | 5 | 6 | **150** | `72` `CROP_SHOOTING` + `9` `VERTICAL_DISPLAY` symbols; menu `.uxc` gated |
| **23** | **Native-Width 4.1K Open Gate (`4096x2720` / `4096x2736` mod 16)** | a7S III `5.01`, FX3 `7.02`, ZV-E1 `2.02` | **Next-Wave** (`DMM`/`Lrc`-Blocked) | 8 | 3 | 6 | **144** | Exceeds `0x2d9` (`13.27 MB` pool) by `>700 KB`; needs live `0x43f`/`0x498` DMM + `Lrc` phase tuning |
| **24** | **Background Defocus (`0x405a`/`0x4145`) & Cinematic Vlog (`CINEMATIC_MODE`)** | a7S III `5.01`, FX3 `7.02` *(ZV Retail)* | **Next-Wave** (Grade C) | 4 | 5 | 7 | **140** | Real `0x405a`/`0x4145` IPC + 295 `CINEMATIC_MODE` symbols; hidden by `.uxc`/`menu_item` |
| **25** | **Secondary Cross-Model UI Unlocks (Still Log S3, Focus Bracket FX3, BULB Timer ZV, Timeshift S3)** | Model-specific | **Next-Wave / Partial** (`C` / `E`) | 3–5 | 3–4 | 6–7 | **54–140** | Mixed partial IPC (`0x4159` ZV Bulb) vs stubs (`S3` Timeshift/Still Log `0` vtable, `FX3` Focus Bracket unsupported) |
| **26** | **BIG6 Cinema Layout (S3 `C/D`) / Product Showcase (S3 `C/E`) / Var. Shutter Flicker (`E/C`)** | a7S III / FX3 / ZV-E1 | **Blocked / Partial** (`C/D` & `E`) | 6 | 2 | 5 | **60** | S3 `product_concept` `0x17f84f8` affects body/CFexpress/dial ID; S3 `0x416c` lock & `FLICKER_SCAN` are stubs |
| **27** | **ZV-E1 16-bit External HDMI RAW** | ZV-E1 `2.02` *(S3/FX3 Retail)* | **Blocked Offline** (`PT_LOAD[1]` / Stripped) | 9 | 2 | 3 | **54** | `T0[1052..1054]` in `PT_LOAD[1]` (`OT_UUD=0/SA=0`), UI stripped, `0` refs to Sabin `0xf58830` |
| **28** | **a7S III BIG6 e-ND Readout / ZV-E1 Mech Shutter** | a7S III / ZV-E1 | **Hardware-Blocked** (`D`) | 5 | 1 | 5 | **25** | Physical hardware absent (no internal e-ND on S3; `mecha_shutter=1` no mechanical shutter on ZV-E1) |
| **29** | **AI Subject Recognition (`Animal/Bird/Insect/Car/Plane` Movie) & Auto Framing** | a7S III `5.01`, FX3 `7.02` *(ZV Retail)* | **Hardware-Blocked** (`D`) | 8 | 1 | 3 | **24** | `GEN_TYPE_2` vs ZV-E1 `GEN_TYPE_4` AI NPU; `0` callers on S3/FX3 FM rows |
| **30** | **False Color (`FALSE_COLOR_*`)** | a7S III `5.01` *(0 hits FX3/ZV)* | **Strings / Dead Stub** (`E`) | 9 | 1 | 2 | **18** | S3 `0x8482a60` has 1 dead writer (`0x2aaa500`), **0 readers**, **0 IPC**, **0 `cpapp`** |
| **31** | **Waveform & Vectorscope (`VIDEO_SIGNAL_MONITOR_*`)** | a7S III `5.01`, ZV-E1 `2.02` *(0 hits FX3)* | **Strings / Stubbed IPC** (`E`) | 9 | 1 | 2 | **18** | Compile-time `str wzr, [x1]; ret` stubs (`0x35220cc` S3, `0x33cca94` ZV); debug table only in `cpapp` |
| **32** | **BIG6 Home Screen (ZV-E1) & ZV-E1 Shutter Angle / `1.5x`/`1.8x` De-Squeeze** | ZV-E1 `2.02` | **Stripped (`E`)** | 7 | 1 | 2 | **14** | `update_big6_item_iso_ei`, `GUIDE_BIG6_*`, `shutter_angle_*_seq`, and `1.5x`/`1.8x` completely stripped |
| **33** | **4.2K `4224x2816` Open Gate (`IMX510` Native Width)** | All 3 12.1MP Bodies | **Blocked (`D/E`)** | 7 | 1 | 2 | **14** | Exceeds `0x2d9` (`14.87 MB`), `Opt-vprf-si` masks `0xfeffffff` (`3840`/`4096` only), 0 codec tables |
| **34** | **Pixel Shift Multi-Shoot (`PX_SHIFT_MULTI_SHOOT`) & FX30 Pixel Shift / 8K** | 12.1MP Bodies / FX30 | **Strings / Hardware (`E/D`)** | 3 | 1 | 2 | **6** | `0` `sequence_*px_shift*` IPC & `0` `cpapp` hits; FX30 pixel shift boot-looped & <8K photosites |
| **35** | **48p / 50p / 59.94p (60p) Full-Height Open Gate (`3840x2560`)** | All 3 12.1MP Bodies | **Outside modeled timing limits** (`D`) | 10 | 0 | 1 | **0** | `IMX510` @ `36 MHz` ceiling `36.747 Hz` (`col=1`) / `47.158 Hz` (`col=3`) -> `0` solutions (crashes 60p) |
| **EX** | **Paid DRM / License Features (`CUSTOM_GRID`, `C2PA`, `DIGITAL_SIGNATURE`, Paid `DCI4K_24P`/`4K120P`)** | All Bodies | **Policy Excluded** | — | 0 | 0 | **0** | **Never bypass.** Direct users to Sony official regional licenses |

---

## 3. Offline RAM Designs (Verified in Binary + JSON Emitted)

All **14 JSON files** in `designs/` and **15 repo baseline JSONs** across `a7siii-open-gate-test`, `fx3-open-gate-test`, and `zve1-open-gate-test` passed 100% offline verification via `verify_swarm_designs.py` (**491 patches, 9 optional sites, 370 non-overlapping 16B stock guards, 0 collisions**).

### 3.1 Emitted JSON Inventory & Design Links

| Feature Package | Model (`Build`) | Firmware (`version.txt`) | Target Binaries | Patches (`Bytes`) | Opt (`B`) | 16B Guards | Verified Design File |
|---|---|---|---|---:|---:|---:|---|
| **MP4 3:2 Container + Gyro + Playback** | a7S III (`a7s3_501`) | `5.01` (`39183_16.2026041504`) | `libmpr.so` (`PT_LOAD[0]`) | `8` (`32 B`) | `1` (`4 B`) | `17` | [mp4_3x2_s3_501.json](../designs/mp4_3x2_s3_501.json) |
| **MP4 3:2 Container + Gyro + Playback** | FX3 (`fx3_702`) | `7.02` (`39180_21.2025122503`) | `libmpr.so` (`PT_LOAD[0]`) | `8` (`32 B`) | `1` (`4 B`) | `17` | [mp4_3x2_fx3_702.json](../designs/mp4_3x2_fx3_702.json) |
| **MP4 3:2 Container + Gyro + Playback** | ZV-E1 (`zve1_202`) | `2.02` (`32000_08.2025101101`) | `libmpr.so` (`PT_LOAD[0]`) | `8` (`32 B`) | `1` (`4 B`) | `17` | [mp4_3x2_zv_202.json](../designs/mp4_3x2_zv_202.json) |
| **Clean 3:2 & De-Squeezed HDMI** | a7S III (`a7s3_501`) | `5.01` (`39183_16.2026041504`) | `cpapp-b.bin` (`0x108000+`) | `14` (`88 B`) | `0` (`0 B`) | `15` | [hdmi32_s3_501.json](../designs/hdmi32_s3_501.json) |
| **Clean 3:2 & De-Squeezed HDMI** | FX3 (`fx3_702`) | `7.02` (`39180_21.2025122503`) | `cpapp-b.bin` (`0x108000+`) | `8` (`60 B`) | `0` (`0 B`) | `7` | [hdmi32_fx3_702.json](../designs/hdmi32_fx3_702.json) |
| **Clean 3:2 & De-Squeezed HDMI** | ZV-E1 (`zve1_202`) | `2.02` (`32000_08.2025101101`) | `cpapp-b.bin` (`0x108000+`) | `8` (`46 B`) | `0` (`0 B`) | `13` | [hdmi32_zv_202.json](../designs/hdmi32_zv_202.json) |
| **XAVC S-I 4K All-Intra `3840x2560`** | a7S III (`a7s3_501`) | `5.01` (`39183_16.2026041504`) | `libmpr.so`, `av-cam.bin` | `42` (`138 B`) | `2` (`8 B`) | `43` | [og_xavcsi_s3_501.json](../designs/og_xavcsi_s3_501.json) |
| **XAVC S-I 4K All-Intra `3840x2560`** | FX3 (`fx3_702`) | `7.02` (`39180_21.2025122503`) | `libmpr.so`, `av-cam.bin` | `42` (`138 B`) | `2` (`8 B`) | `42` | [og_xavcsi_fx3_702.json](../designs/og_xavcsi_fx3_702.json) |
| **XAVC S-I 4K All-Intra `3840x2560`** | ZV-E1 (`zve1_202`) | `2.02` (`32000_08.2025101101`) | `libmpr.so`, `av-cam.bin` | `26` (`98 B`) | `2` (`8 B`) | `26` | [og_xavcsi_zv_202.json](../designs/og_xavcsi_zv_202.json) |
| **High-Bitrate `200M/300M` Long-GOP** | a7S III (`a7s3_501`) | `5.01` (`39183_16.2026041504`) | `av-cam.bin` | `108` (`675 B`) | `0` (`0 B`) | `54` | [og_highbitrate_s3_501.json](../designs/og_highbitrate_s3_501.json) |
| **High-Bitrate `200M/300M` Long-GOP** | FX3 (`fx3_702`) | `7.02` (`39180_21.2025122503`) | `av-cam.bin` | `108` (`675 B`) | `0` (`0 B`) | `54` | [og_highbitrate_fx3_702.json](../designs/og_highbitrate_fx3_702.json) |
| **High-Bitrate `200M/300M` Long-GOP** | ZV-E1 (`zve1_202`) | `2.02` (`32000_08.2025101101`) | `av-cam.bin` | `108` (`675 B`) | `0` (`0 B`) | `54` | [og_highbitrate_zv_202.json](../designs/og_highbitrate_zv_202.json) |
| **Bright-Mon Focus Mag + DigZoom AF** | a7S III (`a7s3_501`) | `5.01` (`39183_16.2026041504`) | `appFw.so` (`PT_LOAD[0]`) | `2` (`8 B`) | `0` (`0 B`) | `7` | [monitoring_assist_s3_501.json](../designs/monitoring_assist_s3_501.json) |
| **Bright-Mon Focus Mag** | ZV-E1 (`zve1_202`) | `2.02` (`32000_08.2025101101`) | `appFw.so` (`PT_LOAD[0]`) | `1` (`4 B`) | `0` (`0 B`) | `4` | [monitoring_assist_zv_202.json](../designs/monitoring_assist_zv_202.json) |

*(Note: `hdmi32_zv_202.json` lists legacy string labels `ogsq_zv_v1`/`ogfile2560_hs_s_zv_202` in `compatible_with`, while automated verification confirmed zero byte overlaps against the actual `zve1-open-gate-test` `ogsq_zv_v2` and `ogfile2560_hs_s_zv_v1` intervals.)*

### 3.2 Repo Open-Gate Foundation (`a7siii` / `fx3` / `zve1`)

- **a7S III `5.01` ([ArcaneLantern/a7siii-open-gate-test](https://github.com/ArcaneLantern/a7siii-open-gate-test)):** `ogsq_s3_v5.json` (`21` sites), `outsz2560_s3_v1.json` (`1` site, `2` guards), `ogfile2560_hs_s_s3_v1.json` (`105` sites), `lcdratio32_s3_v1.json` (`14` sites, `17` guards), `lcdcycle_s3_v3.json` (`93` sites).
- **FX3 `7.02` ([ArcaneLantern/fx3-open-gate-test](https://github.com/ArcaneLantern/fx3-open-gate-test)):** `ogsq_fx3_v1.json` (`21` sites), `outsz2560_fx3_v1.json` (`1` site, `2` guards), `ogfile2560_hs_s_fx3_v1.json` (`105` sites), `lcd32dsq_fx3_v1.json` (`30` sites, `32` guards).
- **ZV-E1 `2.02` ([ArcaneLantern/zve1-open-gate-test](https://github.com/ArcaneLantern/zve1-open-gate-test)):** `dmmwb_zv_v1.json` (`1` site: `10.33 MB -> 26.21 MB`), `ogsq_zv_v2.json` (`21` sites), `outsz2560_zv_v1.json` (`1` site, `2` guards), `ogfile2560_hs_s_zv_v1.json` (`105` sites), `lcdfill_zv_v2.json` (`5` sites, `9` guards), `lcdcycle_zv_v1.json` (`93` sites).

### 3.3 Recommended Hardware Test Order (After Explicit User Approval)

1. **Gate 0 — Offline & Read-Only Identity Check (Mandatory First Step):**
   - Run `tools/verify_swarm_designs.py` (`exit 0` offline).
   - With explicit user approval, run `s3_run.py` / `fx3_run.py` / `zv_run.py` `check --go --firmware-shown <ver>` and `dump --go --firmware-shown <ver>` to confirm `VERDICT READY` and zero unexpected memory diffs.
2. **Stage 1 — `mp4_3x2_*` + Existing Open-Gate Base (ZV-E1 `2.02` & a7S III `5.01` First, then FX3 `7.02`):**
   - Verify ZV-E1 `dmmwb_zv_v1 + ogsq_zv_v2` resolves the v1 movie-entry reboot, then add `mp4_3x2_zv_202` and `mp4_3x2_s3_501`. Confirm untouched MP4 clips import at `3840x2560` (`1:1` PAR) in DaVinci Resolve, play back in-camera, and stabilize via `rtmd` gyro in Catalyst / Gyroflow.
   - Establish the first physical FX3 `7.02` Open-Gate recording (`ogsq_fx3_v1 + outsz2560_fx3_v1 + ogfile2560_hs_s_fx3_v1 + lcd32dsq_fx3_v1 + mp4_3x2_fx3_702`).
3. **Stage 2 — `hdmi32_*` External Monitor & De-Squeeze Validation:**
   - Apply `hdmi32_{s3_501,zv_202,fx3_702}` over the Stage 1 stack; test external `16:9` HDMI monitor framing (`3:2` pillarbox `1620x1080` / `3240x2160`) and `1.3x`/`1.5x`/`1.65x`/`1.8x`/`2.0x` uncropped anamorphic de-squeeze (`FX3` native De-Squeeze + `S3`/`ZV` C-button cycle).
4. **Stage 3 — `og_highbitrate_*` (`200M` / `300M` Long-GOP) Soak Test:**
   - Apply `og_highbitrate_*` (`av-cam.bin` only) on V60 (`200M` modes) and CFexpress Type A / V90 (`300M` modes); run 10-minute thermal/buffer-drop soak tests at `23.976p`.
5. **Stage 4 — `og_xavcsi_*` All-Intra Validation (AVC Level 5.1 Decoder Check):**
   - Test `og_xavcsi_{s3_501,fx3_702,zv_202}` on CFexpress Type A (`240M`/`250M`). **Mandatory check:** inspect SPS `level_idc` (`51`, max `36,864` MBs vs `38,400` MBs at `3840x2560`) across Resolve, Premiere, FFmpeg, and in-camera playback (`Opt-vprf-si` `0xf600`) and record editor playback separately. A recording at this raster signaling Level 5.1 exceeds the level limit even if the tested decoders accept it.
6. **Stage 5 — Stock monitoring comparison**
   - Record stock Bright Monitoring and focus magnification on both bodies. Evaluate the separate a7S III zoom/AF hypothesis only if a repeatable limitation remains.

---

## 4. High-Potential Next-Wave Unlocks (Partial Gate / Needs Short Runtime Dump)

1. **a7 IV `6.02` `5760x3840` (`300M`) + Native `mp4_3x2` & In-Camera Playback (Score: `630`):**
   - Upstream already reports the cadence and metadata fixes. Use its latest kit as the reference for original-file and playback checks. See the field-kit link above.
2. **Stills -> Movie Open-Gate Live-View Glitch Fix (Score: `448`):**
   - Offline track audit (`02_og_60p_hdmi_and_raw.md`) identified a candidate explanation for the purple/half-black live view involving lightweight mode-switching (`0x86cb60` / `0x86d608` / `0x335a94`) skipping full sensor re-init (`0x86cde6` `fullinit`) until recording starts or `IMG INIT` triggers. Redirecting the Stills->Movie branch in `cpapp-b.bin` to `0x86cde6` can be validated cleanly via a short `cpapp` RAM patch + live-view check.
3. **Grade B Single-Gate `appFw.so` Unlocks (Score: `252–432`):**
   - **Custom Memory Recall During S1/S2 (`0x371f260` S3 / `0x35734fc` ZV-E1, `22`/`20` callers):** Full `w0 == 0` paths exist; needs `CT6` live shutter-hold verification.
   - **OneMount Image Size Switch (`0x371fdc0` S3 / `0x2f9a180` FX3):** Needs `cpapp` `0x402d` `set_still_format` confirmation.
   - **Cross `24.00p` UI Flag (`0x371f420` S3, `23` callers) & Soft Skin Effect (`0x4049`, `B/C`):** Real `cpapp` IPC exists; needs `.uxc`/UI visibility verification.
4. **Grade C Multi-Layer Cinema Line Unlocks on a7S III `5.01` & ZV-E1 `2.02` (Score: `210–350`):**
   - **a7S III Cine EI / Base ISO (`800/12800`):** Complete backend (`0x26c9d90`, `8` `sequence_*` LUT/Base ISO classes, `647` `cpapp` LUT refs, `220` `.uxc` files), but blocked from safe static `PT_LOAD[0]` patching by `PT_LOAD[1]` HAITA nodes (`0x58aefc0`, `0x58bf880`, `0x58bfa00`, `0x58bfac0`) feeding `.bss` snapshots (`0x7f7d8f8` / `0x7f7d8d8`) and an `87/116` blast radius on `0x3e28753`.
   - **a7S III Shutter Angle & Standalone De-Squeeze (`1.3x`/`2.0x`):** Compiled backends exist (`cmd 0x147` `0x351c330`, `mode_sh`/`sh_ang` setters), but gated by `PT_LOAD[1]` nodes (`0x5856b98`, `0x585ae08`, `0x585ffb8`) and `41`–`119` `.bss` PRM/HAITA callers. Requires the read-only `CT6` `.bss` snapshot protocol (`03_shutter_angle_and_desqueeze.md`) before designing a safe `PT_LOAD[0]` trampoline (verified `.text` cave `0x1e9db94`, len `0x150`).
   - **ZV-E1 True DCI 4K (`4096x2160` 24.00p):** `cpapp-b.bin` (`25` `<HH`, `35` packed, `outsz` `0x4ab592`), `libmpr.so` (`row 12` `0x2b2e18`), and primary `av-cam.bin` (`105230..105241`) exist, while all `24` `205xxx` rows, `.text` DCI handlers (`0` vs `12/20`), and `ARGO` `system_architecture` HAITA support are stripped.
   - **29.97p / 25.000p Open Gate (`3840x2560`):** `IMX510` @ `36 MHz` has `93` (`65` with `4|V`) exact solutions for `29.970p` (`(312,3840,16,13)`) and `78` (`55`) for `25.000p` (`(312,4608,2,1)`); needs live `stored_record` / DMM headroom tests.
   - **4.1K Open Gate (`4096x2720` / `4096x2736` mod 16):** Requires emulated DMM pool reassignment (`0x2d9` `13.27 MB` overflow -> `0x43f`/`0x498`) + horizontal `Lrc` tuning (`4096x2730` rejected due to odd `4:2:0` chroma height `1365`).
   - **Other Grade C `.uxc`/Menu-Gated Capabilities:** Preset Focus/Zoom (`0x414f`/`0x414d`), Framing Stabilizer (`FIXED_CAMERA_FRAMING`), Dynamic Active SteadyShot (`0x400c`/`0x407d` on S3), Step Crop & Vertical Display (S3), Background Defocus (`0x405a`/`0x4145`), and Cinematic Vlog (`CINEMATIC_MODE` on S3).

---

## 5. Hardware-Blocked / Strings-Only Items (Honest Exclusions)

Every item below was rigorously audited offline and **excluded from patch emission** so users are never misled by shared Sony boilerplate strings:

| Excluded Item | Grade | Root-Cause Proof Across Audited Binaries |
|---|---|---|
| **48p / 50p / 59.94p (60p) Full-Height Open Gate** | **D (modeled readouts)** | `IMX510` @ `36 MHz` (`V_min = 3140 col1 / 2982 col3`) yields ceilings of `36.747 Hz` (`col=1`) and `47.158 Hz` (`col=3`) with **`0` exact `(H,V,P,E)` solutions** within the modeled readouts. The crash mechanism remains unconfirmed. |
| **ZV-E1 16-bit External HDMI RAW** | **Blocked (`PT_LOAD[1]` / Stripped)** | `T0[1052..1054]` sit in `PT_LOAD[1]` (`OT_UUD=0/SA=0`), S3 RAW codec/menu UI is stripped, `chg_hdmi_res` (`0x2feee34`) has `0` callers, and Sabin `"/usr/sabin/dcv_psf_table_movie_hdmiraw.bin"` (`0xf58830`) has `0` `u32` references in `cpapp-b.bin`. |
| **False Color (`FALSE_COLOR_*`)** | **E (Dead Code)** | `0` hits on FX3 & ZV-E1 (`0` in all 3 `cpapp-b.bin` files); S3 `0x8482a60` has 1 dead writer (`0x2aaa500`), **0 readers**, **0 `sequence_*` IPC**, and **0 `BKID_APP_*` entries**. |
| **Waveform & Vectorscope (`VIDEO_SIGNAL_MONITOR_*`)** | **E (Stubbed IPC)** | `0` hits on FX3; `sequence_sys_ods_set_video_signal_monitor::run()` resolves to **`str wzr, [x1]; ret`** (`0x35220cc` S3, `0x33cca94` ZV-E1); `cpapp-b.bin` string sits only in a debug lookup table. |
| **AI Subject Recognition & Auto Framing (S3/FX3)** | **D (Hardware)** | `eye_face_af_gen_type = 0:GEN_TYPE_2` on S3/FX3 vs `1:GEN_TYPE_4` (dedicated AI processing unit) on ZV-E1; `0` callers on S3/FX3 FM rows. |
| **Internal e-ND (S3 BIG6) & Mechanical Shutter (ZV-E1)** | **D (Hardware)** | S3 lacks internal electronic ND hardware; ZV-E1 `mecha_shutter = 1` (no physical shutter, `0` flash-sync callers). |
| **ZV-E1 BIG6 Home Screen / ZV-E1 Shutter Angle / ZV-E1 `1.5x`/`1.8x` De-Squeeze** | **E (Stripped)** | `update_big6_item_iso_ei`, `GUIDE_BIG6_*`, `shutter_angle_*_seq`, and `1.5x`/`1.8x` ratios are compiled out of `zve1` `appFw.so` (and `1.5x`/`1.8x` absent from S3 `appFw.so`). |
| **4.2K `4224x2816` Open Gate & Pixel Shift (`PX_SHIFT_MULTI_SHOOT`) / FX30 8K** | **D / E** | `4224x2816` exceeds `0x2d9` (`14.87 MB`) and fails `Opt-vprf-si` (`0xfeffffff` mask); `PX_SHIFT` has `0` IPC/`cpapp` code; FX30 pixel shift boot-looped and lacks 8K photosites. |
| **Paid DRM / License Features (`CUSTOM_GRID`, `C2PA`, `DIGITAL_SIGNATURE`, Paid `DCI4K_24P`/`4K120P`)** | **Policy Excluded (`0`)** | Hard safety & legal exclusion; zero bypasses generated or permitted. |

---

## 6. Commercialization, Clean-Room / GPLv3, & Non-DRM Legal Guardrails

1. **Repository License Hygiene (Critical for Any Commercial Product):**
   - **GPLv3 Copyleft (`a7iv-open-gate-test`, `a7siii-open-gate-test`, `fx3-open-gate-test`, `zve1-open-gate-test`):** All four Open-Gate field kits are licensed under **GNU General Public License v3 (GPLv3)**. Any commercial tool or service that incorporates or links GPLv3 code from those kits (`libJit` loaders, USB service-mode scripts, or Android APK code) **must** distribute complete corresponding source code under GPLv3. To build a proprietary commercial application, teams must perform a **strict clean-room re-implementation** of the USB host loader and volatile memory engine using zero GPLv3 source files.
   - **CC BY-NC-SA 4.0 NonCommercial (`fx30_fw`):** `fx30_fw/LICENSE` is **Attribution-NonCommercial-ShareAlike 4.0 International (`CC BY-NC-SA 4.0`)**. While local offline research unpackers (`unpack_firmware.sh`) use `fx30_fw` scripts for offline internal research, **zero `fx30_fw` code or assets may be bundled, invoked, or shipped in any clean-room or commercial workflow** (clean-room pipelines use MIT-licensed [DavidBuchanan314/fwtool.py](https://github.com/DavidBuchanan314/fwtool.py) or operate strictly on live camera RAM reads without offline unpackers).
   - **MIT Licensed Reference Repos (`fwtool.py`, `Sony-PMCA-RE`, `sony-a7iv-feature-research`):** Permissive MIT license; retain copyright and permission notices if referenced or reused.
2. **Sony Binary Copyright & Clean-Room Delivery Boundary:**
   - Never redistribute Sony `BODYDATA.DAT` images, extracted firmware binaries (`appFw.so`, `libmpr.so`, `cpapp-b.bin`, `av-cam.bin`, `DmmCfg.bin`), or binary patches containing copyrighted Sony machine-code blocks (`3000B` sensor records) in commercial distributions. Ship only clean-room offset/delta descriptors and client-side read-only verification (`SHA-256` + `16B` non-overlapping stock guards) against the user's own camera.
3. **Non-DRM / Anti-Circumvention & Warranty Safety:**
   - **Zero DRM Circumvention (DMCA §1201 Compliance):** Strictly exclude paid Sony cryptographic/feature licenses (`CUSTOM_GRID`, `C2PA`, `DIGITAL_SIGNATURE`, and paid regional `LICENSE_TYPE_DCI4K_24P` / `LICENSE_TYPE_4K120P`).
   - **100% Volatile RAM & Pre-Flight Gate:** Commercial launchers must never write to `nflasha*` eMMC, `boot0`/`boot1`, or `BK4`/`BACKUP.BIN`, must enforce `persistent_writes == false`, must verify all non-overlapping stock guards read-only before every RAM write, and must provide explicit user disclosures covering cold-boot reversion, thermal limits (`300M`/All-Intra), and SD/CFexpress media requirements.

---

## 7. Master Offline Verification Sign-Off

Executed via offline design verifier `verify_swarm_designs.py`:
- **14 emitted `docs/designs/*.json` files:** `491` patches, `9` optional sites, `370` 16B aligned stock guards — `0` overlaps, `100%` `MANIFEST.json` SHA-256 match, `PT_LOAD[0]` / `cpapp` (`0x108000`) / `av-cam` bounds verified, Capstone AArch64 & Thumb-2 disassemblies verified, `"persistent_writes": false`, zero paid DRM tokens.
- **All sub-verifiers (`exit 0`):** `verify_all_offsets.py` (`15` repo design JSONs, `678` static checks), `verify_og_codecs.py`, `verify_og_60p_hdmi.py`, `verify_shutter_desq.py` (`21` passed), `verify_cineei_s3.py` (`153` passed), `verify_dci4k_zv.py` (`0` failed), `verify_falsecolor_scout.py` (`281` passed), plus all 3 `CT6_memory_read_check` `--selftest` harnesses (`s3_run.py`, `fx3_run.py`, `zv_run.py`).
- **All 8 cloned reference repos:** clean `git status --short`.
