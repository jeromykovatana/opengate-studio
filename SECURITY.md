# Security & Hardware Safety Policy

## Volatile RAM Boundary

**Sony OpenGate Studio** is designed strictly for **volatile RAM modification only** (`persistent_writes: false`):

- No patch writes to eMMC flash (`nflasha*`), bootloaders (`boot0`/`boot1`), or persistent settings (`BK4` / `BACKUP.BIN`).
- Every write helper verifies 16-byte aligned stock guard windows before patching and checks for cross-pack byte collisions.
- Every live run enforces a mandatory read-only preflight (`CT6`) checking `DeviceInfo.xml` and memory identity pages before unlocking `apply`.
- Pulling the camera battery for `>= 10` seconds clears all volatile RAM patches and restores 100% stock firmware.

## Reporting a Safety or Security Issue

Please report any of the following immediately:

- Any preflight bypass, mismatched-firmware acceptance, or guard-collision bug.
- Any unexpected write behavior, warm-reset hazard, or UI state mismatch that could allow `apply` on a non-`READY` camera.
- Any clean-room or SHA-256 pin verification bypass.

You can report issues privately via GitHub Security Advisories (if enabled on the repository) or open an issue labeled `bug` without attaching any proprietary Sony files. See [docs/SAFETY_AND_CLEANROOM.md](docs/SAFETY_AND_CLEANROOM.md) for the full 5-gate specification.
