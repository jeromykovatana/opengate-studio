/*
 * OpenGate Studio — Clean-Room ARM32 Volatile-RAM Write Helper (cxd90045_write.c)
 * Copyright (C) 2026 ArcaneLantern & OpenGate Studio Contributors
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * STEP_NUM = 5/6/16/17/19/20, IS_APPLY = 1 (apply) or 0 (putback).
 * Compiled with -DMP_H='"expected_mp_<design>.h"' for L5/L6 (ogsq), L16/L17 (outsz2560),
 * or L19/L20 (ogfile2560).
 *
 * Writes ONLY into volatile main-processor RAM (av-cam.bin via /dev/mem cached RW mmap,
 * verified against kernel view via pread64; and libmpr.so via /proc/self/mem pwrite64).
 * Refuses to touch anything unless /proc/cmdline has AVCAM_RESERVE, every guard matches,
 * every site holds stock or target bytes, and kernel view equals mmap view. On any write
 * or readback failure, restores every byte touched in this run.
 */
#ifndef STEP_NUM
#error "cxd90045_write.c requires -DSTEP_NUM"
#endif
#ifndef IS_APPLY
#error "cxd90045_write.c requires -DIS_APPLY"
#endif
#ifndef MP_H
#error "cxd90045_write.c requires -DMP_H"
#endif

typedef unsigned char u8;
typedef unsigned int u32;
typedef int i32;
typedef unsigned long long u64;

#include MP_H

#if IS_APPLY
#define MP_FROM(e) ((e)->stock)
#define MP_TO(e) ((e)->changed)
#define MP_VERB "apply"
#else
#define MP_FROM(e) ((e)->changed)
#define MP_TO(e) ((e)->stock)
#define MP_VERB "put back"
#endif

#define RESULT_PATH "/tmp_wbshd/readcheck_result.txt"
#define TOTAL_CAP (256U * 1024U)
#define MAPS_CAP (256U * 1024U)

/* ------------------------------------------------------------------ Linux ARM32 EABI syscalls */
#define NR_read 3
#define NR_write 4
#define NR_close 6
#define NR_munmap 91
#define NR_pread64 180
#define NR_pwrite64 181
#define NR_mmap2 192
#define NR_geteuid32 201
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
#define F_RDWR 2
#define F_NEW (1 | 0x40 | 0x80)

static i32 sys_open(const char *p, i32 flags, i32 mode) { return sc6(NR_openat, AT_FDCWD, (i32)p, flags, mode, 0, 0); }
static i32 sys_read(i32 fd, void *b, u32 n) { return sc6(NR_read, fd, (i32)b, (i32)n, 0, 0, 0); }
static i32 sys_write(i32 fd, const void *b, u32 n) { return sc6(NR_write, fd, (i32)b, (i32)n, 0, 0, 0); }
static i32 sys_close(i32 fd) { return sc6(NR_close, fd, 0, 0, 0, 0, 0); }
static i32 sys_geteuid(void) { return sc6(NR_geteuid32, 0, 0, 0, 0, 0, 0); }
static i32 sys_munmap(void *p, u32 len) { return sc6(NR_munmap, (i32)p, (i32)len, 0, 0, 0, 0); }
static i32 sys_mmap_rw(i32 fd, u32 len, u32 phys_off)
{
    i32 r = sc6(NR_mmap2, 0, (i32)len, 3 /* PROT_READ | PROT_WRITE */, 1 /* MAP_SHARED */, fd, (i32)(phys_off >> 12));
    return ((u32)r >= 0xfffff001U) ? -1 : r;
}
__attribute__((noinline)) static int mp_kview(i32 fd, u32 phys, u8 *out, u32 len)
{
    return sc6(NR_pread64, fd, (i32)out, (i32)len, 0, (i32)phys, 0) == (i32)len;
}
__attribute__((noinline)) static int mp_lm_put(i32 pm, u32 va, const u8 *bytes, u32 len)
{
    return sc6(NR_pwrite64, pm, (i32)bytes, (i32)len, 0, (i32)va, 0) == (i32)len;
}

/* ------------------------------------------------------------------ output helpers */
static i32 out_fd = -1;
static u32 out_total;
static char maps[MAPS_CAP];
static u32 maps_len;
static char cmdline[2048];
static u8 mp_do_av[MP_MAX], mp_do_lm[MP_MAX];

