# Contributing to Sony OpenGate Studio

Thank you for helping improve **Sony OpenGate Studio**!

## Hard Clean-Room & Safety Rules

All pull requests are automatically checked by `scripts/verify_clean_room.py` in CI. Contributions **must** adhere to these non-negotiable rules:

1. **Volatile RAM Only (`persistent_writes: false`):** Never submit patches that write to `nflasha*` eMMC partitions, `boot0`/`boot1`, or `BK4` / `BACKUP.BIN` persistent settings.
2. **Zero Sony Proprietary Binaries or Keys:** Never commit `.DAT` updaters, `.bin` firmware images, `.elf` dumps, decrypted Sony binaries (`appFw.so`, `libmpr.so`, `libsencore.so`, `libJiritsu.so`, `cpapp-b.bin`, `av-cam.bin`, `DmmCfg.bin`), or decryption keys.
3. **License Hygiene (`GPL-3.0-or-later`):** Never include `CC BY-NC-SA` code or unpacker scripts. Vendored `sony-pmca-re` files under `transport/third_party/sony-pmca-re/` are MIT-licensed and SHA-256 pinned in `PINNED.json`.
4. **Zero Paid DRM Bypasses:** Paid Sony license checks (`CUSTOM_GRID`, `C2PA`, `DIGITAL_SIGNATURE`, paid regional `DCI4K_24P`/`4K120P`) are strictly excluded.
5. **Reproducible Helper Binaries:** Any `.so` helpers in `kits/` must be compiled cleanly with `ziglang 0.13.0` (`clang version 18.1.6`), export only allowed symbols, and have updated SHA-256 pins in `kits/<body_id>/manifest.json`.

## Local Verification Before Opening a PR

Run the full offline verification suite from the repo root:

```bash
python3 scripts/verify_clean_room.py
python3 cli/studio_cli.py verify-pins --json
python3 cli/bionz_clip_check.py --selftest
python3 -B -m unittest discover -s tests -v
bash macos/OpenGateStudio/run_tests.sh   # on macOS
```

## Ways to Contribute

- **Hardware Field Testing:** Test on `ZV-E1 2.02`, `a7S III 5.01`, or `FX3 7.02` following [docs/OFFICE_CAMERA_TEST_GUIDE.md](docs/OFFICE_CAMERA_TEST_GUIDE.md) and submit a **Field Test Report** issue.
- **Clip & Gyro Verification:** Run `cli/bionz_clip_check.py` on real camera clips and verify framing/stabilization in DaVinci Resolve, Premiere Pro, Gyroflow, and Sony Catalyst Browse.
- **Documentation & UX:** Improve macOS SwiftUI UX, setup guides, or troubleshooting notes.
