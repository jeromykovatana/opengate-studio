#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Clean-room release packager for OpenGate Studio (macOS arm64 + runtime).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

usage() {
    cat <<'EOF'
Usage: scripts/package_release.sh --version <tag> [--dry-run] [--output-dir <dir>] [--apk <path>]

Options:
  --version <tag>     Release version tag (e.g. v0.1.3-alpha). Required.
  --dry-run           Run verification gates and stage/verify clean runtime in a
                      temporary directory without building the .app or writing dist/.
  --output-dir <dir>  Output directory for zip, optional apk, and SHA256SUMS.txt (default: ./dist).
  --apk <path>        Optional Android debug/release APK to copy into <output-dir> as
                      OpenGate-Field-Companion-<version>-debug.apk and include in SHA256SUMS.txt.
  -h, --help          Show this help message.
EOF
}

VERSION=""
DRY_RUN=0
OUTPUT_DIR="$REPO_ROOT/dist"
APK_SRC=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "ERROR: --version requires a value." >&2
                usage >&2
                exit 2
            fi
            VERSION="$2"
            shift 2
            ;;
        --version=*)
            VERSION="${1#*=}"
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --output-dir)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "ERROR: --output-dir requires a value." >&2
                usage >&2
                exit 2
            fi
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --output-dir=*)
            OUTPUT_DIR="${1#*=}"
            shift
            ;;
        --apk)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "ERROR: --apk requires a value." >&2
                usage >&2
                exit 2
            fi
            APK_SRC="$2"
            shift 2
            ;;
        --apk=*)
            APK_SRC="${1#*=}"
            if [[ -z "$APK_SRC" ]]; then
                echo "ERROR: --apk requires a non-empty path." >&2
                usage >&2
                exit 2
            fi
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -z "$VERSION" ]]; then
    echo "ERROR: --version <tag> is required (e.g. --version v0.1.3-alpha)." >&2
    usage >&2
    exit 2
fi

