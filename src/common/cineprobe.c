/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * cineprobe.c: Freestanding read-only AArch64 Cinema Line unlock probe.
 *
 * Inspects live /usr/lib/appFw.so ELF segments, .dynsym cinema symbols,
 * string xrefs + referenced .bss/PT_LOAD[1] RAM windows, targeted code/data
 * windows, non-zero RW page hashes, and read-only coprocessor pages.
 *
 * Writes ONLY /tmp_wbshd/readcheck_result.txt on the camera RAM disk.
 * Performs ZERO writes to flash or camera memory.
 */

#define RESULT_PATH "/tmp_wbshd/readcheck_result.txt"
#define FILE_CAP   (64 * 1024)
#define MAPS_CAP   (384 * 1024)
#define TOTAL_CAP  (1536 * 1024)
#define CP_PAGE    4096U
#define MAX_VMAS   512
#define MAX_XREF_TARGETS 64
#define MAX_RAM_XREFS    128

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long u64;
typedef long i64;
typedef int i32;

/* ------------------------------------------------------------------ per-body config */

struct id_file {
    const char *name;
    u8 sha256[32];
};

struct id_page {
    u32 address;
    u8 sha256[32];
};

struct cp_range {
    const char *name;
    u32 address;
    u32 pages;
};

struct target_win {
    const char *name;
    u64 va;
    u32 len;
};

#if defined(BODY_ZVE1)
#define PROBE_HEADER "zvread cineprobe_v1 cineprobe for ZV-E1 2.02; read-only\n"
#define FW_STR "2.02"
#define CP_LO 0xC0000U
#define CP_HI 0x2700000U

static const struct id_file id_files[] = {
    { "/appFw.so",     { 0x88,0x14,0x6f,0xa5,0xf5,0x84,0x4b,0x45,0xde,0x9f,0x20,0xab,0x5f,0x17,0x50,0xaa,0x6e,0x82,0x1e,0x10,0x65,0x8a,0xf3,0x7f,0x88,0xce,0x7d,0x4d,0x76,0xa8,0x33,0xf8 } },
    { "/libmpr.so",    { 0xe4,0x5d,0xde,0x41,0x29,0x1c,0xf4,0x5d,0xd8,0x08,0x97,0xe0,0xd9,0xfa,0x03,0x81,0x8c,0x1c,0xdc,0x14,0xae,0x4d,0x46,0x6c,0x64,0xf3,0xd4,0x8a,0xf4,0x19,0xe7,0xcd } },
    { "/libsencore.so",{ 0x78,0x4e,0x51,0x59,0xc2,0xf4,0xd3,0xc7,0xa1,0x08,0xe5,0xc5,0x3a,0x36,0x73,0xe0,0x37,0xc6,0x86,0xe7,0xe5,0xa1,0x99,0xd9,0x86,0xea,0xde,0xdb,0xb1,0x49,0x2f,0x58 } },
    { "/libJiritsu.so",{ 0xb2,0x60,0x59,0x5f,0x78,0xf6,0xb7,0xf7,0x91,0xbb,0x69,0xf2,0x97,0x3b,0xad,0xd8,0x5b,0xf5,0x30,0xcc,0x19,0x8b,0xf1,0x56,0x48,0xc8,0x03,0x11,0x72,0xbc,0x82,0xf2 } },
};
static const struct id_page id_pages[] = {
    { 0x128000U, { 0xaf,0xe5,0x5f,0x4a,0x38,0x3f,0xcf,0xfa,0x2b,0x66,0x35,0xc4,0xe5,0x47,0xa7,0x51,0xd3,0x34,0x94,0x13,0x84,0x0a,0x63,0x6a,0xa8,0xce,0x7a,0x5b,0x66,0xbc,0x14,0x66 } },
    { 0x4aa000U, { 0x39,0x4f,0x8a,0x96,0xe9,0x92,0x0d,0xad,0x65,0xa0,0x7a,0x50,0xfa,0x82,0xa1,0xf7,0x57,0xc1,0xab,0x59,0x54,0x88,0x13,0xc4,0x4b,0xfa,0xd4,0x85,0xa5,0xe7,0xa9,0xec } },
    { 0x96d000U, { 0x26,0x0c,0x64,0xe3,0x8a,0x16,0x8c,0x6b,0x98,0xdd,0x78,0x0c,0x9a,0xdb,0xa4,0x50,0xe5,0xc0,0xbf,0x6c,0x7c,0xd5,0x7b,0x6c,0x64,0xad,0x44,0x90,0x8c,0x2b,0x77,0xf3 } },
    { 0x788000U, { 0xcf,0x89,0x64,0x3b,0x7f,0x0e,0x6c,0x71,0x33,0x6d,0x0b,0x96,0x20,0x12,0x13,0x64,0x6e,0x20,0x6c,0x2b,0x83,0x7f,0xc2,0x4e,0x24,0xbb,0x2d,0xc0,0x4f,0x34,0x79,0xfe } },
};
static const struct cp_range cp_probe_ranges[] = {
    { "shadow",      0x11bd000U, 2 },
    { "context",     0x168b000U, 4 },
    { "kprint_tail", 0x00f8000U, 8 },
};
static const struct target_win targeted_windows[] = {
    { "elf_hdr",                   0x0000000UL, 64  },
    { "zv_reladyn_cave_after_c19", 0x17d65c0UL, 512 },
    { "zv_dlsym_stub",             0x17de7a0UL, 96  },
    { "zv_fm_getters",             0x1915100UL, 256 },
    { "zv_text_cave",              0x1f576e0UL, 256 },
    { "zv_input_hook_area",        0x1f7c5c0UL, 192 },
    { "zv_system_mode",            0x28a6720UL, 128 },
    { "zv_vdf_layout",             0x33a3540UL, 128 },
    { "zv_fm_rodata",              0x35734e0UL, 256 },
    { "zv_fm_rodata_mag",          0x35743e0UL, 96  },
};

#elif defined(BODY_FX3)
#define PROBE_HEADER "fx3read cineprobe_v1 cineprobe for ILME-FX3 7.02; read-only\n"
#define FW_STR "7.02"
#define CP_LO 0xC0000U
#define CP_HI 0x2100000U

