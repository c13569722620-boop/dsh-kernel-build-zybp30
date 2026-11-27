/*
 * Zero-dependency AArch64 gralloc.default.so bridge for MT6768 Linux 5.10
 * simple-framebuffer (/dev/graphics/fb0) + vendor.hwcomposer-2-1 HWC2OnFbAdapter.
 *
 * HWC2OnFbAdapter calls fbdev->post(fbdev, buffer_handle_t) with DMA-BUF
 * native_handle_t buffers allocated by vendor.gralloc-4-0 (ARM Mali Valhall).
 * Stock gralloc.default.so rejects foreign handles with "invalid gralloc handle".
 * This minimal HAL module locates the valid pixel DMA-BUF fd in hnd->data[],
 * synchronizes CPU read coherency via DMA_BUF_IOCTL_SYNC, and blits frames
 * directly into the mmap'd simplefb framebuffer with R<->B swap when fb0 is a8r8g8b8.
 */

#include <arm_neon.h>
#include <asm/unistd.h>
#include <fcntl.h>
#include <linux/dma-buf.h>
#include <linux/fb.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/mman.h>

#define HARDWARE_MODULE_TAG 0x48574d54U /* "HWMT" */
#define HARDWARE_DEVICE_TAG 0x48574454U /* "HWDT" */
#define MAX_HANDLES_SCAN 8

typedef struct {
    int version;
    int numFds;
    int numInts;
    int data[];
} bridge_native_handle_t;

struct hw_module_t;
struct hw_device_t;

typedef struct {
    int (*open)(const struct hw_module_t *module, const char *id,
                struct hw_device_t **device);
} hw_module_methods_t;

typedef struct hw_module_t {
    uint32_t tag;
    uint16_t module_api_version;
    uint16_t hal_api_version;
    const char *id;
    const char *name;
    const char *author;
    hw_module_methods_t *methods;
    void *dso;
    uint64_t reserved[32 - 7];
    uint8_t extra_pad[440]; /* matches stock gralloc.default.so HMI 688B size */
} hw_module_t;

/* Verify offset invariants matching AOSP / vendor_a gralloc.default.so */
typedef char chk_id_off[(offsetof(hw_module_t, id) == 0x08) ? 1 : -1];
typedef char chk_meth_off[(offsetof(hw_module_t, methods) == 0x20) ? 1 : -1];

typedef struct hw_device_t {
    uint32_t tag;
    uint32_t version;
    struct hw_module_t *module;
    uint64_t reserved[12];
    int (*close)(struct hw_device_t *device);
} hw_device_t;

typedef struct framebuffer_device_t {
    hw_device_t common;
    const uint32_t flags;
    const uint32_t width;
    const uint32_t height;
    const int stride;
    const int format;
    const float xdpi;
    const float ydpi;
    const float fps;
    const int minSwapInterval;
    const int maxSwapInterval;
    const int numFramebuffers;
    int reserved[7];
    int (*setSwapInterval)(struct framebuffer_device_t *window, int interval);
    int (*setUpdateRect)(struct framebuffer_device_t *window, int left, int top,
                         int width, int height);
    int (*post)(struct framebuffer_device_t *dev, const bridge_native_handle_t *buffer);
    int (*compositionComplete)(struct framebuffer_device_t *dev);
    void (*dump)(struct framebuffer_device_t *dev, char *buff, int buff_len);
    int (*enableScreen)(struct framebuffer_device_t *dev, int enable);
    void *reserved_proc[6];
} framebuffer_device_t;

typedef char chk_close_off[(offsetof(hw_device_t, close) == 0x70) ? 1 : -1];
typedef char chk_w_off[(offsetof(framebuffer_device_t, width) == 0x7c) ? 1 : -1];
typedef char chk_stride_off[(offsetof(framebuffer_device_t, stride) == 0x84) ? 1 : -1];
typedef char chk_swap_off[(offsetof(framebuffer_device_t, setSwapInterval) == 0xc0) ? 1 : -1];
typedef char chk_post_off[(offsetof(framebuffer_device_t, post) == 0xd0) ? 1 : -1];
typedef char chk_fbdev_sz[(sizeof(framebuffer_device_t) == 0x120) ? 1 : -1];

