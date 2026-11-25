/*
 * Sony OpenGate Studio — Volatile RAM Read/Write Helper (readcheck.c)
 * Copyright (C) 2026 ArcaneLantern & Sony OpenGate Studio Contributors
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */
/*
 * readcheck: look-only helper for the read check of modding/USB_READ_CHECK_DESIGN.md (A7 IV 6.02).
 *
 * NOT RUN ON A CAMERA. Written for review. Running it is the owner's decision (CAMERA_REQUESTS.md, B2).
 *
 * How it would run: the service file-write command loads /tmp/jiritsu/libJit.so with dlopen right after
 * writing it (libJiritsu.so adj_cmd_set_file2, finding F409). Loading runs the constructor below, once, inside
 * the service process; the firmware then calls dlclose.
 *
 * What it does, complete:
 *   level 1  reads a fixed list of /proc and /sys files and lists two directories        (reads only)
 *   level 2  level 1, then maps three ranges of the kernel's copy of av-cam.bin through /dev/mem,
 *            read-only, and prints their SHA-256 next to the values computed from the update file
 *   level 3  level 1, then reads twelve 4 KB pages of coprocessor memory into a buffer, one at a time,
 *            with the camera's own transfer function, and prints their SHA-256 the same way. Direction
 *            is always coprocessor to buffer. It is the only level that calls outside this file: three
 *            functions of libsencore.so, which is already loaded in the process (finding F512).
 *   level 4  level 1, then ONE WRITE TEST on coprocessor memory: 64 bytes at 0xf31f00, in the padding after
 *            the end of the image's constant data, read back, then zeros written back and read back again. It is the only level
 *            that changes any memory other than its own buffer. The address and the length are constants
 *            in one function; nothing else in this file can make a transfer towards the coprocessor.
 *   level 5  level 1, then THE TEST CHANGE: the 13 sensor and record sites of the design og4k_data_v1, and
 *            24 bytes of the stored drive-parameter record of mode 0x8c0 (found through three pointers), are
 *            written into coprocessor memory. Every site must hold its stock bytes first; each write is read
 *            back; on any mismatch everything written is put back. Nothing is written outside those sites'
 *            64-byte lines. A cold boot (battery out) undoes it: the image is reloaded from flash.
 *   level 6  the same code with the two byte sets exchanged: puts the stock bytes back.
 *   level 7  level 1, then READ-ONLY: follows three pointers in coprocessor memory from the sensor object to
 *            the array of stored drive-parameter records (finding F520) and copies out the object, the list of
 *            mode ids and the records of two modes. Every transfer is coprocessor to buffer.
 *   level 8  level 7, then more READ-ONLY reads: what each of the 14 sites of the test change holds now, and five
 *            small pieces of the coprocessor's working state that show which sizes it computed for the mode last
 *            entered. Every transfer is coprocessor to buffer.
 *   level 9  level 1, then READ-ONLY on the main processor only: the first 2 KB of each file in /log (the camera's own
 *            log partition), and the kernel's log buffer, 256 KB of main memory at the address its command line
 *            names (klog.addr), read through /dev/mem. No coprocessor transfer, no library call.
 *   level 10 level 1, then READ-ONLY: the coprocessor's kprint log and boot-time log, 64 pages at fixed addresses.
 *   level 12 level 1, then READ-ONLY: the coprocessor's memory-manager state (finding F671). Whole 4 KB pages, every
 *            transfer coprocessor to buffer: the page of the manager's pointers, its copies of the unit and group records,
 *            the camera core's write-buffer records and movie size table (all at fixed addresses), then the manager's
 *            workspace and its command log, found through two pointers read from the first page. (There is no level 11
 *            build: that number is a proposal in README.md.)
 *   level 13 level 1, then A CHANGE OF FOUR WORDS in the memory manager's copy of its unit records (findings F671, F674;
 *            modding/DMMWB_V1.md): the size of the two write-buffer records of layout 0x8a, and the key of the two of layout
 *            0x89. Before anything is written: no unit made from the present records may exist, the four records and the
 *            parent's must be as in the file, and two units of the new size must fit the parent. Each write is one 64-byte
 *            line, read first, with four bytes replaced, and is read back; on any mismatch everything written is put
 *            back. A cold boot undoes it: the tables are rebuilt from /cp/DmmCfg.bin.
 *   level 14 the same code with the two byte sets exchanged: puts the file's words back.
 *   level 15 level 1, then READ-ONLY: the movie output state (finding F684). Whole 4 KB pages at fixed addresses, every
 *            transfer coprocessor to buffer: the camera core's context with its output records, their saved copies, the
 *            movie size table, the resize calculation's state and settings, and the memory manager's id table.
 *   level 16 level 1, then A CHANGE OF A FEW WORDS in a RAM table of the coprocessor (a design made by build/build_ram_words.py;
 *            the first is the output size of the stock 4K size class in the movie size table, finding F684). Before anything
 *            is written the bytes beside the sites must be as listed. Each write is one 64-byte line, read first, with four
 *            bytes replaced, and is read back; on any mismatch everything written is put back. A cold boot undoes it.
 *   level 17 the same code with the two byte sets exchanged: puts the earlier words back.
 *   level 18 level 1, then READ-ONLY on the main processor only: what the sites of an encoder-side design (build/build_ogfile.py;
 *            modding/OG4K_FILE_SIDE.md) hold now. The sites in av-cam.bin are read through one read-only mapping of /dev/mem, as
 *            level 2 reads that image; the sites in libmpr.so are read where the library is mapped in this process, found in
 *            /proc/self/maps. Each site is reported as holding the stock bytes, the design's bytes, or something else. Nothing
 *            is written anywhere but the result file; no coprocessor transfer, no library call.
 *   level 19 level 1, then THE FIRST WRITE TO MAIN-PROCESSOR MEMORY in this file: the sites of an encoder-side design (the tables level 18
 *            reads). av-cam.bin's tables are written through one read-write mapping of /dev/mem, opened without O_SYNC so that the
 *            mapping is cached as the kernel's own is; each site is read back through the mapping and through the kernel's own view of
 *            that memory (a read of /dev/mem at the same offset). The two rows of libmpr.so are written through /proc/self/mem and read
 *            back in the process's memory. Before anything is written every guard must be as in the file, every site must hold the
 *            stock or the design's bytes, and the kernel's view must equal the mapping. On any failure everything this run wrote is
 *            put back. A cold boot undoes it: av-cam.bin is loaded again from flash and the process starts anew.
 *   level 20 the same code with the two byte sets exchanged: puts the stock bytes back.
 *   level 29 level 1, then CODE AND DATA OF av-cam.bin, the kernel's AV image (an av-cam code design of helper_fx3/gen_fx3_write.py; the
 *            first is avdec8k_fx3_v1, the FX3's playback decoder in the A7 IV's form). The code page is mapped read-write through /dev/mem
 *            at a user address with the kernel address's offset from a 2 MB boundary, the data page as level 19 maps its tables. Before
 *            anything is written every byte of the code page apart from the sites must be as in the file, every data guard as in the file,
 *            every site must hold the stock or the design's word, the kernel's view must equal the mappings, CTR_EL0 must name a PIPT or
 *            VIPT instruction cache, and the cache maintenance is run once on the sites as they are. Each site is one aligned 32-bit store,
 *            read back in both views; after the code writes, the data cache is cleaned and the instruction cache invalidated at every site on
 *            every processor. Code first, data last; on any failure everything this run wrote is put back. A cold boot undoes it.
 *   level 30 the same code with the two word sets exchanged and the order reversed (data first, code last): puts the stock words back.
 *   level 27 level 1, then WRITES: stage V4 of modding/VCD_V4_DESIGN.md. Checks that the codec is off and that its program area at
 *            0x43c000000 holds the stock stubs, writes the three hello_v1 boot stubs there (cached mapping, dc civac, read back in two views),
 *            replays av-cam's own clock-on store by store (F782), releases the codec CPUs (+0x80 = 0), reads the records the stubs write for
 *            0.3 s, replays av-cam's clock-off and puts every byte back. Device stores only from its three tables; no interrupt or mailbox
 *            register is written. A cold boot undoes anything left over.
 *   level 26 level 1, then READ-ONLY on the main processor only: the VCD program area read as plain memory (F780). The address is
 *            0x400000000 + a word av-cam stores when it boots the codec, read at run time; with no boot since power-on nothing else is
 *            read. Six small spans (boot stubs of the three CPUs, the SPU code start, the log head, the hello_v1 record area), the av-cam
 *            words and the SCU clock word for context. No codec register. Nothing is written but the result file.
 *   level 22 level 1, then READ-ONLY on the main processor only: the VCD codec's state (modding/VCD_HELLO_WORLD_PLAN.md stage V2,
 *            reference/vcd_boot_protocol.md). Through /dev/mem opened read-only with O_SYNC (uncached): one word of the SCU page and four
 *            of the clock/reset block; ONLY IF the SCU word shows the codec clocked, six registers of the codec's own window (only ones
 *            av-cam itself reads; never the interrupt-status registers, whose read may clear them), the clock word again, and four small
 *            spans of the codec's program area at the address the codec's own register names. Also nine words of av-cam.bin's data.
 *            Nothing is written anywhere but the result file; no coprocessor transfer, no library call.
 *   It writes ONE file, RESULT_PATH on the RAM disk, created new (it never overwrites or deletes).
 *   If that file already exists it does nothing at all.
 * What it does not do: no write to any other file, no ioctl, no write mapping, no coprocessor transfer,
 * no network, no process or thread creation, no call into any other library (it has no imports).
 * The coprocessor transfer of the design (level 3) is deliberately not in this file: it needs facts that only
 * a level 1 run can give (see README.md).
 *
 * Build for the camera: build.sh (AArch64, freestanding, no libc). Build for an off-camera test: host_test.sh
 * (-DHOST_TEST: the same logic on a PC against a fake file tree, through libc).
 */

#ifndef LEVEL
#define LEVEL 1
#endif
#if LEVEL < 1 || LEVEL > 30 || LEVEL == 11
#error "LEVEL must be 1 to 10, or 12 to 30"
#endif
#if LEVEL >= 3 && defined(HOST_TEST)
#error "levels 3 to 8 have no PC build: they call three functions of the camera's libsencore.so (see emu_built.py)"
#endif
#if (LEVEL == 2 || (LEVEL >= 18 && LEVEL <= 20) || LEVEL == 22 || LEVEL == 26 || LEVEL == 27) && !defined(AVCAM_PHYS)
#error "levels 2, 18 to 20, 22 and 26 need -DAVCAM_PHYS=<physical load address of av-cam.bin, read from a level 1 result>"
#endif
/* The design whose site table levels 5, 6 and 8 carry. Another design is built with -DSITES_H='"expected_sites_<name>.h"'
 * -DDESIGN_LABEL='"<name>"' (build.sh does this from DESIGN=<name>); without them the build is the og4k_data_v1 one, byte for
 * byte as before. SHADOW_STATE adds one more read-only state range to level 8: the sensor register shadow. */
#ifndef SITES_H
#define SITES_H "expected_sites.h"
#endif
/* The number of stored-record bytes a design changes (REC_BYTES, from its header), as text for the report: 24 for every design
 * up to ogsq_v2, so those builds are byte for byte as before; 26 for a design that also sets the vertical sampling ratio. */
#define RC_STR_(x) #x
#define RC_STR(x) RC_STR_(x)
#define REC_BYTES_TEXT RC_STR(REC_BYTES)
#ifndef DESIGN_LABEL
#define DESIGN_LABEL "og4k_data_v1"
#endif

#ifndef TEST_ROOT
#define TEST_ROOT ""                       /* prefix for every path; empty on the camera */
#endif
#define RESULT_PATH TEST_ROOT "/tmp_wbshd/readcheck_result.txt"

#define FILE_CAP   (64 * 1024)             /* at most this much of any one file is copied */
#define MAPS_CAP   (512 * 1024)            /* except the list of mappings: 64 KB cut it short on the camera (F509) */
#define TOTAL_CAP  (1024 * 1024)           /* at most this much is written in all */
#define DIR_ENTRIES_CAP 64

typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long u64;
typedef long i64;

/* ------------------------------------------------------------------ system calls */

#ifdef HOST_TEST
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <dirent.h>
static i64 sys_open(const char *p, int flags, int mode) { return open(p, flags, mode); }
static i64 sys_read(int fd, void *b, u64 n) { return read(fd, b, n); }
static i64 sys_write(int fd, const void *b, u64 n) { return write(fd, b, n); }
static i64 sys_close(int fd) { return close(fd); }
static i64 sys_getdents64(int fd, void *b, u64 n) { return syscall(SYS_getdents64, fd, b, n); }
static i64 sys_geteuid(void) { return geteuid(); }
#if LEVEL == 2                             /* a level 1 build contains no mapping call at all */
static i64 sys_mmap_ro(int fd, u64 len, u64 off) { void *p = mmap(0, len, PROT_READ, MAP_SHARED, fd, off); return p == MAP_FAILED ? -1 : (i64)p; }
static i64 sys_munmap(void *p, u64 len) { return munmap(p, len); }
#endif
#define F_RDONLY O_RDONLY
#define F_DIR (O_RDONLY | O_DIRECTORY)
#define F_NEW (O_WRONLY | O_CREAT | O_EXCL)
#else
/* AArch64 Linux. Numbers from the kernel's asm-generic/unistd.h. */
#define NR_openat 56
#define NR_close 57
#define NR_getdents64 61
#define NR_read 63
#define NR_write 64
#define NR_geteuid 175
#define NR_munmap 215
#define NR_mmap 222
static i64 sc(i64 n, i64 a, i64 b, i64 c, i64 d, i64 e, i64 f)
{
    register i64 x8 __asm__("x8") = n;
    register i64 x0 __asm__("x0") = a;
    register i64 x1 __asm__("x1") = b;
    register i64 x2 __asm__("x2") = c;
    register i64 x3 __asm__("x3") = d;
    register i64 x4 __asm__("x4") = e;
    register i64 x5 __asm__("x5") = f;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5) : "memory", "cc");
    return x0;
}
#define AT_FDCWD (-100)
#define F_RDONLY 0
#define F_DIR (0 | 0x4000)                 /* O_RDONLY | O_DIRECTORY (arm64 value) */
#define F_NEW (1 | 0x40 | 0x80)            /* O_WRONLY | O_CREAT | O_EXCL */
static i64 sys_open(const char *p, int flags, int mode) { return sc(NR_openat, AT_FDCWD, (i64)p, flags, mode, 0, 0); }
static i64 sys_read(int fd, void *b, u64 n) { return sc(NR_read, fd, (i64)b, (i64)n, 0, 0, 0); }
static i64 sys_write(int fd, const void *b, u64 n) { return sc(NR_write, fd, (i64)b, (i64)n, 0, 0, 0); }
static i64 sys_close(int fd) { return sc(NR_close, fd, 0, 0, 0, 0, 0); }
static i64 sys_getdents64(int fd, void *b, u64 n) { return sc(NR_getdents64, fd, (i64)b, (i64)n, 0, 0, 0); }
static i64 sys_geteuid(void) { return sc(NR_geteuid, 0, 0, 0, 0, 0, 0); }
#if LEVEL == 2 || LEVEL == 3 || (LEVEL >= 7 && LEVEL <= 12) || LEVEL == 15 || LEVEL == 18 || (LEVEL >= 21 && LEVEL <= 28)  /* a level 1 build contains no mapping call at all */
static i64 sys_mmap_ro(int fd, u64 len, u64 off)
{
    i64 r = sc(NR_mmap, 0, (i64)len, 1 /* PROT_READ */, 1 /* MAP_SHARED */, fd, (i64)off);
    return (r < 0 && r > -4096) ? -1 : r;
}
#endif
/* The only writable mapping call in this file (and levels 29 and 30's ad_map_code). Levels 4 to 6, 13, 14, 16 and 17 map their own transfer buffer to fill it; levels 19 and 20 map the pages of av-cam.bin's tables; levels 24 and 25 one page of a codec firmware copy at a time; levels 29 and 30 one page of av-cam.bin's data. */
#if (LEVEL >= 4 && LEVEL <= 6) || LEVEL == 13 || LEVEL == 14 || LEVEL == 16 || LEVEL == 17 || LEVEL == 19 || LEVEL == 20 || LEVEL == 24 || LEVEL == 25 || LEVEL == 27 || LEVEL == 29 || LEVEL == 30
static i64 sys_mmap_rw(int fd, u64 len, u64 off)
{
    i64 r = sc(NR_mmap, 0, (i64)len, 3 /* PROT_READ | PROT_WRITE */, 1 /* MAP_SHARED */, fd, (i64)off);
    return (r < 0 && r > -4096) ? -1 : r;
}
#endif
#if LEVEL >= 2
static i64 sys_munmap(void *p, u64 len) { return sc(NR_munmap, (i64)p, (i64)len, 0, 0, 0, 0); }
#endif
#endif

/* ------------------------------------------------------------------ output */

static int out_fd = -1;
static u64 out_total;

static u64 slen(const char *s) { u64 n = 0; while (s[n]) n++; return n; }

static void put(const void *b, u64 n)
{
    if (out_fd < 0 || out_total >= TOTAL_CAP) return;
    if (n > TOTAL_CAP - out_total) n = TOTAL_CAP - out_total;
    const u8 *p = b;
    while (n) {
        i64 w = sys_write(out_fd, p, n);
        if (w <= 0) { out_fd = -1; return; }           /* a failed write ends all output; nothing is retried */
        p += w; n -= (u64)w; out_total += (u64)w;
    }
}
static void puts_(const char *s) { put(s, slen(s)); }
static void putnum(i64 v)
{
    char t[24]; int i = 23; int neg = v < 0; u64 u = neg ? (u64)(-v) : (u64)v;
    t[i] = 0;
    do { t[--i] = (char)('0' + u % 10); u /= 10; } while (u);
    if (neg) t[--i] = '-';
    puts_(t + i);
}
#if LEVEL >= 2 && LEVEL != 9
static void puthex(const u8 *b, u64 n)
{
    static const char d[] = "0123456789abcdef";
    for (u64 i = 0; i < n; i++) { char c[2] = { d[b[i] >> 4], d[b[i] & 15] }; put(c, 2); }
}
#endif

/* ------------------------------------------------------------------ level 1: look only */

static void copy_file(const char *path, u64 cap)
{
    static u8 buf[4096];
    puts_("== file "); puts_(path); puts_("\n");
    i64 fd = sys_open(path, F_RDONLY, 0);
    if (fd < 0) { puts_("!! open failed "); putnum(fd); puts_("\n"); return; }
    u64 got = 0;
    for (;;) {
        u64 want = sizeof buf;
        if (want > cap - got) want = cap - got;
        if (!want) { puts_("\n!! truncated at "); putnum((i64)cap); puts_(" bytes\n"); break; }
        i64 r = sys_read((int)fd, buf, want);
        if (r < 0) { puts_("\n!! read failed "); putnum(r); puts_("\n"); break; }
        if (r == 0) break;
        put(buf, (u64)r); got += (u64)r;
    }
    sys_close((int)fd);
    puts_("\n== end "); putnum((i64)got); puts_(" bytes\n");
}

static void join(char *dst, u64 cap, const char *a, const char *b)
{
    u64 i = 0;
    for (; *a && i + 1 < cap; a++) dst[i++] = *a;
    if (i + 1 < cap) dst[i++] = '/';
    for (; *b && i + 1 < cap; b++) dst[i++] = *b;
    dst[i] = 0;
}

struct dirent64_ { u64 ino; i64 off; unsigned short reclen; u8 type; char name[]; };

/* List a directory and copy each regular-looking entry (not "." or ".."), at most DIR_ENTRIES_CAP of them. */
static void copy_dir(const char *path, u64 cap_each)
{
    static u8 dbuf[4096];
    static char names[DIR_ENTRIES_CAP][64];
    int count = 0;
    puts_("== dir "); puts_(path); puts_("\n");
    i64 fd = sys_open(path, F_DIR, 0);
    if (fd < 0) { puts_("!! open failed "); putnum(fd); puts_("\n"); return; }
    for (;;) {
        i64 r = sys_getdents64((int)fd, dbuf, sizeof dbuf);
        if (r <= 0) break;
        for (i64 o = 0; o < r;) {
            struct dirent64_ *d = (struct dirent64_ *)(dbuf + o);
            if (d->reclen == 0) { o = r; break; }
            const char *n = d->name;
            int dot = n[0] == '.' && (n[1] == 0 || (n[1] == '.' && n[2] == 0));
            if (!dot && count < DIR_ENTRIES_CAP && slen(n) < 64) {
                u64 k = 0; for (; n[k]; k++) names[count][k] = n[k];
                names[count][k] = 0; count++;
            }
            o += d->reclen;
        }
    }
    sys_close((int)fd);
    puts_("entries "); putnum(count); puts_("\n");
    for (int i = 0; i < count; i++) {
        char full[256];
        join(full, sizeof full, path, names[i]);
        copy_file(full, cap_each);
    }
}

static void level1(void)
{
    static const char *const files[] = {
        TEST_ROOT "/proc/version", TEST_ROOT "/proc/cmdline", TEST_ROOT "/proc/mounts", TEST_ROOT "/proc/iomem",
        TEST_ROOT "/proc/modules", TEST_ROOT "/proc/self/status", TEST_ROOT "/proc/self/maps",
    };
    u64 n = sizeof files / sizeof files[0];
    for (u64 i = 0; i < n; i++) copy_file(files[i], i == n - 1 ? MAPS_CAP : FILE_CAP);       /* the last one is the list of mappings */
    copy_dir(TEST_ROOT "/sys/module/liro/parameters", 256);
    copy_dir(TEST_ROOT "/proc/driver/pcie", 4096);
}

/* ------------------------------------------------------------------ level 2: av-cam.bin in kernel memory, read-only */

