#!/usr/bin/env bash
# Build the new FX3 7.02 write packs (V19/V20, H16/H17, B19/B20, I19/I20)
# and coherent read-only helpers (libJit_fx3_check.so, libJit_fx3_dump.so).
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
STUDIO_ROOT="$(cd "$SRC_DIR/../.." && pwd)"
WORKSPACE_ROOT="$(cd "$STUDIO_ROOT/.." && pwd)"
KIT_DIR="${KIT_OUT_DIR:-$STUDIO_ROOT/kits/fx3_702}"
FW_DIR="${SONY_FW_DIR:-$WORKSPACE_ROOT/firmwares/fx3/ghidra_targets}"
SEN="${SEN_SO_PATH:-$FW_DIR/libsencore.so}"
READCHECK_C="$STUDIO_ROOT/src/common/readcheck.c"
ZIG_PY="${ZIG_PY:-python3}"

mkdir -p "$KIT_DIR"
if [ "${SKIP_GEN:-0}" != "1" ]; then
  "$ZIG_PY" -B "$SRC_DIR/gen_fx3_packs.py"
fi

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
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DSITES_H="expected_sites_ogsq_fx3_v2.h"' '-DDESIGN_LABEL="ogsq_fx3_v2"' \
    -DIMAGER=0x127ab68UL -DCTRL_DRVPARAM=0x698U \
    "$READCHECK_C" "$SEN" -o "$KIT_DIR/libJit_fx3_${N}.so"
done

# L16/L17 & S16/S17: outsz2560_fx3_v1 & lcd32dsq_fx3_v1
for L in 16 17; do
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DWORDS_H="expected_words_outsz2560_fx3_v1.h"' \
    "$READCHECK_C" "$SEN" -o "$KIT_DIR/libJit_fx3_L${L}.so"
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DWORDS_H="expected_words_lcd32dsq_fx3_v1.h"' \
    "$READCHECK_C" "$SEN" -o "$KIT_DIR/libJit_fx3_S${L}.so"
done

# L19/L20: Data-only 23.98p/25p/29.97p Long-GOP fallback (4 libmpr + 149 av-cam = 153 sites)
for L in 19 20; do
  N="L$L"
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DMP_H="expected_mp_ogfile2560_hs_s_fx3_nometa.h"' -DAVCAM_PHYS=0x401000000UL \
    "$READCHECK_C" -o "$KIT_DIR/libJit_fx3_${N}.so"
done

# V19/V20: MP4 3:2 + encoder union (12 libmpr + 149 av-cam = 161 sites)
for L in 19 20; do
  N="V$L"
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DMP_H="expected_mp_ogfile2560_hs_s_fx3_v3.h"' -DAVCAM_PHYS=0x401000000UL \
    "$READCHECK_C" -o "$KIT_DIR/libJit_fx3_${N}.so"
done

# H16/H17: Clean 3:2 HDMI + anamorphic de-squeeze (18 words in cpapp-b.bin)
for L in 16 17; do
  N="H$L"
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DWORDS_H="expected_words_hdmi32_fx3_702.h"' \
    "$READCHECK_C" "$SEN" -o "$KIT_DIR/libJit_fx3_${N}.so"
done

# B19/B20: High-bitrate 200M/300M Long-GOP (108 av-cam sites)
for L in 19 20; do
  N="B$L"
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DMP_H="expected_mp_og_highbitrate_fx3_702.h"' -DAVCAM_PHYS=0x401000000UL \
    "$READCHECK_C" -o "$KIT_DIR/libJit_fx3_${N}.so"
done

# I19/I20: Orthogonal XAVC S-I All-Intra delta (42 sites)
for L in 19 20; do
  N="I$L"
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DMP_H="expected_mp_og_xavcsi_addon_fx3_702.h"' -DAVCAM_PHYS=0x401000000UL \
    "$READCHECK_C" -o "$KIT_DIR/libJit_fx3_${N}.so"
done

# P29/P30: FX3 8K decode channel avdec8k_fx3_v1 (4 av-cam code words + 1 data word)
for L in 29 30; do
  N="P$L"
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DAD_H="expected_ad_avdec8k_fx3_v1.h"' -DAVCAM_PHYS=0x401000000UL \
    "$READCHECK_C" -o "$KIT_DIR/libJit_fx3_${N}.so"
done

# Fused single-pass presets (Q19/Q20 Safe Daily, F19/F20 Cinema Full)
FUSED_C="$STUDIO_ROOT/src/common/fused_preset.c"
for L in 19 20; do
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DFUSED_H="expected_fused_safe_daily_fx3.h"' \
    "$FUSED_C" "$SEN" -o "$KIT_DIR/libJit_fx3_Q${L}.so"
  "${CC[@]}" -I "$SRC_DIR" -DLEVEL=$L '-DFUSED_H="expected_fused_cinema_full_fx3.h"' \
    "$FUSED_C" "$SEN" -o "$KIT_DIR/libJit_fx3_F${L}.so"
done
for code in Q19 Q20 F19 F20; do
  sz=$(wc -c < "$KIT_DIR/libJit_fx3_${code}.so" | tr -d ' ')
  [ "$sz" -le 65520 ] || { echo "SIZE LIMIT EXCEEDED ($sz > 65520) for libJit_fx3_${code}.so"; exit 1; }
done

# Coherent read-only helpers (fx3read_v2)
"${CC[@]}" -I "$SRC_DIR" -DDUMP=0 "$SRC_DIR/fx3read.c" "$SEN" -o "$KIT_DIR/libJit_fx3_check.so"
"${CC[@]}" -I "$SRC_DIR" -DDUMP=1 "$SRC_DIR/fx3read.c" "$SEN" -o "$KIT_DIR/libJit_fx3_dump.so"

if [ "${SKIP_EMIT_MANIFEST:-0}" != "1" ] && [ "$KIT_DIR" = "$STUDIO_ROOT/kits/fx3_702" ]; then
  "$ZIG_PY" -B "$SRC_DIR/gen_fx3_packs.py" --emit-manifest
fi

for f in "$KIT_DIR"/*.so; do
  strings "$f" | grep -q "clang version 18.1.6" || { echo "MISSING clang 18.1.6 in $f"; exit 1; }
done

echo "Built FX3 7.02 artifacts in $KIT_DIR:"
for f in "$KIT_DIR"/libJit_fx3_{L5,L6,L16,L17,S16,S17,L19,L20,V19,V20,H16,H17,B19,B20,I19,I20,P29,P30,Q19,Q20,F19,F20,check,dump}.so; do
  printf "  %s  %s  %d bytes\n" "$(shasum -a 256 "$f" | awk '{print $1}')" "$(basename "$f")" "$(wc -c < "$f")"
done