static inline long sc6(long nr, long a0, long a1, long a2, long a3, long a4, long a5) {
    register long x8 __asm__("x8") = nr;
    register long x0 __asm__("x0") = a0;
    register long x1 __asm__("x1") = a1;
    register long x2 __asm__("x2") = a2;
    register long x3 __asm__("x3") = a3;
    register long x4 __asm__("x4") = a4;
    register long x5 __asm__("x5") = a5;
    __asm__ volatile("svc #0"
                     : "+r"(x0)
                     : "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5), "r"(x8)
                     : "memory", "cc");
    return x0;
}

static inline int sys_open(const char *path, int flags) {
    return (int)sc6(__NR_openat, AT_FDCWD, (long)path, flags, 0, 0, 0);
}

static inline int sys_close(int fd) {
    return (int)sc6(__NR_close, fd, 0, 0, 0, 0, 0);
}

static inline int sys_ioctl(int fd, unsigned long req, void *arg) {
    return (int)sc6(__NR_ioctl, fd, (long)req, (long)arg, 0, 0, 0);
}

static inline void *sys_mmap(void *addr, size_t len, int prot, int flags, int fd, long off) {
    return (void *)sc6(__NR_mmap, (long)addr, (long)len, prot, flags, fd, off);
}

static inline int sys_munmap(void *addr, size_t len) {
    return (int)sc6(__NR_munmap, (long)addr, (long)len, 0, 0, 0, 0);
}

static inline long sys_lseek(int fd, long offset, int whence) {
    return sc6(__NR_lseek, fd, offset, whence, 0, 0, 0);
}

static inline long sys_write(int fd, const void *buf, size_t count) {
    return sc6(__NR_write, fd, (long)buf, (long)count, 0, 0, 0);
}

static void b_memset(void *dst, uint8_t val, size_t n) {
    volatile uint8_t *p = (volatile uint8_t *)dst;
    for (size_t i = 0; i < n; i++) p[i] = val;
}

static int b_strcmp(const char *a, const char *b) {
    while (*a && (*a == *b)) {
        a++;
        b++;
    }
    return (unsigned char)*a - (unsigned char)*b;
}

static size_t append_cstr(char *buf, size_t pos, size_t cap, const char *s) {
    while (*s && pos + 1 < cap) {
        buf[pos++] = *s++;
    }
    buf[pos] = '\0';
    return pos;
}

static size_t append_dec(char *buf, size_t pos, size_t cap, long v) {
    unsigned long uv;
    if (v < 0) {
        if (pos + 1 < cap) buf[pos++] = '-';
        uv = (unsigned long)(-(v + 1)) + 1UL;
    } else {
        uv = (unsigned long)v;
    }
    char d[24];
    int n = 0;
    if (uv == 0) {
        d[n++] = '0';
    } else {
        while (uv > 0 && n < 24) {
            d[n++] = (char)('0' + (uv % 10));
            uv /= 10;
        }
    }
    while (n > 0 && pos + 1 < cap) buf[pos++] = d[--n];
    buf[pos] = '\0';
    return pos;
}

static size_t append_hex(char *buf, size_t pos, size_t cap, unsigned long v) {
    pos = append_cstr(buf, pos, cap, "0x");
    char d[16];
    int n = 0;
    if (v == 0) {
        d[n++] = '0';
    } else {
        while (v > 0 && n < 16) {
            unsigned long nib = v & 0xfUL;
            d[n++] = (nib < 10) ? (char)('0' + nib) : (char)('a' + (nib - 10));
            v >>= 4;
        }
    }
    while (n > 0 && pos + 1 < cap) buf[pos++] = d[--n];
    buf[pos] = '\0';
    return pos;
}

static void log_append(const char *s) {
    int fd = sys_open("/dev/.fb0_bridge.log", O_WRONLY | O_APPEND);
    if (fd < 0) fd = sys_open("/dev/kmsg", O_WRONLY);
    if (fd >= 0) {
        size_t len = 0;
        while (s[len]) len++;
        (void)sys_write(fd, s, len);
        sys_close(fd);
    }
}

static void klog_msg_num(const char *prefix, long v) {
    char buf[192];
    size_t pos = 0;
    pos = append_cstr(buf, pos, sizeof(buf), prefix);
    pos = append_dec(buf, pos, sizeof(buf), v);
    (void)append_cstr(buf, pos, sizeof(buf), "\n");
    log_append(buf);
}

typedef struct {
    int fb_fd;
    uint8_t *fb_mem;
    size_t fb_map_len;
    uint32_t w;
    uint32_t h;
    size_t dst_stride;
    int swap_rb;
    unsigned long post_count;
    int post_err_logged;
} fb_bridge_state_t;