static const struct id_file id_files[] = {
    { "/appFw.so",     { 0x54,0x5c,0x50,0x53,0xa7,0x4e,0x04,0xff,0xbf,0x2b,0xba,0xaf,0x80,0xf5,0x58,0x09,0x2d,0xd5,0x45,0xed,0x22,0x98,0xb2,0x39,0x5c,0xa5,0x47,0xdb,0xba,0x58,0x29,0x0f } },
    { "/libmpr.so",    { 0x9a,0xee,0xf3,0xb9,0xed,0xb3,0xd0,0x11,0xc0,0xc9,0x0c,0xd2,0x38,0x7b,0x3a,0x47,0xbd,0x3b,0x50,0x6e,0xbf,0xa5,0x7b,0xe3,0x9a,0xd1,0xa9,0x72,0x97,0x71,0xb5,0x7c } },
    { "/libsencore.so",{ 0xa2,0x90,0x71,0x11,0xc4,0xa2,0x23,0x14,0xdc,0xb1,0x2c,0x25,0x88,0x9e,0x0e,0x31,0x42,0x76,0x4c,0x6a,0x4a,0x91,0x0a,0x74,0x6e,0x43,0x90,0x8f,0x76,0xe7,0xc4,0x10 } },
    { "/libJiritsu.so",{ 0xbd,0xef,0x58,0xb2,0x4a,0x3b,0x67,0xb4,0xd1,0x4d,0x4f,0x02,0x14,0xb8,0x9a,0xae,0x0f,0xca,0xd1,0x9f,0x11,0x4b,0x41,0x88,0xc3,0x28,0xf9,0xd2,0xc0,0x92,0xf1,0xd9 } },
};
static const struct id_page id_pages[] = {
    { 0x128000U, { 0x04,0x2e,0xcc,0xe2,0x56,0xd4,0x49,0xd3,0x83,0xe7,0xe1,0x14,0xe5,0x7d,0x72,0x6d,0xd7,0xc1,0x5b,0xf0,0x69,0x88,0x86,0xf3,0x09,0xb3,0x18,0x3e,0x4f,0xa8,0xc2,0x9b } },
    { 0x4a8000U, { 0x6a,0xab,0x18,0x62,0x6a,0x73,0x9d,0x46,0x38,0x46,0xcb,0x87,0x52,0xae,0xd2,0x8c,0x14,0xec,0x25,0xda,0x91,0x0e,0xf5,0x08,0xa3,0x11,0x56,0xc0,0xdf,0x03,0x95,0xb8 } },
    { 0x857000U, { 0x23,0xed,0x3c,0x50,0xb2,0x33,0x4e,0xbb,0xaf,0xc7,0xe7,0xf9,0xe9,0x40,0x63,0xe3,0x28,0x36,0x4a,0xc2,0x33,0x3e,0xd6,0x94,0x72,0xaf,0xb7,0x78,0x83,0x6c,0x4f,0xb7 } },
    { 0xaeb000U, { 0x56,0x12,0xe5,0x1a,0x9e,0x78,0x8f,0x66,0xed,0xb6,0x21,0xcc,0xdc,0xb9,0x96,0x66,0x3d,0x2c,0x23,0x58,0x13,0xde,0xa5,0x0a,0xe3,0x95,0x2e,0x77,0xf4,0x8f,0xe3,0xb2 } },
};
static const struct cp_range cp_probe_ranges[] = {
    { "shadow",      0x0ff4000U, 2 },
    { "context",     0x117b000U, 5 },
    { "kprint_tail", 0x00f8000U, 8 },
};
static const struct target_win targeted_windows[] = {
    { "elf_hdr",          0x0000000UL, 64  },
    { "fx3_ptload0_tail", 0x3d0f740UL, 192 },
    { "fx3_fm_onemount",  0x2f9a160UL, 128 },
};

#elif defined(BODY_A7S3)
#define PROBE_HEADER "s3read cineprobe_v1 cineprobe for ILCE-7SM3 5.01; read-only\n"
#define FW_STR "5.01"
#define CP_LO 0xC0000U
#define CP_HI 0x2100000U

static const struct id_file id_files[] = {
    { "/appFw.so",     { 0xeb,0xa8,0x92,0x99,0x27,0x35,0x42,0xe9,0xde,0x89,0xd6,0x4f,0x3b,0xd3,0x80,0x11,0x4b,0x2b,0x9d,0xf6,0x7a,0x24,0x6a,0x69,0x27,0xcd,0x7a,0x83,0xf2,0x04,0x37,0x81 } },
    { "/libmpr.so",    { 0x59,0xea,0x13,0x4f,0x5a,0x40,0x16,0x63,0x79,0x25,0x81,0x26,0xb7,0xff,0x02,0xc0,0xb3,0x6b,0x98,0x46,0x12,0x9b,0x22,0xb4,0xcd,0xc7,0xfa,0xa5,0x2c,0x92,0x74,0x59 } },
    { "/libsencore.so",{ 0x80,0xb0,0xe7,0x9f,0x10,0xef,0x0d,0x26,0x47,0x4e,0x32,0x3b,0x16,0x21,0x68,0x1a,0x41,0x1e,0xf0,0x83,0xe7,0xcf,0x99,0x54,0x7b,0x3e,0xc7,0x12,0x27,0xf7,0x7e,0x94 } },
    { "/libJiritsu.so",{ 0xcf,0xc1,0x34,0x19,0x0f,0xd8,0x3b,0xee,0x36,0xfe,0x15,0x9e,0x4f,0xa9,0x0a,0x65,0xfe,0x5a,0xe0,0x4a,0x80,0x3f,0x92,0x1d,0xce,0x50,0xd5,0x34,0xed,0x0e,0x1f,0xd0 } },
};
static const struct id_page id_pages[] = {
    { 0x128000U, { 0x19,0x8a,0x2f,0xd1,0xe8,0x98,0x00,0xa5,0x72,0x06,0x58,0x83,0x1e,0x3a,0xa4,0x2a,0xb5,0xe5,0xa7,0xc1,0xd0,0x38,0xae,0xab,0x37,0xa8,0x67,0xbe,0xf3,0xa2,0xb6,0x02 } },
    { 0x4a8000U, { 0xba,0x3f,0x03,0xf1,0xeb,0x8c,0x5b,0xc1,0x46,0xc7,0xee,0x04,0xf8,0x4d,0x0f,0x40,0x56,0x4a,0x31,0xf1,0x91,0x9e,0x3e,0xd8,0xfd,0x2d,0x14,0x78,0x10,0x9f,0x1a,0xea } },
    { 0x86d000U, { 0x31,0x7b,0x60,0x72,0xf4,0xe4,0x00,0xdc,0x08,0x87,0x44,0xb4,0x54,0x58,0x2e,0x0c,0x96,0xe9,0xe9,0x71,0x89,0x69,0x5b,0xec,0xc5,0x0b,0x36,0xe1,0x14,0xd9,0xd0,0x91 } },
    { 0xb11000U, { 0x65,0x4e,0xfc,0xe6,0x88,0x69,0xb9,0x74,0x78,0xb2,0x78,0x20,0xff,0xbf,0x5d,0x29,0x81,0xb4,0xf2,0x15,0xb6,0xb3,0x36,0x96,0x82,0x28,0xb5,0x3f,0x34,0xa8,0x00,0xe3 } },
};
static const struct cp_range cp_probe_ranges[] = {
    { "shadow",      0x1019000U, 2 },
    { "context",     0x11a3000U, 4 },
    { "kprint_tail", 0x00f8000U, 8 },
};
static const struct target_win targeted_windows[] = {
    { "elf_hdr",                 0x0000000UL, 64  },
    { "s3_dlsym_stub",           0x16d8d40UL, 96  },
    { "s3_product_concept_fm",   0x17f84e0UL, 128 },
    { "s3_fm_getters",           0x17f8860UL, 192 },
    { "s3_text_cave_1e9db94",    0x1e9db80UL, 384 },
    { "s3_input_hook_area",      0x1ec5380UL, 128 },
    { "s3_cineei_backend",       0x26c9d60UL, 256 },
    { "s3_system_mode",          0x28a13f0UL, 96  },
    { "s3_cmd147_shutter_desq",  0x351c300UL, 256 },
    { "s3_product_selector",     0x3e28720UL, 128 },
    { "s3_haita_shutter_1",      0x5856b80UL, 128 },
    { "s3_haita_shutter_2",      0x585adf0UL, 128 },
    { "s3_haita_shutter_3",      0x585ffa0UL, 128 },
    { "s3_haita_cineei_1",       0x58aefa0UL, 128 },
    { "s3_haita_cineei_2",       0x58bf860UL, 640 },
    { "s3_bss_cineei_snapshots", 0x7f7d880UL, 256 },
};