if [[ ! "$VERSION" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "ERROR: Invalid version tag '$VERSION'. Allowed characters: A-Za-z0-9._-" >&2
    exit 2
fi

if [[ -n "$APK_SRC" && ! -f "$APK_SRC" ]]; then
    echo "ERROR: --apk file not found: $APK_SRC" >&2
    exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "ERROR: Python interpreter not found: $PYTHON_BIN" >&2
    exit 1
fi

RELEASE_STEM="Sony-OpenGate-Studio-${VERSION}-macos-arm64"
ZIP_NAME="${RELEASE_STEM}.zip"
APK_NAME="OpenGate-Field-Companion-${VERSION}-debug.apk"

TMP_WORK="$(mktemp -d "${TMPDIR:-/tmp}/opengate_release.XXXXXX")"
cleanup() {
    rm -rf "$TMP_WORK"
}
trap cleanup EXIT

STAGE_DIR="$TMP_WORK/$RELEASE_STEM"
mkdir -p "$STAGE_DIR"

echo "[1/5] Running clean-room, support matrix, and SHA-256 pin checks..."
"$PYTHON_BIN" "$REPO_ROOT/scripts/verify_clean_room.py"
"$PYTHON_BIN" "$REPO_ROOT/scripts/generate_support_matrix.py" --check
"$PYTHON_BIN" "$REPO_ROOT/cli/studio_cli.py" verify-pins --json

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[2/5] Dry-run: skipping macos/OpenGateStudio/bundle_app.sh (APP_VERSION=$VERSION)..."
else
    echo "[2/5] Building OpenGate Studio.app (APP_VERSION=$VERSION)..."
    APP_VERSION="$VERSION" bash "$REPO_ROOT/macos/OpenGateStudio/bundle_app.sh"
    APP_BUNDLE_SRC="$REPO_ROOT/macos/OpenGateStudio/dist/OpenGate Studio.app"
    if [[ ! -d "$APP_BUNDLE_SRC" ]]; then
        echo "ERROR: Expected app bundle not found at $APP_BUNDLE_SRC" >&2
        exit 1
    fi
fi

echo "[3/5] Staging clean runtime into temporary staging directory..."
copy_clean_tree() {
    local src="$1"
    local dst="$2"
    if command -v rsync >/dev/null 2>&1; then
        mkdir -p "$dst"
        rsync -a \
            --exclude='.git' \
            --exclude='.git/**' \
            --exclude='.venv' \
            --exclude='.venv/**' \
            --exclude='.DS_Store' \
            --exclude='__pycache__' \
            --exclude='__pycache__/**' \
            --exclude='*.pyc' \
            --exclude='*.pyo' \
            --exclude='dist' \
            --exclude='dist/**' \
            --exclude='.build' \
            --exclude='.build/**' \
            --exclude='sessions' \
            --exclude='sessions/**' \
            --exclude='camera_private' \
            --exclude='camera_private/**' \
            --exclude='*.log' \
            "$src/" "$dst/"
    else
        "$PYTHON_BIN" - "$src" "$dst" <<'PY'
import shutil
import sys
from pathlib import Path

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
exclude_dirs = {".git", ".venv", "__pycache__", "dist", ".build", "sessions", "camera_private"}

def ignore(dirpath, names):
    ignored = []
    for name in names:
        if name in exclude_dirs or name == ".DS_Store" or name.endswith((".pyc", ".pyo", ".log")):
            ignored.append(name)
    return ignored

shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True, symlinks=True)
PY
    fi
}

if [[ "$DRY_RUN" -eq 0 ]]; then
    ditto "$REPO_ROOT/macos/OpenGateStudio/dist/OpenGate Studio.app" "$STAGE_DIR/OpenGate Studio.app"
    find "$STAGE_DIR/OpenGate Studio.app" -name '.DS_Store' -delete
fi

for dir_name in cli kits presets transport scripts docs; do
    if [[ ! -d "$REPO_ROOT/$dir_name" ]]; then
        echo "ERROR: Required runtime directory missing: $dir_name" >&2
        exit 1
    fi
    copy_clean_tree "$REPO_ROOT/$dir_name" "$STAGE_DIR/$dir_name"
done

mkdir -p "$STAGE_DIR/macos"
shopt -s nullglob
LIVE_SCRIPTS=("$REPO_ROOT"/macos/run_live_*.sh)
shopt -u nullglob
if [[ ${#LIVE_SCRIPTS[@]} -eq 0 ]]; then
    echo "ERROR: No macos/run_live_*.sh scripts found." >&2
    exit 1
fi
for script_path in "${LIVE_SCRIPTS[@]}"; do
    cp -p "$script_path" "$STAGE_DIR/macos/"
done

for file_name in requirements.txt requirements-build.txt setup_and_open_mac.command README.md LICENSE; do
    if [[ ! -f "$REPO_ROOT/$file_name" ]]; then
        echo "ERROR: Required runtime file missing: $file_name" >&2
        exit 1
    fi
    cp -p "$REPO_ROOT/$file_name" "$STAGE_DIR/$file_name"
done

echo "[4/5] Verifying staged tree integrity and exclusions..."
EXCLUDED_HITS="$(
    find "$STAGE_DIR" \
        \( -name '.git' -o -name '.venv' -o -name '.DS_Store' -o -name '__pycache__' \
           -o -name 'dist' -o -name '.build' -o -name 'sessions' -o -name 'camera_private' \
           -o -name '*.pyc' -o -name '*.pyo' -o -name '*.log' \) -print
)"
if [[ -n "$EXCLUDED_HITS" ]]; then
    echo "ERROR: Excluded artifact(s) leaked into staging directory:" >&2
    echo "$EXCLUDED_HITS" >&2
    exit 1
fi

MANIFEST_COUNT="$(find "$STAGE_DIR/kits" -mindepth 2 -maxdepth 2 -name 'manifest.json' | wc -l | tr -d ' ')"
SO_COUNT="$(find "$STAGE_DIR/kits" -mindepth 2 -maxdepth 2 -name '*.so' | wc -l | tr -d ' ')"
if [[ "$MANIFEST_COUNT" -ne 5 ]]; then
    echo "ERROR: Expected 5 kits/*/manifest.json files in staging, found $MANIFEST_COUNT" >&2
    exit 1
fi
if [[ "$SO_COUNT" -ne 90 ]]; then
    echo "ERROR: Expected 90 kits/*/*.so helpers in staging, found $SO_COUNT" >&2
    exit 1
fi

"$PYTHON_BIN" - "$STAGE_DIR" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import verify_clean_room
res = verify_clean_room.verify_clean_room(Path(sys.argv[1]))
if not res["ok"]:
    print("Staged clean-room check failed:", res["errors"], file=sys.stderr)
    sys.exit(1)
print(
    f"STAGED CLEAN-ROOM PASS: {res['checked_manifests']} manifests, "
    f"{res['checked_so']} .so helpers, {res['checked_pmca_files']} pmca files."
)
PY

if [[ "$DRY_RUN" -eq 1 ]]; then
    SUMS_PREVIEW="$TMP_WORK/SHA256SUMS.preview.txt"
    (
        cd "$STAGE_DIR"
        printf '<pending-zip-build>  %s\n' "$ZIP_NAME"
        if [[ -n "$APK_SRC" ]]; then
            printf '<pending-apk-copy>  %s\n' "$APK_NAME"
        fi
        find kits -mindepth 2 -maxdepth 2 -name 'manifest.json' | sort | xargs shasum -a 256
        find kits -mindepth 2 -maxdepth 2 -name '*.so' | sort | xargs shasum -a 256
    ) > "$SUMS_PREVIEW"
    SUM_LINES="$(wc -l < "$SUMS_PREVIEW" | tr -d ' ')"
    echo "[5/5] Dry-run complete (no dist/ files written)."
    echo "  Planned archive: $OUTPUT_DIR/$ZIP_NAME"
    if [[ -n "$APK_SRC" ]]; then
        echo "  Planned APK:     $OUTPUT_DIR/$APK_NAME"
        echo "  Planned sums:    $OUTPUT_DIR/SHA256SUMS.txt ($SUM_LINES entries: 1 zip + 1 apk + $MANIFEST_COUNT manifests + $SO_COUNT .so helpers)"
    else
        echo "  Planned sums:    $OUTPUT_DIR/SHA256SUMS.txt ($SUM_LINES entries: 1 zip + $MANIFEST_COUNT manifests + $SO_COUNT .so helpers)"
    fi
    exit 0
fi

echo "[5/5] Creating $OUTPUT_DIR/$ZIP_NAME and $OUTPUT_DIR/SHA256SUMS.txt..."
mkdir -p "$OUTPUT_DIR"
ZIP_PATH="$OUTPUT_DIR/$ZIP_NAME"
APK_PATH="$OUTPUT_DIR/$APK_NAME"
SUMS_PATH="$OUTPUT_DIR/SHA256SUMS.txt"
rm -f "$ZIP_PATH" "$SUMS_PATH"
if [[ -n "$APK_SRC" ]]; then
    rm -f "$APK_PATH"
    cp -p "$APK_SRC" "$APK_PATH"
fi

COPYFILE_DISABLE=1 ditto -c -k --keepParent "$STAGE_DIR" "$ZIP_PATH"

{
    (
        cd "$OUTPUT_DIR"
        shasum -a 256 "$ZIP_NAME"
        if [[ -n "$APK_SRC" ]]; then
            shasum -a 256 "$APK_NAME"
        fi
    )
    (
        cd "$STAGE_DIR"
        find kits -mindepth 2 -maxdepth 2 -name 'manifest.json' | sort | xargs shasum -a 256
        find kits -mindepth 2 -maxdepth 2 -name '*.so' | sort | xargs shasum -a 256
    )
} > "$SUMS_PATH"

SUM_LINES="$(wc -l < "$SUMS_PATH" | tr -d ' ')"
echo "Release artifacts ready:"
echo "  Archive:   $ZIP_PATH"
if [[ -n "$APK_SRC" ]]; then
    echo "  APK:       $APK_PATH"
fi
echo "  Checksums: $SUMS_PATH ($SUM_LINES entries)"
