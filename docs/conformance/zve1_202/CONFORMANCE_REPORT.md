# OpenGate Studio Clean-Room Conformance Report — Sony ZV-E1 (`zve1_202`)

- **Generated (UTC):** `2026-11-27T16:44:28Z`
- **Commit:** `5929cb0`
- **Firmware Target:** `2.02`
- **Clean-Room Safeguards:** `serials_redacted=True`, `raw_ct6_dumps_excluded=True`
- **Hardware Proof Status:** `VERIFIED (live_usb)`

> [!NOTE]
> **Provenance & `V19` Out-of-the-Box NRT XML Verification (`v0.2.0-alpha`):**
> - Live USB preflight (`session_1795796997543823000_0009`) and closing dump (`session_1795797306677655000_0010`) verified under `v0.2.0-alpha` (`manifest_sha256` `9b9114a03209b626dc0035576347d93979a8cf80ba2a59c1e5d3ee993dabba99`, `V19` helper `511e8afe...`, `NrtMetaWrapper::Init` `0x238108`/`0x238114`).
> - Untouched camera original `C6438.MP4` + `C6438M01.XML` (`3840x2560`, `23.976p`, `528` KLV `rtmd` samples, `0.0 ms` drift, Sony `0xe40e` readout `12.336 ms`) writes complete non-truncated embedded (`2172 B`) and sidecar (`2173 B`) NRT XML (`<Device>`, `<VideoLayout>`, `<VideoFrame>`) out-of-the-box **without** `repair-nrt-xml`, paired with untouched stock `16:9` baseline `C6437.MP4` and earlier `C6433`–`C6436` Gyroflow v1.7.1 verification.

## 1. Live USB Session Validation

- **Summary:** Verified 6 live_usb session(s) for zve1_202.
- **Verified `live_usb` Sessions:** `6` (apply verified: `True`)
- **Mock Sessions Rejected:** `0` | **Invalid `live_usb` Rejected:** `5`

| Session ID | Kind | Mode | State | Active Packs | Validation |
|---|---|---|---|---|---|
| `session_1795797306677655000_0010` | `closing_dump` | `live_usb` | `applied` | `core_open_gate, mp4_3x2, screen_3x2` | Verified live_usb closing_dump session (applied) |
| `session_1795796997543823000_0009` | `preflight` | `live_usb` | `stock` | `none` | Verified live_usb preflight session (stock) |
| `session_1795773748643719000_0008` | `putback` | `live_usb` | `stock` | `none` | Verified live_usb putback session (stock) |
| `session_1795773160803993000_0007` | `closing_dump` | `live_usb` | `applied` | `core_open_gate, mp4_3x2, screen_3x2` | Verified live_usb closing_dump session (applied) |
| `session_1795772927687522000_0006` | `preflight` | `live_usb` | `stock` | `none` | Verified live_usb preflight session (stock) |
| `session_1795771363837854000_0005` | `preflight` | `live_usb` | `stock` | `none` | Verified live_usb preflight session (stock) |

### Rejected Sessions

- `session_1795797840614111000_0011` (`live_usb` / `preflight`): Invalid live_usb session: ready is not True
- `session_1795770756687209000_0004` (`live_usb` / `preflight`): Invalid live_usb session: ready is not True; verified is not True; missing boot_nonce; missing or invalid preflight_result_sha256; missing camera_identity
- `session_1795770265070621000_0003` (`live_usb` / `preflight`): Invalid live_usb session: ready is not True; verified is not True; missing boot_nonce; missing or invalid preflight_result_sha256; missing camera_identity
- `session_1795769787549458000_0002` (`live_usb` / `preflight`): Invalid live_usb session: ready is not True; verified is not True; missing boot_nonce; missing or invalid preflight_result_sha256; missing camera_identity
- `session_1795769710990356000_0001` (`live_usb` / `preflight`): Invalid live_usb session: ready is not True; verified is not True; missing boot_nonce; missing or invalid preflight_result_sha256; missing camera_identity

## 2. Conformance Slot Checklist

| Slot | Status | Detail |
|---|---|---|
| `open_gate_23_976p` | **PASS** | 1 passing 3:2 clip(s) at 23.976p/24p |
| `open_gate_25_000p` | **OPTIONAL/MISSING** | No 25.000p open-gate clip in bundle |
| `open_gate_29_970p` | **OPTIONAL/MISSING** | No 29.970p open-gate clip in bundle |
| `stock_baseline` | **PASS** | 1 passing stock 16:9 baseline clip(s) |
| `rtmd_cadence` | **PASS** | All clips have constant rtmd cadence, readable KLV payload, <=100ms drift |
| `vprf_and_xml` | **PASS** | All open-gate clips have 3:2 VPRF + paired M01.XML |
| `untouched_sha256` | **PASS** | 2/2 MP4 SHA-256 hashes verified untouched |
| `long_take_soak` | **OPTIONAL/MISSING** | Optional >=30 min thermal soak not yet confirmed |

## 3. Untouched Clip & `rtmd` Audit

- **Clips Scanned:** `2` | **Passed:** `2` | **Failed:** `0`

| Relative Path | Mode | Res | Codec | FPS | VPRF 3:2 | XML 3:2 | rtmd Samples | Drift (ms) | KLV | Gyroflow | Catalyst | MP4 SHA-256 (prefix) | Status |
|---|---|---|---|---|---|---|---:|---:|---|---|---|---|---|
| `C6437.MP4` | stock | 3840x2160 | hvc1 | 23.976p | NO | YES | 336 | 0.0 | YES | READY | READY | `22dfc992aa4b348f...` | PASS |
| `C6438.MP4` | open-gate | 3840x2560 | hvc1 | 23.976p | YES | YES | 528 | 0.0 | YES | READY | READY | `8c78be5876a2155f...` | PASS |

## 4. Operator Verification & Readout Calibration

| Check | Value |
|---|---|
| Gyroflow OK | `True` |
| Catalyst OK | `None` |
| NLE Import OK | `None` |
| In-Camera Playback OK | `None` |
| Thermal / Long-Take OK | `None` |
| Measured Readout (ms) | `12.336` |

### Calibration Patch Export (Dry-Run)

- Upgrade `presets/gyroflow/calibration_profiles.json` (`zve1_202`): `10.3 ms` (`estimated_from_imx510_line_ratio`) -> **`12.336 ms`** (`hardware_measured`)
- Note: Measured from conformance bundle (1 passing open-gate clip(s); live_usb_verified=True).

## 5. Eligible `docs/support_matrix.json` Promotions (Dry-Run Only)

- **Matrix Mutated:** `False` (dry-run recommendation only)

| FPS | Codec | Pack | Dimension | From | To | Reason |
|---|---|---|---|---|---|---|
| `23.98p` | XAVC HS / S 4K | `mp4_3x2` | `clip_xml_validated` | `partial` | **`yes`** | Untouched MP4 + M01.XML + VPRF 3:2 + rtmd KLV cadence validated. |
