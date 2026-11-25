#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Build ZV-E1 2.02 new studio write helpers (V19/V20, H16/H17, B19/B20, I19/I20),
# upgraded zvread_v4 read-only helpers (check/dump), and emit kits/zve1_202/manifest.json.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
STUDIO="$(cd "$SRC/../.." && pwd)"
WS="$(cd "$STUDIO/.." && pwd)"
KIT="$STUDIO/kits/zve1_202"

ZIG_PYTHON="${ZIG_PYTHON:-python3}"
SONY_FW_DIR="${SONY_FW_DIR:-$WS/firmwares/zve1/ghidra_targets}"
SEN="$SONY_FW_DIR/libsencore.so"

if [ -f "$STUDIO/src/common/readcheck.c" ]; then
  READCHECK_C="$STUDIO/src/common/readcheck.c"
else
  READCHECK_C="$WS/zve1-pr2-preflight/windows/tools/camera_tests/CT6_memory_read_check/helper/readcheck.c"
fi

export SONY_FW_DIR
PYTHONDONTWRITEBYTECODE=1 "$ZIG_PYTHON" -B "$SRC/gen_zv_studio.py" --fw-dir "$SONY_FW_DIR"
PYTHONDONTWRITEBYTECODE=1 "$ZIG_PYTHON" -B "$SRC/gen_zv_v4.py" --fw-dir "$SONY_FW_DIR"

CC=("$ZIG_PYTHON" -m ziglang cc -target aarch64-linux-gnu -std=gnu11 -O1 -Wall -Wextra -Werror
    -fPIC -shared -nostdlib -ffreestanding -fno-stack-protector -fno-builtin
    -fno-asynchronous-unwind-tables -Wl,-soname,libJit.so -Wl,--no-undefined -Wl,-z,now -g0 -s
    -Wl,-z,max-page-size=4096 -I"$SRC")

mkdir -p "$KIT"

# V19/V20: ogfile2560_hs_s_zv_v3
for L in 19 20; do
  "${CC[@]}" -DLEVEL=$L '-DMP_H="expected_mp_ogfile2560_hs_s_zv_v3.h"' -DAVCAM_PHYS=0x401000000UL \
    "$READCHECK_C" -o "$KIT/libJit_zv_V$L.so"
done

# H16/H17: hdmi32_zv_202 (linked against libsencore.so)
for L in 16 17; do
  "${CC[@]}" -DLEVEL=$L '-DWORDS_H="expected_words_hdmi32_zv_202.h"' \
    "$READCHECK_C" "$SEN" -o "$KIT/libJit_zv_H$L.so"
done

# B19/B20: og_highbitrate_zv_202
for L in 19 20; do
  "${CC[@]}" -DLEVEL=$L '-DMP_H="expected_mp_og_highbitrate_zv_202.h"' -DAVCAM_PHYS=0x401000000UL \
    "$READCHECK_C" -o "$KIT/libJit_zv_B$L.so"
done

# I19/I20: og_xavcsi_addon_zv_202
for L in 19 20; do
  "${CC[@]}" -DLEVEL=$L '-DMP_H="expected_mp_og_xavcsi_addon_zv_202.h"' -DAVCAM_PHYS=0x401000000UL \
    "$READCHECK_C" -o "$KIT/libJit_zv_I$L.so"
done

# zvread_v4 check/dump (linked against libsencore.so)
"${CC[@]}" -DDUMP=0 "$SRC/zvread.c" "$SEN" -o "$KIT/libJit_zv_check.so"
"${CC[@]}" -DDUMP=1 "$SRC/zvread.c" "$SEN" -o "$KIT/libJit_zv_dump.so"

PYTHONDONTWRITEBYTECODE=1 "$ZIG_PYTHON" -B "$SRC/emit_manifest.py"

for f in "$KIT"/*.so; do
  strings "$f" | grep -q "clang version 18.1.6" || { echo "MISSING clang 18.1.6 in $f"; exit 1; }
done
echo "PASS: all $(ls -1 "$KIT"/*.so | wc -l | tr -d ' ') .so files verified with clang version 18.1.6"