#if LEVEL == 2 || LEVEL == 3
struct sha { u32 h[8]; u8 block[64]; u64 len; u32 fill; };
static const u32 K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2 };
static u32 ror(u32 x, int n) { return (x >> n) | (x << (32 - n)); }
static void sha_block(struct sha *s, const u8 *p)
{
    u32 w[64], a, b, c, d, e, f, g, h;
    for (int i = 0; i < 16; i++) w[i] = (u32)p[4 * i] << 24 | (u32)p[4 * i + 1] << 16 | (u32)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (int i = 16; i < 64; i++)
        w[i] = w[i - 16] + (ror(w[i - 15], 7) ^ ror(w[i - 15], 18) ^ (w[i - 15] >> 3)) + w[i - 7] + (ror(w[i - 2], 17) ^ ror(w[i - 2], 19) ^ (w[i - 2] >> 10));
    a = s->h[0]; b = s->h[1]; c = s->h[2]; d = s->h[3]; e = s->h[4]; f = s->h[5]; g = s->h[6]; h = s->h[7];
    for (int i = 0; i < 64; i++) {
        u32 t1 = h + (ror(e, 6) ^ ror(e, 11) ^ ror(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i];
        u32 t2 = (ror(a, 2) ^ ror(a, 13) ^ ror(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        h = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    s->h[0] += a; s->h[1] += b; s->h[2] += c; s->h[3] += d; s->h[4] += e; s->h[5] += f; s->h[6] += g; s->h[7] += h;
}
static void sha_init(struct sha *s)
{
    static const u32 iv[8] = { 0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19 };
    for (int i = 0; i < 8; i++) s->h[i] = iv[i];
    s->len = 0; s->fill = 0;
}
static void sha_add(struct sha *s, const u8 *p, u64 n)
{
    s->len += n;
    while (n) {
        s->block[s->fill++] = *p++; n--;
        if (s->fill == 64) { sha_block(s, s->block); s->fill = 0; }
    }
}
static void sha_end(struct sha *s, u8 out[32])
{
    u64 bits = s->len * 8;
    u8 pad = 0x80;
    sha_add(s, &pad, 1);
    pad = 0;
    while (s->fill != 56) sha_add(s, &pad, 1);
    for (int i = 7; i >= 0; i--) { u8 b = (u8)(bits >> (8 * i)); sha_add(s, &b, 1); }
    for (int i = 0; i < 8; i++) { out[4 * i] = (u8)(s->h[i] >> 24); out[4 * i + 1] = (u8)(s->h[i] >> 16); out[4 * i + 2] = (u8)(s->h[i] >> 8); out[4 * i + 3] = (u8)s->h[i]; }
}

#endif

#if LEVEL == 2
#include "expected.h"                      /* generated from evidence/security/usb_read_check_expected.json by gen_expected.py */
#ifndef DEVMEM_PATH
#define DEVMEM_PATH TEST_ROOT "/dev/mem"
#endif

static void level2(void)
{
    u64 base = (u64)AVCAM_PHYS;
    u8 be[8];
    for (int k = 0; k < 8; k++) be[k] = (u8)(base >> (8 * (7 - k)));
    puts_("== level 2: av-cam.bin at physical 0x"); puthex(be, 8); puts_("\n");
    i64 fd = sys_open(DEVMEM_PATH, F_RDONLY, 0);                 /* read-only: this descriptor cannot be mapped for writing */
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("\n"); return; }
    for (u64 i = 0; i < sizeof av_regions / sizeof av_regions[0]; i++) {
        const struct av_region *r = &av_regions[i];
        u64 start = (u64)AVCAM_PHYS + r->file_offset, page = start & ~0xfffUL, lead = start - page;
        u64 maplen = (lead + r->length + 0xfff) & ~0xfffUL;
        puts_("region "); puts_(r->name); puts_(" length "); putnum((i64)r->length); puts_("\n");
        i64 m = sys_mmap_ro((int)fd, maplen, page);
        if (m == -1) { puts_("!! mmap failed; stopping level 2\n"); break; }          /* stop at the first failure, no retry */
        struct sha s; u8 dg[32];
        sha_init(&s); sha_add(&s, (const u8 *)m + lead, r->length); sha_end(&s, dg);
        sys_munmap((void *)m, maplen);
        int same = 1;
        for (int k = 0; k < 32; k++) if (dg[k] != r->sha256[k]) same = 0;
        puts_("  sha256 "); puthex(dg, 32); puts_(same ? "  SAME as the update file\n" : "  DIFFERS from the update file\n");
    }
    sys_close((int)fd);
}
#endif

/* ------------------------------------------------------------------ level 3: coprocessor memory, read-only */

#if LEVEL == 3
#include "expected_cp.h"                   /* generated by gen_expected.py */

/* The three imports, all from libsencore.so (finding F512). Nothing else is called outside this file. */
extern u64 cam_dmm_alloc(u32 size, u32 *handle) __asm__("_Z9dmm_allocjPj");      /* a buffer in main memory: its physical address, 0 on failure */
extern u64 cam_dmm_free(u32 handle) __asm__("_Z8dmm_freej");
extern u32 sen_dma_transfer(u32 dir, u64 src, u64 dst, u32 size);                 /* dir 0: coprocessor (src) to main memory (dst); 0 on success */

#define CP_PAGE 4096U
#define F_RDONLY_SYNC (0 | 0x101000)       /* O_RDONLY | O_SYNC: the uncached mapping the camera's own code uses for these buffers */
#define RAM_LO 0x400000000UL               /* system RAM on this camera (finding F509) */
#define RAM_HI 0x500000000UL

static void level3(void)
{
    u32 handle = 0;
    puts_("== level 3: coprocessor memory, read-only\n");
    u64 phys = cam_dmm_alloc(CP_PAGE, &handle);
    if (!phys) { puts_("!! buffer allocation failed; stopping level 3\n"); return; }
    u8 be[8];
    for (int k = 0; k < 8; k++) be[k] = (u8)(phys >> (8 * (7 - k)));
    puts_("buffer physical 0x"); puthex(be, 8); puts_(" handle "); putnum(handle); puts_("\n");
    /* The allocator's addresses are not page-aligned (first camera run: 0x47e67b080), so the buffer may span two pages. */
    if ((phys & 0x3f) || phys < RAM_LO || phys + CP_PAGE > RAM_HI) {
        puts_("!! buffer address is not 64-byte aligned inside system RAM; stopping level 3\n");
        cam_dmm_free(handle);
        return;
    }
    i64 fd = sys_open(TEST_ROOT "/dev/mem", F_RDONLY_SYNC, 0);        /* read-only: the buffer is only ever read from here */
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("\n"); cam_dmm_free(handle); return; }
    u64 lead = phys & 0xfff, maplen = (lead + CP_PAGE + 0xfff) & ~0xfffUL;
    i64 m = sys_mmap_ro((int)fd, maplen, phys - lead);
    if (m == -1) { puts_("!! mmap of the buffer failed; stopping level 3\n"); sys_close((int)fd); cam_dmm_free(handle); return; }
    for (u64 i = 0; i < sizeof cp_pages / sizeof cp_pages[0]; i++) {
        const struct cp_page *p = &cp_pages[i];
        u8 a[8];
        for (int k = 0; k < 8; k++) a[k] = (u8)(p->address >> (8 * (7 - k)));
        puts_("page "); puts_(p->name); puts_(" address 0x"); puthex(a, 8); puts_("\n");
        u32 r = sen_dma_transfer(0, p->address, phys, CP_PAGE);       /* 0: from the coprocessor. This file contains no other direction */
        if (r) { puts_("!! transfer failed "); putnum(r); puts_("; stopping level 3\n"); goto out; }    /* stop at the first failure, no retry */
        struct sha s; u8 dg[32];
        sha_init(&s); sha_add(&s, (const u8 *)m + lead, CP_PAGE); sha_end(&s, dg);
        int same = 1;
        for (int k = 0; k < 32; k++) if (dg[k] != p->sha256[k]) same = 0;
        puts_("  sha256 "); puthex(dg, 32); puts_(same ? "  SAME as the update file\n" : "  DIFFERS from the update file\n");
        if (!same) { puts_("!! stopping level 3 at the first difference\n"); goto out; }
    }
    /* Sites that lie in read/write data: the page as a whole changes while the camera runs, so only the cell's bytes are shown and compared. */
    for (u64 i = 0; i < sizeof cp_cells / sizeof cp_cells[0]; i++) {
        const struct cp_cell *c = &cp_cells[i];
        u8 a[8];
        for (int k = 0; k < 8; k++) a[k] = (u8)(c->address >> (8 * (7 - k)));
        puts_("cell address 0x"); puthex(a, 8); puts_("\n");
        u32 r = sen_dma_transfer(0, c->address & ~0xfffUL, phys, CP_PAGE);
        if (r) { puts_("!! transfer failed "); putnum(r); puts_("; stopping level 3\n"); break; }
        const u8 *v = (const u8 *)m + lead + (c->address & 0xfff);
        int same = 1;
        for (u32 k = 0; k < c->length; k++) if (v[k] != c->stock[k]) same = 0;
        puts_("  bytes "); puthex(v, c->length); puts_(same ? "  SAME as the update file\n" : "  DIFFERS from the update file\n");
    }
out:
    sys_munmap((void *)m, maplen);
    sys_close((int)fd);
    cam_dmm_free(handle);
    puts_("buffer released\n");
}
#endif

/* ------------------------------------------------------------------ level 4: one write test on an unused page */

#if LEVEL == 4
/* The three imports, all from libsencore.so (finding F512). Nothing else is called outside this file. */
extern u64 cam_dmm_alloc(u32 size, u32 *handle) __asm__("_Z9dmm_allocjPj");
extern u64 cam_dmm_free(u32 handle) __asm__("_Z8dmm_freej");
extern u32 sen_dma_transfer(u32 dir, u64 src, u64 dst, u32 size);   /* dir 0: coprocessor to buffer; dir 1: buffer to coprocessor */

#define CP_PAGE 4096U
#define F_RDWR_SYNC (2 | 0x101000)         /* O_RDWR | O_SYNC: for the helper's own buffer only */
#define RAM_LO 0x400000000UL               /* system RAM on this camera (finding F509) */
#define RAM_HI 0x500000000UL
/* Where the test line is. The image's constant data ends at 0xf31e40 (its header: 0xb11000 + 0x420e40); the rest of that page, to 0xf32000,
   is padding: zeros in the file, and no pointer anywhere in the image points into it. (The zero page 0xba4000 is NOT unused: finding F517.) */
#define TEST_PAGE 0xf31000UL               /* the page that is read, before and after */
#define PAD_FROM 0xe40U                    /* offset in that page where the padding starts */
#define TEST_OFF 0xf00U                    /* offset of the test line: 64-byte aligned, inside the padding */
#define TEST_ADDR (TEST_PAGE + TEST_OFF)   /* 0xf31f00: the only address this file can write to */
#define TEST_LEN 64U                       /* one cache line: Sony's cache request works in whole 64-byte lines (F419) */

static u64 l4_phys;                        /* the buffer: physical address and where it is mapped here */
static u8 *l4_buf;
static u8 l4_before[CP_PAGE];               /* the page as first read: what every later read is compared with */

/* THE ONLY TRANSFER TOWARDS THE COPROCESSOR IN THIS FILE: TEST_LEN bytes of the buffer to TEST_ADDR. Both are constants. */
static u32 write_test_line(void) { return sen_dma_transfer(1, l4_phys, TEST_ADDR, TEST_LEN); }
static u32 read_test_page(void) { return sen_dma_transfer(0, TEST_PAGE, l4_phys, CP_PAGE); }

/* Read the page into the buffer and compare it with the page as first read, the test line replaced by `want` (zeros if want is null).
   With first set it is the first read: the page is kept, and the whole padding must be zero. 0: as expected; 1: not; 2: transfer failed. */
static int read_and_compare(const u8 *want, int first)
{
    for (u32 i = 0; i < CP_PAGE; i++) l4_buf[i] = 0xee;                 /* so that a transfer that moves nothing cannot pass */
    u32 r = read_test_page();
    if (r) { puts_("!! read transfer failed "); putnum(r); puts_("\n"); return 2; }
    int same = 1;
    if (first) {
        for (u32 i = 0; i < CP_PAGE; i++) l4_before[i] = l4_buf[i];
        for (u32 i = PAD_FROM; i < CP_PAGE; i++) if (l4_buf[i]) same = 0;
    } else {
        for (u32 i = 0; i < CP_PAGE; i++) {
            int in_line = i >= TEST_OFF && i < TEST_OFF + TEST_LEN;
            if (l4_buf[i] != (u8)((in_line && want) ? want[i - TEST_OFF] : l4_before[i])) same = 0;
        }
    }
    puts_("  test line, first 16 bytes "); puthex(l4_buf + TEST_OFF, 16); puts_("\n");
    return same ? 0 : 1;
}

static void level4(void)
{
    static const u8 pattern[TEST_LEN] = "A7IV-CT6 stage 2 write test: 64 bytes of padding at 0x00f31f00..";
    u32 handle = 0;
    puts_("== level 4: write test in the padding after constant data\n");
    l4_phys = cam_dmm_alloc(CP_PAGE, &handle);
    if (!l4_phys) { puts_("!! buffer allocation failed; stopping level 4\n"); return; }
    u8 be[8];
    for (int k = 0; k < 8; k++) be[k] = (u8)(l4_phys >> (8 * (7 - k)));
    puts_("buffer physical 0x"); puthex(be, 8); puts_(" handle "); putnum(handle); puts_("\n");
    if ((l4_phys & 0x3f) || l4_phys < RAM_LO || l4_phys + CP_PAGE > RAM_HI) {
        puts_("!! buffer address is not 64-byte aligned inside system RAM; stopping level 4\n");
        cam_dmm_free(handle);
        return;
    }
    i64 fd = sys_open(TEST_ROOT "/dev/mem", F_RDWR_SYNC, 0);
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("\n"); cam_dmm_free(handle); return; }
    u64 lead = l4_phys & 0xfff, maplen = (lead + CP_PAGE + 0xfff) & ~0xfffUL;
    i64 m = sys_mmap_rw((int)fd, maplen, l4_phys - lead);              /* the helper's own buffer, nothing else */
    if (m == -1) { puts_("!! mmap of the buffer failed; stopping level 4\n"); sys_close((int)fd); cam_dmm_free(handle); return; }
    l4_buf = (u8 *)m + lead;

    puts_("step 1: read the page before anything is written\n");
    int c = read_and_compare(0, 1);
    if (c) { puts_(c == 1 ? "!! the padding is not all zeros; nothing is written\n" : "!! nothing is written\n"); goto out; }
    puts_("  the padding is all zeros, as in the update file\n");

    puts_("step 2: write the 64-byte pattern\n");
    for (u32 i = 0; i < TEST_LEN; i++) l4_buf[i] = pattern[i];
    u32 w = write_test_line();
    if (w) { puts_("!! write transfer failed "); putnum(w); puts_("\n"); }       /* go on to the restore all the same: the state is unknown */
    else {
        puts_("step 3: read the page back\n");
        c = read_and_compare(pattern, 0);
        puts_(c == 0 ? "  WRITE SEEN: the pattern is there and the rest of the page is as it was\n"
                     : c == 1 ? "!! WRITE NOT SEEN as written\n" : "!! read-back failed\n");
    }

    puts_("step 4: write zeros back\n");                                         /* always, once a write has been tried */
    for (u32 i = 0; i < TEST_LEN; i++) l4_buf[i] = 0;
    w = write_test_line();
    if (w) { puts_("!! restore transfer failed "); putnum(w); puts_("\n"); }
    puts_("step 5: read the page again\n");
    c = read_and_compare(0, 0);
    puts_(c == 0 ? "  RESTORED: the whole page is as it was first read\n" : "!! PAGE NOT CONFIRMED AS RESTORED. Cold boot the camera.\n");
out:
    sys_munmap((void *)m, maplen);
    sys_close((int)fd);
    cam_dmm_free(handle);
    puts_("buffer released\n");
}
#endif

/* ------------------------------------------------------------------ levels 5 and 6: the 13 sites, applied or put back */

#if LEVEL == 5 || LEVEL == 6
#include SITES_H                           /* generated by gen_expected.py from the design file */

/* The three imports, all from libsencore.so (finding F512). Nothing else is called outside this file. */
extern u64 cam_dmm_alloc(u32 size, u32 *handle) __asm__("_Z9dmm_allocjPj");
extern u64 cam_dmm_free(u32 handle) __asm__("_Z8dmm_freej");
extern u32 sen_dma_transfer(u32 dir, u64 src, u64 dst, u32 size);   /* dir 0: coprocessor to buffer; dir 1: buffer to coprocessor */

#define CP_PAGE 4096U
#define F_RDWR_SYNC (2 | 0x101000)         /* O_RDWR | O_SYNC: for the helper's own buffer only */
#define RAM_LO 0x400000000UL
#define RAM_HI 0x500000000UL
#define N_TABLE (sizeof cp_sites / sizeof cp_sites[0])
#define N_SITES (N_TABLE + 1)              /* the table's sites, then the stored record */
#define CP_LO 0x108000UL                   /* pointers read from coprocessor memory must lie between these, or nothing is written */
#define CP_HI 0x10000000UL
#ifndef IMAGER                             /* another build of the camera software names its own (-DIMAGER=, -DCTRL_DRVPARAM=): helper_s3/build_s3_write.sh */
#define IMAGER 0x12b9ce0UL                 /* the sensor object; chain as in level 7 (findings F520 to F522) */
#define CTRL_DRVPARAM 0x684U
#endif
#ifndef SITES_TEXT                         /* how many sites the table has, and with the stored record, as text for the report */
#define SITES_TEXT "13"
#define ALL_TEXT "14"
#endif
#ifndef REC                                /* the stored record's size: 0x170 on the A7C II 2.01 (helper_c2/build_c2_write.sh) */
#define REC 0x15cU
#endif
#ifndef MODE_ID                           /* a design for another drive mode names it in its header (expected_sites_<name>.h) */
#define MODE_ID 0x8c0U
#define MODE_TEXT "0x8c0"
#endif
#if LEVEL == 5
#define FROM(s) ((s)->stock)               /* what a site must hold before */
#define TO(s) ((s)->changed)               /* what it holds after */
#define VERB "apply"
#else
#define FROM(s) ((s)->changed)
#define TO(s) ((s)->stock)
#define VERB "put back"
#endif

static u64 l5_phys;
static u8 *l5_buf;
static struct cp_site l5_rec;              /* the 14th site, filled in once the record has been found */
static const struct cp_site *site_at(u64 i) { return i < N_TABLE ? &cp_sites[i] : &l5_rec; }

/* Every transfer is of whole 64-byte lines: the lines a site lies in, at most 4,096 bytes (the generator checks). */
static u64 line_base(const struct cp_site *s) { return s->address & ~63UL; }
static u32 line_len(const struct cp_site *s) { return (u32)(((s->address + s->length + 63) & ~63UL) - line_base(s)); }

static int site_read(const struct cp_site *s)                /* the site's lines into the buffer; 0 on success */
{
    u32 n = line_len(s);
    for (u32 i = 0; i < n; i++) l5_buf[i] = 0xee;
    return sen_dma_transfer(0, line_base(s), l5_phys, n) != 0;
}
/* THE ONLY TRANSFER TOWARDS THE COPROCESSOR IN LEVELS 5 AND 6: the lines of one listed site, as just read, with the site's bytes replaced. */
static int site_write(const struct cp_site *s, const u8 *bytes)
{
    if (site_read(s)) return 1;                                /* the neighbours in those lines are written back as they are now */
    u8 *at = l5_buf + (s->address - line_base(s));
    if (s->offs) for (u32 i = 0; i < s->noffs; i++) at[s->offs[i]] = bytes[i];
    else for (u32 i = 0; i < s->length; i++) at[i] = bytes[i];
    return sen_dma_transfer(1, l5_phys, line_base(s), line_len(s)) != 0;
}
static int site_holds(const struct cp_site *s, const u8 *bytes)   /* after site_read: 1 if the site's bytes equal `bytes` */
{
    const u8 *at = l5_buf + (s->address - line_base(s));
    if (s->offs) { for (u32 i = 0; i < s->noffs; i++) if (at[s->offs[i]] != bytes[i]) return 0; }
    else for (u32 i = 0; i < s->length; i++) if (at[i] != bytes[i]) return 0;
    return 1;
}
/* A plain read used only to follow the pointer chain: `len` bytes at `addr`, as whole lines. Null if refused or failed. */
static const u8 *chain_read(u64 addr, u32 len)
{
    u64 base = addr & ~63UL, end = (addr + len + 63) & ~63UL;
    if (addr < CP_LO || addr + len > CP_HI || end - base > CP_PAGE) return 0;
    if (sen_dma_transfer(0, base, l5_phys, (u32)(end - base))) return 0;
    return l5_buf + (addr - base);
}
static u32 le32(const u8 *p) { return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24; }
static int bad_pointer(u32 v) { return (v & 3) || v < CP_LO || v >= CP_HI; }
/* Find the stored record of MODE_ID and fill l5_rec. 0 on success. */
static int find_record(void)
{
    const u8 *p = chain_read(IMAGER, 4);
    if (!p) return 1;
    u32 ctrl = le32(p);
    if (bad_pointer(ctrl) || !(p = chain_read((u64)ctrl + CTRL_DRVPARAM, 4))) return 1;
    u32 obj = le32(p);
    if (bad_pointer(obj) || !(p = chain_read(obj, 0x18))) return 1;
    u32 count = le32(p + 4), ids = le32(p + 8), base = le32(p + 0x10);
    if (count == 0 || count > 64 || bad_pointer(ids) || bad_pointer(base) || !(p = chain_read(ids, count * 4))) return 1;
    u32 index = 0xff;
    for (u32 i = 0; i < count; i++) if (le32(p + 4 * i) == MODE_ID && index == 0xff) index = i;
    if (index == 0xff) return 1;
    l5_rec.address = (u64)base + index * REC;
    l5_rec.length = REC;
    l5_rec.stock = rec_stock; l5_rec.changed = rec_new;
    l5_rec.offs = rec_offs; l5_rec.noffs = REC_BYTES;
    return l5_rec.address + REC > CP_HI;
}
static void say_site(const char *what, const struct cp_site *s)
{
    u8 a[4] = { (u8)(s->address >> 24), (u8)(s->address >> 16), (u8)(s->address >> 8), (u8)s->address };
    puts_(what); puts_(" 0x"); puthex(a, 4); puts_(" length "); putnum(s->length); puts_(": ");
}

static void level5(void)
{
    static u8 done[N_SITES];                                   /* 1: this run wrote the site */
    u32 handle = 0;
    puts_("== level " ); putnum(LEVEL); puts_(": " VERB " the " SITES_TEXT " sites of " DESIGN_LABEL " and the stored record\n");
    l5_phys = cam_dmm_alloc(CP_PAGE, &handle);
    if (!l5_phys) { puts_("!! buffer allocation failed; nothing is written\n"); return; }
    u8 be[8];
    for (int k = 0; k < 8; k++) be[k] = (u8)(l5_phys >> (8 * (7 - k)));
    puts_("buffer physical 0x"); puthex(be, 8); puts_(" handle "); putnum(handle); puts_("\n");
    if ((l5_phys & 0x3f) || l5_phys < RAM_LO || l5_phys + CP_PAGE > RAM_HI) {
        puts_("!! buffer address is not 64-byte aligned inside system RAM; nothing is written\n");
        cam_dmm_free(handle);
        return;
    }
    i64 fd = sys_open(TEST_ROOT "/dev/mem", F_RDWR_SYNC, 0);
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("; nothing is written\n"); cam_dmm_free(handle); return; }
    u64 lead = l5_phys & 0xfff, maplen = (lead + CP_PAGE + 0xfff) & ~0xfffUL;
    i64 m = sys_mmap_rw((int)fd, maplen, l5_phys - lead);              /* the helper's own buffer, nothing else */
    if (m == -1) { puts_("!! mmap of the buffer failed; nothing is written\n"); sys_close((int)fd); cam_dmm_free(handle); return; }
    l5_buf = (u8 *)m + lead;

    if (find_record()) { puts_("!! the stored record was not found where the pointers lead; nothing is written\n"); goto out; }
    say_site("stored record of mode " MODE_TEXT " at", &l5_rec); puts_(REC_BYTES_TEXT " of its bytes are a site\n");
    puts_("pass 1: read every site; nothing is written unless all are as expected\n");
    u32 todo = 0;
    for (u64 i = 0; i < N_SITES; i++) {
        const struct cp_site *s = site_at(i);
        say_site("site", s);
        if (site_read(s)) { puts_("!! read failed; nothing is written\n"); goto out; }
        if (site_holds(s, FROM(s))) { puts_("as expected\n"); todo++; }
        else if (site_holds(s, TO(s))) puts_("already holds the target bytes\n");
        else { puts_("!! holds neither the stock nor the new bytes; nothing is written\n"); goto out; }
    }
    if (!todo) { puts_("NOTHING TO DO: every site already holds the target bytes\n"); goto out; }

    puts_("pass 2: write, and read each site back\n");
    int failed = 0;
    for (u64 i = 0; i < N_SITES && !failed; i++) {
        const struct cp_site *s = site_at(i);
        if (site_read(s)) { say_site("site", s); puts_("!! read failed\n"); failed = 1; break; }
        if (site_holds(s, TO(s))) continue;                          /* was already there in pass 1 */
        say_site("site", s);
        done[i] = 1;                                                 /* from here on it counts as touched */
        if (site_write(s, TO(s))) { puts_("!! write failed\n"); failed = 1; break; }
        if (site_read(s) || !site_holds(s, TO(s))) { puts_("!! not as written on read-back\n"); failed = 1; break; }
        puts_("written and read back\n");
    }

    if (!failed) {
        puts_("pass 3: read every site once more\n");
        for (u64 i = 0; i < N_SITES; i++) {
            const struct cp_site *s = site_at(i);
            if (site_read(s) || !site_holds(s, TO(s))) { say_site("site", s); puts_("!! does not hold the target bytes\n"); failed = 1; }
        }
    }
    if (!failed) { puts_("DONE: all " ALL_TEXT " sites hold the target bytes (" VERB ")\n"); goto out; }

    puts_("undo: every site this run touched gets its earlier bytes back\n");
    int left = 0;
    for (u64 i = 0; i < N_SITES; i++) {
        const struct cp_site *s = site_at(i);
        if (!done[i]) continue;
        say_site("undo", s);
        if (site_write(s, FROM(s)) || site_read(s) || !site_holds(s, FROM(s))) { puts_("!! NOT PUT BACK\n"); left++; }
        else puts_("put back and read back\n");
    }
    puts_(left ? "!! UNDO INCOMPLETE. Cold boot the camera (battery out) before anything else.\n"
               : "NOT DONE: a step failed; every site this run touched was put back\n");
out:
    sys_munmap((void *)m, maplen);
    sys_close((int)fd);
    cam_dmm_free(handle);
    puts_("buffer released\n");
}
#endif

