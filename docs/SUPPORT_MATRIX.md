# OpenGate Studio — Public Evidence & Support Matrix

> Generated automatically from [`docs/support_matrix.json`](support_matrix.json) by [`scripts/generate_support_matrix.py`](../scripts/generate_support_matrix.py). Current maturity: **`v0.2.0-alpha (Hardening Release)`**.

## Evidence Legend

| Token | Meaning |
|---|---|
| ✅ Yes | Verified with published artifact or offline check |
| 🟡 Partial | Partial/upstream hardware report or architectural evidence; full Studio conformance bundle pending |
| ⬜ Pending | Not yet verified with untouched camera originals |
| ⛔ Blocked | Blocked by hardware readout timing or policy |
| — | Not applicable in OpenGate Studio |

## Recommended vs. Experimental Profiles

| Profile | Tier | Packs | Frame Rates | Guidance |
|---|---|---|---|---|
| **Safe Daily 3:2 (Recommended)** | `recommended` | `core_open_gate`, `mp4_3x2`, `screen_3x2` | `23.98p (plus 25p PAL on FX3 7.02)` | Smallest volatile RAM footprint; 23.98p open-gate core is hardware-reported across all three bodies. |
| **Experimental Packs (hdmi32 / high_bitrate / xavc_si / 25p-29.97p / fx3_playback)** | `experimental` | `hdmi32`, `high_bitrate`, `xavc_si`, `fx3_playback` | `23.98p / 25p / 29.97p` | Offline byte-verified and Unicorn AArch64 emulator-verified; treat as experimental until untouched original clips and sustained soak reports are published. |

## Granular Body × Firmware × FPS × Codec × Pack Matrix