static fb_bridge_state_t g_fb = { -1, NULL, 0, 0, 0, 0, 0, 0UL, 0 };
static framebuffer_device_t g_fbdev;

static int fb_close(struct hw_device_t *dev) {
    (void)dev;
    return 0;
}

static int fb_set_swap_interval(struct framebuffer_device_t *window, int interval) {
    if (interval < window->minSwapInterval || interval > window->maxSwapInterval)
        return -22;
    return 0;
}

static inline void blit_row(uint8_t *dst_row, const uint8_t *src_row, size_t copy_bytes, int swap_rb) {
    size_t off = 0;
    size_t vector_bytes = copy_bytes & ~(size_t)15;

    if (swap_rb) {
        const uint8x16_t rgba_to_bgra = {
            2, 1, 0, 3, 6, 5, 4, 7, 10, 9, 8, 11, 14, 13, 12, 15
        };
        for (; off < vector_bytes; off += 16) {
            uint8x16_t pixels = vld1q_u8(src_row + off);
            vst1q_u8(dst_row + off, vqtbl1q_u8(pixels, rgba_to_bgra));
        }
        for (; copy_bytes - off >= 4; off += 4) {
            dst_row[off] = src_row[off + 2];
            dst_row[off + 1] = src_row[off + 1];
            dst_row[off + 2] = src_row[off];
            dst_row[off + 3] = src_row[off + 3];
        }
    } else {
        for (; off < vector_bytes; off += 16) {
            vst1q_u8(dst_row + off, vld1q_u8(src_row + off));
        }
    }
    for (; off < copy_bytes; off++) {
        dst_row[off] = src_row[off];
    }
}

static int should_log_frame(unsigned long call_idx) {
    if (call_idx == 1UL || call_idx == 10UL || call_idx == 60UL || call_idx == 120UL)
        return 1;
    if (call_idx <= 3000UL && (call_idx % 300UL) == 0UL)
        return 1;
    return 0;
}

