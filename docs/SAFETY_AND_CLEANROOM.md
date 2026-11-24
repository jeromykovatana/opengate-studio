# Safety, Volatile RAM Architecture & Clean-Room Policy

## 1. Hard Safety Guardrails

1. **Volatile RAM Only (`persistent_writes: false`):**
   Every helper library in `kits/` runs strictly inside `/tmp/jiritsu/` during an active USB service session and modifies **volatile RAM only** (`/proc/self/mem` in `libmpr.so` / `appFw.so` `PT_LOAD[0]`, `/dev/mem` for `av-cam.bin`, or coprocessor RAM for `cpapp-b.bin` / `DmmCfg.bin`).
   - **Zero flash writes:** Nothing in this repository writes to `nflasha*` eMMC partitions, `boot0`/`boot1`, or `BK4` / `BACKUP.BIN` persistent settings containers.
   - **Battery pull restores stock:** Switching off and pulling the battery for >= 10 seconds clears all volatile RAM patches and restores 100% factory firmware state.

2. **5-Gate Safety Protocol (Mandatory Read-Only Preflight):**
   - **Gate 1 (Cold-Boot Stills):** Camera must be cold-booted (battery pulled >= 10s), powered on in **Stills** mode, and not switched to Movie mode before applying.
   - **Gate 2 (Read-Only Preflight):** `check` / `dump` must return `VERDICT READY (stock preflight)` or `VERDICT READY (open gate applied)` before `apply` is permitted.
   - **Gate 3 (Warm Power-Switch Detection):** Toggling the power switch without pulling the battery can leave coprocessor RAM (`cpapp-b.bin`) stock while main-processor RAM (`av-cam.bin` / `libmpr.so`) retains encoder patches (`mixed_powerswitch`). Preflight detects this and returns `VERDICT NOT READY`, blocking `apply` until a battery pull restores stock.
   - **Gate 4 (16-Byte Stock Guards & Cross-Pack Disjointness):** Every apply/putback `.so` verifies 16-byte aligned stock guard windows before writing a single byte, and verifies zero cross-pack overlap between `mp4_3x2`, `hdmi32`, `high_bitrate`, and `xavc_si`.
   - **Gate 5 (Explicit USB Approval):** Both `studio_cli.py` and the macOS app default to `--mock-camera` sandbox simulation and never touch live USB (`libusb` / `Sony-PMCA-RE`) unless `--live-usb` is explicitly invoked with user approval.

3. **Zero Paid DRM Bypasses:**
   Paid Sony license checks (`CUSTOM_GRID`, `C2PA`, `DIGITAL_SIGNATURE`, paid `DCI4K_24P` / `4K120P`) are strictly excluded.

## 2. Clean-Room & Licensing Policy

- **License:** All source code, build scripts, CLI tools, SwiftUI app code, and `.so` helpers in this repository are licensed under **GPL-3.0-or-later** (`LICENSE`).
- **No Sony Proprietary Binaries:** Zero decrypted firmware partitions, `.DAT` updaters, `.bin` firmware images, Sony shared objects (`appFw.so`, `libmpr.so`, `libsencore.so`, `libJiritsu.so`), or firmware decryption keys are stored in or distributed with this repository.
- **No Non-Commercial Unpacker Code:** Zero `CC BY-NC-SA` code or unpacker scripts are included.
- **Pinned Reproducible Toolchain:** All `kits/*/*.so` helpers are compiled with `ziglang 0.13.0` (`clang version 18.1.6`) against freestanding headers (`src/common/readcheck.c`), pinned by SHA-256 in each `kits/<body_id>/manifest.json`, and verified continuously by `scripts/verify_clean_room.py`.
