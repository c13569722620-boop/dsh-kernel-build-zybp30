#!/usr/bin/env python3
"""Inject DMA_BUF_IOCTL_SYNC UAPI definitions into a C source if missing.

Ubuntu 22.04 ships a <linux/dma-buf.h> that lacks the sync ioctl introduced
later upstream, which makes gralloc_fb0_bridge.c fail with
"expected expression before 'struct'".
"""
import sys

MARKER = "#include <linux/dma-buf.h>"

ADDITION = MARKER + """
#ifndef DMA_BUF_IOCTL_SYNC
struct dma_buf_sync {
\tunsigned long long flags;
};
#define DMA_BUF_SYNC_READ      (1 << 0)
#define DMA_BUF_SYNC_WRITE     (2 << 0)
#define DMA_BUF_SYNC_RW        (DMA_BUF_SYNC_READ | DMA_BUF_SYNC_WRITE)
#define DMA_BUF_SYNC_START     (0 << 2)
#define DMA_BUF_SYNC_END       (1 << 2)
#define DMA_BUF_BASE           'b'
#define DMA_BUF_IOCTL_SYNC     _IOW(DMA_BUF_BASE, 0, struct dma_buf_sync)
#endif"""


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_dmabuf.py <file.c>", file=sys.stderr)
        return 2
    path = sys.argv[1]
    with open(path, encoding="utf-8", errors="replace") as f:
        src = f.read()

    if "#define DMA_BUF_IOCTL_SYNC" in src:
        print("[i] DMA_BUF_IOCTL_SYNC already defined, nothing to do")
        return 0
    if MARKER not in src:
        print(f"[x] anchor not found: {MARKER}", file=sys.stderr)
        return 1

    src = src.replace(MARKER, ADDITION, 1)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    print("[+] injected DMA_BUF_IOCTL_SYNC definitions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