static const u64 a7s3_extra_xref_targets[] = {
    0x5856b98UL, 0x585ae08UL, 0x585ffb8UL,
    0x58aefc0UL, 0x58bf880UL, 0x58bfa00UL, 0x58bfac0UL,
    0x7f7d8d8UL, 0x7f7d8f8UL, 0x3e28753UL,
};
#else
#error "cineprobe.c requires -DBODY_ZVE1, -DBODY_FX3, or -DBODY_A7S3"
#endif

/* ------------------------------------------------------------------ syscalls (AArch64 Linux) */
#define NR_openat  56
#define NR_close   57
#define NR_read    63
#define NR_write   64
#define NR_pread64 67
#define NR_munmap  215
#define NR_mmap    222

#define AT_FDCWD      (-100)
#define F_RDONLY      0
#define F_RDONLY_SYNC (0 | 0x101000)
#define F_NEW         (1 | 0x40 | 0x80)

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
static i64 sys_pread64(int fd, void *b, u64 n, u64 off) { return sc(NR_pread64, fd, (i64)b, (i64)n, (i64)off, 0, 0); }
static i64 sys_write(int fd, const void *b, u64 n) { return sc(NR_write, fd, (i64)b, (i64)n, 0, 0, 0); }
static i64 sys_close(int fd) { return sc(NR_close, fd, 0, 0, 0, 0, 0); }
static i64 sys_mmap_ro(int fd, u64 len, u64 off)
{
    i64 r = sc(NR_mmap, 0, (i64)len, 1 /* PROT_READ */, 1 /* MAP_SHARED */, fd, (i64)off);
    return (r < 0 && r > -4096) ? -1 : r;
}
static i64 sys_munmap(void *p, u64 len) { return sc(NR_munmap, (i64)p, (i64)len, 0, 0, 0, 0); }

/* ------------------------------------------------------------------ output helpers */
static int out_fd = -1;
static u64 out_total;

static u64 slen(const char *s)
{
    u64 n = 0;
    while (s[n]) n++;
    return n;
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
    do { t[--i] = (char)('0' + (u % 10)); u /= 10; } while (u);
    if (neg) t[--i] = '-';
    puts_(t + i);
}

static void puthex(const u8 *b, u64 n)
{
    static const char d[] = "0123456789abcdef";
    char line[128];
    u64 k = 0;
    for (u64 i = 0; i < n; i++) {
        line[k++] = d[b[i] >> 4];
        line[k++] = d[b[i] & 15];
        if (k == sizeof line) { put(line, k); k = 0; }
    }
    if (k) put(line, k);
}

static void puthex64_pad(u64 v)
{
    u8 be[8];
    for (int i = 0; i < 8; i++) be[i] = (u8)(v >> (8 * (7 - i)));
    puthex(be, 8);
}

static void putaddr(u64 v)
{
    u8 a[8];
    int k = 0;
    for (int i = 0; i < 8; i++) a[i] = (u8)(v >> (8 * (7 - i)));
    while (k < 7 && !a[k]) k++;
    puts_("0x");
    puthex(a + k, (u64)(8 - k));
}

static int same(const u8 *a, const u8 *b, u64 n)
{
    for (u64 i = 0; i < n; i++) if (a[i] != b[i]) return 0;
    return 1;
}

