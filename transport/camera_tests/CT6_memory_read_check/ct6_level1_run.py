"""CT6: send the level 1 read-check helper, remove it again, fetch its result. NOT A READ-ONLY TEST.

This is the only camera script in the map that writes a file to the camera and makes the camera run code that
did not come from Sony. It needs the owner's explicit go-ahead for this run (CAMERA_REQUESTS.md, backlog B2).
What it changes on the camera, complete:
  - writes one file, /tmp/jiritsu/libJit.so, on the service partition nflasha6 (flash), and removes it again;
  - the camera loads that file once (its own file-write command does this), which runs the helper's constructor
    in the service process. The helper reads /proc and /sys files and creates /tmp_wbshd/readcheck_result.txt
    (RAM disk; gone at power off). See README.md and helper/readcheck.c.
No setting is written, no firmware file, no coprocessor command.

Camera: USB Connection Mode = Mass Storage, as for CT1 stage 2 and CT5; same libusb-win32 drivers.

  python -I -B ct6_level1_run.py --dry-run          list what would be sent (simulated camera)
  python -I -B ct6_level1_run.py --selftest         the flow, the stop rules and the guard against a simulated camera
  python -I -B ct6_level1_run.py --go --firmware-shown 6.02 --library-sha256 <the 64 hex digits in README.md>
  python -I -B ct6_level1_run.py --remove-only --go --firmware-shown 6.02 --library-sha256 <same>
Add --level 2 to any of these for the level 2 build (level 1 plus three read-only looks at av-cam.bin in kernel memory),
or --level 3 for the level 3 build (level 1 plus twelve read-only transfers from coprocessor memory; README.md).
--level 5 WRITES the test change (14 sites) and --level 6 puts the stock bytes back; a cold boot also undoes it. See README.md and the plan page.
--level 9 is read-only and touches the main processor only: the first 2 KB of each file in /log and the 256 KB kernel log buffer.
--level 10 is read-only: 64 transfers from coprocessor memory, its kprint log (0xe0000, 128 KB, kept across a restart without power loss)
and its boot-time log (0xc0000, 128 KB), saved as cp_kprint.bin and cp_boottime.bin in the private session folder.
--level 12 is read-only: about 90 transfers from coprocessor memory, the state of its memory manager (reference/dmm_memory_manager.md): the page of
its pointers, its copies of the unit and group records, the camera core's write-buffer records and movie size table, its workspace (open handles, unit
objects, scene) and its command log. Saved as dmm_<name>_<address>.bin and decoded into dmm_decoded.json in the private session folder.
--level 13 WRITES four words of the coprocessor's memory-manager tables (a taller raw write buffer: modding/DMMWB_V1.md) and --level 14 puts the
file's words back; both need --design dmmwb4080_v1 or dmmwb4688_v1. Nothing is written unless no unit made from the present records exists, the
records are as in DmmCfg.bin and the new size fits. A cold boot also undoes it.
--level 27 WRITES (stage V4, modding/VCD_V4_DESIGN.md): the three hello_v1 boot stubs into the codec's program area at 0x43c000000, av-cam's
own clock-on store by store (F782), the codec CPUs released for 0.3 s, av-cam's clock-off, every byte put back. Needs the state of requests 35/37
(cold boot, a short recording, USB on movie); refuses to write anything otherwise. A cold boot undoes anything left over.
--level 26 is read-only and touches the main processor only: the VCD program area read as plain memory at 0x400000000 + the word av-cam
stores when it boots the codec (F780): the three boot stubs, the SPU code start, the log head and the hello_v1 record area. No codec register.
--level 22 is read-only and touches the main processor only: the VCD codec's state (modding/VCD_HELLO_WORLD_PLAN.md stage V2). The clock word and
the clock/reset block first; only if the codec is clocked, six registers of its window (never the interrupt status) and four small spans of its program
area. The verdict is CODEC OFF, CODEC ON, RUNNING, or CODEC ON with something to look at. Nothing is written.
--level 18 is read-only and touches the main processor only: what each site of an encoder-side design holds now (--design ogfile2560_hs_v1 or
ogfile2560_s_v1; modding/OG4K_FILE_SIDE.md), in the kernel's copy of av-cam.bin (one read-only mapping of /dev/mem) and in libmpr.so where the camera's
own process has it mapped. Each site is reported as stock, target or other; the verdict is READY, APPLIED or NOT READY. Nothing is written.
--level 19 WRITES MAIN-PROCESSOR MEMORY: the sites of --design ogfile2560_hs_v1, in the kernel's copy of av-cam.bin (a read-write mapping of /dev/mem,
each write checked against the kernel's own view) and in libmpr.so in the camera's own process (through /proc/self/mem). --level 20 puts the stock
bytes back. Nothing is written unless every guard is as in the file and every site holds one of the two sets of bytes; on a failure everything the
run wrote is put back. A cold boot also undoes it.
--level 8 is read-only: level 7, then what each of the 14 sites holds and five pieces of the coprocessor's working state.
--level 7 is read-only: it follows three pointers in coprocessor memory and copies out the stored drive-parameter records of two modes.
--level 4 is different in kind: it WRITES 64 bytes into unused padding in coprocessor memory (0xf31f00), reads them back and writes zeros back.
--design fhband_v1 with --level 5, 6 or 8: the band-crop test (modding/designs/fhband_v1.json, full-height read-out with the stock 16:9 picture)
in place of og4k_data_v1. Same helper source and the same 13 sites plus the stored record, with that design's record bytes; its level 8
also copies out the sensor register shadow (register 0x01, the sensor's own mode: 16 stock full-frame 4K, 2 full height).

Order in the service session (nothing is retried; the stop request is always sent):
  1. read DeviceInfo.xml; it must equal the 6.02 file (known answer), else stop
  2. /tmp/jiritsu/libJit.so must not exist, else stop (a file that is there is never overwritten)
  3. /tmp_wbshd/readcheck_result.txt must not exist, else stop (the helper would do nothing)
  4. /tmp/jbusy must not exist, else stop (the camera would refuse the library)
  5. select /tmp/jiritsu/libJit.so and send the library: the one file pinned by SHA-256 below, nothing else
  6. whatever step 5 returned: delete /tmp/jiritsu/libJit.so, then read it back and expect "no such file"
  7. read /tmp_wbshd/readcheck_result.txt and save it outside the map (camera_private)
--remove-only does 1, then 6 if a library with the pinned hash is there (for a run that was cut off after 5).
--clear-result SHA256 (with --go and the rest): at step 3, if a result file is there and its content has that SHA-256 (that is, it is a
result this PC has already saved), it is deleted and the run goes on. For a second run without a cold boot in between.
With --clear-only it does 1, deletes that file under the same condition, and sends no library.

Where the packets come from (all read in libJiritsu.so 6.02, see README.md "The service commands"):
  select path  0x1001/0x400f  body 00 + path                 as CT1 and CT5 sent it on this camera
  read         0x1001/0x4011  body 00 ff 00                  as CT1 and CT5 sent it on this camera
  write        0x1001/0x4010  body 00 ff 00 + file           adj_cmd_set_file2 0x983c; body as the Erlla client sends it
  delete       0x1001/0x4012  body 00 ff                     cmd_file_delete2 0xa5b8; body as the Erlla client sends it
The four codes are the ones libsencore.so's routing table registers for these commands (JIRITSU_SET_FILE_PATH,
_SET_FILE2, _GET_FILE2, _FILE_DELETE2). Never sent to this camera before a first run: the write and the delete.
"""
import argparse
import os
import posixpath
import re
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "CT1_usb_first_contact"))
sys.path.insert(0, str(HERE / "helper"))
import ct1_common as c

PRIVATE_ROOT = Path(os.environ.get("OPENGATE_CAMERA_PRIVATE") or (c.REPO / "sessions" / "camera_private"))

# level -> (file, SHA-256): the builds inspected by check_built.py and run by emu_built.py. --level picks one; main() sets the three names below.
LIBS = {1: ("libJit_level1.so", "70b2695e917a19e05ca15f674f1260dab6e19f479bb963a697ea510eec3beeec"),
        2: ("libJit_level2.so", "2e1b083463392604af3f33a0bb84237ebeecc5bc19a6741c90509ef7fcf1f51f"),
        3: ("libJit_level3.so", "d6993559673619795e52b07fbf0c842dcfc1c102f0cd1e7d65cc328452e1bbd4"),
        4: ("libJit_level4.so", "8a373006706bfddc0d067b020dc35bad09c6683a61ff124da36dd2cc568e66e1"),   # level 4 WRITES 64 bytes to coprocessor memory and restores them
        # levels 5 and 6 WRITE the test change (13 sites of og4k_data_v1 and 24 bytes of the stored drive-parameter record) and put it back
        5: ("libJit_level5.so", "8bfb946009ef166dc7990cd10a86ad5bc776217389a4ca9f1b3fcc7a3aa0ecf4"),
        6: ("libJit_level6.so", "1020aaaee7f20ca53d51c25b9b8e7fa72670169bc8e1318d7becc08c355250a2"),
        7: ("libJit_level7.so", "0c68b776d0cb860675d1e53a0c297f00d50747f22edc57a46ac0423513647226"),   # level 7 is read-only: the stored drive-parameter records
        8: ("libJit_level8.so", "81c578a2ecb147aca119df5cb9835dd79c05cd5cd19487d5daa9300ae3bf06ac"),   # level 8 is read-only: level 7 plus what the 14 sites hold and the working state
        9: ("libJit_level9.so", "02033967cc92ad97d4d7a744ae2c0b260327ce2ad1413aa77a6bd8246a35fef6"),   # level 9 is read-only, main processor only: /log and the kernel log buffer
        10: ("libJit_level10.so", "2ca49ecf301e0c18ef2ed401ced681fca17c472d193097d6f618c158862b2f90"),  # level 10 is read-only: the coprocessor's kprint and boot-time logs
        # level 12 is read-only: the state of the coprocessor's memory manager (there is no level 11 build)
        12: ("libJit_level12.so", "0b5f6ad293a693834019498d29ab873bbf7f7d6f697cb7b27cd37ff18eb96a28"),
        # level 15 is read-only: the movie output state (output records with their format code, size table, resize state, the memory id table; F684)
        15: ("libJit_level15.so", "5917c00c4909f6324e62c2526ac1635c0c58bc1055fe31df3b5e276653f0aba2"),
        # level 21 is read-only: the raw ports' state, the encoding type each RDC port object last had set (level 15's code, its own ranges)
        21: ("libJit_level21.so", "50fe0a917cce83e9503cf3813fc9f33fb618a55b6a7a2732c0908b38028e085f"),
        # level 28 is read-only: the frame widgets' state (the model rings cpActAfWindow and cpActTrackingFrame read, their rectangle tables, the
        # display's fit-word page; F966, F967; level 15's code, its own ranges; build/frame_state.py decodes it)
        28: ("libJit_level28.so", "d0b0735cd888df6ca0766732b620ca6d884b93486de96842854e67d509eecdcd"),
        # level 22 is read-only, main processor only: the VCD codec's clock word, its window registers and its program area (stage V2)
        22: ("libJit_level22.so", "ae7c5d2018a500ffbc1b157ecba8a6070d0ecb0f2a285d811f6b8bb29091c10d"),
        # level 26 is read-only, main processor only: the VCD program area as plain memory (F780), before any code of ours runs there
        26: ("libJit_level26.so", "ebc16c4fa6e2bf9ac10c4b862565363a6d34cdfc0b7748e25950a096dce7dbe6"),
        # level 27 WRITES: hello_v1 run on the VCD codec CPUs (stage V4); everything written is put back
        27: ("libJit_level27_hello_v1.so", "706285a5af410115ad69f5b7ef9933341341c85c768744d8565dcb4d9346c69b")}
