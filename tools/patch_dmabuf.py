#!/usr/bin/env python3
"""Make gralloc_fb0_bridge.c build against glibc (Ubuntu) headers.

Two problems show up when compiling the upstream bridge on Ubuntu 22.04
instead of Android's bionic:

1. <linux/dma-buf.h> there predates DMA_BUF_IOCTL_SYNC, so the identifier is
   unknown.
2. Even after defining DMA_BUF_IOCTL_SYNC = _IOW(...), `_IOW` itself comes
   from <sys/ioctl.h>, which the file never includes -- bionic pulls it in
   indirectly, glibc does not.  Without it the macro expands to garbage and
   gcc reports "expected expression before 'struct'".

This script injects both, idempotently.
"""
import sys

DMABUF_ANCHOR = "#include <linux/dma-buf.h>"
IOCTL_INCLUDE = "#include <sys/ioctl.h>"

DMABUF_BLOCK = DMABUF_ANCHOR + """
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

    changed = False

    # 1) <sys/ioctl.h> for _IOW
    if "\n#include <sys/ioctl.h>" not in src and "include <sys/ioctl.h>" not in src:
        if DMABUF_ANCHOR in src:
            src = src.replace(DMABUF_ANCHOR, IOCTL_INCLUDE + "\n" + DMABUF_ANCHOR, 1)
            changed = True
            print("[+] added #include <sys/ioctl.h>")
        else:
            print("[x] could not find dma-buf.h anchor", file=sys.stderr)
            return 1
    else:
        print("[i] <sys/ioctl.h> already included")

    # 2) DMA_BUF_IOCTL_SYNC fallback definitions
    if "#define DMA_BUF_IOCTL_SYNC" in src:
        print("[i] DMA_BUF_IOCTL_SYNC already defined")
    else:
        # re-read anchor position (it may have shifted)
        anchor = "#include <sys/ioctl.h>\n" + DMABUF_ANCHOR
        use = anchor if anchor in src else DMABUF_ANCHOR
        block = (("#include <sys/ioctl.h>\n" + DMABUF_BLOCK) if use == anchor
                 else DMABUF_BLOCK)
        src = src.replace(use, block, 1)
        changed = True
        print("[+] injected DMA_BUF_IOCTL_SYNC definitions")

    if changed:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(src)
        print(f"[ok] patched {path}")
    else:
        print("[i] nothing to change")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
