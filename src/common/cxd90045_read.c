/*
 * OpenGate Studio — Clean-Room ARM32 Read-Only Helper (cxd90045_read.c)
 * Copyright (C) 2026 ArcaneLantern & OpenGate Studio Contributors
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * 100% volatile & read-only: uploaded to /tmp/jiritsu/libJit.so, executed once via
 * dlopen(), and deleted immediately. Writes zero bytes to camera flash, coprocessor
 * RAM, /dev/mem, or /proc/self/mem (writes only its own RAM-disk result file).
 */

#ifndef DUMP
#define DUMP 0
#endif

typedef unsigned char u8;
typedef unsigned int u32;
typedef int i32;
typedef unsigned long long u64;

struct id_file { char name[24]; unsigned char sha256[32]; };
struct mp_ro_site { char name[20]; unsigned int off; unsigned char len; unsigned char group; unsigned char stock[16]; unsigned char target[16]; };
struct page_guard { char name[20]; unsigned int off; unsigned int len; unsigned char sha256[32]; };
struct dump_range { char name[16]; unsigned int phys; unsigned int pages; };

#include EXPECTED_H

#define RESULT_PATH "/tmp_wbshd/readcheck_result.txt"
#define FILE_CAP (64U * 1024U)
#define MAPS_CAP (256U * 1024U)
#define TOTAL_CAP (DUMP ? (512U * 1024U) : (256U * 1024U))

/* ------------------------------------------------------------------ Linux ARM32 EABI syscalls */
#define NR_read 3
#define NR_write 4
#define NR_close 6
#define NR_munmap 91
#define NR_mmap2 192
#define NR_geteuid32 201
#define NR_getdents64 217
#define NR_openat 322

static i32 sc6(i32 n, i32 a, i32 b, i32 c, i32 d, i32 e, i32 f)
{
    register i32 r7 __asm__("r7") = n;
    register i32 r0 __asm__("r0") = a;
    register i32 r1 __asm__("r1") = b;
    register i32 r2 __asm__("r2") = c;
    register i32 r3 __asm__("r3") = d;
    register i32 r4 __asm__("r4") = e;
    register i32 r5 __asm__("r5") = f;
    __asm__ volatile("svc #0"
                     : "+r"(r0)
                     : "r"(r7), "r"(r1), "r"(r2), "r"(r3), "r"(r4), "r"(r5)
                     : "memory", "cc");
    return r0;
}

#define AT_FDCWD (-100)
#define F_RDONLY 0
#define F_DIR 0x4000
#define F_NEW (1 | 0x40 | 0x80)

static i32 sys_open(const char *p, i32 flags, i32 mode) { return sc6(NR_openat, AT_FDCWD, (i32)p, flags, mode, 0, 0); }
static i32 sys_read(i32 fd, void *b, u32 n) { return sc6(NR_read, fd, (i32)b, (i32)n, 0, 0, 0); }
static i32 sys_write(i32 fd, const void *b, u32 n) { return sc6(NR_write, fd, (i32)b, (i32)n, 0, 0, 0); }
static i32 sys_close(i32 fd) { return sc6(NR_close, fd, 0, 0, 0, 0, 0); }
static i32 sys_geteuid(void) { return sc6(NR_geteuid32, 0, 0, 0, 0, 0, 0); }
static i32 sys_munmap(void *p, u32 len) { return sc6(NR_munmap, (i32)p, (i32)len, 0, 0, 0, 0); }
static i32 sys_mmap_ro(i32 fd, u32 len, u32 phys_off)
{
    i32 r = sc6(NR_mmap2, 0, (i32)len, 1 /* PROT_READ */, 1 /* MAP_SHARED */, fd, (i32)(phys_off >> 12));
    return ((u32)r >= 0xfffff001U) ? -1 : r;
}
#if DUMP
static i32 sys_getdents64(i32 fd, void *b, u32 n) { return sc6(NR_getdents64, fd, (i32)b, (i32)n, 0, 0, 0); }
#endif

/* ------------------------------------------------------------------ output helpers */
static i32 out_fd = -1;
static u32 out_total;
static u8 iobuf[4096];

static u32 slen(const char *s) { u32 n = 0; while (s[n]) n++; return n; }
static int same(const u8 *a, const u8 *b, u32 n) { for (u32 i = 0; i < n; i++) if (a[i] != b[i]) return 0; return 1; }

