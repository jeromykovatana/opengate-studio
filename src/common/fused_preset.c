/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * fused_preset.c: Freestanding AArch64 single-pass fused preset applier / putback.
 *
 * Compiles to volatile RAM helpers libJit_<prefix>_{Q19,Q20,F19,F20}.so:
 *   LEVEL == 19: Apply fused preset  (DMM L13 -> Sensor L5 -> CP Words -> MP av-cam+libmpr -> MP appFw cave-then-hook)
 *   LEVEL == 20: Put back fused preset (MP appFw hook-then-cave -> MP libmpr+av-cam -> CP Words -> Sensor L6 -> DMM L14)
 *
 * Pass 1 performs all identity checks, pointer-chain discovery, guard checks,
 * warm power-switch safety checks, and read-backs with ZERO writes.
 * Pass 2 writes only sites needing change, verifying every write immediately.
 * Pass 3 re-verifies every active site across all stages.
 * On any failure after the first write, touched sites are rolled back in strict reverse order.
 */

#ifndef LEVEL
#error "fused_preset.c requires -DLEVEL=19 or -DLEVEL=20"
#endif
#if LEVEL != 19 && LEVEL != 20
#error "fused_preset.c supports only LEVEL 19 (apply) or LEVEL 20 (putback)"
#endif
#ifndef FUSED_H
#error "fused_preset.c requires -DFUSED_H=<expected_fused_*.h>"
#endif
#ifndef TEST_ROOT
#define TEST_ROOT ""
#endif

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long u64;
typedef long i64;

struct fused_id_file {
    const char *name;
    u8 sha256[32];
};

struct fused_id_page {
    u32 address;
    u8 sha256[32];
};

struct cp_site {
    u64 address;
    u32 length;
    const u8 *stock;
    const u8 *changed;
    const u16 *offs;
    u32 noffs;
};

struct ram_word {
    u32 address;
    u8 stock[4];
    u8 changed[4];
};

struct ram_guard {
    u32 address;
    u32 len;
    u8 bytes[16];
};

struct mp_ent {
    u32 off;
    u32 blob_off;
    u8 len;
    u8 kind; /* 0 = guard, 1 = site */
};

struct dmm_site {
    u32 address;
    u8 stock[4];
    u8 changed[4];
};

struct dmm_rec {
    u32 address;
    u32 site_off;
    u8 file[20];
};

#include FUSED_H

#define RESULT_PATH TEST_ROOT "/tmp_wbshd/readcheck_result.txt"
#define TOTAL_CAP   (512U * 1024U)
#define FILE_CAP    (64U * 1024U)
#define MAPS_CAP    (384U * 1024U)
#define CP_PAGE     4096U
#define RAM_LO      0x400000000UL
#define RAM_HI      0x500000000UL

#ifndef DMM_WORDS_TEXT
#define DMM_WORDS_TEXT "the memory-manager word"
#endif

#if LEVEL == 19
#define FUSED_VERB "apply"
#define S_FROM(s) ((s)->stock)
#define S_TO(s)   ((s)->changed)
#define W_FROM(s) ((s)->stock)
#define W_TO(s)   ((s)->changed)
#define M_FROM(e) (&mp_pool[(e)->blob_off])
#define M_TO(e)   (&mp_pool[(e)->blob_off + (e)->len])
#else
#define FUSED_VERB "put back"
#define S_FROM(s) ((s)->changed)
#define S_TO(s)   ((s)->stock)
#define W_FROM(s) ((s)->changed)
#define W_TO(s)   ((s)->stock)
#define M_FROM(e) (&mp_pool[(e)->blob_off + (e)->len])
#define M_TO(e)   (&mp_pool[(e)->blob_off])
#endif

extern u64 cam_dmm_alloc(u32 size, u32 *handle) __asm__("_Z9dmm_allocjPj");
extern u64 cam_dmm_free(u32 handle) __asm__("_Z8dmm_freej");
extern u32 sen_dma_transfer(u32 dir, u64 src, u64 dst, u32 size);

/* ------------------------------------------------------------------ AArch64 Linux syscalls */

#define NR_openat   56
#define NR_close    57
#define NR_read     63
#define NR_write    64
#define NR_pread64  67
#define NR_pwrite64 68
#define NR_geteuid  175
#define NR_munmap   215
#define NR_mmap     222

#define AT_FDCWD     (-100)
#define F_RDONLY     0
#define F_RDWR       2
#define F_RDWR_SYNC  (2 | 0x101000)
#define F_NEW        (1 | 0x40 | 0x80)

static i64 sc(i64 n, i64 a, i64 b, i64 c, i64 d, i64 e, i64 f)
{
    register i64 x8 __asm__("x8") = n;
    register i64 x0 __asm__("x0") = a;
    register i64 x1 __asm__("x1") = b;
    register i64 x2 __asm__("x2") = c;
    register i64 x3 __asm__("x3") = d;
    register i64 x4 __asm__("x4") = e;
    register i64 x5 __asm__("x5") = f;
    __asm__ volatile("svc #0"
                     : "+r"(x0)
                     : "r"(x8), "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5)
                     : "memory", "cc");
    return x0;
}

static i64 sys_open(const char *p, int flags, int mode) { return sc(NR_openat, AT_FDCWD, (i64)p, flags, mode, 0, 0); }
static i64 sys_read(int fd, void *b, u64 n) { return sc(NR_read, fd, (i64)b, (i64)n, 0, 0, 0); }
static i64 sys_write(int fd, const void *b, u64 n) { return sc(NR_write, fd, (i64)b, (i64)n, 0, 0, 0); }
static i64 sys_close(int fd) { return sc(NR_close, fd, 0, 0, 0, 0, 0); }
static i64 sys_geteuid(void) { return sc(NR_geteuid, 0, 0, 0, 0, 0, 0); }
static i64 sys_mmap_rw(int fd, u64 len, u64 off)
{
    i64 r = sc(NR_mmap, 0, (i64)len, 3 /* PROT_READ | PROT_WRITE */, 1 /* MAP_SHARED */, fd, (i64)off);
    return (r < 0 && r > -4096) ? -1 : r;
}
static i64 sys_munmap(void *p, u64 len) { return sc(NR_munmap, (i64)p, (i64)len, 0, 0, 0, 0); }

/* ------------------------------------------------------------------ output & byte helpers */

static int out_fd = -1;
static u64 out_total;

static u64 slen(const char *s) { u64 n = 0; while (s[n]) n++; return n; }

static int eq_bytes(const u8 *a, const u8 *b, u64 n)
{
    for (u64 i = 0; i < n; i++) if (a[i] != b[i]) return 0;
    return 1;
}

static void put(const void *b, u64 n)
{
    if (out_fd < 0 || out_total >= TOTAL_CAP) return;
    if (n > TOTAL_CAP - out_total) n = TOTAL_CAP - out_total;
    const u8 *p = (const u8 *)b;
    while (n) {
        i64 w = sys_write(out_fd, p, n);
        if (w <= 0) { out_fd = -1; return; }
        p += w;
        n -= (u64)w;
        out_total += (u64)w;
    }
}

