# Releasing OpenGate Studio

This guide documents how to verify, sign, package, and publish clean-room macOS `arm64` alpha releases of **OpenGate Studio** (`ZV-E1 2.02`, `a7S III 5.01`, `FX3 7.02`).

> [!IMPORTANT]
> Releases are strictly **clean-room** and **volatile-RAM-only**: zero Sony firmware binaries, zero `.DAT`/`.bin`/`.img`/`.tar`/`.elf` files, and zero persistent camera flash writes may ever be packaged or published.

---

## 1. Alpha Release Criteria

Before tagging or publishing a release, every check below must pass with zero skipped assertions:

1. **Clean-Room & Policy Gate**
   ```bash
   python3 scripts/verify_clean_room.py
   ```
   Confirms `0` clean-room violations across `3` kit manifests, `62` `.so` helpers (`clang version 18.1.6`, zero unexpected ELF imports/exports), `17` MIT-pinned `sony-pmca-re` files, and all source files.

2. **Support Matrix & SHA-256 Pin Gate**
   ```bash
   python3 scripts/generate_support_matrix.py --check
   python3 cli/studio_cli.py verify-pins --json
   ```
   Ensures `docs/SUPPORT_MATRIX.md` and `README.md` match `docs/support_matrix.json`, and all `65` pinned files (`62` `.so` helpers + `3` `device_info` XMLs) match `kits/*/manifest.json`.

3. **Reproducible Helper Build Gate**
   ```bash
   python3 scripts/verify_reproducible_build.py --json
   ```
   Rebuilds all `62` `.so` helpers using the hash-pinned `ziglang 0.13.0` toolchain (`requirements-build.txt`) and confirms exact SHA-256 parity with `kits/*/*.so`.

4. **Clip Inspector, Python & Swift Test Suites**
   ```bash
   python3 cli/bionz_clip_check.py --selftest
   .venv/bin/python -B -m unittest discover -s tests -v
   bash macos/OpenGateStudio/run_tests.sh
   ```

5. **Evidence Honesty**
   Every document, release note, and UI label must accurately distinguish hardware-measured results from Unicorn AArch64 emulation (`Emu`) or sensor-geometry estimates (`estimated_from_imx510_line_ratio`).

---

## 2. Building & Signing `OpenGate Studio.app`

[`macos/OpenGateStudio/bundle_app.sh`](../macos/OpenGateStudio/bundle_app.sh) builds the release `arm64` SwiftUI binary, writes `Info.plist` and `StudioMetadata.json`, validates the Mach-O architecture, and signs the bundle.

### Version Injection (`APP_VERSION`)

Set `APP_VERSION` to populate `CFBundleShortVersionString` (any leading `v`/`V` is stripped automatically, e.g., `v0.1.3-alpha` → `0.1.3-alpha`):

```bash
APP_VERSION=v0.1.3-alpha bash macos/OpenGateStudio/bundle_app.sh
```

If `APP_VERSION` is omitted, `CFBundleShortVersionString` defaults to `1.0.0`. `CFBundleVersion` defaults to `1` (override with `APP_BUILD_VERSION`).

### Option A: Ad-Hoc Signing (Default / Community Alpha Builds)

When `APPLE_DEVELOPER_ID_APP` is unset, `bundle_app.sh` falls back to ad-hoc signing:

```bash
codesign --force --deep --sign - "macos/OpenGateStudio/dist/OpenGate Studio.app"
codesign --verify --deep --strict "macos/OpenGateStudio/dist/OpenGate Studio.app"
```

End users launching an ad-hoc build downloaded from GitHub Releases may need to clear the macOS quarantine attribute once (or right-click → **Open**):

```bash
xattr -dr com.apple.quarantine "OpenGate Studio.app"
```

### Option B: Developer ID Signing + Hardened Runtime + Notarization

For Gatekeeper-trusted distribution without quarantine warnings, configure a Developer ID Application certificate in your keychain and an `xcrun notarytool` keychain profile:

```bash
# One-time keychain profile setup (if not already stored):
xcrun notarytool store-credentials "opengate-notary" \
  --apple-id "you@example.com" \
  --team-id "YOURTEAMID" \
  --password "<app-specific-password>"

# Build, Developer ID sign (hardened runtime + timestamp), notarize, and staple:
APP_VERSION=v0.1.3-alpha \
APPLE_DEVELOPER_ID_APP="Developer ID Application: Your Name (YOURTEAMID)" \
APPLE_NOTARY_PROFILE="opengate-notary" \
bash macos/OpenGateStudio/bundle_app.sh
```

