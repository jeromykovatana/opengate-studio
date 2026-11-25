#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# One-click macOS setup for OpenGate Studio:
#   1. Creates .venv and installs pyusb, pycryptodomex, and libusb-package (no Homebrew libusb needed).
#   2. Verifies kit SHA-256 pins.
#   3. Builds OpenGate Studio.app via macos/OpenGateStudio/bundle_app.sh if swift is available and opens it.
#   4. Prints live CLI & office camera test instructions.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

close_prompt() {
  local rc="$1"
  if [ -t 0 ] && [ -z "${OPENGATE_NO_CLOSE_PROMPT:-}" ]; then
    echo
    read -r -p "Press Return to close. " || true
  fi
  exit "$rc"
}

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
  for cand in /opt/homebrew/opt/python@3.11/bin/python3.11 /opt/homebrew/bin/python3 python3; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
      PYTHON_BIN="$(command -v "$cand")"
      break
    fi
  done
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: Python 3.9+ not found. Install Python 3 or run: xcode-select --install" >&2
  close_prompt 1
fi

echo "[1/4] Setting up Python virtualenv at $REPO_ROOT/.venv using $PYTHON_BIN..."
if [ ! -x "$REPO_ROOT/.venv/bin/python" ]; then
  "$PYTHON_BIN" -m venv "$REPO_ROOT/.venv" || close_prompt 1
fi
"$REPO_ROOT/.venv/bin/python" -m pip install --upgrade pip || close_prompt 1
"$REPO_ROOT/.venv/bin/python" -m pip install -r "$REPO_ROOT/requirements.txt" || close_prompt 1

echo "[2/4] Verifying SHA-256 pins across kits/..."
"$REPO_ROOT/.venv/bin/python" -B "$REPO_ROOT/cli/studio_cli.py" verify-pins --json

APP_BUNDLE="$REPO_ROOT/macos/OpenGateStudio/dist/OpenGate Studio.app"
if [ "${OPENGATE_FORCE_REBUILD:-0}" = "1" ] || [ ! -d "$APP_BUNDLE" ]; then
  if command -v swift >/dev/null 2>&1 && [ -x "$REPO_ROOT/macos/OpenGateStudio/bundle_app.sh" ]; then
    echo "[3/4] Building OpenGate Studio.app..."
    "$REPO_ROOT/macos/OpenGateStudio/bundle_app.sh" || close_prompt 1
  else
    echo "[3/4] Skipping Swift build (swift toolchain not found); checking prebuilt .app..."
  fi
else
  echo "[3/4] Using prebuilt OpenGate Studio.app (set OPENGATE_FORCE_REBUILD=1 to rebuild)..."
fi

if [ -d "$APP_BUNDLE" ] && [ -z "${OPENGATE_NO_APP_OPEN:-}" ]; then
  xattr -dr com.apple.quarantine "$APP_BUNDLE" 2>/dev/null || true
  echo "[4/4] Opening OpenGate Studio.app..."
  open "$APP_BUNDLE"
else
  echo "[4/4] App bundle status: $([ -d "$APP_BUNDLE" ] && echo "$APP_BUNDLE" || echo "not built (Swift CLI tools still ready)")"
fi

cat <<'EOF'

==============================================================================
OpenGate Studio — Ready for Office Camera Testing
==============================================================================
No Zadig or Homebrew libusb driver is required on macOS: live USB commands
automatically prompt once for your macOS password to detach iousbmassstorage.

Live Terminal CLI Usage:
  # Read-only preflight (safe, writes nothing):
  ./macos/run_live_terminal.sh preflight --body zve1_202
  ./macos/run_live_terminal.sh preflight --body a7s3_501
  ./macos/run_live_terminal.sh preflight --body fx3_702

  # Dry-run packet preview (touches nothing):
  ./macos/run_live_terminal.sh apply --body zve1_202 --packs mp4_3x2,screen_3x2 --dry-run

  # Inspect recorded MP4 + M01.XML + rtmd gyro clips:
  .venv/bin/python -B cli/studio_cli.py check-clip /path/to/C0001.MP4 --xml /path/to/C0001M01.XML --json

Full Camera Menu Settings & Step-by-Step Checklist:
  docs/OFFICE_CAMERA_TEST_GUIDE.md
==============================================================================
EOF

close_prompt 0