static void put(const void *b, u32 n)
{
    if (out_fd < 0 || out_total >= TOTAL_CAP) return;
    if (n > TOTAL_CAP - out_total) n = TOTAL_CAP - out_total;
    const u8 *p = (const u8 *)b;
    while (n) {
        i32 w = sys_write(out_fd, p, n);
        if (w <= 0) { out_fd = -1; return; }
        p += w; n -= (u32)w; out_total += (u32)w;
    }
}
static void puts_(const char *s) { put(s, slen(s)); }

/* Avoid __aeabi_uidivmod in freestanding ARMv7 builds by using reciprocal multiply by 1/10. */
static void putnum(i32 v)
{
    char t[16];
    int i = 15;
    int neg = v < 0;
    u32 u = neg ? (u32)(-v) : (u32)v;
    t[i] = 0;
    do {
        u32 q = (u32)(((u64)u * 0xCCCCCCCDULL) >> 35);
        u32 r = u - q * 10U;
        t[--i] = (char)('0' + r);
        u = q;
    } while (u);
    if (neg) t[--i] = '-';
    puts_(t + i);
}

static void puthex(const u8 *b, u32 n)
{
    static const char d[] = "0123456789abcdef";
    char line[128]; u32 k = 0;
    for (u32 i = 0; i < n; i++) {
        line[k++] = d[b[i] >> 4]; line[k++] = d[b[i] & 15];
        if (k == sizeof line) { put(line, k); k = 0; }
    }
    if (k) put(line, k);
}

static void putaddr(u32 v)
{
    u8 a[4]; int k = 0;
    a[0] = (u8)(v >> 24); a[1] = (u8)(v >> 16); a[2] = (u8)(v >> 8); a[3] = (u8)v;
    while (k < 3 && !a[k]) k++;
    puts_("0x"); puthex(a + k, (u32)(4 - k));
}

/* ------------------------------------------------------------------ SHA-256 */
struct sha { u32 h[8]; u8 block[64]; u64 len; u32 fill; };
static const u32 K[64] = {
    0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U, 0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
    0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U, 0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
    0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU, 0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
    0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U, 0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
    0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U, 0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
    0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U, 0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
    0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U, 0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
    0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U, 0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U,
};
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
    static const u32 iv[8] = { 0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU, 0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U };
    for (int i = 0; i < 8; i++) s->h[i] = iv[i];
    s->len = 0; s->fill = 0;
}
static void sha_add(struct sha *s, const u8 *p, u32 n)
{
    s->len += n;
    while (n) {
        s->block[s->fill++] = *p++; n--;
        if (s->fill == 64) { sha_block(s, s->block); s->fill = 0; }
    }
}
static void sha_end(struct sha *s, u8 out[32])
{
    u64 bits = s->len * 8ULL;
    u8 pad = 0x80;
    sha_add(s, &pad, 1);
    pad = 0;
    while (s->fill != 56) sha_add(s, &pad, 1);
    for (int i = 7; i >= 0; i--) { u8 b = (u8)(bits >> (8 * i)); sha_add(s, &b, 1); }
    for (int i = 0; i < 8; i++) { out[4 * i] = (u8)(s->h[i] >> 24); out[4 * i + 1] = (u8)(s->h[i] >> 16); out[4 * i + 2] = (u8)(s->h[i] >> 8); out[4 * i + 3] = (u8)s->h[i]; }
}

/* ------------------------------------------------------------------ /proc & files */
static char maps[MAPS_CAP];
static u32 maps_len;
static char cmdline[2048];
static u32 n_other;
static u32 n_av_stock, n_av_target, n_ogsq_target, n_av_non_ogsq_stock;
static u32 n_lm_stock, n_lm_target;

static void copy_file(const char *path, u32 cap)
{
    puts_("== file "); puts_(path); puts_("\n");
    i32 fd = sys_open(path, F_RDONLY, 0);
    if (fd < 0) { puts_("!! open failed "); putnum(fd); puts_("\n"); return; }
    u32 got = 0;
    for (;;) {
        u32 want = sizeof iobuf;
        if (want > cap - got) want = cap - got;
        if (!want) { puts_("\n!! truncated at "); putnum((i32)cap); puts_(" bytes\n"); break; }
        i32 r = sys_read(fd, iobuf, want);
        if (r < 0) { puts_("\n!! read failed "); putnum(r); puts_("\n"); break; }
        if (r == 0) break;
        put(iobuf, (u32)r); got += (u32)r;
    }
    sys_close(fd);
    puts_("\n== end "); putnum((i32)got); puts_(" bytes\n");
}

