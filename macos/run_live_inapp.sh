#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Native in-app Live USB wrapper for OpenGate Studio.
# Invoked by Swift StudioBridge (under macOS administrator privileges for live runs,
# or directly unprivileged when --dry-run is present). Never invokes sudo itself.
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

OWNER_UID="${SUDO_UID:-}"
OWNER_GID="${SUDO_GID:-}"
SESSION_DIR="${OPENGATE_SESSION_DIR:-/tmp/opengate_studio_sessions}"
PRIVATE_DIR="${OPENGATE_CAMERA_PRIVATE:-$REPO_ROOT/sessions/camera_private}"
EVENTS_FILE=""
LOG_FILE=""
HAS_JSON_EVENTS=0
IS_DRY_RUN=0
PASS_ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --owner-uid)
      if [ $# -lt 2 ]; then
        echo "ERROR: --owner-uid requires a value." >&2
        exit 2
      fi
      OWNER_UID="$2"
      shift 2
      ;;
    --owner-uid=*)
      OWNER_UID="${1#*=}"
      shift
      ;;
    --owner-gid)
      if [ $# -lt 2 ]; then
        echo "ERROR: --owner-gid requires a value." >&2
        exit 2
      fi
      OWNER_GID="$2"
      shift 2
      ;;
    --owner-gid=*)
      OWNER_GID="${1#*=}"
      shift
      ;;
    --session-dir)
      PASS_ARGS+=("$1")
      if [ $# -ge 2 ]; then
        SESSION_DIR="$2"
        PASS_ARGS+=("$2")
        shift 2
      else
        shift
      fi
      ;;
    --session-dir=*)
      SESSION_DIR="${1#*=}"
      PASS_ARGS+=("$1")
      shift
      ;;
    --events-file)
      PASS_ARGS+=("$1")
      if [ $# -ge 2 ]; then
        EVENTS_FILE="$2"
        PASS_ARGS+=("$2")
        shift 2
      else
        shift
      fi
      ;;
    --events-file=*)
      EVENTS_FILE="${1#*=}"
      PASS_ARGS+=("$1")
      shift
      ;;
    --log-file)
      PASS_ARGS+=("$1")
      if [ $# -ge 2 ]; then
        LOG_FILE="$2"
        PASS_ARGS+=("$2")
        shift 2
      else
        shift
      fi
      ;;
    --log-file=*)
      LOG_FILE="${1#*=}"
      PASS_ARGS+=("$1")
      shift
      ;;
    --json-events)
      HAS_JSON_EVENTS=1
      PASS_ARGS+=("$1")
      shift
      ;;
    --dry-run)
      IS_DRY_RUN=1
      PASS_ARGS+=("$1")
      shift
      ;;
    *)
      PASS_ARGS+=("$1")
      shift
      ;;
  esac
done

export OPENGATE_CAMERA_PRIVATE="$PRIVATE_DIR"

prepare_stream_file() {
  local fpath="$1"
  if [ -z "$fpath" ]; then
    return 0
  fi
  mkdir -p "$(dirname "$fpath")"
  touch "$fpath"
  chmod 644 "$fpath" || true
  if [ "$(id -u)" -eq 0 ] && [ -n "$OWNER_UID" ] && [ -n "$OWNER_GID" ]; then
    chown "$OWNER_UID:$OWNER_GID" "$fpath" 2>/dev/null || true
  fi
}

cleanup() {
  if [ "$(id -u)" -eq 0 ] && [ -n "$OWNER_UID" ] && [ -n "$OWNER_GID" ]; then
    if [ -n "$SESSION_DIR" ] && [ -d "$SESSION_DIR" ]; then
      chown -R "$OWNER_UID:$OWNER_GID" "$SESSION_DIR" 2>/dev/null || true
    fi
    if [ -n "$PRIVATE_DIR" ] && [ -d "$PRIVATE_DIR" ]; then
      chown -R "$OWNER_UID:$OWNER_GID" "$PRIVATE_DIR" 2>/dev/null || true
    fi
    if [ -n "$EVENTS_FILE" ] && [ -e "$EVENTS_FILE" ]; then
      chown "$OWNER_UID:$OWNER_GID" "$EVENTS_FILE" 2>/dev/null || true
      chmod 644 "$EVENTS_FILE" 2>/dev/null || true
    fi
    if [ -n "$LOG_FILE" ] && [ -e "$LOG_FILE" ]; then
      chown "$OWNER_UID:$OWNER_GID" "$LOG_FILE" 2>/dev/null || true
      chmod 644 "$LOG_FILE" 2>/dev/null || true
    fi
  fi
}
trap cleanup EXIT

prepare_stream_file "$EVENTS_FILE"
prepare_stream_file "$LOG_FILE"

if [ "$IS_DRY_RUN" -eq 0 ]; then
  mkdir -p "$SESSION_DIR" "$PRIVATE_DIR"
fi

EXTRA_FLAGS=()
if [ "$HAS_JSON_EVENTS" -eq 0 ]; then
  EXTRA_FLAGS+=(--json-events)
fi

RUN_CMD=("$PY" -I -B "$ORCH" ${PASS_ARGS[@]+"${PASS_ARGS[@]}"} ${EXTRA_FLAGS[@]+"${EXTRA_FLAGS[@]}"})
if [ "$(id -u)" -eq 0 ] && [ "$IS_DRY_RUN" -eq 0 ] && [ -x /bin/launchctl ]; then
  case "$OWNER_UID" in
    ''|0|*[!0-9]*)
      ;;
    *)
      if /bin/launchctl print "gui/$OWNER_UID" >/dev/null 2>&1; then
        RUN_CMD=(/bin/launchctl asuser "$OWNER_UID" "${RUN_CMD[@]}")
      fi
      ;;
  esac
fi

set +e
"${RUN_CMD[@]}"
STATUS=$?
set -e

exit "$STATUS"