| Body | FW | FPS | Codec | Pack | Tier | Bytes | Emu | HW Rec | MP4/XML | Gyroflow | Catalyst | NLE | Playback | Soak | Field Ready | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `zve1_202` | `2.02` | `23.98p` | XAVC HS / S 4K | `core_open_gate + screen_3x2` | `recommended` | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | 23.98p + SteadyShot Active/Dynamic Active hardware-confirmed; untouched conformance bundle pending. |
| `zve1_202` | `2.02` | `23.98p` | XAVC HS / S 4K | `mp4_3x2` | `recommended` | ✅ | ✅ | 🟡 | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | rtmd track independence verified in Ghidra; synthetic clip checks pass; end-to-end Gyroflow/Catalyst/NLE proof on untouched originals pending. |
| `zve1_202` | `2.02` | `25p / 29.97p` | XAVC HS / S 4K | `core_open_gate + mp4_3x2` | `experimental` | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | Dual NTSC/PAL MULTI_REC and rate-code-2 tables Unicorn-verified; awaiting hardware test. |
| `zve1_202` | `2.02` | `23.98p / 25p / 29.97p` | XAVC HS / S 4K | `hdmi32` | `experimental` | ✅ | ✅ | ⬜ | ⬜ | — | — | — | — | ⬜ | ⬜ | 16 cpapp-b.bin words verified offline; awaiting external monitor hardware check. |
| `zve1_202` | `2.02` | `23.98p / 25p` | XAVC HS / S 4K | `high_bitrate` | `experimental` | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | 200M/300M Long-GOP profile overlay Unicorn-verified; awaiting sustained card/thermal soak. |
| `zve1_202` | `2.02` | `23.98p / 25p / 29.97p` | XAVC S-I 4K | `xavc_si` | `experimental` | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | Orthogonal XAVC S-I delta + dual-core row split Unicorn-verified; awaiting hardware test. |
| `a7s3_501` | `5.01` | `23.98p` | XAVC HS / S 4K | `core_open_gate + screen_3x2` | `recommended` | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | 23.98p + 4:3 LCD ratio/C3 cycle hardware-confirmed; untouched conformance bundle pending. |
| `a7s3_501` | `5.01` | `23.98p` | XAVC HS / S 4K | `mp4_3x2` | `recommended` | ✅ | ✅ | 🟡 | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | rtmd track independence verified in Ghidra; synthetic clip checks pass; end-to-end Gyroflow/Catalyst/NLE proof on untouched originals pending. |
| `a7s3_501` | `5.01` | `25p / 29.97p` | XAVC HS / S 4K | `core_open_gate + mp4_3x2` | `experimental` | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | Dual NTSC/PAL MULTI_REC and rate-code-2 tables Unicorn-verified; awaiting hardware test. |
| `a7s3_501` | `5.01` | `23.98p / 25p / 29.97p` | XAVC HS / S 4K | `hdmi32` | `experimental` | ✅ | ✅ | ⬜ | ⬜ | — | — | — | — | ⬜ | ⬜ | 28 cpapp-b.bin words verified offline; awaiting external monitor hardware check. |
| `a7s3_501` | `5.01` | `23.98p / 25p` | XAVC HS / S 4K | `high_bitrate` | `experimental` | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | 200M/300M Long-GOP profile overlay Unicorn-verified; awaiting sustained card/thermal soak. |
| `a7s3_501` | `5.01` | `23.98p / 25p / 29.97p` | XAVC S-I 4K | `xavc_si` | `experimental` | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | Orthogonal XAVC S-I delta + dual-core row split Unicorn-verified; awaiting hardware test. |
| `fx3_702` | `7.02` | `23.98p / 25p (PAL)` | XAVC HS / S 4K | `core_open_gate + screen_3x2` | `recommended` | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | 23.98p, PAL 25p (0x820), and 4:3 LCD/De-Squeeze hardware-confirmed; in-camera playback freezes without fx3_playback. |
| `fx3_702` | `7.02` | `23.98p / 25p (PAL)` | XAVC HS / S 4K | `mp4_3x2` | `recommended` | ✅ | ✅ | 🟡 | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | rtmd track independence verified in Ghidra; synthetic clip checks pass; end-to-end Gyroflow/Catalyst/NLE proof on untouched originals pending. |
| `fx3_702` | `7.02` | `29.97p` | XAVC HS / S 4K | `core_open_gate + mp4_3x2` | `experimental` | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | Rate-code-2 29.97p tables Unicorn-verified; awaiting hardware test. |
| `fx3_702` | `7.02` | `23.98p / 25p / 29.97p` | XAVC HS / S 4K | `hdmi32` | `experimental` | ✅ | ✅ | ⬜ | ⬜ | — | — | — | — | ⬜ | ⬜ | 18 cpapp-b.bin words verified offline; recommended way to run anamorphic de-squeeze while keeping Sony AF active. |
| `fx3_702` | `7.02` | `23.98p / 25p` | XAVC HS / S 4K | `high_bitrate` | `experimental` | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | 200M/300M Long-GOP profile overlay Unicorn-verified; awaiting sustained card/thermal soak. |
| `fx3_702` | `7.02` | `23.98p / 25p / 29.97p` | XAVC S-I 4K | `xavc_si` | `experimental` | ✅ | ✅ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | ⬜ | Orthogonal XAVC S-I delta + dual-core row split Unicorn-verified; awaiting hardware test. |
| `fx3_702` | `7.02` | `23.98p / 25p / 29.97p` | Playback | `fx3_playback` | `experimental` | ✅ | ✅ | ⬜ | — | — | — | — | ⬜ | ⬜ | ⬜ | Disabled by default (P29/P30 avdec8k_fx3_v1). Untested on hardware. |
| `zve1_202 / a7s3_501 / fx3_702` | `2.02 / 5.01 / 7.02` | `50p / 60p / 120p` | Any | `All open-gate packs` | `blocked` | ⛔ | ⛔ | ⛔ | ⛔ | ⛔ | ⛔ | ⛔ | ⛔ | ⛔ | ⛔ | Blocked by IMX510 sensor pixel-clock/readout ceiling; switches crash or distort. |
| `a7iv_602` | `6.02` | `23.98p / 25p / 29.97p` | Clip Inspector Only | `Upstream a7iv-open-gate-test` | `external` | — | — | — | 🟡 | — | — | — | — | — | — | Studio inspects a7 IV 3840x2560 and 5760x3840 clips; patching remains in upstream a7iv-open-gate-test. |

## Public Conformance Corpus (Call for Untouched Camera Originals)

Automated media checks currently validate synthetic MP4/XML/`rtmd` fixtures. To promote cells from `⬜ Pending` / `🟡 Partial` to `✅ Yes`, please submit untouched camera original bundles via [Field Test Report](https://github.com/jeromykovatana/opengate-studio/issues/new?template=field-test-report.yml) generated with `cli/studio_cli.py build-report`:
- Locked tripod 16:9 stock vs. 3:2 open-gate `Cxxxx.MP4` + `CxxxxM01.XML`
- Handheld `rtmd` gyro pan/roll clip + Gyroflow / Catalyst Browse stabilization screenshots
- Sustained thermal/card soak clip (`>= 30 min`) + in-camera playback check