#if DUMP
struct dirent64_ { u64 ino; long long off; unsigned short reclen; u8 type; char name[]; };
static void copy_dir(const char *path, u32 cap_each)
{
    static u8 dbuf[4096];
    static char names[48][64];
    int count = 0;
    puts_("== dir "); puts_(path); puts_("\n");
    i32 fd = sys_open(path, F_DIR, 0);
    if (fd < 0) { puts_("!! open failed "); putnum(fd); puts_("\n"); return; }
    for (;;) {
        i32 r = sys_getdents64(fd, dbuf, sizeof dbuf);
        if (r <= 0) break;
        for (i32 o = 0; o < r;) {
            struct dirent64_ *d = (struct dirent64_ *)(dbuf + o);
            if (d->reclen == 0) break;
            const char *n = d->name;
            int dot = n[0] == '.' && (n[1] == 0 || (n[1] == '.' && n[2] == 0));
            if (!dot && count < 48 && slen(n) < 64) { u32 k = 0; for (; n[k]; k++) names[count][k] = n[k]; names[count][k] = 0; count++; }
            o += d->reclen;
        }
    }
    sys_close(fd);
    puts_("entries "); putnum(count); puts_("\n");
    for (int i = 0; i < count; i++) {
        char full[256]; u32 k = 0;
        for (const char *a = path; *a && k < 190; a++) full[k++] = *a;
        full[k++] = '/';
        for (const char *b = names[i]; *b && k < 255; b++) full[k++] = *b;
        full[k] = 0;
        copy_file(full, cap_each);
    }
}
#endif

static u32 read_all(const char *path, char *dst, u32 cap)
{
    i32 fd = sys_open(path, F_RDONLY, 0);
    u32 got = 0;
    if (fd < 0) return 0;
    for (;;) {
        i32 r = sys_read(fd, dst + got, cap - 1 - got);
        if (r <= 0) break;
        got += (u32)r;
        if (got >= cap - 1) break;
    }
    sys_close(fd);
    dst[got] = 0;
    return got;
}

static u32 hexval(const char **p)
{
    u32 v = 0;
    for (;; (*p)++) {
        char c = **p; int d;
        if (c >= '0' && c <= '9') d = c - '0'; else if (c >= 'a' && c <= 'f') d = c - 'a' + 10; else break;
        v = (v << 4) | (u32)d;
    }
    return v;
}

static int ends_with(const char *s, u32 n, const char *suffix)
{
    u32 m = slen(suffix);
    if (n < m) return 0;
    return same((const u8 *)s + n - m, (const u8 *)suffix, m);
}

static u32 mapped_at(const char *name, u32 off, char *path, u32 pathcap)
{
    const char *p = maps, *end = maps + maps_len;
    u32 found = 0;
    while (p < end) {
        const char *line = p, *q = p;
        while (p < end && *p != '\n') p++;
        u32 n = (u32)(p - line);
        if (p < end) p++;
        if (!ends_with(line, n, name)) continue;
        u32 lo = hexval(&q); if (*q != '-') continue; q++;
        u32 hi = hexval(&q); if (*q != ' ') continue; q++;
        char r = q[0];
        q += 5;
        u32 fo = hexval(&q);
        if (path && !path[0]) {
            const char *s = line + n;
            while (s > line && s[-1] != ' ') s--;
            u32 k = 0;
            for (; s < line + n && k + 1 < pathcap; s++) path[k++] = *s;
            path[k] = 0;
        }
        if (!found && r == 'r' && off >= fo && off < fo + (hi - lo)) found = lo + (off - fo);
    }
    return found;
}

static int cmdline_has(const char *needle)
{
    u32 m = slen(needle);
    for (u32 i = 0; cmdline[i]; i++) if (same((const u8 *)cmdline + i, (const u8 *)needle, m)) return 1;
    return 0;
}

