# Cinema Unlock Read-Only Probe Guide (`cineprobe`)

This guide explains how to run the **100% read-only `CT6` Cinema Unlock Probe (`cineprobe`)** on supported bodies (**ILME-FX3 7.02**, **ZV-E1 2.02**, **ILCE-7SM3 5.01**) to map the exact live runtime `.bss` offsets, coprocessor shadow pages, `.text` / `.rodata` string cross-references, and `.rela.dyn` cave guard bytes needed for **Shutter Angle** and **Cine EI / Dual Base ISO**.

> **Read-only & Gate 2 safety:** `cineprobe` executes at `level 103` (`READ_ONLY`) using read-only `/proc/self/maps`, `/proc/self/mem` (`pread64`), `dladdr`, and `coprocessor` reads. It never calls `write()`, `mprotect()`, or any firmware patcher, and its session verdict always sets `ready: false` so it can never unlock Open-Gate `apply`.

---

## 1. Dry-Run Verification (No Camera Required)

Before connecting any camera over USB, verify the kit pins and simulated transport locally:

```bash
./macos/run_live_terminal.sh cineprobe --body fx3_702 --dry-run
./macos/run_live_terminal.sh cineprobe --body zve1_202 --dry-run
./macos/run_live_terminal.sh cineprobe --body a7s3_501 --dry-run
```

For event-stream dry-run inspection:

```bash
.venv/bin/python -B cli/studio_live_apply.py cineprobe --body fx3_702 --dry-run --simulate-events --json-events
```

---

## 2. Live USB A/B Capture Protocol

Each run boots the camera into USB Mass Storage / Service mode, uploads the read-only `cineprobe` helper into RAM, writes `sessions/camera_private/CT6_<timestamp>_<body_short>_.../readcheck_result.txt`, and prints the exact path at completion.

### A. Sony FX3 (`fx3_702`, firmware `7.02`) — Retail Reference Truth

Because FX3 `7.02` natively includes both **Shutter Angle** and **Cine EI**, capturing two runs isolates every `.bss`, HAITA, `xref_ram`, and coprocessor `shadow`/`context` word controlled by those two modes.

1. **Run A (Baseline Speed + Flexible ISO):**
   - Set **23.98p**, **Shutter Speed 1/50**, **Flexible ISO 800** (stock Log shooting, Cine EI off, Shutter Angle off).
   - Connect USB and run:
     ```bash
     ./macos/run_live_terminal.sh cineprobe --body fx3_702
     ```
   - Note the printed `readcheck_result.txt` path as `<FX3_RUN_A>`.
   - Unplug USB, let the camera return to normal shooting mode.

2. **Run B (Shutter Angle + Cine EI Active):**
   - Keep **23.98p**.
   - Switch shutter mode to **Shutter Angle = 180.0 deg**.
   - Switch shooting mode to **Cine EI** with **Base ISO 12800** and **EI 6400**.
   - Connect USB and run:
     ```bash
     ./macos/run_live_terminal.sh cineprobe --body fx3_702
     ```
   - Note the printed `readcheck_result.txt` path as `<FX3_RUN_B>`.

### B. Sony ZV-E1 (`zve1_202`, firmware `2.02`) — Target Body

Run the A/B capture on **ZV-E1 `2.02`** to locate live shutter, ISO/EI, dual-base gain, and `.bss` state offsets alongside `.text` string xrefs (`update_big6_item_iso_ei`, stripped shutter-angle strings, and candidate `.text` cave bytes):

1. **Run A (23.98p Baseline):**
   - Set **23.98p**, **Shutter Speed 1/50**, **ISO 640** (or Flexible ISO 640).
   - Connect USB and run:
     ```bash
     ./macos/run_live_terminal.sh cineprobe --body zve1_202
     ```
   - Note the printed `readcheck_result.txt` path as `<ZVE1_RUN_A>`.
   - Unplug USB, let the camera return to normal shooting mode.

2. **Run B (29.97p High-Base Delta):**
   - Set **29.97p**, **Shutter Speed 1/60**, **ISO 12800**.
   - Connect USB and run:
     ```bash
     ./macos/run_live_terminal.sh cineprobe --body zve1_202
     ```
   - Note the printed `readcheck_result.txt` path as `<ZVE1_RUN_B>`.

### C. Sony a7S III (`a7s3_501`, firmware `5.01`) — Target Body

When an **a7S III `5.01`** body is available, capture an equivalent A/B pair (23.98p 1/50 ISO 640 vs. 29.97p 1/60 ISO 12800) with:

```bash
./macos/run_live_terminal.sh cineprobe --body a7s3_501
```

---

## 3. Offline Inspection & A/B Diffing

Once two captures exist under `sessions/camera_private/`, inspect individual captures or diff any A/B pair with `studio_cli.py`:

```bash
# Summarize appFw.so PHDRs, dynsym hits, rodata string xrefs, and targeted RAM windows
.venv/bin/python -B cli/studio_cli.py inspect-cineprobe <RUN_B_RESULT> --json

# Compute exact u32 diffs across rwpage hashes, xref_ram blocks, targeted windows, and coprocessor pages
.venv/bin/python -B cli/studio_cli.py diff-cineprobe <RUN_A_RESULT> <RUN_B_RESULT> --json
```

`diff-cineprobe` reports:
- `changed_rw_pages`: every non-zero RW `.data`/`.bss` 4 KiB page whose FNV-64 hash changed between Run A and Run B.
- `targeted_window_diffs`: exact little-endian `u32` word deltas (`word_va`, `old_u32`, `new_u32`) in body-specific PRM / coprocessor / HAITA windows.
- `xref_ram_diffs`: exact `u32` word deltas at RW/`.bss` addresses referenced by ADRP+ADD/LDR pairs near discovered `rodata` strings.
- `coprocessor_diffs`: exact `u32` word deltas in coprocessor pages (excluding noisy `kprint_tail` pages, whose newly appended ASCII lines are reported separately in `kprint_new_lines`).