static void puts_(const char *s) { put(s, slen(s)); }

static void putnum(i64 v)
{
    char t[24];
    int i = 23;
    int neg = v < 0;
    u64 u = neg ? (u64)(-v) : (u64)v;
    t[i] = 0;
    do { t[--i] = (char)('0' + u % 10); u /= 10; } while (u);
    if (neg) t[--i] = '-';
    puts_(t + i);
}

static void puthex(const u8 *b, u64 n)
{
    static const char d[] = "0123456789abcdef";
    char line[64];
    u64 k = 0;
    for (u64 i = 0; i < n; i++) {
        line[k++] = d[b[i] >> 4];
        line[k++] = d[b[i] & 15];
        if (k == sizeof line) { put(line, k); k = 0; }
    }
    if (k) put(line, k);
}

static void putx32(u32 v)
{
    u8 b[4] = { (u8)(v >> 24), (u8)(v >> 16), (u8)(v >> 8), (u8)v };
    puts_("0x");
    puthex(b, 4);
}

static void putx64(u64 v)
{
    u8 be[8];
    int k = 0;
    for (int i = 0; i < 8; i++) be[i] = (u8)(v >> (8 * (7 - i)));
    while (k < 7 && !be[k]) k++;
    puts_("0x");
    puthex(be + k, (u64)(8 - k));
}

/* ------------------------------------------------------------------ SHA-256 */

struct sha { u32 h[8]; u8 block[64]; u64 len; u32 fill; };

static const u32 K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
};

static u32 ror(u32 x, int n) { return (x >> n) | (x << (32 - n)); }