static char tolower_c(char c) { return (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c; }

static int str_contains_ci(const char *hay, const char *needle)
{
    u64 nlen = slen(needle);
    if (!nlen) return 1;
    for (u64 i = 0; hay[i]; i++) {
        u64 j = 0;
        while (j < nlen && hay[i + j] && tolower_c(hay[i + j]) == tolower_c(needle[j])) j++;
        if (j == nlen) return 1;
    }
    return 0;
}

static u32 rd_u32(const u8 *p)
{
    return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
}

static u16 rd_u16(const u8 *p)
{
    return (u16)p[0] | ((u16)p[1] << 8);
}

static u64 rd_u64(const u8 *p)
{
    return (u64)rd_u32(p) | ((u64)rd_u32(p + 4) << 32);
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
static u32 ror32(u32 x, int n) { return (x >> n) | (x << (32 - n)); }

static void sha_block(struct sha *s, const u8 *p)
{
    u32 w[64], a, b, c, d, e, f, g, h;
    for (int i = 0; i < 16; i++)
        w[i] = ((u32)p[4 * i] << 24) | ((u32)p[4 * i + 1] << 16) | ((u32)p[4 * i + 2] << 8) | p[4 * i + 3];
    for (int i = 16; i < 64; i++)
        w[i] = w[i - 16] + (ror32(w[i - 15], 7) ^ ror32(w[i - 15], 18) ^ (w[i - 15] >> 3))
             + w[i - 7] + (ror32(w[i - 2], 17) ^ ror32(w[i - 2], 19) ^ (w[i - 2] >> 10));
    a = s->h[0]; b = s->h[1]; c = s->h[2]; d = s->h[3];
    e = s->h[4]; f = s->h[5]; g = s->h[6]; h = s->h[7];
    for (int i = 0; i < 64; i++) {
        u32 t1 = h + (ror32(e, 6) ^ ror32(e, 11) ^ ror32(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i];
        u32 t2 = (ror32(a, 2) ^ ror32(a, 13) ^ ror32(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        h = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    s->h[0] += a; s->h[1] += b; s->h[2] += c; s->h[3] += d;
    s->h[4] += e; s->h[5] += f; s->h[6] += g; s->h[7] += h;
}

static void sha_init(struct sha *s)
{
    static const u32 iv[8] = {
        0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
        0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U,
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

/* ------------------------------------------------------------------ global BSS buffers */
static u8 iobuf[16384];
static u8 scanbuf[16384 + 64];
static char maps[MAPS_CAP];
static u64 maps_len;

struct vma_entry {
    u64 lo;
    u64 hi;
    u64 foff;
    char perms[4];
    u32 name_off;
    u32 name_len;
};

static struct vma_entry vmas[MAX_VMAS];
static u32 n_vmas;
static int pm_ro_fd = -1;
static u32 identity_problems;

/* ------------------------------------------------------------------ file copy & maps parsing */
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
        char ch = **p;
        int d;
        if (ch >= '0' && ch <= '9') d = ch - '0';
        else if (ch >= 'a' && ch <= 'f') d = ch - 'a' + 10;
        else if (ch >= 'A' && ch <= 'F') d = ch - 'A' + 10;
        else break;
        v = (v << 4) | (u64)d;
    }
    return v;
}

static int ends_with(const char *s, u64 n, const char *suffix)
{
    u64 m = slen(suffix);
    if (n < m) return 0;
    return same((const u8 *)s + n - m, (const u8 *)suffix, m);
}

static void parse_vmas(void)
{
    n_vmas = 0;
    const char *p = maps, *end = maps + maps_len;
    while (p < end && n_vmas < MAX_VMAS) {
        const char *line = p, *q = p;
        while (p < end && *p != '\n') p++;
        u64 n = (u64)(p - line);
        if (p < end) p++;
        u64 lo = hexval(&q); if (*q != '-') continue; q++;
        u64 hi = hexval(&q); if (*q != ' ') continue; q++;
        char p0 = q[0], p1 = q[1], p2 = q[2], p3 = q[3];
        if (!p0 || !p1 || !p2 || !p3 || q[4] != ' ') continue;
        q += 5;
        u64 fo = hexval(&q);
        const char *s = line + n;
        while (s > line && s[-1] != ' ') s--;
        /* Skip anonymous "[...]"? Keep all readable VMAs including anonymous rw-p (.bss) */
        struct vma_entry *v = &vmas[n_vmas++];
        v->lo = lo;
        v->hi = hi;
        v->foff = fo;
        v->perms[0] = p0;
        v->perms[1] = p1;
        v->perms[2] = p2;
        v->perms[3] = p3;
        v->name_off = (u32)(s - maps);
        v->name_len = (u32)((line + n) - s);
    }
}

static u64 mapped_at(const char *name, u64 off, char *path, u64 pathcap)
{
    u64 found = 0;
    for (u32 i = 0; i < n_vmas; i++) {
        const struct vma_entry *v = &vmas[i];
        const char *vname = maps + v->name_off;
        if (!ends_with(vname, v->name_len, name)) continue;
        if (path && !path[0] && v->name_len > 0 && vname[0] == '/') {
            u64 k = 0;
            for (; k < v->name_len && k + 1 < pathcap; k++) path[k] = vname[k];
            path[k] = 0;
        }
        if (!found && v->perms[0] == 'r' && off >= v->foff && off < v->foff + (v->hi - v->lo))
            found = v->lo + (off - v->foff);
    }
    return found;
}

static int addr_is_readable(u64 addr, u32 len)
{
    if (len == 0) return 1;
    u64 cur = addr;
    u64 end = addr + len;
    if (end < addr) return 0;
    while (cur < end) {
        int hit = 0;
        for (u32 i = 0; i < n_vmas; i++) {
            const struct vma_entry *v = &vmas[i];
            if (v->perms[0] == 'r' && cur >= v->lo && cur < v->hi) {
                cur = (v->hi >= end) ? end : v->hi;
                hit = 1;
                break;
            }
        }
        if (!hit) return 0;
    }
    return 1;
}

static int safe_read_va(u64 bias, u64 rel_va, void *dst, u32 len)
{
    if (pm_ro_fd < 0) return 0;
    u64 addr = bias + rel_va;
    if (addr < bias) return 0;
    if (!addr_is_readable(addr, len)) return 0;
    return sys_pread64(pm_ro_fd, dst, len, addr) == (i64)len;
}

/* ------------------------------------------------------------------ file identity */
static char appfw_path[256];
static u64 appfw_base;

static int verify_file_identity(void)
{
    int appfw_ok = 0;
    appfw_path[0] = 0;
    appfw_base = 0;
    puts_("== identity: files of this process\n");
    for (u64 i = 0; i < sizeof id_files / sizeof id_files[0]; i++) {
        char path[256];
        path[0] = 0;
        u64 at = mapped_at(id_files[i].name, 0, path, sizeof path);
        puts_("file "); puts_(id_files[i].name);
        if (!path[0] || !at) {
            puts_("  NOT MAPPED in this process\n");
            identity_problems++;
            continue;
        }
        puts_(" path "); puts_(path); puts_(" mapped "); putaddr(at); puts_("\n");
        i64 fd = sys_open(path, F_RDONLY, 0);
        if (fd < 0) {
            puts_("!! open failed "); putnum(fd); puts_("\n");
            identity_problems++;
            continue;
        }
        struct sha s;
        u8 dg[32];
        u64 total = 0;
        sha_init(&s);
        for (;;) {
            i64 r = sys_read((int)fd, iobuf, sizeof iobuf);
            if (r <= 0) break;
            sha_add(&s, iobuf, (u64)r);
            total += (u64)r;
        }
        sys_close((int)fd);
        sha_end(&s, dg);
        int ok = same(dg, id_files[i].sha256, 32);
        puts_("  bytes "); putnum((i64)total);
        puts_(" sha256 "); puthex(dg, 32);
        puts_(ok ? "  SAME as the " FW_STR " update\n" : "  DIFFERS from the " FW_STR " update\n");
        if (!ok) {
            identity_problems++;
        } else if (i == 0) {
            appfw_ok = 1;
            appfw_base = at;
            for (u64 k = 0; k < sizeof appfw_path && path[k]; k++) appfw_path[k] = path[k];
            appfw_path[sizeof appfw_path - 1] = 0;
        }
    }
    return appfw_ok;
}

/* ------------------------------------------------------------------ ELF segments */
static u64 p0_vaddr, p0_filesz, p0_memsz;
static u64 p1_vaddr, p1_filesz, p1_memsz;
static u64 elf_shoff;
static u16 elf_shentsize, elf_shnum;

static int inspect_elf_segments(void)
{
    u8 eh[64];
    puts_("== cineprobe: elf_segments\n");
    if (!safe_read_va(appfw_base, 0, eh, 64)) {
        puts_("!! failed to read appFw.so ELF header\n");
        identity_problems++;
        return 0;
    }
    if (eh[0] != 0x7f || eh[1] != 'E' || eh[2] != 'L' || eh[3] != 'F' || eh[4] != 2 || rd_u16(eh + 18) != 183) {
        puts_("!! appFw.so is not ELF64 AArch64\n");
        identity_problems++;
        return 0;
    }
    u64 e_phoff = rd_u64(eh + 32);
    elf_shoff = rd_u64(eh + 40);
    u16 e_phentsize = rd_u16(eh + 54);
    u16 e_phnum = rd_u16(eh + 56);
    elf_shentsize = rd_u16(eh + 58);
    elf_shnum = rd_u16(eh + 60);

    puts_("appfw_base "); putaddr(appfw_base);
    puts_(" e_phnum "); putnum(e_phnum);
    puts_(" e_shnum "); putnum(elf_shnum); puts_("\n");

    p0_vaddr = p0_filesz = p0_memsz = 0;
    p1_vaddr = p1_filesz = p1_memsz = 0;
    int load_idx = 0;
    for (u16 i = 0; i < e_phnum && i < 32; i++) {
        u8 ph[56];
        if (e_phentsize < 56 || !safe_read_va(appfw_base, e_phoff + (u64)i * e_phentsize, ph, 56)) break;
        u32 p_type = rd_u32(ph);
        u32 p_flags = rd_u32(ph + 4);
        u64 p_off = rd_u64(ph + 8);
        u64 p_va = rd_u64(ph + 16);
        u64 p_fsz = rd_u64(ph + 32);
        u64 p_msz = rd_u64(ph + 40);
        if (p_type == 1 /* PT_LOAD */ || p_type == 2 /* PT_DYNAMIC */) {
            puts_("phdr idx "); putnum(i);
            puts_(" type "); putnum(p_type);
            puts_(" flags "); putaddr(p_flags);
            puts_(" off "); putaddr(p_off);
            puts_(" va "); putaddr(p_va);
            puts_(" filesz "); putaddr(p_fsz);
            puts_(" memsz "); putaddr(p_msz); puts_("\n");
        }
        if (p_type == 1) {
            if (load_idx == 0) { p0_vaddr = p_va; p0_filesz = p_fsz; p0_memsz = p_msz; }
            else if (load_idx == 1) { p1_vaddr = p_va; p1_filesz = p_fsz; p1_memsz = p_msz; }
            load_idx++;
        }
    }

    u64 span_hi = appfw_base + (p1_vaddr + p1_memsz + 0x200000UL);
    for (u32 i = 0; i < n_vmas; i++) {
        const struct vma_entry *v = &vmas[i];
        if (v->hi <= appfw_base || v->lo >= span_hi) continue;
        puts_("vma "); putaddr(v->lo - appfw_base);
        puts_("-"); putaddr(v->hi - appfw_base);
        puts_(" ");
        put(v->perms, 4);
        puts_(" foff "); putaddr(v->foff);
        puts_(" ");
        if (v->name_len) put(maps + v->name_off, v->name_len);
        else puts_("[anon]");
        puts_("\n");
    }
    return p0_filesz > 0;
}

/* ------------------------------------------------------------------ .dynsym matching */
static const char *const sym_needles[] = {
    "shutter",
    "angle",
    "cine_ei",
    "cineei",
    "base_iso",
    "baseiso",
    "iso_ei",
    "exposure_index",
    "log_shoot",
    "select_lut",
    "embed_lut",
    "flexible_iso",
    "flicker",
    "frame_rate",
    "framerate",
    "feature_manager",
    "product_model",
    "product_concept",
    "haita",
    "system_mode",
    "process_input_event",
};

static int match_sym_keywords(const char *name)
{
    for (u64 i = 0; i < sizeof sym_needles / sizeof sym_needles[0]; i++) {
        if (str_contains_ci(name, sym_needles[i])) return 1;
    }
    return 0;
}

static void inspect_dynsym(void)
{
    puts_("== cineprobe: dynsym_matches\n");
    i64 fd = sys_open(appfw_path, F_RDONLY, 0);
    if (fd < 0) {
        puts_("!! open appFw.so for dynsym failed "); putnum(fd); puts_("\n");
        return;
    }
    u64 dyn_off = 0, dyn_sz = 0, str_off = 0, str_sz = 0;
    u32 dyn_link = 0;
    for (u16 i = 0; i < elf_shnum && i < 256; i++) {
        u8 sh[64];
        if (elf_shentsize < 64 || sys_pread64((int)fd, sh, 64, elf_shoff + (u64)i * elf_shentsize) != 64) break;
        u32 sh_type = rd_u32(sh + 4);
        if (sh_type == 11 /* SHT_DYNSYM */) {
            dyn_off = rd_u64(sh + 24);
            dyn_sz = rd_u64(sh + 32);
            dyn_link = rd_u32(sh + 40);
            break;
        }
    }
    if (!dyn_off || !dyn_sz || dyn_link >= elf_shnum) {
        puts_("!! SHT_DYNSYM not found\n");
        sys_close((int)fd);
        return;
    }
    {
        u8 sh[64];
        if (sys_pread64((int)fd, sh, 64, elf_shoff + (u64)dyn_link * elf_shentsize) == 64) {
            str_off = rd_u64(sh + 24);
            str_sz = rd_u64(sh + 32);
        }
    }
    if (!str_off || !str_sz) {
        puts_("!! .dynstr not found\n");
        sys_close((int)fd);
        return;
    }

    static char str_cache[16384];
    u64 cache_off = (u64)-1;
    u64 cache_len = 0;

    u32 total_syms = (u32)(dyn_sz / 24);
    u32 matched = 0;
    u32 code_dumped = 0;
    u32 sym_idx = 0;

    while (sym_idx < total_syms && matched < 450) {
        u32 batch = total_syms - sym_idx;
        if (batch > (u32)(sizeof iobuf / 24)) batch = (u32)(sizeof iobuf / 24);
        u64 bytes = (u64)batch * 24;
        if (sys_pread64((int)fd, iobuf, bytes, dyn_off + (u64)sym_idx * 24) != (i64)bytes) break;

        for (u32 b = 0; b < batch && matched < 450; b++) {
            const u8 *ent = iobuf + (u64)b * 24;
            u32 st_name = rd_u32(ent);
            u8 st_info = ent[4];
            u16 st_shndx = rd_u16(ent + 6);
            u64 st_val = rd_u64(ent + 8);
            u64 st_sz = rd_u64(ent + 16);
            if (!st_name || (u64)st_name >= str_sz) continue;

            if (cache_off == (u64)-1 || (u64)st_name < cache_off || (u64)st_name + 256 > cache_off + cache_len) {
                u64 new_off = (u64)st_name;
                u64 want = str_sz - new_off;
                if (want > sizeof str_cache) want = sizeof str_cache;
                i64 rd = sys_pread64((int)fd, str_cache, want, str_off + new_off);
                if (rd <= 0) continue;
                cache_off = new_off;
                cache_len = (u64)rd;
            }
            u64 rel = (u64)st_name - cache_off;
            char name[256];
            u64 k = 0;
            while (k + 1 < sizeof name && rel + k < cache_len && str_cache[rel + k]) {
                name[k] = str_cache[rel + k];
                k++;
            }
            name[k] = 0;
            if (!name[0] || !match_sym_keywords(name)) continue;

            matched++;
            puts_("sym "); putaddr(st_val);
            puts_(" "); putnum((i64)st_sz);
            puts_(" "); putaddr(st_info);
            puts_(" "); putnum(st_shndx);
            puts_(" "); puts_(name); puts_("\n");

            if ((st_info & 0xfU) == 2U && st_shndx != 0 && st_val >= 0x1000UL && st_val + 64 <= p0_filesz && code_dumped < 100) {
                u8 cbuf[64];
                if (safe_read_va(appfw_base, st_val, cbuf, 64)) {
                    puts_("sym_code "); putaddr(st_val); puts_(" "); puthex(cbuf, 64); puts_("\n");
                    code_dumped++;
                }
            }
        }
        sym_idx += batch;
    }
    puts_("dynsym_total "); putnum(total_syms); puts_(" matched "); putnum(matched); puts_("\n");
    sys_close((int)fd);
}

/* ------------------------------------------------------------------ rodata strings & AArch64 xrefs */
static const char *const ro_tokens[] = {
    "SHUTTER_ANGLE",
    "MODE_SHUTTER",
    "shutter_angle",
    "CINE_EI",
    "BASE_ISO",
    "LOG_SHOOTING",
    "SELECT_LUT",
    "EMBED_LUT",
    "FLICKER_SCAN",
    "MOVIE_SHUTTER",
};

static u64 xref_targets[MAX_XREF_TARGETS];
static u32 n_xref_targets;
static u64 page_bloom[16]; /* 1024-bit page filter */

static void add_xref_target(u64 va)
{
    for (u32 i = 0; i < n_xref_targets; i++) if (xref_targets[i] == va) return;
    if (n_xref_targets < MAX_XREF_TARGETS) {
        xref_targets[n_xref_targets++] = va;
        u64 bit = (va >> 12) & 1023UL;
        page_bloom[bit >> 6] |= (1ULL << (bit & 63));
    }
}

static int page_maybe_hit(u64 page_va)
{
    u64 bit = (page_va >> 12) & 1023UL;
    return (int)((page_bloom[bit >> 6] >> (bit & 63)) & 1ULL);
}

static u64 ram_xrefs[MAX_RAM_XREFS];
static u32 n_ram_xrefs;

static void record_ram_xref(u64 ram_va, u64 from_pc)
{
    if (ram_va < p1_vaddr || ram_va >= p1_vaddr + p1_memsz) return;
    for (u32 i = 0; i < n_ram_xrefs; i++) if (ram_xrefs[i] == ram_va) return;
    if (n_ram_xrefs >= MAX_RAM_XREFS) return;
    ram_xrefs[n_ram_xrefs++] = ram_va;
    u8 rbuf[64];
    u64 aligned = ram_va & ~7ULL;
    if (safe_read_va(appfw_base, aligned, rbuf, 64)) {
        puts_("xref_ram va="); putaddr(ram_va);
        puts_(" aligned="); putaddr(aligned);
        puts_(" from_pc="); putaddr(from_pc);
        puts_(" hex="); puthex(rbuf, 64); puts_("\n");
    } else {
        puts_("xref_ram va="); putaddr(ram_va);
        puts_(" from_pc="); putaddr(from_pc);
        puts_(" UNMAPPED\n");
    }
}

static int decode_adrp(u32 insn, u64 pc, u32 *rd_out, u64 *page_out)
{
    if ((insn & 0x9f000000U) != 0x90000000U) return 0;
    u32 rd = insn & 31U;
    if (rd == 31U) return 0;
    u32 immlo = (insn >> 29) & 3U;
    u32 immhi = (insn >> 5) & 0x7ffffU;
    u32 imm21 = (immhi << 2) | immlo;
    i32 s_imm = (i32)(imm21 << 11) >> 11;
    *rd_out = rd;
    *page_out = (pc & ~0xfffUL) + (u64)((i64)s_imm << 12);
    return 1;
}

static int decode_page_off_pair(u32 i2, u32 expected_rn, u64 page_va, u64 *ea_out)
{
    if ((i2 & 0xffc00000U) == 0x91000000U) {
        u32 rn = (i2 >> 5) & 31U;
        if (rn == expected_rn) {
            *ea_out = page_va + ((i2 >> 10) & 0xfffU);
            return 1;
        }
    } else if ((i2 & 0x3f000000U) == 0x39000000U) {
        u32 rn = (i2 >> 5) & 31U;
        if (rn == expected_rn) {
            u32 sz = (i2 >> 30) & 3U;
            u64 imm12 = (i2 >> 10) & 0xfffU;
            *ea_out = page_va + (imm12 << sz);
            return 1;
        }
    }
    return 0;
}

static void scan_rodata_and_xrefs(void)
{
    puts_("== cineprobe: rodata_strings_and_xrefs\n");
    n_xref_targets = 0;
    n_ram_xrefs = 0;
    for (int i = 0; i < 16; i++) page_bloom[i] = 0;

    const u64 chunk = 16384;
    const u64 overlap = 64;
    u64 off = 0;
    while (off < p0_filesz && n_xref_targets < 48) {
        u64 rlen = p0_filesz - off;
        if (rlen > chunk + overlap) rlen = chunk + overlap;
        if (rlen < 16) break;
        if (!safe_read_va(appfw_base, off, scanbuf, (u32)rlen)) break;

        u64 limit = (rlen > chunk) ? chunk : rlen;
        for (u64 i = 0; i < limit && n_xref_targets < 48; i++) {
            for (u64 t = 0; t < sizeof ro_tokens / sizeof ro_tokens[0]; t++) {
                const char *tok = ro_tokens[t];
                u64 tlen = slen(tok);
                if (i + tlen > rlen) continue;
                if (!same(scanbuf + i, (const u8 *)tok, tlen)) continue;

                /* Walk back up to 64 bytes for start of C-string if null-terminated nearby */
                u64 start = i;
                u64 back = 0;
                while (start > 0 && back < 64 && scanbuf[start - 1] >= 0x20 && scanbuf[start - 1] < 0x7f) {
                    start--;
                    back++;
                }
                u64 str_va = off + start;
                if (start > 0 && scanbuf[start - 1] == 0) {
                    char preview[96];
                    u64 pk = 0;
                    while (pk + 1 < sizeof preview && start + pk < rlen && scanbuf[start + pk] >= 0x20 && scanbuf[start + pk] < 0x7f) {
                        preview[pk] = (char)scanbuf[start + pk];
                        pk++;
                    }
                    preview[pk] = 0;
                    if (start + pk < rlen && scanbuf[start + pk] == 0) {
                        add_xref_target(str_va);
                        puts_("str "); putaddr(str_va); puts_(" "); puts_(preview); puts_("\n");
                    }
                }
                i += tlen - 1;
                break;
            }
        }
        off += chunk;
    }

#if defined(BODY_A7S3)
    for (u64 i = 0; i < sizeof a7s3_extra_xref_targets / sizeof a7s3_extra_xref_targets[0]; i++) {
        add_xref_target(a7s3_extra_xref_targets[i]);
    }
#endif

    puts_("xref_targets "); putnum(n_xref_targets); puts_("\n");
    if (!n_xref_targets) return;

    u32 xref_hits = 0;
    u64 pc_off = 0;
    while (pc_off + 20 <= p0_filesz && xref_hits < 200) {
        u64 rlen = p0_filesz - pc_off;
        if (rlen > chunk + 16) rlen = chunk + 16;
        if (rlen < 20) break;
        if (!safe_read_va(appfw_base, pc_off, scanbuf, (u32)rlen)) break;

        u64 limit = (rlen > chunk) ? chunk : (rlen - 16);
        for (u64 i = 0; i < limit && xref_hits < 200; i += 4) {
            u32 insn = rd_u32(scanbuf + i);
            u32 rd = 0;
            u64 page_va = 0;
            u64 pc = pc_off + i;
            if (!decode_adrp(insn, pc, &rd, &page_va)) continue;
            if (!page_maybe_hit(page_va)) continue;

            for (u32 k = 1; k <= 4 && i + (u64)k * 4 + 4 <= rlen; k++) {
                u32 i2 = rd_u32(scanbuf + i + (u64)k * 4);
                u64 ea = 0;
                if (!decode_page_off_pair(i2, rd, page_va, &ea)) continue;

                int matched_target = 0;
                for (u32 t = 0; t < n_xref_targets; t++) {
                    if (xref_targets[t] == ea) { matched_target = 1; break; }
                }
                if (!matched_target) continue;

                xref_hits++;
                u64 win_va = (pc >= 32) ? (pc - 32) : 0;
                u8 wbuf[96];
                if (safe_read_va(appfw_base, win_va, wbuf, 96)) {
                    puts_("xref target="); putaddr(ea);
                    puts_(" pc="); putaddr(pc);
                    puts_(" win_va="); putaddr(win_va);
                    puts_(" hex="); puthex(wbuf, 96); puts_("\n");

                    /* Also inspect any PT_LOAD[1] / .bss ADRP+ADD/LDR/STR inside this 96B window */
                    for (u32 wi = 0; wi + 20 <= 96; wi += 4) {
                        u32 w_insn = rd_u32(wbuf + wi);
                        u32 wrd = 0;
                        u64 wpage = 0;
                        u64 wpc = win_va + wi;
                        if (!decode_adrp(w_insn, wpc, &wrd, &wpage)) continue;
                        for (u32 wk = 1; wk <= 4 && wi + wk * 4 + 4 <= 96; wk++) {
                            u32 wi2 = rd_u32(wbuf + wi + wk * 4);
                            u64 wea = 0;
                            if (decode_page_off_pair(wi2, wrd, wpage, &wea)) {
                                record_ram_xref(wea, wpc);
                                break;
                            }
                        }
                    }
                }
                break;
            }
        }
        pc_off += chunk;
    }
    puts_("xref_hits "); putnum(xref_hits); puts_(" ram_xrefs "); putnum(n_ram_xrefs); puts_("\n");
}

/* ------------------------------------------------------------------ targeted windows & RW hashes */
static void inspect_targeted_windows(void)
{
    puts_("== cineprobe: targeted_windows\n");
    static u8 wbuf[1024];
    for (u64 i = 0; i < sizeof targeted_windows / sizeof targeted_windows[0]; i++) {
        const struct target_win *w = &targeted_windows[i];
        u32 rlen = w->len;
        if (rlen > sizeof wbuf) rlen = sizeof wbuf;
        puts_("win "); puts_(w->name);
        puts_(" "); putaddr(w->va);
        puts_(" len "); putnum(rlen);
        if (safe_read_va(appfw_base, w->va, wbuf, rlen)) {
            puts_(" hex "); puthex(wbuf, rlen); puts_("\n");
        } else {
            puts_(" UNMAPPED\n");
        }
    }
}

static void inspect_rw_page_hashes(void)
{
    puts_("== cineprobe: rw_page_hashes\n");
    if (!p1_memsz) {
        puts_("rwpages 0\n");
        return;
    }
    static u8 pbuf[4096];
    u64 start = p1_vaddr & ~0xfffUL;
    u64 end = (p1_vaddr + p1_memsz + 0xfffUL) & ~0xfffUL;
    u32 emitted = 0;
    for (u64 rel = start; rel < end && emitted < 4096; rel += 4096) {
        if (!safe_read_va(appfw_base, rel, pbuf, 4096)) continue;
        int nonzero = 0;
        for (u32 k = 0; k < 4096; k += 8) {
            if (rd_u64(pbuf + k) != 0) { nonzero = 1; break; }
        }
        if (!nonzero) continue;
        u64 fnv = 0xcbf29ce484222325ULL;
        for (u32 k = 0; k < 4096; k++) {
            fnv ^= (u64)pbuf[k];
            fnv *= 0x100000001b3ULL;
        }
        puts_("rwpage "); putaddr(rel); puts_(" "); puthex64_pad(fnv); puts_("\n");
        emitted++;
    }
    puts_("rwpages_nonzero "); putnum(emitted); puts_("\n");
}

/* ------------------------------------------------------------------ coprocessor read-only probe */
extern u64 cam_dmm_alloc(u32 size, u32 *handle) __asm__("_Z9dmm_allocjPj");
extern u64 cam_dmm_free(u32 handle) __asm__("_Z8dmm_freej");
extern u32 sen_dma_transfer(u32 dir, u64 src, u64 dst, u32 size);

#define RAM_LO 0x400000000UL
#define RAM_HI 0x500000000UL

static const u8 *cp_buf;
static u64 cp_phys;
static int cp_ok;

static int cp_page(u32 page)
{
    if (!cp_ok) return 0;
    if ((page & 0xfffU) || page < CP_LO || page >= CP_HI) {
        puts_("!! coprocessor address outside allowed range\n");
        return 0;
    }
    u32 r = sen_dma_transfer(0, page, cp_phys, CP_PAGE);
    if (r) {
        puts_("!! transfer failed "); putnum(r); puts_(" at "); putaddr(page); puts_("\n");
        cp_ok = 0;
        return 0;
    }
    return 1;
}

static void inspect_coprocessor(void)
{
    u32 handle = 0;
    puts_("== coprocessor memory, read-only\n");
    cp_phys = cam_dmm_alloc(CP_PAGE, &handle);
    if (!cp_phys) {
        puts_("!! buffer allocation failed; no coprocessor reads\n");
        identity_problems++;
        return;
    }
    puts_("buffer physical "); putaddr(cp_phys); puts_(" handle "); putnum(handle); puts_("\n");
    if ((cp_phys & 0x3fUL) || cp_phys < RAM_LO || cp_phys + CP_PAGE > RAM_HI) {
        puts_("!! buffer address not usable; no coprocessor reads\n");
        cam_dmm_free(handle);
        identity_problems++;
        return;
    }
    i64 fd = sys_open("/dev/mem", F_RDONLY_SYNC, 0);
    if (fd < 0) {
        puts_("!! /dev/mem open failed "); putnum(fd); puts_("\n");
        cam_dmm_free(handle);
        identity_problems++;
        return;
    }
    u64 lead = cp_phys & 0xfffUL;
    u64 maplen = (lead + CP_PAGE + 0xfffUL) & ~0xfffUL;
    i64 m = sys_mmap_ro((int)fd, maplen, cp_phys - lead);
    if (m == -1) {
        puts_("!! mmap of coprocessor buffer failed\n");
        sys_close((int)fd);
        cam_dmm_free(handle);
        identity_problems++;
        return;
    }
    cp_buf = (const u8 *)m + lead;
    cp_ok = 1;

    puts_("== identity: coprocessor code pages\n");
    for (u64 i = 0; i < sizeof id_pages / sizeof id_pages[0] && cp_ok; i++) {
        puts_("page "); putaddr(id_pages[i].address);
        if (!cp_page(id_pages[i].address)) { identity_problems++; break; }
        struct sha s;
        u8 dg[32];
        sha_init(&s);
        sha_add(&s, cp_buf, CP_PAGE);
        sha_end(&s, dg);
        int ok = same(dg, id_pages[i].sha256, 32);
        puts_(" sha256 "); puthex(dg, 32);
        puts_(ok ? "  SAME as the " FW_STR " update\n" : "  DIFFERS from the " FW_STR " update\n");
        if (!ok) identity_problems++;
    }

    puts_("== cineprobe: coprocessor_state\n");
    for (u64 i = 0; i < sizeof cp_probe_ranges / sizeof cp_probe_ranges[0] && cp_ok; i++) {
        for (u32 p = 0; p < cp_probe_ranges[i].pages && cp_ok; p++) {
            u32 addr = cp_probe_ranges[i].address + p * CP_PAGE;
            if (!cp_page(addr)) { identity_problems++; break; }
            puts_("cppage "); puts_(cp_probe_ranges[i].name);
            puts_(" "); putaddr(addr);
            puts_(" "); puthex(cp_buf, CP_PAGE); puts_("\n");
        }
    }

    sys_munmap((void *)m, maplen);
    sys_close((int)fd);
    cam_dmm_free(handle);
}

/* ------------------------------------------------------------------ entrypoint */
static void run(void)
{
    i64 fd = sys_open(RESULT_PATH, F_NEW, 0600);
    if (fd < 0) return;
    out_fd = (int)fd;
    identity_problems = 0;

    puts_(PROBE_HEADER);
    copy_file("/proc/version", FILE_CAP);
    copy_file("/proc/cmdline", FILE_CAP);
    maps_len = read_all("/proc/self/maps", maps, sizeof maps);
    puts_("== file /proc/self/maps\n");
    put(maps, maps_len);
    puts_("\n== end "); putnum((i64)maps_len); puts_(" bytes\n");

    parse_vmas();
    pm_ro_fd = (int)sys_open("/proc/self/mem", F_RDONLY, 0);
    if (pm_ro_fd < 0) {
        puts_("!! /proc/self/mem open failed "); putnum(pm_ro_fd); puts_("\n");
        identity_problems++;
    }

    int appfw_ok = verify_file_identity();
    if (!appfw_ok || pm_ro_fd < 0) {
        puts_("!! /appFw.so identity failed; skipping appFw inspection\n");
    } else if (inspect_elf_segments()) {
        inspect_dynsym();
        scan_rodata_and_xrefs();
        inspect_targeted_windows();
        inspect_rw_page_hashes();
    }

    if (pm_ro_fd >= 0) {
        sys_close(pm_ro_fd);
        pm_ro_fd = -1;
    }

    inspect_coprocessor();

    puts_("== summary\nidentity_problems: "); putnum(identity_problems); puts_("\n");
    puts_(identity_problems == 0 ? "VERDICT CINEPROBE COMPLETE (read-only)\n" : "VERDICT NOT READY\n");
    puts_("== done\n");

    sys_close((int)fd);
    out_fd = -1;
}

__attribute__((constructor)) static void cineprobe_ctor(void) { run(); }