static int fb_post(struct framebuffer_device_t *dev, const bridge_native_handle_t *hnd) {
    (void)dev;
    unsigned long call_idx = ++g_fb.post_count;
    int diag_first = (call_idx == 1UL);
    int diag_sample = should_log_frame(call_idx);

    if (!g_fb.fb_mem) {
        if (!g_fb.post_err_logged) {
            g_fb.post_err_logged = 1;
            log_append("fb0-bridge: fb_post failed: fb_mem is NULL\n");
        }
        return -19;
    }
    if (!hnd || hnd->numFds <= 0) {
        if (!g_fb.post_err_logged) {
            g_fb.post_err_logged = 1;
            klog_msg_num("fb0-bridge: fb_post invalid native_handle_t count=", (long)call_idx);
        }
        return -22;
    }

    int best_fd = -1;
    size_t best_sz = 0;
    size_t min_bytes = (size_t)g_fb.w * (size_t)g_fb.h * 4;
    int scan = hnd->numFds;
    if (scan > MAX_HANDLES_SCAN) scan = MAX_HANDLES_SCAN;

    int cand_fds[MAX_HANDLES_SCAN];
    long lseek_vals[MAX_HANDLES_SCAN];
    for (int i = 0; i < scan; i++) {
        int cand = hnd->data[i];
        cand_fds[i] = cand;
        if (cand < 0) {
            lseek_vals[i] = -999;
            continue;
        }
        long s = sys_lseek(cand, 0, 2 /* SEEK_END */);
        lseek_vals[i] = s;
        if (s > 0 && (size_t)s >= best_sz) {
            best_sz = (size_t)s;
            best_fd = cand;
        } else if (best_fd < 0) {
            best_fd = cand;
        }
    }

    if (diag_first || (best_fd < 0 && !g_fb.post_err_logged)) {
        char hbuf[384];
        size_t p = 0;
        p = append_cstr(hbuf, p, sizeof(hbuf), "fb0-bridge: fb_post#");
        p = append_dec(hbuf, p, sizeof(hbuf), (long)call_idx);
        p = append_cstr(hbuf, p, sizeof(hbuf), " numFds=");
        p = append_dec(hbuf, p, sizeof(hbuf), (long)hnd->numFds);
        p = append_cstr(hbuf, p, sizeof(hbuf), " numInts=");
        p = append_dec(hbuf, p, sizeof(hbuf), (long)hnd->numInts);
        p = append_cstr(hbuf, p, sizeof(hbuf), " data=[");
        for (int i = 0; i < scan; i++) {
            if (i > 0) p = append_cstr(hbuf, p, sizeof(hbuf), ",");
            p = append_dec(hbuf, p, sizeof(hbuf), (long)cand_fds[i]);
            p = append_cstr(hbuf, p, sizeof(hbuf), "(");
            p = append_dec(hbuf, p, sizeof(hbuf), lseek_vals[i]);
            p = append_cstr(hbuf, p, sizeof(hbuf), ")");
        }
        p = append_cstr(hbuf, p, sizeof(hbuf), "] best_fd=");
        p = append_dec(hbuf, p, sizeof(hbuf), (long)best_fd);
        p = append_cstr(hbuf, p, sizeof(hbuf), " best_sz=");
        p = append_dec(hbuf, p, sizeof(hbuf), (long)best_sz);
        (void)append_cstr(hbuf, p, sizeof(hbuf), "\n");
        log_append(hbuf);
    }

    if (best_fd < 0) {
        if (!g_fb.post_err_logged) {
            g_fb.post_err_logged = 1;
            log_append("fb0-bridge: no valid DMA-BUF fd in native_handle_t\n");
        }
        return -22;
    }

    if (best_sz < min_bytes) {
        best_sz = (size_t)g_fb.h * g_fb.dst_stride;
        if (best_sz < min_bytes) best_sz = min_bytes;
    }

    struct dma_buf_sync sync_args;
    sync_args.flags = DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ;
    int sync_start_rc = sys_ioctl(best_fd, DMA_BUF_IOCTL_SYNC, &sync_args);

    void *src_map = sys_mmap(NULL, best_sz, PROT_READ, MAP_SHARED, best_fd, 0);
    if ((unsigned long)src_map >= (unsigned long)-4095UL) {
        if (!g_fb.post_err_logged) {
            char ebuf[256];
            size_t p = 0;
            g_fb.post_err_logged = 1;
            p = append_cstr(ebuf, p, sizeof(ebuf), "fb0-bridge: mmap dmabuf failed count=");
            p = append_dec(ebuf, p, sizeof(ebuf), (long)call_idx);
            p = append_cstr(ebuf, p, sizeof(ebuf), " fd=");
            p = append_dec(ebuf, p, sizeof(ebuf), (long)best_fd);
            p = append_cstr(ebuf, p, sizeof(ebuf), " sz=");
            p = append_dec(ebuf, p, sizeof(ebuf), (long)best_sz);
            p = append_cstr(ebuf, p, sizeof(ebuf), " sync_rc=");
            p = append_dec(ebuf, p, sizeof(ebuf), (long)sync_start_rc);
            p = append_cstr(ebuf, p, sizeof(ebuf), " err=");
            p = append_dec(ebuf, p, sizeof(ebuf), (long)src_map);
            (void)append_cstr(ebuf, p, sizeof(ebuf), "\n");
            log_append(ebuf);
        }
        sync_args.flags = DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ;
        (void)sys_ioctl(best_fd, DMA_BUF_IOCTL_SYNC, &sync_args);
        return -12;
    }

    size_t row_bytes = (size_t)g_fb.w * 4;
    size_t src_stride = row_bytes;
    if (best_sz == (size_t)g_fb.h * g_fb.dst_stride) {
        src_stride = g_fb.dst_stride;
    } else if ((best_sz % (size_t)g_fb.h) == 0 &&
               (best_sz / (size_t)g_fb.h) >= row_bytes &&
               (best_sz / (size_t)g_fb.h) <= row_bytes + 512) {
        src_stride = best_sz / (size_t)g_fb.h;
    }

    uint32_t px0 = 0U, px_mid = 0U;
    unsigned long rgb_nz = 0;
    if (diag_sample) {
        const uint32_t *src32 = (const uint32_t *)src_map;
        size_t total_px = best_sz / 4;
        if (total_px > 0) px0 = src32[0];
        size_t mid_idx = ((size_t)(g_fb.h / 2)) * (src_stride / 4) + (size_t)(g_fb.w / 2);
        if (mid_idx < total_px) px_mid = src32[mid_idx];
        for (size_t idx = 0; idx < total_px; idx += 1009) {
            if ((src32[idx] & 0x00ffffffU) != 0U) rgb_nz++;
        }
    }

    const uint8_t *src = (const uint8_t *)src_map;
    uint8_t *dst = g_fb.fb_mem;
    if (src_stride == g_fb.dst_stride) {
        size_t total = (size_t)g_fb.h * g_fb.dst_stride;
        if (total > g_fb.fb_map_len) total = g_fb.fb_map_len;
        blit_row(dst, src, total, g_fb.swap_rb);
    } else {
        size_t max_rows = g_fb.fb_map_len / g_fb.dst_stride;
        size_t rows = (g_fb.h < max_rows) ? g_fb.h : max_rows;
        for (size_t y = 0; y < rows; y++) {
            blit_row(dst + y * g_fb.dst_stride, src + y * src_stride, row_bytes, g_fb.swap_rb);
        }
    }

    (void)sys_munmap(src_map, best_sz);
    sync_args.flags = DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ;
    (void)sys_ioctl(best_fd, DMA_BUF_IOCTL_SYNC, &sync_args);

    if (diag_sample) {
        size_t dst_mid_off = ((size_t)(g_fb.h / 2)) * g_fb.dst_stride + ((size_t)(g_fb.w / 2)) * 4;
        uint32_t dst_mid = (dst_mid_off + 4 <= g_fb.fb_map_len)
                               ? *(const volatile uint32_t *)(const void *)(g_fb.fb_mem + dst_mid_off)
                               : 0U;
        char mbuf[320];
        size_t p = 0;
        p = append_cstr(mbuf, p, sizeof(mbuf), "fb0-bridge: fb_post#");
        p = append_dec(mbuf, p, sizeof(mbuf), (long)call_idx);
        p = append_cstr(mbuf, p, sizeof(mbuf), " fd=");
        p = append_dec(mbuf, p, sizeof(mbuf), (long)best_fd);
        p = append_cstr(mbuf, p, sizeof(mbuf), " sz=");
        p = append_dec(mbuf, p, sizeof(mbuf), (long)best_sz);
        p = append_cstr(mbuf, p, sizeof(mbuf), " src_stride=");
        p = append_dec(mbuf, p, sizeof(mbuf), (long)src_stride);
        p = append_cstr(mbuf, p, sizeof(mbuf), " sync_rc=");
        p = append_dec(mbuf, p, sizeof(mbuf), (long)sync_start_rc);
        p = append_cstr(mbuf, p, sizeof(mbuf), " px0=");
        p = append_hex(mbuf, p, sizeof(mbuf), (unsigned long)px0);
        p = append_cstr(mbuf, p, sizeof(mbuf), " px_mid=");
        p = append_hex(mbuf, p, sizeof(mbuf), (unsigned long)px_mid);
        p = append_cstr(mbuf, p, sizeof(mbuf), " rgb_nz=");
        p = append_dec(mbuf, p, sizeof(mbuf), (long)rgb_nz);
        p = append_cstr(mbuf, p, sizeof(mbuf), " dst_mid=");
        p = append_hex(mbuf, p, sizeof(mbuf), (unsigned long)dst_mid);
        (void)append_cstr(mbuf, p, sizeof(mbuf), "\n");
        log_append(mbuf);
    }
    return 0;
}