RECORDS = HERE.parent.parent / "evidence" / "pipeline" / "og4k_drvparam_records_emu.json"     # the emulated stock and design records of mode 0x8c0
# --design: another design's builds of levels 5, 6 and 8 (helper/gen_expected.py --design, build commands in README.md). Checked by
# check_built.py and emu_built.py with CT6_DESIGN set to the design's name.
DESIGN_LIBS = {"fhband_v1": {5: ("libJit_level5_fhband_v1.so", "982d2ea9d8916246a171c204004715a6cd6a080c2e97a509ad2a0157b9a78ef1"),
                             6: ("libJit_level6_fhband_v1.so", "87df78823088ad546e6243025840fece07745fca21a4500b45c8a4a6fbf1328e"),
                             8: ("libJit_level8_fhband_v1.so", "51c7fbc0120c33805ebe5a17e70bd6d08546f4032ff53b1ff5c7feaf12fe7d9b")},
               # ogsq_v1: 3:2 full-height open gate, squeezed into the stock 4K picture (modding/OGSQ_V1.md)
               "ogsq_v1": {5: ("libJit_level5_ogsq_v1.so", "81e95f87df890a72f899bc74c32ac296495116dbdbea2a5e24e33c2a49b99559"),
                           6: ("libJit_level6_ogsq_v1.so", "a8c04568e3cf551df7f137f5b7fe0abf70398d1d77b401c5e0dcfc5d37a8f87e"),
                           8: ("libJit_level8_ogsq_v1.so", "a87a4c2a777362213e8d771c2bef9170148e8c924d94102e0c3e476cde895e14")},
               # the stage-height bracket (build/build_fhstage.py, F663): a 4080-row and a 4112-row first stage, bottom-aligned, stock after the scaler
               "fhs4080_v1": {5: ("libJit_level5_fhs4080_v1.so", "51f965e59fc90dfff458283b2672f1c9a4649642a6d928ea2591b7817a40bea0"),
                              6: ("libJit_level6_fhs4080_v1.so", "06d22ac563eaa1137a5cd02c0b7953f1fb1e33ea20c63848b7dcf85a31d40600"),
                              8: ("libJit_level8_fhs4080_v1.so", "98812b36e08445f5d5eea1e331ce34afbc8e75a78d54993dc38acf2e03f4cba5")},
               # rebuilt 2026-11-17 with the corrected rule for the four stage-height fields (F664); never run with the earlier build
               "fhs4112_v1": {5: ("libJit_level5_fhs4112_v1.so", "f14c560db32a2b899109a37eb76ae180783e1c837a4d6bb530739f2a4c043335"),
                              6: ("libJit_level6_fhs4112_v1.so", "34d666cdf3b187e8b2419aa47c2af6c295f4b6372344cae4bc63c3c18dae338c"),
                              8: ("libJit_level8_fhs4112_v1.so", "7649ac2158f53207f1d0546d621ebf48da1b7d4e8ad5158cb90d85bb4ae9a080")},
               # F664: the four stage-height fields (+0xb1c, +0xb40, +0xb48, +0xb58) as stage height + 28 (+27); og_build's model gave them 6 rows too many
               "ogsq_v2": {5: ("libJit_level5_ogsq_v2.so", "4439c6b69b97c96db394154c73671c201d9b658221f28481cb852b49d38c6a43"),
                           6: ("libJit_level6_ogsq_v2.so", "b055e2837e20f67c555da5a5d430e610de8f5ebd86d70cff00dd105ccab248c6"),
                           8: ("libJit_level8_ogsq_v2.so", "dbe99733ba1a891b954f6a666090b948c0fb0e4c17b2d06f3dd0ed233f0cdb2b")},
               # F681: ogsq_v2 plus the vertical sampling ratio 27/32 in the stored record (+6, +7), so that the resize fit keeps the whole
               # 3:2 window and the picture comes out squeezed (26 record bytes where the others have 24). Goes with level 13 dmmwb4688_v1.
               # ogh2560_v1: ogsq_v3 with the first-stage scaler giving 4336x2560 instead of 4336x2438 (stock widths and seam): real 2,560 rows for the
               # 3840x2560 file, and a test of a taller picture after the first scaler without og4k_data_v1's six-row error (build/build_fhpost.py, F711)
               # ogw5760_v1: ogsq_v3 with the first-stage scaler giving 5760x2438: halves 2924/2892 wide, wider than any stock mode (F711)
               "ogw5760_v1": {5: ("libJit_level5_ogw5760_v1.so", "bc38d0bb851a25dc3be16e103d0f491739fe0161951dea92434116ea2bf6ffdd"),
                              6: ("libJit_level6_ogw5760_v1.so", "9f3933363f0bc759c0e04c9a46484ca6e38490462a6c5f42a1c0b4ca315ed35d"),
                              8: ("libJit_level8_ogw5760_v1.so", "98400f79ea611f96308c83bf8334df19c731e60f139889aeacea4496583648eb")},
               # half-width bracket after F793/F795/F797: first scaler 4640x2438 (halves 2364/2332, the FX30's width) and 5152x2438 (2620/2588)
               "ogw4640_v1": {5: ("libJit_level5_ogw4640_v1.so", "db09829e8bbbe657413ea63827be73b588c4cbfe3c0b4a9128cbeba5ea691eab"),
                              6: ("libJit_level6_ogw4640_v1.so", "4153c33a6785593248ac48c99733c73fbdc6d5b0fdc6480dbfd8063bc18f656f"),
                              8: ("libJit_level8_ogw4640_v1.so", "e935a97bf954b5512e2de2465e34fb78aca9fe2f4b2727568e95860b797ede30")},
               # ogw4640_v2: ogw4640_v1 with per-half history line sizes 584/576 (no 8-byte overlap of the two halves' history writes, F801)
               "ogw4640_v2": {5: ("libJit_level5_ogw4640_v2.so", "82e5a2080413c2b7c2a60a65a3ba3d982e9ba8eceb689963f84f7f2f51a4985b"),
                              6: ("libJit_level6_ogw4640_v2.so", "8bbe5b43795225c9d60b1ce5e0d2ad29d10b0c7211b649d775690b16d54fd1cd"),
                              8: ("libJit_level8_ogw4640_v2.so", "7c4bc1f290e98dc2fd9e8ad1eb6408aa339a0429b5e1008027a63c5f36a5d301")},
               "ogw5152_v1": {5: ("libJit_level5_ogw5152_v1.so", "d4bf87907122933816e456221ba913a401dc3d915aff3cef07291c07ef0895e3"),
                              6: ("libJit_level6_ogw5152_v1.so", "abb6acb4bc06dabe4a049b7bd762e9cd88c8e54f7627495f346d94f38562490e"),
                              8: ("libJit_level8_ogw5152_v1.so", "7fd9e863c05bd4fb836da6f41d61ef302a7e257f56cb545b49813a205f5e2b2a")},
               # 2026-11-20, build/build_fhnative.py (F900-F902): the same Lrc pictures with the firmware planner's own column geometry and the
               # stock row rule. Unlike the designs above they break none of the rules of build/lint_split_record.py (85 of 85 stock pairs).
               # ogw4640n_v1 4640x2438 (halves 2364/2332, pad 8); ogw5760n_v1 5760x2438 (2912/2912, pad 10); og57n_v1 5760x3840 (rows padded 6).
               "ogw4640n_v1": {5: ("libJit_level5_ogw4640n_v1.so", "c7837e773e57b1e1c542aa5fa84303bacc79b8df50119bfd45626ea8c746acc0"),
                               6: ("libJit_level6_ogw4640n_v1.so", "6e505668ef89649d7fa8dd8b0c56e988d0fffb355ecc96b1e450787195d11e87"),
                               8: ("libJit_level8_ogw4640n_v1.so", "471a43bbe700cca65cd51c25d0579f226466ecabf12e180fbaf3996fff2af614")},
               "ogw5760n_v1": {5: ("libJit_level5_ogw5760n_v1.so", "6d6afa9704d72834b1e6b612fe3665eef35162b07beb48d9bfca4affd7c8bb0c"),
                               6: ("libJit_level6_ogw5760n_v1.so", "ed22efb822e5355b73a80865d32a6fd181eb66cee2724648deb7a62ca0a07b33"),
                               8: ("libJit_level8_ogw5760n_v1.so", "6e9d648fefd006b00befe994efe5b9eca4960b59b9a46a93767f1396ccff00da")},
               "og57n_v1": {5: ("libJit_level5_og57n_v1.so", "2ad88f667330657007d7666a0d88c651d77a7d9f6487b39c88640e85aac1f7b4"),
                            6: ("libJit_level6_og57n_v1.so", "5245ada6ca32ff2065fbed8cc828d40c2180518e78c900dbfeaa2b971dfd51f5"),
                            8: ("libJit_level8_og57n_v1.so", "dc3194e69586be4f5ed562900048f3bcf324e5bd8783c6e4c82a62cd493ab465")},
               # 2026-11-20, the anamorphic-native 2.4:1 state (a 3:2 sensor picture through a 1.6x lens, stored with square pixels; file 6912x2880).
               # ogan7008_v1: first scaler 7008x2920, one to one across (step 4096) and 1.6 down; halves 3552/3520 x 2928; the second scaler reduces
               # 1.4% to 6912x2880. ogan6912_v1: first scaler 6912x2880 directly (halves 3488/3488 x 2888), second one to one. build_fhnative.py.
               "ogan7008_v1": {5: ("libJit_level5_ogan7008_v1.so", "1a38d659b36173dfdbc8f064de324dfde68f0b21d13bdc62919f0e023be974a8"),
                               6: ("libJit_level6_ogan7008_v1.so", "05575e1713af106652152945f7f63c3897213f2635fe8effb3aea3631ff16425"),
                               8: ("libJit_level8_ogan7008_v1.so", "c9b57b3e060fda955b442ef06bebea664889f9e6b94b185f4b44baed39e54315")},
               "ogan6912_v1": {5: ("libJit_level5_ogan6912_v1.so", "3788b9dc3f69e14a376dbd1f974487ccac0c18b179e7ad91ebd6ebb01750072c"),
                               6: ("libJit_level6_ogan6912_v1.so", "ab793c3424c3eb69935d8ea7d831c9ecf59b168d073b1cade91a000ff23477e6"),
                               8: ("libJit_level8_ogan6912_v1.so", "2a96fd3342aaa67cb61b019338d43ef8c08c0b514106ee9ad0d48df0190c8937")},
               # og57full_v1: ogsq_v3 with the first-stage scaler giving 5760x3840: the real 5.7K picture (F711)
               "og57full_v1": {5: ("libJit_level5_og57full_v1.so", "6c9f1fa0df4d8d02d17783b0c12853ffd55e39c45454c6a866a312156da496ba"),
                              6: ("libJit_level6_og57full_v1.so", "da3379c74d91e66acc5a56f8e051c275a17f4503d980ebbd22401c88f213e212"),
                              8: ("libJit_level8_og57full_v1.so", "fc9ce2fb6cfa308722a53753065b5b217f6083100846f2d55d6dc84f9ae2accb")},
               "ogh2560_v1": {5: ("libJit_level5_ogh2560_v1.so", "14cf91406f68428e553ce71a627bf930248fd5b132ce9fb889dda409f95d0c8a"),
                              6: ("libJit_level6_ogh2560_v1.so", "0b50a0e9ea27bdcbb0d7cd2115bbf1c8e6bae8c5ee16092e1d3e3e6874ed489e"),
                              8: ("libJit_level8_ogh2560_v1.so", "113851cecc39807d8d8df8ff9cafea16c768883562ac86bb42295d33698eed90")},
               "ogsq_v3": {5: ("libJit_level5_ogsq_v3.so", "527c12d151824a5431dafc46693033ea53add09b96dd59e39aa975139e454446"),
                           6: ("libJit_level6_ogsq_v3.so", "4286cf74b8efab46cc42f51d5a466467d547fd94d1ee58802eacb8e3f7399457"),
                           8: ("libJit_level8_ogsq_v3.so", "f51691c100d0902f5270b76e1f2e072c91b04a602656c2d679a6c9a8ef8de794")},
               # 2026-11-21: the same designs for a camera set to PAL (build/build_pal_records.py). The 13 sites are the same; the stored record's
               # stock and new bytes are those of frame-rate family 1 (input table 0xc98d80), six of the 26 differ from the NTSC ones. The stock
               # bytes equal the record read from the camera on PAL (level 7, 2026-11-21). An NTSC library refuses on a PAL camera and the reverse.
               "ogsq_v3_pal": {5: ("libJit_level5_ogsq_v3_pal.so", "775f6cdad18ea622b1f0440b09d395292510d26791961ac16886cc821fb3c821"),
                               6: ("libJit_level6_ogsq_v3_pal.so", "67d11df3e9530d57b2e86f6adb7fd68b34713e61a611307e4ffa1a1bd837cf90"),
                               8: ("libJit_level8_ogsq_v3_pal.so", "0b0cf33ac57eefb071e8b6b9d9306f918be308f923977ccf7e73c99e42912291")},
               "og57n_v1_pal": {5: ("libJit_level5_og57n_v1_pal.so", "5d1b256ebfa9567cd2aac1ce3b3d9b23369561c4f8b14234bd8152cc50fbd04a"),
                                6: ("libJit_level6_og57n_v1_pal.so", "c266f1847161fac07ebcddb38ef7ffae91a16b77b60544c3eb6897401b28d17c"),
                                8: ("libJit_level8_og57n_v1_pal.so", "7eec2a84659946a30e6c83511273be3b5261a3a56fd32f267ae9811efaec74be")},
               # 2026-11-21: the same two designs moved to drive mode 0x880 (index 9), the mode a camera set to PAL uses for full-frame 4K 25p
               # (build/build_mode880.py; level 8 on the camera read drive mode 0x880 with the PAL state above applied). 13 sites one table row
               # before 0x8c0's, the 0x880 image records 0xbf5ec8 / 0xbf6a80, and the stored record of index 9 with the PAL family's bytes.
               "ogsq880_v1": {5: ("libJit_level5_ogsq880_v1.so", "f7db0d936713a2a41acdfc7746828ea7d0a201b32fc58a166529bbf519620636"),
                              6: ("libJit_level6_ogsq880_v1.so", "b53856345106b9fd67a2871663ce25538721139f6e034a22a6d9d07118901b8a"),
                              8: ("libJit_level8_ogsq880_v1.so", "94bb67c72d26e423170f7dbae4150c40b0538a15f85f339f2b7a04b0916e775b")},
               "og57n880_v1": {5: ("libJit_level5_og57n880_v1.so", "e2908a73cecab247d5d37be5d757beeb9a1c30fcf60f55aa0a481b93af527760"),
                               6: ("libJit_level6_og57n880_v1.so", "87f58556213a04d6bfa28865ddaa891b6b14e58e2229d46dee53009a7bcfe14e"),
                               8: ("libJit_level8_og57n880_v1.so", "78c0f1a1d1cdb16394f489fda56fb44a57e166a7bb4acf763360874b3382db6c")},
               # T3: the stock 3958-row stage and stock scaler, moved to the bottom of the full-height frame (ends on the same row as the failures)
               "fhs3958b_v1": {5: ("libJit_level5_fhs3958b_v1.so", "604ee7454e5841775853f955692a534facf8ef0bc549b4822dfd161818e7e8e8"),
                               6: ("libJit_level6_fhs3958b_v1.so", "f36006754d58a5603618bb91ef13b05be4a77512daac83564ecddeb4c76e7174"),
                               8: ("libJit_level8_fhs3958b_v1.so", "e9da317543e24b0afd5683d082aefcae80379789cc43a0a21263aa3301fc6dc2")},
               # request 19 (F666): H = fhs4080_v2 with the scaler cropped back to 3942 rows (stock vertical step); S = T3 with the scaler using 3700 rows
               "fhs4080c_v1": {5: ("libJit_level5_fhs4080c_v1.so", "580c7bea0a8437fce80d9d9896ee50ac7c4eb9d15d5380a581c5dd679c0a9275"),
                               6: ("libJit_level6_fhs4080c_v1.so", "5f59a62ebc5cae5631c925dede3955527ec4a393f53891cd2034a85258973e36"),
                               8: ("libJit_level8_fhs4080c_v1.so", "c35f725ad02e165459f572192498493fb419e253fb0a2f9e43ceaf6b2e1522f8")},
               "fhs3958s_v1": {5: ("libJit_level5_fhs3958s_v1.so", "7dcb10b52531dc72f07a000725d163b4050e257578a546d3cc2a8125e981a14e"),
                               6: ("libJit_level6_fhs3958s_v1.so", "f09176407b353854e329204853e78ed70deed7e4275ee53e95ec42d1b0f04aa6"),
                               8: ("libJit_level8_fhs3958s_v1.so", "2b84c86034c7387e2d2bdc68c8fd9ed7e506b52e326a626f275d42c3c0ed48b1")},
               # levels 13 (apply) and 14 (put back): four words of the memory manager's unit records, so that the raw write buffer (memory id 0x43e)
               # holds 4,080 or 4,688 rows (build/build_dmm_sites.py, helper/gen_expected.py --dmm; F674). They go with a level 5 design, not instead of one.
               "dmmwb4080_v1": {13: ("libJit_level13_dmmwb4080_v1.so", "f8d738d334ebd54979fa37d347babdf29a683251c5afb7b3ec929f4eda5b5f23"),
                                14: ("libJit_level14_dmmwb4080_v1.so", "cac7b3c326093aea39888bab62561aa7a4a446120cbea169e51f922d1f555ffe")},
               "dmmwb4688_v1": {13: ("libJit_level13_dmmwb4688_v1.so", "938f9baf7d9d77a4163cc3568341614e1023dea1a4c4210bc85975ae437a6009"),
                                14: ("libJit_level14_dmmwb4688_v1.so", "ae578b454c255bfb3219824f2a1d87c3083f52310846eec9d2fb1de71ea65147")},
               # levels 16 (apply) and 17 (put back): words of a RAM table (build/build_ram_words.py, helper/gen_expected.py --words). outsz2560_v1 is the
               # output size of the stock 4K size class in the movie size table, 3840x2160 to 3840x2560 (F684, F687). It goes on top of the baseline.
               "outsz2560_v1": {16: ("libJit_level16_outsz2560_v1.so", "af755e0b5dc17586565947f49cc4be839d1cdef6dfd2db739b9123db53ab59d7"),
                                17: ("libJit_level17_outsz2560_v1.so", "7e57634d7198a724495768561348f89f04b062bbccfe11a6db9fc52453e92fea")},
               # og2560e4_v1: outsz2560_v1 and the unit-count setting 0x143c9b8 = 3, four scaler units (a test of the four-unit division at the size that
               # records). og57cp_v1: the coprocessor words of a 5760x3840 output: four scaler units, memory id 0x43f made from the row of an id that
               # cannot be opened, with the key list of id 0x608 (units of 27,864,320 bytes), and the output size (F701, request 30).
               "og2560e4_v1": {16: ("libJit_level16_og2560e4_v1.so", "919a5e8f68f8e15a41ed885db774ff5df00b9ba66dd4499c072940e44735c1a4"),
                               17: ("libJit_level17_og2560e4_v1.so", "7ccbbe31f3ae39f8952cfe160f725c47a434fa89ae0ab97a9c765b9cf105e74c")},
               "og57cp_v1": {16: ("libJit_level16_og57cp_v1.so", "d33f392b96630640106871cf2b77eead151fd75b63c58ea5a13acab3ea1b33c7"),
                             17: ("libJit_level17_og57cp_v1.so", "3cfe8b8f0319516496c8e3ca4f8d9ca06a5fa4ff652cffb5f369cf5606706978")},
               # og57cp_v2 = v1 plus the size table's own memory id for the output, 0x143c7c0, 0x2d9 to 0x43f. With v1 on the camera the 27.6 MB
               # planes went into units of 13,271,040 bytes: the sequence takes its output buffer id from the table, not from the size (F704).
               # og57cp_v3 = v2 with id 0x43f on key 0x5f2 (30.8 MB, three to a 0x39 block) instead of 0x6a3, whose units take a 0x2f block that the
               # recording needs for id 0x60c (F707, F708; the firmware's allocator: evidence/hardware/dmm_server_id_0x43f_keys_compared.json).
               "og57cp_v3": {16: ("libJit_level16_og57cp_v3.so", "eb14cbfff320dd8b23e5fd70326a115fc23350029e7dbe187b9979301dd6d599"),
                             17: ("libJit_level17_og57cp_v3.so", "5cf92e5debd2400bc9440e5859436394f8fccbc90c290a1a8e9f75a407fe8a32")},
               # ogan69cp_v1 (2026-11-20) = og57cp_v3 with the output size 6912x2880 (2.4:1) instead of 5760x3840: the same four units, id 0x43f and
               # 30.8 MB units (the plane is smaller: 24.9 MB). 7008 wide is refused by the four-unit division (multiples of 128 only).
               "ogan69cp_v1": {16: ("libJit_level16_ogan69cp_v1.so", "54f3225321135c6553fa273929502673237357fea9bf4c2c6c52103c61739eb8"),
                               17: ("libJit_level17_ogan69cp_v1.so", "e22bac5119a433b6af51b33003966e405d4d4b13f805f8daf7b4dc63e7bb56a9")},
               "og57cp_v2": {16: ("libJit_level16_og57cp_v2.so", "276666af4d51f5bc9591106908f747bfa3d384021ba59c9aaa52511847c0af7f"),
                             17: ("libJit_level17_og57cp_v2.so", "328670b4352a08f7eec7828297b6afeb3307a354a9b2844ecfb4150d9b21fd95")},
               # lcdfill_v1: the rear screen at 3:2 in movie mode. One word of VDF's fit-mode table in the loaded image (0x1e4bcc, 16:9 picture on the
               # 3:2 panel: 3 letterbox to 0 fill), so the squeezed live view of ogsq_v3 is stretched x32/27 over the whole panel (modding/LCD32_V1.md).
               # lcdratio21_v1 / lcdratio24_v1: on top of lcdfill_v1, letterbox again with VDF's ratio constants (FUN_001e4da0 0x1e4dc4, 0x1e4dc8) set
               # to 1/2 or 5/12: the rear screen shows the squeezed live view at 2:1 or 2.4:1 (1.33x / 1.6x anamorphic preview). Level 17 = back to 3:2.
               "lcdratio21_v1": {16: ("libJit_level16_lcdratio21_v1.so", "c20d022f30f8426049bc5855c2db37a341f26a1ee3548f5b186844b938684299"),
                                 17: ("libJit_level17_lcdratio21_v1.so", "975b425f8f3299123c7bc1de1c8737bef59443e401d27150c491efe1a046ff99")},
               "lcdratio24_v1": {16: ("libJit_level16_lcdratio24_v1.so", "a916fed727a658cddd0ff1759c773a711b12437b1f37885e611502c7a2a0afc0"),
                                 17: ("libJit_level17_lcdratio24_v1.so", "982c4e4a12d72c77ecfe0f72645f5ce0b357aa09c404979ce342871a34fb31ba")},
               # lcdfill_v2 (F966): lcdfill_v1 plus the frame widgets' expected rectangle for a 16:9 picture on the rear panel (three table entries,
               # 0xd7b5a0, 0xd7b618, 0xd7b690: the stock letterbox to the whole panel), so that the focus frames are drawn on the filled screen.
               "lcdfill_v2": {16: ("libJit_level16_lcdfill_v2.so", "1393e38434ac21b2f1050cde5534fb06feed459bd9c837e0d5d69a0a0bd2f22c"),
                              17: ("libJit_level17_lcdfill_v2.so", "468a2a922726da4bd870f4e5a5ba6e5022ef36fc833234f64d3eac124f2dda9f")},
               "lcdfill_v1": {16: ("libJit_level16_lcdfill_v1.so", "1141376a1dd43614a6b9950fd89b7449d292adceaecc254a4561a1f18c4cb57d"),
                              17: ("libJit_level17_lcdfill_v1.so", "1d9d823c49d4dc3c481a98e3ee9fadaeaf3b64dab42df56507326451a4db854c")},
               # level 18 (read-only, main processor only): what the sites of an encoder-side design hold now, in the kernel's copy of av-cam.bin and in
               # libmpr.so in the camera's own process (build/build_ogfile.py, helper/gen_expected.py --mp; F690). It writes nothing but its result file.
               # levels 19 (apply) and 20 (put back) WRITE MAIN-PROCESSOR MEMORY: the sites level 18 reads, av-cam.bin's through a read-write mapping of
               # /dev/mem (no O_SYNC) checked against the kernel's own view, libmpr.so's through /proc/self/mem. Built for the HS design only, whose
               # sites were read on the camera and found stock (request 27, F692).
               "ogfile2560_hs_v1": {18: ("libJit_level18_ogfile2560_hs_v1.so", "87e93b8e7878d100753a7273fbc29e3d2551075f352b74e9368b6c21cac4650d"),
                                    19: ("libJit_level19_ogfile2560_hs_v1.so", "e86a60c88fb3d9317fb3a805823263ebaa2f09105af3f3d8dde4f7b6a9b7f19c"),
                                    20: ("libJit_level20_ogfile2560_hs_v1.so", "f2d96549bf3a6b357b8a413414957116f2b57fb1390497bb2d9bb863fd1ee7f4")},
               "ogfile2560_s_v1": {18: ("libJit_level18_ogfile2560_s_v1.so", "a5feb779e732722bead9115f0be0318cdd2b16de98ff0654fe533a2f2fbe9d60")},
               # the union of the two designs: XAVC HS 4K and XAVC S 4K both at 3840x2560 (build/build_ogfile.py; F699). Level 18 reads its 105 sites,
               # level 19 applies them, level 20 puts the stock bytes back. The HS half is the one that recorded on the camera (F698).
               # lcdcycle_v1 (F850): the C3 'Not set' key steps the rear-screen preview 3:2 -> 2:1 -> 2.4:1 in movie mode. CODE in appFw.so: a cave at
               # 0x50bba60 and two hooked instructions (0x1f06594, 0x35c02fc), written cave first, put back hooks first (MP_LM_ORDERED). Not run.
               # lcdcycle_v2 (F852): v1 with a trigger that emits an event ('Switch Aspect Marker' / 'Exp. Effect Select' / 'Wireless Test Flash',
               # taken over in movie mode only and turned into the ignored 'Not set' event). v1's 'Not set' trigger emits nothing (request 39).
               # lcdcycle_v3: v2 plus the trigger 'Grid Line Type' (EVENT_FUNC_GRID_LINE_TYPE_ON 0x216003e); the A7 IV's movie C3 list offers none of v2's.
               # lcdcycle_v4: the raw C3 key press (EVENT_INPUT_KEY_TACT_CUSTOM3_ON 0x2150006) in movie mode is the trigger, whatever C3 is assigned
               # to; v3's function-event trigger never reaches process_input_event (the classifier makes it later).
               # lcdcycle_v5 (F857): v4's raw-C3 trigger; each press writes the VDF fit word and letterbox constants (3:2 / 2:1 / 2.4:1, F856) into the
               # coprocessor from appFw through libsencore (dlsym), then requests a fresh automatic layout. One hook, no hook 2.
               # lcdcycle_v6 (F966): v5 plus the frame widgets' rectangle, written per preview mode, so the focus frames are drawn in 3:2, 2:1 and 2.4:1.
               "lcdcycle_v6": {18: ("libJit_level18_lcdcycle_v6.so", "05948cf1d879d264bf05edb1a626496683fb8d74b2778de293d8ba4019194da0"),
                               19: ("libJit_level19_lcdcycle_v6.so", "64a67f1f7d541e9946e1084a382884d11b11f17031cc29a746e18e0d1b58fe10"),
                               20: ("libJit_level20_lcdcycle_v6.so", "1fbc9c43ce4e8a053e01f4900bb04bf3c4aea62543ff34d5e63ebea2301fc7ee")},
               "lcdcycle_v5": {18: ("libJit_level18_lcdcycle_v5.so", "3ad5810ffeb6fa954dc5517b9f54802e8029d68f92ef048862c528dc1fb546f4"),
                               19: ("libJit_level19_lcdcycle_v5.so", "590a450de873e70bce6b5a7414183aa46892e71e2afa5ac6b54055380c5d728c"),
                               20: ("libJit_level20_lcdcycle_v5.so", "70e66d2757378d7e2391fcf512f68525a667bcb728c19feebe54afcb267843ec")},
               "lcdcycle_v4": {18: ("libJit_level18_lcdcycle_v4.so", "43105d821d730a784704cf2addbc5e4b076deb15be529787d5cbb64b65ab73f6"),
                               19: ("libJit_level19_lcdcycle_v4.so", "3e392ba3bb161a175212ab5d8db38e3ee0ca30410754f4cc83795afcb78e7478"),
                               20: ("libJit_level20_lcdcycle_v4.so", "bde1ab93de7e2e6523e82f581ea8b546eb16153c326efda00a90bee981bf1e4b")},
               "lcdcycle_v3": {18: ("libJit_level18_lcdcycle_v3.so", "e3eeeaf0d732b793c28c3cb6f5bcf178762b54e5a2eade72042a05edeec00051"),
                               19: ("libJit_level19_lcdcycle_v3.so", "7db8fdaa2f2f3d021d1f8131345a4df14ea929e67659aac1072047c889aadb9a"),
                               20: ("libJit_level20_lcdcycle_v3.so", "40ea3dacba761ef1e6e7696caab89d2ba3bdabd151194879d356c93d721d23e1")},
               "lcdcycle_v2": {18: ("libJit_level18_lcdcycle_v2.so", "a8a6f247bfc5b0fabbf728c7ca8768071a73f75d64fc836e2f2ca41bca3c8a42"),
                               19: ("libJit_level19_lcdcycle_v2.so", "8d082304486b2d55f53e203eb82b82fc9017b9616dc986dcf39371f881055960"),
                               20: ("libJit_level20_lcdcycle_v2.so", "aa03ba24fb1d4f990e782750895fbafa8353f69941f4087082c9c16c6a7c989c")},
               "lcdcycle_v1": {18: ("libJit_level18_lcdcycle_v1.so", "bb003153cb872f29cfb8b011b03da826e7cfc98af11f478bbcfd3ba781f78603"),
                               19: ("libJit_level19_lcdcycle_v1.so", "3664cde6e0a1c419539fa92de977a52cb9d94b3a2af079fef63819e10de3b4a6"),
                               20: ("libJit_level20_lcdcycle_v1.so", "15ec5f0af45259add7a2f87f06a7b76dcd611dcace4516537c6281d2ae913bc4")},
               "ogfile2560_hs_s_v1": {18: ("libJit_level18_ogfile2560_hs_s_v1.so", "b322a716e7ef15267f5ac66e8fae89d29b8869041399baedb97ecd6ae2d00980"),
                                      19: ("libJit_level19_ogfile2560_hs_s_v1.so", "7a354f584b36bc38309f8257cd04784c6d245d3de2ae8e4a96a7b3ca0a21a7a2"),
                                      20: ("libJit_level20_ogfile2560_hs_s_v1.so", "674e5529c3d3e7dfd75be1e395c863637b77182a31e1177da673c98fd43c4c18")},
               # the encoder side of a 5760x3840 file on XAVC HS 4K and XAVC S 4K (build/build_og57.py; F701): both encoder cores, the 4K memory blocks
               # in an order that holds the picture, 29 descriptors and their profiles. 209 sites. Not run on a camera.
               "ogfile57_v1": {18: ("libJit_level18_ogfile57_v1.so", "00b099ed7a787e3a9402b5dd7cfe1c1d81531863ed0c81651f9d38a6b47ca5d3"),
                               19: ("libJit_level19_ogfile57_v1.so", "aa1f318fafe1a71a5286b076c2f4fc274f68f196aeaf9bf8518b4841dd2c5f8a"),
                               20: ("libJit_level20_ogfile57_v1.so", "7f739de98479d67e907286fb771bd048173e22c1896a16947df695fd38899e4c")},
               # ogfile57r300_v1 (2026-11-21; build/build_og57.py --rate300; a test the owner asked for): ogfile57_v1, and in the 11 profiles at 97
               # million or more (the 100M record settings) the three rate fields get the figures of Sony's own dormant 5760x3240 profiles
               # (300, 340, 340 million) and the level byte Level 6.1. 242 sites. Not run on a camera.
               "ogfile57r300_v1": {18: ("libJit_level18_ogfile57r300_v1.so", "7ea1b14d914074136b687bb871e662eb1c4855b9af2d954fa132f6281f6e6613"),
                                   19: ("libJit_level19_ogfile57r300_v1.so", "56f4af121f1b944fb50e94924035af3212b4e041ee3393e39d20d90a08693c75"),
                                   20: ("libJit_level20_ogfile57r300_v1.so", "1a093b909f326695aad2e220df185ddc6815401386c91f00f82fd3c079b8f0c0")},
               # ogfile69_v1 (2026-11-20; build/build_og57.py --raster 6912 2880): the same 209 sites for a 6912x2880 picture (2.4:1): rows for the
               # first core 1440, +0x4c 10368, Level 6. The codec's own calculation asks less memory than for 5760x3840. Not run on a camera.
               "ogfile69_v1": {18: ("libJit_level18_ogfile69_v1.so", "15bccab5d034cabaf90b153c1e288193456a57a9dc1d01c774dbc323633dcdc3"),
                               19: ("libJit_level19_ogfile69_v1.so", "a3a6e068c53bc49adecfb48e55894c5310effdfa8fe0948123c03350165b32e0"),
                               20: ("libJit_level20_ogfile69_v1.so", "4f571c140f127159ff49fafe8905f471d407ba9ad56cb9fe36c584822c7dea75")},
               # ask the encoder for 12-bit (build/build_bd12.py, 2026-11-19): BitDepth code 2 in the profile rows of XAVC HS 4K and XAVC S 4K at
               # 23.98p and in the HEIF still template; 19 one-byte data sites in av-cam.bin, nothing in libmpr.so. Goes on a STOCK camera. Not run.
               "bd12_v1": {18: ("libJit_level18_bd12_v1.so", "3da227d1222ee6c9cee6b2fb67a78c37e50e1d53f948f2c791d6149b61905807"),
                           19: ("libJit_level19_bd12_v1.so", "6538e8977426fe166c794dcb04ebda8576090b777ff4961fed7845ebf705e47f"),
                           20: ("libJit_level20_bd12_v1.so", "537f465daed426ec15d62b1939d48fd689319148288b099912134074e9f796da")},
               # the codec firmware's own 10-bit set-up made 12-bit (build/build_vcd12.py, 2026-11-19): two words in every copy of
               # vcd_firmware_imola2.bin found in DMM region key 0x22 (the shadow av-cam copies over the program area at each codec power-up).
               # Level 23 reads (READY / APPLIED / NOT FOUND), 24 applies, 25 puts back. Goes on a STOCK camera. Not run.
               "vcd12_v1": {23: ("libJit_level23_vcd12_v1.so", "0a6aa8471df950a1c43c8871305ddffc32ec512e144902724264946d213f3b55"),
                            24: ("libJit_level24_vcd12_v1.so", "73a37de4f67072dcb7aa8cd42a01944e2c9b011d31f33702f24499dc93f299d3"),
                            25: ("libJit_level25_vcd12_v1.so", "a401d07cde7593445aba203e1e85d33471eb430b7e355f736f1b5bf3ed9f51ee")},
               "fhs4080_v2": {5: ("libJit_level5_fhs4080_v2.so", "dd7eab5eceb496b457fe9a1fabc24397f5d73c379155686be71ac83bc7d28dc0"),
                              6: ("libJit_level6_fhs4080_v2.so", "8d0df2f806a34f3e499e98848ecf30aa6f5c445303d6439a6636fabdc4551608"),
                              8: ("libJit_level8_fhs4080_v2.so", "39716663b63dc83f4ce0a12f95a34f1b28fdbe04768e8aff771d9fb1e521f3f0")}}