/* ------------------------------------------------------------------ level 7: the stored drive-parameter records, read-only */

#if LEVEL == 7 || LEVEL == 8
#if LEVEL == 8
#include SITES_H                           /* the 14 sites, to say what each holds; nothing is written */
#endif
/* The three imports, all from libsencore.so (finding F512). Nothing else is called outside this file. */
extern u64 cam_dmm_alloc(u32 size, u32 *handle) __asm__("_Z9dmm_allocjPj");
extern u64 cam_dmm_free(u32 handle) __asm__("_Z8dmm_freej");
extern u32 sen_dma_transfer(u32 dir, u64 src, u64 dst, u32 size);   /* used with dir 0 only: coprocessor to buffer */

#define CP_PAGE 4096U
#define F_RDONLY_SYNC (0 | 0x101000)
#define RAM_LO 0x400000000UL
#define RAM_HI 0x500000000UL
#define CP_LO 0x108000UL                   /* coprocessor addresses this level will read: from the image's base ... */
#define CP_HI 0x10000000UL                 /* ... to 256 MB. A pointer outside ends the level */
#define IMAGER 0x12b9ce0UL                 /* the sensor object (0x8981f2 returns this address); its first word points to the control object */
#define CTRL_DRVPARAM 0x684U               /* control object: pointer to the drive-parameter object */
#define REC 0x15cU                         /* one stored record */
#define FLAGS 0x14f7220UL                  /* current and requested frame-rate family flags (finding F520) */

static u64 l7_phys;
static const u8 *l7_buf;

/* THE ONLY TRANSFER IN LEVEL 7: `len` bytes at `addr`, read as the whole 64-byte lines they lie in. Returns a pointer to the bytes, or null. */
static const u8 *cp_read(u64 addr, u32 len)
{
    u64 base = addr & ~63UL, end = (addr + len + 63) & ~63UL;
    if (addr < CP_LO || addr + len > CP_HI || end - base > CP_PAGE) { puts_("!! address outside what this level reads\n"); return 0; }
    u32 r = sen_dma_transfer(0, base, l7_phys, (u32)(end - base));
    if (r) { puts_("!! transfer failed "); putnum(r); puts_("\n"); return 0; }
    return l7_buf + (addr - base);
}
static u32 le32(const u8 *p) { return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24; }
static void put32(const char *what, u32 v)
{
    u8 b[4] = { (u8)(v >> 24), (u8)(v >> 16), (u8)(v >> 8), (u8)v };
    puts_(what); puts_(" 0x"); puthex(b, 4); puts_("\n");
}
static int bad_pointer(u32 v) { return (v & 3) || v < CP_LO || v >= CP_HI; }

static void level7(void)
{
#ifndef MODE_ID
#define MODE_ID 0x8c0U
#endif
    static const u32 wanted[] = { MODE_ID, 0xa100 };           /* full-frame 4K 24/25p, and a full-height still mode for comparison */
    u32 handle = 0;
    puts_("== level 7: the stored drive-parameter records, read-only\n");
    l7_phys = cam_dmm_alloc(CP_PAGE, &handle);
    if (!l7_phys) { puts_("!! buffer allocation failed; stopping level 7\n"); return; }
    if ((l7_phys & 0x3f) || l7_phys < RAM_LO || l7_phys + CP_PAGE > RAM_HI) {
        puts_("!! buffer address is not 64-byte aligned inside system RAM; stopping level 7\n");
        cam_dmm_free(handle);
        return;
    }
    i64 fd = sys_open(TEST_ROOT "/dev/mem", F_RDONLY_SYNC, 0);
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("\n"); cam_dmm_free(handle); return; }
    u64 lead = l7_phys & 0xfff, maplen = (lead + CP_PAGE + 0xfff) & ~0xfffUL;
    i64 m = sys_mmap_ro((int)fd, maplen, l7_phys - lead);
    if (m == -1) { puts_("!! mmap of the buffer failed; stopping level 7\n"); sys_close((int)fd); cam_dmm_free(handle); return; }
    l7_buf = (const u8 *)m + lead;

    const u8 *p = cp_read(FLAGS, 2);
    if (!p) goto out;
    puts_("frame-rate family flags, current then requested: "); puthex(p, 2); puts_("\n");

    if (!(p = cp_read(IMAGER, 4))) goto out;
    u32 ctrl = le32(p);
    put32("control object at", ctrl);
    if (bad_pointer(ctrl)) { puts_("!! not a usable pointer; stopping level 7\n"); goto out; }

    if (!(p = cp_read((u64)ctrl + CTRL_DRVPARAM, 4))) goto out;
    u32 obj = le32(p);
    put32("drive-parameter object at", obj);
    if (bad_pointer(obj)) { puts_("!! not a usable pointer; stopping level 7\n"); goto out; }

    if (!(p = cp_read(obj, 0x40))) goto out;
    puts_("object, first 64 bytes: "); puthex(p, 0x40); puts_("\n");
    u32 count = le32(p + 4), ids = le32(p + 8), base = le32(p + 0x10);
    puts_("modes "); putnum(count); puts_("\n");
    put32("mode id list at", ids);
    put32("records at", base);
    if (count == 0 || count > 64 || bad_pointer(ids) || bad_pointer(base)) { puts_("!! the object does not look as expected; stopping level 7\n"); goto out; }

    if (!(p = cp_read(ids, count * 4))) goto out;
    puts_("mode ids: "); puthex(p, count * 4); puts_("\n");
    u32 index[sizeof wanted / sizeof wanted[0]];
    for (u32 w = 0; w < sizeof wanted / sizeof wanted[0]; w++) {
        index[w] = 0xff;
        for (u32 i = 0; i < count; i++) if (le32(p + 4 * i) == wanted[w] && index[w] == 0xff) index[w] = i;
    }
    for (u32 w = 0; w < sizeof wanted / sizeof wanted[0]; w++) {
        put32("mode id", wanted[w]);
        if (index[w] == 0xff) { puts_("  not in the list\n"); continue; }
        puts_("  index "); putnum(index[w]); puts_("\n");
        u32 at = base + index[w] * REC;
        put32("  record at", at);
        if (!(p = cp_read(at, REC))) goto out;
        puts_("  record: "); puthex(p, REC); puts_("\n");
    }
#if LEVEL == 8
    {
        /* What each site holds. The stored record first (its address is known from above), then the table's 13. */
        puts_("== level 8: what the 14 sites hold, and the working state\n");
        if (index[0] != 0xff) {
            if (!(p = cp_read(base + index[0] * REC, REC))) goto out;
            int st = 1, ch = 1;
            for (u32 i = 0; i < REC_BYTES; i++) { if (p[rec_offs[i]] != rec_stock[i]) st = 0; if (p[rec_offs[i]] != rec_new[i]) ch = 0; }
            puts_("stored record, its " REC_BYTES_TEXT " bytes: "); puts_(st ? "stock\n" : ch ? "changed\n" : "OTHER\n");
        }
        for (u64 i = 0; i < sizeof cp_sites / sizeof cp_sites[0]; i++) {
            const struct cp_site *s = &cp_sites[i];
            if (!(p = cp_read(s->address, s->length))) goto out;
            int st = 1, ch = 1;
            for (u32 k = 0; k < s->length; k++) { if (p[k] != s->stock[k]) st = 0; if (p[k] != s->changed[k]) ch = 0; }
            put32("site", (u32)s->address); puts_(st ? "  stock\n" : ch ? "  changed\n" : "  OTHER\n");
        }
        /* Working state, at fixed addresses (the ones the emulation report reads, build/report_og4k_emu.py). */
        static const struct { u32 addr, len; const char *what; } state[] = {
            { 0x11d1194, 0x10, "sensor window: read-out w h, crop start x y, crop w h, front end w h" },
            { 0x11d11ac, 0x18, "size source w h, then the drive mode id" },
            { 0x1450958, 0x08, "second scaler input w h" },
            { 0x145091c, 0x20, "second scaler block" },
            { 0x143c7a4, 0x20, "output size table" },
#ifdef SHADOW_STATE
            /* the register shadow the sensor's mode change fills from one column of the matrix 0xfb33ec (F84): register 0x01 (the
               sensor's own mode) at +0x3e, 0x05 at +0x4e, 0x0e at +0x72, 0x10 at +0x7a, 0x19 at +0x9e; mode 16 has 16 4 8 41 51 there,
               the full-height mode 2 has 2 0 0 0 59 */
            { 0x1033c40, 0x440, "sensor register shadow" },
#endif
        };
        for (u64 i = 0; i < sizeof state / sizeof state[0]; i++) {
            if (!(p = cp_read(state[i].addr, state[i].len))) goto out;
            put32("state", state[i].addr); puts_("  "); puts_(state[i].what); puts_("\n  "); puthex(p, state[i].len); puts_("\n");
        }
        puts_("level 8 complete\n");
    }
#endif
    puts_("level 7 complete\n");
out:
    sys_munmap((void *)m, maplen);
    sys_close((int)fd);
    cam_dmm_free(handle);
    puts_("buffer released\n");
}
#endif

/* ------------------------------------------------------------------ level 9: the camera's own logs, read-only */

#if LEVEL == 9
#define KLOG_PHYS 0x400040000UL            /* klog.addr on the kernel command line read from the camera (finding F509) */
#define KLOG_SIZE 0x40000UL                /* klog.size */

static void level9(void)
{
    puts_("== level 9: the camera's logs, read-only\n");
    copy_dir(TEST_ROOT "/log", 2048);
    i64 fd = sys_open(TEST_ROOT "/dev/mem", F_RDONLY, 0);                  /* read-only: this descriptor cannot be mapped for writing */
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("\n"); return; }
    i64 m = sys_mmap_ro((int)fd, KLOG_SIZE, KLOG_PHYS);
    if (m == -1) { puts_("!! mmap of the kernel log buffer failed\n"); sys_close((int)fd); return; }
    puts_("== klog raw "); putnum((i64)KLOG_SIZE); puts_(" bytes follow\n");
    put((const void *)m, KLOG_SIZE);
    puts_("\n== klog end\n");
    sys_munmap((void *)m, KLOG_SIZE);
    sys_close((int)fd);
}
#endif

/* ------------------------------------------------------------------ level 10: the coprocessor's own logs, read-only */

#if LEVEL == 10
/* The three imports, all from libsencore.so (finding F512). The transfer is used with direction 0 only: coprocessor to buffer. */
extern u64 cam_dmm_alloc(u32 size, u32 *handle) __asm__("_Z9dmm_allocjPj");
extern u64 cam_dmm_free(u32 handle) __asm__("_Z8dmm_freej");
extern u32 sen_dma_transfer(u32 dir, u64 src, u64 dst, u32 size);

#define CP_PAGE 4096U
#define F_RDONLY_SYNC (0 | 0x101000)
#define RAM_LO 0x400000000UL
#define RAM_HI 0x500000000UL
/* Two logs in coprocessor memory, at the addresses of the coprocessor's boot configuration (tomco.txt: klog_addr, klog_size,
   boottime_addr, boottime_size). The kprint log keeps its contents across a restart without loss of power when its header is
   intact (cpapp-b.bin 0x56d218), so after a self-restart it can hold the messages of the start that failed. */
static const struct { u32 addr, len; const char *name; } cp_logs[] = {
    { 0x000E0000U, 0x20000U, "kprint" },
    { 0x000C0000U, 0x20000U, "boottime" },
};
static const u8 zero_page[CP_PAGE];

static void level10(void)
{
    u32 handle = 0;
    puts_("== level 10: the coprocessor's logs, read-only\n");
    u64 phys = cam_dmm_alloc(CP_PAGE, &handle);
    if (!phys) { puts_("!! buffer allocation failed; stopping level 10\n"); return; }
    if ((phys & 0x3f) || phys < RAM_LO || phys + CP_PAGE > RAM_HI) {
        puts_("!! buffer address is not 64-byte aligned inside system RAM; stopping level 10\n");
        cam_dmm_free(handle);
        return;
    }
    i64 fd = sys_open(TEST_ROOT "/dev/mem", F_RDONLY_SYNC, 0);
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("\n"); cam_dmm_free(handle); return; }
    u64 lead = phys & 0xfff, maplen = (lead + CP_PAGE + 0xfff) & ~0xfffUL;
    i64 m = sys_mmap_ro((int)fd, maplen, phys - lead);
    if (m == -1) { puts_("!! mmap of the buffer failed; stopping level 10\n"); sys_close((int)fd); cam_dmm_free(handle); return; }
    const u8 *buf = (const u8 *)m + lead;
    u32 failed = 0, fail_at = 0;
    for (u64 k = 0; k < sizeof cp_logs / sizeof cp_logs[0] && !failed; k++) {
        puts_("== cp log "); puts_(cp_logs[k].name); puts_(" raw "); putnum(cp_logs[k].len); puts_(" bytes follow\n");
        for (u32 off = 0; off < cp_logs[k].len; off += CP_PAGE) {
            if (failed) { put(zero_page, CP_PAGE); continue; }           /* the section keeps its length; the failure is reported below */
            /* THE ONLY TRANSFER IN LEVEL 10: one 4 KB page of a listed log, from the coprocessor into the buffer */
            u32 r = sen_dma_transfer(0, (u64)cp_logs[k].addr + off, phys, CP_PAGE);
            if (r) { failed = r; fail_at = cp_logs[k].addr + off; put(zero_page, CP_PAGE); continue; }
            put(buf, CP_PAGE);
        }
        puts_("\n== cp log end\n");
    }
    if (failed) {
        u8 a[4] = { (u8)(fail_at >> 24), (u8)(fail_at >> 16), (u8)(fail_at >> 8), (u8)fail_at };
        puts_("!! transfer failed "); putnum(failed); puts_(" at 0x"); puthex(a, 4); puts_("; the rest of that log is zeros and later logs were not read\n");
    } else {
        puts_("level 10 complete\n");
    }
    sys_munmap((void *)m, maplen);
    sys_close((int)fd);
    cam_dmm_free(handle);
    puts_("buffer released\n");
}
#endif

/* ------------------------------------------------------------------ level 12: the memory manager's state, read-only */

#if LEVEL == 12
/* The three imports, all from libsencore.so (finding F512). The transfer is used with direction 0 only: coprocessor to buffer. */
extern u64 cam_dmm_alloc(u32 size, u32 *handle) __asm__("_Z9dmm_allocjPj");
extern u64 cam_dmm_free(u32 handle) __asm__("_Z8dmm_freej");
extern u32 sen_dma_transfer(u32 dir, u64 src, u64 dst, u32 size);

#define CP_PAGE 4096U
#define F_RDONLY_SYNC (0 | 0x101000)
#define RAM_LO 0x400000000UL
#define RAM_HI 0x500000000UL
#define CP_LO 0x108000UL                   /* a pointer read from coprocessor memory must lie between these, or its range is not read */
#define CP_HI 0x10000000UL
/* The coprocessor's memory manager (cpapp-b.bin 6.02; reference/dmm_memory_manager.md, findings F671 to F674). */
#define G_WORKSPACE 0xabcU                 /* in the page of pointers, 0x1472abc: start of its workspace (handle records first; 0xaffbba) */
#define G_UNITS 0x610U                     /* 0x1472610: the unit objects, WS_UNITS_AT into the workspace */
#define G_CMDLOG 0x878U                    /* 0x1472878: its command log, a ring of 0x400 entries of 0x30 bytes (0x504ad0) */
#define WS_UNITS_AT 0x107e0U
#define WS_LEN 0x35230U                    /* handle records, unit objects, lists, scene, counters (0xaffbba, 0xafdac6) */
#define CMDLOG_LEN 0xc000U
/* Ranges at fixed addresses, whole pages. The first is the page that holds the manager's pointers. */
struct l12_range { u32 addr, len; const char *name; };
static const struct l12_range dmm_fixed[] = {
    { 0x01472000U, 0x1000U, "globals" },
    { 0x01f73000U, 0x7000U, "unit_records" },      /* its copy of the region records (0x1f730bc) and unit records (0x1f735bc to 0x1f79188) */
    { 0x01d9b000U, 0x4000U, "group_records" },     /* its copy of the head record (0x1d9b578) and the group records (0x1d9b618) */
    { 0x011c6000U, 0x9000U, "write_buffers" },     /* the camera core's write-buffer records, four classes from 0x11c6878 (0x42c724) */
    { 0x0143c000U, 0x1000U, "movie_tables" },      /* the movie size table 0x143c784 and the ring positions 0x143cfcc (0x4293c8, 0x42c724) */
};
static const u8 zero_page[CP_PAGE];
static u64 l12_phys;
static const u8 *l12_buf;
static u32 l12_fail_at;

static u32 le32(const u8 *p) { return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24; }
static void put32(const char *what, u32 v)
{
    u8 b[4] = { (u8)(v >> 24), (u8)(v >> 16), (u8)(v >> 8), (u8)v };
    puts_(what); puts_(" 0x"); puthex(b, 4); puts_("\n");
}
static int bad_pointer(u32 v) { return (v & 3) || v < CP_LO || v >= CP_HI; }

/* Copy `len` bytes (whole pages) at `addr` into the result. Returns 0, or the code of the transfer that failed: the rest of the
   range is then written as zeros, so the section keeps its length. */
static u32 dump_range(const char *name, u32 addr, u32 len)
{
    u8 a[4] = { (u8)(addr >> 24), (u8)(addr >> 16), (u8)(addr >> 8), (u8)addr };
    u32 failed = 0;
    puts_("== cp range "); puts_(name); puts_(" at 0x"); puthex(a, 4); puts_(" raw "); putnum(len); puts_(" bytes follow\n");
    for (u32 off = 0; off < len; off += CP_PAGE) {
        if (failed) { put(zero_page, CP_PAGE); continue; }
        /* THE ONLY TRANSFER IN LEVEL 12: one 4 KB page, from the coprocessor into the buffer */
        u32 r = sen_dma_transfer(0, (u64)addr + off, l12_phys, CP_PAGE);
        if (r) { failed = r; l12_fail_at = addr + off; put(zero_page, CP_PAGE); continue; }
        put(l12_buf, CP_PAGE);
    }
    puts_("\n== cp range end\n");
    return failed;
}

static void level12(void)
{
    u32 handle = 0;
    puts_("== level 12: the memory manager's state, read-only\n");
    l12_phys = cam_dmm_alloc(CP_PAGE, &handle);
    if (!l12_phys) { puts_("!! buffer allocation failed; stopping level 12\n"); return; }
    if ((l12_phys & 0x3f) || l12_phys < RAM_LO || l12_phys + CP_PAGE > RAM_HI) {
        puts_("!! buffer address is not 64-byte aligned inside system RAM; stopping level 12\n");
        cam_dmm_free(handle);
        return;
    }
    i64 fd = sys_open(TEST_ROOT "/dev/mem", F_RDONLY_SYNC, 0);
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("\n"); cam_dmm_free(handle); return; }
    u64 lead = l12_phys & 0xfff, maplen = (lead + CP_PAGE + 0xfff) & ~0xfffUL;
    i64 m = sys_mmap_ro((int)fd, maplen, l12_phys - lead);
    if (m == -1) { puts_("!! mmap of the buffer failed; stopping level 12\n"); sys_close((int)fd); cam_dmm_free(handle); return; }
    l12_buf = (const u8 *)m + lead;

    /* read through a volatile pointer, so that the table stays a table in the built file, where check_built.py compares it entry by entry */
    const struct l12_range *volatile tab = dmm_fixed;
    u32 ws = 0, units = 0, log = 0;
    u32 failed = dump_range(tab[0].name, tab[0].addr, tab[0].len);
    if (!failed) {                                              /* the buffer still holds the page of pointers */
        ws = le32(l12_buf + G_WORKSPACE); units = le32(l12_buf + G_UNITS); log = le32(l12_buf + G_CMDLOG);
    }
    for (u64 k = 1; k < sizeof dmm_fixed / sizeof dmm_fixed[0] && !failed; k++)
        failed = dump_range(tab[k].name, tab[k].addr, tab[k].len);
    if (!failed) {
        put32("workspace pointer", ws); put32("unit objects pointer", units); put32("command log pointer", log);
        if (bad_pointer(ws) || (u64)ws + WS_LEN > CP_HI || units != ws + WS_UNITS_AT)
            puts_("!! the workspace pointers are not as expected; the workspace is not read\n");
        else {
            u32 start = ws & ~0xfffU;
            failed = dump_range("workspace", start, ((ws + WS_LEN + 0xfffU) & ~0xfffU) - start);
        }
    }
    if (!failed) {
        if (bad_pointer(log) || (u64)log + CMDLOG_LEN > CP_HI)
            puts_("!! the command log pointer is not usable; the command log is not read\n");
        else {
            u32 start = log & ~0xfffU;
            failed = dump_range("command_log", start, ((log + CMDLOG_LEN + 0xfffU) & ~0xfffU) - start);
        }
    }
    if (failed) {
        u8 a[4] = { (u8)(l12_fail_at >> 24), (u8)(l12_fail_at >> 16), (u8)(l12_fail_at >> 8), (u8)l12_fail_at };
        puts_("!! transfer failed "); putnum(failed); puts_(" at 0x"); puthex(a, 4); puts_("; the rest of that range is zeros and later ranges were not read\n");
    } else {
        puts_("level 12 complete\n");
    }
    sys_munmap((void *)m, maplen);
    sys_close((int)fd);
    cam_dmm_free(handle);
    puts_("buffer released\n");
}
#endif

