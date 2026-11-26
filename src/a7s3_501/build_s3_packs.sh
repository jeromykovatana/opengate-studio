#!/usr/bin/env bash
# Build the new a7S III 5.01 write packs (V19/V20, H16/H17, B19/B20, I19/I20)
# and coherent read-only helpers (libJit_s3_check.so, libJit_s3_dump.so).
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
STUDIO_ROOT="$(cd "$SRC_DIR/../.." && pwd)"
WORKSPACE_ROOT="$(cd "$STUDIO_ROOT/.." && pwd)"
KIT_DIR="$STUDIO_ROOT/kits/a7s3_501"
FW_DIR="${SONY_FW_DIR:-$WORKSPACE_ROOT/firmwares/a7siii/ghidra_targets}"
SEN="$FW_DIR/libsencore.so"
READCHECK_C="$STUDIO_ROOT/src/common/readcheck.c"
ZIG_PY="${ZIG_PY:-python3}"

mkdir -p "$KIT_DIR"
python3 -B "$SRC_DIR/gen_s3_packs.py"

CC=(
  "$ZIG_PY" -m ziglang cc
  -target aarch64-linux-gnu -std=gnu11 -O1 -Wall -Wextra -Werror
  -fPIC -shared -nostdlib -ffreestanding
  -fno-stack-protector -fno-builtin -fno-asynchronous-unwind-tables
  -Wl,-soname,libJit.so -Wl,--no-undefined -Wl,-z,now -g0 -s -Wl,-z,max-page-size=4096
)

# L5/L6: Dual-mode (0x8c0 + 0x820) NTSC/PAL sensor readout (MULTI_REC)
for L in 5 6; do
  N="L$L"
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DSITES_H="expected_sites_ogsq_s3_v6.h"' '-DDESIGN_LABEL="ogsq_s3_v6"' \
    -DIMAGER=0x12a41f0UL -DCTRL_DRVPARAM=0x698U \
    "$READCHECK_C" "$SEN" -o "$KIT_DIR/libJit_s3_${N}.so"
done

# L19/L20: Data-only 23.98p/25p/29.97p Long-GOP fallback (4 libmpr + 149 av-cam = 153 sites)
for L in 19 20; do
  N="L$L"
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DMP_H="expected_mp_ogfile2560_hs_s_s3_nometa.h"' -DAVCAM_PHYS=0x401000000UL \
    "$READCHECK_C" -o "$KIT_DIR/libJit_s3_${N}.so"
done

# V19/V20: MP4 3:2 + encoder union (12 libmpr + 149 av-cam = 161 sites)
for L in 19 20; do
  N="V$L"
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DMP_H="expected_mp_ogfile2560_hs_s_s3_v3.h"' -DAVCAM_PHYS=0x401000000UL \
    "$READCHECK_C" -o "$KIT_DIR/libJit_s3_${N}.so"
done

# H16/H17: Clean 3:2 HDMI + anamorphic de-squeeze (28 words in cpapp-b.bin)
for L in 16 17; do
  N="H$L"
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DWORDS_H="expected_words_hdmi32_s3_501.h"' \
    "$READCHECK_C" "$SEN" -o "$KIT_DIR/libJit_s3_${N}.so"
done

# B19/B20: High-bitrate 200M/300M Long-GOP (108 av-cam sites)
for L in 19 20; do
  N="B$L"
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DMP_H="expected_mp_og_highbitrate_s3_501.h"' -DAVCAM_PHYS=0x401000000UL \
    "$READCHECK_C" -o "$KIT_DIR/libJit_s3_${N}.so"
done

# I19/I20: Orthogonal XAVC S-I All-Intra delta (42 sites)
for L in 19 20; do
  N="I$L"
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DMP_H="expected_mp_og_xavcsi_addon_s3_501.h"' -DAVCAM_PHYS=0x401000000UL \
    "$READCHECK_C" -o "$KIT_DIR/libJit_s3_${N}.so"
done

# Coherent read-only helpers (s3read_v9)
"${CC[@]}" -I "$SRC_DIR" -DDUMP=0 "$SRC_DIR/s3read.c" "$SEN" -o "$KIT_DIR/libJit_s3_check.so"
"${CC[@]}" -I "$SRC_DIR" -DDUMP=1 "$SRC_DIR/s3read.c" "$SEN" -o "$KIT_DIR/libJit_s3_dump.so"

echo "Built a7S III 5.01 artifacts in $KIT_DIR:"
for f in "$KIT_DIR"/libJit_s3_{L5,L6,L19,L20,V19,V20,H16,H17,B19,B20,I19,I20,check,dump}.so; do
  printf "  %s  %s  %d bytes\n" "$(shasum -a 256 "$f" | awk '{print $1}')" "$(basename "$f")" "$(wc -c < "$f")"
done
