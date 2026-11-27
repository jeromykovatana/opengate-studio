#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="OpenGate Studio"
EXECUTABLE_NAME="OpenGateStudio"
DIST_DIR="$SCRIPT_DIR/dist"
APP_BUNDLE="$DIST_DIR/${APP_NAME}.app"
CONTENTS_DIR="$APP_BUNDLE/Contents"
MACOS_DIR="$CONTENTS_DIR/MacOS"
RESOURCES_DIR="$CONTENTS_DIR/Resources"

RAW_APP_VERSION="${APP_VERSION:-1.0.0}"
BUNDLE_SHORT_VERSION="${RAW_APP_VERSION#v}"
BUNDLE_SHORT_VERSION="${BUNDLE_SHORT_VERSION#V}"
if [[ -z "$BUNDLE_SHORT_VERSION" ]]; then
    echo "ERROR: APP_VERSION resolved to an empty CFBundleShortVersionString (input: '$RAW_APP_VERSION')" >&2
    exit 1
fi
if [[ ! "$BUNDLE_SHORT_VERSION" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "ERROR: Invalid APP_VERSION '$RAW_APP_VERSION'. Allowed characters after optional leading v: A-Za-z0-9._-" >&2
    exit 1
fi
BUNDLE_BUILD_VERSION="${APP_BUILD_VERSION:-1}"

if [[ -n "${APPLE_NOTARY_PROFILE:-}" && -z "${APPLE_DEVELOPER_ID_APP:-}" ]]; then
    echo "ERROR: APPLE_NOTARY_PROFILE requires APPLE_DEVELOPER_ID_APP (ad-hoc signatures cannot be notarized)." >&2
    exit 1
fi

echo "[1/4] Building release binary (version $BUNDLE_SHORT_VERSION)..."
swift build -c release

BIN_DIR="$(swift build -c release --show-bin-path)"
BUILT_BIN="$BIN_DIR/$EXECUTABLE_NAME"

if [[ ! -x "$BUILT_BIN" ]]; then
    echo "ERROR: Built binary not found at $BUILT_BIN" >&2
    exit 1
fi

echo "[2/4] Packaging $APP_BUNDLE..."
rm -rf "$APP_BUNDLE"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"

cp "$BUILT_BIN" "$MACOS_DIR/$EXECUTABLE_NAME"
chmod +x "$MACOS_DIR/$EXECUTABLE_NAME"

if [[ -f "$SCRIPT_DIR/Resources/AppIcon.icns" ]]; then
    cp "$SCRIPT_DIR/Resources/AppIcon.icns" "$RESOURCES_DIR/AppIcon.icns"
fi

cat > "$CONTENTS_DIR/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>
    <key>CFBundleDisplayName</key>
    <string>OpenGate Studio</string>
    <key>CFBundleExecutable</key>
    <string>OpenGateStudio</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>org.opengatestudio.macos</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>OpenGate Studio</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>${BUNDLE_SHORT_VERSION}</string>
    <key>CFBundleVersion</key>
    <string>${BUNDLE_BUILD_VERSION}</string>
    <key>LSMinimumSystemVersion</key>
    <string>14.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
</dict>
</plist>
EOF

cat > "$RESOURCES_DIR/StudioMetadata.json" << EOF
{
  "app": "OpenGate Studio",
  "version": "${BUNDLE_SHORT_VERSION}",
  "license": "GPL-3.0-or-later",
  "mode": "volatile-ram-only",
  "supported_bodies": ["zve1_202", "a7s3_501", "fx3_702", "a7c_203", "zve10_203"]
}
EOF

echo "[3/4] Verifying bundle structure and architecture..."
plutil -lint "$CONTENTS_DIR/Info.plist"

ARCHS="$(lipo -archs "$MACOS_DIR/$EXECUTABLE_NAME")"
echo "Binary architectures: $ARCHS"
if [[ "$ARCHS" != *"arm64"* ]]; then
    echo "ERROR: Expected arm64 architecture in $MACOS_DIR/$EXECUTABLE_NAME, got: $ARCHS" >&2
    exit 1
fi

file "$MACOS_DIR/$EXECUTABLE_NAME"

if [[ ! -f "$CONTENTS_DIR/Info.plist" || ! -x "$MACOS_DIR/$EXECUTABLE_NAME" ]]; then
    echo "ERROR: Incomplete .app bundle at $APP_BUNDLE" >&2
    exit 1
fi

if command -v codesign >/dev/null 2>&1; then
    if [[ -n "${APPLE_DEVELOPER_ID_APP:-}" ]]; then
        echo "[4/4] Developer ID signing (hardened runtime) $APP_BUNDLE..."
        codesign --force --deep --options runtime --timestamp --sign "$APPLE_DEVELOPER_ID_APP" "$APP_BUNDLE"
        codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE"

        if [[ -n "${APPLE_NOTARY_PROFILE:-}" ]]; then
            echo "[4/4] Notarizing and stapling $APP_BUNDLE via profile '$APPLE_NOTARY_PROFILE'..."
            NOTARY_TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/opengate_notary.XXXXXX")"
            NOTARY_ZIP="$NOTARY_TMP_DIR/${APP_NAME}.zip"
            cleanup_notary() {
                rm -rf "$NOTARY_TMP_DIR"
            }
            trap cleanup_notary EXIT
            ditto -c -k --keepParent "$APP_BUNDLE" "$NOTARY_ZIP"
            xcrun notarytool submit "$NOTARY_ZIP" --keychain-profile "$APPLE_NOTARY_PROFILE" --wait
            xcrun stapler staple "$APP_BUNDLE"
            xcrun stapler validate "$APP_BUNDLE"
            codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE"
            cleanup_notary
            trap - EXIT
        else
            echo "[4/4] APPLE_NOTARY_PROFILE unset; skipping notarization."
        fi
    else
        echo "[4/4] Ad-hoc signing and verifying $APP_BUNDLE (APPLE_DEVELOPER_ID_APP unset)..."
        codesign --force --deep --sign - "$APP_BUNDLE"
        codesign --verify --deep --strict "$APP_BUNDLE"
    fi
else
    echo "[4/4] codesign not found; skipping code signature."
fi

echo "Packaged successfully: $APP_BUNDLE"
