#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate docs/SUPPORT_MATRIX.md and README.md support tables from docs/support_matrix.json."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MATRIX_JSON = REPO_ROOT / "docs" / "support_matrix.json"
MATRIX_MD = REPO_ROOT / "docs" / "SUPPORT_MATRIX.md"
README_MD = REPO_ROOT / "README.md"
KITS_DIR = REPO_ROOT / "kits"

BEGIN_MARKER = "<!-- BEGIN GENERATED SUPPORT MATRIX -->"
END_MARKER = "<!-- END GENERATED SUPPORT MATRIX -->"

BADGE_MAP = {
    "yes": "✅ Yes",
    "partial": "🟡 Partial",
    "no": "⬜ Pending",
    "blocked": "⛔ Blocked",
    "na": "—",
}

SHORT_BADGE_MAP = {
    "yes": "✅",
    "partial": "🟡",
    "no": "⬜",
    "blocked": "⛔",
    "na": "—",
}

DIM_LABELS = [
    ("byte_verified", "Bytes"),
    ("emulator_verified", "Emu"),
    ("hardware_recorded", "HW Rec"),
    ("clip_xml_validated", "MP4/XML"),
    ("gyroflow_verified", "Gyroflow"),
    ("catalyst_verified", "Catalyst"),
    ("nle_verified", "NLE"),
    ("playback_verified", "Playback"),
    ("long_take_verified", "Soak"),
    ("field_ready", "Field Ready"),
]


def _validate_against_manifests(data: dict[str, Any]) -> None:
    bodies = data.get("bodies", {})
    for bid, meta in bodies.items():
        man_path = KITS_DIR / bid / "manifest.json"
        if not man_path.is_file():
            raise ValueError(f"Missing kit manifest for {bid}: {man_path}")
        man = json.loads(man_path.read_text(encoding="utf8"))
        if man.get("firmware") != meta.get("firmware"):
            raise ValueError(f"{bid}: firmware mismatch {meta.get('firmware')!r} != {man.get('firmware')!r}")
        if man.get("version_txt") != meta.get("version_txt"):
            raise ValueError(f"{bid}: version_txt mismatch {meta.get('version_txt')!r} != {man.get('version_txt')!r}")
        actual_so = len(list((KITS_DIR / bid).glob("*.so")))
        if actual_so != meta.get("helper_count"):
            raise ValueError(f"{bid}: helper_count mismatch {meta.get('helper_count')} != {actual_so}")

    dims = [d for d, _ in DIM_LABELS]
    if data.get("dimensions") != dims:
        raise ValueError(f"dimensions mismatch: {data.get('dimensions')} != {dims}")
    for idx, entry in enumerate(data.get("entries", [])):
        ev = entry.get("evidence", {})
        for dim in dims:
            val = ev.get(dim)
            if val not in BADGE_MAP:
                raise ValueError(f"Entry #{idx} ({entry.get('body_id')} / {entry.get('pack')}): invalid {dim}={val!r}")


def render_support_matrix_md(data: dict[str, Any]) -> str:
    lines: list[str] = [
        "# OpenGate Studio — Public Evidence & Support Matrix",
        "",
        f"> Generated automatically from [`docs/support_matrix.json`](support_matrix.json) by [`scripts/generate_support_matrix.py`](../scripts/generate_support_matrix.py). Current maturity: **`{data['release_maturity']}`**.",
        "",
        "## Evidence Legend",
        "",
        "| Token | Meaning |",
        "|---|---|",
    ]
    for k, desc in data["status_legend"].items():
        lines.append(f"| {BADGE_MAP[k]} | {desc} |")

    lines.extend([
        "",
        "## Recommended vs. Experimental Profiles",
        "",
        "| Profile | Tier | Packs | Frame Rates | Guidance |",
        "|---|---|---|---|---|",
    ])
    for prof in data["profiles"]:
        packs = ", ".join(f"`{p}`" for p in prof["packs"])
        lines.append(f"| **{prof['label']}** | `{prof['tier']}` | {packs} | `{prof['fps']}` | {prof['notes']} |")

    lines.extend([
        "",
        "## Granular Body × Firmware × FPS × Codec × Pack Matrix",
        "",
        "| Body | FW | FPS | Codec | Pack | Tier | "
        + " | ".join(lbl for _, lbl in DIM_LABELS)
        + " | Notes |",
        "|---|---|---|---|---|---|"
        + "|".join("---" for _ in DIM_LABELS)
        + "|---|",
    ])
    for entry in data["entries"]:
        ev = entry["evidence"]
        cells = " | ".join(SHORT_BADGE_MAP[ev[dim]] for dim, _ in DIM_LABELS)
        lines.append(
            f"| `{entry['body_id']}` | `{entry['firmware']}` | `{entry['fps']}` | {entry['codec']} | "
            f"`{entry['pack']}` | `{entry['tier']}` | {cells} | {entry['notes']} |"
        )

    lines.extend([
        "",
        "## Public Conformance Corpus (Call for Untouched Camera Originals)",
        "",
        "Automated media checks currently validate synthetic MP4/XML/`rtmd` fixtures. To promote cells from `⬜ Pending` / `🟡 Partial` to `✅ Yes`, please submit untouched camera original bundles via [Field Test Report](https://github.com/jeromykovatana/opengate-studio/issues/new?template=field-test-report.yml) generated with `cli/studio_cli.py build-report`:",
        "- Locked tripod 16:9 stock vs. 3:2 open-gate `Cxxxx.MP4` + `CxxxxM01.XML`",
        "- Handheld `rtmd` gyro pan/roll clip + Gyroflow / Catalyst Browse stabilization screenshots",
        "- Sustained thermal/card soak clip (`>= 30 min`) + in-camera playback check",
        "",
    ])
    return "\n".join(lines)


