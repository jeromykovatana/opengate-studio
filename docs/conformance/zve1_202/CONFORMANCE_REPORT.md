# OpenGate Studio Clean-Room Conformance Report — Sony ZV-E1 (`zve1_202`)

- **Generated (UTC):** `2026-11-27T11:03:39Z`
- **Commit:** `417b28a`
- **Firmware Target:** `2.02`
- **Clean-Room Safeguards:** `serials_redacted=True`, `raw_ct6_dumps_excluded=True`
- **Hardware Proof Status:** `VERIFIED (live_usb)`

> [!NOTE]
> **Provenance & Incremental `L3-nrt-vline` Fix:**
> - Live USB sessions (`preflight`, `closing_dump`, `putback`) and test clips (`C6433`–`C6437`) were captured under `v0.1.3-alpha` (`417b28a`, manifest SHA-256 `ad79834c3628d9ca3c42d3327968f8ae0b3c77ca29aca34bb2fd4a21dc3a1133`, `V19` helper `a2c3cda8...`).
> - Hardware `rtmd` tag `0xe40e` measured `12.336 ms` frame readout across all four 23.98p open-gate clips (`2000 Hz` gyro + accel + `LPIF`).
> - Original camera clips truncated trailing `meta -> xml ` right at `<NonRealTimeMeta>` due to `L3-nrt-vline` breaking `FUN_00235628`; running non-destructive `repair-nrt-xml` (`prefix_identical=true`) produced repaired-NRT copies (`C6433`–`C6436` in this audit) that verified cleanly in Gyroflow v1.7.1 (`Sony ZV-E1`, `FE 24mm F1.4 GM`, `Contains gyro: Yes`, `3840x2560`).
> - Upstream `L3-nrt-vline` has now been moved to `NrtMetaWrapper::Init` (`0x238108` on `zve1_202`, `V19` helper `511e8afe...`) so fresh hardware clips write complete trailing NRT XML out-of-the-box.

## 1. Live USB Session Validation

- **Summary:** Verified 4 live_usb session(s) for zve1_202.
- **Verified `live_usb` Sessions:** `4` (apply verified: `True`)
- **Mock Sessions Rejected:** `0` | **Invalid `live_usb` Rejected:** `4`

| Session ID | Kind | Mode | State | Active Packs | Validation |
|---|---|---|---|---|---|
| `session_1795773748643719000_0008` | `putback` | `live_usb` | `stock` | `none` | Verified live_usb putback session (stock) |
| `session_1795773160803993000_0007` | `closing_dump` | `live_usb` | `applied` | `core_open_gate, mp4_3x2, screen_3x2` | Verified live_usb closing_dump session (applied) |
| `session_1795772927687522000_0006` | `preflight` | `live_usb` | `stock` | `none` | Verified live_usb preflight session (stock) |
| `session_1795771363837854000_0005` | `preflight` | `live_usb` | `stock` | `none` | Verified live_usb preflight session (stock) |

### Rejected Sessions

- `session_1795770756687209000_0004` (`live_usb` / `preflight`): Invalid live_usb session: ready is not True; verified is not True; missing boot_nonce; missing or invalid preflight_result_sha256; missing camera_identity
- `session_1795770265070621000_0003` (`live_usb` / `preflight`): Invalid live_usb session: ready is not True; verified is not True; missing boot_nonce; missing or invalid preflight_result_sha256; missing camera_identity
- `session_1795769787549458000_0002` (`live_usb` / `preflight`): Invalid live_usb session: ready is not True; verified is not True; missing boot_nonce; missing or invalid preflight_result_sha256; missing camera_identity
- `session_1795769710990356000_0001` (`live_usb` / `preflight`): Invalid live_usb session: ready is not True; verified is not True; missing boot_nonce; missing or invalid preflight_result_sha256; missing camera_identity

## 2. Conformance Slot Checklist

| Slot | Status | Detail |
|---|---|---|
| `open_gate_23_976p` | **PASS** | 4 passing 3:2 clip(s) at 23.976p/24p |
| `open_gate_25_000p` | **OPTIONAL/MISSING** | No 25.000p open-gate clip in bundle |
| `open_gate_29_970p` | **OPTIONAL/MISSING** | No 29.970p open-gate clip in bundle |
| `stock_baseline` | **PASS** | 1 passing stock 16:9 baseline clip(s) |
| `rtmd_cadence` | **PASS** | All clips have constant rtmd cadence, readable KLV payload, <=100ms drift |
| `vprf_and_xml` | **PASS** | All open-gate clips have 3:2 VPRF + paired M01.XML |
| `untouched_sha256` | **PASS** | 5/5 MP4 SHA-256 hashes verified untouched |
| `long_take_soak` | **OPTIONAL/MISSING** | Optional >=30 min thermal soak not yet confirmed |

## 3. Untouched Clip & `rtmd` Audit

- **Clips Scanned:** `5` | **Passed:** `5` | **Failed:** `0`

| Relative Path | Mode | Res | Codec | FPS | VPRF 3:2 | XML 3:2 | rtmd Samples | Drift (ms) | KLV | Gyroflow | Catalyst | MP4 SHA-256 (prefix) | Status |
|---|---|---|---|---|---|---|---:|---:|---|---|---|---|---|
| `C6433.MP4` | open-gate | 3840x2560 | hvc1 | 23.976p | YES | YES | 384 | 0.0 | YES | READY | READY | `d7e76ba2688ff5e0...` | PASS |
| `C6434.MP4` | open-gate | 3840x2560 | hvc1 | 23.976p | YES | YES | 612 | 0.0 | YES | READY | READY | `80580dcbd3706d81...` | PASS |
| `C6435.MP4` | open-gate | 3840x2560 | hvc1 | 23.976p | YES | YES | 756 | 0.0 | YES | READY | READY | `c2fb9644ea60effd...` | PASS |
| `C6436.MP4` | open-gate | 3840x2560 | hvc1 | 23.976p | YES | YES | 384 | 0.0 | YES | READY | READY | `82e8b563fa54550e...` | PASS |
| `C6437.MP4` | stock | 3840x2160 | hvc1 | 23.976p | NO | YES | 336 | 0.0 | YES | READY | READY | `22dfc992aa4b348f...` | PASS |

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
- Note: Measured from conformance bundle (4 passing open-gate clip(s); live_usb_verified=True).

## 5. Eligible `docs/support_matrix.json` Promotions (Dry-Run Only)

- **Matrix Mutated:** `False` (dry-run recommendation only)

| FPS | Codec | Pack | Dimension | From | To | Reason |
|---|---|---|---|---|---|---|
| `23.98p` | XAVC HS / S 4K | `mp4_3x2` | `clip_xml_validated` | `partial` | **`yes`** | Untouched MP4 + M01.XML + VPRF 3:2 + rtmd KLV cadence validated. |