static void sha_block(struct sha *s, const u8 *p)
{
    u32 w[64], a, b, c, d, e, f, g, h;
    for (int i = 0; i < 16; i++)
        w[i] = (u32)p[4 * i] << 24 | (u32)p[4 * i + 1] << 16 | (u32)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (int i = 16; i < 64; i++)
        w[i] = w[i - 16] + (ror(w[i - 15], 7) ^ ror(w[i - 15], 18) ^ (w[i - 15] >> 3))
             + w[i - 7] + (ror(w[i - 2], 17) ^ ror(w[i - 2], 19) ^ (w[i - 2] >> 10));
    a = s->h[0]; b = s->h[1]; c = s->h[2]; d = s->h[3];
    e = s->h[4]; f = s->h[5]; g = s->h[6]; h = s->h[7];
    for (int i = 0; i < 64; i++) {
        u32 t1 = h + (ror(e, 6) ^ ror(e, 11) ^ ror(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i];
        u32 t2 = (ror(a, 2) ^ ror(a, 13) ^ ror(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        h = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    s->h[0] += a; s->h[1] += b; s->h[2] += c; s->h[3] += d;
    s->h[4] += e; s->h[5] += f; s->h[6] += g; s->h[7] += h;
}

static void sha_init(struct sha *s)
{
    static const u32 iv[8] = {
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
    };
    for (int i = 0; i < 8; i++) s->h[i] = iv[i];
    s->len = 0;
    s->fill = 0;
}

static void sha_add(struct sha *s, const u8 *p, u64 n)
{
    s->len += n;
    while (n) {
        s->block[s->fill++] = *p++;
        n--;
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
    for (int i = 0; i < 8; i++) {
        out[4 * i]     = (u8)(s->h[i] >> 24);
        out[4 * i + 1] = (u8)(s->h[i] >> 16);
        out[4 * i + 2] = (u8)(s->h[i] >> 8);
        out[4 * i + 3] = (u8)s->h[i];
    }
}

/* ------------------------------------------------------------------ /proc inspection */

static u8 iobuf[4096];
static char maps[MAPS_CAP];
static u64 maps_len;
static char cmdline[4096];

static void copy_file(const char *path, u64 cap)
{
    puts_("== file "); puts_(path); puts_("\n");
    i64 fd = sys_open(path, F_RDONLY, 0);
    if (fd < 0) { puts_("!! open failed "); putnum(fd); puts_("\n"); return; }
    u64 got = 0;
    for (;;) {
        u64 want = sizeof iobuf;
        if (want > cap - got) want = cap - got;
        if (!want) { puts_("\n!! truncated at "); putnum((i64)cap); puts_(" bytes\n"); break; }
        i64 r = sys_read((int)fd, iobuf, want);
        if (r < 0) { puts_("\n!! read failed "); putnum(r); puts_("\n"); break; }
        if (r == 0) break;
        put(iobuf, (u64)r);
        got += (u64)r;
    }
    sys_close((int)fd);
    puts_("\n== end "); putnum((i64)got); puts_(" bytes\n");
}

static u64 read_all(const char *path, char *dst, u64 cap)
{
    i64 fd = sys_open(path, F_RDONLY, 0);
    u64 got = 0;
    if (fd < 0) return 0;
    for (;;) {
        i64 r = sys_read((int)fd, dst + got, cap - 1 - got);
        if (r <= 0) break;
        got += (u64)r;
        if (got >= cap - 1) break;
    }
    sys_close((int)fd);
    dst[got] = 0;
    return got;
}

static u64 hexval(const char **p)
{
    u64 v = 0;
    for (;; (*p)++) {
        char c = **p;
        int d;
        if (c >= '0' && c <= '9') d = c - '0';
        else if (c >= 'a' && c <= 'f') d = c - 'a' + 10;
        else break;
        v = v << 4 | (u64)d;
    }
    return v;
}

static int ends_with(const char *s, u64 n, const char *suffix)
{
    u64 m = slen(suffix);
    if (n < m) return 0;
    return eq_bytes((const u8 *)s + n - m, (const u8 *)suffix, m);
}

static int find_lib_map(const char *suffix, u64 *lo_out, u64 *hi_out, char *perms_out, char *path_out, u64 path_cap)
{
    const char *p = maps, *end = maps + maps_len;
    if (path_out && path_cap) path_out[0] = 0;
    while (p < end) {
        const char *line = p, *q = p;
        while (p < end && *p != '\n') p++;
        u64 n = (u64)(p - line);
        if (p < end) p++;
        if (!ends_with(line, n, suffix)) continue;
        u64 lo = hexval(&q); if (*q != '-') continue; q++;
        u64 hi = hexval(&q); if (*q != ' ') continue; q++;
        char perms[5];
        for (int k = 0; k < 4; k++) {
            if (!*q || *q == '\n') { perms[0] = 0; break; }
            perms[k] = *q++;
        }
        perms[4] = 0;
        if (*q != ' ') continue;
        q++;
        u64 foff = hexval(&q);
        if (foff != 0 || hi <= lo) continue;
        if (path_out && path_cap) {
            const char *s = line + n;
            while (s > line && s[-1] != ' ') s--;
            u64 k = 0;
            for (; s < line + n && k + 1 < path_cap; s++) path_out[k++] = *s;
            path_out[k] = 0;
        }
        if (perms_out) for (int k = 0; k < 5; k++) perms_out[k] = perms[k];
        if (lo_out) *lo_out = lo;
        if (hi_out) *hi_out = hi;
        return 1;
    }
    return 0;
}

static int cmdline_has(const char *needle)
{
    u64 m = slen(needle);
    for (u64 i = 0; cmdline[i]; i++)
        if (eq_bytes((const u8 *)cmdline + i, (const u8 *)needle, m)) return 1;
    return 0;
}

/* ------------------------------------------------------------------ coprocessor DMA transport */

static u64 dma_phys;
static u8 *dma_buf;

static u32 le32(const u8 *p)
{
    return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
}

static int bad_pointer(u32 v) { return (v & 3U) || v < CP_LO || v >= CP_HI; }

__attribute__((noinline)) static const u8 *cp_read(u64 addr, u32 len)
{
    u64 base = addr & ~63UL, end = (addr + len + 63UL) & ~63UL;
    if (addr < CP_LO || addr + len > CP_HI || end - base > CP_PAGE) return 0;
    u32 n = (u32)(end - base);
    for (u32 i = 0; i < n; i++) dma_buf[i] = 0xee;
    if (sen_dma_transfer(0, base, dma_phys, n) != 0) return 0;
    return dma_buf + (addr - base);
}

static u64 cp_line_base(const struct cp_site *s) { return s->address & ~63UL; }
static u32 cp_line_len(const struct cp_site *s)
{
    return (u32)(((s->address + s->length + 63UL) & ~63UL) - cp_line_base(s));
}

static int cp_site_read(const struct cp_site *s)
{
    u32 n = cp_line_len(s);
    if (s->address < CP_LO || s->address + s->length > CP_HI || n > CP_PAGE) return 1;
    for (u32 i = 0; i < n; i++) dma_buf[i] = 0xee;
    return sen_dma_transfer(0, cp_line_base(s), dma_phys, n) != 0;
}

static int cp_site_holds(const struct cp_site *s, const u8 *bytes)
{
    const u8 *at = dma_buf + (s->address - cp_line_base(s));
    if (s->offs) {
        for (u32 i = 0; i < s->noffs; i++) if (at[s->offs[i]] != bytes[i]) return 0;
        return 1;
    }
    return eq_bytes(at, bytes, s->length);
}

__attribute__((noinline)) static int cp_site_write(const struct cp_site *s, const u8 *bytes)
{
    if (cp_site_read(s)) return 1;
    u8 *at = dma_buf + (s->address - cp_line_base(s));
    if (s->offs) for (u32 i = 0; i < s->noffs; i++) at[s->offs[i]] = bytes[i];
    else for (u32 i = 0; i < s->length; i++) at[i] = bytes[i];
    return sen_dma_transfer(1, dma_phys, cp_line_base(s), cp_line_len(s)) != 0;
}

__attribute__((noinline)) static int cp_word_write(u32 addr, const u8 *bytes)
{
    u64 base = (u64)addr & ~63UL;
    if (!cp_read(base, 64)) return 1;
    u8 *at = dma_buf + ((u64)addr - base);
    for (u32 i = 0; i < 4; i++) at[i] = bytes[i];
    return sen_dma_transfer(1, dma_phys, base, 64) != 0;
}

static int cp_word_state(u32 addr, const u8 *from, const u8 *to)
{
    const u8 *p = cp_read(addr, 4);
    if (!p) return 3;
    int is_from = eq_bytes(p, from, 4);
    int is_to = eq_bytes(p, to, 4);
    return is_to ? 1 : is_from ? 0 : 2;
}

/* ------------------------------------------------------------------ firmware identity */

static int check_identity(void)
{
    puts_("== identity: mapped files and coprocessor pages\n");
    for (u64 i = 0; i < sizeof fused_id_files / sizeof fused_id_files[0]; i++) {
        char path[256];
        u64 lo = 0, hi = 0;
        char perms[8];
        if (!find_lib_map(fused_id_files[i].name, &lo, &hi, perms, path, sizeof path) || !path[0]) {
            puts_("file "); puts_(fused_id_files[i].name); puts_(" not mapped\n");
            puts_("!! firmware identity mismatch; nothing is written\n");
            return 0;
        }
        i64 fd = sys_open(path, F_RDONLY, 0);
        if (fd < 0) {
            puts_("file "); puts_(path); puts_(" open failed\n");
            puts_("!! firmware identity mismatch; nothing is written\n");
            return 0;
        }
        struct sha s;
        u8 dg[32];
        sha_init(&s);
        for (;;) {
            i64 r = sys_read((int)fd, iobuf, sizeof iobuf);
            if (r <= 0) break;
            sha_add(&s, iobuf, (u64)r);
        }
        sys_close((int)fd);
        sha_end(&s, dg);
        if (!eq_bytes(dg, fused_id_files[i].sha256, 32)) {
            puts_("file "); puts_(fused_id_files[i].name); puts_(" sha256 mismatch\n");
            puts_("!! firmware identity mismatch; nothing is written\n");
            return 0;
        }
    }
    for (u64 i = 0; i < sizeof fused_id_pages / sizeof fused_id_pages[0]; i++) {
        u32 addr = fused_id_pages[i].address;
        if ((addr & 0xfffU) || addr < CP_LO || (u64)addr + CP_PAGE > CP_HI) {
            puts_("!! firmware identity mismatch; nothing is written\n");
            return 0;
        }
        if (sen_dma_transfer(0, (u64)addr, dma_phys, CP_PAGE) != 0) {
            puts_("page "); putx32(addr); puts_(" DMA read failed\n");
            puts_("!! firmware identity mismatch; nothing is written\n");
            return 0;
        }
        struct sha s;
        u8 dg[32];
        sha_init(&s);
        sha_add(&s, dma_buf, CP_PAGE);
        sha_end(&s, dg);
        if (!eq_bytes(dg, fused_id_pages[i].sha256, 32)) {
            puts_("page "); putx32(addr); puts_(" sha256 mismatch\n");
            puts_("!! firmware identity mismatch; nothing is written\n");
            return 0;
        }
    }
    puts_("identity checks passed\n");
    return 1;
}

/* ------------------------------------------------------------------ DMM stage (#ifdef FUSED_HAS_DMM) */

#ifdef FUSED_HAS_DMM
#define WS_UNITS_AT 0x107e0U
#define N_OBJ       0x580U
#define OBJ         0x50U
#define DMM_POOL    (N_OBJ * OBJ)
#define N_DMM_SITES (sizeof dmm_sites / sizeof dmm_sites[0])

static u8 dmm_pool[DMM_POOL];
static u8 dmm_do[N_DMM_SITES];
static int dmm_skip;

static int dmm_precheck(u32 *n_todo)
{
    u32 n_busy = (u32)(sizeof dmm_busy_keys / sizeof dmm_busy_keys[0]);
    u32 n_recs = (u32)(sizeof dmm_recs / sizeof dmm_recs[0]);
    u32 n_parents = (u32)(sizeof dmm_parents / sizeof dmm_parents[0]);
    const u8 *p = cp_read(DMM_GLOBALS + G_WORKSPACE, 4);
    if (!p) { puts_("!! DMM workspace pointer page could not be read; nothing is written\n"); return 0; }
    u32 ws = le32(p);
    if (!(p = cp_read(DMM_GLOBALS + G_UNITS, 4))) {
        puts_("!! DMM units pointer page could not be read; nothing is written\n");
        return 0;
    }
    u32 units = le32(p);
    if (bad_pointer(ws) || units != ws + WS_UNITS_AT || (u64)units + DMM_POOL > CP_HI) {
        puts_("!! DMM workspace pointers are not as expected; nothing is written\n");
        return 0;
    }
    for (u32 done = 0; done < DMM_POOL;) {
        u64 a = (u64)units + done;
        u32 n = DMM_POOL - done, lead = (u32)(a & 63U);
        if (lead + n > CP_PAGE) n = CP_PAGE - lead;
        if (!(p = cp_read(a, n))) {
            puts_("!! DMM unit objects could not be read; nothing is written\n");
            return 0;
        }
        for (u32 i = 0; i < n; i++) dmm_pool[done + i] = p[i];
        done += n;
    }
    int busy_live = 0;
    u32 busy_key_found = 0;
    for (u32 i = 0; i < N_OBJ; i++) {
        const u8 *o = dmm_pool + i * OBJ;
        u32 key = le32(o + 0x24), size = le32(o + 0x14), parent = le32(o + 0x20);
        int listed = 0;
        for (u32 k = 0; k < n_busy; k++) if (key == dmm_busy_keys[k]) listed = 1;
        if (!listed || !(key || size)) continue;
        int live = 1;
        if (parent >= units && parent < units + DMM_POOL && (parent - units) % OBJ == 0)
            live = dmm_pool[(parent - units) + 2] & 1;
        if (live) { busy_live = 1; busy_key_found = key; break; }
    }
    if (busy_live) {
#if LEVEL == 19
        puts_("!! a unit of key "); putx32(busy_key_found);
        puts_(" exists: movie raw write buffer is open; cold boot and apply before movie mode; nothing is written\n");
        return 0;
#else
        dmm_skip = 1;
        puts_("DMM unit key "); putx32(busy_key_found);
        puts_(" is live on putback (movie buffer open); skipping L14 DMM restore\n");
        return 1;
#endif
    }
    for (u32 k = 0; k < n_recs; k++) {
        if (!(p = cp_read(dmm_recs[k].address, 20))) {
            puts_("!! DMM record could not be read; nothing is written\n");
            return 0;
        }
        for (u32 j = 0; j < 20; j++) {
            if ((j < dmm_recs[k].site_off || j >= dmm_recs[k].site_off + 4) && p[j] != dmm_recs[k].file[j]) {
                puts_("!! DMM record at "); putx32(dmm_recs[k].address);
                puts_(" is not as in the file; nothing is written\n");
                return 0;
            }
        }
    }
    for (u32 k = 0; k < n_parents; k++) {
        if (!(p = cp_read(dmm_parents[k].address, 20))) {
            puts_("!! DMM parent record could not be read; nothing is written\n");
            return 0;
        }
        for (u32 j = 0; j < 20; j++) {
            if (p[j] != dmm_parents[k].file[j]) {
                puts_("!! DMM parent record at "); putx32(dmm_parents[k].address);
                puts_(" is not as in the file; nothing is written\n");
                return 0;
            }
        }
        if ((u64)dmm_fit[1] * dmm_fit[0] > le32(p + 12)) {
            puts_("!! DMM parent unit too small; nothing is written\n");
            return 0;
        }
    }
    for (u64 i = 0; i < N_DMM_SITES; i++) {
        const struct dmm_site *s = &dmm_sites[i];
        int st = cp_word_state(s->address, W_FROM(s), W_TO(s));
        dmm_do[i] = 0;
        if (st == 3) { puts_("!! DMM site read failed; nothing is written\n"); return 0; }
        if (st == 0) { dmm_do[i] = 1; (*n_todo)++; }
        else if (st != 1) {
            puts_("!! DMM site "); putx32(s->address);
            puts_(" holds neither stock nor target bytes; nothing is written\n");
            return 0;
        }
    }
    return 1;
}
#endif

/* ------------------------------------------------------------------ Sensor MULTI_REC stage (L5/L6) */

#define N_CP_TABLE (sizeof cp_sites / sizeof cp_sites[0])
#define N_CP_SITES (N_CP_TABLE + N_RECS)

static struct cp_site l5_recs[N_RECS];
static u32 l5_variant;
static u8 l5_do[N_CP_SITES];

static const struct cp_site *cp_site_at(u64 i)
{
    return i < N_CP_TABLE ? &cp_sites[i] : &l5_recs[i - N_CP_TABLE];
}

static int find_records(void)
{
    const u8 *p = cp_read(IMAGER, 4);
    if (!p) return 1;
    u32 ctrl = le32(p);
    if (bad_pointer(ctrl) || !(p = cp_read((u64)ctrl + CTRL_DRVPARAM, 4))) return 1;
    u32 obj = le32(p);
    if (bad_pointer(obj) || !(p = cp_read(obj, 0x18))) return 1;
    u32 count = le32(p + 4), ids = le32(p + 8), base = le32(p + 0x10);
    if (count == 0 || count > 64 || bad_pointer(ids) || bad_pointer(base) || !(p = cp_read(ids, count * 4U)))
        return 1;
    for (u32 r = 0; r < N_RECS; r++) {
        u32 idx = 0xff;
        for (u32 i = 0; i < count; i++) if (le32(p + 4U * i) == rec_modes[r] && idx == 0xff) idx = i;
        if (idx == 0xff) return 1;
        l5_recs[r].address = (u64)base + (u64)idx * REC;
        l5_recs[r].length = REC;
        l5_recs[r].offs = rec_offs;
        l5_recs[r].noffs = REC_BYTES;
        if (l5_recs[r].address + REC > CP_HI) return 1;
    }
    u32 fits = 0, which = 0;
    for (u32 v = 0; v < REC_VARIANTS; v++) {
        int all = 1;
        for (u32 r = 0; r < N_RECS && all; r++) {
            if (cp_site_read(&l5_recs[r])) return 1;
            if (!cp_site_holds(&l5_recs[r], rec_stock[r][v]) && !cp_site_holds(&l5_recs[r], rec_new[r][v]))
                all = 0;
        }
        if (all) { fits++; which = v; }
    }
    if (fits != 1) return 2;
    l5_variant = which;
    for (u32 r = 0; r < N_RECS; r++) {
        l5_recs[r].stock = rec_stock[r][which];
        l5_recs[r].changed = rec_new[r][which];
    }
    return 0;
}

static int l5_precheck(u32 *l5_todo, u32 *total_todo)
{
    int found = find_records();
    if (found == 1) {
        puts_("!! sensor stored record was not found where pointers lead; nothing is written\n");
        return 0;
    }
    if (found == 2) {
        puts_("!! sensor stored records hold neither timing variant; nothing is written\n");
        return 0;
    }
    puts_("sensor records variant "); puts_(rec_variant_name[l5_variant]); puts_("\n");
    for (u64 i = 0; i < N_CP_SITES; i++) {
        const struct cp_site *s = cp_site_at(i);
        l5_do[i] = 0;
        if (cp_site_read(s)) {
            puts_("!! sensor site "); putx64(s->address); puts_(" read failed; nothing is written\n");
            return 0;
        }
        if (cp_site_holds(s, S_FROM(s))) {
            l5_do[i] = 1;
            (*l5_todo)++;
            (*total_todo)++;
        } else if (!cp_site_holds(s, S_TO(s))) {
            puts_("!! sensor site "); putx64(s->address);
            puts_(" holds neither stock nor target bytes; nothing is written\n");
            return 0;
        }
    }
    return 1;
}

/* ------------------------------------------------------------------ CP words stage (L16+S16[+H16]) */

#define N_RAM_WORDS  (sizeof ram_words / sizeof ram_words[0])
#define N_RAM_GUARDS (sizeof ram_guards / sizeof ram_guards[0])

static u8 word_do[N_RAM_WORDS];

static int cp_words_precheck(u32 *total_todo)
{
    for (u64 k = 0; k < N_RAM_GUARDS; k++) {
        const struct ram_guard *g = &ram_guards[k];
        const u8 *p = cp_read(g->address, g->len);
        if (!p) {
            puts_("!! CP word guard "); putx32(g->address); puts_(" read failed; nothing is written\n");
            return 0;
        }
        if (!eq_bytes(p, g->bytes, g->len)) {
            puts_("!! CP word guard "); putx32(g->address); puts_(" mismatch; nothing is written\n");
            return 0;
        }
    }
    for (u64 i = 0; i < N_RAM_WORDS; i++) {
        const struct ram_word *w = &ram_words[i];
        int st = cp_word_state(w->address, W_FROM(w), W_TO(w));
        word_do[i] = 0;
        if (st == 3) {
            puts_("!! CP word "); putx32(w->address); puts_(" read failed; nothing is written\n");
            return 0;
        }
        if (st == 0) {
            word_do[i] = 1;
            (*total_todo)++;
        } else if (st != 1) {
            puts_("!! CP word "); putx32(w->address);
            puts_(" holds neither stock nor target bytes; nothing is written\n");
            return 0;
        }
    }
    return 1;
}

/* ------------------------------------------------------------------ MP av-cam + libmpr + optional appFw stage */

#define N_MP_AV (sizeof mp_av / sizeof mp_av[0])
#define N_MP_LM (sizeof mp_lm / sizeof mp_lm[0])

static u8 mp_av_do[N_MP_AV];
static u8 mp_lm_do[N_MP_LM];

#ifdef FUSED_HAS_APPFW
#define N_APP_LM (sizeof app_lm / sizeof app_lm[0])
static u8 app_lm_do[N_APP_LM];

__attribute__((noinline)) static u64 app_ctr(void)
{
    u64 v;
    __asm__ volatile("mrs %0, ctr_el0" : "=r"(v));
    return v;
}

__attribute__((noinline)) static void app_sync_site(u64 va, u32 len)
{
    u64 a0 = va & ~63UL;
    u64 a1 = (va + len - 1UL) & ~63UL;
    __asm__ volatile("dc cvau, %0" : : "r"(a0) : "memory");
    if (a1 != a0) __asm__ volatile("dc cvau, %0" : : "r"(a1) : "memory");
    __asm__ volatile("dsb ish" : : : "memory");
    __asm__ volatile("ic ivau, %0" : : "r"(a0) : "memory");
    if (a1 != a0) __asm__ volatile("ic ivau, %0" : : "r"(a1) : "memory");
    __asm__ volatile("dsb ish" : : : "memory");
    __asm__ volatile("isb" : : : "memory");
}
#endif

__attribute__((noinline)) static int mp_kview(int fd, u64 phys, u8 *out, u32 len)
{
    return sc(NR_pread64, fd, (i64)out, (i64)len, (i64)phys, 0, 0) == (i64)len;
}

__attribute__((noinline)) static int mp_mem_put(int pm, u64 lo, const struct mp_ent *e, const u8 *bytes)
{
    return sc(NR_pwrite64, pm, (i64)bytes, (i64)e->len, (i64)(lo + e->off), 0, 0) == (i64)e->len;
}

static int mp_mem_is(u64 lo, const struct mp_ent *e, const u8 *bytes)
{
    const volatile u8 *mem = (const volatile u8 *)lo;
    for (u32 k = 0; k < e->len; k++) if (mem[e->off + k] != bytes[k]) return 0;
    return 1;
}

static void mp_av_put(volatile u8 *av, const struct mp_ent *e, const u8 *bytes)
{
    for (u32 k = 0; k < e->len; k++) av[e->off - MP_AV_FIRST + k] = bytes[k];
}

static int mp_av_is(const volatile u8 *av, int fd, const struct mp_ent *e, const u8 *bytes)
{
    u8 kv[16];
    for (u32 k = 0; k < e->len; k++) if (av[e->off - MP_AV_FIRST + k] != bytes[k]) return 0;
    return mp_kview(fd, (u64)AVCAM_PHYS + e->off, kv, e->len) && eq_bytes(kv, bytes, e->len);
}

static int mp_refuse(const char *tag, const struct mp_ent *e, const char *why)
{
    puts_("!! "); puts_(tag); puts_(e->kind ? " site " : " guard "); putx32(e->off);
    puts_(": "); puts_(why); puts_("; nothing is written\n");
    return 0;
}

static int mp_pass1(const char *tag, const struct mp_ent *t, u64 n, u8 *todo,
                    const volatile u8 *mem, u64 first, u64 span, int fd,
                    u32 *n_todo, u32 *n_already)
{
    for (u64 i = 0; i < n; i++) {
        const struct mp_ent *e = &t[i];
        u8 got[16], kv[16];
        todo[i] = 0;
        if (e->len == 0 || e->len > 16 || e->off < first || (u64)e->off + e->len > first + span)
            return mp_refuse(tag, e, "lies outside mapped range");
        for (u32 k = 0; k < e->len; k++) got[k] = mem[e->off - first + k];
        if (fd >= 0) {
            if (!mp_kview(fd, (u64)AVCAM_PHYS + e->off, kv, e->len))
                return mp_refuse(tag, e, "kernel view unreadable");
            if (!eq_bytes(kv, got, e->len))
                return mp_refuse(tag, e, "kernel view differs from mapping");
        }
        if (!e->kind) {
            if (!eq_bytes(got, &mp_pool[e->blob_off], e->len))
                return mp_refuse(tag, e, "guard mismatch");
            continue;
        }
        if (eq_bytes(got, M_FROM(e), e->len)) {
            todo[i] = 1;
            if (n_todo) (*n_todo)++;
        } else if (eq_bytes(got, M_TO(e), e->len)) {
            if (n_already) (*n_already)++;
        } else {
            return mp_refuse(tag, e, "holds neither stock nor target bytes");
        }
    }
    return 1;
}

/* ------------------------------------------------------------------ main fused execution */

static void run(void)
{
    i64 res_fd = sys_open(RESULT_PATH, F_NEW, 0600);
    if (res_fd < 0) return;
    out_fd = (int)res_fd;
    out_total = 0;

    puts_("readcheck 1 level "); putnum(LEVEL);
    puts_("\neuid "); putnum(sys_geteuid()); puts_("\n");

    copy_file(TEST_ROOT "/proc/version", FILE_CAP);
    copy_file(TEST_ROOT "/proc/cmdline", FILE_CAP);
    read_all(TEST_ROOT "/proc/cmdline", cmdline, sizeof cmdline);
    maps_len = read_all(TEST_ROOT "/proc/self/maps", maps, sizeof maps);
    puts_("== maps read "); putnum((i64)maps_len); puts_(" bytes\n");

    if (!cmdline_has(AVCAM_RESERVE)) {
        puts_("!! kernel command line does not reserve memory as " AVCAM_RESERVE "; nothing is written\n");
        goto done_line;
    }

    u64 lm_lo = 0, lm_hi = 0;
    char lm_perms[8];
    if (!find_lib_map("/libmpr.so", &lm_lo, &lm_hi, lm_perms, 0, 0) || lm_perms[0] != 'r') {
        puts_("!! /libmpr.so is not mapped readable in this process; nothing is written\n");
        goto done_line;
    }

#ifdef FUSED_HAS_APPFW
    u64 app_lo = 0, app_hi = 0;
    char app_perms[8];
    if (!find_lib_map("/appFw.so", &app_lo, &app_hi, app_perms, 0, 0) || app_perms[0] != 'r') {
        puts_("!! /appFw.so is not mapped readable in this process; nothing is written\n");
        goto done_line;
    }
#endif

    u32 dma_handle = 0;
    dma_phys = cam_dmm_alloc(CP_PAGE, &dma_handle);
    if (!dma_phys) {
        puts_("!! buffer allocation failed; nothing is written\n");
        goto done_line;
    }
    if ((dma_phys & 0x3fUL) || dma_phys < RAM_LO || dma_phys + CP_PAGE > RAM_HI) {
        puts_("!! buffer address is not 64-byte aligned inside system RAM; nothing is written\n");
        cam_dmm_free(dma_handle);
        goto done_line;
    }

    i64 fd_sync = sys_open(TEST_ROOT "/dev/mem", F_RDWR_SYNC, 0);
    if (fd_sync < 0) {
        puts_("!! /dev/mem (sync) open failed "); putnum(fd_sync); puts_("; nothing is written\n");
        cam_dmm_free(dma_handle);
        goto done_line;
    }
    u64 lead = dma_phys & 0xfffUL;
    u64 dma_maplen = (lead + CP_PAGE + 0xfffUL) & ~0xfffUL;
    i64 dma_m = sys_mmap_rw((int)fd_sync, dma_maplen, dma_phys - lead);
    if (dma_m == -1) {
        puts_("!! mmap of DMA buffer failed; nothing is written\n");
        sys_close((int)fd_sync);
        cam_dmm_free(dma_handle);
        goto done_line;
    }
    dma_buf = (u8 *)dma_m + lead;

    if (!check_identity()) goto out_dma;

    puts_("== level "); putnum(LEVEL); puts_(": " FUSED_VERB " fused preset " FUSED_LABEL "\n");

    i64 fd_mem = sys_open(TEST_ROOT "/dev/mem", F_RDWR, 0);
    if (fd_mem < 0) {
        puts_("!! /dev/mem open failed "); putnum(fd_mem); puts_("; nothing is written\n");
        goto out_dma;
    }
    i64 av_m = sys_mmap_rw((int)fd_mem, MP_AV_BYTES, (u64)AVCAM_PHYS + MP_AV_FIRST);
    if (av_m == -1) {
        puts_("!! mmap of av-cam.bin tables failed; nothing is written\n");
        sys_close((int)fd_mem);
        goto out_dma;
    }
    i64 pm_fd = sys_open(TEST_ROOT "/proc/self/mem", F_RDWR, 0);
    if (pm_fd < 0) {
        puts_("!! /proc/self/mem open failed "); putnum(pm_fd); puts_("; nothing is written\n");
        sys_munmap((void *)av_m, MP_AV_BYTES);
        sys_close((int)fd_mem);
        goto out_dma;
    }
    volatile u8 *av = (volatile u8 *)av_m;

    /* Pass 1: all-stage pre-check (zero writes) */
    u32 total_todo = 0, l5_todo = 0, mp_todo = 0, mp_already = 0;

#ifdef FUSED_HAS_DMM
    dmm_skip = 0;
    if (!dmm_precheck(&total_todo)) goto out_all;
#endif
    if (!l5_precheck(&l5_todo, &total_todo)) goto out_all;
    if (!cp_words_precheck(&total_todo)) goto out_all;
    if (!mp_pass1("av", mp_av, N_MP_AV, mp_av_do, av, MP_AV_FIRST, MP_AV_BYTES, (int)fd_mem, &mp_todo, &mp_already))
        goto out_all;
    if (!mp_pass1("lm", mp_lm, N_MP_LM, mp_lm_do, (const volatile u8 *)lm_lo, 0, lm_hi - lm_lo, -1, &mp_todo, &mp_already))
        goto out_all;
    total_todo += mp_todo;

#ifdef FUSED_HAS_APPFW
    u32 app_todo = 0;
    u64 ctr = app_ctr();
    u32 l1ip = (u32)(ctr >> 14) & 3U;
    if (l1ip < 2U) {
        puts_("!! instruction cache neither PIPT nor VIPT; nothing is written\n");
        goto out_all;
    }
    if (!mp_pass1("app", app_lm, N_APP_LM, app_lm_do, (const volatile u8 *)app_lo, 0, app_hi - app_lo, -1, &app_todo, 0))
        goto out_all;
    total_todo += app_todo;
    if (app_todo > 0) {
        /* Probe cache maintenance on an untouched code address before any write */
        for (u64 i = 0; i < N_APP_LM; i++) {
            if (app_lm_do[i]) { app_sync_site(app_lo + app_lm[i].off, app_lm[i].len); break; }
        }
    }
#endif

#if LEVEL == 19
    if (l5_todo > 0 && mp_already > 0 && mp_todo == 0) {
        puts_("!! warm power-switch mixed state (coprocessor stock, encoder patched); pull battery >= 10s; nothing is written\n");
        goto out_all;
    }
#endif

    puts_("pass 1 passed: todo="); putnum((i64)total_todo);
    puts_(" l5_todo="); putnum((i64)l5_todo);
    puts_(" mp_todo="); putnum((i64)mp_todo);
    puts_(" mp_already="); putnum((i64)mp_already); puts_("\n");

    if (total_todo == 0) {
        puts_("NOTHING TO DO: every site already holds the target bytes (fused " FUSED_LABEL ")\n");
        goto out_all;
    }

    /* Pass 2: ordered writes + immediate read-back */
    int failed = 0;

#if LEVEL == 19
    /* Apply: DMM (L13) -> Sensor (L5) -> CP Words -> MP av-cam+libmpr -> MP appFw cave-then-hook */
#ifdef FUSED_HAS_DMM
    for (u64 i = 0; i < N_DMM_SITES && !failed; i++) {
        if (dmm_do[i] != 1) continue;
        dmm_do[i] = 2;
        const struct dmm_site *s = &dmm_sites[i];
        if (cp_word_write(s->address, W_TO(s)) || cp_word_state(s->address, W_FROM(s), W_TO(s)) != 1) {
            puts_("!! DMM write/verify failed at "); putx32(s->address); puts_("\n");
            failed = 1;
        }
    }
#endif
    for (u64 i = 0; i < N_CP_SITES && !failed; i++) {
        if (l5_do[i] != 1) continue;
        l5_do[i] = 2;
        const struct cp_site *s = cp_site_at(i);
        if (cp_site_write(s, S_TO(s)) || cp_site_read(s) || !cp_site_holds(s, S_TO(s))) {
            puts_("!! sensor write/verify failed at "); putx64(s->address); puts_("\n");
            failed = 1;
        }
    }
    for (u64 i = 0; i < N_RAM_WORDS && !failed; i++) {
        if (word_do[i] != 1) continue;
        word_do[i] = 2;
        const struct ram_word *w = &ram_words[i];
        if (cp_word_write(w->address, W_TO(w)) || cp_word_state(w->address, W_FROM(w), W_TO(w)) != 1) {
            puts_("!! CP word write/verify failed at "); putx32(w->address); puts_("\n");
            failed = 1;
        }
    }
    for (u64 i = 0; i < N_MP_AV && !failed; i++) {
        if (mp_av_do[i] != 1) continue;
        mp_av_do[i] = 2;
        const struct mp_ent *e = &mp_av[i];
        mp_av_put(av, e, M_TO(e));
        if (!mp_av_is(av, (int)fd_mem, e, M_TO(e))) {
            puts_("!! av write/verify failed at "); putx32(e->off); puts_("\n");
            failed = 1;
        }
    }
    for (u64 i = 0; i < N_MP_LM && !failed; i++) {
        if (mp_lm_do[i] != 1) continue;
        mp_lm_do[i] = 2;
        const struct mp_ent *e = &mp_lm[i];
        if (!mp_mem_put((int)pm_fd, lm_lo, e, M_TO(e)) || !mp_mem_is(lm_lo, e, M_TO(e))) {
            puts_("!! lm write/verify failed at "); putx32(e->off); puts_("\n");
            failed = 1;
        }
    }
#ifdef FUSED_HAS_APPFW
    for (u64 i = 0; i < N_APP_LM && !failed; i++) {
        if (app_lm_do[i] != 1) continue;
        app_lm_do[i] = 2;
        const struct mp_ent *e = &app_lm[i];
        if (!mp_mem_put((int)pm_fd, app_lo, e, M_TO(e))) {
            puts_("!! appFw write failed at "); putx32(e->off); puts_("\n");
            failed = 1;
            break;
        }
        app_sync_site(app_lo + e->off, e->len);
        if (!mp_mem_is(app_lo, e, M_TO(e))) {
            puts_("!! appFw verify failed at "); putx32(e->off); puts_("\n");
            failed = 1;
        }
    }
#endif

#else /* LEVEL == 20 */
    /* Putback: MP appFw hook-then-cave -> MP libmpr+av-cam -> CP Words -> Sensor (L6) -> DMM (L14 if !dmm_skip) */
#ifdef FUSED_HAS_APPFW
    for (u64 k = N_APP_LM; k > 0 && !failed; k--) {
        u64 i = k - 1;
        if (app_lm_do[i] != 1) continue;
        app_lm_do[i] = 2;
        const struct mp_ent *e = &app_lm[i];
        if (!mp_mem_put((int)pm_fd, app_lo, e, M_TO(e))) {
            puts_("!! appFw write failed at "); putx32(e->off); puts_("\n");
            failed = 1;
            break;
        }
        app_sync_site(app_lo + e->off, e->len);
        if (!mp_mem_is(app_lo, e, M_TO(e))) {
            puts_("!! appFw verify failed at "); putx32(e->off); puts_("\n");
            failed = 1;
        }
    }
#endif
    for (u64 k = N_MP_LM; k > 0 && !failed; k--) {
        u64 i = k - 1;
        if (mp_lm_do[i] != 1) continue;
        mp_lm_do[i] = 2;
        const struct mp_ent *e = &mp_lm[i];
        if (!mp_mem_put((int)pm_fd, lm_lo, e, M_TO(e)) || !mp_mem_is(lm_lo, e, M_TO(e))) {
            puts_("!! lm write/verify failed at "); putx32(e->off); puts_("\n");
            failed = 1;
        }
    }
    for (u64 k = N_MP_AV; k > 0 && !failed; k--) {
        u64 i = k - 1;
        if (mp_av_do[i] != 1) continue;
        mp_av_do[i] = 2;
        const struct mp_ent *e = &mp_av[i];
        mp_av_put(av, e, M_TO(e));
        if (!mp_av_is(av, (int)fd_mem, e, M_TO(e))) {
            puts_("!! av write/verify failed at "); putx32(e->off); puts_("\n");
            failed = 1;
        }
    }
    for (u64 k = N_RAM_WORDS; k > 0 && !failed; k--) {
        u64 i = k - 1;
        if (word_do[i] != 1) continue;
        word_do[i] = 2;
        const struct ram_word *w = &ram_words[i];
        if (cp_word_write(w->address, W_TO(w)) || cp_word_state(w->address, W_FROM(w), W_TO(w)) != 1) {
            puts_("!! CP word write/verify failed at "); putx32(w->address); puts_("\n");
            failed = 1;
        }
    }
    for (u64 k = N_CP_SITES; k > 0 && !failed; k--) {
        u64 i = k - 1;
        if (l5_do[i] != 1) continue;
        l5_do[i] = 2;
        const struct cp_site *s = cp_site_at(i);
        if (cp_site_write(s, S_TO(s)) || cp_site_read(s) || !cp_site_holds(s, S_TO(s))) {
            puts_("!! sensor write/verify failed at "); putx64(s->address); puts_("\n");
            failed = 1;
        }
    }
#ifdef FUSED_HAS_DMM
    if (!dmm_skip) {
        for (u64 k = N_DMM_SITES; k > 0 && !failed; k--) {
            u64 i = k - 1;
            if (dmm_do[i] != 1) continue;
            dmm_do[i] = 2;
            const struct dmm_site *s = &dmm_sites[i];
            if (cp_word_write(s->address, W_TO(s)) || cp_word_state(s->address, W_FROM(s), W_TO(s)) != 1) {
                puts_("!! DMM write/verify failed at "); putx32(s->address); puts_("\n");
                failed = 1;
            }
        }
    }
#endif
#endif /* LEVEL */

    /* Pass 3: full post-write read-back across every active stage */
    if (!failed) {
#ifdef FUSED_HAS_DMM
        if (!dmm_skip) {
            for (u64 i = 0; i < N_DMM_SITES; i++) {
                const struct dmm_site *s = &dmm_sites[i];
                if (cp_word_state(s->address, W_FROM(s), W_TO(s)) != 1) failed = 1;
            }
        }
#endif
        for (u64 i = 0; i < N_CP_SITES && !failed; i++) {
            const struct cp_site *s = cp_site_at(i);
            if (cp_site_read(s) || !cp_site_holds(s, S_TO(s))) failed = 1;
        }
        for (u64 i = 0; i < N_RAM_WORDS && !failed; i++) {
            const struct ram_word *w = &ram_words[i];
            if (cp_word_state(w->address, W_FROM(w), W_TO(w)) != 1) failed = 1;
        }
        for (u64 i = 0; i < N_MP_AV && !failed; i++) {
            const struct mp_ent *e = &mp_av[i];
            if (e->kind && !mp_av_is(av, (int)fd_mem, e, M_TO(e))) failed = 1;
        }
        for (u64 i = 0; i < N_MP_LM && !failed; i++) {
            const struct mp_ent *e = &mp_lm[i];
            if (e->kind && !mp_mem_is(lm_lo, e, M_TO(e))) failed = 1;
        }
#ifdef FUSED_HAS_APPFW
        for (u64 i = 0; i < N_APP_LM && !failed; i++) {
            const struct mp_ent *e = &app_lm[i];
            if (e->kind && !mp_mem_is(app_lo, e, M_TO(e))) failed = 1;
        }
#endif
        if (!failed) {
            puts_("DONE: every site holds the target bytes (fused " FUSED_LABEL ")\n");
            goto out_all;
        }
        puts_("!! pass 3 verification mismatch; rolling back touched sites\n");
    }

    /* Reverse rollback of every site touched in Pass 2 */
    int undo_bad = 0;

#if LEVEL == 19
#ifdef FUSED_HAS_APPFW
    for (u64 k = N_APP_LM; k > 0; k--) {
        u64 i = k - 1;
        if (app_lm_do[i] != 2) continue;
        const struct mp_ent *e = &app_lm[i];
        int ok = mp_mem_put((int)pm_fd, app_lo, e, M_FROM(e));
        app_sync_site(app_lo + e->off, e->len);
        if (!ok || !mp_mem_is(app_lo, e, M_FROM(e))) undo_bad++;
    }
#endif
    for (u64 k = N_MP_LM; k > 0; k--) {
        u64 i = k - 1;
        if (mp_lm_do[i] != 2) continue;
        const struct mp_ent *e = &mp_lm[i];
        if (!mp_mem_put((int)pm_fd, lm_lo, e, M_FROM(e)) || !mp_mem_is(lm_lo, e, M_FROM(e))) undo_bad++;
    }
    for (u64 k = N_MP_AV; k > 0; k--) {
        u64 i = k - 1;
        if (mp_av_do[i] != 2) continue;
        const struct mp_ent *e = &mp_av[i];
        mp_av_put(av, e, M_FROM(e));
        if (!mp_av_is(av, (int)fd_mem, e, M_FROM(e))) undo_bad++;
    }
    for (u64 k = N_RAM_WORDS; k > 0; k--) {
        u64 i = k - 1;
        if (word_do[i] != 2) continue;
        const struct ram_word *w = &ram_words[i];
        if (cp_word_write(w->address, W_FROM(w)) || cp_word_state(w->address, W_TO(w), W_FROM(w)) != 1) undo_bad++;
    }
    for (u64 k = N_CP_SITES; k > 0; k--) {
        u64 i = k - 1;
        if (l5_do[i] != 2) continue;
        const struct cp_site *s = cp_site_at(i);
        if (cp_site_write(s, S_FROM(s)) || cp_site_read(s) || !cp_site_holds(s, S_FROM(s))) undo_bad++;
    }
#ifdef FUSED_HAS_DMM
    for (u64 k = N_DMM_SITES; k > 0; k--) {
        u64 i = k - 1;
        if (dmm_do[i] != 2) continue;
        const struct dmm_site *s = &dmm_sites[i];
        if (cp_word_write(s->address, W_FROM(s)) || cp_word_state(s->address, W_TO(s), W_FROM(s)) != 1) undo_bad++;
    }
#endif
#else /* LEVEL == 20 rollback: reverse of putback order */
#ifdef FUSED_HAS_DMM
    for (u64 i = 0; i < N_DMM_SITES; i++) {
        if (dmm_do[i] != 2) continue;
        const struct dmm_site *s = &dmm_sites[i];
        if (cp_word_write(s->address, W_FROM(s)) || cp_word_state(s->address, W_TO(s), W_FROM(s)) != 1) undo_bad++;
    }
#endif
    for (u64 i = 0; i < N_CP_SITES; i++) {
        if (l5_do[i] != 2) continue;
        const struct cp_site *s = cp_site_at(i);
        if (cp_site_write(s, S_FROM(s)) || cp_site_read(s) || !cp_site_holds(s, S_FROM(s))) undo_bad++;
    }
    for (u64 i = 0; i < N_RAM_WORDS; i++) {
        if (word_do[i] != 2) continue;
        const struct ram_word *w = &ram_words[i];
        if (cp_word_write(w->address, W_FROM(w)) || cp_word_state(w->address, W_TO(w), W_FROM(w)) != 1) undo_bad++;
    }
    for (u64 i = 0; i < N_MP_AV; i++) {
        if (mp_av_do[i] != 2) continue;
        const struct mp_ent *e = &mp_av[i];
        mp_av_put(av, e, M_FROM(e));
        if (!mp_av_is(av, (int)fd_mem, e, M_FROM(e))) undo_bad++;
    }
    for (u64 i = 0; i < N_MP_LM; i++) {
        if (mp_lm_do[i] != 2) continue;
        const struct mp_ent *e = &mp_lm[i];
        if (!mp_mem_put((int)pm_fd, lm_lo, e, M_FROM(e)) || !mp_mem_is(lm_lo, e, M_FROM(e))) undo_bad++;
    }
#ifdef FUSED_HAS_APPFW
    for (u64 i = 0; i < N_APP_LM; i++) {
        if (app_lm_do[i] != 2) continue;
        const struct mp_ent *e = &app_lm[i];
        int ok = mp_mem_put((int)pm_fd, app_lo, e, M_FROM(e));
        app_sync_site(app_lo + e->off, e->len);
        if (!ok || !mp_mem_is(app_lo, e, M_FROM(e))) undo_bad++;
    }
#endif
#endif /* LEVEL */

    puts_(undo_bad
          ? "!! UNDO INCOMPLETE. Cold boot the camera (battery out) before anything else.\n"
          : "NOT DONE: a step failed; every site this run touched was put back\n");

out_all:
    sys_close((int)pm_fd);
    sys_munmap((void *)av_m, MP_AV_BYTES);
    sys_close((int)fd_mem);
out_dma:
    sys_munmap((void *)dma_m, dma_maplen);
    sys_close((int)fd_sync);
    cam_dmm_free(dma_handle);
done_line:
    puts_("== done, bytes written before this line: "); putnum((i64)out_total); puts_("\n");
    if (out_fd >= 0) sys_close(out_fd);
    out_fd = -1;
}

__attribute__((constructor)) static void fused_ctor(void) { run(); }
