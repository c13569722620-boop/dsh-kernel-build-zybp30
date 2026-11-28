#!/usr/bin/env python3
"""Pad a boot image to the full partition size and optionally append an AVB footer.

Why this matters for the ZPD1203 (MT6768, A/B):
  * The boot partition is exactly 33,554,432 bytes (32 MiB).
  * The stock image fills the whole partition and carries an AVB footer
    ("AVBf", 64 bytes at the end) whose original_image_size points at the
    real payload length.
  * LK (the bootloader) reads the partition by size and, on unlocked devices,
    still parses the AVB footer when present. A short image without a footer
    can leave the partition tail containing stale data from a previous flash,
    which some LK builds refuse.

This tool:
  1. computes original_image_size = current file size
  2. appends an unsigned AVB hash-footer descriptor
  3. zeros out to the full partition size

The footer we emit is the *footer struct only* (no vbmeta blob), which LK
accepts as "no verification data" and is the safe choice for an unlocked
device doing bring-up.

Usage:
  pad_boot_avb.py <boot.img> --partition-size 33554432 [--out FILE] [--no-avb]
"""
import argparse
import struct
import sys

AVB_FOOTER_MAGIC = b"AVBf"
AVB_FOOTER_VERSION_MAJOR = 1
AVB_FOOTER_VERSION_MINOR = 0
AVB_FOOTER_SIZE = 64


def make_footer(original_image_size, vbmeta_offset, vbmeta_size):
    """Build the 64-byte AvbFooter struct (big-endian)."""
    buf = bytearray()
    buf += AVB_FOOTER_MAGIC                                  # magic[4]
    buf += struct.pack(">II", AVB_FOOTER_VERSION_MAJOR,
                       AVB_FOOTER_VERSION_MINOR)             # version 8
    buf += struct.pack(">Q", original_image_size)            # 8
    buf += struct.pack(">Q", vbmeta_offset)                  # 8
    buf += struct.pack(">Q", vbmeta_size)                    # 8
    buf += b"\x00" * 28                                      # reserved[28]
    assert len(buf) == AVB_FOOTER_SIZE, len(buf)
    return bytes(buf)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--partition-size", type=int, required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-avb", action="store_true",
                    help="pad only, do not append an AVB footer")
    args = ap.parse_args()

    out_path = args.out or args.image
    data = bytearray(open(args.image, "rb").read())
    part = args.partition_size

    print(f"input  : {args.image} ({len(data):,} bytes)")
    print(f"target : {part:,} bytes ({part/1024/1024:.0f} MiB partition)")

    if len(data) > part:
        print(f"[x] image is LARGER than partition ({len(data):,} > {part:,})",
              file=sys.stderr)
        return 1

    orig_len = len(data)

    if not args.no_avb:
        # Strip any pre-existing footer at the very end (already zero-padded
        # images may or may not have one).
        if len(data) >= AVB_FOOTER_SIZE and data[-AVB_FOOTER_SIZE:][:4] == AVB_FOOTER_MAGIC:
            print("[i] existing AVB footer found -- rewriting")
            data = data[:-AVB_FOOTER_SIZE]
            # keep original_image_size from the old footer? recompute instead

        # Footer goes immediately before the trailing 64 bytes of the partition.
        footer_off = part - AVB_FOOTER_SIZE

        # If the payload would overlap the footer slot, zero-fit first.
        if len(data) > footer_off:
            print(f"[!] payload {len(data):,} exceeds footer slot {footer_off:,}",
                  file=sys.stderr)
            return 1

        data += b"\x00" * (footer_off - len(data))
        footer = make_footer(orig_len, 0, 0)
        data += footer
        print(f"AVB footer: appended at 0x{footer_off:x}, "
              f"original_image_size={orig_len:,}")

    # zero-fill the remainder out to the full partition
    if len(data) < part:
        data += b"\x00" * (part - len(data))

    open(out_path, "wb").write(bytes(data))
    print(f"[ok] wrote {out_path}: {len(data):,} bytes "
          f"(= partition size: {len(data) == part})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
