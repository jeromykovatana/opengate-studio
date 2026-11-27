# OpenGate Studio — Gyroflow 3:2 Starter Lens Profiles

These starter profiles provide **3:2 Open Gate container dimensions** and **estimated rolling-shutter readout times** for Sony BIONZ XR cameras so Gyroflow does not fall back to 16:9 profile matching.

## Evidence Level Notice (Read Before Production Use)

| Body ID | Camera Model | Dimension | `frame_readout_time` (ms) | Evidence Level | Basis |
|---|---|---|---|---|---|
| `zve1_202` | `ZV-E1` | `3840x2560` | `10.3` | `estimated_from_imx510_line_ratio` | Scaled from ~8.7 ms stock 16:9 (`2392` active rows) to `2832` open-gate rows (`8.7 * 2832 / 2392`) |
| `a7s3_501` | `ILCE-7SM3` | `3840x2560` | `10.3` | `estimated_from_imx510_line_ratio` | Same `IMX510` 12.1MP sensor readout geometry |
| `fx3_702` | `ILME-FX3` | `3840x2560` | `10.3` | `estimated_from_imx510_line_ratio` | Same `IMX510` 12.1MP sensor readout geometry |
| `a7iv_602` | `ILCE-7M4` | `5760x3840` | `31.8` | `estimated_from_imx710_line_ratio` | Scaled from ~26.8 ms stock 16:9 (`3942` active rows) to `4672` open-gate rows (`26.8 * 4672 / 3942`) |

> **Important:** None of these `frame_readout_time` values are `hardware_measured` on open-gate card originals yet, and all `distortion_coeffs` are `[0, 0, 0, 0]` starter placeholders (`num_images: 0`). Always run a per-lens checkerboard calibration and verify rolling shutter in Gyroflow against your actual lens and footage.

## Installation

Default macOS install destination:
`~/Library/Application Support/Gyroflow/lens_profiles/OpenGateStudio`

Install via Python:
```bash
python3 cli/studio_gyro.py install-presets
```
Or via `studio_cli.py`:
```bash
python3 cli/studio_cli.py install-gyroflow-presets --json
```

See [docs/GYRO_WORKFLOW.md](../../docs/GYRO_WORKFLOW.md) for IBIS/OIS rules, Active SteadyShot warnings, third-party/anamorphic checklists, and proxy relinking rules.
