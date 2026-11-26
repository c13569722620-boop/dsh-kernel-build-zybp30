#!/usr/bin/env python3
"""Minimal Android boot image v2 packer, matching MTK ZPD1203 stock layout.

Reproduces what `mkbootimg --header_version 2` produces for this device,
using the exact field values observed in the stock boot_a.img:

    base          0x40000000
    kernel_offset 0x00080000  -> kernel_addr  0x40080000
    ramdisk_offset 0x07c80000 -> ramdisk_addr 0x47c80000
    tags_offset   0x0bc80000  -> tags_addr    0x4bc80000
    dtb_offset    0x0bc80000  -> dtb_addr     0x4bc80000
    page_size     2048
    header_version 2
    os_version    12.0.0 / 2024-07  (raw 0x18000187)

The v2 header is 1660 bytes; the MTK variant appends 36 zero bytes after
extra_cmdline (total 1696) and stores dtb_size at 1648 and dtb_addr at 1652,
which is what this packer writes.

Usage:
  pack_boot_v2.py --kernel K --ramdisk R --dtb D --cmdline "..." -o boot.img
"""
import argparse
import struct
import sys
from pathlib import Path

PAGE = 2048

BOOT_MAGIC = b"ANDROID!"
HEADER_VERSION = 2
HEADER_SIZE = 1660          # v2 standard header size
MTK_HEADER_TOTAL = 1696     # 1660 + 36 zero padding (as seen in stock img)

# os_version encoding (AOSP mkbootimg):
#   raw = ((major << 14) | (minor << 7) | patch) << 11
#         | ((year - 2000) << 4) | month
def encode_os_version(major, minor, patch, year, month):
    return (((major << 14) | (minor << 7) | patch) << 11) | (((year - 2000) << 4) | month)

def pad(data, page=PAGE):
    rem = len(data) % page
    return data if rem == 0 else data + b"\x00" * (page - rem)

def build(kernel, ramdisk, dtb, cmdline, out,
          kernel_addr=0x40080000, ramdisk_addr=0x47c80000,
          tags_addr=0x4bc80000, dtb_addr=0x4bc80000,
          os_version_raw=None, second=b"", recovery_dtbo=b""):

    # name (16 bytes), cmdline (512), extra_cmdline (1024)
    name = b""
    cmd = cmdline.encode("utf-8")
    if len(cmd) > 512:
        raise ValueError("cmdline too long (>512)")
    extra = b""

    if os_version_raw is None:
        os_version_raw = encode_os_version(12, 0, 0, 2024, 7)

    hdr = bytearray()
    hdr += BOOT_MAGIC                                    # 0   magic
    hdr += struct.pack("<I", len(kernel))                # 8   kernel_size
    hdr += struct.pack("<I", kernel_addr)                # 12  kernel_addr
    hdr += struct.pack("<I", len(ramdisk))               # 16  ramdisk_size
    hdr += struct.pack("<I", ramdisk_addr)               # 20  ramdisk_addr
    hdr += struct.pack("<I", len(second))                # 24  second_size
    hdr += struct.pack("<I", 0)                          # 28  second_addr (stock: 0)
    hdr += struct.pack("<I", tags_addr)                  # 32  tags_addr
    hdr += struct.pack("<I", PAGE)                       # 36  page_size
    hdr += struct.pack("<I", HEADER_VERSION)             # 40  header_version
    hdr += struct.pack("<I", os_version_raw)             # 44  os_version
    hdr += name.ljust(16, b"\x00")                       # 48  name[16]
    hdr += cmd.ljust(512, b"\x00")                       # 64  cmdline[512]
    hdr += struct.pack("<I", 0)                          # 576 id[8] (part 1)
    hdr += struct.pack("<I", 0)                          # 580 id[8] (part 2)
    hdr += extra.ljust(1024, b"\x00")                    # 584 extra_cmdline[1024]

    # --- position: 1608 ---
    hdr += struct.pack("<I", 0)                          # 1608 recovery_dtbo_size
    hdr += struct.pack("<Q", 0)                          # 1612 recovery_dtbo_offset
    hdr += struct.pack("<I", 0)                          # 1620 (stock: 0)
    hdr += struct.pack("<I", 0)                          # 1624
    hdr += struct.pack("<I", 0)                          # 1628
    hdr += struct.pack("<I", 0)                          # 1632
    hdr += struct.pack("<I", 0)                          # 1636
    hdr += struct.pack("<I", 0)                          # 1640
    hdr += struct.pack("<I", HEADER_SIZE)                # 1644 header_size (MTK puts it here)
    hdr += struct.pack("<I", len(dtb))                   # 1648 dtb_size
    hdr += struct.pack("<I", dtb_addr & 0xFFFFFFFF)      # 1652 dtb_addr low
    hdr += struct.pack("<I", (dtb_addr >> 32) & 0xFFFFFFFF)  # 1656 dtb_addr high

    hdr = bytes(hdr)
    assert len(hdr) == HEADER_SIZE, f"header {len(hdr)} != {HEADER_SIZE}"

    # MTK pads header to 1696 with zeros
    hdr_padded = hdr + b"\x00" * (MTK_HEADER_TOTAL - HEADER_SIZE)

    # assemble: header page + kernel + ramdisk + second + dtb
    outbuf = bytearray()
    outbuf += hdr_padded
    outbuf += b"\x00" * (PAGE - (len(outbuf) % PAGE)) if len(outbuf) % PAGE else b""
    assert len(outbuf) == PAGE, f"header block should be one page, got {len(outbuf)}"

    outbuf += pad(kernel)
    outbuf += pad(ramdisk)
    if second:
        outbuf += pad(second)
    outbuf += pad(dtb)

    Path(out).write_bytes(bytes(outbuf))
    return len(outbuf)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--ramdisk", required=True)
    ap.add_argument("--dtb", required=True)
    ap.add_argument("--cmdline", default="bootopt=64S3,32N2,64N2 buildvariant=user")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--os-version-raw", type=lambda x: int(x, 0), default=None)
    args = ap.parse_args()

    k = Path(args.kernel).read_bytes()
    r = Path(args.ramdisk).read_bytes()
    d = Path(args.dtb).read_bytes()

    print(f"kernel : {len(k):>12,} bytes")
    print(f"ramdisk: {len(r):>12,} bytes")
    print(f"dtb    : {len(d):>12,} bytes")
    print(f"cmdline: {args.cmdline!r}")

    total = build(k, r, d, args.cmdline, args.out,
                  os_version_raw=args.os_version_raw)
    print(f"\nwrote {args.out}  ({total:,} bytes = {total/1024/1024:.2f} MB)")

if __name__ == "__main__":
    main()