/* ------------------------------------------------------------------ level 15: the movie output state, read-only */

#if LEVEL == 15 || LEVEL == 21 || LEVEL == 28
/* Level 21 is this same code with its own table of ranges: the raw ports' state (the RDC objects of the device group), read-only.
   The three imports, all from libsencore.so (finding F512). The transfer is used with direction 0 only: coprocessor to buffer. */
extern u64 cam_dmm_alloc(u32 size, u32 *handle) __asm__("_Z9dmm_allocjPj");
extern u64 cam_dmm_free(u32 handle) __asm__("_Z8dmm_freej");
extern u32 sen_dma_transfer(u32 dir, u64 src, u64 dst, u32 size);

#define CP_PAGE 4096U
#define F_RDONLY_SYNC (0 | 0x101000)
#define RAM_LO 0x400000000UL
#define RAM_HI 0x500000000UL
/* Ranges at fixed addresses, whole pages (cpapp-b.bin 6.02; findings F680, F681, F684). Nothing is found through a pointer. */
struct l15_range { u32 addr, len; const char *name; };
#if LEVEL == 21
#define L15_N "21"
#define L15_HEAD "== level 21: the raw ports' state, read-only\n"
/* cpapp-b.bin 6.02: the device group object 0x10c14d0 (built by 0x6d5938 and 0x6d5f9c) holds the 25 RDC port objects at +0x13c to +0x1e88,
   0x3c bytes each; the port number is at +0x20 and the encoding type SetParam last stored at +0x2c (0x6d047c, 0x249048, 0x6d05e6, 0x6d07ea).
   The camera core's context is read as well, for the mode the camera is in. Nothing is found through a pointer. */
static const struct l15_range out_fixed[] = {
    { 0x010c1000U, 0x3000U, "rdc_ports" },         /* the device group 0x10c14d0 to past its last RDC object (0x10c3394 + 0x3c) */
    { 0x011d0000U, 0x2000U, "context" },           /* the camera core's context 0x11d0680, as in level 15: drive mode, window, output records */
};
#elif LEVEL == 28
#define L15_N "28"
#define L15_HEAD "== level 28: the frame widgets' state, read-only\n"
/* cpapp-b.bin 6.02 (findings F966, F967): the model rings the frame widgets cpActAfWindow and cpActTrackingFrame read (AF window 0x11fc258,
   tracking 0x12078f8, layout 0x12099b4, tracking frames 0x120e874, 32 entries each, with their index words), the tables of rectangles the
   widgets compare the live view with (0xd7b560 to 0xd7b6c8), and the page of the display's fit word and letterbox constants (0x1e4bcc,
   0x1e4dc4). Nothing is found through a pointer. */
static const struct l15_range out_fixed[] = {
    { 0x011fc000U, 0x15000U, "widget_models" },   /* 0x11fc000 to 0x1211000: the four model rings and their index words */
    { 0x00d7b000U, 0x1000U, "frame_tables" },     /* the three tables of expected live-view rectangles */
    { 0x001e4000U, 0x1000U, "vdf_words" },        /* the display's fit-mode table and letterbox constants */
};
#else
#define L15_N "15"
#define L15_HEAD "== level 15: the movie output state, read-only\n"
static const struct l15_range out_fixed[] = {
    { 0x011d0000U, 0x2000U, "context" },           /* the camera core's context 0x11d0680: its two parameter views, the window (+0xb14) and the four output records (+0xb34) */
    { 0x011cf000U, 0x1000U, "saved_records" },     /* the saved copies of the output records (0x11cf838) and of the block before them (0x11cf578) */
    { 0x0143c000U, 0x1000U, "movie_tables" },      /* the movie size table 0x143c784: output size and memory id by size class */
    { 0x01450000U, 0x3000U, "resize_state" },      /* the resize result 0x145091c, the drive-parameter copy 0x1450bc4, the resize module's settings 0x1452480 */
    { 0x011e1000U, 0x1000U, "resize_work" },       /* the resize working structure 0x11e1510 (pixel aspect +0x48, scales +0x4c, +0x50) */
    { 0x01fae000U, 0x1000U, "id_rows" },           /* the memory manager's id table: rows {id, pointer} from 0x1fae380 to the end row */
    { 0x01fb0000U, 0x1000U, "id_keys" },           /* its key lists from 0x1fb0380 */
};
#endif
static const u8 zero_page[CP_PAGE];
static u64 l15_phys;
static const u8 *l15_buf;
static u32 l15_fail_at;

/* Copy `len` bytes (whole pages) at `addr` into the result. Returns 0, or the code of the transfer that failed: the rest of the
   range is then written as zeros, so the section keeps its length. */
static u32 dump_range(const char *name, u32 addr, u32 len)
{
    u8 a[4] = { (u8)(addr >> 24), (u8)(addr >> 16), (u8)(addr >> 8), (u8)addr };
    u32 failed = 0;
    puts_("== cp range "); puts_(name); puts_(" at 0x"); puthex(a, 4); puts_(" raw "); putnum(len); puts_(" bytes follow\n");
    for (u32 off = 0; off < len; off += CP_PAGE) {
        if (failed) { put(zero_page, CP_PAGE); continue; }
        /* THE ONLY TRANSFER IN LEVEL 15: one 4 KB page, from the coprocessor into the buffer */
        u32 r = sen_dma_transfer(0, (u64)addr + off, l15_phys, CP_PAGE);
        if (r) { failed = r; l15_fail_at = addr + off; put(zero_page, CP_PAGE); continue; }
        put(l15_buf, CP_PAGE);
    }
    puts_("\n== cp range end\n");
    return failed;
}

static void level15(void)
{
    u32 handle = 0;
    puts_(L15_HEAD);
    l15_phys = cam_dmm_alloc(CP_PAGE, &handle);
    if (!l15_phys) { puts_("!! buffer allocation failed; stopping level " L15_N "\n"); return; }
    if ((l15_phys & 0x3f) || l15_phys < RAM_LO || l15_phys + CP_PAGE > RAM_HI) {
        puts_("!! buffer address is not 64-byte aligned inside system RAM; stopping level " L15_N "\n");
        cam_dmm_free(handle);
        return;
    }
    i64 fd = sys_open(TEST_ROOT "/dev/mem", F_RDONLY_SYNC, 0);
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("\n"); cam_dmm_free(handle); return; }
    u64 lead = l15_phys & 0xfff, maplen = (lead + CP_PAGE + 0xfff) & ~0xfffUL;
    i64 m = sys_mmap_ro((int)fd, maplen, l15_phys - lead);
    if (m == -1) { puts_("!! mmap of the buffer failed; stopping level " L15_N "\n"); sys_close((int)fd); cam_dmm_free(handle); return; }
    l15_buf = (const u8 *)m + lead;

    /* read through a volatile pointer, so that the table stays a table in the built file, where check_built.py compares it entry by entry */
    const struct l15_range *volatile tab = out_fixed;
    u32 failed = 0;
    for (u64 k = 0; k < sizeof out_fixed / sizeof out_fixed[0] && !failed; k++)
        failed = dump_range(tab[k].name, tab[k].addr, tab[k].len);
    if (failed) {
        u8 a[4] = { (u8)(l15_fail_at >> 24), (u8)(l15_fail_at >> 16), (u8)(l15_fail_at >> 8), (u8)l15_fail_at };
        puts_("!! transfer failed "); putnum(failed); puts_(" at 0x"); puthex(a, 4); puts_("; the rest of that range is zeros and later ranges were not read\n");
    } else {
        puts_("level " L15_N " complete\n");
    }
    sys_munmap((void *)m, maplen);
    sys_close((int)fd);
    cam_dmm_free(handle);
    puts_("buffer released\n");
}
#endif

/* ------------------------------------------------------------------ levels 13 and 14: four words of the memory manager's tables */

#if LEVEL == 13 || LEVEL == 14
#ifndef DMM_SITES_H
#error "levels 13 and 14 need -DDMM_SITES_H with the header that `gen_expected.py --dmm <design>` writes"
#endif
#include DMM_SITES_H                       /* dmm_sites, dmm_recs, dmm_parents, dmm_busy_keys, dmm_fit, DMM_DESIGN */

/* The three imports, all from libsencore.so (finding F512). Nothing else is called outside this file. */
extern u64 cam_dmm_alloc(u32 size, u32 *handle) __asm__("_Z9dmm_allocjPj");
extern u64 cam_dmm_free(u32 handle) __asm__("_Z8dmm_freej");
extern u32 sen_dma_transfer(u32 dir, u64 src, u64 dst, u32 size);   /* dir 0: coprocessor to buffer; dir 1: buffer to coprocessor */

#define CP_PAGE 4096U
#define F_RDWR_SYNC (2 | 0x101000)         /* O_RDWR | O_SYNC: for the helper's own buffer only */
#define RAM_LO 0x400000000UL
#define RAM_HI 0x500000000UL
#define CP_LO 0x108000UL                   /* coprocessor addresses this level will read: from the image's base ... */
#define CP_HI 0x10000000UL                 /* ... to 256 MB */
/* The coprocessor's memory manager (cpapp-b.bin 6.02; reference/dmm_memory_manager.md; seen on the camera, finding F677). */
#ifndef DMM_GLOBALS                        /* another build names its own (-DDMM_GLOBALS= -DG_WORKSPACE= -DG_UNITS=): helper_c2/build_c2_write.sh */
#define DMM_GLOBALS 0x01472000UL           /* the page that holds its pointers */
#define G_WORKSPACE 0xabcU                 /* 0x1472abc: start of its workspace */
#define G_UNITS 0x610U                     /* 0x1472610: the unit objects, WS_UNITS_AT into the workspace */
#endif
#define WS_UNITS_AT 0x107e0U
#define N_OBJ 0x580U                       /* unit objects in the pool (0xafedcc) */
#define OBJ 0x50U                          /* one unit object: +2 flags (bit 0: divided), +0x14 size, +0x20 parent object, +0x24 key */
#define POOL (N_OBJ * OBJ)
#define N_SITES (sizeof dmm_sites / sizeof dmm_sites[0])
/* The texts name the A7 IV design's four words; a design with another count names its own (-DDMM_WORDS_TEXT= ...: helper_zv/build_zv_write.sh).
   The defaults give the same strings as before, so the A7 IV and A7C II libraries build to their pinned hashes. */
#ifndef DMM_WORDS_TEXT
#define DMM_WORDS_TEXT "the four memory-manager words"
#define DMM_DONE_TEXT "all four sites hold"
#define DMM_RECS_TEXT "the four records and the parent's are as in the file; two units of the new size fit"
#define DMM_NOFIT_TEXT "two units of the new size do not fit the parent"
#endif
#if LEVEL == 13
#define FROM(s) ((s)->stock)               /* what a site must hold before */
#define TO(s) ((s)->changed)               /* what it holds after */
#define VERB "apply"
#else
#define FROM(s) ((s)->changed)
#define TO(s) ((s)->stock)
#define VERB "put back"
#endif

static u64 l13_phys;
static u8 *l13_buf;
static u8 l13_pool[POOL];                  /* a copy of the unit objects, to look for units made from the present records */

static u32 le32(const u8 *p) { return (u32)p[0] | (u32)p[1] << 8 | (u32)p[2] << 16 | (u32)p[3] << 24; }
static int bad_pointer(u32 v) { return (v & 3) || v < CP_LO || v >= CP_HI; }
static void put32(const char *what, u32 v)
{
    u8 b[4] = { (u8)(v >> 24), (u8)(v >> 16), (u8)(v >> 8), (u8)v };
    puts_(what); puts_(" 0x"); puthex(b, 4);
}

/* THE ONLY READ TRANSFER IN LEVELS 13 AND 14: `len` bytes at `addr`, as the whole 64-byte lines they lie in, at most a page. Null if refused
   or failed. Not inlined, so that the built file has this one call with direction 0 (check_built.py counts). */
__attribute__((noinline)) static const u8 *cp_read(u64 addr, u32 len)
{
    u64 base = addr & ~63UL, end = (addr + len + 63) & ~63UL;
    if (addr < CP_LO || addr + len > CP_HI || end - base > CP_PAGE) return 0;
    u32 n = (u32)(end - base);
    for (u32 i = 0; i < n; i++) l13_buf[i] = 0xee;                  /* so that a transfer that moves nothing cannot pass for a read */
    if (sen_dma_transfer(0, base, l13_phys, n)) return 0;
    return l13_buf + (addr - base);
}
/* THE ONLY TRANSFER TOWARDS THE COPROCESSOR IN LEVELS 13 AND 14: the one 64-byte line a listed site lies in, as read a moment before,
   with the site's four bytes replaced. Not inlined, so that the built file has this one call with direction 1 (check_built.py counts). */
__attribute__((noinline)) static int site_write(const struct dmm_site *s, const u8 *bytes)
{
    u64 base = s->address & ~63UL;
    if (!cp_read(base, 64)) return 1;                               /* the other 60 bytes of the line go back as they are now */
    u8 *at = l13_buf + (s->address - base);
    for (u32 i = 0; i < 4; i++) at[i] = bytes[i];
    return sen_dma_transfer(1, l13_phys, base, 64) != 0;
}
/* What a site holds: 0 its FROM bytes, 1 its TO bytes, 2 something else, 3 the read failed. */
static int site_state(const struct dmm_site *s)
{
    const u8 *p = cp_read(s->address, 4);
    if (!p) return 3;
    int from = 1, to = 1;
    for (u32 i = 0; i < 4; i++) { if (p[i] != FROM(s)[i]) from = 0; if (p[i] != TO(s)[i]) to = 0; }
    return to ? 1 : from ? 0 : 2;
}
static void say_site(const char *what, const struct dmm_site *s) { put32(what, s->address); puts_(": "); }

/* Everything that must hold before a word is written. 0: go on. Anything else: the reason has been written, and nothing is written. */
static int precheck(const struct dmm_rec *recs, u32 nrecs, const struct dmm_rec *parents, u32 nparents, const u32 *busy, u32 nbusy, const u32 *fit)
{
    const u8 *p = cp_read(DMM_GLOBALS + G_WORKSPACE, 4);
    if (!p) { puts_("!! the page of pointers could not be read; nothing is written\n"); return 1; }
    u32 ws = le32(p);
    if (!(p = cp_read(DMM_GLOBALS + G_UNITS, 4))) { puts_("!! the page of pointers could not be read; nothing is written\n"); return 1; }
    u32 units = le32(p);
    put32("workspace", ws); put32(", unit objects", units); puts_("\n");
    if (bad_pointer(ws) || units != ws + WS_UNITS_AT || (u64)units + POOL > CP_HI) {
        puts_("!! the workspace pointers are not as expected; nothing is written\n");
        return 1;
    }
    for (u32 done = 0; done < POOL;) {                              /* copy the unit objects out, whole lines at a time */
        u64 a = (u64)units + done;
        u32 n = POOL - done, lead = (u32)(a & 63);
        if (lead + n > CP_PAGE) n = CP_PAGE - lead;
        if (!(p = cp_read(a, n))) { puts_("!! the unit objects could not be read; nothing is written\n"); return 1; }
        for (u32 i = 0; i < n; i++) l13_pool[done + i] = p[i];
        done += n;
    }
    /* A unit object of one of the listed keys that belongs to a division still in force means a block is divided from the present records.
       The server would go on handing out that division's units, so the change would have no effect; and nothing should be changed under it. */
    for (u32 i = 0; i < N_OBJ; i++) {
        const u8 *o = l13_pool + i * OBJ;
        u32 key = le32(o + 0x24), size = le32(o + 0x14), parent = le32(o + 0x20);
        int listed = 0;
        for (u32 k = 0; k < nbusy; k++) if (key == busy[k]) listed = 1;
        if (!listed || !(key || size)) continue;
        int live = 1;                                               /* anything unexpected counts as in force */
        if (parent >= units && parent < units + POOL && (parent - units) % OBJ == 0)
            live = l13_pool[(parent - units) + 2] & 1;              /* the parent's "divided" flag: clear once the division was merged back */
        if (live) {
            put32("!! a unit of key", key); puts_(" exists: a block is divided from the present records; nothing is written\n");
            puts_("   Cold boot the camera and run this before movie mode is entered.\n");
            return 1;
        }
    }
    for (u32 k = 0; k < nrecs; k++) {                               /* the four records: every byte but the site's four as in the file */
        if (!(p = cp_read(recs[k].address, 20))) { puts_("!! a record could not be read; nothing is written\n"); return 1; }
        for (u32 j = 0; j < 20; j++)
            if ((j < recs[k].site_off || j >= recs[k].site_off + 4) && p[j] != recs[k].file[j]) {
                put32("!! the record at", recs[k].address); puts_(" is not as in the file; nothing is written\n");
                return 1;
            }
    }
    for (u32 k = 0; k < nparents; k++) {                            /* the parent's records: as in the file, and large enough */
        if (!(p = cp_read(parents[k].address, 20))) { puts_("!! a record could not be read; nothing is written\n"); return 1; }
        for (u32 j = 0; j < 20; j++)
            if (p[j] != parents[k].file[j]) {
                put32("!! the parent's record at", parents[k].address); puts_(" is not as in the file; nothing is written\n");
                return 1;
            }
        if ((u64)fit[1] * fit[0] > le32(p + 12)) { puts_("!! " DMM_NOFIT_TEXT "; nothing is written\n"); return 1; }
    }
    puts_("checks passed: no unit of the present division exists; " DMM_RECS_TEXT "\n");
    return 0;
}

static void level13(void)
{
    static u8 done[N_SITES];                                        /* 1: this run wrote the site */
    /* the tables are read through volatile pointers, so that they stay tables in the built file, where check_built.py compares them */
    const struct dmm_site *volatile sites = dmm_sites;
    const struct dmm_rec *volatile recs = dmm_recs;
    const struct dmm_rec *volatile parents = dmm_parents;
    const u32 *volatile busy = dmm_busy_keys;
    const u32 *volatile fit = dmm_fit;
    u32 handle = 0;
    puts_("== level "); putnum(LEVEL); puts_(": " VERB " " DMM_WORDS_TEXT " of " DMM_DESIGN "\n");
    l13_phys = cam_dmm_alloc(CP_PAGE, &handle);
    if (!l13_phys) { puts_("!! buffer allocation failed; nothing is written\n"); return; }
    if ((l13_phys & 0x3f) || l13_phys < RAM_LO || l13_phys + CP_PAGE > RAM_HI) {
        puts_("!! buffer address is not 64-byte aligned inside system RAM; nothing is written\n");
        cam_dmm_free(handle);
        return;
    }
    i64 fd = sys_open(TEST_ROOT "/dev/mem", F_RDWR_SYNC, 0);
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("; nothing is written\n"); cam_dmm_free(handle); return; }
    u64 lead = l13_phys & 0xfff, maplen = (lead + CP_PAGE + 0xfff) & ~0xfffUL;
    i64 m = sys_mmap_rw((int)fd, maplen, l13_phys - lead);             /* the helper's own buffer, nothing else */
    if (m == -1) { puts_("!! mmap of the buffer failed; nothing is written\n"); sys_close((int)fd); cam_dmm_free(handle); return; }
    l13_buf = (u8 *)m + lead;

    if (precheck(recs, sizeof dmm_recs / sizeof dmm_recs[0], parents, sizeof dmm_parents / sizeof dmm_parents[0], busy, sizeof dmm_busy_keys / sizeof dmm_busy_keys[0], fit))
        goto out;
    puts_("pass 1: read every site; nothing is written unless all are as expected\n");
    u32 todo = 0;
    for (u64 i = 0; i < N_SITES; i++) {
        const struct dmm_site *s = &sites[i];
        say_site("site", s);
        int st = site_state(s);
        if (st == 3) { puts_("!! read failed; nothing is written\n"); goto out; }
        if (st == 0) { puts_("as expected\n"); todo++; }
        else if (st == 1) puts_("already holds the target bytes\n");
        else { puts_("!! holds neither the file's nor the new bytes; nothing is written\n"); goto out; }
    }
    if (!todo) { puts_("NOTHING TO DO: every site already holds the target bytes\n"); goto out; }

    puts_("pass 2: write, and read each site back\n");
    int failed = 0;
    for (u64 i = 0; i < N_SITES && !failed; i++) {
        const struct dmm_site *s = &sites[i];
        int st = site_state(s);
        if (st == 3) { say_site("site", s); puts_("!! read failed\n"); failed = 1; break; }
        if (st == 1) continue;                                      /* was already there in pass 1 */
        say_site("site", s);
        if (st != 0) { puts_("!! no longer holds the bytes it held in pass 1\n"); failed = 1; break; }
        done[i] = 1;                                                /* from here on it counts as touched */
        if (site_write(s, TO(s))) { puts_("!! write failed\n"); failed = 1; break; }
        if (site_state(s) != 1) { puts_("!! not as written on read-back\n"); failed = 1; break; }
        puts_("written and read back\n");
    }
    if (!failed) {
        puts_("pass 3: read every site once more\n");
        for (u64 i = 0; i < N_SITES; i++) {
            const struct dmm_site *s = &sites[i];
            if (site_state(s) != 1) { say_site("site", s); puts_("!! does not hold the target bytes\n"); failed = 1; }
        }
    }
    if (!failed) { puts_("DONE: " DMM_DONE_TEXT " the target bytes (" VERB ")\n"); goto out; }

    puts_("undo: every site this run touched gets its earlier bytes back\n");
    int left = 0;
    for (u64 i = 0; i < N_SITES; i++) {
        const struct dmm_site *s = &sites[i];
        if (!done[i]) continue;
        say_site("undo", s);
        if (site_write(s, FROM(s)) || site_state(s) != 0) { puts_("!! NOT PUT BACK\n"); left++; }
        else puts_("put back and read back\n");
    }
    puts_(left ? "!! UNDO INCOMPLETE. Cold boot the camera (battery out) before anything else.\n"
               : "NOT DONE: a step failed; every site this run touched was put back\n");
out:
    sys_munmap((void *)m, maplen);
    sys_close((int)fd);
    cam_dmm_free(handle);
    puts_("buffer released\n");
}
#endif

/* ------------------------------------------------------------------ levels 16 and 17: words of a RAM table */

#if LEVEL == 16 || LEVEL == 17
#ifndef WORDS_H
#error "levels 16 and 17 need -DWORDS_H with the header that `gen_expected.py --words <design>` writes"
#endif
#include WORDS_H                           /* ram_words, ram_guards, WORDS_DESIGN */

/* The three imports, all from libsencore.so (finding F512). Nothing else is called outside this file. */
extern u64 cam_dmm_alloc(u32 size, u32 *handle) __asm__("_Z9dmm_allocjPj");
extern u64 cam_dmm_free(u32 handle) __asm__("_Z8dmm_freej");
extern u32 sen_dma_transfer(u32 dir, u64 src, u64 dst, u32 size);   /* dir 0: coprocessor to buffer; dir 1: buffer to coprocessor */

