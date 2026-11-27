#!/usr/bin/env bash
# Build Sony a7C Mark I (ILCE-7C v2.03) volatile-RAM helpers and emit kits/a7c_203/manifest.json.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
STUDIO_ROOT="$(cd "$SRC_DIR/../.." && pwd)"
KIT_DIR="${KIT_OUT_DIR:-$STUDIO_ROOT/kits/a7c_203}"
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
  "$PY" -B "$SRC_DIR/gen_a7c_packs.py"
fi

CC=(
  "$PY" -m ziglang cc
  -target arm-linux-gnueabi -mcpu=cortex_a9 -marm -mfloat-abi=soft
  -std=gnu11 -O1 -Wall -Wextra -Werror
  -fPIC -fvisibility=hidden -shared -nostdlib -ffreestanding
  -fno-stack-protector -fno-builtin -fno-unwind-tables -fno-asynchronous-unwind-tables
  -Wl,-soname,libJit.so -Wl,--no-undefined -Wl,-z,now -g0 -s -Wl,-z,max-page-size=4096
)

"${CC[@]}" -I "$SRC_DIR" -DDUMP=0 -DREADER_NAME='"a7cread"' -DMODEL_NAME='"ILCE-7C"' -DFW_VER='"2.03"' -DEXPECTED_H='"a7c_expected.h"' \
  "$READ_C" -o "$KIT_DIR/libJit_a7c_check.so"
"${CC[@]}" -I "$SRC_DIR" -DDUMP=1 -DREADER_NAME='"a7cread"' -DMODEL_NAME='"ILCE-7C"' -DFW_VER='"2.03"' -DEXPECTED_H='"a7c_expected.h"' \
  "$READ_C" -o "$KIT_DIR/libJit_a7c_dump.so"

"${CC[@]}" -I "$SRC_DIR" -DSTEP_NUM=5  -DIS_APPLY=1 '-DMP_H="expected_mp_ogsq_a7c_v1.h"'      "$WRITE_C" -o "$KIT_DIR/libJit_a7c_L5.so"
"${CC[@]}" -I "$SRC_DIR" -DSTEP_NUM=6  -DIS_APPLY=0 '-DMP_H="expected_mp_ogsq_a7c_v1.h"'      "$WRITE_C" -o "$KIT_DIR/libJit_a7c_L6.so"
"${CC[@]}" -I "$SRC_DIR" -DSTEP_NUM=16 -DIS_APPLY=1 '-DMP_H="expected_mp_outsz2560_a7c_v1.h"' "$WRITE_C" -o "$KIT_DIR/libJit_a7c_L16.so"
"${CC[@]}" -I "$SRC_DIR" -DSTEP_NUM=17 -DIS_APPLY=0 '-DMP_H="expected_mp_outsz2560_a7c_v1.h"' "$WRITE_C" -o "$KIT_DIR/libJit_a7c_L17.so"
"${CC[@]}" -I "$SRC_DIR" -DSTEP_NUM=19 -DIS_APPLY=1 '-DMP_H="expected_mp_ogfile2560_a7c_v1.h"' "$WRITE_C" -o "$KIT_DIR/libJit_a7c_L19.so"
"${CC[@]}" -I "$SRC_DIR" -DSTEP_NUM=20 -DIS_APPLY=0 '-DMP_H="expected_mp_ogfile2560_a7c_v1.h"' "$WRITE_C" -o "$KIT_DIR/libJit_a7c_L20.so"

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
    "body_id": "a7c_203",
    "camera": "ILCE-7C (a7C)",
    "firmware": "2.03",
    "version_txt": "39119_08.2026013101",
    "toolchain": "ziglang 0.13.0 (clang 18.1.6)",
    "persistent_writes": False,
    "device_info": {
        "file": "DeviceInfo.xml",
        "sha256": hashlib.sha256(dev.read_bytes()).hexdigest(),
        "size": dev.stat().st_size,
    },
    "readonly": {
        "check": meta("libJit_a7c_check.so", 101, "Coherent read-only preflight check (a7cread_v1: 51 av + 40 lm sites)"),
        "dump": meta("libJit_a7c_dump.so", 102, "Coherent read-only diagnostic dump + DDR pages (a7cread_v1)"),
    },
    "packs": {
        "core_open_gate": {
            "label": "Core 3:2 Open Gate (Sensor Squeezed 3840x2160)",
            "required": True,
            "apply_steps": ["L5"],
            "putback_steps": ["L6"],
            "summary": "Expands 4K24p split-half sensor readout to full 6000x4000 (3:2) vertically squeezed into standard 3840x2160 XAVC S 4K",
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
        "L5": meta("libJit_a7c_L5.so", 205, "Apply sensor 3:2 full-height readout (ogsq_a7c_v1: 22 sites)"),
        "L6": meta("libJit_a7c_L6.so", 206, "Put back sensor 3:2 full-height readout (ogsq_a7c_v1)"),
        "L16": meta("libJit_a7c_L16.so", 216, "Apply movie output height 2160 -> 2560 (outsz2560_a7c_v1: 9 sites)"),
        "L17": meta("libJit_a7c_L17.so", 217, "Put back movie output height (outsz2560_a7c_v1)"),
        "L19": meta("libJit_a7c_L19.so", 219, "Apply encoder/muxer 3840x2560 tables (ogfile2560_a7c_v1: 20 av + 40 lm sites)"),
        "L20": meta("libJit_a7c_L20.so", 220, "Put back encoder/muxer 3840x2560 tables (ogfile2560_a7c_v1)"),
    },
}
(kit / "manifest.json").write_text(json.dumps(man, indent=2) + "\n", encoding="utf8", newline="\n")
print("Wrote", kit / "manifest.json")
PYEOF
fi
