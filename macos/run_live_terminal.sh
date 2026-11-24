#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Live USB Terminal wrapper for Sony OpenGate Studio.
# macOS keeps its own iousbmassstorage driver bound to Sony cameras in MSC mode;
# only root may detach it, so live runs execute under sudo and restore ownership
# of both --session-dir and OPENGATE_CAMERA_PRIVATE afterwards.
# --dry-run / --help bypass sudo and send nothing.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ORCH="$REPO_ROOT/cli/studio_live_apply.py"

if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
  PY="$REPO_ROOT/.venv/bin/python"
elif [ -x "$REPO_ROOT/../.venv/bin/python" ]; then
  PY="$REPO_ROOT/../.venv/bin/python"
else
  PY="$(command -v python3 || true)"
fi

if [ -z "$PY" ] || [ ! -x "$PY" ]; then
  echo "ERROR: Python 3 environment missing. Run setup_and_open_mac.command first." >&2
  exit 1
fi

SESSION_DIR="${OPENGATE_SESSION_DIR:-/tmp/opengate_studio_sessions}"
ARGS=("$@")
i=0
while [ $i -lt ${#ARGS[@]} ]; do
  if [ "${ARGS[$i]}" = "--session-dir" ] && [ $((i + 1)) -lt ${#ARGS[@]} ]; then
    SESSION_DIR="${ARGS[$((i + 1))]}"
    break
  fi
  i=$((i + 1))
done

PRIVATE_DIR="${OPENGATE_CAMERA_PRIVATE:-$REPO_ROOT/sessions/camera_private}"
export OPENGATE_CAMERA_PRIVATE="$PRIVATE_DIR"

close_prompt() {
  local rc="$1"
  if [ -t 0 ] && [ -z "${OPENGATE_NO_CLOSE_PROMPT:-}" ]; then
    echo
    read -r -p "Press Return to close. " || true
  fi
  exit "$rc"
}

case " $* " in
  *" --dry-run "*|*" --help "*|*" -h "*)
    "$PY" -I -B "$ORCH" "$@"
    exit $?
    ;;
esac

echo "macOS requires administrator rights once to release iousbmassstorage from the camera."
mkdir -p "$SESSION_DIR" "$PRIVATE_DIR"

set +e
sudo /bin/bash -c 'trap : INT; session_dir=$1; private_dir=$2; shift 2; OPENGATE_CAMERA_PRIVATE="$private_dir" "$@"; status=$?
  [ -n "$session_dir" ] && [ -d "$session_dir" ] && chown -R "$SUDO_UID:$SUDO_GID" "$session_dir"
  [ -n "$private_dir" ] && [ -d "$private_dir" ] && chown -R "$SUDO_UID:$SUDO_GID" "$private_dir"
  exit $status' run "$SESSION_DIR" "$PRIVATE_DIR" "$PY" -I -B "$ORCH" "$@"
STATUS=$?
set -e

close_prompt "$STATUS"
