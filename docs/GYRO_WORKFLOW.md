# Sony BIONZ XR 3:2 Open-Gate Gyro Stabilization Workflow

This guide documents end-to-end gyro stabilization (`rtmd` timed metadata) for OpenGate Studio 3:2 clips (`3840x2560` on `ZV-E1`, `a7S III`, `FX3`; `3840x2560` / `5760x3840` on `a7 IV`) in **Gyroflow** and **Sony Catalyst Browse / Prepare**.

---

## 1. Honest Calibration & Evidence Status

OpenGate Studio distinguishes strictly between **estimated** sensor timing and **hardware-measured** calibration:

| Platform | Resolution | Estimated `frame_readout_time` | Evidence Level | Calculation / Status |
|---|---|---|---|---|
| **ZV-E1 (`zve1_202`)** | `3840x2560` | **`10.3 ms`** | `estimated_from_imx510_line_ratio` | Scaled from stock 16:9 (~8.7 ms across `2392` active rows) to `2832` open-gate rows (`8.7 * 2832 / 2392 = 10.30 ms`). Hardware measurement on untouched card originals pending. |
| **a7S III (`a7s3_501`)** | `3840x2560` | **`10.3 ms`** | `estimated_from_imx510_line_ratio` | Shared `IMX510` 12.1MP readout geometry. Hardware measurement pending. |
| **FX3 (`fx3_702`)** | `3840x2560` | **`10.3 ms`** | `estimated_from_imx510_line_ratio` | Shared `IMX510` 12.1MP readout geometry. Hardware measurement pending. |
| **a7 IV (`a7iv_602`)** | `5760x3840` | **`31.8 ms`** | `estimated_from_imx710_line_ratio` | Scaled from stock 16:9 (~26.8 ms across `3942` active rows) to `4672` open-gate rows (`26.8 * 4672 / 3942 = 31.76 ms`). Hardware measurement pending. |

All bundled starter profiles in `presets/gyroflow/` carry `evidence_level` labels and `num_images: 0` with zeroed distortion coefficients (`[0, 0, 0, 0]`). **Never treat starter templates as hardware-measured lens calibrations** — calibrate your specific lens with a Gyroflow checkerboard chart at `3:2` open gate and measure actual rolling shutter before critical shoots.

---

## 2. IBIS / OIS & SteadyShot Guidance

| Stabilization Workflow | Camera IBIS (`SteadyShot`) | Lens `OSS` | Notes & Warnings |
|---|---|---|---|
| **In-Camera Only (No Post Gyro)** | **Standard** or **Active** | **ON** | ZV-E1 `2.02` Active & Dynamic Active are hardware-confirmed at `23.98p`. Active applies an electronic crop in-camera. |
| **Gyroflow (`rtmd` Post Stabilization)** | **OFF** *(recommended)* | **OFF** | **Active SteadyShot OFF Warning:** Active / Dynamic Active SteadyShot warps frames electronically inside the camera, fighting Gyroflow's `rtmd` solver and producing border jello/corner swimming. Standard IBIS + OIS also introduces unmodeled optical-center shifts unless turned OFF. |
| **Sony Catalyst Browse / Prepare** | **OFF** *(required)* | **OFF** | Catalyst requires SteadyShot **OFF** (and `mp4_3x2` native `3:2` MP4 + `M01.XML` metadata) for full stabilization support. |

> [!WARNING]
> **Active SteadyShot OFF Warning:** If you plan to stabilize in **Gyroflow** or **Sony Catalyst**, turn **SteadyShot = OFF** in the camera menu and switch **OSS = OFF** on any stabilized lens. Never shoot Active or Dynamic Active SteadyShot expecting clean post-stabilization.

---

## 3. Third-Party & Anamorphic Lens Checklist

### Third-Party E-Mount AF Lenses (Sigma, Tamron, Samyang, Viltrox, Sirui)
1. **Verify focal-length reporting:** Confirm the lens reports non-zero focal length in the `M01.XML` / `rtmd` stream.
2. **Disable lens OSS/VC/OS** when using Gyroflow or Catalyst.
3. **Create a 3:2 Gyroflow lens profile** for each focal length (or zoom stop) because stock Gyroflow `16:9` profiles expect `3840x2160` crop geometry.

