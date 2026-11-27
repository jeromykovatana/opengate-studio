#!/usr/bin/env bash
# Build Sony ZV-E10 Mark I (ZV-E10 v2.03) volatile-RAM helpers and emit kits/zve10_203/manifest.json.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
STUDIO_ROOT="$(cd "$SRC_DIR/../.." && pwd)"
KIT_DIR="${KIT_OUT_DIR:-$STUDIO_ROOT/kits/zve10_203}"
READ_C="$STUDIO_ROOT/src/common/cxd90045_read.c"
WRITE_C="$STUDIO_ROOT/src/common/cxd90045_write.c"

if [[ -n "${ZIG_PY:-}" ]]; then
  PY="$ZIG_PY"
elif [[ -x "$STUDIO_ROOT/.venv/bin/python" ]]; then
  PY="$STUDIO_ROOT/.venv/bin/python"
else
  PY="$(command -v python3)"
fi

mkdir -p "$KIT_DIR"
if [[ "${SKIP_GEN:-0}" != "1" ]]; then
  "$PY" -B "$SRC_DIR/gen_zve10_packs.py"
fi

CC=(
  "$PY" -m ziglang cc
  -target arm-linux-gnueabi -mcpu=cortex_a9 -marm -mfloat-abi=soft
  -std=gnu11 -O1 -Wall -Wextra -Werror
  -fPIC -fvisibility=hidden -shared -nostdlib -ffreestanding
  -fno-stack-protector -fno-builtin -fno-unwind-tables -fno-asynchronous-unwind-tables
  -Wl,-soname,libJit.so -Wl,--no-undefined -Wl,-z,now -g0 -s -Wl,-z,max-page-size=4096
)

"${CC[@]}" -I "$SRC_DIR" -DDUMP=0 -DREADER_NAME='"zve10read"' -DMODEL_NAME='"ZV-E10"' -DFW_VER='"2.03"' -DEXPECTED_H='"zve10_expected.h"' \
  "$READ_C" -o "$KIT_DIR/libJit_zve10_check.so"
"${CC[@]}" -I "$SRC_DIR" -DDUMP=1 -DREADER_NAME='"zve10read"' -DMODEL_NAME='"ZV-E10"' -DFW_VER='"2.03"' -DEXPECTED_H='"zve10_expected.h"' \
  "$READ_C" -o "$KIT_DIR/libJit_zve10_dump.so"

"${CC[@]}" -I "$SRC_DIR" -DSTEP_NUM=5  -DIS_APPLY=1 '-DMP_H="expected_mp_ogsq_zve10_v1.h"'      "$WRITE_C" -o "$KIT_DIR/libJit_zve10_L5.so"
"${CC[@]}" -I "$SRC_DIR" -DSTEP_NUM=6  -DIS_APPLY=0 '-DMP_H="expected_mp_ogsq_zve10_v1.h"'      "$WRITE_C" -o "$KIT_DIR/libJit_zve10_L6.so"
"${CC[@]}" -I "$SRC_DIR" -DSTEP_NUM=16 -DIS_APPLY=1 '-DMP_H="expected_mp_outsz2560_zve10_v1.h"' "$WRITE_C" -o "$KIT_DIR/libJit_zve10_L16.so"
"${CC[@]}" -I "$SRC_DIR" -DSTEP_NUM=17 -DIS_APPLY=0 '-DMP_H="expected_mp_outsz2560_zve10_v1.h"' "$WRITE_C" -o "$KIT_DIR/libJit_zve10_L17.so"
"${CC[@]}" -I "$SRC_DIR" -DSTEP_NUM=19 -DIS_APPLY=1 '-DMP_H="expected_mp_ogfile2560_zve10_v1.h"' "$WRITE_C" -o "$KIT_DIR/libJit_zve10_L19.so"
"${CC[@]}" -I "$SRC_DIR" -DSTEP_NUM=20 -DIS_APPLY=0 '-DMP_H="expected_mp_ogfile2560_zve10_v1.h"' "$WRITE_C" -o "$KIT_DIR/libJit_zve10_L20.so"

if [[ "${SKIP_EMIT_MANIFEST:-0}" != "1" ]]; then
  "$PY" - "$KIT_DIR" <<'PYEOF'
import hashlib, json, sys
from pathlib import Path

kit = Path(sys.argv[1])
def meta(fname, level, summary):
    p = kit / fname
    raw = p.read_bytes()
    return {
        "file": fname,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
        "level": level,
        "summary": summary,
    }

dev = kit / "DeviceInfo.xml"
man = {
    "schema_version": 1,
    "body_id": "zve10_203",
    "camera": "ZV-E10",
    "firmware": "2.03",
    "version_txt": "30110_06.2026060501",
    "toolchain": "ziglang 0.13.0 (clang 18.1.6)",
    "persistent_writes": False,
    "device_info": {
        "file": "DeviceInfo.xml",
        "sha256": hashlib.sha256(dev.read_bytes()).hexdigest(),
        "size": dev.stat().st_size,
    },
    "readonly": {
        "check": meta("libJit_zve10_check.so", 101, "Coherent read-only preflight check (zve10read_v1: 45 av + 40 lm sites)"),
        "dump": meta("libJit_zve10_dump.so", 102, "Coherent read-only diagnostic dump + DDR pages (zve10read_v1)"),
    },
    "packs": {
        "core_open_gate": {
            "label": "Core 3:2 Open Gate (Sensor Squeezed 3840x2160)",
            "required": True,
            "apply_steps": ["L5"],
            "putback_steps": ["L6"],
            "summary": "Expands 4K24p unsplit sensor readout to full 6000x4000 (3:2) vertically squeezed into standard 3840x2160 XAVC S 4K",
        },
        "raster_2560": {
            "label": "True 3840x2560 3:2 Raster (Experimental)",
            "required": False,
            "default_enabled": False,
            "apply_steps": ["L16", "L19"],
            "putback_steps": ["L20", "L17"],
            "summary": "Experimental native 3840x2560 H.264 output across movie size, encoder descriptors, VCD profiles, and libmpr (leave off for Safe Daily 3:2)",
        },
    },
    "steps": {
        "L5": meta("libJit_zve10_L5.so", 205, "Apply sensor 3:2 full-height readout (ogsq_zve10_v1: 16 sites)"),
        "L6": meta("libJit_zve10_L6.so", 206, "Put back sensor 3:2 full-height readout (ogsq_zve10_v1)"),
        "L16": meta("libJit_zve10_L16.so", 216, "Apply movie output height 2160 -> 2560 (outsz2560_zve10_v1: 9 sites)"),
        "L17": meta("libJit_zve10_L17.so", 217, "Put back movie output height (outsz2560_zve10_v1)"),
        "L19": meta("libJit_zve10_L19.so", 219, "Apply encoder/muxer 3840x2560 tables (ogfile2560_zve10_v1: 20 av + 40 lm sites)"),
        "L20": meta("libJit_zve10_L20.so", 220, "Put back encoder/muxer 3840x2560 tables (ogfile2560_zve10_v1)"),
    },
}
(kit / "manifest.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf8", newline="\n")
print("Wrote", kit / "manifest.json")
PYEOF
fi