DESIGN = "og4k_data_v1"
# the sensor register shadow a fhband_v1 level 8 copies out (0x1033c40, 0x440 bytes): (offset, register, value in mode 16, value in mode 2)
SHADOW = ((0x3E, "0x01", 16, 2), (0x4E, "0x05", 4, 0), (0x72, "0x0e", 8, 0), (0x7A, "0x10", 41, 0), (0x9E, "0x19", 51, 59))
# level 27 with hello_v2 (stage V5, modding/VCD_V5_PLAN.md): --level 27 --design hello_v2
DESIGN_LIBS["hello_v6"] = {27: ("libJit_level27_hello_v6.so", "ed813ee9e80b34684cc21dd8ca1e52029c682e191546c20fa04669ae20a1a7bf")}   # the first codec hardware job (V5 step 4c)
DESIGN_LIBS["hello_v5"] = {27: ("libJit_level27_hello_v5.so", "e5a3f356bb4a10fee48537fb3c9bd95acf1d9dabcf045a4d2b22379a19274f69")}   # a read-only look at the codec block registers (V5 step 3)
DESIGN_LIBS["hello_v4"] = {27: ("libJit_level27_hello_v4.so", "cef5863220798234df1e5f140930c1443cc360e429bbf003ddff534dc8147d48")}   # the codec CPUs' DRAM bandwidth (V5 step 2)
DESIGN_LIBS["hello_v3"] = {27: ("libJit_level27_hello_v3.so", "0171359dbfb4bd220c073d383c5582b20982235383a35145e23c52cc4a93cd1d")}   # hello_v2 plus the block set-up and progress words
DESIGN_LIBS["hello_v2"] = {27: ("libJit_level27_hello_v2.so", "9852db7f38894360041d7d9b368df34be822013a6ef61f35408813e04579bf58")}
LEVEL = 1
LIB = HERE / "helper" / LIBS[1][0]
LIB_SHA256 = LIBS[1][1]
AV_FILE = "0700_part_image/dev/nflasha3/av-cam.bin"
LM_FILE = "0700_part_image/dev/nflasha15/lib/libmpr.so"
APPFW_FILE = "0700_part_image/dev/nflasha15/lib/appFw.so"
VCD_FILE = "0700_part_image/dev/nflasha15/codec/vcd_firmware_imola2.bin"
CP_FILE = "0700_part_image/dev/nflasha8/cpapp-b.bin"
LIB_MAX = 65520                                    # the Erlla client's bound for one upload packet

KNOWN_PATH = b"../../usr/share/pmbp/DeviceInfo.xml"
KNOWN_FILE = "0700_part_image/dev/nflasha15/share/pmbp/DeviceInfo.xml"
LIB_PATH = b"/tmp/jiritsu/libJit.so"               # must come out as exactly this string, or the camera does not load it
RESULT_PATH = b"../../tmp_wbshd/readcheck_result.txt"
BUSY_PATH = b"../../tmp/jbusy"
PATHS = (KNOWN_PATH, LIB_PATH, RESULT_PATH, BUSY_PATH)

SET_FILE_PATH, GET_FILE2, SET_FILE2, FILE_DELETE2 = 0x400F, 0x4011, 0x4010, 0x4012     # as registered in libsencore.so's routing table
ST_OK, ST_NO_FILE, ST_LOAD_FAILED, ST_BUSY, ST_REMOVE_FAILED = 0, 0x10000006, 0x10000000, 0x10000011, 0x1000000B
STATUS_TEXT = {ST_OK: "ok", ST_NO_FILE: "no such file", ST_LOAD_FAILED: "written, but the camera could not load it",
               ST_BUSY: "refused: /tmp/jbusy exists", ST_REMOVE_FAILED: "remove failed", 0x1000000F: "refused: service partition full",
               0x10000004: "service partition did not mount", 0x10000008: "open for writing failed", 0x10000009: "short write",
               0x10000015: "no transfer buffer", 0x1000001C: "folder create failed", 0x10000201: "request refused as malformed"}


def library():
    data = LIB.read_bytes()
    if c.sha256(data) != LIB_SHA256 or not 0 < len(data) <= LIB_MAX:
        raise SystemExit("%s is not the pinned build (SHA-256 %s, %d bytes). Nothing was sent." % (LIB.name, c.sha256(data), len(data)))
    return data


def rules(lib):
    return {
        (c.PFUNC_ADJUST, 0x1001, SET_FILE_PATH): ("SET_FILE_PATH", lambda p: p[:1] == b"\x00" and p[1:] in PATHS),
        (c.PFUNC_ADJUST, 0x1001, GET_FILE2): ("GET_FILE2", lambda p: p == b"\x00\xff\x00"),
        (c.PFUNC_ADJUST, 0x1001, SET_FILE2): ("SET_FILE2", lambda p: p == b"\x00\xff\x00" + lib and c.sha256(p[3:]) == LIB_SHA256),
        (c.PFUNC_ADJUST, 0x1001, FILE_DELETE2): ("FILE_DELETE2", lambda p: p == b"\x00\xff"),
    }


GUARDS = []                                        # the guard of the current session is the last one


class Guard(c.ServiceGuard):
    """CT1's guard plus the two rules a write needs: only onto the library path, and only once."""

    def __init__(self, device, session, rule_list, lib):
        super().__init__(device, session, rule_list)
        self._big = len(lib) + 7
        self.writes = 0
        self.allow_result_delete = False
        GUARDS.append(self)

    def _send(self, pFunc, data, _oData):
        if len(data) > 0x1000 and len(data) != self._big:
            raise c.GuardRefusal("a %d-byte service packet that is not the pinned library" % len(data))
        device = self._device
        header = struct.pack(c.SENSER_HEADER, len(data), pFunc, device._sequence, 0, 0, 0, 0)
        device.driver.write(header + bytes(data))                      # one write, as the Erlla client does it
        response, out = c.read_service_answer(device.driver, device._sequence, self.session.log)
        device._sequence += 1
        return response, out

    def send(self, pFunc, data, oData=None):
        name = c.classify_service_packet(pFunc, data, self.rules)      # raises before any write
        if name == "FILE_DELETE2" and self._path_set == RESULT_PATH and self.allow_result_delete:
            self.allow_result_delete = False                           # one delete of the result file, after its content was checked (--clear-result)
            return super().send(pFunc, data, oData)
        if name in ("SET_FILE2", "FILE_DELETE2") and self._path_set != LIB_PATH:
            raise c.GuardRefusal("%s when the path selected just before is not %s" % (name, LIB_PATH.decode()))
        if name == "SET_FILE2":
            if self.writes:
                raise c.GuardRefusal("a second file write in one session")
            self.writes += 1
        return super().send(pFunc, data, oData)


def service_session(session, inner, body, lib):
    """As CT1's service_session, with this test's guard. The stop request is always sent."""
    from pmca.usb.sony import SonySenserAuthDevice, SonySenserCamera, SonySenserDevice
    driver = c.GuardedDriver(inner, session, "senser")
    session.results["service_usb_id"] = "%04x:%04x" % driver.getId()
    auth = SonySenserAuthDevice(driver)
    session.say("Authenticating")
    auth.start()
    try:
        auth.authenticate()
        device = SonySenserDevice(driver)
        Guard(device, session, rules(lib), lib)
        body(SonySenserCamera(device))
    finally:
        auth.stop()
        session.say("Stop request sent")


# ------------------------------------------------------------ the steps

def text(status):
    return "no status" if status is None else "0x%08x (%s)" % (status, STATUS_TEXT.get(status, "not a status this script knows"))


def command(camera, code, payload):
    """One service command: (status, data after the status). A guard refusal passes through untouched."""
    answer = camera._sendAdjustControlPacket(0x1001, code, payload)
    if len(answer) < 4:
        return None, b""
    return struct.unpack_from("<I", answer)[0], answer[4:]


def select(camera, path):
    status, _ = command(camera, SET_FILE_PATH, b"\x00" + path)
    if status not in (None, ST_OK):                 # CT1's simulated camera gives no status here; the real one gives 0
        raise c.StopTest("selecting %s: status %s" % (path.decode(), text(status)))


def read(camera, path):
    """(True, content) if the file is there, (False, b'') if the camera says it is not; anything else stops."""
    select(camera, path)
    status, data = command(camera, GET_FILE2, b"\x00\xff\x00")
    if status == ST_OK:
        return True, data
    if status == ST_NO_FILE:
        return False, b""
    raise c.StopTest("reading %s: status %s" % (path.decode(), text(status)))


def known_answer(session, camera):
    want = (c.EXTRACTED / KNOWN_FILE).read_bytes()
    there, data = read(camera, KNOWN_PATH)
    if not there:
        raise c.StopTest("DeviceInfo.xml does not match the 6.02 file (the camera returned no file); nothing else is sent")
    if data != want:
        raise c.StopTest("DeviceInfo.xml does not match the 6.02 file (the camera returned %d bytes, SHA-256 %s; the 6.02 file has %d); nothing else is sent"
                         % (len(data), c.sha256(data)[:16], len(want)))
    session.say("Known-answer read: DeviceInfo.xml equals the 6.02 file")


def remove(session, camera, out):
    """Delete the library and confirm. Never raises for a camera answer: the outcome is recorded and said aloud."""
    out["remove_status"] = out["library_on_camera_after"] = None
    try:
        select(camera, LIB_PATH)
        out["remove_status"], _ = command(camera, FILE_DELETE2, b"\x00\xff")
        session.say("Remove request: status %s" % text(out["remove_status"]))
    except c.GuardRefusal:
        raise
    except Exception as exc:
        out["remove_error"] = "%s: %s" % (type(exc).__name__, exc)
        session.say("Remove request got no answer (%s)" % out["remove_error"])
    try:
        out["library_on_camera_after"] = read(camera, LIB_PATH)[0]
    except c.GuardRefusal:
        raise
    except Exception as exc:
        out["confirm_error"] = "%s: %s" % (type(exc).__name__, exc)
    if out["library_on_camera_after"] is False:
        session.say("Confirmed: /tmp/jiritsu/libJit.so is not on the camera")
    else:
        session.say("!! THE LIBRARY MAY STILL BE ON THE SERVICE PARTITION (/tmp/jiritsu/libJit.so). It is not loaded again by itself "
                    "(F409: only with /tmp/jmode set). Cold boot the camera, then run this script with --remove-only.")