#define CP_PAGE 4096U
#define F_RDWR_SYNC (2 | 0x101000)         /* O_RDWR | O_SYNC: for the helper's own buffer only */
#define RAM_LO 0x400000000UL
#define RAM_HI 0x500000000UL
#define CP_LO 0x108000UL                   /* coprocessor addresses this level will read: from the image's base ... */
#define CP_HI 0x10000000UL                 /* ... to 256 MB */
#define N_WORDS (sizeof ram_words / sizeof ram_words[0])
#define N_GUARDS (sizeof ram_guards / sizeof ram_guards[0])
#if LEVEL == 16
#define FROM(s) ((s)->stock)               /* what a site must hold before */
#define TO(s) ((s)->changed)               /* what it holds after */
#define VERB "apply"
#else
#define FROM(s) ((s)->changed)
#define TO(s) ((s)->stock)
#define VERB "put back"
#endif

static u64 l16_phys;
static u8 *l16_buf;

static void put32(const char *what, u32 v)
{
    u8 b[4] = { (u8)(v >> 24), (u8)(v >> 16), (u8)(v >> 8), (u8)v };
    puts_(what); puts_(" 0x"); puthex(b, 4);
}

/* THE ONLY READ TRANSFER IN LEVELS 16 AND 17: `len` bytes at `addr`, as the whole 64-byte lines they lie in, at most a page. Null if refused
   or failed. Not inlined, so that the built file has this one call with direction 0 (check_built.py counts). */
__attribute__((noinline)) static const u8 *cp_read(u64 addr, u32 len)
{
    u64 base = addr & ~63UL, end = (addr + len + 63) & ~63UL;
    if (addr < CP_LO || addr + len > CP_HI || end - base > CP_PAGE) return 0;
    u32 n = (u32)(end - base);
    for (u32 i = 0; i < n; i++) l16_buf[i] = 0xee;                  /* so that a transfer that moves nothing cannot pass for a read */
    if (sen_dma_transfer(0, base, l16_phys, n)) return 0;
    return l16_buf + (addr - base);
}
/* THE ONLY TRANSFER TOWARDS THE COPROCESSOR IN LEVELS 16 AND 17: the one 64-byte line a listed site lies in, as read a moment before,
   with the site's four bytes replaced. Not inlined, so that the built file has this one call with direction 1 (check_built.py counts). */
__attribute__((noinline)) static int word_write(const struct ram_word *s, const u8 *bytes)
{
    u64 base = s->address & ~63UL;
    if (!cp_read(base, 64)) return 1;                               /* the other 60 bytes of the line go back as they are now */
    u8 *at = l16_buf + (s->address - base);
    for (u32 i = 0; i < 4; i++) at[i] = bytes[i];
    return sen_dma_transfer(1, l16_phys, base, 64) != 0;
}
/* What a site holds: 0 its FROM bytes, 1 its TO bytes, 2 something else, 3 the read failed. */
static int word_state(const struct ram_word *s)
{
    const u8 *p = cp_read(s->address, 4);
    if (!p) return 3;
    int from = 1, to = 1;
    for (u32 i = 0; i < 4; i++) { if (p[i] != FROM(s)[i]) from = 0; if (p[i] != TO(s)[i]) to = 0; }
    return to ? 1 : from ? 0 : 2;
}
static void say_word(const char *what, const struct ram_word *s) { put32(what, s->address); puts_(": "); }

static void level16(void)
{
    static u8 done[N_WORDS];                                        /* 1: this run wrote the site */
    /* the tables are read through volatile pointers, so that they stay tables in the built file, where check_built.py compares them */
    const struct ram_word *volatile words = ram_words;
    const struct ram_guard *volatile guards = ram_guards;
    u32 handle = 0;
    puts_("== level "); putnum(LEVEL); puts_(": " VERB " the words of " WORDS_DESIGN "\n");
    l16_phys = cam_dmm_alloc(CP_PAGE, &handle);
    if (!l16_phys) { puts_("!! buffer allocation failed; nothing is written\n"); return; }
    if ((l16_phys & 0x3f) || l16_phys < RAM_LO || l16_phys + CP_PAGE > RAM_HI) {
        puts_("!! buffer address is not 64-byte aligned inside system RAM; nothing is written\n");
        cam_dmm_free(handle);
        return;
    }
    i64 fd = sys_open(TEST_ROOT "/dev/mem", F_RDWR_SYNC, 0);
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("; nothing is written\n"); cam_dmm_free(handle); return; }
    u64 lead = l16_phys & 0xfff, maplen = (lead + CP_PAGE + 0xfff) & ~0xfffUL;
    i64 m = sys_mmap_rw((int)fd, maplen, l16_phys - lead);             /* the helper's own buffer, nothing else */
    if (m == -1) { puts_("!! mmap of the buffer failed; nothing is written\n"); sys_close((int)fd); cam_dmm_free(handle); return; }
    l16_buf = (u8 *)m + lead;

    /* The bytes beside the sites must be what the table held when it was read on the camera: otherwise this is not the table, and nothing is written. */
    for (u64 k = 0; k < N_GUARDS; k++) {
        const struct ram_guard *g = &guards[k];
        const u8 *p = cp_read(g->address, g->len);
        if (!p) { put32("!! the bytes at", g->address); puts_(" could not be read; nothing is written\n"); goto out; }
        for (u32 j = 0; j < g->len; j++)
            if (p[j] != g->bytes[j]) { put32("!! the bytes at", g->address); puts_(" are not as expected; nothing is written\n"); goto out; }
    }
    puts_("checks passed: the bytes beside the sites are as expected\n");
    puts_("pass 1: read every site; nothing is written unless all are as expected\n");
    u32 todo = 0;
    for (u64 i = 0; i < N_WORDS; i++) {
        const struct ram_word *s = &words[i];
        say_word("site", s);
        int st = word_state(s);
        if (st == 3) { puts_("!! read failed; nothing is written\n"); goto out; }
        if (st == 0) { puts_("as expected\n"); todo++; }
        else if (st == 1) puts_("already holds the target bytes\n");
        else { puts_("!! holds neither the earlier nor the new bytes; nothing is written\n"); goto out; }
    }
    if (!todo) { puts_("NOTHING TO DO: every site already holds the target bytes\n"); goto out; }

    puts_("pass 2: write, and read each site back\n");
    int failed = 0;
    for (u64 i = 0; i < N_WORDS && !failed; i++) {
        const struct ram_word *s = &words[i];
        int st = word_state(s);
        if (st == 3) { say_word("site", s); puts_("!! read failed\n"); failed = 1; break; }
        if (st == 1) continue;                                      /* was already there in pass 1 */
        say_word("site", s);
        if (st != 0) { puts_("!! no longer holds the bytes it held in pass 1\n"); failed = 1; break; }
        done[i] = 1;                                                /* from here on it counts as touched */
        if (word_write(s, TO(s))) { puts_("!! write failed\n"); failed = 1; break; }
        if (word_state(s) != 1) { puts_("!! not as written on read-back\n"); failed = 1; break; }
        puts_("written and read back\n");
    }
    if (!failed) {
        puts_("pass 3: read every site once more\n");
        for (u64 i = 0; i < N_WORDS; i++) {
            const struct ram_word *s = &words[i];
            if (word_state(s) != 1) { say_word("site", s); puts_("!! does not hold the target bytes\n"); failed = 1; }
        }
    }
    if (!failed) { puts_("DONE: every site holds the target bytes (" VERB ")\n"); goto out; }

    puts_("undo: every site this run touched gets its earlier bytes back\n");
    int left = 0;
    for (u64 i = 0; i < N_WORDS; i++) {
        const struct ram_word *s = &words[i];
        if (!done[i]) continue;
        say_word("undo", s);
        if (word_write(s, FROM(s)) || word_state(s) != 0) { puts_("!! NOT PUT BACK\n"); left++; }
        else puts_("put back and read back\n");
    }
    puts_(left ? "!! UNDO INCOMPLETE. Cold boot the camera (battery out) before anything else.\n"
               : "NOT DONE: a step failed; every site this run touched was put back\n");
out:
    sys_munmap((void *)m, maplen);
    sys_close((int)fd);
    cam_dmm_free(handle);
    puts_("buffer released\n");
}
#endif

/* ------------------------------------------------------------------ level 18: the encoder-side sites on the main processor, read-only */

#if LEVEL >= 18 && LEVEL <= 20
#ifndef MP_H
#error "levels 18 to 20 need -DMP_H with the header that `gen_expected.py --mp <design>` writes"
#endif
#include MP_H                              /* MP_DESIGN, MP_AV_FIRST, MP_AV_BYTES, struct mp_site, mp_av[], mp_lm[] */
#ifndef MP_LIB                             /* the library the mp_lm table is in; a header may name another (lcdcycle_v1: appFw.so) */
#define MP_LIB "libmpr.so"
#endif

#if LEVEL == 18
struct mp_tally { u32 guards, guards_ok, sites, stock, target, other; };
#endif

static void mp_putx(u64 v)
{
    u8 be[8]; int k = 0;
    for (int i = 0; i < 8; i++) be[i] = (u8)(v >> (8 * (7 - i)));
    while (k < 7 && !be[k]) k++;
    puts_("0x"); puthex(be + k, (u64)(8 - k));
}

static int mp_eq(const u8 *a, const u8 *b, u32 n)
{
    for (u32 i = 0; i < n; i++) if (a[i] != b[i]) return 0;
    return 1;
}

#if LEVEL == 18
/* One table against memory. `mem` is where the byte at file offset `first` lies; only [first, first + span) may be read. */
static void mp_check(const char *tag, const struct mp_site *t, u64 n, const u8 *mem, u64 first, u64 span, struct mp_tally *y)
{
    for (u64 i = 0; i < n; i++) {
        u8 got[16];
        u32 len = t[i].len;
        puts_("  "); puts_(tag); puts_(" "); putnum((i64)i); puts_(t[i].kind ? " site " : " guard "); mp_putx(t[i].off); puts_(" "); putnum(len);
        if (len > 16 || t[i].off < first || t[i].off + len > first + span) { puts_(" !! outside the range read\n"); y->other++; continue; }
        for (u32 k = 0; k < len; k++) got[k] = mem[t[i].off - first + k];     /* read once; what is printed is what was compared */
        if (!t[i].kind) {
            y->guards++;
            if (mp_eq(got, t[i].stock, len)) { y->guards_ok++; puts_(" SAME "); } else puts_(" DIFFERS ");
        } else {
            y->sites++;
            if (mp_eq(got, t[i].stock, len)) { y->stock++; puts_(" STOCK "); }
            else if (mp_eq(got, t[i].changed, len)) { y->target++; puts_(" TARGET "); }
            else { y->other++; puts_(" OTHER "); }
        }
        puthex(got, len); puts_("\n");
    }
}
#endif

static int mp_hex(const char **pp, u64 *out)
{
    const char *p = *pp; u64 v = 0; int n = 0;
    for (;; p++, n++) {
        char c = *p; u32 d;
        if (c >= '0' && c <= '9') d = (u32)(c - '0');
        else if (c >= 'a' && c <= 'f') d = (u32)(c - 'a' + 10);
        else break;
        v = v << 4 | d;
    }
    *pp = p; *out = v;
    return n;
}

/* One line of /proc/self/maps: "start-end perms offset dev inode path". Taken when the path ends with /MP_LIB and the offset is 0. */
static int mp_line(const char *s, u64 n, u64 *lo, u64 *hi, char *perms)
{
    static const char want[] = "/" MP_LIB;
    u64 w = sizeof want - 1, a, b, off;
    const char *p = s;
    if (n < w) return 0;
    for (u64 k = 0; k < w; k++) if (s[n - w + k] != want[k]) return 0;
    if (!mp_hex(&p, &a) || *p++ != '-' || !mp_hex(&p, &b) || *p++ != ' ') return 0;
    for (int k = 0; k < 4; k++) { if (!*p) return 0; perms[k] = *p++; }
    perms[4] = 0;
    if (*p++ != ' ' || !mp_hex(&p, &off) || off != 0 || b <= a) return 0;
    *lo = a; *hi = b;
    return 1;
}

static int mp_find_lib(u64 *lo, u64 *hi, char *perms)
{
    static u8 buf[4096];
    static char line[512];
    u64 n = 0; int found = 0, over = 0;
    i64 fd = sys_open(TEST_ROOT "/proc/self/maps", F_RDONLY, 0);
    if (fd < 0) return 0;
    for (;;) {
        i64 r = sys_read((int)fd, buf, sizeof buf);
        if (r <= 0) break;
        for (i64 i = 0; i < r; i++) {
            char c = (char)buf[i];
            if (c != '\n') { if (n + 1 < sizeof line) line[n++] = c; else over = 1; continue; }
            line[n] = 0;
            if (!over && !found && mp_line(line, n, lo, hi, perms)) found = 1;       /* the first such line; the rest of the file is read and ignored */
            n = 0; over = 0;
        }
    }
    sys_close((int)fd);
    return found;
}

#if LEVEL == 18
static void mp_sum(const char *what, const struct mp_tally *y)
{
    puts_(what); puts_(": guards "); putnum(y->guards_ok); puts_(" of "); putnum(y->guards); puts_(" as in the file; sites: ");
    putnum(y->stock); puts_(" stock, "); putnum(y->target); puts_(" target, "); putnum(y->other); puts_(" other\n");
}

static void level18(void)
{
    struct mp_tally av = { 0, 0, 0, 0, 0, 0 }, lm = { 0, 0, 0, 0, 0, 0 };
    u64 n_av = sizeof mp_av / sizeof mp_av[0], n_lm = sizeof mp_lm / sizeof mp_lm[0];
    int av_read = 0, lm_read = 0;
    puts_("== level 18: the encoder-side sites of " MP_DESIGN ", read-only\n");

    puts_("av-cam.bin at physical "); mp_putx((u64)AVCAM_PHYS); puts_(", "); putnum((i64)n_av); puts_(" entries\n");
    i64 fd = sys_open(TEST_ROOT "/dev/mem", F_RDONLY, 0);                  /* read-only: this descriptor cannot be mapped for writing */
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("\n"); }
    else {
        i64 m = sys_mmap_ro((int)fd, MP_AV_BYTES, (u64)AVCAM_PHYS + MP_AV_FIRST);
        if (m == -1) puts_("!! mmap of the av-cam.bin tables failed\n");
        else {
            mp_check("av", mp_av, n_av, (const u8 *)m, MP_AV_FIRST, MP_AV_BYTES, &av);
            sys_munmap((void *)m, MP_AV_BYTES);
            av_read = 1;
        }
        sys_close((int)fd);
    }
    mp_sum("av-cam.bin", &av);

    u64 lo = 0, hi = 0; char perms[8];
    if (!mp_find_lib(&lo, &hi, perms)) puts_("!! " MP_LIB " is not in this process's list of mappings\n");
    else {
        puts_(MP_LIB " mapped at "); mp_putx(lo); puts_("-"); mp_putx(hi); puts_(" "); puts_(perms); puts_(", "); putnum((i64)n_lm); puts_(" entries\n");
        if (perms[0] != 'r') puts_("!! that mapping is not readable\n");
        else { mp_check("lm", mp_lm, n_lm, (const u8 *)lo, 0, hi - lo, &lm); lm_read = 1; }     /* this process's own memory, inside that mapping only */
    }
    mp_sum(MP_LIB, &lm);

    int whole = av_read && lm_read && av.guards == av.guards_ok && lm.guards == lm.guards_ok && av.sites + lm.sites == n_av + n_lm - av.guards - lm.guards;
    if (whole && !av.target && !av.other && !lm.target && !lm.other) puts_("== level 18 verdict: READY: every guard is as in the file and every site holds the stock bytes\n");
    else if (whole && !av.stock && !av.other && !lm.stock && !lm.other) puts_("== level 18 verdict: APPLIED: every guard is as in the file and every site holds the design's bytes\n");
    else puts_("== level 18 verdict: NOT READY: see the lines above\n");
}
#endif
#endif

/* ------------------------------------------------------------------ level 22: the VCD codec's state, read-only */

#if LEVEL == 22
/* Addresses: reference/vcd_boot_protocol.md (F753, F754). All reads are aligned 32-bit loads through uncached mappings. */
#define V_SCU_PAGE  0xF1388000UL               /* SCU: only +0x70 is read (av-cam's read helper 0x1294a0c reads +0 of a register) */
#define V_SCU_CLK   0x70UL
#define V_SCU_BITS  0x1CU                      /* bits av-cam sets at clock-on (0x10, 0x08, 0x04) and clears at clock-off */
#define V_PBL_PAGE  0xF3400000UL               /* clock/reset block, device 0x73: 0x830, 0x838, 0xA30, 0xA38 */
#define V_VCD_BASE  0xF3800000UL               /* the codec's host window; pages 0 to 4 are mapped, six words read */
#define V_VCD_LEN   0x5000UL
#define V_DRAM_BASE 0x400000000UL              /* codec bus address B is CPU-physical 0x400000000 + B (av-cam table 0xffffffc001324df8) */
#define V_PROG_SIZE 0x1400000UL                /* av-cam's pool for the program area (dmm id 0x1d0) */
#define V_AV_VA     0xffffffc001000000UL       /* av-cam.bin is mapped here; its physical address is AVCAM_PHYS */
#define V_SYNC      (0 | 0x101000)             /* O_RDONLY | O_SYNC */

static const u32 v_pbl[] = { 0x830, 0x838, 0xA30, 0xA38 };
static const u32 v_vcd[] = { 0x80, 0x84, 0x88, 0x90, 0x1000, 0x4204 };   /* never 0x4200 or 0x4208 (interrupt status) */
static const u64 v_av[] = { 0xffffffc001b8a130UL, 0xffffffc001b8a138UL, 0xffffffc001b8a140UL, 0xffffffc001b8a148UL,
                            0xffffffc001b8a150UL, 0xffffffc001b8a158UL, 0xffffffc001b8a160UL };   /* window pointers set by 0x1269770 */
static const u64 v_av32[] = { 0xffffffc001b61264UL, 0xffffffc001b61268UL };                    /* stored by ImolaVcdBoot and its check */
struct v_span { u32 off, len; const char *what; };
static const struct v_span v_prog[] = {
    { 0x0, 0x40, "boot stub header" },
    { 0x9000, 0x20, "start of the SPU code" },
    { 0x1300000, 0x40, "log area head" },
    { 0x13f0000, 0x100, "hello_v1 record area" },
};

static void v_x32(u32 v) { u8 b[4] = { (u8)(v >> 24), (u8)(v >> 16), (u8)(v >> 8), (u8)v }; puts_("0x"); puthex(b, 4); }
static void v_x64(u64 v) { u8 b[8]; for (int i = 0; i < 8; i++) b[i] = (u8)(v >> (8 * (7 - i))); puts_("0x"); puthex(b, 8); }
static u32 v_rd(i64 m, u64 off) { return *(volatile const u32 *)(m + (i64)off); }

static void level22(void)
{
    puts_("== level 22: the VCD codec's state, read-only\n");
    i64 fd = sys_open(TEST_ROOT "/dev/mem", V_SYNC, 0);          /* read-only: this descriptor cannot be mapped for writing */
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("\n== level 22 verdict: NOTHING READ\n"); return; }

    /* 1. av-cam.bin's data: the window pointers it sets when it boots the codec */
    i64 m = sys_mmap_ro((int)fd, 0x1000, (u64)AVCAM_PHYS + ((v_av[0] - V_AV_VA) & ~0xFFFUL));
    if (m == -1) puts_("!! mmap of av-cam.bin's data page failed\n");
    else {
        for (u64 i = 0; i < sizeof v_av / sizeof v_av[0]; i++) {
            u64 o = (v_av[i] - V_AV_VA) & 0xFFFUL;
            u64 v = (u64)v_rd(m, o) | (u64)v_rd(m, o + 4) << 32;
            puts_("avcam "); v_x64(v_av[i]); puts_(" = "); v_x64(v); puts_("\n");
        }
        sys_munmap((void *)m, 0x1000);
    }
    m = sys_mmap_ro((int)fd, 0x1000, (u64)AVCAM_PHYS + ((v_av32[0] - V_AV_VA) & ~0xFFFUL));
    if (m == -1) puts_("!! mmap of av-cam.bin's second data page failed\n");
    else {
        for (u64 i = 0; i < sizeof v_av32 / sizeof v_av32[0]; i++) {
            puts_("avcam "); v_x64(v_av32[i]); puts_(" = "); v_x32(v_rd(m, (v_av32[i] - V_AV_VA) & 0xFFFUL)); puts_("\n");
        }
        sys_munmap((void *)m, 0x1000);
    }

    /* 2. the clock word and the clock/reset block: control registers av-cam reads itself */
    u32 scu = 0; int have_scu = 0;
    m = sys_mmap_ro((int)fd, 0x1000, V_SCU_PAGE);
    if (m == -1) puts_("!! mmap of the SCU page failed\n");
    else {
        scu = v_rd(m, V_SCU_CLK); have_scu = 1;
        sys_munmap((void *)m, 0x1000);
        puts_("scu 0xf1388070 = "); v_x32(scu); puts_("\n");
    }
    m = sys_mmap_ro((int)fd, 0x1000, V_PBL_PAGE);
    if (m == -1) puts_("!! mmap of the clock/reset page failed\n");
    else {
        u32 pv[4];
        for (u64 i = 0; i < 4; i++) pv[i] = v_rd(m, v_pbl[i]);
        sys_munmap((void *)m, 0x1000);
        for (u64 i = 0; i < 4; i++) { puts_("pbl "); v_x32((u32)(V_PBL_PAGE + v_pbl[i])); puts_(" = "); v_x32(pv[i]); puts_("\n"); }
    }
    if (!have_scu || (scu & V_SCU_BITS) != V_SCU_BITS) {
        puts_("gate: the codec is not clocked (or the SCU word was not read); its window and program area are not read\n");
        sys_close((int)fd);
        puts_("== level 22 verdict: CODEC OFF\n");
        return;
    }
    puts_("gate: the codec is clocked\n");

    /* 3. the codec's window: registers av-cam reads, never the interrupt status */
    u32 reg[6] = { 0, 0, 0, 0, 0, 0 }; int have_reg = 0;
    m = sys_mmap_ro((int)fd, V_VCD_LEN, V_VCD_BASE);
    if (m == -1) puts_("!! mmap of the codec window failed\n");
    else {
        for (u64 i = 0; i < 6; i++) reg[i] = v_rd(m, v_vcd[i]);
        sys_munmap((void *)m, V_VCD_LEN);
        have_reg = 1;
        for (u64 i = 0; i < 6; i++) { puts_("vcd "); v_x32((u32)(V_VCD_BASE + v_vcd[i])); puts_(" = "); v_x32(reg[i]); puts_("\n"); }
    }
    m = sys_mmap_ro((int)fd, 0x1000, V_SCU_PAGE);
    if (m != -1) {
        u32 after = v_rd(m, V_SCU_CLK);
        sys_munmap((void *)m, 0x1000);
        puts_("scu after = "); v_x32(after);
        puts_((after & V_SCU_BITS) == V_SCU_BITS ? " (still clocked)\n" : " (CLOCKED OFF MEANWHILE: the window values may be invalid)\n");
    }

    /* 4. the program area, at the bus address in +0x84 */
    u32 b84 = reg[1];
    if (!have_reg || !b84 || (b84 & 0xFFF) || b84 != reg[2] || (u64)b84 + V_PROG_SIZE > 0x100000000UL) {
        puts_("program base not usable (+0x84 zero, unaligned, unequal to +0x88, or too high); the program area is not read\n");
    } else {
        u64 pbase = V_DRAM_BASE + b84;
        puts_("program area at physical "); v_x64(pbase); puts_("\n");
        for (u64 i = 0; i < sizeof v_prog / sizeof v_prog[0]; i++) {
            u64 a = pbase + v_prog[i].off, pg = a & ~0xFFFUL, len = ((a - pg) + v_prog[i].len + 0xFFF) & ~0xFFFUL;
            u8 buf[0x100];
            puts_("prog +"); v_x32(v_prog[i].off); puts_(" "); putnum(v_prog[i].len); puts_(" "); puts_(v_prog[i].what); puts_(" ");
            m = sys_mmap_ro((int)fd, len, pg);
            if (m == -1) { puts_("!! mmap failed\n"); continue; }
            for (u32 k = 0; k < v_prog[i].len; k += 4) {
                u32 w = v_rd(m, a - pg + k);
                buf[k] = (u8)w; buf[k + 1] = (u8)(w >> 8); buf[k + 2] = (u8)(w >> 16); buf[k + 3] = (u8)(w >> 24);
            }
            sys_munmap((void *)m, len);
            puthex(buf, v_prog[i].len); puts_("\n");
        }
    }
    sys_close((int)fd);
    puts_(have_reg && reg[0] == 0 ? "== level 22 verdict: CODEC ON, RUNNING (+0x80 = 0)\n" : "== level 22 verdict: CODEC ON, see the lines above\n");
}
#endif