What `bundle_app.sh` performs when those variables are set:
1. Signs with `codesign --force --deep --options runtime --timestamp --sign "$APPLE_DEVELOPER_ID_APP"`.
2. If `APPLE_NOTARY_PROFILE` is set, zips the `.app` with `ditto -c -k --keepParent`, submits via `xcrun notarytool submit --keychain-profile "$APPLE_NOTARY_PROFILE" --wait`, staples the ticket via `xcrun stapler staple`, and validates via `xcrun stapler validate` and `codesign --verify --deep --strict`.
3. Refuses to run notarization if `APPLE_DEVELOPER_ID_APP` is unset (ad-hoc bundles cannot be notarized).

---

## 3. Packaging a Clean-Room Release (`scripts/package_release.sh`)

### Dry-Run Verification (No `dist/` Output)

Always test staging and exclusions first with `--dry-run`:

```bash
bash scripts/package_release.sh --version v0.1.3-alpha --dry-run
```

`--dry-run` runs `verify_clean_room.py`, `generate_support_matrix.py --check`, and `studio_cli.py verify-pins --json`, skips `bundle_app.sh`, stages the clean runtime into a temporary directory, asserts zero excluded files leaked, verifies `3` `kits/*/manifest.json` + `62` `.so` helpers, previews `SHA256SUMS.txt` (`66` entries), and removes the temporary directory so `git status` remains clean.

### Full Release Build

```bash
bash scripts/package_release.sh --version v0.1.3-alpha
```

*(Pass `APPLE_DEVELOPER_ID_APP` and `APPLE_NOTARY_PROFILE` in the environment for a notarized archive.)*

This produces:
- `dist/Sony-OpenGate-Studio-v0.1.3-alpha-macos-arm64.zip`
- `dist/SHA256SUMS.txt`

> [!WARNING]
> Never commit `dist/` or `macos/OpenGateStudio/dist/` to git. `dist/` is strictly for local release upload artifacts.

### Staged Archive Contents & Exclusions

The release `.zip` unpacks to `Sony-OpenGate-Studio-<version>-macos-arm64/` containing:
- `OpenGate Studio.app`
- `cli/`, `kits/`, `presets/`, `transport/`, `scripts/`
- `macos/run_live_inapp.sh`, `macos/run_live_terminal.sh`
- `requirements.txt`, `requirements-build.txt`, `setup_and_open_mac.command`, `README.md`, `docs/`, `LICENSE`

Explicitly excluded from staging:
- `.git/`, `.venv/`, `.DS_Store`, `__pycache__/`, `*.pyc`, `*.pyo`, `dist/`, `.build/`, `sessions/`, `camera_private/`, `*.log`

---

## 4. Checksum Verification (`SHA256SUMS.txt`)

`dist/SHA256SUMS.txt` contains **66 SHA-256 entries**:
1. `Sony-OpenGate-Studio-<version>-macos-arm64.zip` (1 archive)
2. `kits/<body_id>/manifest.json` (3 manifests: `a7s3_501`, `fx3_702`, `zve1_202`)
3. `kits/<body_id>/*.so` (62 helper binaries)

### Verifying the Downloaded Archive

In the directory containing both `Sony-OpenGate-Studio-<version>-macos-arm64.zip` and `SHA256SUMS.txt`:

```bash
grep "Sony-OpenGate-Studio-" SHA256SUMS.txt | shasum -a 256 -c -
```

### Verifying Extracted Kit Manifests & `.so` Helpers

Inside the extracted `Sony-OpenGate-Studio-<version>-macos-arm64/` directory:

```bash
grep "^[0-9a-f]*  kits/" ../SHA256SUMS.txt | shasum -a 256 -c -
python3 cli/studio_cli.py verify-pins --json
```

---

## 5. Publishing an Alpha Pre-Release on GitHub

1. Confirm all changes are committed, pushed to `main`, and all GitHub Actions CI jobs (`Clean-Room & Python Suite`, `Reproducible Helper SHA-256 Verification`, `macOS SwiftUI & Core Tests`) are green:
   ```bash
   gh run list --branch main --limit 5
   gh run watch <run-id> --exit-status
   ```
2. Build the release artifacts locally (`bash scripts/package_release.sh --version v0.1.3-alpha`) and verify `dist/SHA256SUMS.txt`.
3. Create and publish the GitHub pre-release (never mark alpha builds as latest production):
   ```bash
   gh release create v0.1.3-alpha \
     dist/Sony-OpenGate-Studio-v0.1.3-alpha-macos-arm64.zip \
     dist/SHA256SUMS.txt \
     --prerelease \
     --title "OpenGate Studio v0.1.3-alpha" \
     --notes-file <release-notes.md>
   ```
4. Remove local `dist/` (or keep outside the git worktree) so no untracked artifacts remain in the repository.