def check_result(data):
    """Facts about a result file without its content (the content stays in camera_private)."""
    facts = {"bytes": len(data), "sha256": c.sha256(data)}
    head = re.match(rb"readcheck 1 level %d\neuid (\d+)\n" % LEVEL, data)
    done = re.search(rb"== done, bytes written before this line: (\d+)\n\Z", data)
    facts["header_ok"] = bool(head)
    facts["euid"] = int(head.group(1)) if head else None
    facts["complete"] = bool(done) and int(done.group(1)) == done.start(1)
    facts["sections"] = [m.group(1).decode() + " " + m.group(2).decode() for m in re.finditer(rb"^== (file|dir) (\S+)$", data, re.M)]
    facts["problems"] = len(re.findall(rb"^!! ", data, re.M))
    if LEVEL == 9:
        k = re.search(rb"^== klog raw (\d+) bytes follow\n", data, re.M)
        klog = data[k.end():k.end() + int(k.group(1))] if k else b""
        logpart = data.split(b"== level 9:", 1)[1].split(b"== klog raw", 1)[0] if b"== level 9:" in data else b""
        facts["level9"] = {"log_entries": [m.decode("latin1") for m in re.findall(rb"^== file \S*/log/(\S+)$", logpart, re.M)],
                           "log_folder_error": [m.decode() for m in re.findall(rb"^== dir \S*/log\n(!! .*)$", logpart, re.M)],
                           "klog_bytes": len(klog), "klog_sha256": c.sha256(klog), "klog_nonzero": sum(1 for b in klog if b),
                           "klog_problems": [m.decode() for m in re.findall(rb"^!! (?:mmap of the kernel log buffer|/dev/mem open failed).*$", data, re.M)]}
        facts["_klog"] = klog
    if LEVEL == 10:
        logs = {}
        for name in (b"kprint", b"boottime"):
            k = re.search(rb"^== cp log " + name + rb" raw (\d+) bytes follow\n", data, re.M)
            logs[name.decode()] = data[k.end():k.end() + int(k.group(1))] if k else b""
        kp = logs["kprint"]
        magic = len(kp) >= 16 and struct.unpack_from("<I", kp, 0)[0] == 0x4B4C4F47
        used = struct.unpack_from("<I", kp, 4)[0] if magic else None
        txt = kp[16:16 + used] if magic and used is not None and used <= len(kp) - 16 else b""
        facts["level10"] = {"kprint_bytes": len(kp), "kprint_header_ok": magic, "kprint_used": used, "kprint_flag": struct.unpack_from("<I", kp, 8)[0] if magic else None,
                            "kprint_lines": txt.count(b"\n"), "kept_after_restart": b"Detect & keep kprint log" in txt, "initialised": b"Initialize kprint log" in txt,
                            "boottime_bytes": len(logs["boottime"]), "boottime_nonzero": sum(1 for b in logs["boottime"] if b),
                            "complete": b"\nlevel 10 complete\n" in data, "released": data.count(b"\nbuffer released\n"),
                            "problems": [m.decode() for m in re.findall(rb"^!! .*$", data.split(b"== level 10:", 1)[1] if b"== level 10:" in data else b"", re.M)]}
        facts["_cp_logs"] = logs
    if LEVEL == 12:
        sys.path.insert(0, str(HERE.parent.parent / "build"))
        import dmm_dump
        ranges = dmm_dump.parse_result(data)
        part = data.split(b"== level 12:", 1)[1] if b"== level 12:" in data else b""
        dec = dmm_dump.decode(ranges) if "globals" in ranges else {"problems": ["the page of pointers was not copied"]}
        w, cl = dec.get("workspace") or {}, dec.get("command_log") or {}
        facts["level12"] = {"complete": b"\nlevel 12 complete\n" in data, "released": data.count(b"\nbuffer released\n"),
                            "problems": [m.decode() for m in re.findall(rb"^!! .*$", re.sub(rb"== cp range \w+ at 0x[0-9a-f]{8} raw (\d+) bytes follow\n(?s:.*?)\n== cp range end\n", b"", part), re.M)],
                            "ranges": {n: {"address": "0x%08x" % a, "bytes": len(b), "sha256": c.sha256(b)} for n, (a, b) in ranges.items()},
                            "pointers": dec.get("pointers"),
                            "unit_records_equal_to_the_file": (dec.get("unit_records") or {}).get("equal_to_the_file"),
                            "unit_records_that_differ": (dec.get("unit_records") or {}).get("records_that_differ"),
                            "group_records_equal_to_the_file": (dec.get("group_records") or {}).get("equal_to_the_file"),
                            "scene": w.get("scene"), "unit_objects_live": w.get("unit_objects_live"), "unit_objects_in_use": w.get("unit_objects_in_use"),
                            "in_use_by_memory_id": w.get("in_use_by_memory_id"), "layouts_in_force": w.get("layouts_in_force"), "parents_0x6fa": w.get("parents_0x6fa"),
                            "units_of_layout_0x89": w.get("units_of_layout_0x89"), "write_buffer_change_would_take_effect": w.get("write_buffer_change_would_take_effect"),
                            "command_log": {k: cl.get(k) for k in ("tag_before_it", "entries_used", "requests", "opens_by_memory_id")} if cl else None,
                            "write_buffers": dec.get("write_buffers"), "movie_tables": dec.get("movie_tables"),
                            "decode_problems": dec.get("problems"), "report": dmm_dump.report(dec).split("\n")}
        facts["_cp_ranges"], facts["_dmm_decoded"] = ranges, dec
    if LEVEL == 15:
        sys.path.insert(0, str(HERE.parent.parent / "build"))
        import dmm_dump
        import out_state
        ranges = dmm_dump.parse_result(data)                        # the same '== cp range' sections as level 12 writes
        part = data.split(b"== level 15:", 1)[1] if b"== level 15:" in data else b""
        dec = out_state.decode(ranges)
        facts["level15"] = {"complete": b"\nlevel 15 complete\n" in data, "released": data.count(b"\nbuffer released\n"),
                            "problems": [m.decode() for m in re.findall(rb"^!! .*$", re.sub(rb"== cp range \w+ at 0x[0-9a-f]{8} raw (\d+) bytes follow\n(?s:.*?)\n== cp range end\n", b"", part), re.M)],
                            "ranges": {n: {"address": "0x%08x" % a, "bytes": len(b), "sha256": c.sha256(b)} for n, (a, b) in ranges.items()},
                            **{k: dec.get(k) for k in ("window", "resize_reference_window", "output_size", "drive_mode_id", "output_records", "for_a_3840x2560_picture",
                                                       "resize_result", "resize_working_values", "resize_settings", "drive_parameter_copy", "id_table")},
                            "saved_copy_equal": dec.get("output_records") == dec.get("output_records_saved_copy"),
                            "decode_problems": dec.get("problems"), "report": out_state.report(dec).split("\n")}
        facts["_out_ranges"], facts["_out_decoded"] = ranges, dec
    if LEVEL == 21:
        sys.path.insert(0, str(HERE.parent.parent / "build"))
        import rdc_state
        ranges = rdc_state.parse_result(data)
        part = data.split(b"== level 21:", 1)[1] if b"== level 21:" in data else b""
        dec = rdc_state.decode(ranges)
        facts["level21"] = {"complete": b"\nlevel 21 complete\n" in data, "released": data.count(b"\nbuffer released\n"),
                            "problems": [m.decode() for m in re.findall(rb"^!! .*$", re.sub(rb"== cp range \w+ at 0x[0-9a-f]{8} raw (\d+) bytes follow\n(?s:.*?)\n== cp range end\n", b"", part), re.M)],
                            "ranges": {n: {"address": "0x%08x" % a, "bytes": len(b), "sha256": c.sha256(b)} for n, (a, b) in ranges.items()},
                            "drive_mode_id": dec.get("drive_mode_id"), "output_size": dec.get("output_size"), "ports": dec.get("ports"),
                            "decode_problems": dec.get("problems"), "report": rdc_state.report(dec).split("\n")}
        facts["_out_ranges"], facts["_out_decoded"] = ranges, dec
    if LEVEL == 28:
        sys.path.insert(0, str(HERE.parent.parent / "build"))
        import frame_state
        ranges = frame_state.parse_result(data)
        part = data.split(b"== level 28:", 1)[1] if b"== level 28:" in data else b""
        dec = frame_state.decode(ranges)
        facts["level28"] = {"complete": b"\nlevel 28 complete\n" in data, "released": data.count(b"\nbuffer released\n"),
                            "problems": [m.decode() for m in re.findall(rb"^!! .*$", re.sub(rb"== cp range \w+ at 0x[0-9a-f]{8} raw (\d+) bytes follow\n(?s:.*?)\n== cp range end\n", b"", part), re.M)],
                            "ranges": {n: {"address": "0x%08x" % a, "bytes": len(b), "sha256": c.sha256(b)} for n, (a, b) in ranges.items()},
                            **{k: dec.get(k) for k in ("index", "layout_now", "tracking_now", "frames_now", "afwindow_now", "tables_16x9_rear_panel",
                                                       "tracking_check_now", "vdf_fit_word", "vdf_letterbox_words")},
                            "frames_with_a_frame": len(dec.get("frames_with_a_frame") or []),
                            "decode_problems": dec.get("problems"), "report": frame_state.report(dec).split("\n")}
        facts["_out_ranges"], facts["_out_decoded"] = ranges, dec
    if LEVEL in (13, 14):
        head = re.search(rb"^== level 1[34]: (apply|put back) the four memory-manager words of (\S+)$", data, re.M)
        part = data[head.start():] if head else b""
        ptr = re.search(rb"^workspace 0x([0-9a-f]{8}), unit objects 0x([0-9a-f]{8})$", part, re.M)
        facts["level1314"] = {"verb": head.group(1).decode() if head else None, "design": head.group(2).decode() if head else None,
                              "workspace": "0x" + ptr.group(1).decode() if ptr else None, "unit_objects": "0x" + ptr.group(2).decode() if ptr else None,
                              "checks_passed": b"\nchecks passed: no unit of the present division exists" in part,
                              "as_expected": len(re.findall(rb"^site 0x[0-9a-f]{8}: as expected$", part, re.M)),
                              "already": len(re.findall(rb"^site 0x[0-9a-f]{8}: already holds the target bytes$", part, re.M)),
                              "written": len(re.findall(rb"^site 0x[0-9a-f]{8}: written and read back$", part, re.M)),
                              "done": b"\nDONE: all four sites hold the target bytes (" in part, "nothing_to_do": b"\nNOTHING TO DO: " in part,
                              "undone": b"\nNOT DONE: a step failed; every site this run touched was put back\n" in part,
                              "undo_incomplete": b"UNDO INCOMPLETE" in part, "released": part.count(b"\nbuffer released\n"),
                              "refused": [m.decode() for m in re.findall(rb"^(!! .*; nothing is written)$", part, re.M)],
                              "problems": [m.decode() for m in re.findall(rb"^(?:site|undo) 0x[0-9a-f]{8}: (!! .*)$|^(!! .*)$", part, re.M) for m in m if m]}
    if LEVEL in (16, 17):
        head = re.search(rb"^== level 1[67]: (apply|put back) the words of (\S+)$", data, re.M)
        part = data[head.start():] if head else b""
        facts["level1617"] = {"verb": head.group(1).decode() if head else None, "design": head.group(2).decode() if head else None,
                              "checks_passed": b"\nchecks passed: the bytes beside the sites are as expected\n" in part,
                              "as_expected": len(re.findall(rb"^site 0x[0-9a-f]{8}: as expected$", part, re.M)),
                              "already": len(re.findall(rb"^site 0x[0-9a-f]{8}: already holds the target bytes$", part, re.M)),
                              "written": len(re.findall(rb"^site 0x[0-9a-f]{8}: written and read back$", part, re.M)),
                              "done": b"\nDONE: every site holds the target bytes (" in part, "nothing_to_do": b"\nNOTHING TO DO: " in part,
                              "undone": b"\nNOT DONE: a step failed; every site this run touched was put back\n" in part,
                              "undo_incomplete": b"UNDO INCOMPLETE" in part, "released": part.count(b"\nbuffer released\n"),
                              "refused": [m.decode() for m in re.findall(rb"^(!! .*; nothing is written)$", part, re.M)],
                              "problems": [m.decode() for m in re.findall(rb"^(?:site|undo) 0x[0-9a-f]{8}: (!! .*)$|^(!! .*)$", part, re.M) for m in m if m]}
    if LEVEL == 27:
        part = data.split(b"== level 27:", 1)[1] if b"== level 27:" in data else b""
        verdict = re.search(rb"^== level 27 verdict: (.*)$", part, re.M)
        word = re.search(rb"^avcam word (0x[0-9a-f]{8}) count (0x[0-9a-f]{8})$", part, re.M)
        before = re.search(rb"^before: scu (0x[0-9a-f]{8}) gates (0x[0-9a-f]{8}) reset (0x[0-9a-f]{8})$", part, re.M)
        after = re.search(rb"^after: scu (0x[0-9a-f]{8}) gates (0x[0-9a-f]{8}) reset (0x[0-9a-f]{8}) \((.*)\)$", part, re.M)
        ran = re.search(rb"^ran for (\d+) ms$", part, re.M)
        rel0 = re.search(rb"^vcd \+0x80 before release (0x[0-9a-f]{8})$", part, re.M)
        rel1 = re.search(rb"^vcd \+0x80 at the end (0x[0-9a-f]{8})$", part, re.M)
        names = ("magic", "version", "cpu", "rounds", "count_last", "prid", "config", "status_at_reset", "dram_window", "count_entry")

        names_v2 = {0: ("magic", "version", "cpu", "rounds", "count_latest", "timer_at_entry", "timer_ticks_1x_loop_uncached",
                        "timer_ticks_64x_loop_cached", "timer_at_mbp_release", "timer_latest"),
                    1: ("magic", "version", "cpu", "rounds", "count_latest", "timer_at_entry", "count_after_test_write", "dram_window",
                        "prid", "timer_latest")}

        def rec(h):
            b = bytes.fromhex(h.decode())
            w = struct.unpack("<10I", b[:40])
            if w[1] == 6 and w[2] == 0:                        # hello_v6 (SPU): progress, exception, tries, last outcome, flags
                r = {"magic": b[:4].decode("latin1"), "version": "0x%08x" % w[1], "cpu": "0x%08x" % w[2], "rounds": "0x%08x" % w[3],
                     "progress": "0x%08x" % w[4], "tries_started": w[7], "last_outcome": "0x%08x" % w[8], "flags": "0x%08x" % w[9]}
                if (w[9] >> 16) == 0x444F:
                    r["done"] = {"block_setup": bool(w[9] & 1), "guards": bool(w[9] & 2), "all_tries_clean": bool(w[9] & 4), "end": bool(w[9] & 8)}
                if (w[4] >> 16) == 0x5052 and not (w[9] & 8):
                    st = (w[4] >> 12) & 0xF
                    r["stopped_in"] = {0: "start", 1: "block set-up", 2: "patterns", 3: "guards", 4: "FMC programme", 5: "core programme",
                                       6: "waiting for the core", 7: "waiting for the FMC", 8: "canaries and copy", 9: "end"}.get(st, "?")
                    r["stopped_at_try_row"] = [(w[4] >> 8) & 0xF, w[4] & 0xFF]
                elif (w[4] >> 16) == 0x4558:
                    r["exception"] = {"vector": "0x%03x" % (w[4] & 0xFFFF), "epc": "0x%08x" % w[5], "cause": "0x%08x" % w[6]}
                return r
            if w[1] == 6:
                return {"magic": b[:4].decode("latin1"), "version": "0x%08x" % w[1], "cpu": "0x%08x" % w[2], "rounds": "0x%08x" % w[3]}
            if w[1] == 5 and w[2] == 0:                        # hello_v5 (SPU): progress, exception, differences, pass time, flags
                r = {"magic": b[:4].decode("latin1"), "version": "0x%08x" % w[1], "cpu": "0x%08x" % w[2], "rounds": "0x%08x" % w[3],
                     "progress": "0x%08x" % w[4], "words_differing_pass1_pass2": w[7], "pass1_ticks": w[8], "flags": "0x%08x" % w[9]}
                if (w[9] >> 16) == 0x444F:
                    r["done"] = {"block_setup": bool(w[9] & 1), "pass1": bool(w[9] & 2), "pass2": bool(w[9] & 4), "compare": bool(w[9] & 8)}
                if (w[4] >> 16) == 0x5052 and not (w[9] & 8):
                    st = (w[4] >> 12) & 0xF
                    r["stopped_in"] = {0: "start", 1: "block set-up", 2: "pass 1", 3: "the 10 ms wait", 4: "pass 2", 5: "compare"}.get(st, "?")
                    if st in (2, 4):
                        sys.path.insert(0, str(HERE.parent.parent / "modding" / "vcd_hello"))
                        import v5_regs
                        k = w[4] & 0xFFF
                        r["stopped_before_reading"] = v5_regs.name_of(k) if k < v5_regs.N else "index %d" % k
                elif (w[4] >> 16) == 0x4558:
                    r["exception"] = {"vector": "0x%03x" % (w[4] & 0xFFFF), "epc": "0x%08x" % w[5], "cause": "0x%08x" % w[6]}
                return r
            if w[1] == 5:                                      # hello_v5 (MBPs): they stay held, so normally all zero
                return {"magic": b[:4].decode("latin1"), "version": "0x%08x" % w[1], "cpu": "0x%08x" % w[2], "rounds": "0x%08x" % w[3]}
            if w[1] == 4:                                      # hello_v4: test times in timer ticks, then the flag word
                r = {"magic": b[:4].decode("latin1"), "version": "0x%08x" % w[1], "cpu": "0x%08x" % w[2], "rounds": "0x%08x" % w[3],
                     "t1_write_1MB": w[4], "t2_read_1MB": w[5], "t3_copy_512KB": w[6], "t4_uncached_read_64KB": w[7], "t5_read_1MB_together": w[8],
                     "flags": "0x%08x" % w[9]}
                if (w[9] >> 16) == 0x444F:
                    r["checks"] = {"t2_sum": bool(w[9] & 1), "t3_copy": bool(w[9] & 2), "t4_sum": bool(w[9] & 4), "t5_sum": bool(w[9] & 8), "t5_on_go": bool(w[9] & 16)}
                elif (w[9] >> 16) == 0x5052:
                    r["stopped_in"] = {1: "T1", 2: "T2", 3: "T3", 4: "T4", 5: "T5", 6: "block set-up", 7: "MBP release", 8: "waiting for ready/go", 0: "start"}.get((w[9] >> 8) & 0xFF, "?")
                elif (w[9] >> 16) == 0x4558:
                    r["exception"] = {"vector": "0x%03x" % (w[9] & 0xFFFF), "epc": "0x%08x" % w[8], "cause": "0x%08x" % w[4]}
                tick = 1 / 1.6825e6                                # seconds per codec-timer tick (F787)
                mbps = lambda nbytes, t: round(nbytes / (t * tick) / 1e6, 1) if t else None
                r["MB_per_s"] = {"write": mbps(1 << 20, w[4]), "read": mbps(1 << 20, w[5]), "copy_moved": mbps(1 << 19, w[6]),
                                 "uncached_read": mbps(1 << 16, w[7]), "read_together": mbps(1 << 20, w[8])}
                return r
            nm = names if w[1] not in (2, 3) else names_v2[0 if w[2] == 0 else 1]   # hello_v2/v3 records (version 2, 3) have their own layout
            r = {"magic": b[:4].decode("latin1"), **{n: "0x%08x" % v for n, v in zip(nm[1:], w[1:])}}
            if w[1] == 3 and (w[9] >> 16) == 0x5052:          # hello_v3: the SPU stopped while setting up; the word says before which store
                r["progress"] = {1: "block set-up, before store %d of 12" % (w[9] & 0xFF), 2: "MBP release, before store %d of 6" % (w[9] & 0xFF),
                                 3: "after the MBP release"}.get((w[9] >> 8) & 0xFF, "0x%08x" % w[9])
            if w[1] == 3 and (w[9] >> 16) == 0x4558:          # an exception: vector, EPC, Cause
                r["exception"] = {"vector": "0x%03x" % (w[9] & 0xFFFF), "epc": "0x%08x" % w[8], "cause": "0x%08x" % w[4]}
            return r
        recs = {}
        for tag, cpu, h in re.findall(rb"^rec ([abc]) (\d) ([0-9a-f]{80})$", part, re.M):
            recs.setdefault(tag.decode(), {})[int(cpu)] = rec(h)
        stores = re.findall(rb"^  st (0x[0-9a-f]{8}) (0x[0-9a-f]{8}) rb (0x[0-9a-f]{8})$", part, re.M)
        rate = None
        if ran and "a" in recs and "b" in recs and 0 in recs["b"] and recs["b"][0].get("version") in ("0x00000002", "0x00000003"):
            rate = {}
            ms = int(ran.group(1))
            for cpu in sorted(recs["b"]):
                rb_, ra_ = recs["b"][cpu], recs["a"].get(cpu, {})
                if not rb_.get("magic", "").strip("\x00"):
                    continue
                t1, c1 = int(rb_["timer_latest"], 16), int(rb_["count_latest"], 16)
                t0 = int(ra_["timer_latest"], 16) if ra_.get("magic", "").strip("\x00") else int(rb_["timer_at_entry"], 16)
                c0 = int(ra_["count_latest"], 16) if ra_.get("magic", "").strip("\x00") else 0
                dt, dc = (t1 - t0) & 0xFFFFFFFF, (c1 - c0) & 0xFFFFFFFF
                rate[cpu] = {"timer_delta": dt, "count_delta": dc, "count_per_timer_tick": round(dc / dt, 4) if dt else None}
            if 0 in rate and recs["a"].get(0, {}).get("magic") == "HELO":
                rate["timer_ticks_per_ms_approx"] = round(rate[0]["timer_delta"] / max(1, ms - 50), 1)   # snapshots at about 50 and `ms`
            u, c64 = int(recs["b"][0]["timer_ticks_1x_loop_uncached"], 16), int(recs["b"][0]["timer_ticks_64x_loop_cached"], 16)
            rate["cached_speedup"] = round(64 * u / c64, 1) if c64 else None
        elif "b" in recs and 0 in recs["b"] and recs["b"][0].get("version") == "0x00000004":
            # hello_v4: bandwidth per CPU, and all three reading together (T5): 3 MB over the longest of the three times
            rate = {cpu: r["MB_per_s"] for cpu, r in sorted(recs["b"].items()) if "MB_per_s" in r}
            t5 = [r["t5_read_1MB_together"] for r in recs["b"].values() if r.get("t5_read_1MB_together")]
            if len(t5) == 3:
                rate["read_together_all_three_MB_per_s"] = round(3 * (1 << 20) / (max(t5) / 1.6825e6) / 1e6, 1)
        elif ran and "a" in recs and "b" in recs and 0 in recs["a"] and 0 in recs["b"] and "count_last" in recs["b"][0]:
            dc = (int(recs["b"][0]["count_last"], 16) - int(recs["a"][0]["count_last"], 16)) & 0xFFFFFFFF
            rate = {"spu_count_delta_a_to_b": dc, "note": "the stub stores Count once per round; the delta over the ~250 ms between snapshots, against the main processor's ms clock, gives the Count rate (MIPS Count runs at the CPU clock or half of it)"}
        regs5 = job6 = None
        rows = re.findall(rb"^dump 0x([0-9a-f]{8}) ([0-9a-f]{128})$", part, re.M)
        if rows and bytes.fromhex(rows[0][1].decode())[:4] == b"JOB6":   # hello_v6: the job's tries and outputs
            sys.path.insert(0, str(HERE.parent.parent / "modding" / "vcd_hello"))
            import emu_v6
            dmp = b"".join(bytes.fromhex(h.decode()) for _, h in rows)
            job6 = emu_v6.parse_dump(dmp)
            for t in job6["per_try"]:
                t["outcome_meaning"] = [m for b, m in __import__("v6_job").OUTCOME_BITS.items() if t["outcome"] & b]
                for k in ("status_028_before", "status_028_after", "fmc_010_after", "fmc_2000_after"):
                    t[k] = "0x%08x" % t[k]
            job6["outputs_hex"] = {i: dmp[0x100 + i * 0x300:0x100 + i * 0x300 + 0x300].hex() for i in range(len(job6["per_try"]))}
            rows = []
        if rows:                                               # hello_v5: the register dump, named from v5_regs.py
            sys.path.insert(0, str(HERE.parent.parent / "modding" / "vcd_hello"))
            import v5_regs
            dmp = b"".join(bytes.fromhex(h.decode()) for _, h in rows)
            dw = struct.unpack("<%dI" % (len(dmp) // 4), dmp)
            hdr = dw[:4]
            valid = len(dw) >= 4 + 2 * v5_regs.N and hdr[0] == v5_regs.DUMP_MAGIC and hdr[1] == 5 and hdr[2] == v5_regs.N
            passes = hdr[3] if valid else 0
            p1 = dw[4:4 + v5_regs.N] if valid and passes >= 1 else ()
            p2 = dw[4 + v5_regs.N:4 + 2 * v5_regs.N] if valid and passes >= 2 else ()
            regs5 = {"header_ok": valid, "passes": passes,
                     "pass1": {v5_regs.name_of(i): "0x%08x" % v for i, v in enumerate(p1)},
                     "changed_between_passes": {v5_regs.name_of(i): ["0x%08x" % p1[i], "0x%08x" % p2[i]] for i in range(len(p2)) if p1[i] != p2[i]},
                     "fmc_idle": {b: (not (p1[v5_regs.OFFS.index(0x4010) + b * v5_regs.N_BLOCK] & 1)) for b in (0, 1)} if p1 else None,
                     "all_ones_words": sum(1 for v in p1 if v == 0xFFFFFFFF), "zero_words": sum(1 for v in p1 if v == 0)}
        facts["level27"] = {"verdict": verdict.group(1).decode() if verdict else None, "registers": regs5, "job": job6,
                            "avcam_word": word.group(1).decode() if word else None, "count": word.group(2).decode() if word else None,
                            "before": [x.decode() for x in before.groups()] if before else None,
                            "after": [x.decode() for x in after.groups()] if after else None,
                            "stores": len(stores), "plus_0x80_before_release": rel0.group(1).decode() if rel0 else None,
                            "plus_0x80_at_the_end": rel1.group(1).decode() if rel1 else None,
                            "ran_ms": int(ran.group(1)) if ran else None, "records": recs, "rate": rate,
                            "restored": b"\nrestored: the stubs hold the stock bytes and the record area is zero, in both views\n" in part,
                            "problems": [m.decode() for m in re.findall(rb"^.*!! .*$", part, re.M)]}
    if LEVEL == 26:
        part = data.split(b"== level 26:", 1)[1] if b"== level 26:" in data else b""
        verdict = re.search(rb"^== level 26 verdict: (.*)$", part, re.M)
        word = re.search(rb"^avcam 0xffffffc001b61268 = (0x[0-9a-f]{8})$", part, re.M)
        scu = re.search(rb"^scu 0xf1388070 = (0x[0-9a-f]{8})", part, re.M)
        base = re.search(rb"^program area at physical (0x[0-9a-f]+)$", part, re.M)
        prog = {int(m[0], 16): bytes.fromhex(m[1].decode()) for m in re.findall(rb"^prog \+(0x[0-9a-f]{8}) \d+ [^\n]*? ([0-9a-f]+)$", part, re.M)}
        stock = (c.EXTRACTED / VCD_FILE).read_bytes()
        same = lambda off: (prog[off] == stock[off:off + len(prog[off])]) if off in prog else None
        rec = prog.get(0x13f0000)
        facts["level26"] = {"verdict": verdict.group(1).decode() if verdict else None, "avcam_word": word.group(1).decode() if word else None,
                            "scu_0x70": scu.group(1).decode() if scu else None, "program_area_physical": base.group(1).decode() if base else None,
                            "spu_stub_is_stock": same(0x0), "spu_code_is_stock": same(0x9000), "mbp0_stub_is_stock": same(0xa6a000), "mbp1_stub_is_stock": same(0xa6d000),
                            "log_head": prog[0x1300000].hex() if 0x1300000 in prog else None,
                            "record_area_all_zero": (not any(rec)) if rec is not None else None,
                            "record_area_nonzero_bytes": sum(1 for b in rec if b) if rec is not None else None,
                            "problems": [m.decode() for m in re.findall(rb"^.*!! .*$", part, re.M)]}
    if LEVEL == 22:
        part = data.split(b"== level 22:", 1)[1] if b"== level 22:" in data else b""
        num = lambda m: int(m, 16)
        verdict = re.search(rb"^== level 22 verdict: (.*)$", part, re.M)
        regs = {m[0].decode(): num(m[1]) for m in re.findall(rb"^vcd (0x[0-9a-f]{8}) = (0x[0-9a-f]{8})$", part, re.M)}
        prog = {m[0].decode(): bytes.fromhex(m[2].decode()) for m in re.findall(rb"^prog \+(0x[0-9a-f]{8}) (\d+) [^\n]*? ([0-9a-f]+)$", part, re.M)}
        scu = re.search(rb"^scu 0xf1388070 = (0x[0-9a-f]{8})$", part, re.M)
        after = re.search(rb"^scu after = (0x[0-9a-f]{8})", part, re.M)
        base = re.search(rb"^program area at physical (0x[0-9a-f]+)$", part, re.M)
        stock = (c.EXTRACTED / VCD_FILE).read_bytes()
        head, rec = prog.get("0x00000000"), prog.get("0x013f0000")
        facts["level22"] = {"verdict": verdict.group(1).decode() if verdict else None,
                            "scu_0x70": "0x%08x" % num(scu.group(1)) if scu else None, "scu_after": "0x%08x" % num(after.group(1)) if after else None,
                            "clocked": b"gate: the codec is clocked" in part,
                            "pbl": {m[0].decode(): "0x%08x" % num(m[1]) for m in re.findall(rb"^pbl (0x[0-9a-f]{8}) = (0x[0-9a-f]{8})$", part, re.M)},
                            "avcam": {m[0].decode(): m[1].decode() for m in re.findall(rb"^avcam (0x[0-9a-f]{16}) = (0x[0-9a-f]+)$", part, re.M)},
                            "vcd": {k: "0x%08x" % v for k, v in regs.items()},
                            "program_area_physical": base.group(1).decode() if base else None,
                            "program_head_is_stock": head == stock[:0x40] if head is not None else None,
                            "spu_code_is_stock": prog.get("0x00009000") == stock[0x9000:0x9020] if "0x00009000" in prog else None,
                            "record_area_all_zero": (not any(rec)) if rec is not None else None,
                            "log_head": prog["0x01300000"].hex() if "0x01300000" in prog else None,
                            "problems": [m.decode() for m in re.findall(rb"^!! .*$", part, re.M)]}
    if LEVEL == 18:
        head = re.search(rb"^== level 18: the encoder-side sites of (\S+), read-only$", data, re.M)
        part = data[head.start():] if head else b""
        verdict = re.search(rb"^== level 18 verdict: (READY|APPLIED|NOT READY): ", part, re.M)
        lines = re.findall(rb"^  (av|lm) (\d+) (site|guard) (0x[0-9a-f]+) (\d+) (SAME|DIFFERS|STOCK|TARGET|OTHER) ([0-9a-f]*)$", part, re.M)
        tally = lambda tag: {w.lower(): sum(1 for l in lines if l[0] == tag and l[5] == w.encode()) for w in ("SAME", "DIFFERS", "STOCK", "TARGET", "OTHER")}
        where = re.search(rb"^(?:libmpr|appFw)\.so mapped at (0x[0-9a-f]+)-(0x[0-9a-f]+) (\S+), (\d+) entries$", part, re.M)
        facts["level18"] = {"design": head.group(1).decode() if head else None, "verdict": verdict.group(1).decode() if verdict else None,
                            "av_cam": tally(b"av"), "libmpr": tally(b"lm"),
                            "libmpr_mapping": {"start": where.group(1).decode(), "end": where.group(2).decode(), "permissions": where.group(3).decode()} if where else None,
                            "not_stock": [b" ".join(l).decode() for l in lines if l[5] in (b"DIFFERS", b"TARGET", b"OTHER")],
                            "problems": [m.decode().strip() for m in re.findall(rb"^.*!! .*$", part, re.M)]}
    if LEVEL == 23:
        head = re.search(rb"^== level 23: the codec firmware sites of (\S+), read-only$", data, re.M)
        part = data[head.start():] if head else b""
        verdict = re.search(rb"^== level 23 verdict: (READY|APPLIED|NOT FOUND|NOT READY|NOTHING READ)", part, re.M)
        facts["level23"] = {"design": head.group(1).decode() if head else None, "verdict": verdict.group(1).decode() if verdict else None,
                            "copies_at": [m.decode() for m in re.findall(rb"^copy \d+ at physical (0x[0-9a-f]+)$", part, re.M)],
                            "found": [m.decode() for m in re.findall(rb"^copy found at physical (.*)$", part, re.M)],
                            "sites": {w.lower().decode(): len(re.findall(rb"^  copy \d+ site 0x[0-9a-f]+ 4 " + w + rb" ", part, re.M)) for w in (b"STOCK", b"TARGET", b"OTHER")},
                            "guards": {"same": len(re.findall(rb" SAME$", part, re.M)), "differs": len(re.findall(rb" DIFFERS ", part, re.M))},
                            "problems": [m.decode() for m in re.findall(rb"^.*!! .*$", part, re.M)]}
    if LEVEL in (24, 25):
        head = re.search(rb"^== level (?:24|25): (apply|put back) the codec firmware sites of (\S+)$", data, re.M)
        part = data[head.start():] if head else b""
        count = lambda text: len(re.findall(rb"^copy \d+ site 0x[0-9a-f]+: " + text + rb"$", part, re.M))
        facts["level2425"] = {"verb": head.group(1).decode() if head else None, "design": head.group(2).decode() if head else None,
                              "copies_at": [m.decode() for m in re.findall(rb"^copy \d+ at physical (0x[0-9a-f]+)$", part, re.M)],
                              "checks_passed": b"\nchecks passed: in every copy " in part,
                              "as_expected": count(b"as expected"), "already": count(b"already holds the target bytes"), "written": count(b"written and read back"),
                              "done": b"\nDONE: every site of every copy holds the target bytes (" in part, "nothing_to_do": b"\nNOTHING TO DO: " in part,
                              "undone": b"\nNOT DONE: a step failed; every site this run touched was put back\n" in part,
                              "undo_incomplete": b"UNDO INCOMPLETE" in part,
                              "refused": [m.decode() for m in re.findall(rb"^(!! .*; nothing is written)$", part, re.M)],
                              "problems": [m.decode() for m in re.findall(rb"^(!! .*)$", part, re.M)]}
    if LEVEL in (19, 20):
        head = re.search(rb"^== level (?:19|20): (apply|put back) the main-processor sites of (\S+)$", data, re.M)
        part = data[head.start():] if head else b""
        where = re.search(rb"^av-cam.bin at physical (0x[0-9a-f]+), (\d+) entries; (?:libmpr|appFw)\.so mapped at (0x[0-9a-f]+)-(0x[0-9a-f]+) (\S+), (\d+) entries$", part, re.M)
        count = lambda tag, text: len(re.findall(rb"^" + tag + rb" site 0x[0-9a-f]+: " + text + rb"$", part, re.M))
        facts["level1920"] = {"verb": head.group(1).decode() if head else None, "design": head.group(2).decode() if head else None,
                              "libmpr_mapping": {"start": where.group(3).decode(), "end": where.group(4).decode(), "permissions": where.group(5).decode()} if where else None,
                              "checks_passed": b"\nchecks passed: every guard is as in the file, " in part,
                              "as_expected": {"av_cam": count(b"av", b"as expected"), "libmpr": count(b"lm", b"as expected")},
                              "already": {"av_cam": count(b"av", b"already holds the target bytes"), "libmpr": count(b"lm", b"already holds the target bytes")},
                              "written": {"av_cam": count(b"av", b"written and read back"), "libmpr": count(b"lm", b"written and read back")},
                              "done": b"\nDONE: every site holds the target bytes (" in part, "nothing_to_do": b"\nNOTHING TO DO: " in part,
                              "undone": b"\nNOT DONE: a step failed; every site this run touched was put back\n" in part,
                              "undo_incomplete": b"UNDO INCOMPLETE" in part,
                              "put_back_by_the_undo": len(re.findall(rb"^undo (?:av|lm) site 0x[0-9a-f]+: put back$", part, re.M)),
                              "refused": [m.decode() for m in re.findall(rb"^(!! .*; nothing is written)$", part, re.M)],
                              "problems": [m.decode() for m in re.findall(rb"^(!! .*)$", part, re.M)]}
    if LEVEL == 8:
        part = data.split(b"== level 8:", 1)[1] if b"== level 8:" in data else b""
        state = {a.decode(): h.decode() for a, h in re.findall(rb"^state 0x([0-9a-f]{8})\n  [^\n]*\n  ([0-9a-f]+)$", part, re.M)}
        w = struct.unpack("<8H", bytes.fromhex(state["011d1194"])) if "011d1194" in state else None
        m = struct.unpack("<2H2I", bytes.fromhex(state["011d11ac"])[:12]) if "011d11ac" in state else None
        facts["level8"] = {"record": (re.findall(rb"^stored record, its \d+ bytes: (\w+)$", part, re.M) or [b"not reported"])[0].decode(),
                           "sites": {k: len(re.findall(rb"^site 0x[0-9a-f]{8}\n  " + k.encode() + rb"$", part, re.M)) for k in ("stock", "changed", "OTHER")},
                           "state": state, "complete": b"\nlevel 8 complete\n" in data,
                           "window": None if not w else {"readout": w[0:2], "crop_start": w[2:4], "crop": w[4:6], "front_end": w[6:8]},
                           "size_source": None if not m else list(m[0:2]), "drive_mode_id": None if not m else "0x%x" % m[2]}
        if "0145091c" in state and len(state["0145091c"]) >= 40:
            # the resize result (F680): input size, then the window the second scaler takes from it, start and size as whole part and 12-bit fraction
            r = struct.unpack("<10H", bytes.fromhex(state["0145091c"])[:20])
            facts["level8"]["second_scaler"] = {"input": list(r[0:2]), "start": [round(r[2] + r[6] / 4096, 3), round(r[3] + r[7] / 4096, 3)],
                                                "size": [round(r[4] + r[8] / 4096, 3), round(r[5] + r[9] / 4096, 3)],
                                                "takes_every_row": r[3] == 0 and r[5] == r[1] - 1}
        if "01033c40" in state:
            sh = bytes.fromhex(state["01033c40"])
            vals = {r: sh[o] for o, r, _, _ in SHADOW} if len(sh) == 0x440 else {}
            facts["level8"]["sensor_shadow"] = vals
            facts["level8"]["sensor_mode"] = ("not read" if not vals else "2 (full height)" if all(vals[r] == m2 for _, r, _, m2 in SHADOW)
                                              else "16 (stock full-frame 4K)" if all(vals[r] == m16 for _, r, m16, _ in SHADOW)
                                              else "neither: register 0x01 = %d" % vals["0x01"])
    if LEVEL in (5, 6):
        facts["level56"] = {"record_at": [m.decode() for m in re.findall(rb"^stored record of mode 0x8[0-9a-f]{2} at 0x([0-9a-f]{8}) ", data, re.M)],
                            "as_expected": len(re.findall(rb"^site 0x[0-9a-f]{8} length \d+: as expected$", data, re.M)),
                            "already": len(re.findall(rb"^site 0x[0-9a-f]{8} length \d+: already holds the target bytes$", data, re.M)),
                            "written": len(re.findall(rb"^site 0x[0-9a-f]{8} length \d+: written and read back$", data, re.M)),
                            "done": b"\nDONE: all 14 sites hold the target bytes (" in data, "nothing_to_do": b"\nNOTHING TO DO: " in data,
                            "undone": b"\nNOT DONE: a step failed; every site this run touched was put back\n" in data,
                            "undo_incomplete": b"UNDO INCOMPLETE" in data, "released": data.count(b"\nbuffer released\n"),
                            "problems": [m.decode() for m in re.findall(rb"^(?:site|undo) 0x[0-9a-f]{8} length \d+: (!! .*)$|^(!! (?:buffer|the stored record|UNDO|mmap of the buffer|/dev/mem open failed).*)$", data, re.M) for m in m if m]}
    if LEVEL == 7:
        import json
        ref = json.loads(RECORDS.read_text(encoding="utf8"))
        recs = re.findall(rb"^mode id 0x([0-9a-f]{8})\n  index (\d+)\n  record at 0x([0-9a-f]{8})\n  record: ([0-9a-f]{696})$", data, re.M)
        one = lambda pat: (re.findall(pat, data, re.M) or [b""])[0].decode()
        l7 = facts["level7"] = {"flags": one(rb"^frame-rate family flags, current then requested: ([0-9a-f]{4})$"),
                                "control_object": one(rb"^control object at (0x[0-9a-f]{8})$"), "drvparam_object": one(rb"^drive-parameter object at (0x[0-9a-f]{8})$"),
                                "modes": one(rb"^modes (\d+)$"), "mode_ids_at": one(rb"^mode id list at (0x[0-9a-f]{8})$"), "records_at": one(rb"^records at (0x[0-9a-f]{8})$"),
                                "records": {}, "complete": b"\nlevel 7 complete\n" in data, "released": data.count(b"\nbuffer released\n"),
                                "problems": [m.decode() for m in re.findall(rb"^!! (?:buffer|address|transfer|not a usable|the object|mmap of the buffer|/dev/mem open failed).*$", data, re.M)]}
        for mid, idx, at, hexrec in recs:
            row = l7["records"]["0x%x" % int(mid, 16)] = {"index": int(idx), "address": "0x" + at.decode(), "record": hexrec.decode()}
            if int(mid, 16) == 0x8C0:
                got = bytes.fromhex(row["record"])
                for name in ("stock", "design"):
                    want = bytes.fromhex(ref[name + "_record_10"])
                    row["bytes_different_from_emulated_" + name] = sum(1 for x, y in zip(got, want) if x != y)
    if LEVEL == 4:
        facts["level4"] = {"buffer": [m.decode() for m in re.findall(rb"^buffer physical (0x[0-9a-f]+) handle \d+$", data, re.M)],
                           "steps": [int(m) for m in re.findall(rb"^step (\d):", data, re.M)],
                           "first16": [m.decode() for m in re.findall(rb"^  test line, first 16 bytes ([0-9a-f]{32})$", data, re.M)],
                           "page_zero_before": b"\n  the padding is all zeros, as in the update file\n" in data,
                           "write_seen": b"\n  WRITE SEEN: " in data,
                           "restored": b"\n  RESTORED: the whole page is as it was first read\n" in data,
                           "released": data.count(b"\nbuffer released\n"),
                           "problems": [m.decode() for m in re.findall(rb"^!! (?:buffer|read transfer|read-back|write transfer|restore|WRITE|PAGE|the padding|nothing|mmap of the buffer|/dev/mem open failed).*$", data, re.M)]}
    if LEVEL == 3:
        facts["level3"] = {"buffer": [m.decode() for m in re.findall(rb"^buffer physical (0x[0-9a-f]+) handle \d+$", data, re.M)],
                           "pages": [m.decode() for m in re.findall(rb"^page (\S+) address 0x[0-9a-f]+$", data, re.M)],
                           "cells": [(a.decode(), v.decode()) for a, v in re.findall(rb"^cell address (0x[0-9a-f]+)\n  bytes ([0-9a-f]+)  ", data, re.M)],
                           "same": len(re.findall(rb"  SAME as the update file$", data, re.M)),
                           "differs": len(re.findall(rb"  DIFFERS from the update file$", data, re.M)),
                           "released": data.count(b"\nbuffer released\n"),
                           "stopped": [m.decode() for m in re.findall(rb"^!! (?:buffer|transfer|mmap of the buffer|stopping level 3|/dev/mem open failed).*$", data, re.M)]}
        facts["level3"]["released"] = facts["level3"]["released"] or int(any("buffer address" in t for t in facts["level3"]["stopped"]))   # that path releases without the closing line
    if LEVEL == 2:
        facts["level2"] = {"regions": [m.decode() for m in re.findall(rb"^region (\S+) length \d+$", data, re.M)],
                           "same": len(re.findall(rb"  SAME as the update file$", data, re.M)),
                           "differs": len(re.findall(rb"  DIFFERS from the update file$", data, re.M)),
                           "stopped": [m.decode() for m in re.findall(rb"^!! (?:mmap failed|/dev/mem open failed).*$", data, re.M)]}
    return facts


def body_run(session, camera, lib):
    out = session.results["ct6"] = {"library_bytes": len(lib), "library_sha256": LIB_SHA256, "library_sent": False}
    known_answer(session, camera)
    there, data = read(camera, LIB_PATH)
    if there:
        ours = c.sha256(data) == LIB_SHA256
        raise c.StopTest("a libJit.so is already on the service partition (%d bytes, %s). Nothing was written. %s"
                         % (len(data), "it is this script's library from an earlier run" if ours else "it is NOT this script's library",
                            "Use --remove-only." if ours else "It is left alone."))
    there, old = read(camera, RESULT_PATH)
    if there and CLEAR_SHA and c.sha256(old) == CLEAR_SHA:          # --clear-result: it is a result already saved here; delete it and go on
        session.say("An earlier result is on the RAM disk and is the one already saved here (%d bytes). Deleting it." % len(old))
        GUARDS[-1].allow_result_delete = True
        select(camera, RESULT_PATH)
        out["clear_status"], _ = command(camera, FILE_DELETE2, b"\x00\xff")
        there = read(camera, RESULT_PATH)[0]
        session.say("Delete request: status %s; result file now %s" % (text(out["clear_status"]), "STILL THERE" if there else "gone"))
    if there:
        raise c.StopTest("a result file is already on the RAM disk; the helper would do nothing. Cold boot the camera first, or pass --clear-result "
                         "with the SHA-256 of that result if it is one already saved here. Nothing was written.")
    if read(camera, BUSY_PATH)[0]:
        raise c.StopTest("/tmp/jbusy exists; the camera would refuse the library. Nothing was written.")
    session.say("Checks passed: no library, no result, not busy")

    select(camera, LIB_PATH)                        # a failure here stops with nothing written
    session.say("Sending the library (%d bytes)" % len(lib))
    out["library_sent"] = True
    status = None
    try:
        status, _ = command(camera, SET_FILE2, b"\x00\xff\x00" + lib)
    except c.GuardRefusal:
        out["library_sent"] = False                 # refused on the PC: nothing left it
        raise
    except Exception as exc:
        out["write_error"] = "%s: %s" % (type(exc).__name__, exc)
        session.say("The write got no answer (%s)" % out["write_error"])
    out["write_status"] = status
    if "write_error" not in out:
        session.say("Write and load: status %s" % text(status))

    remove(session, camera, out)                    # always, once the library has been sent
    if "write_error" in out:
        raise c.StopTest("the write got no answer; the result is not read")

    there, result = read(camera, RESULT_PATH)
    out["result_found"] = there
    if not there:
        raise c.StopTest("no result file: the helper did not get as far as creating it (status of the write: %s)" % text(status))
    session.save_bytes("readcheck_result.txt", result)
    facts = out["result"] = check_result(result)
    klog = facts.pop("_klog", None)
    for name, blob in (facts.pop("_cp_logs", None) or {}).items():
        session.save_bytes("cp_%s.bin" % name, blob)              # the coprocessor's logs on their own, for reading offline
    for name, (addr, blob) in (facts.pop("_cp_ranges", None) or {}).items():
        session.save_bytes("dmm_%s_%08x.bin" % (name, addr), blob)  # level 12: each range on its own (build/dmm_dump.py <folder> decodes them)
    if "_dmm_decoded" in facts:
        import json
        session.save_bytes("dmm_decoded.json", json.dumps(facts.pop("_dmm_decoded"), indent=1).encode())
    for name, (addr, blob) in (facts.pop("_out_ranges", None) or {}).items():
        session.save_bytes("out_%s_%08x.bin" % (name, addr), blob)  # level 15: each range on its own (build/out_state.py <folder> decodes them)
    if "_out_decoded" in facts:
        import json
        session.save_bytes("out_decoded.json", json.dumps(facts.pop("_out_decoded"), indent=1).encode())
    if klog:
        session.save_bytes("klog.bin", klog)                        # the kernel log buffer on its own, for reading offline
    session.say("Result saved: %d bytes, header %s, effective user id %s, %d sections, %d problem lines, %s"
                % (facts["bytes"], "ok" if facts["header_ok"] else "NOT as expected", facts["euid"], len(facts["sections"]),
                   facts["problems"], "complete" if facts["complete"] else "NOT complete (the last line is missing or wrong)"))
    if LEVEL == 9:
        f = facts["level9"]
        session.say("Level 9: /log has %d entries%s; kernel log buffer: %d bytes, %d of them non-zero%s"
                    % (len(f["log_entries"]), " (" + "; ".join(f["log_folder_error"]) + ")" if f["log_folder_error"] else "", f["klog_bytes"], f["klog_nonzero"],
                       "; reported: " + "; ".join(f["klog_problems"]) if f["klog_problems"] else ""))
        session.say("  /log entries: %s" % ", ".join(f["log_entries"][:64]))
    if LEVEL == 10:
        f = facts["level10"]
        session.say("Level 10: %s; kprint log %d bytes, header %s, %s bytes used, %d lines, %s; boot-time log %d bytes (%d non-zero)%s"
                    % ("complete" if f["complete"] else "NOT complete", f["kprint_bytes"], "ok" if f["kprint_header_ok"] else "NOT found", f["kprint_used"], f["kprint_lines"],
                       "KEPT from before a restart" if f["kept_after_restart"] else "initialised at this start" if f["initialised"] else "start line not found",
                       f["boottime_bytes"], f["boottime_nonzero"], "; reported: " + "; ".join(f["problems"]) if f["problems"] else ""))
    if LEVEL == 12:
        f = facts["level12"]
        session.say("Level 12: %s; %d ranges copied (%s)%s" % ("complete" if f["complete"] else "NOT complete", len(f["ranges"]),
                                                              ", ".join("%s %d bytes" % (n, r["bytes"]) for n, r in f["ranges"].items()),
                                                              "; reported: " + "; ".join(f["problems"]) if f["problems"] else ""))
        for line in f["report"]:
            session.say("  " + line)
    if LEVEL == 28:
        f = facts["level28"]
        session.say("Level 28: %s; %d ranges copied (%s)%s" % ("complete" if f["complete"] else "NOT complete", len(f["ranges"]),
                                                              ", ".join("%s %d bytes" % (n, r["bytes"]) for n, r in f["ranges"].items()),
                                                              "; reported: " + "; ".join(f["problems"]) if f["problems"] else ""))
        for line in f["report"]:
            session.say("  " + line)
    if LEVEL == 21:
        f = facts["level21"]
        session.say("Level 21: %s; %d ranges copied (%s)%s" % ("complete" if f["complete"] else "NOT complete", len(f["ranges"]),
                                                              ", ".join("%s %d bytes" % (n, r["bytes"]) for n, r in f["ranges"].items()),
                                                              "; reported: " + "; ".join(f["problems"]) if f["problems"] else ""))
        for line in f["report"]:
            session.say("  " + line)
    if LEVEL == 15:
        f = facts["level15"]
        session.say("Level 15: %s; %d ranges copied (%s)%s" % ("complete" if f["complete"] else "NOT complete", len(f["ranges"]),
                                                              ", ".join("%s %d bytes" % (n, r["bytes"]) for n, r in f["ranges"].items()),
                                                              "; reported: " + "; ".join(f["problems"]) if f["problems"] else ""))
        for line in f["report"]:
            session.say("  " + line)
    if LEVEL in (13, 14):
        f = facts["level1314"]
        state = ("DONE: all four words hold the target bytes" if f["done"] else "nothing to do: every word already held the target bytes" if f["nothing_to_do"]
                 else "NOT DONE, and everything touched was put back" if f["undone"] else "REFUSED before any write" if f["refused"] else "NOT DONE")
        session.say("Level %d (%s, %s): %s. Checks before writing: %s. Pass 1: %d as expected, %d already at target; written and read back: %d%s"
                    % (LEVEL, f["verb"], f["design"], state, "passed" if f["checks_passed"] else "NOT passed", f["as_expected"], f["already"], f["written"],
                       "; reported: " + "; ".join(f["problems"]) if f["problems"] else ""))
        if f["undo_incomplete"]:
            session.say("!! THE UNDO DID NOT COMPLETE: THE MEMORY MANAGER'S TABLES ARE PARTLY CHANGED. Cold boot the camera now (battery out for 10 seconds) before anything else.")
    if LEVEL in (16, 17):
        f = facts["level1617"]
        state = ("DONE: every word holds the target bytes" if f["done"] else "nothing to do: every word already held the target bytes" if f["nothing_to_do"]
                 else "NOT DONE, and everything touched was put back" if f["undone"] else "REFUSED before any write" if f["refused"] else "NOT DONE")
        session.say("Level %d (%s, %s): %s. Checks before writing: %s. Pass 1: %d as expected, %d already at target; written and read back: %d%s"
                    % (LEVEL, f["verb"], f["design"], state, "passed" if f["checks_passed"] else "NOT passed", f["as_expected"], f["already"], f["written"],
                       "; reported: " + "; ".join(f["problems"]) if f["problems"] else ""))
        if f["undo_incomplete"]:
            session.say("!! THE UNDO DID NOT COMPLETE: THE TABLE MAY BE PARTLY CHANGED. Cold boot the camera now (battery out for 10 seconds) before anything else.")
    if LEVEL == 23:
        f = facts["level23"]
        session.say("Level 23 (%s): verdict %s. Copies at %s; guards %d as in the file, %d not; sites %d stock, %d target, %d other%s"
                    % (f["design"], f["verdict"] or "MISSING", ", ".join(f["copies_at"]) or "none", f["guards"]["same"], f["guards"]["differs"],
                       f["sites"]["stock"], f["sites"]["target"], f["sites"]["other"], "; reported: " + "; ".join(f["problems"]) if f["problems"] else ""))
    if LEVEL in (24, 25):
        f = facts["level2425"]
        state = ("DONE: every site of every copy holds the target bytes" if f["done"] else "nothing to do: every site already held the target bytes" if f["nothing_to_do"]
                 else "NOT DONE, and everything touched was put back" if f["undone"] else "REFUSED before any write" if f["refused"] else "NOT DONE")
        session.say("Level %d (%s, %s): %s. Copies at %s. Checks before writing: %s. %d as expected, %d already at target, %d written and read back%s"
                    % (LEVEL, f["verb"], f["design"], state, ", ".join(f["copies_at"]) or "none", "passed" if f["checks_passed"] else "NOT passed",
                       f["as_expected"], f["already"], f["written"], "; reported: " + "; ".join(f["problems"]) if f["problems"] else ""))
        if f["undo_incomplete"]:
            session.say("!! THE UNDO DID NOT COMPLETE: THE CODEC FIRMWARE COPY MAY BE PARTLY CHANGED. Cold boot the camera now (battery out for 10 seconds) before anything else.")
    if LEVEL in (19, 20):
        f = facts["level1920"]
        state = ("DONE: every site holds the target bytes" if f["done"] else "nothing to do: every site already held the target bytes" if f["nothing_to_do"]
                 else "NOT DONE, and everything touched was put back" if f["undone"] else "REFUSED before any write" if f["refused"] else "NOT DONE")
        w = f["libmpr_mapping"]
        session.say("Level %d (%s, %s): %s. Checks before writing: %s. av-cam.bin: %d as expected, %d already at target, %d written and read back. libmpr.so%s: "
                    "%d as expected, %d already at target, %d written and read back%s"
                    % (LEVEL, f["verb"], f["design"], state, "passed" if f["checks_passed"] else "NOT passed", f["as_expected"]["av_cam"], f["already"]["av_cam"],
                       f["written"]["av_cam"], " at %s-%s %s" % (w["start"], w["end"], w["permissions"]) if w else "", f["as_expected"]["libmpr"], f["already"]["libmpr"],
                       f["written"]["libmpr"], "; reported: " + "; ".join(f["problems"]) if f["problems"] else ""))
        if f["undo_incomplete"]:
            session.say("!! THE UNDO DID NOT COMPLETE: MAIN-PROCESSOR MEMORY MAY BE PARTLY CHANGED. Cold boot the camera now (battery out for 10 seconds) before anything else.")
    if LEVEL == 8:
        f = facts["level8"]
        session.say("Level 8: %s. Stored record: %s. The 13 table sites: %d stock, %d changed, %d other"
                    % ("complete" if f["complete"] else "NOT complete", f["record"], f["sites"]["stock"], f["sites"]["changed"], f["sites"]["OTHER"]))
        if f["window"]:
            session.say("  working state: drive mode id %s; read-out %s, crop %s, front end %s; size source %s"
                        % (f["drive_mode_id"], list(f["window"]["readout"]), list(f["window"]["crop"]), list(f["window"]["front_end"]), f["size_source"]))
            if DESIGN == "og4k_data_v1":
                session.say("  for comparison, emulated: stock read-out [7032, 3958] front end [4336, 2438]; with the change read-out [7032, 4688] front end [3840, 2560]")
            elif DESIGN == "ogsq_v1":
                session.say("  for comparison, emulated: stock read-out [7032, 3958] crop [7008, 3942]; with ogsq_v1 read-out [7032, 4688] crop [7008, 4672]; "
                            "front end [4336, 2438] in both")
            elif DESIGN == "fhband_v1":
                session.say("  for comparison, emulated: stock and %s alike read-out [7032, 3958] front end [4336, 2438] (this window is the stage after "
                            "the first crop; the band test changes the frame around it)" % DESIGN)
            else:
                import json
                exp = json.loads((HERE.parent.parent / "modding" / "designs" / (DESIGN + ".json")).read_text(encoding="utf8"))["summary"].get("expected_working_state", {})
                session.say("  for comparison, emulated: stock read-out [7032, 3958] crop [7008, 3942]; with %s read-out %s crop %s front end %s"
                            % (DESIGN, exp.get("readout"), exp.get("crop"), exp.get("front_end")))
        if "second_scaler" in f:
            s = f["second_scaler"]
            session.say("  second scaler: takes %s by %s of the %s by %s picture, from (%s, %s): %s"
                        % (s["size"][0], s["size"][1], s["input"][0], s["input"][1], s["start"][0], s["start"][1],
                           "every row (no aspect cut)" if s["takes_every_row"] else "NOT every row: an aspect cut is in force"))
        if "sensor_mode" in f:
            session.say("  sensor register shadow: %s; registers %s" % (f["sensor_mode"], f["sensor_shadow"]))
    if LEVEL in (5, 6):
        f = facts["level56"]
        state = ("DONE: all 14 sites hold the target bytes" if f["done"] else "nothing to do: every site already held the target bytes" if f["nothing_to_do"]
                 else "NOT DONE, and everything touched was put back" if f["undone"] else "NOT DONE")
        session.say("Level %d (%s): %s. Pass 1: %d as expected, %d already at target; written and read back: %d; stored record at %s%s"
                    % (LEVEL, "apply" if LEVEL == 5 else "put back", state, f["as_expected"], f["already"], f["written"],
                       "0x" + f["record_at"][0] if f["record_at"] else "not found", "; reported: " + "; ".join(f["problems"]) if f["problems"] else ""))
        if f["undo_incomplete"]:
            session.say("!! THE UNDO DID NOT COMPLETE: COPROCESSOR MEMORY IS PARTLY CHANGED. Cold boot the camera now (battery out for 10 seconds) before anything else.")
    if LEVEL == 7:
        l7 = facts["level7"]
        r8 = l7["records"].get("0x8c0")
        session.say("Level 7: %s; objects %s, %s; %s modes; records at %s%s"
                    % ("complete" if l7["complete"] else "NOT complete", l7["control_object"], l7["drvparam_object"], l7["modes"], l7["records_at"],
                       "; reported: " + "; ".join(l7["problems"]) if l7["problems"] else ""))
        if r8:
            session.say("  record of mode 0x8c0 (index %d, at %s): %d bytes different from the emulated stock record, %d from the emulated design record"
                        % (r8["index"], r8["address"], r8["bytes_different_from_emulated_stock"], r8["bytes_different_from_emulated_design"]))
    if LEVEL == 4:
        l4 = facts["level4"]
        wrote = 2 in l4["steps"]
        session.say("Level 4: padding zero before: %s; write %s; page %s%s"
                    % ("yes" if l4["page_zero_before"] else "NO", "seen on read-back" if l4["write_seen"] else ("NOT seen" if wrote else "not attempted"),
                       "restored and confirmed" if l4["restored"] else ("NOT CONFIRMED AS RESTORED" if wrote else "untouched"),
                       "; reported: " + "; ".join(l4["problems"]) if l4["problems"] else ""))
        if wrote and not l4["restored"]:
            session.say("!! THE TEST PAGE WAS WRITTEN AND IS NOT CONFIRMED AS RESTORED. Cold boot the camera now (battery out for 10 seconds): that reloads the coprocessor image.")
    if LEVEL == 3:
        l3 = facts["level3"]
        session.say("Level 3: %d page(s) and cell(s) equal to the update file, %d different, buffer %s%s"
                    % (l3["same"], l3["differs"], "released" if l3["released"] else "NOT reported as released",
                       "; stopped: " + "; ".join(l3["stopped"]) if l3["stopped"] else ""))
    if LEVEL == 2:
        l2 = facts["level2"]
        session.say("Level 2: %d range(s) equal to the update file, %d different%s"
                    % (l2["same"], l2["differs"], "; stopped: " + "; ".join(l2["stopped"]) if l2["stopped"] else ""))
    if LEVEL == 27:
        f = facts["level27"]
        session.say("Level 27: verdict %s; av-cam word %s; %d control stores; +0x80 %s before release, %s at the end; ran %s ms; restored: %s%s"
                    % (f["verdict"] or "MISSING", f["avcam_word"], f["stores"], f["plus_0x80_before_release"], f["plus_0x80_at_the_end"], f["ran_ms"],
                       "yes" if f["restored"] else "NO", "; reported: " + "; ".join(f["problems"]) if f["problems"] else ""))
        session.say("  before: %s; after: %s" % (f["before"], f["after"]))
        for tag in ("a", "b"):
            for cpu, r in sorted(f["records"].get(tag, {}).items()):
                session.say("  record %s cpu %d: %s" % (tag, cpu, ", ".join("%s %s" % (k, v) for k, v in r.items() if k not in ("version", "cpu"))))
        if f["rate"]:
            session.say("  rates: %s" % f["rate"])
    if LEVEL == 26:
        f = facts["level26"]
        session.say("Level 26: verdict %s; av-cam word %s; SCU 0x70 %s%s" % (f["verdict"] or "MISSING", f["avcam_word"], f["scu_0x70"],
                    "; reported: " + "; ".join(f["problems"]) if f["problems"] else ""))
        if f["program_area_physical"]:
            st = lambda v: "STOCK" if v else ("NOT stock" if v is not None else "not read")
            session.say("  program area at %s: SPU stub %s, SPU code %s, MBP0 stub %s, MBP1 stub %s; hello_v1 record area %s"
                        % (f["program_area_physical"], st(f["spu_stub_is_stock"]), st(f["spu_code_is_stock"]), st(f["mbp0_stub_is_stock"]), st(f["mbp1_stub_is_stock"]),
                           "all zero" if f["record_area_all_zero"] else "not read" if f["record_area_all_zero"] is None else "%d non-zero bytes" % f["record_area_nonzero_bytes"]))
    if LEVEL == 22:
        f = facts["level22"]
        session.say("Level 22: verdict %s; SCU 0x70 %s%s; clock/reset %s%s" % (f["verdict"] or "MISSING", f["scu_0x70"], " (after: %s)" % f["scu_after"] if f["scu_after"] else "",
                    ", ".join("%s %s" % kv for kv in f["pbl"].items()), "; reported: " + "; ".join(f["problems"]) if f["problems"] else ""))
        if f["vcd"]:
            session.say("  codec window: " + ", ".join("%s %s" % kv for kv in f["vcd"].items()))
        if f["program_area_physical"]:
            session.say("  program area at %s: head %s, SPU code %s, hello_v1 record area %s" % (f["program_area_physical"],
                        "STOCK" if f["program_head_is_stock"] else "NOT stock", "STOCK" if f["spu_code_is_stock"] else "NOT stock",
                        "all zero" if f["record_area_all_zero"] else "NOT ZERO: hello_v1 must use another place"))
        session.say("  av-cam: " + ", ".join("%s %s" % kv for kv in f["avcam"].items()))
    if LEVEL == 18:
        f = facts["level18"]
        a, m, w = f["av_cam"], f["libmpr"], f["libmpr_mapping"]
        session.say("Level 18 (%s): verdict %s. av-cam.bin: guards %d as in the file, %d not; sites %d stock, %d target, %d other. libmpr.so%s: guards %d as in "
                    "the file, %d not; sites %d stock, %d target, %d other%s"
                    % (f["design"], f["verdict"] or "MISSING", a["same"], a["differs"], a["stock"], a["target"], a["other"],
                       " at %s-%s %s" % (w["start"], w["end"], w["permissions"]) if w else " (not found)", m["same"], m["differs"], m["stock"], m["target"], m["other"],
                       "; reported: " + "; ".join(f["problems"]) if f["problems"] else ""))
        for line in f["not_stock"][:24]:
            session.say("  not stock: " + line)


CLEAR_SHA = None                                   # --clear-result: the SHA-256 the result file on the camera must have to be deleted


def body_clear_result(session, camera, lib):
    """Delete the helper's own result file from the RAM disk, so that another run can follow without a cold boot.
    Only if its content is the result this PC already saved (same SHA-256). Sends no library and writes nothing else."""
    out = session.results["ct6"] = {"library_sent": False, "clear_result": True, "expected_sha256": CLEAR_SHA}
    known_answer(session, camera)
    there, data = read(camera, RESULT_PATH)
    if not there:
        out["result_on_camera_after"] = False
        session.say("There is no result file on the RAM disk. Nothing to clear.")
        return
    out["found_sha256"] = c.sha256(data)
    if c.sha256(data) != CLEAR_SHA:
        raise c.StopTest("the result file on the camera (%d bytes) is not the one named with --clear-result. It is left alone." % len(data))
    session.say("The result file on the camera is the one already saved here (%d bytes). Deleting it." % len(data))
    GUARDS[-1].allow_result_delete = True
    select(camera, RESULT_PATH)
    out["delete_status"], _ = command(camera, FILE_DELETE2, b"\x00\xff")
    session.say("Delete request: status %s" % text(out["delete_status"]))
    out["result_on_camera_after"] = read(camera, RESULT_PATH)[0]
    session.say("Confirmed: no result file on the RAM disk" if out["result_on_camera_after"] is False else "!! the result file is still there")


def body_remove_only(session, camera, lib):
    out = session.results["ct6"] = {"library_sha256": LIB_SHA256, "library_sent": False, "remove_only": True}
    known_answer(session, camera)
    there, data = read(camera, LIB_PATH)
    if not there:
        out["library_on_camera_after"] = False
        session.say("There is no /tmp/jiritsu/libJit.so on the camera. Nothing to remove.")
        return
    if c.sha256(data) != LIB_SHA256:
        raise c.StopTest("the libJit.so on the camera (%d bytes) is not this script's library. It is left alone." % len(data))
    remove(session, camera, out)


# ------------------------------------------------------------ simulated camera

def canned_result():
    """A result in the helper's format, for a simulated camera without the emulator."""
    out = b"readcheck 1 level %d\neuid 0\n== file /proc/version\nLinux (simulated)\n\n== end 18 bytes\n" % LEVEL
    lead = b"== done, bytes written before this line: "
    return out + lead + b"%d\n" % (len(out) + len(lead))


def run_helper(data):
    """What loading the uploaded bytes produces: the real AArch64 code in Unicorn if it is installed, else a canned text."""
    try:
        import emu_built
    except ImportError:
        return canned_result(), "canned"
    dirs = {"/tmp_wbshd", "/sys/module/liro/parameters", "/proc/driver/pcie"}
    files, phys = emu_built.tree(), None
    if LEVEL == 2:
        files["/dev/mem"] = b""
        phys = {emu_built.AVCAM_PHYS: (c.EXTRACTED / AV_FILE).read_bytes()}
    cp = None
    if LEVEL in (3, 4):
        files["/dev/mem"] = b""
        cp = (c.EXTRACTED / CP_FILE).read_bytes()
    if LEVEL == 10:
        files["/dev/mem"] = b""
        cp = emu_built.log_memory()
    if LEVEL == 12:
        files["/dev/mem"] = b""
        cp = emu_built.dmm_model()[1]                      # the firmware's own memory-manager state after four opens and a free, as pages
    if LEVEL in (13, 14):
        files["/dev/mem"] = b""
        cp = emu_built.dmm_state_pages()                   # the firmware's own memory-manager state with nothing opened: a stock camera on stills (F677)
    if LEVEL == 28:
        files["/dev/mem"] = b""
        cp = emu_built.frame_model()[1]                    # the four model rings with one entry of each filled in, and the file's tables
    if LEVEL == 21:
        files["/dev/mem"] = b""
        cp = emu_built.rdc_model()[1]                      # the 25 RDC objects with made-up types in an address pattern
    if LEVEL == 15:
        files["/dev/mem"] = b""
        cp = emu_built.out_model()[1]                      # the baseline's output state, with the firmware's own id table
    if LEVEL in (16, 17):
        files["/dev/mem"] = b""
        cp = emu_built.words_model()                       # the page of the movie size table as the camera held it (request 25)
    if LEVEL == 9:
        files["/dev/mem"] = b""
        files["/log/errlog.bin"] = b"E" * 3000
        dirs = dirs | {"/log"}
        phys = {0x400040000: bytes((k * 31 + 7) & 0xFF for k in range(0x40000))}
    if LEVEL in (5, 6):
        files["/dev/mem"] = b""
        cp = emu_built.level7_memory((c.EXTRACTED / CP_FILE).read_bytes(), emu_built.stock_record())      # a stock camera
    if LEVEL in (7, 8):
        import json
        files["/dev/mem"] = b""
        stock10 = bytes.fromhex(json.loads(RECORDS.read_text(encoding="utf8"))["stock_record_10"])
        cp = emu_built.level7_memory((c.EXTRACTED / CP_FILE).read_bytes(), stock10)
    if LEVEL == 26:
        files["/dev/mem"] = b""
        phys = emu_built.w_model(stock=(c.EXTRACTED / VCD_FILE).read_bytes())       # after a boot: the area at 0x43c000000 with the stock image, an empty record area
    if LEVEL == 22:
        files["/dev/mem"] = b""
        phys = emu_built.v_model(stock=(c.EXTRACTED / VCD_FILE).read_bytes())       # the codec clocked and running with the stock image
    own = None
    if LEVEL in (23, 24, 25):
        files["/dev/mem"] = b""
        phys = {emu_built.VC_SHADOW: (c.EXTRACTED / VCD_FILE).read_bytes()}       # a stock camera: one copy (the shadow) in DMM region 0x22
    if LEVEL in (19, 20):
        files["/proc/self/mem"] = b""
    if LEVEL in (18, 19, 20):
        files["/dev/mem"] = b""
        lname, lbase = emu_built.mp_lib(DESIGN)[:2]          # the library the design's mp_lm table is in: libmpr.so, or appFw.so (lcdcycle_v1)
        files["/proc/self/maps"] = emu_built.mp_maps(name=lname)     # a list of mappings like im.elf's, with that library in it
        lfile = LM_FILE if lname == "libmpr.so" else APPFW_FILE
        av_mem, lm_mem = emu_built.mp_memory((c.EXTRACTED / AV_FILE).read_bytes(), (c.EXTRACTED / lfile).read_bytes(), DESIGN)     # a stock camera
        phys, own = {emu_built.AVCAM_PHYS: av_mem}, {lbase: lm_mem}
    if LEVEL == 27:                                        # the joint model: the helper drives the codec model, the real MIPS stubs run in it
        files["/dev/mem"] = b""
        model = (emu_built.CodecModel(scratch=True, steps_per_ms=200000) if DESIGN == "hello_v4" else emu_built.CodecModel(regs=True) if DESIGN == "hello_v5"
                 else emu_built.CodecModel(job="copy") if DESIGN == "hello_v6" else emu_built.CodecModel())
        run = emu_built.Run27(data, files, dirs, emu_built.k_phys((c.EXTRACTED / VCD_FILE).read_bytes()), model).go()
    else:
        run = emu_built.Run(data, LEVEL, files, dirs, phys, cp=cp, own=own).go()
    if run.bad:
        raise AssertionError("emulated helper: " + run.bad)
    return run.writes[emu_built.RESULT], "emulated"


def make_sim(lib, files=None, fault=None):
    import ct1_sim

    class Sim(ct1_sim.SimDriver):
        def __init__(self):
            super().__init__("senser", rules=rules(lib))
            self.fs = {"/usr/share/pmbp/DeviceInfo.xml": (c.EXTRACTED / KNOWN_FILE).read_bytes()}
            self.fs.update(files or {})
            self.loads, self.how, self.dead = 0, None, False

        def write(self, data, ep=0):
            if self.dead:
                raise ct1_sim.SimUsbError("the simulated camera no longer answers")
            return super().write(data, ep)

        def _handle(self, pfunc, body):
            try:
                name = c.classify_service_packet(pfunc, body, self.rules)
            except c.GuardRefusal as exc:
                self.unexpected.append(("service packet", pfunc, body[:16].hex(), str(exc)))
                return 0xEE, b""
            st = lambda v: struct.pack("<I", v)
            if name == "SET_FILE_PATH":
                p = body[5:].decode()
                self._path = p if p.startswith("/tmp/jiritsu") else posixpath.normpath("/tmp/jiritsu/" + p)
                return 0, st(ST_OK)
            path, self._path = self._path, None                         # the camera forgets the path after one use
            if path is None:
                return 0, st(0x10000201)
            if name == "GET_FILE2":
                return (0, st(ST_OK) + self.fs[path]) if path in self.fs else (0, st(ST_NO_FILE))
            if name == "SET_FILE2":
                if body[4:7] != b"\x00\xff\x00":
                    return 0, st(0x10000201)
                if path == LIB_PATH.decode() and "/tmp/jbusy" in self.fs:
                    return 0, st(ST_BUSY)
                if fault == "dead":
                    self.dead = True
                    self.fs[path] = body[7:]                            # written, then the service process is gone
                    raise ct1_sim.SimUsbError("the simulated camera died during the write")
                self.fs[path] = body[7:]
                if path != LIB_PATH.decode():
                    return 0, st(ST_OK)
                if fault == "load":
                    return 0, st(ST_LOAD_FAILED)
                self.loads += 1
                if "/tmp_wbshd/readcheck_result.txt" not in self.fs:
                    self.fs["/tmp_wbshd/readcheck_result.txt"], self.how = run_helper(body[7:])
                return 0, st(ST_OK)
            if name == "FILE_DELETE2":
                if fault == "sticky" or path not in self.fs:
                    return 0, st(ST_REMOVE_FAILED)
                del self.fs[path]
                return 0, st(ST_OK)
            raise AssertionError(name)

    return Sim()


def simulate(lib, body, files=None, fault=None):
    import contextlib
    import io
    c.use_pmca()
    session = c.Session("simulated", write=False, test="CT6")
    sim = make_sim(lib, files, fault)
    stopped = None
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            service_session(session, sim, lambda cam: body(session, cam, lib), lib)
        except c.StopTest as exc:
            stopped = str(exc)
    return session, sim, stopped


def sent(session):
    return [e["name"] for e in session.events if e["kind"] == "service_out"]


def dry_run_lines(lib):
    session, sim, stopped = simulate(lib, body_run)
    if sim.unexpected or stopped:
        raise AssertionError("simulated run did not go through: %r %r" % (sim.unexpected, stopped))
    lines = ["To the service device 054C:0336, after the switch and authentication of CT1:"]
    for e in session.events:
        if e["kind"] != "service_out":
            continue
        data = bytes.fromhex(e["hex"])
        if e["name"] == "SET_FILE2":
            shown = data[:7].hex(" ") + " + the %d bytes of %s (SHA-256 %s)" % (len(data) - 7, LIB.name, LIB_SHA256)
        else:
            shown = data.hex(" ")
        note = ": " + data[5:].decode() if e["name"] == "SET_FILE_PATH" else ""
        lines.append("  service packet type 0x%02x, body %s  (%s%s)" % (e["pfunc"], shown, e["name"], note))
    lines.append("  vendor request out: request 1, value 0xc800, index 0x2855, no data  (STOP_SENSER)")
    lines.append("In the simulated camera the library was loaded %d time(s) (%s helper) and was gone afterwards: %s"
                 % (sim.loads, sim.how, LIB_PATH.decode() not in sim.fs))
    lines.append("Refused by the guard (checked now): " + ", ".join(refusals(lib)))
    return lines


def refusals(lib):
    """Packets the rule list must refuse; raises if one is allowed."""
    other = bytearray(lib)
    other[len(other) // 2] ^= 1
    out = []
    for name, pfunc, cat, code, payload in (
            ("the library with one bit changed", c.PFUNC_ADJUST, 0x1001, SET_FILE2, b"\x00\xff\x00" + bytes(other)),
            ("any other file content", c.PFUNC_ADJUST, 0x1001, SET_FILE2, b"\x00\xff\x00hello"),
            ("a write with the code in its short form", c.PFUNC_ADJUST, 0x1001, 0x0010, b"\x00\xff\x00" + lib),
            ("a write to the memory card", c.PFUNC_ADJUST, 0x1001, SET_FILE2, b"\x01\xff\x00" + lib),
            ("a path off the list", c.PFUNC_ADJUST, 0x1001, SET_FILE_PATH, b"\x00../../etc/passwd"),
            ("delete with another selector", c.PFUNC_ADJUST, 0x1001, FILE_DELETE2, b"\x00\x04"),
            ("the older delete command", c.PFUNC_ADJUST, 0x1001, 0x4009, b"\x00\x02"),
            ("format of the service partition", c.PFUNC_ADJUST, 0x1001, 0x4003, b"\x00"),
            ("the mode command", c.PFUNC_ADJUST, 0x1001, 0x4001, b"\x01\x01"),
            ("the start command", c.PFUNC_ADJUST, 0x1001, 0x4004, b"\x00"),
            ("firmware through the service route", c.PFUNC_ADJUST, 0x1001, 0x4006, b"\x00"),
            ("backup write", c.PFUNC_ADJUST, 0x0603, 2, b"\xf2\x1b\xcf\x02\x02"),
            ("coprocessor flash write", c.PFUNC_ADJUST, 0x060B, 2, b"\x00" * 8),
            ("coprocessor debug write", c.PFUNC_ADJUST, 0x060B, 0x82, b"\x00" * 8),
            ("firmware update", 0x20, 0, 0, b"")):
        try:
            c.classify_service_packet(pfunc, struct.pack("<HH", cat, code) + payload, rules(lib))
        except c.GuardRefusal:
            out.append(name)
            continue
        raise AssertionError("the guard would allow: %s" % name)
    return out


def selftest(lib):
    done = []

    def check(cond, what):
        if not cond:
            raise AssertionError("self-test failed: " + what)
        done.append(what)

    W, D = "SET_FILE2", "FILE_DELETE2"
    s, sim, stopped = simulate(lib, body_run)
    r = s.results["ct6"]
    check(not stopped and not sim.unexpected and sent(s).count(W) == 1 and sent(s).count(D) == 1, "normal run: one write, one delete, nothing off the list")
    check(sent(s).index(D) < len(sent(s)) - 2 and sent(s)[-1] == "GET_FILE2", "normal run: the delete comes before the result is read")
    check(LIB_PATH.decode() not in sim.fs and r["library_on_camera_after"] is False and sim.loads == 1, "normal run: loaded once, library gone and confirmed gone")
    check(r["result"]["header_ok"] and r["result"]["complete"] and r["result"]["euid"] == 0, "normal run: result fetched and well-formed (%s helper)" % sim.how)
    if LEVEL == 5 and sim.how == "emulated":
        f = r["result"]["level56"]
        check(f["done"] and f["as_expected"] == 14 and f["written"] == 14 and not f["problems"] and f["released"] == 1, "normal run, level 5: 14 sites as expected, 14 written and read back, done")
    if LEVEL == 6 and sim.how == "emulated":
        f = r["result"]["level56"]
        check(f["nothing_to_do"] and f["already"] == 14 and not f["written"] and not f["problems"], "normal run, level 6 on a stock camera: nothing to do, nothing written")
    if LEVEL == 10 and sim.how == "emulated":
        f = r["result"]["level10"]
        check(f["complete"] and f["kprint_bytes"] == 0x20000 and f["kprint_header_ok"] and f["initialised"] and f["boottime_bytes"] == 0x20000 and not f["problems"] and f["released"] == 1,
              "normal run, level 10: both coprocessor logs copied out whole, the kprint header and its first line found")
    if LEVEL == 13 and sim.how == "emulated":
        f = r["result"]["level1314"]
        check(f["done"] and f["checks_passed"] and f["as_expected"] == 4 and f["written"] == 4 and not f["problems"] and f["released"] == 1 and f["design"] == DESIGN and f["verb"] == "apply",
              "normal run, level 13 (%s): the checks pass, 4 words as expected, 4 written and read back, done" % DESIGN)
    if LEVEL == 14 and sim.how == "emulated":
        f = r["result"]["level1314"]
        check(f["nothing_to_do"] and f["checks_passed"] and f["already"] == 4 and not f["written"] and not f["problems"] and f["verb"] == "put back",
              "normal run, level 14 on a stock camera (%s): nothing to do, nothing written" % DESIGN)
    if LEVEL in (16, 17):
        import json
        n = len(json.loads((HERE.parent.parent / "modding" / "designs" / (DESIGN + ".json")).read_text(encoding="utf8"))["sites"])
    if LEVEL == 16 and sim.how == "emulated":
        f = r["result"]["level1617"]
        check(f["done"] and f["checks_passed"] and f["as_expected"] == n and f["written"] == n and not f["problems"] and f["released"] == 1 and f["design"] == DESIGN and f["verb"] == "apply",
              "normal run, level 16 (%s): the checks pass, %d word(s) as expected, written and read back, done" % (DESIGN, n))
    if LEVEL == 17 and sim.how == "emulated":
        f = r["result"]["level1617"]
        check(f["nothing_to_do"] and f["checks_passed"] and f["already"] == n and not f["written"] and not f["problems"] and f["verb"] == "put back",
              "normal run, level 17 on a stock camera (%s): nothing to do, nothing written" % DESIGN)
    if LEVEL == 12 and sim.how == "emulated":
        f = r["result"]["level12"]
        check(f["complete"] and not f["problems"] and f["released"] == 1 and sorted(f["ranges"]) == ["command_log", "globals", "group_records", "movie_tables", "unit_records", "workspace", "write_buffers"]
              and f["unit_records_equal_to_the_file"] and f["in_use_by_memory_id"] == {"0x43e": 1, "0x4b8": 1, "0x4af": 1} and f["write_buffer_change_would_take_effect"] is False
              and f["command_log"]["opens_by_memory_id"] == {"0x43e": 2, "0x4b8": 1, "0x4af": 1},
              "normal run, level 12: seven ranges copied out and decoded; the model's open units, its 0x89 division and its command log are reported")
    if LEVEL == 28 and sim.how == "emulated":
        f = r["result"]["level28"]
        check(f["complete"] and not f["problems"] and not f["decode_problems"] and len(f["ranges"]) == 3 and f["released"] == 1
              and f["index"] == {"layout": 3, "tracking": 5, "frames": 7, "afwindow": 9} and f["layout_now"]["kinds"][0]["rect_in_640x480"] == [0, 45, 640, 404]
              and f["tracking_now"]["aspect"] == 4 and f["tracking_now"]["kind_selector"] == 1 and f["frames_now"]["count"] == 1
              and f["frames_now"]["frames"][0]["rect"] == [100, 50, 80, 60] and f["afwindow_now"]["kind_selector_0x244"] == 1
              and f["tables_16x9_rear_panel"] == {"af_window": [0, 38, 640, 404], "remote_send": [0, 38, 640, 404], "tracking": [0, 38, 640, 404]}
              and f["tracking_check_now"]["expected"] == [0, 38, 640, 404] and f["tracking_check_now"]["result"].startswith("FAIL"),
              "normal run, level 28: three ranges copied out and decoded: the ring entries the model filled in, the stock tables, and the tracking "
              "check repeated (a rectangle 7 units off is reported as failing)")
    if LEVEL == 21 and sim.how == "emulated":
        f = r["result"]["level21"]
        check(f["complete"] and not f["problems"] and not f["decode_problems"] and len(f["ranges"]) == 2 and len(f["ports"]) == 25
              and [x["encoding_type"] for x in f["ports"]] == [(k % 16) + 1 for k in range(25)] and f["released"] == 1,
              "normal run, level 21: two ranges copied out; all 25 RDC objects found with their vtable and port, and their types decoded")
    if LEVEL == 15 and sim.how == "emulated":
        f = r["result"]["level15"]
        check(f["complete"] and not f["problems"] and not f["decode_problems"] and len(f["ranges"]) == 7 and f["window"]["readout"] == [7032, 4688]
              and [x["format_code"] for x in f["output_records"]] == [2, 2, 2, 2] and f["output_records"][0]["buffer_id_by_size"] == "0x2d9" and f["saved_copy_equal"]
              and f["for_a_3840x2560_picture"] == [{"format_code": 2, "bytes": 12288000, "buffer_id": "0x2d9", "fits_the_stock_buffers": True}]
              and f["resize_result"]["takes_every_row"] and f["resize_settings"]["as_emu_rc_fit_assumes"] and f["resize_working_values"]["pixel_aspect_q12"] == 0xD80
              and f["id_table"]["rows"] == 339 and f["id_table"]["end_row_at"] == "0x1faee18" and f["id_table"]["equal_to_the_file"] and not f["id_table"]["has_id_0x43f"],
              "normal run, level 15: seven ranges copied out and decoded: the output records with their format code, the verdict for a 3840x2560 picture, "
              "the resize result and settings, and the id table equal to the camera's DmmCfg.bin")
    if LEVEL == 9 and sim.how == "emulated":
        f = r["result"]["level9"]
        check(f["log_entries"] == ["errlog.bin"] and f["klog_bytes"] == 0x40000 and f["klog_sha256"] == c.sha256(bytes((k * 31 + 7) & 0xFF for k in range(0x40000))) and not f["klog_problems"],
              "normal run, level 9: /log listed and the kernel log buffer extracted byte for byte")
    if LEVEL == 8 and sim.how == "emulated":
        f = r["result"]["level8"]
        n_state = 5 if DESIGN == "og4k_data_v1" else 6
        check(f["complete"] and f["record"] == "stock" and f["sites"] == {"stock": 13, "changed": 0, "OTHER": 0} and len(f["state"]) == n_state,
              "normal run, level 8 (%s): the record and the 13 sites reported, %d pieces of state copied out" % (DESIGN, n_state))
        if n_state == 6:
            check(f.get("sensor_shadow", {}).get("0x01") == 11, "normal run, level 8: the sensor register shadow is parsed (the model holds the file's start value, mode 11)")
    if LEVEL == 7 and sim.how == "emulated":
        l7 = r["result"]["level7"]
        r8 = l7["records"].get("0x8c0", {})
        check(l7["complete"] and not l7["problems"] and l7["modes"] == "30" and r8.get("index") == 10 and r8.get("bytes_different_from_emulated_stock") == 0
              and r8.get("bytes_different_from_emulated_design") == 24 and "0xa100" in l7["records"],
              "normal run, level 7: chain followed; the record of mode 0x8c0 comes back and is compared with the emulated stock and design records")
    if LEVEL == 4 and sim.how == "emulated":
        l4 = r["result"]["level4"]
        check(l4["page_zero_before"] and l4["write_seen"] and l4["restored"] and l4["steps"] == [1, 2, 3, 4, 5] and l4["released"] == 1 and not l4["problems"],
              "normal run, level 4: page zero, write seen, page restored, buffer released")
    if LEVEL == 3 and sim.how == "emulated":
        l3 = r["result"]["level3"]
        check(l3["same"] == 12 and not l3["differs"] and l3["released"] == 1 and not l3["stopped"], "normal run, level 3: eleven pages and one cell reported equal, buffer released")
    if LEVEL == 23 and sim.how == "emulated":
        f = r["result"]["level23"]
        check(f["verdict"] == "READY" and f["design"] == DESIGN and len(f["copies_at"]) == 1 and f["sites"]["stock"] >= 1 and not f["sites"]["target"]
              and not f["guards"]["differs"] and not f["problems"], "normal run, level 23 (%s): one copy found, every guard as in the file, every site stock, READY" % DESIGN)
    if LEVEL == 24 and sim.how == "emulated":
        f = r["result"]["level2425"]
        check(f["done"] and f["checks_passed"] and f["as_expected"] == f["written"] >= 1 and len(f["copies_at"]) == 1 and not f["problems"] and f["verb"] == "apply",
              "normal run, level 24 (%s): the checks pass, every site as expected, written and read back, done" % DESIGN)
    if LEVEL == 25 and sim.how == "emulated":
        f = r["result"]["level2425"]
        check(f["nothing_to_do"] and f["checks_passed"] and f["already"] >= 1 and not f["written"] and not f["problems"] and f["verb"] == "put back",
              "normal run, level 25 on a stock camera (%s): nothing to do, nothing written" % DESIGN)
    if LEVEL in (19, 20) and sim.how == "emulated":
        import json
        ps = json.loads((HERE.parent.parent / "modding" / "designs" / (DESIGN + ".json")).read_text(encoding="utf8"))["patches"]
        n_av, n_lm = sum(1 for x in ps if x["binary"] == "av-cam.bin"), sum(1 for x in ps if x["binary"] != "av-cam.bin")
        f = r["result"]["level1920"]
    if LEVEL == 19 and sim.how == "emulated":
        check(f["done"] and f["checks_passed"] and f["as_expected"] == {"av_cam": n_av, "libmpr": n_lm} and f["written"] == {"av_cam": n_av, "libmpr": n_lm}
              and not f["problems"] and f["design"] == DESIGN and f["verb"] == "apply" and f["libmpr_mapping"]["permissions"] == "r-xp",
              "normal run, level 19 (%s): the checks pass, %d + %d sites as expected, written and read back, done" % (DESIGN, n_av, n_lm))
    if LEVEL == 20 and sim.how == "emulated":
        check(f["nothing_to_do"] and f["checks_passed"] and f["already"] == {"av_cam": n_av, "libmpr": n_lm} and not sum(f["written"].values()) and not f["problems"]
              and f["verb"] == "put back", "normal run, level 20 on a stock camera (%s): nothing to do, nothing written" % DESIGN)
    if LEVEL == 27 and sim.how == "emulated":
        f = r["result"]["level27"]
        # each design's result in the joint model, which matches the camera: v1 RAN: SPU (F783), v2 stalls (F786), v3 all three
        want = {"hello_v3": "RAN: SPU+MBP0+MBP1", "hello_v4": "RAN: SPU+MBP0+MBP1", "hello_v2": "NO SIGN OF LIFE"}.get(DESIGN, "RAN: SPU")
        mags = ["HELO", "MBP0", "MBP1"] if DESIGN in ("hello_v3", "hello_v4") else ["HELO", "\x00" * 4, "\x00" * 4]
        check(f["verdict"] == want and f["stores"] == 56 and f["restored"] and f["after"] and f["after"][3] == "as before"
              and [f["records"]["b"][k]["magic"] for k in range(3)] == mags and not f["problems"],
              "normal run, level 27 (%s, joint model): 56 control stores, verdict %s, the codec off again as before, every byte put back" % (DESIGN if DESIGN.startswith("hello_") else "hello_v1", want))
        if DESIGN == "hello_v6":
            j, s0 = f["job"] or {}, f["records"]["b"][0]
            check(j.get("magic_ok") and j.get("guards") == 1 and j.get("tries") == 3 and [t["outcome"] for t in j.get("per_try", [])] == [3, 3, 3]
                  and all(t["y_copy"] and t["c_copy"] and t["canary_words_changed"] == 0 for t in j["per_try"]) and s0.get("flags") == "0x444f000f",
                  "normal run, level 27 (hello_v6, engine model 'copy'): three tries decoded, each done, output equal to the source, canaries intact")
        if DESIGN == "hello_v5":
            g, s0 = f["registers"] or {}, f["records"]["b"][0]
            check(g.get("header_ok") and g.get("passes") == 2 and len(g.get("pass1", {})) == 224 and g.get("fmc_idle") == {0: True, 1: True}
                  and sorted(g.get("changed_between_passes", {})) == ["core0+0x028 (core_global, 0xbf068028)", "core1+0x028 (core_global, 0xbf078028)"]
                  and s0.get("done") == {"block_setup": True, "pass1": True, "pass2": True, "compare": True} and s0.get("words_differing_pass1_pass2") == 2,
                  "normal run, level 27 (hello_v5): the dump decodes: 224 named registers, two passes, the two live words found, both FMCs idle")
    if LEVEL == 26 and sim.how == "emulated":
        f = r["result"]["level26"]
        check(f["verdict"] == "PROGRAM AREA READ" and f["program_area_physical"] == "0x000000043c000000" and f["spu_stub_is_stock"] and f["spu_code_is_stock"]
              and f["mbp0_stub_is_stock"] and f["mbp1_stub_is_stock"] and f["record_area_all_zero"] and not f["problems"],
              "normal run, level 26: the area at 0x43c000000 read; all three stubs and the SPU code stock; the record area empty")
    if LEVEL == 22 and sim.how == "emulated":
        f = r["result"]["level22"]
        check(f["verdict"] == "CODEC ON, RUNNING (+0x80 = 0)" and f["clocked"] and f["program_head_is_stock"] and f["spu_code_is_stock"] and f["record_area_all_zero"]
              and len(f["vcd"]) == 6 and len(f["pbl"]) == 4 and len(f["avcam"]) == 9 and not f["problems"],
              "normal run, level 22: codec clocked and running; six window registers, the stock program head and SPU code, an empty record area")
    if LEVEL == 18 and sim.how == "emulated":
        import json
        ps18 = json.loads((HERE.parent.parent / "modding" / "designs" / (DESIGN + ".json")).read_text(encoding="utf8"))["patches"]
        n = len(ps18)
        import emu_built
        lm_guards = sum(1 for e in emu_built.mp_tables(DESIGN)[3] if not e[2])       # the guards of the mp_lm table, as its header lists them
        f = r["result"]["level18"]
        check(f["verdict"] == "READY" and f["design"] == DESIGN and f["av_cam"]["stock"] + f["libmpr"]["stock"] == n and not f["problems"] and not f["not_stock"]
              and f["av_cam"]["same"] and f["libmpr"]["same"] == lm_guards and f["libmpr_mapping"]["permissions"] == "r-xp",
              "normal run, level 18 (%s): %d sites reported stock, every guard as in the file, the verdict is READY" % (DESIGN, n))
    if LEVEL == 2 and sim.how == "emulated":
        check(r["result"]["level2"]["same"] == 3 and not r["result"]["level2"]["differs"], "normal run, level 2: three ranges reported equal to the update file")
    check(sim.service_writes[sent(s).index(W)][12 + 7:] == lib, "normal run: the bytes that left are the pinned library")
    check(sim.vendor_requests[-1][:3] == (1, 0xC800, 0x2855), "normal run: the stop request was sent")

    for label, files in (("a library already there", {"/tmp/jiritsu/libJit.so": b"someone else's"}),
                         ("this library already there", {"/tmp/jiritsu/libJit.so": lib}),
                         ("a result already there", {"/tmp_wbshd/readcheck_result.txt": b"old"}),
                         ("/tmp/jbusy there", {"/tmp/jbusy": b""})):
        s, sim, stopped = simulate(lib, body_run, files)
        check(stopped and W not in sent(s) and D not in sent(s) and all(sim.fs[k] == v for k, v in files.items()),
              "%s: stops, nothing written, nothing deleted" % label)
    s, sim, stopped = simulate(lib, body_run, {"/usr/share/pmbp/DeviceInfo.xml": b"<other/>"})
    check(stopped and sent(s) == ["SET_FILE_PATH", "GET_FILE2"], "known answer wrong: stops after the first read")

    s, sim, stopped = simulate(lib, body_run, fault="load")
    check(stopped and sent(s).count(D) == 1 and LIB_PATH.decode() not in sim.fs and s.results["ct6"]["write_status"] == ST_LOAD_FAILED,
          "camera cannot load the library: it is still removed, and the run reports no result")
    s, sim, stopped = simulate(lib, body_run, fault="sticky")
    check(s.results["ct6"]["library_on_camera_after"] is True and any("MAY STILL BE" in e.get("text", "") for e in s.events),
          "remove fails: said aloud, recorded")
    s, sim, stopped = simulate(lib, body_run, fault="dead")
    check(stopped and s.results["ct6"]["library_on_camera_after"] is None and "write_error" in s.results["ct6"]
          and sim.vendor_requests[-1][:3] == (1, 0xC800, 0x2855), "camera stops answering during the write: recorded as unknown, stop request still sent")

    s, sim, stopped = simulate(lib, body_remove_only, {"/tmp/jiritsu/libJit.so": lib})
    check(not stopped and W not in sent(s) and LIB_PATH.decode() not in sim.fs, "--remove-only: removes this script's library, writes nothing")
    s, sim, stopped = simulate(lib, body_remove_only, {"/tmp/jiritsu/libJit.so": b"someone else's"})
    check(stopped and D not in sent(s) and "/tmp/jiritsu/libJit.so" in sim.fs, "--remove-only: leaves a library that is not ours")
    s, sim, stopped = simulate(lib, body_remove_only)
    check(not stopped and D not in sent(s), "--remove-only: nothing there, nothing sent but two reads")

    def stateful(body):                              # guard rules that depend on what was sent before
        s, sim, stopped = simulate(lib, lambda session, cam, _lib: body(cam))
        return stopped, sim, s
    stopped, sim, s = stateful(lambda cam: (select(cam, RESULT_PATH), command(cam, SET_FILE2, b"\x00\xff\x00" + lib)))
    check(stopped and "path selected" in stopped and W not in sent(s), "guard: a write when another path is selected is refused")
    stopped, sim, s = stateful(lambda cam: command(cam, SET_FILE2, b"\x00\xff\x00" + lib))
    check(stopped and W not in sent(s), "guard: a write with no path selected is refused")
    stopped, sim, s = stateful(lambda cam: (select(cam, BUSY_PATH), command(cam, FILE_DELETE2, b"\x00\xff")))
    check(stopped and D not in sent(s), "guard: a delete when another path is selected is refused")
    stopped, sim, s = stateful(lambda cam: (select(cam, LIB_PATH), command(cam, SET_FILE2, b"\x00\xff\x00" + lib),
                                            select(cam, LIB_PATH), command(cam, SET_FILE2, b"\x00\xff\x00" + lib)))
    check(stopped and "second file write" in stopped and sent(s).count(W) == 1, "guard: a second write in one session is refused")
    check(len(refusals(lib)) == 15, "guard: 15 packets that must never leave are refused")
    global CLEAR_SHA
    saved, CLEAR_SHA = CLEAR_SHA, c.sha256(b"an earlier result")
    R = "/tmp_wbshd/readcheck_result.txt"
    s, sim, stopped = simulate(lib, body_clear_result, {R: b"an earlier result"})
    check(not stopped and R not in sim.fs and W not in sent(s) and sent(s).count(D) == 1, "--clear-result: deletes the result file whose content matches, sends no library")
    s, sim, stopped = simulate(lib, body_clear_result, {R: b"some other content"})
    check(stopped and sim.fs.get(R) == b"some other content" and D not in sent(s), "--clear-result: leaves a result file with other content")
    s, sim, stopped = simulate(lib, body_clear_result)
    check(not stopped and D not in sent(s), "--clear-result: nothing there, nothing deleted")
    stopped, sim, s = stateful(lambda cam: (select(cam, RESULT_PATH), command(cam, FILE_DELETE2, b"\x00\xff")))
    check(stopped and D not in sent(s), "guard: a delete of the result file without the content check is refused")
    s, sim, stopped = simulate(lib, body_run, {R: b"an earlier result"})
    check(not stopped and sent(s).count(D) == 2 and sent(s).count(W) == 1 and s.results["ct6"]["result"]["header_ok"] and sim.fs[R] != b"an earlier result",
          "--clear-result with a run: the earlier result is deleted, then the run goes through and a new result is fetched")
    s, sim, stopped = simulate(lib, body_run, {R: b"some other content"})
    check(stopped and W not in sent(s) and D not in sent(s) and sim.fs[R] == b"some other content", "--clear-result with a run: a result with other content stops the run, nothing written")
    CLEAR_SHA = saved
    check(check_result(canned_result())["complete"] and not check_result(canned_result()[:-3])["complete"], "result check: a cut-off result is reported as not complete")
    return done


# ------------------------------------------------------------ live

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--go", action="store_true")
    parser.add_argument("--remove-only", action="store_true")
    parser.add_argument("--clear-result", metavar="SHA256", help="before the run, delete the helper's result file from the RAM disk, only if its SHA-256 is this (a result already saved here)")
    parser.add_argument("--clear-only", action="store_true", help="with --clear-result: only delete that file; send no library")
    parser.add_argument("--level", type=int, choices=sorted(set(LIBS) | {13, 14, 16, 17, 18, 19, 20, 23, 24, 25}), default=1, help="which pinned build to use (default 1)")
    parser.add_argument("--design", choices=["og4k_data_v1"] + sorted(DESIGN_LIBS), default="og4k_data_v1",
                        help="for levels 5, 6 and 8: whose site table (default og4k_data_v1); for levels 13 and 14: dmmwb4080_v1 or dmmwb4688_v1; "
                             "for levels 16 and 17: outsz2560_v1, og2560e4_v1, og57cp_v1, og57cp_v2, og57cp_v3 or lcdfill_v1; for level 18: ogfile2560_hs_v1, ogfile2560_s_v1, ogfile2560_hs_s_v1, ogfile57_v1 or ogfile57r300_v1; "
                             "for levels 19 and 20: ogfile2560_hs_v1, ogfile2560_hs_s_v1, ogfile57_v1 or ogfile57r300_v1")
    parser.add_argument("--firmware-shown")
    parser.add_argument("--library-sha256", help="the SHA-256 of the library you reviewed; must equal the pinned one")
    args = parser.parse_args()
    global LEVEL, LIB, LIB_SHA256, DESIGN
    LEVEL, DESIGN = args.level, args.design
    if DESIGN == "og4k_data_v1":
        if args.level not in LIBS:
            raise SystemExit("--level %d needs --design with one of: %s. Nothing was sent."
                             % (args.level, ", ".join(sorted(d for d in DESIGN_LIBS if args.level in DESIGN_LIBS[d]))))
        LIB, LIB_SHA256 = HERE / "helper" / LIBS[args.level][0], LIBS[args.level][1]
    elif LEVEL in DESIGN_LIBS[DESIGN]:
        LIB, LIB_SHA256 = HERE / "helper" / DESIGN_LIBS[DESIGN][LEVEL][0], DESIGN_LIBS[DESIGN][LEVEL][1]
    else:
        raise SystemExit("--design %s has builds of levels %s only. Nothing was sent." % (DESIGN, sorted(DESIGN_LIBS[DESIGN])))
    import os
    os.environ["CT6_DESIGN"] = DESIGN                 # for the emulated helper of the self-test (helper/emu_built.py)
    lib = library()
    if args.dry_run or args.selftest:
        if args.go:
            raise SystemExit("--go cannot be combined with --dry-run or --selftest")
        if args.selftest:
            for line in selftest(lib):
                print("PASS  " + line)
            print("all checks passed; nothing was sent to any device")
        else:
            print("\n".join(dry_run_lines(lib)))
        return
    if not args.go or args.firmware_shown != c.EXPECTED_FIRMWARE or args.library_sha256 != LIB_SHA256:
        raise SystemExit("A live run needs --go, --firmware-shown %s and --library-sha256 with the hash in README.md. Nothing was sent."
                         % c.EXPECTED_FIRMWARE)
    refusals(lib)
    selftest(lib)                                   # the flow must pass on the simulated camera on the day, before the real one
    import ct1_stage2_service as service
    global CLEAR_SHA
    CLEAR_SHA = args.clear_result
    body = body_clear_result if (args.clear_result and args.clear_only) else body_remove_only if args.remove_only else body_run
    run_name = "level%d_run" % LEVEL + ("" if DESIGN == "og4k_data_v1" else "_" + DESIGN)
    with c.Session("clear_result" if (args.clear_result and args.clear_only) else "remove_only" if args.remove_only else run_name, test="CT6") as session:
        session.results.update(firmware_shown_on_camera=args.firmware_shown, level=LEVEL, design=DESIGN)
        inner = service.connect(session)
        try:
            service_session(session, inner, lambda cam: body(session, cam, lib), lib)
        finally:
            time.sleep(3)
            c.print_pnp(session, "after the stop request")
            out = session.results.get("ct6", {})
            print("Library sent: %s. On the camera now: %s." % (
                "yes" if out.get("library_sent") else "no",
                {False: "no (confirmed)", True: "YES", None: "not sent" if not out.get("library_sent") and not args.remove_only else "UNKNOWN"}[out.get("library_on_camera_after")]))
            print("When this test sequence is over, cold boot the camera (battery out for 10 seconds). A cold boot, or a restart, also undoes "
                  "whatever levels 5, 13, 16 and 19 wrote: do not cold boot between the steps of one test.")


if __name__ == "__main__":
    main()