/* ------------------------------------------------------------------ level 26: the VCD program area as plain memory, read-only */

#if LEVEL == 26
/* F780: after a recording av-cam's word 0xffffffc001b61268 holds the low half of the program buffer's kernel address (linear map),
 * so the program area is at CPU-physical 0x400000000 + that word. This level reads it as DRAM: no codec register, no gate needed.
 * The word is read at run time, never assumed; if it is zero (no boot since power-on) nothing else is read. */
#define W_AV_VA     0xffffffc001000000UL
#define W_AV_WORD   0xffffffc001b61268UL       /* (u32) program buffer address, stored by 0x126b158 */
#define W_AV_AREAS  0xffffffc001b61264UL       /* result areas (0x100 after a boot): shows the word is ImolaVcdBoot's */
#define W_DRAM_BASE 0x400000000UL
#define W_PROG_SIZE 0x1400000UL
#define W_SCU_PAGE  0xF1388000UL               /* context only: the clock word, as level 22 reads it */
#define W_SYNC      (0 | 0x101000)             /* O_RDONLY | O_SYNC */

struct w_span { u32 off, len; const char *what; };
static const struct w_span w_prog[] = {
    { 0x0, 0x40, "SPU boot stub header" },
    { 0x9000, 0x20, "start of the SPU code" },
    { 0xa6a000, 0x40, "MBP0 boot stub header" },
    { 0xa6d000, 0x40, "MBP1 boot stub header" },
    { 0x1300000, 0x40, "log area head" },
    { 0x13f0000, 0x100, "hello_v1 record area" },
};

static void w_x32(u32 v) { u8 b[4] = { (u8)(v >> 24), (u8)(v >> 16), (u8)(v >> 8), (u8)v }; puts_("0x"); puthex(b, 4); }
static void w_x64(u64 v) { u8 b[8]; for (int i = 0; i < 8; i++) b[i] = (u8)(v >> (8 * (7 - i))); puts_("0x"); puthex(b, 8); }
static u32 w_rd(i64 m, u64 off) { return *(volatile const u32 *)(m + (i64)off); }

static void level26(void)
{
    puts_("== level 26: the VCD program area as memory, read-only\n");
    i64 fd = sys_open(TEST_ROOT "/dev/mem", W_SYNC, 0);          /* read-only: this descriptor cannot be mapped for writing */
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("\n== level 26 verdict: NOTHING READ\n"); return; }

    u32 word = 0, areas = 0; int have = 0;
    i64 m = sys_mmap_ro((int)fd, 0x1000, (u64)AVCAM_PHYS + ((W_AV_WORD - W_AV_VA) & ~0xFFFUL));
    if (m == -1) puts_("!! mmap of av-cam.bin's data page failed\n");
    else {
        word = w_rd(m, (W_AV_WORD - W_AV_VA) & 0xFFFUL);
        areas = w_rd(m, (W_AV_AREAS - W_AV_VA) & 0xFFFUL);
        sys_munmap((void *)m, 0x1000);
        have = 1;
        puts_("avcam 0xffffffc001b61268 = "); w_x32(word); puts_("\navcam 0xffffffc001b61264 = "); w_x32(areas); puts_("\n");
    }
    m = sys_mmap_ro((int)fd, 0x1000, W_SCU_PAGE);
    if (m != -1) {
        u32 scu = w_rd(m, 0x70);
        sys_munmap((void *)m, 0x1000);
        puts_("scu 0xf1388070 = "); w_x32(scu); puts_((scu & 0x1C) == 0x1C ? " (codec clocked)\n" : " (codec not clocked)\n");
    }
    if (!have || !word || areas != 0x100) {
        sys_close((int)fd);
        puts_("== level 26 verdict: NO BOOT SINCE POWER-ON (or the word was not read); nothing else is read\n");
        return;
    }
    if ((word & 0xFFF) || (u64)word + W_PROG_SIZE > 0x100000000UL) {
        sys_close((int)fd);
        puts_("== level 26 verdict: ADDRESS NOT USABLE (unaligned or too high); nothing else is read\n");
        return;
    }
    u64 pbase = W_DRAM_BASE + word;
    puts_("program area at physical "); w_x64(pbase); puts_("\n");
    int got = 0;
    for (u64 i = 0; i < sizeof w_prog / sizeof w_prog[0]; i++) {
        u64 a = pbase + w_prog[i].off, pg = a & ~0xFFFUL, len = ((a - pg) + w_prog[i].len + 0xFFF) & ~0xFFFUL;
        u8 buf[0x100];
        puts_("prog +"); w_x32(w_prog[i].off); puts_(" "); putnum(w_prog[i].len); puts_(" "); puts_(w_prog[i].what); puts_(" ");
        m = sys_mmap_ro((int)fd, len, pg);
        if (m == -1) { puts_("!! mmap failed\n"); continue; }
        for (u32 k = 0; k < w_prog[i].len; k += 4) {
            u32 w = w_rd(m, a - pg + k);
            buf[k] = (u8)w; buf[k + 1] = (u8)(w >> 8); buf[k + 2] = (u8)(w >> 16); buf[k + 3] = (u8)(w >> 24);
        }
        sys_munmap((void *)m, len);
        puthex(buf, w_prog[i].len); puts_("\n");
        got++;
    }
    sys_close((int)fd);
    puts_(got ? "== level 26 verdict: PROGRAM AREA READ\n" : "== level 26 verdict: EVERY MAPPING REFUSED\n");
}
#endif

/* ------------------------------------------------------------------ level 27: hello_v1 run on the VCD codec CPUs (stage V4), WRITES */

#if LEVEL == 27
/* modding/VCD_V4_DESIGN.md; F753-F758, F780-F782. Writes three boot stubs into the codec's program area (DRAM), replays av-cam's own
 * clock-on, releases the codec CPUs, reads the records the stubs write, replays av-cam's own clock-off and puts every byte back. */
#ifndef V4_H
#error "level 27 needs -DV4_H with the header that gen_v4_header.py writes"
#endif
#include V4_H                               /* V4_DESIGN, V4_BUS, v4_off[], v4_len[], v4_stock[][], v4_new[][], v4_spu[] */
#ifndef V4_BLK
#define V4_BLK 256                          /* bytes checked and kept per stub; a header for a larger stub sets it (hello_v2: 1024) */
#endif

#define NR_pread64 67
#define NR_clock_gettime 113
#define F_RDWR 2                            /* O_RDWR, no O_SYNC: a cached mapping of RAM, as levels 19, 20 and 24 */
#define F_SYNC (0 | 0x101000)               /* O_RDONLY | O_SYNC: uncached reads of RAM, as levels 22 and 26 */
#define K_AV_VA     0xffffffc001000000UL
#define K_AV_WORD   0xffffffc001b61268UL
#define K_AV_AREAS  0xffffffc001b61264UL
#define K_DRAM      0x400000000UL
#define K_SCU       0xF1388000UL
#define K_PBL       0xF3400000UL
#define K_WIN       0xF3800000UL
#define K_WIN_LEN   0x6000UL
#define K_REC       0x13f0000UL             /* hello_v1 records: CPU*0x40, 0x28 bytes used each */
#define K_PKT       0x13f8000UL             /* the page +0x90 is pointed at (unused; checked zero) */
#define K_A_MS      50                      /* first snapshot */
#define K_B_MS      300                     /* last snapshot; the codec runs this long */

/* av-cam's clock-on (F782): one store per row, each read back, then dsb sy. Physical addresses; the page is chosen by the high bits. */
struct k_st { u32 addr, val; };
static const struct k_st k_on1[] = {
    { 0xF3400240, 0x1 }, { 0xF3400240, 0x4 },
    { 0xF3400040, 0x1 }, { 0xF3400040, 0x4 }, { 0xF3400040, 0x10 }, { 0xF3400040, 0x40 }, { 0xF3400040, 0x100 }, { 0xF3400040, 0x400 },
    { 0xF3400040, 0x1000 }, { 0xF3400040, 0x4000 },
    { 0xF1388074, 0x10 }, { 0xF1388074, 0x8 }, { 0xF1388074, 0x4 },
    { 0xF3400834, 0x1 }, { 0xF3400834, 0x4 }, { 0xF3400834, 0x10 }, { 0xF3400834, 0x40 }, { 0xF3400834, 0x400 },
    { 0xF3400A34, 0x10 },
    { 0xF3400838, 0x0CF00000 },
    { 0xF3400830, 0x1 }, { 0xF3400830, 0x4 }, { 0xF3400830, 0x10 }, { 0xF3400830, 0x40 }, { 0xF3400830, 0x400 },
    { 0xF3400834, 0x1 }, { 0xF3400834, 0x4 }, { 0xF3400834, 0x10 }, { 0xF3400834, 0x40 }, { 0xF3400834, 0x400 },
    { 0xF3400A34, 0x10 },
    { 0xF3400830, 0x1 }, { 0xF3400830, 0x4 }, { 0xF3400830, 0x10 }, { 0xF3400830, 0x40 }, { 0xF3400830, 0x400 },
};
/* then eight reads of 0xF3400830, then: */
static const struct k_st k_on2[] = {
    { 0xF3400834, 0x1 }, { 0xF3400834, 0x4 }, { 0xF3400834, 0x10 }, { 0xF3400834, 0x40 }, { 0xF3400834, 0x400 },
    { 0xF3400A30, 0x10 },
    { 0xF3400830, 0x1 }, { 0xF3400830, 0x4 }, { 0xF3400830, 0x10 }, { 0xF3400830, 0x40 }, { 0xF3400830, 0x400 },
};
/* av-cam's clock-off, after its short wait (mcmn_misc_uwait): */
static const struct k_st k_off[] = {
    { 0xF1388078, 0x10 }, { 0xF1388078, 0x8 }, { 0xF1388078, 0x4 },
    { 0xF3400834, 0x1 }, { 0xF3400834, 0x4 }, { 0xF3400834, 0x10 }, { 0xF3400834, 0x40 }, { 0xF3400834, 0x400 },
    { 0xF3400A34, 0x10 },
};
/* the boot writes in the codec window (F753), all but +0x80; values filled in at run time from V4_BUS */
static const volatile u32 k_win_regs[] = { 0x84, 0x88, 0x90, 0x5000 };   /* volatile: kept as a table in the file, for check_built */

static i64 k_scu = -1, k_pbl = -1;          /* read-write mappings of the two control pages */

static void k_x32(u32 v) { u8 b[4] = { (u8)(v >> 24), (u8)(v >> 16), (u8)(v >> 8), (u8)v }; puts_("0x"); puthex(b, 4); }
static void k_x64(u64 v) { u8 b[8]; for (int i = 0; i < 8; i++) b[i] = (u8)(v >> (8 * (7 - i))); puts_("0x"); puthex(b, 8); }
static u32 k_rd(i64 m, u64 off) { return *(volatile const u32 *)(m + (i64)off); }
static int k_eq(const u8 *a, const u8 *b, u32 n) { for (u32 i = 0; i < n; i++) if (a[i] != b[i]) return 0; return 1; }

__attribute__((noinline)) static u64 k_ms(void)            /* the only place that asks for the time */
{
    i64 ts[2] = { 0, 0 };
    sc(NR_clock_gettime, 1 /* CLOCK_MONOTONIC */, (i64)ts, 0, 0, 0, 0);
    return (u64)ts[0] * 1000UL + (u64)ts[1] / 1000000UL;
}

/* One store to a control register, from the tables above only; read back and reported. */
static void k_store(const struct k_st *s)
{
    i64 m = (s->addr & ~0xFFFU) == K_SCU ? k_scu : k_pbl;
    volatile u32 *p = (volatile u32 *)(m + (i64)(s->addr & 0xFFF));
    *p = s->val;
    u32 back = *p;
    __asm__ volatile("dsb sy" : : : "memory");
    puts_("  st "); k_x32(s->addr); puts_(" "); k_x32(s->val); puts_(" rb "); k_x32(back); puts_("\n");
}

static void k_run(const struct k_st *t, u64 n) { for (u64 i = 0; i < n; i++) k_store(&t[i]); }

/* The kernel's own view of physical memory: a read of /dev/mem at an offset. */
__attribute__((noinline)) static int k_kview(int fd, u64 phys, u8 *out, u32 len) { return sc(NR_pread64, fd, (i64)out, (i64)len, (i64)phys, 0, 0) == (i64)len; }

/* `len` bytes at `phys` through an uncached read-only mapping of its page. */
static int k_read(int fds, u64 phys, u8 *out, u32 len)
{
    u64 pg = phys & ~0xFFFUL;
    i64 m = sys_mmap_ro(fds, 0x1000, pg);
    if (m == -1) return 0;
    for (u32 k = 0; k < len; k += 4) {
        u32 w = k_rd(m, phys - pg + k);
        out[k] = (u8)w; out[k + 1] = (u8)(w >> 8); out[k + 2] = (u8)(w >> 16); out[k + 3] = (u8)(w >> 24);
    }
    sys_munmap((void *)m, 0x1000);
    return 1;
}

/* `len` bytes (a multiple of 4) written at `phys` through a cached read-write mapping of its page, cleaned to memory, then read back
 * through the uncached view and the kernel's view. Returns 1 when both show `data`. */
static int k_write(int fdw, int fds, u64 phys, const u8 *data, u32 len)
{
    u64 pg = phys & ~0xFFFUL;
    u8 a[V4_BLK], b[V4_BLK];
    i64 m = sys_mmap_rw(fdw, 0x1000, pg);
    if (m == -1) return 0;
    for (u32 k = 0; k < len; k += 4) {
        volatile u32 *w = (volatile u32 *)(m + (i64)(phys - pg + k));
        *w = (u32)data[k] | (u32)data[k + 1] << 8 | (u32)data[k + 2] << 16 | (u32)data[k + 3] << 24;
    }
    for (u32 k = 0; k < len; k += 64) __asm__ volatile("dc civac, %0" : : "r"(m + (i64)(phys - pg + k)) : "memory");
    __asm__ volatile("dc civac, %0\n\tdsb sy" : : "r"(m + (i64)(phys - pg + len - 1)) : "memory");
    sys_munmap((void *)m, 0x1000);
    return k_read(fds, phys, a, len) && k_kview(fdw, phys, b, len) && k_eq(a, data, len) && k_eq(b, data, len);
}

static void k_rec(const char *tag, const u8 *r)
{
    for (u32 c = 0; c < 3; c++) { puts_("rec "); puts_(tag); puts_(" "); putnum(c); puts_(" "); puthex(r + 0x40 * c, 0x28); puts_("\n"); }
}

static const u8 k_zero[256];

static void level27(void)
{
    static u8 w[8], a[V4_BLK], b[V4_BLK], ra[192], rb[192], rc[192];
    int wrote = 0, ran = 0, have_a = 0;
    u32 scu0 = 0, g0 = 0, r0 = 0, run0 = 0, run1 = 0, word = 0, areas = 0;
    u64 pb = 0, t0 = 0;
    i64 win = -1;
    puts_("== level 27: run " V4_DESIGN " on the VCD codec CPUs\n");
    i64 fdw = sys_open(TEST_ROOT "/dev/mem", F_RDWR, 0);
    i64 fds = sys_open(TEST_ROOT "/dev/mem", F_SYNC, 0);
    if (fdw < 0 || fds < 0) { puts_("!! /dev/mem open failed\n== level 27 verdict: NOT READY: nothing is written\n"); goto close; }

    /* 1. where the program area is, from av-cam's own word; it must be the address seen on the camera (F781) */
    if (!k_read((int)fds, (u64)AVCAM_PHYS + (K_AV_AREAS - K_AV_VA), w, 8)) { puts_("!! av-cam.bin's data page cannot be mapped\n== level 27 verdict: NOT READY: nothing is written\n"); goto close; }
    areas = (u32)w[0] | (u32)w[1] << 8 | (u32)w[2] << 16 | (u32)w[3] << 24; word = (u32)w[4] | (u32)w[5] << 8 | (u32)w[6] << 16 | (u32)w[7] << 24;
    puts_("avcam word "); k_x32(word); puts_(" count "); k_x32(areas); puts_("\n");
    if (word != V4_BUS || areas != 0x100) { puts_("== level 27 verdict: NOT READY: the program area is not where it was on the camera (or no boot since power-on); nothing is written\n"); goto close; }
    pb = K_DRAM + V4_BUS;
    puts_("program area at physical "); k_x64(pb); puts_("\n");

    /* 2. the codec must be off: the control pages, mapped read-write for the run, read first */
    k_scu = sys_mmap_rw((int)fdw, 0x1000, K_SCU);
    k_pbl = sys_mmap_rw((int)fdw, 0x1000, K_PBL);
    if (k_scu == -1 || k_pbl == -1) { puts_("!! a control page cannot be mapped\n== level 27 verdict: NOT READY: nothing is written\n"); goto unmap; }
    scu0 = k_rd(k_scu, 0x70); g0 = k_rd(k_pbl, 0x830); r0 = k_rd(k_pbl, 0xA30);
    puts_("before: scu "); k_x32(scu0); puts_(" gates "); k_x32(g0); puts_(" reset "); k_x32(r0); puts_("\n");
    if ((scu0 & 0x1C) || (g0 & 0x455) || (r0 & 0x10)) { puts_("== level 27 verdict: NOT READY: the codec is not off; nothing is written\n"); goto unmap; }

    /* 3. guards: the three stubs and the SPU code as in the file, the record area and the packet page zero, in both views */
    for (u32 c = 0; c < 3; c++) {
        if (!k_read((int)fds, pb + v4_off[c], a, V4_BLK) || !k_kview((int)fdw, pb + v4_off[c], b, V4_BLK) || !k_eq(a, v4_stock[c], V4_BLK) || !k_eq(b, v4_stock[c], V4_BLK)) {
            puts_("!! stub "); putnum(c); puts_(" is not as in the file\n== level 27 verdict: NOT READY: nothing is written\n"); goto unmap;
        }
    }
    if (!k_read((int)fds, pb + 0x9000, a, 32) || !k_eq(a, v4_spu, 32)) { puts_("!! the SPU code is not as in the file\n== level 27 verdict: NOT READY: nothing is written\n"); goto unmap; }
    if (!k_read((int)fds, pb + K_REC, a, 256) || !k_eq(a, k_zero, 256) || !k_read((int)fds, pb + K_PKT, b, 256) || !k_eq(b, k_zero, 256)) {
        puts_("!! the record area or the packet page is not zero\n== level 27 verdict: NOT READY: nothing is written\n"); goto unmap;
    }
    puts_("guards: three stubs and the SPU code as in the file; record area and packet page zero\n");

    /* 4. the stubs */
    for (u32 c = 0; c < 3; c++) {
        wrote = c + 1;                      /* counted before the write: a stub that fails its read-back is put back too */
        if (!k_write((int)fdw, (int)fds, pb + v4_off[c], v4_new[c], v4_len[c])) { puts_("!! stub "); putnum(c); puts_(" did not read back\n"); goto restore; }
        puts_("stub "); putnum(c); puts_(" written, "); putnum(v4_len[c]); puts_(" bytes, read back in both views\n");
    }

    /* 5. av-cam's clock-on */
    puts_("clock on\n");
    k_run(k_on1, sizeof k_on1 / sizeof k_on1[0]);
    for (int i = 0; i < 8; i++) (void)k_rd(k_pbl, 0x830);
    k_run(k_on2, sizeof k_on2 / sizeof k_on2[0]);

    /* 6. the codec window, mapped only now that the codec is clocked */
    win = sys_mmap_rw((int)fdw, K_WIN_LEN, K_WIN);
    if (win == -1) { puts_("!! the codec window cannot be mapped\n"); goto off; }
    run0 = k_rd(win, 0x80);
    puts_("vcd +0x80 before release "); k_x32(run0); puts_("\n");
    if (!run0) { puts_("!! +0x80 is already 0: the CPUs are not held; not released\n"); sys_munmap((void *)win, K_WIN_LEN); goto off; }
    for (u64 i = 0; i < sizeof k_win_regs / sizeof k_win_regs[0]; i++) {
        u32 r = k_win_regs[i], v = r == 0x90 ? (u32)(V4_BUS + K_PKT) : r == 0x5000 ? 352U : (u32)V4_BUS;
        volatile u32 *p = (volatile u32 *)(win + (i64)r);
        *p = v;
        u32 back = *p;
        __asm__ volatile("dsb sy" : : : "memory");
        puts_("  win +"); k_x32(r); puts_(" "); k_x32(v); puts_(" rb "); k_x32(back); puts_("\n");
    }
    t0 = k_ms();
    *(volatile u32 *)(win + 0x80) = 0;
    __asm__ volatile("dsb sy" : : : "memory");
    puts_("released\n");
    for (;;) {
        u64 t = k_ms() - t0;
        if (!have_a && t >= K_A_MS) { if (!k_read((int)fds, pb + K_REC, ra, 192)) break; have_a = 1; }
        if (t >= K_B_MS) { if (k_read((int)fds, pb + K_REC, rb, 192)) ran = have_a; break; }
    }
    puts_("ran for "); putnum((i64)(k_ms() - t0)); puts_(" ms\n");
    run1 = k_rd(win, 0x80);
    puts_("vcd +0x80 at the end "); k_x32(run1); puts_("\n");
    sys_munmap((void *)win, K_WIN_LEN);

off:
    /* 7. av-cam's clock-off, after a 1 ms wait in place of its mcmn_misc_uwait */
    { u64 t = k_ms(); while (k_ms() - t < 2) { } }
    puts_("clock off\n");
    k_run(k_off, sizeof k_off / sizeof k_off[0]);
    {
        u32 scu1 = k_rd(k_scu, 0x70), g1 = k_rd(k_pbl, 0x830), r1 = k_rd(k_pbl, 0xA30);
        puts_("after: scu "); k_x32(scu1); puts_(" gates "); k_x32(g1); puts_(" reset "); k_x32(r1);
        puts_(scu1 == scu0 && g1 == g0 && r1 == r0 ? " (as before)\n" : " (DIFFERENT FROM BEFORE)\n");
    }
    if (k_read((int)fds, pb + K_REC, rc, 192)) {
        if (ran) { k_rec("a", ra); k_rec("b", rb); }
        k_rec("c", rc);
    }
#ifdef V4_DUMP_OFF
    /* 7b. a design's dump (hello_v5: the codec registers it read), read-only through the uncached view, after the clock-off. It lies
     * in program-area scratch that av-cam re-copies at the next codec power-up (F789), so nothing is put back. Only when a stub was
     * written: before that the range holds Sony's bytes, not ours. */
    _Static_assert((V4_DUMP_OFF & 0xFFF) + V4_DUMP_LEN <= 0x1000 && V4_DUMP_LEN % 64 == 0, "k_read maps one page");
    if (wrote == 3) {
        static u8 dmp[V4_DUMP_LEN];
        if (k_read((int)fds, pb + V4_DUMP_OFF, dmp, V4_DUMP_LEN)) {
            for (u32 k = 0; k < V4_DUMP_LEN; k += 64) { puts_("dump "); k_x32(k); puts_(" "); puthex(dmp + k, 64); puts_("\n"); }
        } else puts_("!! the dump cannot be read\n");
    }
#endif

restore:
    /* 8. every byte back: the stubs written, and the record area */
    {
        int ok = 1;
        for (int c = 0; c < wrote; c++) if (!k_write((int)fdw, (int)fds, pb + v4_off[c], v4_stock[c], v4_len[c])) ok = 0;
        if (wrote && !k_write((int)fdw, (int)fds, pb + K_REC, k_zero, 256)) ok = 0;
        if (wrote) puts_(ok ? "restored: the stubs hold the stock bytes and the record area is zero, in both views\n" : "!! RESTORE INCOMPLETE\n");
        if (!ok) puts_("== level 27 verdict: RESTORE INCOMPLETE: a cold boot puts everything back\n");
        else if (!wrote || wrote < 3) puts_("== level 27 verdict: NOT DONE: a stub did not read back; everything written was put back\n");
        else if (!ran) puts_("== level 27 verdict: NOT DONE: see the lines above; everything written was put back\n");
        else {
            u32 n0a = (u32)ra[0x0c] | (u32)ra[0x0d] << 8 | (u32)ra[0x0e] << 16 | (u32)ra[0x0f] << 24, n0b = (u32)rb[0x0c] | (u32)rb[0x0d] << 8 | (u32)rb[0x0e] << 16 | (u32)rb[0x0f] << 24;
            int spu = rb[0] == 'H' && rb[1] == 'E' && rb[2] == 'L' && rb[3] == 'O' && n0b > n0a;
            int mbp = 1;
            for (u32 c = 1; c < 3; c++) {
                const u8 *x = ra + 0x40 * c, *y = rb + 0x40 * c;
                u32 p = (u32)x[0x0c] | (u32)x[0x0d] << 8 | (u32)x[0x0e] << 16 | (u32)x[0x0f] << 24, q = (u32)y[0x0c] | (u32)y[0x0d] << 8 | (u32)y[0x0e] << 16 | (u32)y[0x0f] << 24;
                if (!(y[0] == 'M' && y[1] == 'B' && y[2] == 'P' && q > p)) mbp = 0;
            }
            puts_(spu && mbp ? "== level 27 verdict: RAN: SPU+MBP0+MBP1\n" : spu ? "== level 27 verdict: RAN: SPU\n" : "== level 27 verdict: NO SIGN OF LIFE\n");
        }
    }
unmap:
    if (k_scu != -1) sys_munmap((void *)k_scu, 0x1000);
    if (k_pbl != -1) sys_munmap((void *)k_pbl, 0x1000);
close:
    if (fdw >= 0) sys_close((int)fdw);
    if (fds >= 0) sys_close((int)fds);
}
#endif