static u32 slen(const char *s) { u32 n = 0; while (s[n]) n++; return n; }
static int mp_eq(const u8 *a, const u8 *b, u32 n) { for (u32 i = 0; i < n; i++) if (a[i] != b[i]) return 0; return 1; }

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
    char line[64]; u32 k = 0;
    for (u32 i = 0; i < n; i++) {
        line[k++] = d[b[i] >> 4]; line[k++] = d[b[i] & 15];
        if (k == sizeof line) { put(line, k); k = 0; }
    }
    if (k) put(line, k);
}
static void mp_putx(u32 v)
{
    u8 a[4]; int k = 0;
    a[0] = (u8)(v >> 24); a[1] = (u8)(v >> 16); a[2] = (u8)(v >> 8); a[3] = (u8)v;
    while (k < 3 && !a[k]) k++;
    puts_("0x"); puthex(a + k, (u32)(4 - k));
}

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
    return mp_eq((const u8 *)s + n - m, (const u8 *)suffix, m);
}

static u32 mapped_at(const char *name, u32 off)
{
    const char *p = maps, *end = maps + maps_len;
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
        if (r == 'r' && off >= fo && off < fo + (hi - lo)) return lo + (off - fo);
    }
    return 0;
}

static int cmdline_has(const char *needle)
{
    u32 m = slen(needle);
    for (u32 i = 0; cmdline[i]; i++) if (mp_eq((const u8 *)cmdline + i, (const u8 *)needle, m)) return 1;
    return 0;
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

static int mp_lm_is(u32 va, const struct mp_site *e, const u8 *bytes)
{
    const volatile u8 *mem = (const volatile u8 *)va;
    for (u32 k = 0; k < e->len; k++) if (mem[k] != bytes[k]) return 0;
    return 1;
}

static void mp_av_put(volatile u8 *av, const struct mp_site *e, const u8 *bytes)
{
    for (u32 k = 0; k < e->len; k++) av[e->off - MP_AV_FIRST + k] = bytes[k];
}

static int mp_av_is(const volatile u8 *av, i32 fd, const struct mp_site *e, const u8 *bytes)
{
    u8 kv[16];
    for (u32 k = 0; k < e->len; k++) if (av[e->off - MP_AV_FIRST + k] != bytes[k]) return 0;
    return mp_kview(fd, AVCAM_PHYS + e->off, kv, e->len) && mp_eq(kv, bytes, e->len);
}

static void run(void)
{
    i32 rfd = sys_open(RESULT_PATH, F_NEW, 0600);
    if (rfd < 0) return;
    out_fd = rfd;

    puts_("readcheck 1 level "); putnum(STEP_NUM); puts_("\neuid "); putnum(sys_geteuid()); puts_("\n");
    puts_("== level "); putnum(STEP_NUM); puts_(": " MP_VERB " the main-processor sites of " MP_DESIGN "\n");

    maps_len = read_all("/proc/self/maps", maps, sizeof maps);
    read_all("/proc/cmdline", cmdline, sizeof cmdline);
    if (!cmdline_has(AVCAM_RESERVE)) {
        puts_("!! /proc/cmdline missing " AVCAM_RESERVE "; nothing is written\n");
        goto finish;
    }

    i32 fd = sys_open("/dev/mem", F_RDWR, 0);
    if (fd < 0) { puts_("!! /dev/mem open failed "); putnum(fd); puts_("; nothing is written\n"); goto finish; }
    i32 m = sys_mmap_rw(fd, MP_AV_BYTES, AVCAM_PHYS + MP_AV_FIRST);
    if (m == -1) { puts_("!! mmap of av-cam.bin tables failed; nothing is written\n"); sys_close(fd); goto finish; }
    i32 pm = sys_open("/proc/self/mem", F_RDWR, 0);
    if (pm < 0) { puts_("!! /proc/self/mem open failed "); putnum(pm); puts_("; nothing is written\n"); sys_munmap((void *)m, MP_AV_BYTES); sys_close(fd); goto finish; }

    volatile u8 *av = (volatile u8 *)m;
    u32 n_av = sizeof mp_av / sizeof mp_av[0];
    u32 n_lm = sizeof mp_lm / sizeof mp_lm[0];
    u32 n_todo = 0;
    int ok = 1;

    for (u32 i = 0; i < n_av && ok; i++) {
        const struct mp_site *e = &mp_av[i];
        u8 got[16], kv[16];
        mp_do_av[i] = 0;
        if (e->len > 16 || e->off < MP_AV_FIRST || e->off + e->len > MP_AV_FIRST + MP_AV_BYTES) {
            ok = mp_refuse("av", e, "lies outside the mapped range"); break;
        }
        for (u32 k = 0; k < e->len; k++) got[k] = av[e->off - MP_AV_FIRST + k];
        if (!mp_kview(fd, AVCAM_PHYS + e->off, kv, e->len) || !mp_eq(kv, got, e->len)) {
            ok = mp_refuse("av", e, "kernel view differs from mapping"); break;
        }
        if (!e->kind) {
            if (!mp_eq(got, e->stock, e->len)) { ok = mp_refuse("av", e, "is not as in the file"); break; }
            continue;
        }
        if (mp_eq(got, MP_FROM(e), e->len)) { mp_do_av[i] = 1; n_todo++; mp_where("av", e); puts_(": as expected\n"); }
        else if (mp_eq(got, MP_TO(e), e->len)) { mp_where("av", e); puts_(": already holds the target bytes\n"); }
        else { ok = mp_refuse("av", e, "holds neither set of bytes"); break; }
    }

    u32 lm_vas[MP_MAX];
    for (u32 i = 0; i < n_lm && ok; i++) {
        const struct mp_site *e = &mp_lm[i];
        u8 got[16];
        mp_do_lm[i] = 0;
        u32 va = mapped_at("/libmpr.so", e->off);
        u32 va_end = mapped_at("/libmpr.so", e->off + e->len - 1);
        lm_vas[i] = va;
        if (e->len > 16 || !va || !va_end || va_end != va + e->len - 1) {
            ok = mp_refuse("lm", e, "not mapped cleanly in /proc/self/maps"); break;
        }
        const volatile u8 *p = (const volatile u8 *)va;
        for (u32 k = 0; k < e->len; k++) got[k] = p[k];
        if (!e->kind) {
            if (!mp_eq(got, e->stock, e->len)) { ok = mp_refuse("lm", e, "is not as in the file"); break; }
            continue;
        }
        if (mp_eq(got, MP_FROM(e), e->len)) { mp_do_lm[i] = 1; n_todo++; mp_where("lm", e); puts_(": as expected\n"); }
        else if (mp_eq(got, MP_TO(e), e->len)) { mp_where("lm", e); puts_(": already holds the target bytes\n"); }
        else { ok = mp_refuse("lm", e, "holds neither set of bytes"); break; }
    }

    if (!ok) goto cleanup;
    puts_("checks passed: every guard is as in the file, every site holds one of the two sets of bytes\n");
    if (!n_todo) {
        puts_("NOTHING TO DO: every site already holds the target bytes (" MP_VERB ")\n");
        goto cleanup;
    }

    int failed = 0, undo_bad = 0;
    for (u32 i = 0; i < n_av && !failed; i++) {
        const struct mp_site *e = &mp_av[i];
        if (mp_do_av[i] != 1) continue;
        mp_do_av[i] = 2;
        mp_av_put(av, e, MP_TO(e));
        if (mp_av_is(av, fd, e, MP_TO(e))) { mp_where("av", e); puts_(": written and read back\n"); }
        else { puts_("!! "); mp_where("av", e); puts_(": write not seen in both views\n"); failed = 1; }
    }
    for (u32 i = 0; i < n_lm && !failed; i++) {
        const struct mp_site *e = &mp_lm[i];
        if (mp_do_lm[i] != 1) continue;
        mp_do_lm[i] = 2;
        if (!mp_lm_put(pm, lm_vas[i], MP_TO(e), e->len)) { puts_("!! "); mp_where("lm", e); puts_(": /proc/self/mem write failed\n"); failed = 1; }
        else if (!mp_lm_is(lm_vas[i], e, MP_TO(e))) { puts_("!! "); mp_where("lm", e); puts_(": write not seen in process memory\n"); failed = 1; }
        else { mp_where("lm", e); puts_(": written and read back\n"); }
    }
    if (!failed) {
        puts_("DONE: every site holds the target bytes (" MP_VERB ")\n");
        goto cleanup;
    }

    for (u32 i = 0; i < n_lm; i++) {
        const struct mp_site *e = &mp_lm[i];
        if (mp_do_lm[i] != 2) continue;
        mp_lm_put(pm, lm_vas[i], MP_FROM(e), e->len);
        if (mp_lm_is(lm_vas[i], e, MP_FROM(e))) { puts_("undo "); mp_where("lm", e); puts_(": put back\n"); }
        else { puts_("!! undo "); mp_where("lm", e); puts_(": NOT put back\n"); undo_bad = 1; }
    }
    for (u32 i = 0; i < n_av; i++) {
        const struct mp_site *e = &mp_av[i];
        if (mp_do_av[i] != 2) continue;
        mp_av_put(av, e, MP_FROM(e));
        if (mp_av_is(av, fd, e, MP_FROM(e))) { puts_("undo "); mp_where("av", e); puts_(": put back\n"); }
        else { puts_("!! undo "); mp_where("av", e); puts_(": NOT put back\n"); undo_bad = 1; }
    }
    puts_(undo_bad ? "!! UNDO INCOMPLETE: memory may be partly changed; cold boot the camera\n"
                   : "NOT DONE: a step failed; every site touched was put back\n");

cleanup:
    sys_close(pm);
    sys_munmap((void *)m, MP_AV_BYTES);
    sys_close(fd);
finish:
    puts_("== done, bytes written before this line: "); putnum((i32)out_total); puts_("\n");
    sys_close(rfd);
    out_fd = -1;
}

__attribute__((constructor, used)) void cxd90045_write_ctor(void) { run(); }
