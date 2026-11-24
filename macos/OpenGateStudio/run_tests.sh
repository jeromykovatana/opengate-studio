#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CLT_FRAMEWORKS="/Library/Developer/CommandLineTools/Library/Developer/Frameworks"
if [[ -d "$CLT_FRAMEWORKS/Testing.framework" ]]; then
    exec swift test -Xswiftc -F -Xswiftc "$CLT_FRAMEWORKS" "$@"
else
    exec swift test "$@"
fi
