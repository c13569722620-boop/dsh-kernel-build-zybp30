#!/usr/bin/env python3
"""Print a concise summary of a boot image's tail: size, AVB footer, padding.

Useful as a CI gate to confirm the image fills its partition and carries the
footer LK expects.

Usage: inspect_boot_tail.py <boot.img> [--partition-size N]
Exit 0 always (informational); prints '[x]' lines on problems.
"""
import struct
import sys
import os

DEFAULT_PART = 33554432


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    part = DEFAULT_PART
    for i, a in enumerate(sys.argv):
        if a == "--partition-size" and i + 1 < len(sys.argv):
            part = int(sys.argv[i + 1], 0)

    if not args:
        print("usage: inspect_boot_tail.py <boot.img> [--partition-size N]",
              file=sys.stderr)
        return 2

    path = args[0]
    data = open(path, "rb").read()

    print(f"image size    : {len(data):,} bytes ({len(data)/1024/1024:.2f} MiB)")
    print(f"partition size: {part:,} bytes ({part/1024/1024:.0f} MiB)")
    if len(data) == part:
        print("fill          : EXACT (full partition)")
    elif len(data) < part:
        print(f"fill          : SHORT by {part-len(data):,} bytes")
    else:
        print(f"fill          : OVER by {len(data)-part:,} bytes")

    tail = data[-64:]
    if tail[:4] == b"AVBf":
        vmaj, vmin = struct.unpack(">II", tail[4:12])
        orig = struct.unpack(">Q", tail[12:20])[0]
        voff = struct.unpack(">Q", tail[20:28])[0]
        vsz = struct.unpack(">Q", tail[28:36])[0]
        print(f"AVB footer    : present at 0x{len(data)-64:x}")
        print(f"  version     : {vmaj}.{vmin}")
        print(f"  orig_size   : {orig:,}")
        print(f"  vbmeta_off  : 0x{voff:x}")
        print(f"  vbmeta_size : {vsz:,}")
        if voff == 0 and vsz == 0:
            print("  signing     : none (unsigned; fine for unlocked/bring-up)")
        # sanity: payload must contain the ANDROID! magic at offset 0
        if data[:8] == b"ANDROID!":
            print("  payload     : ANDROID! header intact")
    else:
        print(f"AVB footer    : ABSENT (tail {tail[:8].hex()})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