static void file_identity(void)
{
    puts_("== identity: files of this process\n");
    for (u32 i = 0; i < sizeof id_files / sizeof id_files[0]; i++) {
        char path[200]; path[0] = 0;
        u32 at = mapped_at(id_files[i].name, 0, path, sizeof path);
        puts_("file "); puts_(id_files[i].name);
        if (!path[0]) { puts_("  NOT MAPPED in this process\n"); n_other++; continue; }
        puts_(" path "); puts_(path); puts_(" mapped "); putaddr(at); puts_("\n");
        i32 fd = sys_open(path, F_RDONLY, 0);
        if (fd < 0) { puts_("!! open failed "); putnum(fd); puts_("\n"); n_other++; continue; }
        struct sha s; u8 dg[32]; u32 total = 0;
        sha_init(&s);
        for (;;) { i32 r = sys_read(fd, iobuf, sizeof iobuf); if (r <= 0) break; sha_add(&s, iobuf, (u32)r); total += (u32)r; }
        sys_close(fd);
        sha_end(&s, dg);
        int ok = same(dg, id_files[i].sha256, 32);
        puts_("  bytes "); putnum((i32)total); puts_(" sha256 "); puthex(dg, 32);
        puts_(ok ? "  SAME as the " FW_VER " update\n" : "  DIFFERS from the " FW_VER " update\n");
        if (!ok) n_other++;
    }
}

static void report_site(const char *tag, int is_av, const struct mp_ro_site *e, const u8 *v)
{
    int st = same(v, e->stock, e->len), tg = same(v, e->target, e->len);
    puts_(tag); puts_(" "); puts_(e->name); puts_(" "); putaddr(e->off);
    puts_(" len "); putnum(e->len);
    puts_(" bytes "); puthex(v, e->len);
    puts_(st ? "  STOCK\n" : tg ? "  TARGET\n" : "  OTHER\n");
    if (is_av) {
        if (st) {
            n_av_stock++;
            if (e->group != 1) n_av_non_ogsq_stock++;
        } else if (tg) {
            n_av_target++;
            if (e->group == 1) n_ogsq_target++;
        } else {
            n_other++;
        }
    } else {
        if (st) n_lm_stock++;
        else if (tg) n_lm_target++;
        else n_other++;
    }
}

static void mp_part(void)
{
    puts_("== main-processor sites: libmpr.so in this process\n");
    for (u32 i = 0; i < sizeof lm_guards / sizeof lm_guards[0]; i++) {
        const struct page_guard *g = &lm_guards[i];
        u32 at = mapped_at("/libmpr.so", g->off, 0, 0);
        if (!at || !mapped_at("/libmpr.so", g->off + g->len - 1, 0, 0)) {
            puts_("guard "); puts_(g->name); puts_("  NOT MAPPED\n"); n_other++; continue;
        }
        struct sha s; u8 dg[32];
        sha_init(&s); sha_add(&s, (const u8 *)at, g->len); sha_end(&s, dg);
        int ok = same(dg, g->sha256, 32);
        puts_("guard "); puts_(g->name); puts_(" "); putaddr(g->off); puts_(" len "); putnum((i32)g->len);
        puts_(ok ? "  SAME\n" : "  DIFFERS\n");
        if (!ok) n_other++;
    }
    for (u32 i = 0; i < sizeof lm_sites / sizeof lm_sites[0]; i++) {
        const struct mp_ro_site *e = &lm_sites[i];
        u32 at = mapped_at("/libmpr.so", e->off, 0, 0);
        if (!at || !mapped_at("/libmpr.so", e->off + e->len - 1, 0, 0)) {
            puts_("lm "); puts_(e->name); puts_(" "); putaddr(e->off); puts_("  NOT MAPPED\n"); n_other++; continue;
        }
        report_site("lm", 0, e, (const u8 *)at);
    }

    puts_("== main-processor sites: av-cam.bin in reserved DDR\n");
    if (!cmdline_has(AVCAM_RESERVE)) {
        puts_("!! the kernel command line does not reserve memory as " AVCAM_RESERVE "; av-cam.bin is not read\n");
        n_other++;
        return;
    }
    i32 fd = sys_open("/dev/mem", F_RDONLY, 0);
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("\n"); n_other++; return; }

    for (u32 i = 0; i < sizeof av_guards / sizeof av_guards[0]; i++) {
        const struct page_guard *g = &av_guards[i];
        u32 pg = (AVCAM_PHYS + g->off) & ~0xfffU;
        u32 lead = (AVCAM_PHYS + g->off) - pg;
        u32 maplen = (lead + g->len + 0xfffU) & ~0xfffU;
        i32 m = sys_mmap_ro(fd, maplen, pg);
        if (m == -1) { puts_("!! guard mmap failed\n"); n_other++; continue; }
        struct sha s; u8 dg[32];
        sha_init(&s); sha_add(&s, (const u8 *)m + lead, g->len); sha_end(&s, dg);
        sys_munmap((void *)m, maplen);
        int ok = same(dg, g->sha256, 32);
        puts_("guard "); puts_(g->name); puts_(" "); putaddr(g->off); puts_(" len "); putnum((i32)g->len);
        puts_(ok ? "  SAME\n" : "  DIFFERS\n");
        if (!ok) n_other++;
    }

    u32 lo = AV_LO & ~0xfffU, len = ((AV_HI + 0xfffU) & ~0xfffU) - lo;
    i32 m = sys_mmap_ro(fd, len, AVCAM_PHYS + lo);
    if (m == -1) { puts_("!! mmap of av-cam.bin's tables failed\n"); sys_close(fd); n_other++; return; }
    const u8 *av = (const u8 *)m - lo;
    for (u32 i = 0; i < sizeof av_sites / sizeof av_sites[0]; i++) {
        report_site("av", 1, &av_sites[i], av + av_sites[i].off);
    }
    sys_munmap((void *)m, len);