static int fb_device_open(const hw_module_t *module, const char *name,
                          hw_device_t **device) {
    if (!name || b_strcmp(name, "fb0") != 0 || !device) {
        return -22;
    }

    if (!g_fb.fb_mem) {
        int fd = sys_open("/dev/graphics/fb0", O_RDWR);
        if (fd < 0) fd = sys_open("/dev/fb0", O_RDWR);
        if (fd < 0) {
            klog_msg_num("fb0-bridge: open fb0 failed err=", fd);
            return -19;
        }

        struct fb_fix_screeninfo finfo;
        struct fb_var_screeninfo vinfo;
        b_memset(&finfo, 0, sizeof(finfo));
        b_memset(&vinfo, 0, sizeof(vinfo));

        if (sys_ioctl(fd, FBIOGET_FSCREENINFO, &finfo) < 0 ||
            sys_ioctl(fd, FBIOGET_VSCREENINFO, &vinfo) < 0) {
            log_append("fb0-bridge: ioctl FBIOGET_*SCREENINFO failed\n");
            sys_close(fd);
            return -22;
        }

        size_t map_len = (size_t)finfo.smem_len;
        if (map_len < (size_t)vinfo.yres * (size_t)finfo.line_length) {
            map_len = (size_t)vinfo.yres * (size_t)finfo.line_length;
        }
        void *mem = sys_mmap(NULL, map_len, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
        if ((unsigned long)mem >= (unsigned long)-4095UL) {
            klog_msg_num("fb0-bridge: mmap fb0 failed err=", (long)mem);
            sys_close(fd);
            return -12;
        }

        g_fb.fb_fd = fd;
        g_fb.fb_mem = (uint8_t *)mem;
        g_fb.fb_map_len = map_len;
        g_fb.w = vinfo.xres;
        g_fb.h = vinfo.yres;
        g_fb.dst_stride = (size_t)finfo.line_length;
        g_fb.swap_rb = (vinfo.red.offset != 0) ? 1 : 0;

        b_memset(&g_fbdev, 0, sizeof(g_fbdev));
        g_fbdev.common.tag = HARDWARE_DEVICE_TAG;
        g_fbdev.common.version = 0;
        g_fbdev.common.module = (hw_module_t *)(uintptr_t)module;
        g_fbdev.common.close = fb_close;

        *(uint32_t *)(uintptr_t)&g_fbdev.flags = 0;
        *(uint32_t *)(uintptr_t)&g_fbdev.width = vinfo.xres;
        *(uint32_t *)(uintptr_t)&g_fbdev.height = vinfo.yres;
        *(int *)(uintptr_t)&g_fbdev.stride = (int)(finfo.line_length / 4);
        *(int *)(uintptr_t)&g_fbdev.format = g_fb.swap_rb ? 5 : 1;
        *(float *)(uintptr_t)&g_fbdev.xdpi = 160.0f;
        *(float *)(uintptr_t)&g_fbdev.ydpi = 160.0f;
        *(float *)(uintptr_t)&g_fbdev.fps = 60.0f;
        *(int *)(uintptr_t)&g_fbdev.minSwapInterval = 1;
        *(int *)(uintptr_t)&g_fbdev.maxSwapInterval = 1;
        *(int *)(uintptr_t)&g_fbdev.numFramebuffers = 1;
        g_fbdev.setSwapInterval = fb_set_swap_interval;
        g_fbdev.setUpdateRect = NULL;
        g_fbdev.post = fb_post;

        char obuf[320];
        size_t p = 0;
        p = append_cstr(obuf, p, sizeof(obuf), "fb0-bridge: open fb0 w=");
        p = append_dec(obuf, p, sizeof(obuf), (long)g_fb.w);
        p = append_cstr(obuf, p, sizeof(obuf), " h=");
        p = append_dec(obuf, p, sizeof(obuf), (long)g_fb.h);
        p = append_cstr(obuf, p, sizeof(obuf), " dst_stride=");
        p = append_dec(obuf, p, sizeof(obuf), (long)g_fb.dst_stride);
        p = append_cstr(obuf, p, sizeof(obuf), " smem_len=");
        p = append_dec(obuf, p, sizeof(obuf), (long)finfo.smem_len);
        p = append_cstr(obuf, p, sizeof(obuf), " map_len=");
        p = append_dec(obuf, p, sizeof(obuf), (long)g_fb.fb_map_len);
        p = append_cstr(obuf, p, sizeof(obuf), " red.off=");
        p = append_dec(obuf, p, sizeof(obuf), (long)vinfo.red.offset);
        p = append_cstr(obuf, p, sizeof(obuf), " blue.off=");
        p = append_dec(obuf, p, sizeof(obuf), (long)vinfo.blue.offset);
        p = append_cstr(obuf, p, sizeof(obuf), " swap_rb=");
        p = append_dec(obuf, p, sizeof(obuf), (long)g_fb.swap_rb);
        p = append_cstr(obuf, p, sizeof(obuf), " mem=");
        p = append_hex(obuf, p, sizeof(obuf), (unsigned long)(uintptr_t)mem);
        (void)append_cstr(obuf, p, sizeof(obuf), "\n");
        log_append(obuf);
    }

    *device = &g_fbdev.common;
    return 0;
}

static hw_module_methods_t g_methods = {
    .open = fb_device_open,
};

hw_module_t HMI __attribute__((visibility("default"))) = {
    .tag = HARDWARE_MODULE_TAG,
    .module_api_version = 0x0100,
    .hal_api_version = 0x0000,
    .id = "gralloc",
    .name = "ZPD1203 SimpleFB DMA-BUF Bridge",
    .author = "MT6768-5.10",
    .methods = &g_methods,
    .dso = NULL,
};