/* ------------------------------------------------------------------ levels 19 and 20: the encoder-side sites, applied or put back */

#if LEVEL == 19 || LEVEL == 20
#if LEVEL == 19
#define MP_FROM(e) ((e)->stock)
#define MP_TO(e) ((e)->changed)
#define MP_VERB "apply"
#else
#define MP_FROM(e) ((e)->changed)
#define MP_TO(e) ((e)->stock)
#define MP_VERB "put back"
#endif
#ifndef MP_MAX                             /* a design whose tables are larger sets it in its header */
#define MP_MAX 96                          /* more entries than a table has: checked when this is compiled */
#endif
typedef char mp_av_fits[(sizeof mp_av / sizeof mp_av[0]) <= MP_MAX ? 1 : -1];
typedef char mp_lm_fits[(sizeof mp_lm / sizeof mp_lm[0]) <= MP_MAX ? 1 : -1];
#define NR_pread64 67
#define NR_pwrite64 68
#define F_RDWR 2                           /* O_RDWR, and no O_SYNC: see level19() */

/* The kernel's own view of physical memory: a read of /dev/mem at an offset goes through the kernel's own map of that memory, which is the
 * address av-cam reads its tables at. The only place in this file that makes this call. */
__attribute__((noinline)) static int mp_kview(int fd, u64 phys, u8 *out, u32 len)
{
    return sc(NR_pread64, fd, (i64)out, (i64)len, (i64)phys, 0, 0) == (i64)len;
}

/* The one write into this process's memory: `len` bytes of a libmpr.so site, through /proc/self/mem. The only place that makes this call. */
__attribute__((noinline)) static int mp_lm_put(int pm, u64 lo, const struct mp_site *e, const u8 *bytes)
{
    return sc(NR_pwrite64, pm, (i64)bytes, (i64)e->len, (i64)(lo + e->off), 0, 0) == (i64)e->len;
}

static int mp_lm_is(u64 lo, const struct mp_site *e, const u8 *bytes)
{
    const volatile u8 *mem = (const volatile u8 *)lo;
    for (u32 k = 0; k < e->len; k++) if (mem[e->off + k] != bytes[k]) return 0;
    return 1;
}

static void mp_av_put(volatile u8 *av, const struct mp_site *e, const u8 *bytes)
{
    for (u32 k = 0; k < e->len; k++) av[e->off - MP_AV_FIRST + k] = bytes[k];
}

/* Both views of an av-cam.bin site hold `bytes`: the mapping, and the kernel's own. */
static int mp_av_is(const volatile u8 *av, int fd, const struct mp_site *e, const u8 *bytes)
{
    u8 kv[16];
    for (u32 k = 0; k < e->len; k++) if (av[e->off - MP_AV_FIRST + k] != bytes[k]) return 0;
    return mp_kview(fd, (u64)AVCAM_PHYS + e->off, kv, e->len) && mp_eq(kv, bytes, e->len);
}

static void mp_where(const char *tag, const struct mp_site *e)
{
    puts_(tag); puts_(e->kind ? " site " : " guard "); mp_putx(e->off);
}

static int mp_refuse(const char *tag, const struct mp_site *e, const char *why)
{
    puts_("!! "); mp_where(tag, e); puts_(": "); puts_(why); puts_("; nothing is written\n");
    return 0;
}

static u8 mp_do_av[MP_MAX], mp_do_lm[MP_MAX];          /* per entry: 0 leave, 1 to write, 2 touched by this run */

/* Pass 1 for one table: nothing is written. Returns 0 after reporting the first thing that is not as it must be. */
static int mp_pass1(const char *tag, const struct mp_site *t, u64 n, u8 *todo, const volatile u8 *mem, u64 first, u64 span, int fd, u32 *n_todo)
{
    for (u64 i = 0; i < n; i++) {
        const struct mp_site *e = &t[i];
        u8 got[16], kv[16];
        todo[i] = 0;
        if (e->len > 16 || e->off < first || e->off + e->len > first + span) return mp_refuse(tag, e, "lies outside the range that may be read");
        for (u32 k = 0; k < e->len; k++) got[k] = mem[e->off - first + k];
        if (fd >= 0) {                                 /* av-cam.bin only: the kernel's own view must be readable and equal to the mapping */
            if (!mp_kview(fd, (u64)AVCAM_PHYS + e->off, kv, e->len)) return mp_refuse(tag, e, "the kernel's own view cannot be read");
            if (!mp_eq(kv, got, e->len)) return mp_refuse(tag, e, "the kernel's own view differs from the mapping");
        }
        if (!e->kind) {
            if (!mp_eq(got, e->stock, e->len)) return mp_refuse(tag, e, "is not as in the file");
            continue;
        }
        if (mp_eq(got, MP_FROM(e), e->len)) { todo[i] = 1; (*n_todo)++; mp_where(tag, e); puts_(": as expected\n"); }
        else if (mp_eq(got, MP_TO(e), e->len)) { mp_where(tag, e); puts_(": already holds the target bytes\n"); }
        else return mp_refuse(tag, e, "holds neither set of bytes");
    }
    return 1;
}

static void mp_run(volatile u8 *av, int fd, int pm, u64 lo, u64 hi)
{
    u64 n_av = sizeof mp_av / sizeof mp_av[0], n_lm = sizeof mp_lm / sizeof mp_lm[0];
    u32 n_todo = 0;
    int failed = 0, undo_bad = 0;
    if (!mp_pass1("av", mp_av, n_av, mp_do_av, av, MP_AV_FIRST, MP_AV_BYTES, fd, &n_todo)) return;
    if (!mp_pass1("lm", mp_lm, n_lm, mp_do_lm, (const volatile u8 *)lo, 0, hi - lo, -1, &n_todo)) return;
    puts_("checks passed: every guard is as in the file, every site holds one of the two sets of bytes, and the kernel's own view of av-cam.bin equals the mapping\n");
    if (!n_todo) { puts_("NOTHING TO DO: every site already holds the target bytes (" MP_VERB ")\n"); return; }

    for (u64 i = 0; i < n_av && !failed; i++) {
        const struct mp_site *e = &mp_av[i];
        if (mp_do_av[i] != 1) continue;
        mp_do_av[i] = 2;                               /* touched: the undo covers it even if the write is seen in one view only */
        mp_av_put(av, e, MP_TO(e));
        if (mp_av_is(av, fd, e, MP_TO(e))) { mp_where("av", e); puts_(": written and read back\n"); }
        else { puts_("!! "); mp_where("av", e); puts_(": the write is not seen both in the mapping and in the kernel's own view\n"); failed = 1; }
    }
#ifdef MP_LM_ORDERED                       /* the lm table is in apply order (code before the branches into it): put back runs in reverse */
    for (u64 k = 0; k < n_lm && !failed; k++) {
        u64 i = LEVEL == 19 ? k : n_lm - 1 - k;
#else
    for (u64 i = 0; i < n_lm && !failed; i++) {
#endif
        const struct mp_site *e = &mp_lm[i];
        if (mp_do_lm[i] != 1) continue;
        mp_do_lm[i] = 2;
        if (!mp_lm_put(pm, lo, e, MP_TO(e))) { puts_("!! "); mp_where("lm", e); puts_(": the write through /proc/self/mem failed\n"); failed = 1; }
        else if (!mp_lm_is(lo, e, MP_TO(e))) { puts_("!! "); mp_where("lm", e); puts_(": the write is not seen in the process's memory\n"); failed = 1; }
        else { mp_where("lm", e); puts_(": written and read back\n"); }
    }
    if (!failed) { puts_("DONE: every site holds the target bytes (" MP_VERB ")\n"); return; }

    /* Something failed: put back every site this run touched, libmpr.so first, and say what each holds afterwards. */
#ifdef MP_LM_ORDERED                       /* an undo runs opposite to the writes: branches out before the code they point at */
    for (u64 k = 0; k < n_lm; k++) {
        u64 i = LEVEL == 19 ? n_lm - 1 - k : k;
#else
    for (u64 i = 0; i < n_lm; i++) {
#endif
        const struct mp_site *e = &mp_lm[i];
        if (mp_do_lm[i] != 2) continue;
        mp_lm_put(pm, lo, e, MP_FROM(e));
        if (mp_lm_is(lo, e, MP_FROM(e))) { puts_("undo "); mp_where("lm", e); puts_(": put back\n"); }
        else { puts_("!! undo "); mp_where("lm", e); puts_(": NOT put back\n"); undo_bad = 1; }
    }
    for (u64 i = 0; i < n_av; i++) {
        const struct mp_site *e = &mp_av[i];
        if (mp_do_av[i] != 2) continue;
        mp_av_put(av, e, MP_FROM(e));
        if (mp_av_is(av, fd, e, MP_FROM(e))) { puts_("undo "); mp_where("av", e); puts_(": put back\n"); }
        else { puts_("!! undo "); mp_where("av", e); puts_(": NOT put back\n"); undo_bad = 1; }
    }
    puts_(undo_bad ? "UNDO INCOMPLETE: main-processor memory may be partly changed; cold boot the camera before anything else\n"
                   : "NOT DONE: a step failed; every site this run touched was put back\n");
}

static void level19(void)
{
    u64 lo = 0, hi = 0; char perms[8];
    puts_("== level " RC_STR(LEVEL) ": " MP_VERB " the main-processor sites of " MP_DESIGN "\n");
    /* Read-write, and without O_SYNC: for memory the kernel has in its own map this gives an ordinary cached mapping, as the kernel's own is,
     * so both see one copy. (With O_SYNC the camera's kernel makes a write-combining mapping and reports a cache-type mismatch.) */
    i64 fd = sys_open(TEST_ROOT "/dev/mem", F_RDWR, 0);
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("; nothing is written\n"); return; }
    i64 m = sys_mmap_rw((int)fd, MP_AV_BYTES, (u64)AVCAM_PHYS + MP_AV_FIRST);
    if (m == -1) { puts_("!! mmap of the av-cam.bin tables failed; nothing is written\n"); sys_close((int)fd); return; }
    if (!mp_find_lib(&lo, &hi, perms)) puts_("!! " MP_LIB " is not in this process's list of mappings; nothing is written\n");
    else if (perms[0] != 'r') puts_("!! the mapping of " MP_LIB " is not readable; nothing is written\n");
    else {
        i64 pm = sys_open(TEST_ROOT "/proc/self/mem", F_RDWR, 0);
        if (pm < 0) { puts_("!! /proc/self/mem open failed "); putnum(pm); puts_("; nothing is written\n"); }
        else {
            puts_("av-cam.bin at physical "); mp_putx((u64)AVCAM_PHYS); puts_(", "); putnum((i64)(sizeof mp_av / sizeof mp_av[0]));
            puts_(" entries; " MP_LIB " mapped at "); mp_putx(lo); puts_("-"); mp_putx(hi); puts_(" "); puts_(perms); puts_(", ");
            putnum((i64)(sizeof mp_lm / sizeof mp_lm[0])); puts_(" entries\n");
            mp_run((volatile u8 *)m, (int)fd, (int)pm, lo, hi);
            sys_close((int)pm);
        }
    }
    sys_munmap((void *)m, MP_AV_BYTES);
    sys_close((int)fd);
}
#endif

/* ------------------------------------------------------------------ levels 29 and 30: code and data sites of av-cam.bin, applied or put back */

/* av-cam.bin runs in the kernel at AD_KVA + file offset (liro.ko loads it at AVCAM_PHYS). Its data is written as level 19 writes it; its code is
 * a new kind of write here, kernel text: a processor may have the old instruction in its instruction cache or its pipeline, and a virtually
 * indexed instruction cache files a line under the address it was fetched at. So:
 *   - the code page is mapped at a user address with the kernel address's offset from an AD_ALIGN boundary (2 MB), so that an invalidation
 *     through this mapping reaches the index the kernel's fetches use; an instruction cache that CTR_EL0 calls neither PIPT nor VIPT is refused;
 *   - each site is one aligned 32-bit store: no processor can see half an instruction;
 *   - after the code writes, each site's line is cleaned to the point of unification and the instruction cache invalidated at it, both
 *     broadcast to every processor (inner shareable), then dsb ish and isb (ad_sync);
 *   - the whole maintenance sequence runs once before anything is written: if this processor did not allow it from this process, the
 *     process would end there, with nothing changed;
 *   - order: apply writes the code sites first and the data sites last; put back the data first and the code last (the design's rule: no state
 *     between the two halves may be worse than stock). An undo runs as a put back does.
 * Every byte of the code page apart from the sites must be as in the file, in the mapping and in the kernel's own view; the data entries are
 * checked as level 19 checks its tables. The change does not survive a cold boot. */
#if LEVEL == 29 || LEVEL == 30
#ifndef AD_H
#error "levels 29 and 30 need -DAD_H with the header that helper_fx3/gen_fx3_write.py writes for an av-cam.bin code design"
#endif
#ifndef AVCAM_PHYS
#error "levels 29 and 30 need -DAVCAM_PHYS=<physical load address of av-cam.bin>"
#endif
#include AD_H                              /* AD_DESIGN, AD_KVA, AD_CODE_PAGE, AD_DATA_PAGE, AD_ALIGN, struct ad_site, ad_code[], ad_data[], ad_code_file[] */
#if LEVEL == 29
#define AD_FROM(e) ((e)->stock)
#define AD_TO(e) ((e)->changed)
#define AD_VERB "apply"
#else
#define AD_FROM(e) ((e)->changed)
#define AD_TO(e) ((e)->stock)
#define AD_VERB "put back"
#endif
#define NR_pread64 67
#define F_RDWR 2                           /* O_RDWR, and no O_SYNC: a cached mapping, as the kernel's own map is (see level19()) */
#define AD_PAGE 0x1000UL
#define AD_NC (sizeof ad_code / sizeof ad_code[0])
#define AD_ND (sizeof ad_data / sizeof ad_data[0])
_Static_assert(AD_NC >= 1 && AD_NC <= 16 && AD_ND >= 1 && AD_ND <= 16, "small tables");
_Static_assert(AD_CODE_PAGE % AD_PAGE == 0 && AD_DATA_PAGE % AD_PAGE == 0 && AD_CODE_PAGE != AD_DATA_PAGE, "two whole pages");
_Static_assert(AD_ALIGN >= AD_PAGE && (AD_ALIGN & (AD_ALIGN - 1)) == 0 && AD_KVA % AD_ALIGN == 0, "the alias rule");

static void ad_putx(u64 v)
{
    u8 be[8]; int k = 0;
    for (int i = 0; i < 8; i++) be[i] = (u8)(v >> (8 * (7 - i)));
    while (k < 7 && !be[k]) k++;
    puts_("0x"); puthex(be + k, (u64)(8 - k));
}

static int ad_eq(const u8 *a, const volatile u8 *b, u32 n)
{
    for (u32 i = 0; i < n; i++) if (a[i] != b[i]) return 0;
    return 1;
}

/* The kernel's own view of physical memory, as level 19's mp_kview. The only place in this level that makes this call. */
__attribute__((noinline)) static int ad_kview(int fd, u64 phys, u8 *out, u32 len)
{
    return sc(NR_pread64, fd, (i64)out, (i64)len, (i64)phys, 0, 0) == (i64)len;
}

/* The cache type register as this process reads it (Linux sets SCTLR_EL1.UCT, or answers the read itself). */
__attribute__((noinline)) static u64 ad_ctr(void)
{
    u64 v;
    __asm__ volatile("mrs %0, ctr_el0" : "=r"(v));
    return v;
}

/* The code page, mapped read-write over part of a reservation at `va`. With level 19's sys_mmap_rw, the only writable mapping calls of this level. */
__attribute__((noinline)) static i64 ad_map_code(int fd, u64 va)
{
    i64 r = sc(NR_mmap, (i64)va, (i64)AD_PAGE, 3 /* PROT_READ | PROT_WRITE */, 0x11 /* MAP_SHARED | MAP_FIXED */, fd, (i64)((u64)AVCAM_PHYS + AD_CODE_PAGE));
    return (r < 0 && r > -4096) ? -1 : r;
}

/* The only place that makes the processors fetch the code sites afresh. `code` is the code page in this process. */
__attribute__((noinline)) static void ad_sync(volatile u8 *code)
{
    for (u64 i = 0; i < AD_NC; i++) __asm__ volatile("dc cvau, %0" : : "r"(code + (ad_code[i].off - AD_CODE_PAGE)) : "memory");
    __asm__ volatile("dsb ish" : : : "memory");
    for (u64 i = 0; i < AD_NC; i++) __asm__ volatile("ic ivau, %0" : : "r"(code + (ad_code[i].off - AD_CODE_PAGE)) : "memory");
    __asm__ volatile("dsb ish" : : : "memory");
    __asm__ volatile("isb" : : : "memory");
}

static u8 ad_kpage[AD_PAGE];
static u8 ad_do_c[16], ad_do_d[16];        /* per entry: 0 leave, 1 to write, 2 touched by this run */

static int ad_refuse(const char *tag, u64 off, const char *why)
{
    puts_("!! "); puts_(tag); puts_(" "); ad_putx(off); puts_(": "); puts_(why); puts_("; nothing is written\n");
    return 0;
}

/* A site: one aligned instruction or data word in the page. */
static int ad_site_ok(const struct ad_site *e, u64 page)
{
    return e->kind && e->len == 4 && !(e->off & 3) && e->off >= page && e->off + 4 <= page + AD_PAGE;
}

/* Pass 1 for one table: nothing is written. Code: the whole page in both views, every byte outside the sites as in the file. Data: each entry
 * in both views (the rest of a data page may change while it is read). Returns 0 after reporting the first thing that is not as it must be. */
static int ad_pass1(const char *tag, const struct ad_site *t, u64 n, u8 *todo, const volatile u8 *mem, u64 page, int fd, u32 *n_todo)
{
    if (page == AD_CODE_PAGE) {
        if (!ad_kview(fd, (u64)AVCAM_PHYS + page, ad_kpage, AD_PAGE)) return ad_refuse(tag, page, "the kernel's own view of the page cannot be read");
        for (u64 k = 0; k < AD_PAGE; k++) {
            int in_site = 0;
            if (mem[k] != ad_kpage[k]) return ad_refuse(tag, page + k, "the kernel's own view differs from the mapping");
            for (u64 i = 0; i < n; i++) if (page + k >= t[i].off && page + k < t[i].off + t[i].len) in_site = 1;
            if (!in_site && ad_kpage[k] != ad_code_file[k]) return ad_refuse(tag, page + k, "is not as in the file");
        }
    }
    for (u64 i = 0; i < n; i++) {
        const struct ad_site *e = &t[i];
        u8 kv[16];
        todo[i] = 0;
        if (e->len > 16 || e->off < page || e->off + e->len > page + AD_PAGE) return ad_refuse(tag, e->off, "lies outside its page");
        if (e->kind && !ad_site_ok(e, page)) return ad_refuse(tag, e->off, "is not one aligned word");
        if (page == AD_CODE_PAGE && !e->kind) return ad_refuse(tag, e->off, "a guard in the code page (the whole page is the guard)");
        if (!ad_kview(fd, (u64)AVCAM_PHYS + e->off, kv, e->len)) return ad_refuse(tag, e->off, "the kernel's own view cannot be read");
        if (!ad_eq(kv, mem + (e->off - page), e->len)) return ad_refuse(tag, e->off, "the kernel's own view differs from the mapping");
        if (!e->kind) {
            if (!ad_eq(e->stock, mem + (e->off - page), e->len)) return ad_refuse(tag, e->off, "is not as in the file");
            continue;
        }
        if (ad_eq(AD_FROM(e), mem + (e->off - page), 4)) { todo[i] = 1; (*n_todo)++; puts_(tag); puts_(" site "); ad_putx(e->off); puts_(": as expected\n"); }
        else if (ad_eq(AD_TO(e), mem + (e->off - page), 4)) { puts_(tag); puts_(" site "); ad_putx(e->off); puts_(": already holds the target bytes\n"); }
        else return ad_refuse(tag, e->off, "holds neither set of bytes");
    }
    return 1;
}

static u32 ad_w32(const u8 *b) { return (u32)b[0] | (u32)b[1] << 8 | (u32)b[2] << 16 | (u32)b[3] << 24; }

/* Both views hold `bytes`: the mapping, and the kernel's own. */
static int ad_is(const volatile u8 *mem, u64 page, int fd, const struct ad_site *e, const u8 *bytes)
{
    u8 kv[4];
    return ad_eq(bytes, mem + (e->off - page), 4) && ad_kview(fd, (u64)AVCAM_PHYS + e->off, kv, 4) && ad_eq(bytes, kv, 4);
}

/* The writes of one table: each marked site, one aligned 32-bit store, read back in both views. Returns 0 at the first that is not seen. */
static int ad_write(const char *tag, const struct ad_site *t, u64 n, u8 *todo, volatile u8 *mem, u64 page, int fd)
{
    for (u64 i = 0; i < n; i++) {
        const struct ad_site *e = &t[i];
        if (todo[i] != 1) continue;
        todo[i] = 2;                                   /* touched: the undo covers it even if the write is seen in one view only */
        *(volatile u32 *)(mem + (e->off - page)) = ad_w32(AD_TO(e));
        if (!ad_is(mem, page, fd, e, AD_TO(e))) {
            puts_("!! "); puts_(tag); puts_(" site "); ad_putx(e->off); puts_(": the write is not seen both in the mapping and in the kernel's own view\n");
            return 0;
        }
        puts_(tag); puts_(" site "); ad_putx(e->off); puts_(": written and read back\n");
    }
    return 1;
}

static int ad_undo(const char *tag, const struct ad_site *t, u64 n, const u8 *todo, volatile u8 *mem, u64 page, int fd)
{
    int ok = 1;
    for (u64 i = 0; i < n; i++) {
        const struct ad_site *e = &t[i];
        if (todo[i] != 2) continue;
        *(volatile u32 *)(mem + (e->off - page)) = ad_w32(AD_FROM(e));
        if (ad_is(mem, page, fd, e, AD_FROM(e))) { puts_("undo "); puts_(tag); puts_(" site "); ad_putx(e->off); puts_(": put back\n"); }
        else { puts_("!! undo "); puts_(tag); puts_(" site "); ad_putx(e->off); puts_(": NOT put back\n"); ok = 0; }
    }
    return ok;
}

static void ad_run(volatile u8 *code, volatile u8 *data, int fd)
{
    u32 n_todo = 0;
    int ok;
    if (!ad_pass1("code", ad_code, AD_NC, ad_do_c, code, AD_CODE_PAGE, fd, &n_todo)) return;
    if (!ad_pass1("data", ad_data, AD_ND, ad_do_d, data, AD_DATA_PAGE, fd, &n_todo)) return;
    puts_("checks passed: the code page is as in the file apart from the sites, every guard is as in the file, every site holds one of the two sets of bytes, "
          "and the kernel's own view equals the mappings\n");
    ad_sync(code);                                     /* the probe: on the sites as they are, before anything is written */
    puts_("cache maintenance at the code sites: allowed (run once before any write)\n");
    if (!n_todo) { puts_("NOTHING TO DO: every site already holds the target bytes (" AD_VERB ")\n"); return; }
#if LEVEL == 29
    ok = ad_write("code", ad_code, AD_NC, ad_do_c, code, AD_CODE_PAGE, fd);
    ad_sync(code);
    if (ok) {
        puts_("instruction caches: the code sites cleaned and invalidated on every processor\n");
        ok = ad_write("data", ad_data, AD_ND, ad_do_d, data, AD_DATA_PAGE, fd);
    }
#else
    ok = ad_write("data", ad_data, AD_ND, ad_do_d, data, AD_DATA_PAGE, fd);
    if (ok) {
        ok = ad_write("code", ad_code, AD_NC, ad_do_c, code, AD_CODE_PAGE, fd);
        ad_sync(code);
        if (ok) puts_("instruction caches: the code sites cleaned and invalidated on every processor\n");
    }
#endif
    if (ok) { puts_("DONE: every site holds the target bytes (" AD_VERB ")\n"); return; }

    /* Something failed: put back every site this run touched, as a put back runs (data first, then code, then the caches). */
    ok = ad_undo("data", ad_data, AD_ND, ad_do_d, data, AD_DATA_PAGE, fd);
    ok = ad_undo("code", ad_code, AD_NC, ad_do_c, code, AD_CODE_PAGE, fd) && ok;
    ad_sync(code);
    puts_(!ok ? "UNDO INCOMPLETE: main-processor memory may be partly changed; cold boot the camera before anything else\n"
              : "NOT DONE: a step failed; every site this run touched was put back\n");
}

static void level29(void)
{
    puts_("== level " RC_STR(LEVEL) ": " AD_VERB " the av-cam.bin code and data sites of " AD_DESIGN "\n");
    copy_file(TEST_ROOT "/proc/cpuinfo", 8192);        /* for the record: which processors */
    u64 ctr = ad_ctr();
    u32 l1ip = (u32)(ctr >> 14) & 3;
    puts_("CTR_EL0 "); ad_putx(ctr);
    puts_(l1ip == 3 ? ": instruction cache PIPT\n" : l1ip == 2 ? ": instruction cache VIPT\n" : ": instruction cache neither PIPT nor VIPT\n");
    if (l1ip < 2) { puts_("!! the instruction cache of this kind is not reached through another mapping; nothing is written\n"); return; }
    i64 fd = sys_open(TEST_ROOT "/dev/mem", F_RDWR, 0);
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("; nothing is written\n"); return; }
    /* Address space for the code page: a reservation one page larger than AD_ALIGN, of which one page is then mapped over. */
    i64 res = sc(NR_mmap, 0, (i64)(AD_ALIGN + AD_PAGE), 0 /* PROT_NONE */, 0x22 /* MAP_PRIVATE | MAP_ANONYMOUS */, -1, 0);
    if (res < 0 && res > -4096) { puts_("!! no address space for the code page; nothing is written\n"); sys_close((int)fd); return; }
    u64 want = (AD_KVA + AD_CODE_PAGE) & (AD_ALIGN - 1);
    u64 va = (u64)res + ((want - (u64)res) & (AD_ALIGN - 1));
    i64 c = ad_map_code((int)fd, va), d = -1;
    if (c == -1 || (u64)c != va) puts_("!! the code page cannot be mapped at the address chosen; nothing is written\n");
    else if (((u64)c ^ (AD_KVA + AD_CODE_PAGE)) & (AD_ALIGN - 1)) puts_("!! the code page's address does not keep the kernel's offset; nothing is written\n");
    else if ((d = sys_mmap_rw((int)fd, AD_PAGE, (u64)AVCAM_PHYS + AD_DATA_PAGE)) == -1) puts_("!! the data page cannot be mapped; nothing is written\n");
    else {
        puts_("av-cam.bin at physical "); ad_putx((u64)AVCAM_PHYS); puts_("; code page "); ad_putx(AD_CODE_PAGE); puts_(" (kernel "); ad_putx(AD_KVA + AD_CODE_PAGE);
        puts_(") mapped at "); ad_putx((u64)c); puts_(", data page "); ad_putx(AD_DATA_PAGE); puts_(" at "); ad_putx((u64)d); puts_("\n");
        ad_run((volatile u8 *)c, (volatile u8 *)d, (int)fd);
    }
    if (d != -1) sys_munmap((void *)d, AD_PAGE);
    sys_munmap((void *)res, AD_ALIGN + AD_PAGE);           /* the code page's mapping goes with the reservation */
    sys_close((int)fd);
}
#endif