#if DUMP
    puts_("== reserved DDR pages\n");
    for (u32 i = 0; i < sizeof dump_ranges / sizeof dump_ranges[0]; i++) {
        const struct dump_range *r = &dump_ranges[i];
        for (u32 p = 0; p < r->pages; p++) {
            u32 pa = r->phys + p * 4096U;
            i32 mp = sys_mmap_ro(fd, 4096U, pa);
            if (mp == -1) { puts_("!! ddr mmap failed at "); putaddr(pa); puts_("\n"); break; }
            puts_("ddrpage "); puts_(r->name); puts_(" "); putaddr(pa); puts_(" "); puthex((const u8 *)mp, 4096U); puts_("\n");
            sys_munmap((void *)mp, 4096U);
        }
    }
#endif
    sys_close(fd);
}

static void run(void)
{
    i32 fd = sys_open(RESULT_PATH, F_NEW, 0600);
    if (fd < 0) return;
    out_fd = fd;
    puts_(READER_NAME " " MODEL_LABEL); puts_(DUMP ? " dump" : " check"); puts_(" for " MODEL_NAME " " FW_VER "; read-only\n");
    puts_("euid "); putnum(sys_geteuid()); puts_("\n");
    static const char files[][24] = {
        "/proc/version", "/proc/cmdline", "/proc/iomem", "/proc/mounts",
        "/proc/modules", "/proc/meminfo", "/proc/self/status",
    };
    for (u32 i = 0; i < sizeof files / sizeof files[0]; i++) copy_file(files[i], FILE_CAP);
    maps_len = read_all("/proc/self/maps", maps, sizeof maps);
    read_all("/proc/cmdline", cmdline, sizeof cmdline);
    puts_("== file /proc/self/maps\n"); put(maps, maps_len); puts_("\n== end "); putnum((i32)maps_len); puts_(" bytes\n");
#if DUMP
    copy_dir("/sys/module/liro/parameters", 256);
    copy_dir("/log", 2048);
#endif
    file_identity();
    mp_part();

    u32 n_av = sizeof av_sites / sizeof av_sites[0];
    u32 n_lm = sizeof lm_sites / sizeof lm_sites[0];
    int is_stock = (n_other == 0 && n_av_stock == n_av && n_lm_stock == n_lm);
    int is_squeezed = (n_other == 0 && n_ogsq_target == OGSQ_AV_SITES && n_av_non_ogsq_stock == (n_av - OGSQ_AV_SITES) && n_lm_stock == n_lm);
    int is_full2560 = (n_other == 0 && n_av_target == n_av && n_lm_target == n_lm);

    puts_("== summary\nplaces not as the " FW_VER " update or not read: "); putnum((i32)n_other);
    if (is_stock) {
        puts_("\nVERDICT READY (stock preflight)\n");
    } else if (is_squeezed || is_full2560) {
        puts_("\nVERDICT READY (open gate applied)\n");
    } else {
        puts_("\nVERDICT NOT READY\n");
    }
    puts_("== done\n");
    sys_close(fd);
    out_fd = -1;
}

__attribute__((constructor, used)) void cxd90045_read_ctor(void) { run(); }