### Manual, Vintage, or Adapted Cine Lenses (No Electronic Contacts)
1. Camera records **`0 mm` focal length** (`focalLength=0`) and no lens distortion metadata.
2. **Catalyst Browse** typically rejects or disables stabilization when focal length is missing.
3. **Gyroflow** still stabilizes cleanly using body `rtmd` angular velocity **if** you select a calibrated lens profile (or enter focal length + readout time manually).
4. Set camera SteadyShot focal length manually if shooting in-camera IBIS, or turn SteadyShot **OFF** for Gyroflow.

### Anamorphic Lenses (`1.33x` / `1.5x` / `1.6x` / `2.0x`)
1. **Shoot with `mp4_3x2` active** so the full `3840x2560` sensor frame and `rtmd` track remain intact.
2. For monitoring:
   - **FX3 (`fx3_702`):** `screen_3x2` (`lcd32dsq_fx3_v1`) keeps internal De-Squeeze Display calibrated for `3:2`; for active Sony AF while de-squeezing, use `hdmi32` + external monitor de-squeeze with internal De-Squeeze OFF.
   - **ZV-E1 (`zve1_202`) / a7S III (`a7s3_501`):** Use the `C2` (`ZV-E1`) or `C3` (`a7S III`) cycle (`3:2 -> 2:1 -> 2.25:1 -> 2.4:1 -> 3:2`).
3. **In Gyroflow:** Set `input_horizontal_stretch` to match your squeeze factor (or calibrate your anamorphic lens directly on the squeezed `3840x2560` checkerboard footage with matching output aspect settings).
4. Turn **SteadyShot OFF** (anamorphic squeeze + IBIS vertical/horizontal shift mismatch creates corner breathing if stabilized in-camera before de-squeezing).

---

## 4. Never Re-Mux Camera Originals Before Stabilization

- **Do NOT run `ffmpeg -c copy` or transcodes on originals before Gyroflow/Catalyst.** `ffmpeg` drops Sony's `rtmd` timed-metadata stream (`mp4` muxer limitation).
- **Proxy Workflow Rule:** Edit using `3:2` proxies if needed, then **relink back to the untouched original camera `.MP4`** (`relink_to_original_for_gyro: true`) before running Gyroflow or Catalyst stabilization.

---

## 5. Diagnostic CLI & Failure Categories (`studio_gyro.py`)

Run a full gyro readiness audit on any clip:
```bash
python3 cli/studio_gyro.py diagnose /path/to/C0001.MP4 --xml /path/to/C0001M01.XML --body zve1_202
```

| `failure_category` | Meaning | Typical Fix |
|---|---|---|
| `none` | Container, XML (if present), `rtmd` KLV packets, and cadence are healthy | Load original `.MP4` in Gyroflow with matching 3:2 profile |
| `crop_geometry` | `16:9` container/VPRF or `aspectRatio="16:9"` XML on 3:2 footage, or non-square `pasp` | Re-apply `mp4_3x2` pack on camera before shooting |
| `metadata` | Missing `rtmd` track, missing `cdsc` link, zero-size `stsz` samples, unreadable `stco` offsets, or missing SMPTE KLV header | Use untouched card original (do not use `ffmpeg`-remuxed file) |
| `rtmd_cadence` | `rtmd` `stts` cadence varies or duration drifts `> 100 ms` from video track | Inspect clip for dropped frames / truncated write; re-sync in Gyroflow |
| `lens_profile` | Manual/0mm lens metadata or unrecognized body without a matching 3:2 preset | Calibrate/select lens profile manually in Gyroflow (`num_images > 0`) |
| `app_compatibility` | Active SteadyShot detected in XML, invalid AVC level for `3840x2560`, or unsupported frame rate | Turn Active SteadyShot OFF; verify decoder/NLE level acceptance |

### Installing Starter Gyroflow Profiles
```bash
# List starter presets with SHA-256 and evidence level
python3 cli/studio_gyro.py list-presets

# Install to ~/Library/Application Support/Gyroflow/lens_profiles/OpenGateStudio
python3 cli/studio_gyro.py install-presets
```