/* ------------------------------------------------------------------ levels 23 to 25: sites in copies of the codec firmware, main processor */

#if LEVEL >= 23 && LEVEL <= 25
#ifndef VCD_H
#error "levels 23 to 25 need -DVCD_H with the header that `gen_expected.py --vcd <design>` writes"
#endif
#include VCD_H                             /* VCD_DESIGN, VCD_SCAN_PHYS, VCD_SCAN_LEN, VCD_FILE_LEN, VCD_MAX_COPIES, struct vcd_ent, vcd_ents[] */
/* av-cam keeps a pristine copy (the shadow) of vcd_firmware_imola2.bin for the whole session and copies it over the codec's program area each
 * time it powers the codec up (reference/vcd_boot_protocol.md). The copies are found by the file's first 64 bytes inside the scan range, read
 * through read-only mappings 4 MB at a time. A site is one aligned 4-byte word. Level 23 only reads. Levels 24 and 25 check everything first,
 * then write each site with one aligned store through a cached mapping of its page (as levels 19 and 20 do), clean that cache line to memory
 * (dc civac, dsb sy: whoever reads the copy next, through any mapping, sees the new word), and read it back both in the mapping and in the
 * kernel's own view. A failure after the first write puts back every site this run touched. */
#define VCD_WIN 0x400000UL
#define VCD_NENT (sizeof vcd_ents / sizeof vcd_ents[0])
typedef char vcd_scan_whole[(VCD_SCAN_PHYS % VCD_WIN) == 0 && (VCD_SCAN_LEN % VCD_WIN) == 0 && VCD_FILE_LEN < VCD_SCAN_LEN ? 1 : -1];
#if LEVEL == 24
#define VC_FROM(e) ((e)->stock)
#define VC_TO(e) ((e)->changed)
#define VC_VERB "apply"
#elif LEVEL == 25
#define VC_FROM(e) ((e)->changed)
#define VC_TO(e) ((e)->stock)
#define VC_VERB "put back"
#endif
#if LEVEL >= 24
#define NR_pread64 67
#define F_RDWR 2                           /* O_RDWR, and no O_SYNC: a cached mapping, as the kernel's own map is (see level19()) */
#endif

static u64 vc_base[VCD_MAX_COPIES];
static u32 vc_n, vc_over;                  /* copies found inside the range (only the first VCD_MAX_COPIES are kept); copies that run past its end */

static void vc_x64(u64 v) { u8 b[8]; int k = 0; for (int i = 0; i < 8; i++) b[i] = (u8)(v >> (8 * (7 - i))); while (k < 7 && !b[k]) k++; puts_("0x"); puthex(b + k, (u64)(8 - k)); }

static int vc_eq(const u8 *a, const u8 *b, u32 n) { for (u32 i = 0; i < n; i++) if (a[i] != b[i]) return 0; return 1; }

/* Find the copies. Returns 0 if a part of the range could not be mapped (then nothing may be written). */
static int vc_find(int fd)
{
    u64 h[8];
    if (vcd_ents[0].off != 0 || vcd_ents[0].len != 64 || vcd_ents[0].kind != 0) { puts_("!! the first entry is not the file's first 64 bytes\n"); return 0; }
    for (u32 j = 0; j < 8; j++) {
        u64 w = 0;
        for (u32 b = 0; b < 8; b++) w |= (u64)vcd_ents[0].stock[8 * j + b] << (8 * b);
        h[j] = w;
    }
    puts_("scan "); vc_x64(VCD_SCAN_PHYS); puts_(" + "); vc_x64(VCD_SCAN_LEN); puts_(" for the file's first 64 bytes, every 64 bytes\n");
    for (u64 w = 0; w < VCD_SCAN_LEN; w += VCD_WIN) {
        i64 m = sys_mmap_ro(fd, VCD_WIN, VCD_SCAN_PHYS + w);
        if (m == -1) { puts_("!! mmap of the scan range at "); vc_x64(VCD_SCAN_PHYS + w); puts_(" failed\n"); return 0; }
        const volatile u64 *p = (const volatile u64 *)m;
        for (u64 k = 0; k < VCD_WIN / 8; k += 8) {
            if (p[k] != h[0]) continue;
            u32 j = 1;
            while (j < 8 && p[k + j] == h[j]) j++;
            if (j < 8) continue;
            u64 base = VCD_SCAN_PHYS + w + 8 * k;
            puts_("copy found at physical "); vc_x64(base);
            if (base + VCD_FILE_LEN > VCD_SCAN_PHYS + VCD_SCAN_LEN) { puts_(": runs past the end of the range, not used\n"); vc_over++; continue; }
            puts_("\n");
            if (vc_n < VCD_MAX_COPIES) vc_base[vc_n] = base;
            vc_n++;
        }
        sys_munmap((void *)m, VCD_WIN);
    }
    puts_("copies: "); putnum(vc_n); puts_("\n");
    return 1;
}

/* Bytes at a physical address through a read-only mapping of its page (no entry crosses a page). */
static int vc_read(int fd, u64 phys, u8 *out, u32 len)
{
    u64 pg = phys & ~0xFFFUL;
    i64 m = sys_mmap_ro(fd, 0x1000, pg);
    if (m == -1) return 0;
    const volatile u8 *p = (const volatile u8 *)(m + (i64)(phys - pg));
    for (u32 k = 0; k < len; k++) out[k] = p[k];
    sys_munmap((void *)m, 0x1000);
    return 1;
}

static void vc_where(u32 c, const struct vcd_ent *e)
{
    puts_("copy "); putnum(c); puts_(e->kind ? " site " : " guard "); vc_x64(e->off);
}

#if LEVEL == 23
static void level23(void)
{
    u32 g_ok = 0, g_bad = 0, s_stock = 0, s_target = 0, s_other = 0, unread = 0;
    puts_("== level 23: the codec firmware sites of " VCD_DESIGN ", read-only\n");
    i64 fd = sys_open(TEST_ROOT "/dev/mem", F_RDONLY, 0);                  /* read-only: this descriptor cannot be mapped for writing */
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("\n== level 23 verdict: NOTHING READ\n"); return; }
    int scanned = vc_find((int)fd);
    u32 n = vc_n < VCD_MAX_COPIES ? vc_n : VCD_MAX_COPIES;
    for (u32 c = 0; c < n; c++) {
        puts_("copy "); putnum(c); puts_(" at physical "); vc_x64(vc_base[c]); puts_("\n");
        for (u64 i = 0; i < VCD_NENT; i++) {
            const struct vcd_ent *e = &vcd_ents[i];
            u8 got[64];
            puts_("  "); vc_where(c, e); puts_(" "); putnum(e->len);
            if (!vc_read((int)fd, vc_base[c] + e->off, got, e->len)) { puts_(" !! mmap failed\n"); unread++; continue; }
            if (!e->kind) { if (vc_eq(got, e->stock, e->len)) { g_ok++; puts_(" SAME\n"); } else { g_bad++; puts_(" DIFFERS "); puthex(got, e->len); puts_("\n"); } continue; }
            if (vc_eq(got, e->stock, 4)) { s_stock++; puts_(" STOCK "); }
            else if (vc_eq(got, e->changed, 4)) { s_target++; puts_(" TARGET "); }
            else { s_other++; puts_(" OTHER "); }
            puthex(got, 4); puts_("\n");
        }
    }
    sys_close((int)fd);
    puts_("guards: "); putnum(g_ok); puts_(" as in the file, "); putnum(g_bad); puts_(" not; sites: "); putnum(s_stock); puts_(" stock, ");
    putnum(s_target); puts_(" target, "); putnum(s_other); puts_(" other\n");
    int clean = scanned && !unread && !g_bad && !s_other && vc_n <= VCD_MAX_COPIES;
    if (!scanned) puts_("== level 23 verdict: NOT READY: the scan did not complete\n");
    else if (!vc_n) puts_("== level 23 verdict: NOT FOUND: no copy of the file in the range\n");
    else if (clean && !s_target) puts_("== level 23 verdict: READY: every copy's guards are as in the file and every site holds the stock bytes\n");
    else if (clean && !s_stock) puts_("== level 23 verdict: APPLIED: every copy's guards are as in the file and every site holds the design's bytes\n");
    else puts_("== level 23 verdict: NOT READY: see the lines above\n");
}
#endif

#if LEVEL == 24 || LEVEL == 25
/* The kernel's own view of physical memory (a read of /dev/mem at an offset). The only place in this file that makes this call. */
__attribute__((noinline)) static int vc_kview(int fd, u64 phys, u8 *out, u32 len)
{
    return sc(NR_pread64, fd, (i64)out, (i64)len, (i64)phys, 0, 0) == (i64)len;
}

/* One site written: one aligned 32-bit store through a read-write mapping of its page, the line cleaned to memory, then read back in the
 * mapping and in the kernel's own view. Returns 1 when both show `to`. */
static int vc_put(int fd, u64 phys, const u8 *to)
{
    u64 pg = phys & ~0xFFFUL;
    u8 kv[4];
    i64 m = sys_mmap_rw(fd, 0x1000, pg);
    if (m == -1) return 0;
    volatile u32 *w = (volatile u32 *)(m + (i64)(phys - pg));
    *w = (u32)to[0] | (u32)to[1] << 8 | (u32)to[2] << 16 | (u32)to[3] << 24;
    __asm__ volatile("dc civac, %0\n\tdsb sy" : : "r"(w) : "memory");
    u32 back = *w;
    sys_munmap((void *)m, 0x1000);
    u8 b[4] = { (u8)back, (u8)(back >> 8), (u8)(back >> 16), (u8)(back >> 24) };
    return vc_eq(b, to, 4) && vc_kview(fd, phys, kv, 4) && vc_eq(kv, to, 4);
}

static u8 vc_do[VCD_MAX_COPIES][VCD_NENT];      /* per copy and entry: 0 leave, 1 to write, 2 touched by this run */

static int vc_refuse(u32 c, const struct vcd_ent *e, const char *why)
{
    puts_("!! "); vc_where(c, e); puts_(": "); puts_(why); puts_("; nothing is written\n");
    return 0;
}

static int vc_pass1(int fd, u32 *n_todo)
{
    for (u32 c = 0; c < vc_n; c++) {
        puts_("copy "); putnum(c); puts_(" at physical "); vc_x64(vc_base[c]); puts_("\n");
        for (u64 i = 0; i < VCD_NENT; i++) {
            const struct vcd_ent *e = &vcd_ents[i];
            u8 got[64], kv[64];
            vc_do[c][i] = 0;
            if (!vc_read(fd, vc_base[c] + e->off, got, e->len)) return vc_refuse(c, e, "its page cannot be mapped");
            if (!vc_kview(fd, vc_base[c] + e->off, kv, e->len)) return vc_refuse(c, e, "the kernel's own view cannot be read");
            if (!vc_eq(kv, got, e->len)) return vc_refuse(c, e, "the kernel's own view differs from the mapping");
            if (!e->kind) { if (!vc_eq(got, e->stock, e->len)) return vc_refuse(c, e, "is not as in the file"); continue; }
            if (vc_eq(got, VC_FROM(e), 4)) { vc_do[c][i] = 1; (*n_todo)++; vc_where(c, e); puts_(": as expected\n"); }
            else if (vc_eq(got, VC_TO(e), 4)) { vc_where(c, e); puts_(": already holds the target bytes\n"); }
            else return vc_refuse(c, e, "holds neither set of bytes");
        }
    }
    return 1;
}

static void level24(void)
{
    u32 n_todo = 0;
    int failed = 0, undo_bad = 0;
    puts_("== level " RC_STR(LEVEL) ": " VC_VERB " the codec firmware sites of " VCD_DESIGN "\n");
    i64 fd = sys_open(TEST_ROOT "/dev/mem", F_RDWR, 0);
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("; nothing is written\n"); return; }
    if (!vc_find((int)fd)) { puts_("!! the scan did not complete; nothing is written\n"); sys_close((int)fd); return; }
    if (!vc_n) { puts_("!! no copy of the file in the range; nothing is written\n"); sys_close((int)fd); return; }
    if (vc_n > VCD_MAX_COPIES) { puts_("!! more copies than expected; nothing is written\n"); sys_close((int)fd); return; }
    if (!vc_pass1((int)fd, &n_todo)) { sys_close((int)fd); return; }
    puts_("checks passed: in every copy every guard is as in the file, every site holds one of the two sets of bytes, and the kernel's own view equals the mapping\n");
    if (!n_todo) { puts_("NOTHING TO DO: every site already holds the target bytes (" VC_VERB ")\n"); sys_close((int)fd); return; }
    for (u32 c = 0; c < vc_n && !failed; c++)
        for (u64 i = 0; i < VCD_NENT && !failed; i++) {
            const struct vcd_ent *e = &vcd_ents[i];
            if (vc_do[c][i] != 1) continue;
            vc_do[c][i] = 2;
            if (vc_put((int)fd, vc_base[c] + e->off, VC_TO(e))) { vc_where(c, e); puts_(": written and read back\n"); }
            else { puts_("!! "); vc_where(c, e); puts_(": the write is not seen both in the mapping and in the kernel's own view\n"); failed = 1; }
        }
    if (!failed) { puts_("DONE: every site of every copy holds the target bytes (" VC_VERB ")\n"); sys_close((int)fd); return; }
    for (u32 c = 0; c < vc_n; c++)
        for (u64 i = 0; i < VCD_NENT; i++) {
            const struct vcd_ent *e = &vcd_ents[i];
            if (vc_do[c][i] != 2) continue;
            if (vc_put((int)fd, vc_base[c] + e->off, VC_FROM(e))) { puts_("undo "); vc_where(c, e); puts_(": put back\n"); }
            else { puts_("!! undo "); vc_where(c, e); puts_(": NOT put back\n"); undo_bad = 1; }
        }
    sys_close((int)fd);
    puts_(undo_bad ? "UNDO INCOMPLETE: the codec firmware copy may be partly changed; cold boot the camera before anything else\n"
                   : "NOT DONE: a step failed; every site this run touched was put back\n");
}
#endif
#endif

/* ------------------------------------------------------------------ entry */

static void run(void)
{
    i64 fd = sys_open(RESULT_PATH, F_NEW, 0600);      /* O_EXCL: if a result is already there, do nothing at all */
    if (fd < 0) return;
    out_fd = (int)fd;
    puts_("readcheck 1 level "); putnum(LEVEL); puts_("\neuid "); putnum(sys_geteuid()); puts_("\n");
    level1();
#if LEVEL == 2
    level2();
#endif
#if LEVEL == 3
    level3();
#endif
#if LEVEL == 4
    level4();
#endif
#if LEVEL == 5 || LEVEL == 6
    level5();
#endif
#if LEVEL == 7 || LEVEL == 8
    level7();
#endif
#if LEVEL == 9
    level9();
#endif
#if LEVEL == 10
    level10();
#endif
#if LEVEL == 12
    level12();
#endif
#if LEVEL == 13 || LEVEL == 14
    level13();
#endif
#if LEVEL == 15 || LEVEL == 21 || LEVEL == 28
    level15();
#endif
#if LEVEL == 16 || LEVEL == 17
    level16();
#endif
#if LEVEL == 18
    level18();
#endif
#if LEVEL == 19 || LEVEL == 20
    level19();
#endif
#if LEVEL == 22
    level22();
#endif
#if LEVEL == 23
    level23();
#endif
#if LEVEL == 24 || LEVEL == 25
    level24();
#endif
#if LEVEL == 26
    level26();
#endif
#if LEVEL == 27
    level27();
#endif
#if LEVEL == 29 || LEVEL == 30
    level29();
#endif
    puts_("== done, bytes written before this line: "); putnum((i64)out_total); puts_("\n");
    if (out_fd >= 0) sys_close(out_fd);
    out_fd = -1;
}

#ifdef HOST_TEST
int main(void) { run(); return 0; }
#else
__attribute__((constructor)) static void readcheck_ctor(void) { run(); }
#endif