def render_readme_block(data: dict[str, Any]) -> str:
    bodies = data["bodies"]
    lines: list[str] = [
        BEGIN_MARKER,
        f"### Supported Bodies & Pinned Firmware (`{data['release_maturity']}`)",
        "",
        "| Camera Body | Model ID | Pinned Firmware | `body_id` | Build ID (`version.txt`) | Pinned Helpers | Evidence Summary |",
        "|---|---|---|---|---|---:|---|",
    ]
    hw_notes = {
        "zve1_202": "Bytes + Emu ✅ · `23.98p` + SteadyShot HW ✅ · `25p`/`29.97p`/Experimental ⬜",
        "a7s3_501": "Bytes + Emu ✅ · `23.98p` HW ✅ · `25p`/`29.97p`/Experimental ⬜",
        "fx3_702": "Bytes + Emu ✅ · `23.98p` + PAL `25p` + 4:3 panel HW ✅ · `29.97p`/Experimental ⬜",
    }
    for bid in ("zve1_202", "a7s3_501", "fx3_702"):
        b = bodies[bid]
        lines.append(
            f"| **{b['camera']}** | `{b['model_id']}` | **`{b['firmware']}`** | `{bid}` | `{b['version_txt']}` | {b['helper_count']} `.so` | {hw_notes[bid]} |"
        )

    lines.extend([
        "",
        "### Granular Evidence Summary (Generated from [`docs/support_matrix.json`](docs/support_matrix.json))",
        "",
        "| Body | FPS | Pack | Tier | Bytes | Emu | HW Rec | MP4/XML | Gyroflow | Catalyst | NLE | Playback | Soak | Field Ready |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ])
    for entry in data["entries"]:
        if entry["tier"] in ("blocked", "external"):
            continue
        ev = entry["evidence"]
        lines.append(
            f"| `{entry['body_id']}` | `{entry['fps']}` | `{entry['pack']}` | `{entry['tier']}` | "
            + " | ".join(SHORT_BADGE_MAP[ev[dim]] for dim, _ in DIM_LABELS)
            + " |"
        )

    lines.extend([
        "",
        "_Legend: ✅ Verified · 🟡 Partial (upstream/architectural evidence; full Studio conformance clip pending) · ⬜ Pending untouched camera original · ⛔ Hardware-blocked · — N/A. See the full matrix including blocked `50p/60p/120p` and `a7iv_602` rows in [docs/SUPPORT_MATRIX.md](docs/SUPPORT_MATRIX.md)._",
        END_MARKER,
    ])
    return "\n".join(lines)


def update_readme_text(readme_text: str, block: str) -> str:
    start = readme_text.find(BEGIN_MARKER)
    end = readme_text.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"README.md missing {BEGIN_MARKER} ... {END_MARKER} markers")
    end += len(END_MARKER)
    return readme_text[:start] + block + readme_text[end:]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="Exit nonzero if docs/SUPPORT_MATRIX.md or README.md is out of date")
    args = ap.parse_args(argv)

    data = json.loads(MATRIX_JSON.read_text(encoding="utf8"))
    _validate_against_manifests(data)

    want_matrix_md = render_support_matrix_md(data)
    want_readme = update_readme_text(README_MD.read_text(encoding="utf8"), render_readme_block(data))

    if args.check:
        stale: list[str] = []
        if not MATRIX_MD.is_file() or MATRIX_MD.read_text(encoding="utf8") != want_matrix_md:
            stale.append(str(MATRIX_MD.relative_to(REPO_ROOT)))
        if README_MD.read_text(encoding="utf8") != want_readme:
            stale.append(str(README_MD.relative_to(REPO_ROOT)))
        if stale:
            print(f"SUPPORT MATRIX STALE: run python3 scripts/generate_support_matrix.py (out of date: {', '.join(stale)})", file=sys.stderr)
            return 1
        print("SUPPORT MATRIX OK: docs/SUPPORT_MATRIX.md and README.md match docs/support_matrix.json")
        return 0

    MATRIX_MD.write_bytes(want_matrix_md.encode("utf8"))
    README_MD.write_bytes(want_readme.encode("utf8"))
    print("UPDATED: docs/SUPPORT_MATRIX.md and README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
